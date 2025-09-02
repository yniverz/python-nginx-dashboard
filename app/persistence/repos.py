from typing import Sequence
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.persistence.models import (
    Domain, NginxRoute,
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
    def exists(self, domain_id: int, name: str, type: str) -> DnsRecord | None:
        return self.db.scalar(select(DnsRecord).where(
            DnsRecord.domain_id==domain_id,
            DnsRecord.name==name,
            DnsRecord.type==type
        ))
    def create(self, rec: DnsRecord) -> DnsRecord:
        self.db.add(rec); self.db.commit(); self.db.refresh(rec); return rec
    def update(self, rec: DnsRecord) -> DnsRecord:
        self.db.add(rec); self.db.commit(); self.db.refresh(rec); return rec
    def delete(self, id: int) -> None:
        obj = self.get(id)
        if obj:
            self.db.delete(obj)
            self.db.commit()
    def upsert_user(self, rec: DnsRecord) -> DnsRecord:
        self.db.add(rec); self.db.commit(); self.db.refresh(rec); return rec
    def delete_user(self, id: int) -> None:
        self.db.execute(delete(DnsRecord).where(DnsRecord.id==id, DnsRecord.managed_by==ManagedBy.USER)); self.db.commit()
    def delete_all_managed_by(self, managed_by: ManagedBy) -> None:
        self.db.execute(delete(DnsRecord).where(DnsRecord.managed_by==managed_by)); self.db.commit()
