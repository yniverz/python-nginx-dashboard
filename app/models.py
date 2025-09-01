from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, ForeignKey, JSON, UniqueConstraint, Enum
import enum

class Base(DeclarativeBase):
    pass

class ManagedBy(str, enum.Enum):
    SYSTEM="SYSTEM"
    USER="USER"
    IMPORTED="IMPORTED"

class DnsType(str, enum.Enum):
    A="A"; AAAA="AAAA"; CNAME="CNAME"; TXT="TXT"; MX="MX"; NS="NS"; SRV="SRV"

class DnsProviderAccount(Base):
    __tablename__ = "dns_provider_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="cloudflare")
    name: Mapped[str] = mapped_column(String(64))
    credentials: Mapped[dict] = mapped_column(JSON)
    meta: Mapped[dict | None] = mapped_column(JSON)

class Domain(Base):
    __tablename__ = "domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)  # example.com
    provider_account_id: Mapped[int | None] = mapped_column(ForeignKey("dns_provider_accounts.id"))
    provider_zone_id: Mapped[str | None] = mapped_column(String(128))
    origin_ipv4: Mapped[str | None] = mapped_column(String(45))
    origin_ipv6: Mapped[str | None] = mapped_column(String(45))
    auto_wildcard: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_direct_prefix: Mapped[str] = mapped_column(String(32), default="direct")
    acme_email: Mapped[str | None] = mapped_column(String(255))
    provider_account: Mapped["DnsProviderAccount"] = relationship()

class DomainOrigin(Base):
    __tablename__ = "domain_origins"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    name: Mapped[str] = mapped_column(String(64))
    ipv4: Mapped[str | None] = mapped_column(String(45))
    ipv6: Mapped[str | None] = mapped_column(String(45))
    proxied: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("domain_id", "name", name="uq_domain_origin_name"),)

class HttpRoute(Base):
    __tablename__ = "http_routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    subdomain: Mapped[str] = mapped_column(String(255))  # "@", "app", "foo.bar"
    # simple: one backend string for now (you can extend to targets later)
    backend_url: Mapped[str] = mapped_column(String(1024))  # e.g. http://backend:8080
    __table_args__ = (UniqueConstraint("domain_id", "subdomain", name="uq_http_sub_by_domain"),)

class StreamRoute(Base):
    __tablename__ = "stream_routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    subdomain: Mapped[str] = mapped_column(String(255))     # "mc"
    port: Mapped[int] = mapped_column(Integer)               # 25565
    target: Mapped[str] = mapped_column(String(1024))        # host:port for upstream
    srv_record: Mapped[str | None] = mapped_column(String(255))  # like "_minecraft._tcp"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("domain_id","subdomain","port", name="uq_stream_sub_port_by_domain"),)

class DnsRecord(Base):
    __tablename__ = "dns_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    name: Mapped[str] = mapped_column(String(255))  # "@", "api", "foo.bar", "_srv._tcp.app"
    type: Mapped[DnsType] = mapped_column(Enum(DnsType))
    content: Mapped[str] = mapped_column(String(1024))  # IP/hostname/JSON (SRV)
    ttl: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int | None] = mapped_column(Integer)
    proxied: Mapped[bool | None] = mapped_column(Boolean)
    managed_by: Mapped[ManagedBy] = mapped_column(Enum(ManagedBy), default=ManagedBy.USER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("domain_id", "name", "type", name="uq_dns_key"),)

class CertBundle(Base):
    __tablename__ = "cert_bundles"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    label: Mapped[str] = mapped_column(String(64), default="")
    fullchain_path: Mapped[str] = mapped_column(String(512))
    privkey_path: Mapped[str] = mapped_column(String(512))
    expires_on: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("domain_id", "label", name="uq_cert_label_by_domain"),)
