from pydantic import BaseModel, Field
from typing import Optional, Literal
from app.models import ManagedBy, DnsType

class DomainIn(BaseModel):
    name: str
    provider_account_id: Optional[int] = None
    provider_zone_id: Optional[str] = None
    origin_ipv4: Optional[str] = None
    origin_ipv6: Optional[str] = None
    auto_wildcard: bool = True
    auto_direct_prefix: str = "direct"
    acme_email: Optional[str] = None

class DomainOut(DomainIn):
    id: int
    class Config: from_attributes = True

class DnsProviderAccountIn(BaseModel):
    provider: str = "cloudflare"
    name: str
    credentials: dict
    meta: Optional[dict] = None

class DnsProviderAccountOut(DnsProviderAccountIn):
    id: int
    class Config: from_attributes = True

class HttpRouteIn(BaseModel):
    domain_id: int
    subdomain: str
    backend_url: str

class HttpRouteOut(HttpRouteIn):
    id: int
    class Config: from_attributes = True

class StreamRouteIn(BaseModel):
    domain_id: int
    subdomain: str
    port: int
    target: str
    srv_record: Optional[str] = None
    active: bool = True

class StreamRouteOut(StreamRouteIn):
    id: int
    class Config: from_attributes = True

class DnsRecordIn(BaseModel):
    domain_id: int
    name: str
    type: DnsType
    content: str
    ttl: Optional[int] = None
    priority: Optional[int] = None
    proxied: Optional[bool] = None
    active: bool = True

class DnsRecordOut(DnsRecordIn):
    id: int
    managed_by: ManagedBy
    meta: Optional[dict] = None
    class Config: from_attributes = True

class TokenHeader(BaseModel):
    admin_token: str = Field(alias="x-admin-token")
