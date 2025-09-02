from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import DateTime, String, Integer, Boolean, ForeignKey, JSON, UniqueConstraint, Enum
from app.persistence.db import Base
import enum

class ManagedBy(str, enum.Enum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    IMPORTED = "IMPORTED"

class DnsType(str, enum.Enum):
    A="A"; AAAA="AAAA"; CNAME="CNAME"; TXT="TXT"; MX="MX"; NS="NS"; SRV="SRV"

class Domain(Base):
    __tablename__ = "domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    zone_id: Mapped[str | None] = mapped_column(String(128))
    auto_wildcard: Mapped[bool] = mapped_column(Boolean, default=True)
    use_for_direct_prefix: Mapped[bool] = mapped_column(Boolean, default=False)

class DnsRecord(Base):
    __tablename__ = "dns_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    name: Mapped[str] = mapped_column(String(255))      # relative: "@", "api", "foo.bar"
    type: Mapped[DnsType] = mapped_column(Enum(DnsType))
    content: Mapped[str] = mapped_column(String(1024))  # IP, target FQDN, or SRV JSON
    ttl: Mapped[int | None] = mapped_column(Integer)    # seconds
    priority: Mapped[int | None] = mapped_column(Integer)
    proxied: Mapped[bool | None] = mapped_column(Boolean)
    managed_by: Mapped[ManagedBy] = mapped_column(Enum(ManagedBy), default=ManagedBy.USER)
    meta: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("domain_id", "name", "type", name="uq_dns_key"),)

    domain: Mapped[Domain] = relationship(backref="dns_records", lazy="joined")


class GatewayServer(Base):
    __tablename__ = "gateway_servers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    host: Mapped[str] = mapped_column(String(45))
    bind_port: Mapped[int] = mapped_column(Integer)
    auth_token: Mapped[str] = mapped_column(String(128))
    is_origin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_config_pull_time: Mapped[datetime | None] = mapped_column(DateTime)

class GatewayClient(Base):
    __tablename__ = "gateway_clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    server_id: Mapped[int] = mapped_column(ForeignKey("gateway_servers.id"))
    last_config_pull_time: Mapped[datetime | None] = mapped_column(DateTime)

    server: Mapped[GatewayServer] = relationship(backref="clients", lazy="joined")

class GatewayProtocol(str, enum.Enum):
    TCP = "TCP"

class GatewayFlag(str, enum.Flag):
    ENCRYPTED = "transport.useencryption = true"

class GatewayConnection(Base):
    __tablename__ = "gateway_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    client_id: Mapped[int] = mapped_column(ForeignKey("gateway_clients.id"))
    protocol: Mapped[GatewayProtocol] = mapped_column(Enum(GatewayProtocol))
    local_ip: Mapped[str] = mapped_column(String(45))
    local_port: Mapped[int] = mapped_column(Integer)
    remote_port: Mapped[int] = mapped_column(Integer)
    flags: Mapped[list[GatewayFlag]] = mapped_column(JSON, default=[])
    managed_by: Mapped[ManagedBy] = mapped_column(Enum(ManagedBy), default=ManagedBy.USER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    client: Mapped[GatewayClient] = relationship(backref="connections", lazy="joined")
    server: Mapped[GatewayServer] = relationship(secondary="gateway_clients", viewonly=True, lazy="joined")

class NginxRouteHost(Base):
    __tablename__ = "nginx_route_hosts"
    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("nginx_routes.id"))
    host: Mapped[str] = mapped_column(String(255))
    weight: Mapped[int | None] = mapped_column(Integer)
    max_fails: Mapped[int | None] = mapped_column(Integer)
    fail_timeout: Mapped[int | None] = mapped_column(Integer)
    is_backup: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class NginxRouteProtocol(str, enum.Enum):
    HTTP = "HTTP"
    HTTPS = "HTTPS"
    STREAM = "STREAM"

class NginxRoute(Base):
    __tablename__ = "nginx_routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    subdomain: Mapped[str] = mapped_column(String(255))  # "@", "app", "api.v2"
    protocol: Mapped[NginxRouteProtocol] = mapped_column(Enum(NginxRouteProtocol), default=NginxRouteProtocol.HTTP)
    path_prefix: Mapped[str] = mapped_column(String(255), default="/")
    backend_path: Mapped[str] = mapped_column(String(255), default="")
    hosts: Mapped[list[NginxRouteHost] | None] = relationship(backref="nginx_route", cascade="all, delete-orphan", lazy="selectin")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("domain_id", "subdomain", "path_prefix", name="uq_http_sub_path_by_domain"),)

    domain: Mapped[Domain] = relationship(backref="routes", lazy="joined")
