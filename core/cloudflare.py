from collections import defaultdict
from dataclasses import dataclass, field
import ipaddress
import json
import os
import time
from typing import Optional
import cloudflare
import requests


@dataclass
class SRVRecord():
    name: str
    priority: int
    weight: int
    port: int
    target: str

@dataclass
class CloudFlareMapEntry:
    subdomain: str
    service_name: str
    target_port: int



class CloudFlareSRVManager:
    def __init__(self, token, domain):
        self.cf = cloudflare.Cloudflare(api_token=token)
        self.domain = domain

        zones = self.cf.zones.list()
        self.zone_id = ""
        for zone in zones:
            if zone.name == domain:
                self.zone_id = zone.id
                break
        else:
            raise Exception("Zone not found!")
        
        self._have_records = []
        self._should_records: list[SRVRecord] = []

        self._update_records()

    def _update_records(self):
        self._have_records = [record for record in self.cf.dns.records.list(zone_id=self.zone_id) if record.type == "SRV"]

        # remove all records that are not in should_records
        for record in self._have_records:
            if record.name not in [record.name for record in self._should_records]:
                try:
                    self.cf.dns.records.delete(zone_id=self.zone_id, dns_record_id=record.id)
                    self._have_records.remove(record)
                except Exception as e:
                    print(f"Failed to delete record {record.name}: {e}")

        # add all records that are not in have_records
        for record in self._should_records:
            if record.name not in [record.name for record in self._have_records]:
                try:
                    record = self.cf.dns.records.create(zone_id=self.zone_id, name=record.name, type="SRV", data={"priority": record.priority, "weight": record.weight, "port": record.port, "target": record.target})
                    if record is not None:
                        self._have_records.append(record)
                except Exception as e:
                    print(f"Failed to create record {record.name}: {e}")

        self._should_records = []
        for record in self._have_records:
            self._should_records.append(SRVRecord(name=record.name, priority=record.data.priority, weight=record.data.weight, port=record.data.port, target=record.data.target))
    
    def ensure_srv_records(self, records: list[CloudFlareMapEntry]):
        self._should_records = []
        for record in records:
            self._should_records.append(SRVRecord(name=f"{record.service_name}.{record.subdomain}.{self.domain}", priority=0, weight=5, port=record.target_port, target=self.domain))

        self._update_records()


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
        origin_ips: list[str],
        *,
        proxied: bool = True,
        ttl: int = 1,
    ) -> None:
        """Synchronise DNS with the dashboard state."""

        want_labels: set[str] = self._first_labels_requiring_wildcard(proxy_map)
        have: dict[str, dict] = self._records_by_label()

        want_v4 = {ip for ip in origin_ips if ipaddress.ip_address(ip).version == 4}
        want_v6 = {ip for ip in origin_ips if ipaddress.ip_address(ip).version == 6}

        for label in want_labels:
            fqdn = f"*.{self.domain}" if label == "" else f"*.{label}.{self.domain}"
            have_entry = have.get(label, {"A": set(), "AAAA": set(), "map": {}})

            # ---- IPv4 ---------------------------------------------------
            self._ensure_records(
                label,
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
                    label,
                    fqdn,
                    rtype="AAAA",
                    want_set=want_v6,
                    have_entry=have_entry,
                    proxied=proxied,
                    ttl=ttl,
                )

        # ---- remove *whole* label wildcards that are not wanted anymore ----
        for obsolete in (have.keys() - want_labels):
            fqdn = f"*.{self.domain}" if obsolete == "" else f"*.{obsolete}.{self.domain}"
            for (rtype, ip), rec_id in have[obsolete]["map"].items():
                self.cf.dns.records.delete(
                    zone_id=self.zone_id,
                    dns_record_id=rec_id,
                )
                print(f"Removed unneeded {rtype} {fqdn} → {ip}")

    # ------------------------------------------------------------
    #  HELPERS
    # ------------------------------------------------------------
    def _first_labels_requiring_wildcard(self, proxy_map: dict) -> set[str]:
        """
        Decide which labels really need a wildcard:

        * add "" (root) if **any** depth-1 host exists (foo.domain).
        * add last label when depth ≥ 2   (hello.static.domain -> "static").
        """
        labels: set[str] = set()
        root_needed = False

        for kind in ("http", "stream"):
            for sub in proxy_map.get(kind, {}):
                if sub in ("@", ""):
                    continue  # explicit root entry – ignore

                parts = sub.split(".")
                if len(parts) >= 1:
                    root_needed = True             # depth-1 host: keep *.domain
                if len(parts) >= 2:
                    labels.add(parts[-1])           # need *.label.domain

        if root_needed:
            labels.add("")                          # ""  represents root wildcard

        return labels

    # ------------------------------------------------------------------
    def _records_by_label(self) -> dict[str, dict[str, set[str]]]:
        """
        Build a lookup of existing wildcard records.

        Returns
        -------
        {
          "":        {"A": {ip,…}, "AAAA": {ip,…}, "map": {(rtype, ip): rec_id}},
          "static":  {...},
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

            # recognise "*.domain" (root) or "*.label.domain"
            if rec.name == f"*.{self.domain}":
                label = ""
            elif rec.name.startswith("*.") and rec.name.endswith(suffix):
                label = rec.name[2 : -len(suffix)]
            else:
                continue

            ip = rec.content
            out[label][rec.type].add(ip)
            out[label]["map"][(rec.type, ip)] = rec.id

        return out

    # ------------------------------------------------------------------
    def _ensure_records(
        self,
        label: str,
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