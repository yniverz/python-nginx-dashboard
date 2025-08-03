from collections import defaultdict
from dataclasses import dataclass, field
import ipaddress
import json
import os
import stat
import time
from typing import Optional
import cloudflare
import requests
from pathlib import Path
import datetime
import subprocess
import ipaddress


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
        self._last_labels = want_labels

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

    def current_labels(self) -> set[str]:
        """
        Returns the label set from the **last** `sync_wildcards()` run.

        • ""  → root wildcard  (*.domain)  
        • "static"  →  *.static.domain  
        • "ve.orgn" →  *.ve.orgn.domain, etc.

        If you call this before the first sync the attribute won’t exist,
        so return an empty set in that case.
        """
        return getattr(self, "_last_labels", set())

    # ------------------------------------------------------------
    #  HELPERS
    # ------------------------------------------------------------
    def _first_labels_requiring_wildcard(self, proxy_map: dict) -> set[str]:
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
                    labels.add(".".join(parts[i:]))

        if root_needed:
            labels.add("")                           # '' = *.domain

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


_ORIGIN_CA_ENDPOINT = "/zones/{zone}/origin_ca/certificates"
_VALIDITY_DAYS      = 5475              # 15 years – max allowed
_SSL_DIR            = Path("/etc/nginx/ssl")

class CloudFlareOriginCAManager:
    """
    For every `label` that already receives a wildcard A/AAAA record
    (see CloudFlareWildcardManager) make sure we store a matching
    *Origin-CA* key-pair in  /etc/nginx/ssl/<label or root>/ .

           label == ""    →   *.domain           & domain
           label == "foo" →   *.foo.domain       & foo.domain
           label == "bar.baz" → *.bar.baz.domain & bar.baz.domain
    """

    def __init__(self, cf: cloudflare.Cloudflare, zone_id: str, domain: str,
                 origin_ca_key: str):
        self.cf, self.zone_id, self.domain = cf, zone_id, domain
        self.headers = {"X-Auth-User-Service-Key": origin_ca_key}

    # ------------------------------------------------------------ PUBLIC
    def sync_origin_certs(self, labels: set[str]) -> None:
        """Make sure every *wanted* label has a usable certificate."""
        have = self._index_existing()

        for label in labels:
            if label not in have or self._is_expiring(have[label]["expires"]):
                self._issue_or_renew(label, have.get(label))

        # (optional) revoke certs we no longer want
        for obsolete in (have.keys() - labels):
            self._revoke(have[obsolete]["id"])

    # ---------------------------------------------------- low-level helpers
    def _index_existing(self) -> dict[str, dict]:
        """
        Return {label: {"id": <cert-id>, "expires": <datetime>}, …} for all
        *active* Origin-CA certificates in the zone.

        • "" represents the root wildcard  (*.domain + domain)
        • "foo"  → certificate for  *.foo.domain + foo.domain
        • "ve.orgn" → certificate for *.ve.orgn.domain  + ve.orgn.domain
        """
        by_label: dict[str, dict] = {}
        endpoint = _ORIGIN_CA_ENDPOINT.format(zone=self.zone_id)

        page = 1
        while True:
            resp = self.cf.get(
                endpoint,
                params={"page": page, "per_page": 50},
                headers=self.headers,
            )

            for cert in resp["result"]:
                if cert["revoked_at"] is not None:
                    continue                      # ignore revoked

                # hostnames come back unsorted → sort for deterministic test
                hn = sorted(cert["hostnames"])

                if hn == [self.domain, f"*.{self.domain}"]:
                    label = ""                    # root cert
                else:
                    # take everything between "*." and ".<domain>"
                    label = hn[0][2 : -(len(self.domain) + 1)]

                by_label[label] = {
                    "id": cert["id"],
                    "expires": datetime.datetime.fromisoformat(
                        cert["expires_on"].rstrip("Z")
                    ),
                }

            # pagination bookkeeping
            info = resp.get("result_info", {})
            if not info or page >= info.get("total_pages", 1):
                break
            page += 1

        return by_label

    def _is_expiring(self, dt: datetime.datetime,
                     days: int = 30) -> bool:
        return dt - datetime.datetime.utcnow() < datetime.timedelta(days)

    # ----------------------------------------------------- issue / renew
    def _issue_or_renew(self, label: str, have: dict|None):
        hosts = self._hosts_for(label)
        key_p, csr_p = self._make_key_and_csr(label, hosts)

        # -------- request cert -----------
        url  = _ORIGIN_CA_ENDPOINT.format(zone=self.zone_id)
        body = {
            "csr":              csr_p.read_text(),
            "hostnames":        hosts,
            "request_type":     "origin-rsa",
            "requested_validity": _VALIDITY_DAYS
        }
        if have:                        # we are *renewing* – revoke old one first
            self._revoke(have["id"])

        r = self.cf.post(url, data=json.dumps(body), headers=self.headers)
        cert_pem = r["result"]["certificate"]

        crt = key_p.parent / "fullchain.pem"
        crt.write_text(cert_pem)
        # nginx only needs privkey + cert; intermediate is already included

        print(f"[Origin-CA]  ✅  ({label or '*'}) certificate ready")

    def _revoke(self, cert_id: str):
        url = f"{_ORIGIN_CA_ENDPOINT.format(zone=self.zone_id)}/{cert_id}"
        self.cf.delete(url, headers=self.headers)
        print(f"[Origin-CA]  ✂  revoked obsolete cert {cert_id}")

    # ------------------------------------------------ file helpers
    def _make_key_and_csr(self, label: str, hosts: list[str]) -> tuple[Path, Path]:
        target   = _SSL_DIR / (label or "_root")
        key_p    = target / "privkey.pem"
        csr_p    = target / "req.csr"

        if key_p.exists() and csr_p.exists():
            return key_p, csr_p        # reuse existing key + CSR

        target.mkdir(parents=True, exist_ok=True)
        names = ",".join(f"DNS:{h}" for h in hosts)

        subprocess.run([
            "openssl","req","-new","-newkey","rsa:2048","-nodes","-keyout",str(key_p),
            "-subj", f"/CN={hosts[0]}",
            "-addext", f"subjectAltName={names}",
            "-out", str(csr_p)
        ], check=True)

        key_p.chmod(stat.S_IRUSR | stat.S_IWUSR)   # 0600
        return key_p, csr_p

    def _hosts_for(self, label: str) -> list[str]:
        if label == "":
            return [self.domain, f"*.{self.domain}"]
        sfx = f"{label}.{self.domain}"
        return [sfx, f"*.{sfx}"]