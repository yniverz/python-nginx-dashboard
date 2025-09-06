

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
from app.persistence.models import DnsRecord, GatewayConnection, GatewayProtocol, ManagedBy
from app.services.cloudflare import CloudFlareManager, CloudFlareOriginCAManager
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
        return

    JOB_RUNNING = True
    UNSYNCED_CHANGES = False
    try:
        with DBSession() as db:
            # Generate nginx configuration
            NginxConfigGenerator(db, dry_run=not settings.ENABLE_NGINX)

            # Sync DNS records with Cloudflare
            cf_dns = CloudFlareManager(db, dry_run=not settings.ENABLE_CLOUDFLARE)
            cache = cf_dns.sync()

            # Manage SSL certificates
            cf_ca = CloudFlareOriginCAManager(db, cache, dry_run=not settings.ENABLE_CLOUDFLARE)
            cf_ca.sync()

        # Reload nginx configuration if enabled
        if settings.ENABLE_NGINX:
            subprocess.run(settings.NGINX_RELOAD_CMD.split(" "), check=True)
        JOB_RESULT = "Publish job completed successfully."

    except Exception as e:
        JOB_RESULT = f"Publish job failed: {str(e)}"
        traceback.print_exc()

    finally:
        JOB_RUNNING = False



def propagate_changes(db: Session):
    """
    Automatically propagate changes based on gateway client configurations.
    Creates system-managed DNS records and gateway connections for origin servers.
    """
    global UNSYNCED_CHANGES
    UNSYNCED_CHANGES = True

    origin_ips = []

    # Clear all system-managed records to rebuild them
    repos.GatewayConnectionRepo(db).delete_all_managed_by(ManagedBy.SYSTEM)
    repos.DnsRecordRepo(db).delete_all_managed_by(ManagedBy.SYSTEM)

    # Process all gateway clients
    for client in repos.GatewayClientRepo(db).list_all():
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

            # Create direct DNS records for domains that support direct prefix
            origin_ip = client.server.host

            for domain in repos.DomainRepo(db).list_all():
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
                        repos.DnsRecordRepo(db).update(rec)
                        continue

                    repos.DnsRecordRepo(db).create(
                        DnsRecord(
                            domain_id=domain.id,
                            name=f"{client.server.name}.direct",
                            type="A",
                            content=origin_ip,
                            proxied=False,
                            managed_by=ManagedBy.SYSTEM,
                        )
                    )

            origin_ips.append(origin_ip)

    # Create wildcard DNS records for multi-level subdomains
    subdomains = set()
    for route in repos.NginxRouteRepo(db).list_all():
        if not route.domain.auto_wildcard:
            continue

        # Track all subdomains for later wildcard generation
        subdomains.add((route.subdomain, route.domain.name))

        # Check if this is a multi-level subdomain (has child subdomains)
        is_multilevel = route.subdomain.count(".") > 0
        for other_route in repos.NginxRouteRepo(db).list_by_domain(route.domain_id):
            if other_route.subdomain != route.subdomain and other_route.subdomain.endswith(f".{route.subdomain}") and route.domain.use_for_direct_prefix:
                is_multilevel = True
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
                    rec.proxied = True
                    rec.managed_by = ManagedBy.SYSTEM
                    repos.DnsRecordRepo(db).update(rec)
                    continue
                repos.DnsRecordRepo(db).create(
                    DnsRecord(
                        domain_id=route.domain.id,
                        name=f"*.{without_last}",
                        type="A",
                        content=ip,
                        proxied=True,
                        managed_by=ManagedBy.SYSTEM,
                    )
                )

    # Create root and wildcard DNS records for domains with auto-wildcard enabled
    for domain in repos.DomainRepo(db).list_all():
        if not domain.auto_wildcard:
            continue

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
                    rec = repos.DnsRecordRepo(db).get(exists_id)
                    rec.proxied = True
                    rec.managed_by = ManagedBy.SYSTEM
                    repos.DnsRecordRepo(db).update(rec)
                else:
                    repos.DnsRecordRepo(db).create(
                        DnsRecord(
                            domain_id=domain.id,
                            name=f"@",
                            type="A",
                            content=ip,
                            proxied=True,
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
                    rec = repos.DnsRecordRepo(db).get(exists_id)
                    rec.proxied = True
                    rec.managed_by = ManagedBy.SYSTEM
                    repos.DnsRecordRepo(db).update(rec)
                    continue
                
                repos.DnsRecordRepo(db).create(
                    DnsRecord(
                        domain_id=domain.id,
                        name=f"*",
                        type="A",
                        content=ip,
                        proxied=True,
                        managed_by=ManagedBy.SYSTEM,
                    )
                )