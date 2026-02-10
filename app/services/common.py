

"""
Common service functions for background job management and configuration propagation.
Handles the synchronization of DNS records, SSL certificates, and nginx configuration.
"""
import subprocess
import traceback
from requests import Session
from app.config import settings
from app.persistence import repos
from app.persistence.db import DBSession
from app.persistence.models import DnsRecord, Domain, GatewayConnection, GatewayProtocol, ManagedBy
from app.services.cloudflare import CloudFlareManager, CloudFlareOriginCAManager
from app.services.letsencrypt import LetsEncryptManager
from app.services.nginx import NginxConfigGenerator

# Global state for background job management
JOB_RUNNING = False
JOB_RESULT = None
UNSYNCED_CHANGES = False

def get_job_result():
    """
    Get the result of the last background job.
    Returns None if job is still running or no result available.
    """
    global JOB_RESULT

    if JOB_RUNNING:
        return

    r = JOB_RESULT
    JOB_RESULT = None
    return r

def background_publish():
    """
    Run the background publish job that synchronizes all configurations.
    - Generates nginx configuration
    - Syncs DNS records with Cloudflare
    - Manages SSL certificates
    - Reloads nginx if enabled
    """
    global JOB_RUNNING, JOB_RESULT, UNSYNCED_CHANGES

    
    if JOB_RUNNING:
        print("[background_publish] Job already running, skipping")
        return

    print("[background_publish] Starting background publish job...")
    JOB_RUNNING = True
    UNSYNCED_CHANGES = False
    
    try:
        with DBSession() as db:
            # Generate nginx configuration
            print(f"[background_publish] Generating nginx configuration (dry_run: {not settings.ENABLE_NGINX})")
            NginxConfigGenerator(db, dry_run=not settings.ENABLE_NGINX)

            # Sync DNS records with Cloudflare
            print(f"[background_publish] Syncing DNS records with Cloudflare (dry_run: {not settings.ENABLE_CLOUDFLARE})")
            cf_dns = CloudFlareManager(db, dry_run=not settings.ENABLE_CLOUDFLARE)
            cache = cf_dns.sync()

            # Manage SSL certificates from Cloudflare Origin CA
            print(f"[background_publish] Managing Cloudflare Origin CA certificates (dry_run: {not settings.ENABLE_CLOUDFLARE})")
            cf_ca = CloudFlareOriginCAManager(db, cache, dry_run=not settings.ENABLE_CLOUDFLARE)
            cf_ca.sync()

            # Manage Let's Encrypt SSL certificates
            print(f"[background_publish] Managing Let's Encrypt certificates (dry_run: {not settings.ENABLE_LETSENCRYPT})")
            le_mgr = LetsEncryptManager(db, dry_run=not settings.ENABLE_LETSENCRYPT)
            le_mgr.sync()

        # Reload nginx configuration if enabled
        if settings.ENABLE_NGINX:
            print(f"[background_publish] Reloading nginx with command: {settings.NGINX_RELOAD_CMD}")
            subprocess.run(settings.NGINX_RELOAD_CMD.split(" "), check=True)
        else:
            print("[background_publish] Nginx reload disabled, skipping")
            
        JOB_RESULT = "Publish job completed successfully."

    except Exception as e:
        JOB_RESULT = f"Publish job failed: {str(e)}"
        print(f"[background_publish] Job failed with error: {str(e)}")
        traceback.print_exc()

    finally:
        print("[background_publish] Job completed.")
        JOB_RUNNING = False



def propagate_changes(db: Session):
    """
    Automatically propagate changes based on gateway client configurations.
    Creates system-managed DNS records and gateway connections for origin servers.
    """
    global UNSYNCED_CHANGES
    
    print("[propagate_changes] Starting change propagation...")
    UNSYNCED_CHANGES = True

    origin_ips = []

    # Clear all system-managed records to rebuild them
    print("[propagate_changes] Clearing existing system-managed records...")
    repos.GatewayConnectionRepo(db).delete_all_managed_by(ManagedBy.SYSTEM)
    repos.DnsRecordRepo(db).delete_all_managed_by(ManagedBy.SYSTEM)

    # Get all stream routes to create proxy connections for them
    routes = repos.NginxRouteRepo(db).list_all_active()
    stream_routes = [r for r in routes if r.protocol == "STREAM"]
    stream_ports = []
    stream_route_details = []  # Store tuples of (port, subdomain, domain_id)
    
    for route in stream_routes:
        try:
            # Remove any leading slash and convert to integer
            port = route.path_prefix.lstrip('/')
            port = int(port)
            stream_ports.append(port)
            
            # Store route details for DNS entries
            stream_route_details.append((port, route.subdomain, route.domain_id))
        except (ValueError, AttributeError):
            # Skip routes with invalid port numbers
            print(f"[propagate_changes] Invalid port in stream route: {route.path_prefix}")
            continue

    # Process all gateway clients
    clients = repos.GatewayClientRepo(db).list_all()
    print(f"[propagate_changes] Processing {len(clients)} gateway clients...")

    created_dns_ids = []
    def apply_domain_proxy(domain: Domain, desired: bool) -> bool:
        if not domain.dns_proxy_enabled:
            return False
        return desired

    for client in clients:
        print(f"[propagate_changes] Processing client: {client.server.name} ({client.server.host}), is_origin: {client.is_origin}")
        if client.is_origin:
            # Create gateway connections for HTTP and HTTPS on origin servers
            conn_name = f"origin_{client.server.name}_80"
            repos.GatewayConnectionRepo(db).create(
                GatewayConnection(
                    name=conn_name,
                    client_id=client.id,
                    protocol=GatewayProtocol.TCP,
                    local_ip=settings.LOCAL_IP,
                    local_port=80,
                    remote_port=80,
                    managed_by=ManagedBy.SYSTEM,
                )
            )
            conn_name = f"origin_{client.server.name}_443"
            repos.GatewayConnectionRepo(db).create(
                GatewayConnection(
                    name=conn_name,
                    client_id=client.id,
                    protocol=GatewayProtocol.TCP,
                    local_ip=settings.LOCAL_IP,
                    local_port=443,
                    remote_port=443,
                    managed_by=ManagedBy.SYSTEM,
                )
            )
            
            # Create gateway connections for each STREAM route
            for port in stream_ports:
                conn_name = f"origin_{client.server.name}_{port}"
                print(f"[propagate_changes] Creating stream proxy connection: {conn_name} on port {port}")
                repos.GatewayConnectionRepo(db).create(
                    GatewayConnection(
                        name=conn_name,
                        client_id=client.id,
                        protocol=GatewayProtocol.TCP,
                        local_ip=settings.LOCAL_IP,
                        local_port=port,
                        remote_port=port,
                        managed_by=ManagedBy.SYSTEM,
                    )
                )
            
            # Create DNS entries for each stream route subdomain pointing to this origin server
            origin_ip = client.server.host
            for port, subdomain, domain_id in stream_route_details:
                domain = repos.DomainRepo(db).get(domain_id)
                if not domain:
                    continue
                    
                # Format the subdomain name for the DNS record
                dns_name = subdomain if subdomain != '@' else '@'
                dns_description = f"{subdomain}.{domain.name}" if subdomain != '@' else f"{domain.name}"
                
                print(f"[propagate_changes] Creating stream DNS entry: {dns_description} -> {origin_ip} (port {port})")
                
                # Check if the DNS record already exists
                exists_id = repos.DnsRecordRepo(db).exists(
                    domain_id=domain_id,
                    name=dns_name,
                    type="A",
                    content=origin_ip
                )
                
                if exists_id:
                    # Update the existing record
                    rec = repos.DnsRecordRepo(db).get(exists_id)
                    rec.proxied = False  # Direct connection to the origin
                    rec.managed_by = ManagedBy.SYSTEM
                    new_rec = repos.DnsRecordRepo(db).update(rec)
                    created_dns_ids.append(new_rec.id)
                    continue
                else:
                    # Create a new DNS record
                    new_rec = repos.DnsRecordRepo(db).create(
                        DnsRecord(
                            domain_id=domain_id,
                            name=dns_name,
                            type="A",
                            content=origin_ip,
                            proxied=False,  # Direct connection to the origin
                            managed_by=ManagedBy.SYSTEM,
                        )
                    )
                    created_dns_ids.append(new_rec.id)

            # Create direct DNS records for domains that support direct prefix
            origin_ip = client.server.host

            domains = repos.DomainRepo(db).list_all()
            
            for domain in domains:
                if domain.use_for_direct_prefix:
                    # Create or update direct subdomain DNS record
                    exists_id = repos.DnsRecordRepo(db).exists(
                        domain_id=domain.id,
                        name=f"{client.server.name}.direct",
                        type="A",
                    )
                    if exists_id:
                        rec = repos.DnsRecordRepo(db).get(exists_id)
                        rec.content = origin_ip
                        rec.proxied = False
                        rec.managed_by = ManagedBy.SYSTEM
                        new_rec = repos.DnsRecordRepo(db).update(rec)
                        created_dns_ids.append(new_rec.id)
                        continue

                    new_rec = repos.DnsRecordRepo(db).create(
                        DnsRecord(
                            domain_id=domain.id,
                            name=f"{client.server.name}.direct",
                            type="A",
                            content=origin_ip,
                            proxied=False,
                            managed_by=ManagedBy.SYSTEM,
                        )
                    )
                    created_dns_ids.append(new_rec.id)

            origin_ips.append(origin_ip)

    # # get all that arent in created_dns_ids and delete them
    # stale_dns_entries = repos.DnsRecordRepo(db).list_all_managed_by(ManagedBy.SYSTEM)
    # for entry in stale_dns_entries:
    #     if entry.id not in created_dns_ids:
    #         print(f"[propagate_changes] Deleting stale DNS entry: {entry.name} ({entry.content})")
    #         repos.DnsRecordRepo(db).delete(entry)

    # Create wildcard DNS records for multi-level subdomains
    print("[propagate_changes] Creating wildcard DNS records for multi-level subdomains...")
    subdomains = set()
    routes = repos.NginxRouteRepo(db).list_all()
    
    for route in routes:
        if not route.domain.auto_wildcard:
            continue

        # Track all subdomains for later wildcard generation
        subdomains.add((route.subdomain, route.domain.name))

        # Check if this is a multi-level subdomain (has child subdomains)
        is_multilevel = route.subdomain.count(".") > 0
        
        for other_route in repos.NginxRouteRepo(db).list_by_domain(route.domain_id):
            if other_route.subdomain != route.subdomain and other_route.subdomain.endswith(f".{route.subdomain}") and route.domain.use_for_direct_prefix:
                is_multilevel = True
                print(f"[propagate_changes] Found child subdomain {other_route.subdomain}, marking as multi-level")
                break

        if is_multilevel:
            # Create wildcard DNS record for the parent domain
            without_last = ".".join(route.subdomain.split(".")[1:])
            
            for ip in origin_ips:
                exists_id = repos.DnsRecordRepo(db).exists(
                    domain_id=route.domain.id,
                    name=f"*.{without_last}",
                    type="A",
                    content=ip
                )
                if exists_id:
                    rec = repos.DnsRecordRepo(db).get(exists_id)
                    rec.proxied = apply_domain_proxy(route.domain, True)
                    rec.managed_by = ManagedBy.SYSTEM
                    repos.DnsRecordRepo(db).update(rec)
                    continue
                repos.DnsRecordRepo(db).create(
                    DnsRecord(
                        domain_id=route.domain.id,
                        name=f"*.{without_last}",
                        type="A",
                        content=ip,
                        proxied=apply_domain_proxy(route.domain, True),
                        managed_by=ManagedBy.SYSTEM,
                    )
                )

    # Create root and wildcard DNS records for domains with auto-wildcard enabled
    print("[propagate_changes] Creating root and wildcard DNS records for auto-wildcard domains...")
    
    for domain in repos.DomainRepo(db).list_all():
        if not domain.auto_wildcard:
            continue

        print(f"[propagate_changes] Processing auto-wildcard domain: {domain.name}")
        
        for ip in origin_ips:
            # Create root domain DNS record if there's a root route
            if ("@", domain.name) in subdomains:
                exists_id = repos.DnsRecordRepo(db).exists(
                    domain_id=domain.id,
                    name=f"@",
                    type="A",
                    content=ip
                )
                if exists_id:
                    print(f"[propagate_changes] Updating existing root DNS record: {domain.name} -> {ip}")
                    rec = repos.DnsRecordRepo(db).get(exists_id)
                    rec.proxied = apply_domain_proxy(domain, True)
                    rec.managed_by = ManagedBy.SYSTEM
                    repos.DnsRecordRepo(db).update(rec)
                else:
                    print(f"[propagate_changes] Creating new root DNS record: {domain.name} -> {ip}")
                    repos.DnsRecordRepo(db).create(
                        DnsRecord(
                            domain_id=domain.id,
                            name=f"@",
                            type="A",
                            content=ip,
                            proxied=apply_domain_proxy(domain, True),
                            managed_by=ManagedBy.SYSTEM,
                        )
                    )

            # Create wildcard DNS record if there are any non-root subdomains
            if any(s for s in subdomains if s[0] != "@"):
                exists_id = repos.DnsRecordRepo(db).exists(
                    domain_id=domain.id,
                    name=f"*",
                    type="A",
                    content=ip
                )
                if exists_id:
                    print(f"[propagate_changes] Updating existing wildcard DNS record: *.{domain.name} -> {ip}")
                    rec = repos.DnsRecordRepo(db).get(exists_id)
                    rec.proxied = apply_domain_proxy(domain, True)
                    rec.managed_by = ManagedBy.SYSTEM
                    repos.DnsRecordRepo(db).update(rec)
                    continue
                
                print(f"[propagate_changes] Creating new wildcard DNS record: *.{domain.name} -> {ip}")
                repos.DnsRecordRepo(db).create(
                    DnsRecord(
                        domain_id=domain.id,
                        name=f"*",
                        type="A",
                        content=ip,
                        proxied=apply_domain_proxy(domain, True),
                        managed_by=ManagedBy.SYSTEM,
                    )
                )