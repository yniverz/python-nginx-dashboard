"""
SQLAlchemy database models for the Multi-Domain Edge Manager.
Defines all database tables and their relationships.
"""
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import DateTime, String, Integer, Boolean, ForeignKey, JSON, UniqueConstraint, Enum
from app.persistence.db import Base
import enum

class ManagedBy(str, enum.Enum):
    """Enumeration for tracking who manages a record."""
    SYSTEM = "SYSTEM"      # Managed by the application automatically
    USER = "USER"          # Managed by user through the web interface
    IMPORTED = "IMPORTED"  # Imported from external DNS provider

class DnsType(str, enum.Enum):
    """Supported DNS record types."""
    A="A"; AAAA="AAAA"; CNAME="CNAME"; TXT="TXT"; MX="MX"; NS="NS"; SRV="SRV"

class Domain(Base):
    """Represents a domain managed by the system."""
    __tablename__ = "domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)  # Domain name (e.g., "example.com")
    auto_wildcard: Mapped[bool] = mapped_column(Boolean, default=True)  # Auto-generate wildcard DNS records
    use_for_direct_prefix: Mapped[bool] = mapped_column(Boolean, default=False)  # Create direct.* subdomains

class DnsRecord(Base):
    """DNS record for a domain."""
    __tablename__ = "dns_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    name: Mapped[str] = mapped_column(String(255))      # Relative name: "@" for root, "api", "foo.bar"
    type: Mapped[DnsType] = mapped_column(Enum(DnsType))
    content: Mapped[str] = mapped_column(String(1024))  # IP address, target FQDN, or SRV JSON
    ttl: Mapped[int | None] = mapped_column(Integer, default=1)    # Time to live in seconds
    priority: Mapped[int | None] = mapped_column(Integer)  # For MX and SRV records
    proxied: Mapped[bool | None] = mapped_column(Boolean)  # Cloudflare proxy status
    managed_by: Mapped[ManagedBy] = mapped_column(Enum(ManagedBy), default=ManagedBy.USER)
    meta: Mapped[dict | None] = mapped_column(JSON, default=dict)  # Additional metadata

    # Ensure unique DNS records per domain
    __table_args__ = (UniqueConstraint("domain_id", "name", "type", "content", name="uq_dns_key"),)

    domain: Mapped[Domain] = relationship(backref="dns_records", lazy="joined")

class DnsRecordArchive(Base):
    """Archive table for deleted DNS records to maintain history."""
    __tablename__ = "dns_records_archive"

    id: Mapped[int] = mapped_column(primary_key=True)          # Archive row ID
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("domains.id"))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[DnsType] = mapped_column(Enum(DnsType))
    content: Mapped[str] = mapped_column(String(1024))
    managed_by: Mapped[ManagedBy] = mapped_column(Enum(ManagedBy))

    # No unique constraint here to allow multiple historical entries
    domain: Mapped["Domain"] = relationship(lazy="joined")

    @classmethod
    def from_dns_record(cls, rec: "DnsRecord") -> "DnsRecordArchive":
        """Create an archive record from an existing DNS record."""
        return cls(
            domain_id=rec.domain_id,
            name=rec.name,
            type=rec.type,
            content=rec.content,
            managed_by=rec.managed_by,
        )


class GatewayServer(Base):
    """FRP gateway server configuration."""
    __tablename__ = "gateway_servers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)  # Server identifier
    host: Mapped[str] = mapped_column(String(45))  # Server hostname/IP
    bind_port: Mapped[int] = mapped_column(Integer)  # Port for client connections
    auth_token: Mapped[str] = mapped_column(String(128))  # Authentication token
    last_config_pull_time: Mapped[datetime | None] = mapped_column(DateTime)  # Last config fetch

class GatewayClient(Base):
    """FRP gateway client configuration."""
    __tablename__ = "gateway_clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)  # Client identifier
    server_id: Mapped[int] = mapped_column(ForeignKey("gateway_servers.id"))
    is_origin: Mapped[bool] = mapped_column(Boolean, default=False)  # Is this an origin server?
    last_config_pull_time: Mapped[datetime | None] = mapped_column(DateTime)

    server: Mapped[GatewayServer] = relationship(backref="clients", lazy="joined")

class GatewayProtocol(str, enum.Enum):
    """Supported gateway protocols."""
    TCP = "tcp"
    UDP = "udp"

class GatewayFlag(str, enum.Flag):
    """Gateway connection flags for FRP configuration."""
    ENCRYPTED = "transport.useencryption = true"

class GatewayConnection(Base):
    """FRP gateway connection configuration."""
    __tablename__ = "gateway_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    client_id: Mapped[int] = mapped_column(ForeignKey("gateway_clients.id"))
    protocol: Mapped[GatewayProtocol] = mapped_column(Enum(GatewayProtocol))
    local_ip: Mapped[str] = mapped_column(String(45))  # Local IP to bind to
    local_port: Mapped[int] = mapped_column(Integer)   # Local port to bind to
    remote_port: Mapped[int] = mapped_column(Integer)  # Remote port on server
    flags: Mapped[list[GatewayFlag]] = mapped_column(JSON, default=[])  # Additional FRP flags
    managed_by: Mapped[ManagedBy] = mapped_column(Enum(ManagedBy), default=ManagedBy.USER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    client: Mapped[GatewayClient] = relationship(backref="connections", lazy="joined")
    server: Mapped[GatewayServer] = relationship(secondary="gateway_clients", viewonly=True, lazy="joined")

class NginxRouteHost(Base):
    """Backend host for an nginx route (upstream server)."""
    __tablename__ = "nginx_route_hosts"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("nginx_routes.id"))
    host: Mapped[str] = mapped_column(String(255))  # Backend host:port
    weight: Mapped[int | None] = mapped_column(Integer)  # Load balancing weight
    max_fails: Mapped[int | None] = mapped_column(Integer)  # Max failures before marking down
    fail_timeout: Mapped[int | None] = mapped_column(Integer)  # Timeout in seconds
    is_backup: Mapped[bool] = mapped_column(Boolean, default=False)  # Backup server flag
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class NginxRouteProtocol(str, enum.Enum):
    """Supported nginx route protocols."""
    HTTP = "HTTP"
    HTTPS = "HTTPS"
    STREAM = "STREAM"
    REDIRECT = "REDIRECT"

class NginxRoute(Base):
    """Nginx route configuration for proxying requests."""
    __tablename__ = "nginx_routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    subdomain: Mapped[str] = mapped_column(String(255))  # Subdomain (e.g., "api", "@" for root)
    protocol: Mapped[NginxRouteProtocol] = mapped_column(Enum(NginxRouteProtocol), default=NginxRouteProtocol.HTTP)
    path_prefix: Mapped[str] = mapped_column(String(255), default="/")  # URL path prefix to match
    backend_path: Mapped[str] = mapped_column(String(255), default="")  # Backend path to proxy to
    hosts: Mapped[list[NginxRouteHost] | None] = relationship(backref="nginx_route", cascade="all, delete-orphan", lazy="selectin")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Ensure unique routes per domain/subdomain/path combination
    __table_args__ = (UniqueConstraint("domain_id", "subdomain", "path_prefix", name="uq_http_sub_path_by_domain"),)

    domain: Mapped[Domain] = relationship(backref="routes", lazy="joined")
