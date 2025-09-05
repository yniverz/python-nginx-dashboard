from typing import Sequence
from sqlalchemy import and_, select, delete
from sqlalchemy.orm import Session
from app.persistence.models import (
    DnsRecordArchive, Domain, NginxRoute,
    DnsRecord, ManagedBy,
    GatewayServer, GatewayClient, GatewayConnection
)
from sqlalchemy.orm import selectinload

class DomainRepo:
    def __init__(self, db: Session): self.db = db
    def list_all(self) -> list[Domain]:
        return list(self.db.scalars(select(Domain).order_by(Domain.name)))
    def get(self, id: int) -> Domain | None:
        return self.db.get(Domain, id)
    def by_name(self, name: str) -> Domain | None:
        return self.db.scalar(select(Domain).where(Domain.name==name))
    def create(self, d: Domain) -> Domain:
        self.db.add(d); self.db.commit(); self.db.refresh(d); return d
    def update(self, d: Domain) -> Domain:
        self.db.add(d); self.db.commit(); self.db.refresh(d); return d
    def delete(self, id: int) -> None:
        obj = self.get(id); 
        if obj: self.db.delete(obj); self.db.commit()

class GatewayServerRepo:
    def __init__(self, db: Session): self.db = db
    def list_all(self) -> list[GatewayServer]:
        return list(self.db.scalars(select(GatewayServer).order_by(GatewayServer.name)))
    def get(self, id: int) -> GatewayServer | None:
        return self.db.get(GatewayServer, id)
    def by_name(self, name: str) -> GatewayServer | None:
        return self.db.scalar(select(GatewayServer).where(GatewayServer.name==name))
    def create(self, g: GatewayServer) -> GatewayServer:
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    def update(self, g: GatewayServer) -> GatewayServer:
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    def delete(self, id: int) -> None:
        obj = self.get(id);
        if obj: self.db.delete(obj); self.db.commit()


class GatewayClientRepo:
    def __init__(self, db: Session): self.db = db
    def list_all(self) -> list[GatewayClient]:
        return list(self.db.scalars(select(GatewayClient).order_by(GatewayClient.name)))
    def get(self, id: int) -> GatewayClient | None:
        return self.db.get(GatewayClient, id)
    def by_name(self, name: str) -> GatewayClient | None:
        return self.db.scalar(select(GatewayClient).where(GatewayClient.name==name))
    def create(self, g: GatewayClient) -> GatewayClient:
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    def update(self, g: GatewayClient) -> GatewayClient:
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    def delete(self, id: int) -> None:
        obj = self.get(id);
        if obj: self.db.delete(obj); self.db.commit()

class GatewayConnectionRepo:
    def __init__(self, db: Session): self.db = db
    def list_all(self) -> list[GatewayConnection]:
        return list(self.db.scalars(select(GatewayConnection).order_by(GatewayConnection.name)))
    def list_by_client_id(self, client_id: int) -> list[GatewayConnection]:
        return list(self.db.scalars(select(GatewayConnection).where(GatewayConnection.client_id==client_id)))
    def get(self, id: int) -> GatewayConnection | None:
        return self.db.get(GatewayConnection, id)
    def by_name(self, name: str) -> GatewayConnection | None:
        return self.db.scalar(select(GatewayConnection).where(GatewayConnection.name==name))
    def create(self, g: GatewayConnection) -> GatewayConnection:
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    def update(self, g: GatewayConnection) -> GatewayConnection:
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    def delete(self, id: int) -> None:
        obj = self.get(id);
        if obj: self.db.delete(obj); self.db.commit()
    def delete_all_managed_by(self, managed_by: ManagedBy) -> None:
        self.db.execute(delete(GatewayConnection).where(GatewayConnection.managed_by==managed_by))
        self.db.commit()

class NginxRouteRepo:
    def __init__(self, db: Session): self.db = db
    def list_all(self) -> list[NginxRoute]:
        return list(self.db.scalars(select(NginxRoute).options(selectinload(NginxRoute.hosts))))
    def list_all_active(self) -> list[NginxRoute]:
        return list(self.db.scalars(select(NginxRoute).where(NginxRoute.active==True).options(selectinload(NginxRoute.hosts))))
    def list_by_domain(self, domain_id: int) -> list[NginxRoute]:
        return list(self.db.scalars(select(NginxRoute).where(NginxRoute.domain_id==domain_id).options(selectinload(NginxRoute.hosts))))
    def get(self, id: int) -> NginxRoute | None:
        return self.db.get(NginxRoute, id)
    def exists_with_domain_id(self, domain_id: int) -> bool:
        return self.db.scalar(select(NginxRoute).where(NginxRoute.domain_id==domain_id)) is not None
    def update(self, r: NginxRoute) -> NginxRoute:
        self.db.add(r); self.db.commit(); self.db.refresh(r); return r
    def create(self, r: NginxRoute) -> NginxRoute:
        self.db.add(r); self.db.commit(); self.db.refresh(r); return r
    def delete(self, id: int) -> None:
        obj = self.db.get(NginxRoute, id)
        if obj is not None:
            self.db.delete(obj)
            self.db.commit()

class DnsRecordRepo:
    def __init__(self, db: Session): self.db = db
    def list_user(self, domain_id: int) -> list[DnsRecord]:
        return list(self.db.scalars(select(DnsRecord).where(
            DnsRecord.domain_id==domain_id, DnsRecord.managed_by==ManagedBy.USER)))
    def list_all(self, include: Sequence[ManagedBy] | None = None) -> list[DnsRecord]:
        if include:
            return list(self.db.scalars(select(DnsRecord).where(DnsRecord.managed_by.in_(include))))
        return list(self.db.scalars(select(DnsRecord)))
    def list_by_domain(self, domain_id: int, include: Sequence[ManagedBy] | None = None) -> list[DnsRecord]:
        if include:
            return list(self.db.scalars(select(DnsRecord).where(DnsRecord.domain_id==domain_id, DnsRecord.managed_by.in_(include))))
        return list(self.db.scalars(select(DnsRecord).where(DnsRecord.domain_id==domain_id)))
    def get(self, id: int) -> DnsRecord | None:
        return self.db.get(DnsRecord, id)
    def exists(self, domain_id: int, name: str, type: str, content: str | None = None) -> int | None:
        conditions = [
            DnsRecord.domain_id == domain_id,
            DnsRecord.name == name,
            DnsRecord.type == type,
        ]
        if content is not None:
            conditions.append(DnsRecord.content == content)

        return self.db.scalar(select(DnsRecord.id).where(and_(*conditions)))
    def create(self, rec: DnsRecord) -> DnsRecord:
        archive = self.db.scalar(select(DnsRecordArchive).where(
            DnsRecordArchive.name==rec.name,
            DnsRecordArchive.type==rec.type,
            DnsRecordArchive.content==rec.content
        ))
        if archive:
            self.db.delete(archive)

        self.db.add(rec); self.db.commit(); self.db.refresh(rec); return rec
    # def update(self, rec: DnsRecord) -> DnsRecord:
    #     old = self.get(rec.id)
    #     if old and (old.name != rec.name or old.type != rec.type or old.content != rec.content or old.ttl != rec.ttl or old.proxied != rec.proxied):
    #         archive = DnsRecordArchive.from_dns_record(old)
    #         self.db.add(archive)
    #     self.db.add(rec); self.db.commit(); self.db.refresh(rec); return rec
    def update(self, rec: DnsRecord) -> DnsRecord:
        # 1) Load the persistent instance
        db_obj = self.db.get(DnsRecord, rec.id)
        if db_obj is None:
            raise ValueError(f"DnsRecord {rec.id} not found")

        # 2) Compare BEFORE mutating the persistent object
        changed = (
            db_obj.name    != rec.name or
            db_obj.type    != rec.type or
            db_obj.content != rec.content or
            db_obj.ttl     != rec.ttl or
            db_obj.proxied != rec.proxied
        )
        print(f"DNS Record {db_obj.id} changed: {changed}")

        # 3) Archive the current persisted state if anything changed
        if changed:
            archive = DnsRecordArchive.from_dns_record(db_obj)
            self.db.add(archive)

        # 4) Apply incoming values to the managed instance
        db_obj.name    = rec.name
        db_obj.type    = rec.type
        db_obj.content = rec.content
        db_obj.ttl     = rec.ttl
        db_obj.proxied = rec.proxied

        # 5) Commit and return the managed instance
        self.db.commit()
        self.db.refresh(db_obj)
        return db_obj

    def delete(self, id: int) -> None:
        obj = self.get(id)
        if obj:
            archive = DnsRecordArchive.from_dns_record(obj)
            self.db.add(archive)
            self.db.delete(obj)
            self.db.commit()
    def delete_all_with_domain_id(self, domain_id: int) -> None:
        self.db.add_all([DnsRecordArchive.from_dns_record(rec) for rec in self.list_by_domain(domain_id)])
        self.db.execute(delete(DnsRecord).where(DnsRecord.domain_id==domain_id))
        self.db.commit()
    def delete_all_managed_by(self, managed_by: ManagedBy) -> None:
        self.db.add_all([DnsRecordArchive.from_dns_record(rec) for rec in self.list_all(include=[managed_by])])
        self.db.execute(delete(DnsRecord).where(DnsRecord.managed_by==managed_by)); self.db.commit()


    def list_archived(self) -> list[DnsRecordArchive]:
        return list(self.db.scalars(select(DnsRecordArchive)))
    def delete_archived(self, id: int) -> None:
        obj = self.db.get(DnsRecordArchive, id)
        if obj:
            self.db.delete(obj)
            self.db.commit()