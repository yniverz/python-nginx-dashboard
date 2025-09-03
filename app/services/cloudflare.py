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

    def __init__(self, db: requests.Session):
        self.db = db
        self.cf = settings.CF
        self.zones = self.cf.zones.list()
        self.entries_by_zone: dict[str, None] = {}
        self.domains = repos.DomainRepo(db).list_all()

        self.remote_entries: set[SharedRecordType] = set()
        self.local_entries: set[SharedRecordType] = set()

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
        self.cf.dns.records.delete(record_id, zone_id=zone_id)

    def _create_cloudflare_record(self, record: DnsRecord) -> None:
        print("Creating Cloudflare record:", self._get_fqdn(record))
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


class CloudFlareWildcardManager:
    """
    Make sure Cloudflare holds exactly the wildcard A/AAAA records we need:

    ─ A **root wildcard  *.domain**          if at least one depth-1 host exists.
    ─ A **label wildcard *.label.domain**    if at least one host is deeper
                                             than   <anything>.<label>.<domain>.

    Each wildcard points to *all* IPs given in `origin_ips` (v4 and/or v6).
    Stray IPs are removed so DNS never advertises back-end addresses
    that are no longer listed in the config file.
    """

    # ------------------------------------------------------------
    def __init__(self, cf: cloudflare.Cloudflare, zone_id: str, domain: str):
        self.cf = cf
        self.zone_id = zone_id
        self.domain = domain

    # ------------------------------------------------------------
    #  PUBLIC entry-point
    # ------------------------------------------------------------
    def sync_wildcards(
        self,
        proxy_map: dict,
        origin_ips: dict[str, str],
        *,
        proxied: bool = True,
        ttl: int = 1,
    ) -> None:
        """Synchronise DNS with the dashboard state."""

        want_labels: set[str] = self._first_labels_requiring_wildcard(proxy_map, origin_ips)
        have: dict[str, dict] = self._records_by_label()
        self._last_labels = want_labels

        want_v4 = {ip for ip in origin_ips.values() if ipaddress.ip_address(ip).version == 4}
        want_v6 = {ip for ip in origin_ips.values() if ipaddress.ip_address(ip).version == 6}

        for fqdn in want_labels:
            print(f"Ensuring wildcard {fqdn} → {want_v4} (v4), {want_v6} (v6)")
            have_entry = have.get(fqdn, {"A": set(), "AAAA": set(), "map": {}})

            # ---- IPv4 ---------------------------------------------------
            self._ensure_records(
                fqdn,
                rtype="A",
                want_set=want_v4,
                have_entry=have_entry,
                proxied=proxied,
                ttl=ttl,
            )

            # ---- IPv6 ---------------------------------------------------
            if want_v6:
                self._ensure_records(
                    fqdn,
                    rtype="AAAA",
                    want_set=want_v6,
                    have_entry=have_entry,
                    proxied=proxied,
                    ttl=ttl,
                )

        
        # also add a record for each origin IP that has a key that is not "-" to the ip without proxy mode
        origin_ip_labels = set()
        for key, ip in origin_ips.items():
            if not key or key == "-":
                continue
            fqdn = f"{key}.direct.{self.domain}"
            origin_ip_labels.add(fqdn)
            print(f"Ensuring direct record for {fqdn} → {ip}")
            have_entry = have.get(fqdn, {"A": set(), "AAAA": set(), "map": {}})

            if ipaddress.ip_address(ip).version == 4:
                self._ensure_records(
                    fqdn,
                    rtype="A",
                    want_set={ip},
                    have_entry=have_entry,
                    proxied=False,
                    ttl=ttl,
                )
            elif ipaddress.ip_address(ip).version == 6:
                self._ensure_records(
                    fqdn,
                    rtype="AAAA",
                    want_set={ip},
                    have_entry=have_entry,
                    proxied=False,
                    ttl=ttl,
                )

        # ---- remove *whole* label wildcards that are not wanted anymore ----
        for fqdn in (have.keys() - (want_labels | origin_ip_labels)):
            for (rtype, ip), rec_id in have[fqdn]["map"].items():
                print(f"Removing obsolete {rtype} {fqdn} → {ip}")
                self.cf.dns.records.delete(
                    zone_id=self.zone_id,
                    dns_record_id=rec_id,
                )
                print(f"Removed unneeded {rtype} {fqdn} → {ip}")

        

    def current_labels(self) -> set[str]:
        """
        Returns the label set from the **last** `sync_wildcards()` run.

        • ""  → root wildcard  (*.domain)  
        • "static"  →  *.static.domain  
        • "ve.orgn" →  *.ve.orgn.domain, etc.

        If you call this before the first sync the attribute won’t exist,
        so return an empty set in that case.
        """
        labels = getattr(self, "_last_labels", set())
        new_labels = set()

        suffix = f".{self.domain}"

        for label in labels:
            if not label.startswith("*.") and label != self.domain:
                continue  # skip non-wildcard labels
            if label == self.domain:
                new_labels.add("")
            else:
                new_labels.add(label[2: -len(suffix)])

        return new_labels

    # ------------------------------------------------------------
    #  HELPERS
    # ------------------------------------------------------------
    def _first_labels_requiring_wildcard(self, proxy_map: dict, origin_ips: dict) -> set[str]:
        """
        Return every label (possibly containing dots) that needs a wildcard.

        For a route 'tower.ve.orgn' we emit:
            've.orgn'   (because depth-1 below it exists)
            'orgn'      (because depth-2 below it exists)

        The empty string '' represents the *root* wildcard  *.domain
        and is added only when at least one depth-1 host (foo.domain) exists.
        """
        labels: set[str] = set()
        root_needed = False

        for kind in ("http", "stream"):
            for sub in proxy_map.get(kind, {}):
                if sub in ("@", ""):
                    continue                          # skip explicit root

                parts = sub.split(".")               # e.g. ['tower','ve','orgn']

                if len(parts) >= 1:                  # depth-1 host ⇒ root wildcard
                    root_needed = True

                # walk up the chain, add every parent
                for i in range(1, len(parts)):       # i = 1 … len-1
                    labels.add("*." + ".".join(parts[i:]) + "." + self.domain)

        if root_needed:
            labels.add(self.domain)                              # '' = domain
            labels.add("*." + self.domain)                        # '*.' = *.domain

        return labels


    # ------------------------------------------------------------------
    def _records_by_label(self) -> dict[str, dict[str, set[str]]]:
        """
        Build a lookup of existing wildcard records.

        Returns
        -------
        {
          "domain.tld":        {"A": {ip,…}, "AAAA": {ip,…}, "map": {(rtype, ip): rec_id}},
          "static.domain.tld":  {...},
          ...
        }
        """
        out: dict[str, dict] = defaultdict(
            lambda: {"A": set(), "AAAA": set(), "map": {}}
        )
        suffix = f".{self.domain}"

        for rec in self.cf.dns.records.list(zone_id=self.zone_id, per_page=5000):
            if rec.type not in ("A", "AAAA"):
                continue

            # # recognise "*.domain" (root) or "*.label.domain"
            # if rec.name == f"*.{self.domain}":
            #     label = ""
            # elif rec.name.startswith("*.") and rec.name.endswith(suffix):
            #     label = rec.name[2 : -len(suffix)]
            # else:
            #     continue

            # label = rec.name[:-len(suffix)] if rec.name.endswith(suffix) else continue

            if not rec.name.endswith(suffix) and rec.name != self.domain:
                continue

            label = rec.name

            ip = rec.content
            out[label][rec.type].add(ip)
            out[label]["map"][(rec.type, ip)] = rec.id

        return out

    # ------------------------------------------------------------------
    def _ensure_records(
        self,
        fqdn: str,
        *,
        rtype: str,
        want_set: set[str],
        have_entry: dict,
        proxied: bool,
        ttl: int,
    ) -> None:
        have_set = have_entry[rtype]
        missing = want_set - have_set
        extra = have_set - want_set

        suffix = f".{self.domain}"

        if fqdn == self.domain:
            fqdn = "@"
        else:
            fqdn = fqdn[:-len(suffix)]

        # ---- create missing ----
        for ip in missing:
            self.cf.dns.records.create(
                zone_id=self.zone_id,
                type=rtype,
                name=fqdn,
                content=ip,
                ttl=ttl,
                proxied=proxied,
            )
            print(f"Added   {rtype:5} {fqdn} → {ip}")

        # ---- delete stale ----
        for ip in extra:
            rec_id = have_entry["map"][(rtype, ip)]
            self.cf.dns.records.delete(
                zone_id=self.zone_id,
                dns_record_id=rec_id,
            )
            print(f"Removed {rtype:5} {fqdn} → {ip}")
