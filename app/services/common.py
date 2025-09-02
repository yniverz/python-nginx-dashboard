



from fastapi import Depends
from requests import Session

from app.config import settings
from app.persistence import repos
from app.persistence.db import get_db
from app.persistence.models import DnsRecord, GatewayConnection, GatewayProtocol, ManagedBy


def propagate_changes(db: Session):
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
                    exists = repos.DnsRecordRepo(db).exists(
                        domain_id=domain.id,
                        name=f"{client.server.name}.direct",
                        type="A",
                    )
                    if exists:
                        exists.content = origin_ip
                        exists.proxied = False
                        exists.managed_by = ManagedBy.SYSTEM
                        repos.DnsRecordRepo(db).update(exists)
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

    for route in repos.NginxRouteRepo(db).list_all():
        # multilevel if any subdomain exists with more subdomains than this one, so if this one is "a" then it is multilevel if another one with "b.a" exists
        # or if it is "b.a" and one exists with "c.b.a"
        is_multilevel = False
        for other_route in repos.NginxRouteRepo(db).list_by_domain(route.domain_id):
            if other_route.subdomain != route.subdomain and other_route.subdomain.endswith(f".{route.subdomain}") and route.domain.use_for_direct_prefix:
                is_multilevel = True
                break

        if is_multilevel:
            for ip in origin_ips:
                repos.DnsRecordRepo(db).create(
                    DnsRecord(
                        domain_id=route.domain.id,
                        name=f"*.{route.subdomain}",
                        type="A",
                        content=ip,
                        proxied=True,
                        managed_by=ManagedBy.SYSTEM,
                    )
                )

    for domain in repos.DomainRepo(db).list_all():
        for ip in origin_ips:
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
            if domain.use_for_direct_prefix:
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