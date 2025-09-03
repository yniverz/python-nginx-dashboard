



import subprocess
import traceback
from requests import Session
from app.config import settings
from app.persistence import repos
from app.persistence.db import DBSession
from app.persistence.models import DnsRecord, GatewayConnection, GatewayProtocol, ManagedBy
from app.services.cloudflare import CloudFlareManager, CloudFlareOriginCAManager
from app.services.nginx import NginxConfigGenerator



JOB_RUNNING = False
JOB_RESULT = None
UNSYNCED_CHANGES = False

def get_job_result():
    global JOB_RESULT

    if JOB_RUNNING:
        return

    r = JOB_RESULT
    JOB_RESULT = None
    return r

def background_publish():
    global JOB_RUNNING, JOB_RESULT, UNSYNCED_CHANGES

    if JOB_RUNNING:
        return

    JOB_RUNNING = True
    UNSYNCED_CHANGES = False
    try:
        with DBSession() as db:
            NginxConfigGenerator(db, dry_run=not settings.ENABLE_NGINX)

            cf_dns = CloudFlareManager(db, dry_run=not settings.ENABLE_CLOUDFLARE)
            cache = cf_dns.sync()

            cf_ca = CloudFlareOriginCAManager(db, cache, dry_run=not settings.ENABLE_CLOUDFLARE)
            cf_ca.sync()

        if settings.ENABLE_NGINX:
            subprocess.run(settings.NGINX_RELOAD_CMD.split(" "), check=True)
        JOB_RESULT = "Publish job completed successfully."

    except Exception as e:
        JOB_RESULT = f"Publish job failed: {str(e)}"
        traceback.print_exc()

    finally:
        JOB_RUNNING = False



def propagate_changes(db: Session):
    global UNSYNCED_CHANGES
    UNSYNCED_CHANGES = True

    # Propagator:
    # For every proxy client
    # - Is origin?
    #     - Create proxy connection to 80 and 443


    origin_ips = []

    repos.GatewayConnectionRepo(db).delete_all_managed_by(ManagedBy.SYSTEM)
    repos.DnsRecordRepo(db).delete_all_managed_by(ManagedBy.SYSTEM)

    for client in repos.GatewayClientRepo(db).list_all():
        if client.is_origin:
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

            # For every domain
            # - Use for direct?
            #     - Ensure dns entry proxy_server_name.direct.domain managed by SYSTEM, proxy off

            origin_ip = client.server.host

            for domain in repos.DomainRepo(db).list_all():
                if domain.use_for_direct_prefix:
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

    # For every route (@ is root)
    # - Is multilevel subdomain?
    #     - Ensure dns records for each origin ip Managed by SYSTEM, proxy on

    subdomains = set()
    for route in repos.NginxRouteRepo(db).list_all():
        # multilevel if any subdomain exists with more subdomains than this one, so if this one is "a" then it is multilevel if another one with "b.a" exists
        # or if it is "b.a" and one exists with "c.b.a"
        subdomains.add((route.subdomain, route.domain.name))

        is_multilevel = route.subdomain.count(".") > 0
        for other_route in repos.NginxRouteRepo(db).list_by_domain(route.domain_id):
            if other_route.subdomain != route.subdomain and other_route.subdomain.endswith(f".{route.subdomain}") and route.domain.use_for_direct_prefix:
                is_multilevel = True
                break

        if is_multilevel:
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

    for domain in repos.DomainRepo(db).list_all():
        for ip in origin_ips:
            # if any subdomain == @ for this domain exists
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