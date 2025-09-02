from sqlalchemy.orm import Session
from typing import Dict, List
from app.models import Domain, HttpRoute, StreamRoute, DnsRecord, ManagedBy
from app.repositories import DomainRepo, HttpRouteRepo, StreamRouteRepo, DnsRecordRepo
from app.services.nginx import NginxService
from app.services.dns import DnsService
from app.services.certs import CertService

class Reconciler:
    def __init__(self, db: Session):
        self.db = db
        self.dom_repo = DomainRepo(db)
        self.http_repo = HttpRouteRepo(db)
        self.stream_repo = StreamRouteRepo(db)
        self.dns_repo = DnsRecordRepo(db)
        self.nginx = NginxService()
        self.dns = DnsService(db)
        self.certs = CertService(db)

    async def reconcile(self, domain_id: int|None=None):
        # gather domains
        domains = [self.dom_repo.get(domain_id)] if domain_id else self.dom_repo.list()
        domains = [d for d in domains if d]

        # ensure certs first (Origin CA) per domain
        certs = {}
        for d in domains:
            bundle = await self.certs.ensure_origin_ca(d)
            certs[d.id] = bundle

        # render nginx configs
        routes_http: Dict[int, List[HttpRoute]] = {d.id: self.http_repo.list_by_domain(d.id) for d in domains}
        routes_stream: Dict[int, List[StreamRoute]] = {d.id: self.stream_repo.list_by_domain(d.id) for d in domains}

        http_conf = self.nginx.render_http(domains, routes_http, certs)
        stream_conf = self.nginx.render_stream(domains, routes_stream)
        self.nginx.write_and_reload(http_conf, stream_conf)

        # DNS: compute desired + apply
        for d in domains:
            desired_sys = self.dns.compute_system_desired(d, routes_http[d.id], routes_stream[d.id])
            user = self.dns_repo.list(d.id, include=[ManagedBy.USER], active_only=True)
            await self.dns.diff_and_apply(d, desired_sys, user)
