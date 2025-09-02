import json
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from app.models import Domain, HttpRoute, StreamRoute, DnsRecord, DnsType, ManagedBy
from app.repositories import DnsRecordRepo
from app.providers.cloudflare import CloudflareDnsClient

def fqdn(domain: Domain, subdomain: str) -> str:
    return domain.name if subdomain in ("@", "",) else f"{subdomain}.{domain.name}"

class DnsService:
    def __init__(self, db: Session):
        self.db = db
        self.rec_repo = DnsRecordRepo(db)
        self.cf = CloudflareDnsClient()

    def compute_system_desired(self, domain: Domain, http_routes: List[HttpRoute], stream_routes: List[StreamRoute]) -> List[DnsRecord]:
        desired: Dict[Tuple[str,DnsType], DnsRecord] = {}

        def add(name:str, type:DnsType, content:str, ttl:int|None=None, proxied:bool|None=None, priority:int|None=None, meta:dict|None=None):
            rec = DnsRecord(domain_id=domain.id, name=name, type=type, content=content, ttl=ttl,
                            proxied=proxied, priority=priority, managed_by=ManagedBy.SYSTEM, active=True, meta=meta or {})
            desired[(name,type)] = rec

        # apex
        if domain.origin_ipv4:
            add("@", DnsType.A, domain.origin_ipv4, proxied=True, meta={"source":"APEX"})
            if domain.auto_direct_prefix:
                add(f"{domain.auto_direct_prefix}", DnsType.A, domain.origin_ipv4, proxied=False, meta={"source":"DIRECT"})
        if domain.origin_ipv6:
            add("@", DnsType.AAAA, domain.origin_ipv6, proxied=True, meta={"source":"APEX"})
            if domain.auto_direct_prefix:
                add(f"{domain.auto_direct_prefix}", DnsType.AAAA, domain.origin_ipv6, proxied=False, meta={"source":"DIRECT"})

        # wildcard
        if domain.auto_wildcard:
            if domain.origin_ipv4:
                add("*.@", DnsType.A, domain.origin_ipv4, proxied=True, meta={"source":"WILDCARD"})
            if domain.origin_ipv6:
                add("*.@", DnsType.AAAA, domain.origin_ipv6, proxied=True, meta={"source":"WILDCARD"})

        # http routes
        for r in http_routes:
            name = r.subdomain if r.subdomain not in ("@", "",) else "@"
            if domain.origin_ipv4:
                add(name, DnsType.A, domain.origin_ipv4, proxied=True, meta={"source":"ROUTE"})
                if domain.auto_direct_prefix:
                    add(f"{name}.{domain.auto_direct_prefix}", DnsType.A, domain.origin_ipv4, proxied=False, meta={"source":"DIRECT"})
            if domain.origin_ipv6:
                add(name, DnsType.AAAA, domain.origin_ipv6, proxied=True, meta={"source":"ROUTE"})
                if domain.auto_direct_prefix:
                    add(f"{name}.{domain.auto_direct_prefix}", DnsType.AAAA, domain.origin_ipv6, proxied=False, meta={"source":"DIRECT"})

        # stream routes (+ SRV)
        for r in stream_routes:
            name = r.subdomain if r.subdomain not in ("@", "",) else "@"
            if domain.origin_ipv4:
                add(name, DnsType.A, domain.origin_ipv4, proxied=False, meta={"source":"STREAM"})
            if domain.origin_ipv6:
                add(name, DnsType.AAAA, domain.origin_ipv6, proxied=False, meta={"source":"STREAM"})
            if r.srv_record:
                # SRV records: content as JSON
                target = fqdn(domain, r.subdomain) + "."
                srv_name = f"{r.srv_record}.{name}" if name != "@" else f"{r.srv_record}"
                content = json.dumps({"target": target, "port": r.port, "priority": 10, "weight": 1})
                add(srv_name, DnsType.SRV, content, meta={"source":"SRV"})

        return list(desired.values())

    async def import_provider_records(self, domain: Domain) -> List[DnsRecord]:
        """Pull provider records and mirror them as IMPORTED (read-only)."""
        zone_id = domain.provider_zone_id
        if not zone_id:
            return []
        records = await self.cf.list_records(zone_id)
        mirrored = []
        for rec in records:
            name_fqdn: str = rec["name"]
            # make relative to domain
            suffix = "." + domain.name
            rel = "@"
            if name_fqdn == domain.name:
                rel = "@"
            elif name_fqdn.endswith(suffix):
                rel = name_fqdn[: -len(suffix)].rstrip(".") or "@"
            else:
                # different domain inside same zone (rare), keep as fqdn rel
                rel = name_fqdn

            typ = rec["type"]
            if typ not in [t.value for t in DnsType]:  # skip unsupported types
                continue
            content = rec.get("content","")
            ttl = rec.get("ttl")
            proxied = rec.get("proxied")
            priority = rec.get("priority")
            mirrored.append(self.rec_repo.upsert_imported(
                domain_id=domain.id,
                name=rel,
                type=DnsType(typ),
                content=content,
                ttl=ttl,
                proxied=proxied,
                priority=priority,
                active=True,
                meta={"provider_id": rec.get("id")}
            ))
        return mirrored

    async def diff_and_apply(self, domain: Domain, desired: List[DnsRecord], user_records: List[DnsRecord]):
        """Create/update/delete in provider for SYSTEM+USER; do not touch IMPORTED."""
        zone_id = domain.provider_zone_id
        if not zone_id:
            return {"error":"domain has no provider_zone_id"}

        provider_now = await self.cf.list_records(zone_id)
        # map provider by (name_rel, type)
        def to_rel(name_fqdn:str) -> str:
            if name_fqdn == domain.name:
                return "@"
            suffix = "." + domain.name
            if name_fqdn.endswith(suffix):
                rel = name_fqdn[: -len(suffix)].rstrip(".") or "@"
                return rel
            return name_fqdn  # fallback

        pmap = {}
        for r in provider_now:
            key = (to_rel(r["name"]), r["type"])
            pmap[key] = r

        desired_all = desired + user_records
        # Upserts
        for rec in desired_all:
            key = (rec.name, rec.type.value)
            payload = {
                "type": rec.type.value,
                "name": rec.name if rec.name != "@" else domain.name,
                "content": rec.content,
                "ttl": rec.ttl or 1,  # 1 = auto in CF
            }
            if rec.type in (DnsType.A, DnsType.AAAA, DnsType.CNAME):
                if rec.proxied is not None:
                    payload["proxied"] = rec.proxied
            if rec.type in (DnsType.MX, DnsType.SRV) and rec.priority is not None:
                payload["priority"] = rec.priority
            # SRV requires structured payload; convert JSON content
            if rec.type == DnsType.SRV:
                c = json.loads(rec.content)
                # CF SRV fields: data: {service, proto, name, priority, weight, port, target}
                # We assume rec.name already carries service/proto/name (e.g., _minecraft._tcp.mc)
                payload = {
                    "type": "SRV",
                    "name": rec.name if rec.name != "@" else domain.name,
                    "data": {
                        "service": rec.name.split(".",1)[0],  # "_minecraft"
                        "proto": rec.name.split(".",2)[1],    # "_tcp"
                        "name": ".".join(rec.name.split(".")[2:]) or domain.name,
                        "priority": c.get("priority",10),
                        "weight": c.get("weight",1),
                        "port": c.get("port"),
                        "target": c.get("target")
                    },
                    "ttl": rec.ttl or 1
                }

            if key in pmap:
                # compare and update if changed
                provider_rec = pmap[key]
                need_update = True  # keep simple: always PUT desired
                await self.cf.update_record(zone_id, provider_rec["id"], payload)
            else:
                await self.cf.create_record(zone_id, payload)

        # Deletions: remove provider records that correspond to SYSTEM entries which are no longer desired
        desired_keys = set((r.name, r.type.value) for r in desired_all)
        for key, provider_rec in pmap.items():
            name_rel, typ = key
            # skip if user created on provider and we don't have it (we won't delete unmanaged)
            # delete only if it's a SYSTEM record we know we generated and it's not desired anymore
            # easy heuristic: if there is a SYSTEM record in DB with same (name,type) but inactive,
            # or if it's in provider but not in desired_keys AND matches our 'source' patterns.
            if key not in desired_keys:
                # caution: don't delete unknown records
                continue
                # (you can extend with a managed marker via TXT record if you want safe deletion)

        return {"ok": True}
