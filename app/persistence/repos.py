"""
Repository classes for database operations.
Provides a clean interface for CRUD operations on all database models.
"""
from typing import Sequence
from sqlalchemy import and_, inspect, select, delete
from sqlalchemy.orm import Session
from app.persistence.models import (
    DnsRecordArchive, Domain, NginxRoute,
    DnsRecord, ManagedBy,
    GatewayServer, GatewayClient, GatewayConnection
)
from sqlalchemy.orm import selectinload

class DomainRepo:
    """Repository for Domain model operations."""
    def __init__(self, db: Session): 
        self.db = db
    
    def list_all(self) -> list[Domain]:
        """Get all domains ordered by name."""
        return list(self.db.scalars(select(Domain).order_by(Domain.name)))
    
    def get(self, id: int) -> Domain | None:
        """Get domain by ID."""
        return self.db.get(Domain, id)
    
    def by_name(self, name: str) -> Domain | None:
        """Get domain by name."""
        return self.db.scalar(select(Domain).where(Domain.name==name))
    
    def create(self, d: Domain) -> Domain:
        """Create a new domain."""
        self.db.add(d); self.db.commit(); self.db.refresh(d); return d
    
    def update(self, d: Domain) -> Domain:
        """Update an existing domain."""
        self.db.add(d); self.db.commit(); self.db.refresh(d); return d
    
    def delete(self, id: int) -> None:
        """Delete a domain by ID."""
        obj = self.get(id); 
        if obj: self.db.delete(obj); self.db.commit()

class GatewayServerRepo:
    """Repository for GatewayServer model operations."""
    def __init__(self, db: Session): 
        self.db = db
    
    def list_all(self) -> list[GatewayServer]:
        """Get all gateway servers ordered by name."""
        return list(self.db.scalars(select(GatewayServer).order_by(GatewayServer.name)))
    
    def get(self, id: int) -> GatewayServer | None:
        """Get gateway server by ID."""
        return self.db.get(GatewayServer, id)
    
    def by_name(self, name: str) -> GatewayServer | None:
        """Get gateway server by name."""
        return self.db.scalar(select(GatewayServer).where(GatewayServer.name==name))
    
    def create(self, g: GatewayServer) -> GatewayServer:
        """Create a new gateway server."""
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    
    def update(self, g: GatewayServer) -> GatewayServer:
        """Update an existing gateway server."""
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    
    def delete(self, id: int) -> None:
        """Delete a gateway server by ID."""
        obj = self.get(id);
        if obj: self.db.delete(obj); self.db.commit()


class GatewayClientRepo:
    """Repository for GatewayClient model operations."""
    def __init__(self, db: Session): 
        self.db = db
    
    def list_all(self) -> list[GatewayClient]:
        """Get all gateway clients ordered by name."""
        return list(self.db.scalars(select(GatewayClient).order_by(GatewayClient.name)))
    
    def get(self, id: int) -> GatewayClient | None:
        """Get gateway client by ID."""
        return self.db.get(GatewayClient, id)
    
    def by_name(self, name: str) -> GatewayClient | None:
        """Get gateway client by name."""
        return self.db.scalar(select(GatewayClient).where(GatewayClient.name==name))
    
    def create(self, g: GatewayClient) -> GatewayClient:
        """Create a new gateway client."""
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    
    def update(self, g: GatewayClient) -> GatewayClient:
        """Update an existing gateway client."""
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    
    def delete(self, id: int) -> None:
        """Delete a gateway client by ID."""
        obj = self.get(id);
        if obj: self.db.delete(obj); self.db.commit()

class GatewayConnectionRepo:
    """Repository for GatewayConnection model operations."""
    def __init__(self, db: Session): 
        self.db = db
    
    def list_all(self) -> list[GatewayConnection]:
        """Get all gateway connections ordered by name."""
        return list(self.db.scalars(select(GatewayConnection).order_by(GatewayConnection.name)))
    
    def list_by_client_id(self, client_id: int) -> list[GatewayConnection]:
        """Get all connections for a specific client."""
        return list(self.db.scalars(select(GatewayConnection).where(GatewayConnection.client_id==client_id)))
    
    def get(self, id: int) -> GatewayConnection | None:
        """Get gateway connection by ID."""
        return self.db.get(GatewayConnection, id)
    
    def by_name(self, name: str) -> GatewayConnection | None:
        """Get gateway connection by name."""
        return self.db.scalar(select(GatewayConnection).where(GatewayConnection.name==name))
    
    def create(self, g: GatewayConnection) -> GatewayConnection:
        """Create a new gateway connection."""
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    
    def update(self, g: GatewayConnection) -> GatewayConnection:
        """Update an existing gateway connection."""
        self.db.add(g); self.db.commit(); self.db.refresh(g); return g
    
    def delete(self, id: int) -> None:
        """Delete a gateway connection by ID."""
        obj = self.get(id);
        if obj: self.db.delete(obj); self.db.commit()
    
    def delete_all_managed_by(self, managed_by: ManagedBy) -> None:
        """Delete all connections managed by a specific source."""
        self.db.execute(delete(GatewayConnection).where(GatewayConnection.managed_by==managed_by))
        self.db.commit()

class NginxRouteRepo:
    """Repository for NginxRoute model operations."""
    def __init__(self, db: Session): 
        self.db = db
    
    def list_all(self) -> list[NginxRoute]:
        """Get all nginx routes with their hosts loaded."""
        return list(self.db.scalars(select(NginxRoute).options(selectinload(NginxRoute.hosts))))
    
    def list_all_active(self) -> list[NginxRoute]:
        """Get all active nginx routes with their hosts loaded."""
        return list(self.db.scalars(select(NginxRoute).where(NginxRoute.active==True).options(selectinload(NginxRoute.hosts))))
    
    def list_by_domain(self, domain_id: int) -> list[NginxRoute]:
        """Get all nginx routes for a specific domain."""
        return list(self.db.scalars(select(NginxRoute).where(NginxRoute.domain_id==domain_id).options(selectinload(NginxRoute.hosts))))
    
    def get(self, id: int) -> NginxRoute | None:
        """Get nginx route by ID."""
        return self.db.get(NginxRoute, id)
    
    def exists_with_domain_id(self, domain_id: int) -> bool:
        """Check if any routes exist for a domain."""
        return self.db.scalar(select(NginxRoute).where(NginxRoute.domain_id==domain_id)) is not None
    
    def update(self, r: NginxRoute) -> NginxRoute:
        """Update an existing nginx route."""
        self.db.add(r); self.db.commit(); self.db.refresh(r); return r
    
    def create(self, r: NginxRoute) -> NginxRoute:
        """Create a new nginx route."""
        self.db.add(r); self.db.commit(); self.db.refresh(r); return r
    
    def delete(self, id: int) -> None:
        """Delete an nginx route by ID."""
        obj = self.db.get(NginxRoute, id)
        if obj is not None:
            self.db.delete(obj)
            self.db.commit()

class DnsRecordRepo:
    """Repository for DnsRecord model operations with archive management."""
    def __init__(self, db: Session): 
        self.db = db
    
    def list_user(self, domain_id: int) -> list[DnsRecord]:
        """Get all user-managed DNS records for a domain."""
        return list(self.db.scalars(select(DnsRecord).where(
            DnsRecord.domain_id==domain_id, DnsRecord.managed_by==ManagedBy.USER)))
    
    def list_all(self, include: Sequence[ManagedBy] | None = None) -> list[DnsRecord]:
        """Get all DNS records, optionally filtered by managed_by type."""
        if include:
            return list(self.db.scalars(select(DnsRecord).where(DnsRecord.managed_by.in_(include))))
        return list(self.db.scalars(select(DnsRecord)))
    
    def list_by_domain(self, domain_id: int, include: Sequence[ManagedBy] | None = None) -> list[DnsRecord]:
        """Get all DNS records for a domain, optionally filtered by managed_by type."""
        if include:
            return list(self.db.scalars(select(DnsRecord).where(DnsRecord.domain_id==domain_id, DnsRecord.managed_by.in_(include))))
        return list(self.db.scalars(select(DnsRecord).where(DnsRecord.domain_id==domain_id)))
    
    def get(self, id: int) -> DnsRecord | None:
        """Get DNS record by ID."""
        return self.db.get(DnsRecord, id)
    
    def exists(self, domain_id: int, name: str, type: str, content: str | None = None) -> int | None:
        """Check if a DNS record exists and return its ID if found."""
        conditions = [
            DnsRecord.domain_id == domain_id,
            DnsRecord.name == name,
            DnsRecord.type == type,
        ]
        if content is not None:
            conditions.append(DnsRecord.content == content)

        return self.db.scalar(select(DnsRecord.id).where(and_(*conditions)))
    
    def create(self, rec: DnsRecord) -> DnsRecord:
        """Create a new DNS record, removing any matching archived records first."""
        # Remove any archived record with the same details to avoid conflicts
        archive = self.db.scalar(select(DnsRecordArchive).where(
            DnsRecordArchive.name==rec.name,
            DnsRecordArchive.type==rec.type,
            DnsRecordArchive.content==rec.content,
            DnsRecordArchive.proxied==rec.proxied
        ))
        if archive:
            self.db.delete(archive)

        self.db.add(rec); self.db.commit(); self.db.refresh(rec); return rec
    def update(self, rec: DnsRecord) -> DnsRecord:
        """
        Update a DNS record with automatic archiving of old values.
        Uses SQLAlchemy's inspection API to detect changes and archive the previous state.
        """
        insp = inspect(rec)

        # Helper function to get the original database value
        def old_val(attr):
            h = getattr(insp.attrs, attr).history
            # Check for unchanged first - this is the DB value
            if h.unchanged:
                return h.unchanged[0]
            # If deleted exists and no unchanged, use deleted
            # (means value was set before ever being loaded)
            if h.deleted:
                return h.deleted[0]
            return None

        # Check if any tracked fields have changed
        fields = ["name", "type", "content", "ttl", "priority", "proxied"]
        changed = any(getattr(insp.attrs, f).history.has_changes() for f in fields)

        if changed:
            # Create archive record from the old values before updating
            snap = DnsRecord(
                id=rec.id,
                domain_id=rec.domain_id,
                name=old_val("name"),
                type=old_val("type"),
                content=old_val("content"),
                ttl=old_val("ttl"),
                priority=old_val("priority"),
                proxied=old_val("proxied"),
                managed_by=old_val("managed_by"),
            )
            archive = DnsRecordArchive.from_dns_record(snap)
            self.db.add(archive)

        self.db.commit()
        self.db.refresh(rec)
        return rec

    def delete(self, id: int) -> None:
        """Delete a DNS record, archiving it first."""
        obj = self.get(id)
        if obj:
            # Archive the record before deletion
            archive = DnsRecordArchive.from_dns_record(obj)
            self.db.add(archive)
            self.db.delete(obj)
            self.db.commit()
    
    def delete_all_with_domain_id(self, domain_id: int) -> None:
        """Delete all DNS records for a domain, archiving them first."""
        self.db.add_all([DnsRecordArchive.from_dns_record(rec) for rec in self.list_by_domain(domain_id)])
        self.db.execute(delete(DnsRecord).where(DnsRecord.domain_id==domain_id))
        self.db.commit()
    
    def delete_all_managed_by(self, managed_by: ManagedBy) -> None:
        """Delete all DNS records managed by a specific source, archiving them first."""
        self.db.add_all([DnsRecordArchive.from_dns_record(rec) for rec in self.list_all(include=[managed_by])])
        self.db.execute(delete(DnsRecord).where(DnsRecord.managed_by==managed_by)); self.db.commit()

    def list_archived(self) -> list[DnsRecordArchive]:
        """Get all archived DNS records."""
        return list(self.db.scalars(select(DnsRecordArchive)))
    
    def delete_archived(self, id: int) -> None:
        """Permanently delete an archived DNS record."""
        obj = self.db.get(DnsRecordArchive, id)
        if obj:
            self.db.delete(obj)
            self.db.commit()