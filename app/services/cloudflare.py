from collections import defaultdict
from dataclasses import dataclass, field, replace
import ipaddress
import json
import os
import stat
import time
from typing import Optional, Union
import cloudflare
import cloudflare.types.zones
import requests
from pathlib import Path
import datetime
import subprocess
import ipaddress
from app.config import settings
from app.persistence import repos
from app.persistence.models import DnsRecord, ManagedBy









CF_IPV4_URL = "https://www.cloudflare.com/ips-v4"
CF_IPV6_URL = "https://www.cloudflare.com/ips-v6"

# Reasonable default refresh period. CF ranges rarely change, but we do not want stale data.
DEFAULT_CF_IP_TTL = 24 * 3600  # 1 day


@dataclass
class CloudflareIPCache:
    """In-memory + optional on-disk cache wrapper for Cloudflare IP ranges."""
    cache_path: Optional[str] = None
    ttl_seconds: int = DEFAULT_CF_IP_TTL
    _ipv4: list[str] = field(default_factory=list, init=False, repr=False)
    _ipv6: list[str] = field(default_factory=list, init=False, repr=False)
    _fetched_at: float = field(default=0.0, init=False, repr=False)

    def get(self, force_refresh: bool = False) -> tuple[list[str], list[str]]:
        now = time.time()
        if not force_refresh and self._ipv4 and self._ipv6 and (now - self._fetched_at) < self.ttl_seconds:
            return self._ipv4, self._ipv6
        if not force_refresh and self.cache_path:
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if (now - data.get("fetched_at", 0)) < self.ttl_seconds:
                    self._ipv4 = list(data.get("ipv4", []))
                    self._ipv6 = list(data.get("ipv6", []))
                    self._fetched_at = data["fetched_at"]
                    return self._ipv4, self._ipv6
            except Exception:  # noqa: BLE001 - best-effort
                pass

        # Need fresh fetch
        ipv4, ipv6 = self._fetch_from_cf()
        self._ipv4, self._ipv6 = ipv4, ipv6
        self._fetched_at = now
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
        ipv4 = _fetch_cidr_list(CF_IPV4_URL)
        ipv6 = _fetch_cidr_list(CF_IPV6_URL)
        if not ipv4 and not ipv6:
            print("Could not fetch any Cloudflare IP ranges; proceeding with empty list.")
        return ipv4, ipv6

def _fetch_cidr_list(url: str) -> list[str]:
    """Fetch newline-delimited CIDRs from *url* and validate them.

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
            # Validate; strict=False allows host addresses though CF publishes CIDRs.
            ipaddress.ip_network(line, strict=False)
        except ValueError:
            print(f"Skipping invalid CIDR {line!r} from {url}")
            continue
        cidrs.append(line)
    return cidrs



cloudflare_ip_cache = CloudflareIPCache()
cloudflare_ip_cache.get()



@dataclass(frozen=True)
class SharedRecordType:
    domain: str
    name: str
    type: str
    content: str
    managed_by: str = field(compare=False, hash=False)
    record_id: Union[int, str] = field(compare=False, hash=False, default=None)

class CloudFlareManager:
    """Manage Cloudflare DNS records."""

    def __init__(self, db: requests.Session, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.cf = settings.CF
        self.zones = self.cf.zones.list()
        self.entries_by_zone: dict[str, None] = {}
        self.domains = repos.DomainRepo(db).list_all()

        self.remote_entries: set[SharedRecordType] = set()
        self.local_entries: set[SharedRecordType] = set()

    def run(self):

        self.local_entries.update([self._get_shared_record_from_db(e) for e in repos.DnsRecordRepo(self.db).list_all() if e.managed_by != ManagedBy.IMPORTED])

        repos.DnsRecordRepo(self.db).delete_all_managed_by(ManagedBy.IMPORTED)
        for domain in self.domains:
            zone = self._get_zone(domain.name)
            if zone:
                entries = self.cf.dns.records.list(zone_id=zone.id)
                self.entries_by_zone[zone.id] = entries
                for entry in entries:
                    shared_rec = self._get_shared_record_from_cf(domain.name, entry)

                    existing_local = next((e for e in self.local_entries if e == shared_rec), None)
                    if existing_local:
                        shared_rec = replace(shared_rec, managed_by=existing_local.managed_by)
                    else:
                        repos.DnsRecordRepo(self.db).create(
                            DnsRecord(
                                domain_id=domain.id,
                                name=entry.name,
                                type=entry.type,
                                content=entry.content,
                                ttl=entry.ttl,
                                priority=entry.priority if hasattr(entry, 'priority') else None,
                                proxied=entry.proxied,
                                managed_by=ManagedBy.IMPORTED,
                                meta=entry.meta,
                            )
                        )
                    self.remote_entries.add(shared_rec)

        # go through archived records and see if they still exist, if yes, delete first.
        for entry in repos.DnsRecordRepo(self.db).list_archived():
            print(entry.name)
            shared_rec = self._get_shared_record_from_db(entry)
            if shared_rec in self.remote_entries and entry.managed_by != ManagedBy.IMPORTED:
                self._delete_cloudflare_record(entry)
                self.remote_entries.discard(shared_rec)
            repos.DnsRecordRepo(self.db).delete_archived(entry.id)

        missing_remote = self.local_entries - self.remote_entries
        for entry in missing_remote:
            db_record = self._get_db_record_from_shared(entry)
            if not db_record:
                print("Missing remote entry found in DB:", entry.name, entry.type, entry.content, entry.managed_by)
                continue

            self._create_cloudflare_record(db_record)

        # for e in self.local_entries:
        #     print(e.name, e.type, e.content, e.managed_by)
        # print("---")
        # for e in self.remote_entries:
        #     print(e.name, e.type, e.content, e.managed_by)

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
            managed_by=ManagedBy.IMPORTED,
            record_id=record.id,
        )

    def _get_zone(self, domain: str) -> cloudflare.types.zones.Zone | None:
        for zone in self.zones:
            if zone.name == domain:
                return zone
        return None

    def _get_cf_record_id(self, record: DnsRecord) -> tuple[int | str | None, str | None]:
        zone = self._get_zone(record.domain.name)
        if not zone:
            return None, None
        for entry in self.entries_by_zone.get(zone.id, []):
            if entry.name == self._get_fqdn(record) and entry.type == record.type and entry.content == record.content:
                return entry.id, zone.id
        return None, None

