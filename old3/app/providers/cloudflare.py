import httpx
from typing import Any, Dict, List, Optional
from app.config import settings

class CloudflareDnsClient:
    def __init__(self, api_token: Optional[str]=None, api_base: Optional[str]=None):
        self.api_base = api_base or settings.CF_API_BASE
        self.token = api_token or settings.CF_API_TOKEN
        self.h = {"Authorization": f"Bearer {self.token}"}

    async def find_zone_id(self, domain: str) -> Optional[str]:
        url = f"{self.api_base}/zones"
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, headers=self.h, params={"name":domain})
            r.raise_for_status()
            data = r.json()["result"]
            return data[0]["id"] if data else None

    async def list_records(self, zone_id: str) -> List[Dict[str,Any]]:
        url = f"{self.api_base}/zones/{zone_id}/dns_records"
        results = []
        page = 1
        async with httpx.AsyncClient(timeout=30) as c:
            while True:
                r = await c.get(url, headers=self.h, params={"per_page":100,page:page})
                r.raise_for_status()
                j = r.json()
                results.extend(j["result"])
                if page >= j["result_info"]["total_pages"]: break
                page += 1
        return results

    async def create_record(self, zone_id: str, rec: Dict[str,Any]) -> Dict[str,Any]:
        url = f"{self.api_base}/zones/{zone_id}/dns_records"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers=self.h, json=rec); r.raise_for_status(); return r.json()["result"]

    async def update_record(self, zone_id: str, record_id: str, rec: Dict[str,Any]) -> Dict[str,Any]:
        url = f"{self.api_base}/zones/{zone_id}/dns_records/{record_id}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.put(url, headers=self.h, json=rec); r.raise_for_status(); return r.json()["result"]

    async def delete_record(self, zone_id: str, record_id: str) -> None:
        url = f"{self.api_base}/zones/{zone_id}/dns_records/{record_id}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(url, headers=self.h); r.raise_for_status()

class CloudflareOriginCAClient:
    """
    Uses the Origin CA key (X-Auth-User-Service-Key) to create origin server certs
    for hostnames [domain, *.domain]. The API path here reflects common usage;
    if Cloudflare adjusts endpoints over time, tweak base path accordingly.
    """
    def __init__(self, origin_ca_key: Optional[str]=None, api_base: Optional[str]=None):
        self.api_base = api_base or settings.CF_ORIGIN_CA_BASE
        self.key = origin_ca_key or settings.CF_ORIGIN_CA_KEY
        self.h = {"X-Auth-User-Service-Key": self.key}

    async def create_certificate(self, hostnames: list[str], requested_validity_days: int = 3650) -> dict:
        """
        Creates an RSA Origin CA cert+key pair (private key returned once).
        request_type: origin-rsa (provider generates key); no CSR needed.
        """
        url = f"{self.api_base}/user/origin-ca/certificate"
        payload = {
            "hostnames": hostnames,
            "request_type": "origin-rsa",
            "requested_validity": requested_validity_days
        }
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, headers=self.h, json=payload)
            r.raise_for_status()
            return r.json()["result"]  # contains certificate, private_key, expires_on
