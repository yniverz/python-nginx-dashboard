import os
import time
from typing import Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Domain, CertBundle
from app.providers.cloudflare import CloudflareOriginCAClient

class CertService:
    def __init__(self, db: Session):
        self.db = db
        self.cf_origin = CloudflareOriginCAClient()

    def _paths(self, domain_name: str) -> tuple[str,str]:
        base = os.path.join(settings.CERTS_DIR, domain_name)
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "fullchain.pem"), os.path.join(base, "privkey.pem")

    async def ensure_origin_ca(self, domain: Domain) -> CertBundle:
        """
        Ensure an Origin CA certificate exists on disk for domain (domain + *.domain).
        Stores/updates a CertBundle row.
        """
        fullchain_path, privkey_path = self._paths(domain.name)

        # if files already exist, trust them (you can extend to reissue on expiry)
        if os.path.exists(fullchain_path) and os.path.exists(privkey_path):
            # upsert DB row if missing
            bundle = self.db.query(CertBundle).filter_by(domain_id=domain.id, label="").first()
            if not bundle:
                bundle = CertBundle(domain_id=domain.id, label="", fullchain_path=fullchain_path, privkey_path=privkey_path, expires_on=None)
                self.db.add(bundle); self.db.commit(); self.db.refresh(bundle)
            return bundle

        # issue new
        hostnames = [domain.name, f"*.{domain.name}"]
        result = await self.cf_origin.create_certificate(hostnames)
        cert_pem = result.get("certificate")
        priv_pem = result.get("private_key")
        expires_on = None
        # write
        with open(fullchain_path, "w") as f: f.write(cert_pem)
        with open(privkey_path, "w") as f:
            os.chmod(privkey_path, 0o600)
            f.write(priv_pem)

        bundle = self.db.query(CertBundle).filter_by(domain_id=domain.id, label="").first()
        if bundle:
            bundle.fullchain_path = fullchain_path
            bundle.privkey_path = privkey_path
            bundle.expires_on = expires_on
        else:
            bundle = CertBundle(domain_id=domain.id, label="", fullchain_path=fullchain_path, privkey_path=privkey_path, expires_on=expires_on)
            self.db.add(bundle)
        self.db.commit(); self.db.refresh(bundle)
        return bundle
