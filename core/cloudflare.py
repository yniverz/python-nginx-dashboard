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
