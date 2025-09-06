"""
Cloudflare DNS and SSL certificate management service.
Handles DNS record synchronization, IP range caching, and Origin CA certificate management.
"""
from dataclasses import InitVar, dataclass, field, replace
import ipaddress
import json
import os
import stat
import time
from typing import Optional, Union
import cloudflare
import cloudflare.types.zones
from cloudflare.types.zones import Zone
from cloudflare.pagination import SyncV4PagePaginationArray
import requests
from pathlib import Path
import datetime
import subprocess
import ipaddress
from app.config import settings
from app.persistence import repos
from app.persistence.models import DnsRecord, Domain, ManagedBy









# Cloudflare IP range URLs for real IP detection
CF_IPV4_URL = "https://www.cloudflare.com/ips-v4"
CF_IPV6_URL = "https://www.cloudflare.com/ips-v6"

# Default cache TTL for Cloudflare IP ranges (1 day)
DEFAULT_CF_IP_TTL = 24 * 3600


@dataclass
class CloudflareIPCache:
    """
    Caches Cloudflare IP ranges for nginx real IP configuration.
    Supports both in-memory and on-disk caching with TTL expiration.
    """
    cache_path: Optional[str] = None
    ttl_seconds: int = DEFAULT_CF_IP_TTL
    _ipv4: list[str] = field(default_factory=list, init=False, repr=False)
    _ipv6: list[str] = field(default_factory=list, init=False, repr=False)
    _fetched_at: float = field(default=0.0, init=False, repr=False)

    def get(self, force_refresh: bool = False) -> tuple[list[str], list[str]]:
        """
        Get Cloudflare IP ranges with caching.
        Returns cached data if available and not expired, otherwise fetches fresh data.
        """
        now = time.time()
        # Return in-memory cache if valid
        if not force_refresh and self._ipv4 and self._ipv6 and (now - self._fetched_at) < self.ttl_seconds:
            return self._ipv4, self._ipv6
        
        # Try to load from disk cache if available
        if not force_refresh and self.cache_path:
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if (now - data.get("fetched_at", 0)) < self.ttl_seconds:
                    self._ipv4 = list(data.get("ipv4", []))
                    self._ipv6 = list(data.get("ipv6", []))
                    self._fetched_at = data["fetched_at"]
                    return self._ipv4, self._ipv6
            except Exception:  # noqa: BLE001 - best-effort cache loading
                pass

        # Fetch fresh data from Cloudflare
        ipv4, ipv6 = self._fetch_from_cf()
        self._ipv4, self._ipv6 = ipv4, ipv6
        self._fetched_at = now
        
        # Persist to disk cache if configured
        if self.cache_path:
            tmp = f"{self.cache_path}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"fetched_at": now, "ipv4": ipv4, "ipv6": ipv6}, f)
                os.replace(tmp, self.cache_path)
            except Exception as e:  # noqa: BLE001
                print(f"Failed to persist Cloudflare IP cache: {e}")
        return ipv4, ipv6

    def _fetch_from_cf(self) -> tuple[list[str], list[str]]:
        """Fetch IP ranges from Cloudflare's official endpoints."""
        ipv4 = _fetch_cidr_list(CF_IPV4_URL)
        ipv6 = _fetch_cidr_list(CF_IPV6_URL)
        if not ipv4 and not ipv6:
            print("Could not fetch any Cloudflare IP ranges; proceeding with empty list.")
        return ipv4, ipv6

def _fetch_cidr_list(url: str) -> list[str]:
    """
    Fetch and validate CIDR blocks from Cloudflare's IP range endpoints.
    Returns only syntactically valid CIDRs; invalid lines are skipped with a warning.
    """
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"Fetch failed for {url}: {e}")
        return []
    
    cidrs: list[str] = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            # Validate CIDR format (strict=False allows host addresses)
            ipaddress.ip_network(line, strict=False)
        except ValueError:
            print(f"Skipping invalid CIDR {line!r} from {url}")
            continue
        cidrs.append(line)
    return cidrs



# Global IP cache instance
cloudflare_ip_cache = CloudflareIPCache()
cloudflare_ip_cache.get()


@dataclass(frozen=True)
class SharedRecordType:
    """Immutable representation of a DNS record for comparison and caching."""
    domain: str
    name: str
    type: str
    content: str
    proxied: bool
    managed_by: str = field(compare=False, hash=False)
    record_id: Union[int, str] = field(compare=False, hash=False, default=None)

@dataclass
class CloudFlareDnsCache:
    """Cache for Cloudflare DNS data during synchronization."""
    db: InitVar[requests.Session]
    cf: InitVar[cloudflare.Cloudflare]

    zones: SyncV4PagePaginationArray[Zone] = field(default_factory=list)
    entries_by_zone: dict[str, SyncV4PagePaginationArray] = field(default_factory=dict)
    domains: list[Domain] = field(default_factory=list)

    remote_entries: set[SharedRecordType] = field(default_factory=set)
    local_entries: set[SharedRecordType] = field(default_factory=set)
    local_archived: set[SharedRecordType] = field(default_factory=set)

    def __post_init__(self, db: requests.Session, cf: cloudflare.Cloudflare):
        """Initialize cache with Cloudflare zones and local domains."""
        self.zones = cf.zones.list()
        self.domains = repos.DomainRepo(db).list_all()


class CloudFlareManager:
    """
    Manages DNS record synchronization between local database and Cloudflare.
    Handles importing existing records and creating missing ones.
    """

    def __init__(self, db: requests.Session, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.cf = settings.CF
        self.cf_cache = CloudFlareDnsCache(self.db, self.cf)

    def sync(self) -> CloudFlareDnsCache:
        """
        Synchronize DNS records between local database and Cloudflare.
        - Imports existing Cloudflare records as IMPORTED
        - Creates missing local records on Cloudflare
        - Removes archived records from Cloudflare
        """
        # Load local records (excluding previously imported ones)
        self.cf_cache.local_entries.update([self._get_shared_record_from_db(e) for e in repos.DnsRecordRepo(self.db).list_all() if e.managed_by != ManagedBy.IMPORTED])
        self.cf_cache.local_archived.update([self._get_shared_record_from_db(e) for e in repos.DnsRecordRepo(self.db).list_archived() if e.managed_by != ManagedBy.IMPORTED])

        # Clear previously imported records to re-import fresh
        repos.DnsRecordRepo(self.db).delete_all_managed_by(ManagedBy.IMPORTED)
        
        # Import all existing Cloudflare records
        for domain in self.cf_cache.domains:
            zone = self._get_zone(domain.name)
            if not zone:
                continue

            entries = self.cf.dns.records.list(zone_id=zone.id)
            self.cf_cache.entries_by_zone[zone.id] = entries
            for entry in entries:
                shared_rec = self._get_shared_record_from_cf(domain.name, entry)

                # Check if this record already exists locally (user or system managed)
                existing_local = next((e for e in self.cf_cache.local_entries if e == shared_rec), 
                                      next((e for e in self.cf_cache.local_archived if e == shared_rec), None))
                if existing_local:
                    # Preserve the existing management type
                    shared_rec = replace(shared_rec, managed_by=existing_local.managed_by)
                else:
                    # Import as new record
                    repos.DnsRecordRepo(self.db).create(
                        DnsRecord(
                            domain_id=domain.id,
                            name=entry.name[: -len(domain.name)-1] if entry.name.endswith(f".{domain.name}") else "@",
                            type=entry.type,
                            content=entry.content,
                            ttl=entry.ttl,
                            priority=entry.priority if hasattr(entry, 'priority') else None,
                            proxied=entry.proxied,
                            managed_by=ManagedBy.IMPORTED,
                            meta=entry.meta,
                        )
                    )
                self.cf_cache.remote_entries.add(shared_rec)




        # go through archived records and see if they still exist, if yes, delete first.
        for entry in repos.DnsRecordRepo(self.db).list_archived():
            print("remove ", entry.name)
            shared_rec = self._get_shared_record_from_db(entry)
            if shared_rec in self.cf_cache.remote_entries and entry.managed_by != ManagedBy.IMPORTED:
                self._delete_cloudflare_record(entry)
                self.cf_cache.remote_entries.discard(shared_rec)
            repos.DnsRecordRepo(self.db).delete_archived(entry.id)




        missing_remote = self.cf_cache.local_entries - self.cf_cache.remote_entries
        for entry in missing_remote:
            db_record = self._get_db_record_from_shared(entry)
            if not db_record:
                print("Missing remote entry found in DB:", entry.name, entry.type, entry.content, entry.managed_by)
                continue

            self._create_cloudflare_record(db_record)
            self.cf_cache.remote_entries.add(entry)

        # for e in self.local_entries:
        #     print(e.name, e.type, e.content, e.managed_by)
        # print("---")
        # for e in self.remote_entries:
        #     print(e.name, e.type, e.content, e.managed_by)

        return self.cf_cache

    def _delete_cloudflare_record(self, record: DnsRecord) -> None:
        print("Deleting Cloudflare record:", self._get_fqdn(record))
        record_id, zone_id = self._get_cf_record_id(record)
        if not record_id:
            return

        if self.dry_run:
            print("Dry run enabled, not deleting record.")
            return
        self.cf.dns.records.delete(record_id, zone_id=zone_id)

    def _create_cloudflare_record(self, record: DnsRecord) -> None:
        print("Creating Cloudflare record:", self._get_fqdn(record))
        if self.dry_run:
            print("Dry run enabled, not creating record.")
            return
        self.cf.dns.records.create(
            zone_id=self._get_zone(record.domain.name).id,
            name=self._get_fqdn(record),
            type=record.type.name,
            content=record.content,
            ttl=record.ttl,
            priority=record.priority,
            proxied=record.proxied,
        )

    def _get_db_record_from_shared(self, shared: SharedRecordType) -> DnsRecord:
        return next((r for r in repos.DnsRecordRepo(self.db).list_all() if
                     r.domain.name == shared.domain and
                     self._get_fqdn(r) == shared.name and
                     r.type == shared.type and
                     r.content == shared.content), None)

    def _get_shared_record_from_db(self, record: DnsRecord) -> SharedRecordType:
        name = self._get_fqdn(record)
        return SharedRecordType(
            domain=record.domain.name,
            name=name,
            type=record.type.name,
            content=record.content,
            proxied=record.proxied if hasattr(record, 'proxied') else False,
            managed_by=record.managed_by,
        )

    def _get_fqdn(self, record: DnsRecord) -> str:
        return f"{record.name}.{record.domain.name}" if record.name != "@" else record.domain.name

    def _get_shared_record_from_cf(self, domain: str, record) -> SharedRecordType:
        return SharedRecordType(
            domain=domain,
            name=record.name,
            type=record.type,
            content=record.content,
            proxied=record.proxied,
            managed_by=ManagedBy.IMPORTED,
            record_id=record.id,
        )

    def _get_zone(self, domain: str) -> cloudflare.types.zones.Zone | None:
        for zone in self.cf_cache.zones:
            if zone.name == domain:
                return zone
        return None

    def _get_cf_record_id(self, record: DnsRecord) -> tuple[int | str | None, str | None]:
        zone = self._get_zone(record.domain.name)
        if not zone:
            return None, None
        for entry in self.cf_cache.entries_by_zone.get(zone.id, []):
            if entry.name == self._get_fqdn(record) and entry.type == record.type and entry.content == record.content:
                return entry.id, zone.id
        return None, None





@dataclass
class CACertificateIdentifier:
    id: str
    expires: datetime.datetime
    certificate: str
    private_key: str

class CloudFlareOriginCAManager:

    def __init__(self, db: requests.Session, cf_cache: CloudFlareDnsCache, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.cf = settings.CF
        self.cf_cache = cf_cache


    def sync(self):
        existing = self._index_existing()
        wanted = self._get_labels()
        for (zone_id, domain), certs in existing.items():
            if domain not in wanted:
                continue

            self._sync_zone(zone_id, domain, certs, wanted[domain])

    def _sync_zone(self, zone_id: str, domain: str, existing_certs: dict[str, CACertificateIdentifier], wanted_hosts: set[tuple[str, str]]):
        print("- ", domain)

        for hosts in wanted_hosts:
            info = existing_certs.get(hosts)
            if info and not self._expiring(info.expires) and self._is_on_disk(hosts[0], info):
                print(hosts, info.expires, "still valid.")
                continue

            self._create_or_renew_cert(hosts, info)

        existing = set(existing_certs.keys())

        for hosts in existing - wanted_hosts:
            if self.dry_run:
                print(f"[Origin-CA] would revoke {existing_certs[hosts].id} {hosts} for {domain} (dry run)")
                continue

            self.cf.origin_ca_certificates.delete(existing_certs[hosts].id)
            print(f"[Origin-CA] revoked {existing_certs[hosts].id} {hosts} for {domain}")

    def _create_or_renew_cert(self, hosts: tuple[str, str], info: CACertificateIdentifier):
        if self.dry_run:
            print(f"[Origin-CA] would create/renew cert for {hosts} (dry run)")
            return

        label = hosts[0]
        key_p, csr_p = self._ensure_key_and_csr(label)
        cert = self._upload_csr(label, csr_p.read_text())
        self._write_to_disk(label, cert)

    def _get_labels(self) -> dict[str, set[tuple[str, str]]]:
        relevant_entries = [r for r in self.cf_cache.remote_entries if r.managed_by == ManagedBy.SYSTEM and r.type in ("A", "AAAA") and r.proxied]
        fqdn_labels: dict[str, set[tuple[str, str]]] = {}

        for entry in relevant_entries:
            label = None
            if entry.name.startswith("*"):
                label = entry.name[2:]
            else:
                label = entry.name
            fqdn_labels[entry.domain] = fqdn_labels.get(entry.domain, set())
            fqdn_labels[entry.domain].add((label, f"*.{label}"))

        return fqdn_labels

    def _index_existing(self):
        zone_ids = {(zone.id, zone.name) for zone in self.cf_cache.zones}
        existing: dict[str, dict[str, CACertificateIdentifier]] = {}
        for zone_id in zone_ids:
            certs = self.cf.origin_ca_certificates.list(zone_id=zone_id)
            existing[zone_id] = {tuple(sorted(c.hostnames, reverse=True)): CACertificateIdentifier(
                id=c.id,
                expires=datetime.datetime.strptime(c.expires_on.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S %z"),
                certificate=c.certificate,
                private_key="",  # only present on create
            ) for c in certs}
        return existing

    # ------------------------------------------------------------
    def _ensure_key_and_csr(self, label: str) -> tuple[Path, Path]:
        """
        Generate (or reuse) privkey.pem + req.csr for *label*.
        """
        tdir    = (Path(settings.CF_SSL_DIR) / label).resolve()
        key_p   = tdir / "privkey.pem"
        csr_p   = tdir / "req.csr"

        if key_p.exists() and csr_p.exists():
            return key_p, csr_p

        tdir.mkdir(parents=True, exist_ok=True)

        cn   = f"*.{label}"
        sans = f"DNS:{label},DNS:*.{label}"

        subprocess.run(
            [
                "openssl", "req", "-new", "-nodes",
                "-newkey", "rsa:2048",
                "-subj", f"/CN={cn}",
                "-addext", f"subjectAltName={sans}",
                "-keyout", str(key_p),
                "-out", str(csr_p),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        os.chmod(key_p, 0o600)
        os.chmod(csr_p, 0o600)
        return key_p, csr_p

    # ------------------------------------------------------------
    def _upload_csr(self, label: str, csr_pem: str) -> CACertificateIdentifier:
        """
        Send CSR to Cloudflare and return the resulting certificate dict.
        """
        hostnames = ([f"{label}", f"*.{label}"])
        cert = self.cf.origin_ca_certificates.create(
            hostnames=hostnames,
            request_type="origin-rsa",
            requested_validity=settings.CF_CERT_DAYS,
            csr=csr_pem
        )

        identifier = CACertificateIdentifier(
            id=cert.id,
            expires=datetime.datetime.strptime(cert.expires_on.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S %z"),
            certificate=cert.certificate,
            private_key=cert.private_key
        )

        print(f"[Origin-CA] issued cert id={cert.id} "
              f"for {', '.join(hostnames)}")
        return identifier

    # ------------------------------------------------------------
    def _is_on_disk(self, label: str, entry: CACertificateIdentifier) -> bool:
        """
        Check if the certificate and key files exist on disk.
        """
        tdir  = (Path(settings.CF_SSL_DIR) / label).resolve()
        crt_p = tdir / "fullchain.pem"
        key_p = tdir / "privkey.pem"

        return crt_p.exists() and key_p.exists()

    def _write_to_disk(
        self,
        label: str,
        entry: CACertificateIdentifier,
    ) -> tuple[str, str]:
        """
        Store PEMs under /etc/nginx/ssl and return (crt_path, key_path).
        """
        tdir  = (Path(settings.CF_SSL_DIR) / label).resolve()
        crt_p = tdir / "fullchain.pem"
        key_p = tdir / "privkey.pem"

        tdir.mkdir(parents=True, exist_ok=True)

        crt_p.write_text(entry.certificate)
        os.chmod(crt_p, 0o600)
        
        key_p.write_text(entry.private_key)
        os.chmod(key_p, 0o600)

        return str(crt_p), str(key_p)

    # ------------------------------------------------------------
    @staticmethod
    def _expiring(expires: datetime.datetime) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        return expires - now < datetime.timedelta(days=settings.CF_RENEW_SOON)