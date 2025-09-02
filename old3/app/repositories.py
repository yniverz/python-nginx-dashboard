from typing import Iterable, List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session
from app.models import *

class RepoBase:
    def __init__(self, db: Session): self.db = db

class ProviderRepo(RepoBase):
    def create(self, **data) -> DnsProviderAccount:
        acc = DnsProviderAccount(**data); self.db.add(acc); self.db.commit(); self.db.refresh(acc); return acc
    def list(self) -> list[DnsProviderAccount]:
        return self.db.execute(select(DnsProviderAccount)).scalars().all()

class DomainRepo(RepoBase):
    def create(self, **data) -> Domain:
        dom = Domain(**data); self.db.add(dom); self.db.commit(); self.db.refresh(dom); return dom
    def list(self) -> list[Domain]:
        return self.db.execute(select(Domain)).scalars().all()
    def get(self, id: int) -> Optional[Domain]:
        return self.db.get(Domain, id)
    def update(self, id:int, **data) -> Domain:
        self.db.execute(update(Domain).where(Domain.id==id).values(**data)); self.db.commit(); return self.get(id)
    def delete(self, id: int):
        self.db.execute(delete(Domain).where(Domain.id==id)); self.db.commit()

class HttpRouteRepo(RepoBase):
    def create(self, **data) -> HttpRoute:
        r = HttpRoute(**data); self.db.add(r); self.db.commit(); self.db.refresh(r); return r
    def list_by_domain(self, domain_id:int) -> list[HttpRoute]:
        return self.db.execute(select(HttpRoute).where(HttpRoute.domain_id==domain_id)).scalars().all()
    def list_all(self) -> list[HttpRoute]:
        return self.db.execute(select(HttpRoute)).scalars().all()
    def delete(self, id:int): self.db.execute(delete(HttpRoute).where(HttpRoute.id==id)); self.db.commit()

class StreamRouteRepo(RepoBase):
    def create(self, **data) -> StreamRoute:
        r = StreamRoute(**data); self.db.add(r); self.db.commit(); self.db.refresh(r); return r
    def list_by_domain(self, domain_id:int) -> list[StreamRoute]:
        return self.db.execute(select(StreamRoute).where(StreamRoute.domain_id==domain_id)).scalars().all()
    def list_all(self) -> list[StreamRoute]:
        return self.db.execute(select(StreamRoute)).scalars().all()
    def delete(self, id:int): self.db.execute(delete(StreamRoute).where(StreamRoute.id==id)); self.db.commit()

class DnsRecordRepo(RepoBase):
    def create_user(self, **data) -> DnsRecord:
        rec = DnsRecord(**data, managed_by=ManagedBy.USER); self.db.add(rec); self.db.commit(); self.db.refresh(rec); return rec
    def upsert_imported(self, domain_id:int, name:str, type:DnsType, content:str, **rest) -> DnsRecord:
        existing = self.db.execute(select(DnsRecord).where(
            DnsRecord.domain_id==domain_id, DnsRecord.name==name, DnsRecord.type==type
        )).scalar_one_or_none()
        if existing:
            existing.content = content
            for k,v in rest.items(): setattr(existing,k,v)
            existing.managed_by = ManagedBy.IMPORTED
        else:
            existing = DnsRecord(domain_id=domain_id, name=name, type=type, content=content,
                                 managed_by=ManagedBy.IMPORTED, **rest)
            self.db.add(existing)
        self.db.commit(); self.db.refresh(existing); return existing
    def list(self, domain_id:int, include:Optional[list[ManagedBy]]=None, active_only=True) -> list[DnsRecord]:
        stmt = select(DnsRecord).where(DnsRecord.domain_id==domain_id)
        if include:
            stmt = stmt.where(DnsRecord.managed_by.in_(include))
        if active_only:
            stmt = stmt.where(DnsRecord.active==True)
        return self.db.execute(stmt).scalars().all()
    def delete_user(self, id:int):
        self.db.execute(delete(DnsRecord).where(DnsRecord.id==id, DnsRecord.managed_by==ManagedBy.USER)); self.db.commit()
