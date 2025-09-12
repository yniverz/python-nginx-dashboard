"""
SSL certificate generation service.
Creates self-signed certificates for the application's HTTPS support.
"""
import os
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import threading
import logging

logger = logging.getLogger(__name__)

def ensure_selfsigned_cert(cert_dir: str, domain: str = "localhost") -> tuple[str, str]:
    """
    Make sure cert_dir/{fullchain,privkey}.pem exist.
    Returns (crt_path, key_path). Idempotent & thread-safe.
    
    Args:
        cert_dir: Directory to store certificates
        domain: Domain name for the certificate (defaults to localhost)
    """
    target_dir = Path(cert_dir)
    crt = target_dir / "fullchain.pem"
    key = target_dir / "privkey.pem"

    if crt.exists() and key.exists():
        # refresh every year
        try:
            ts = datetime.fromtimestamp(crt.stat().st_mtime)
            if (datetime.now() - ts) < timedelta(days=365):
                return str(crt), str(key)
        except Exception as e:
            logger.warning(f"Error checking certificate age: {e}")

    target_dir.mkdir(parents=True, exist_ok=True)

    def _run():
        try:
            tmp_crt = crt.with_suffix(".tmp")
            tmp_key = key.with_suffix(".tmp")
            
            # Create certificate for localhost or specified domain
            san_ext = f"subjectAltName=DNS:{domain}"
            if domain != "localhost":
                san_ext += f",DNS:*.{domain}"
            
            subprocess.run([
                "openssl", "req", "-x509", "-nodes",
                "-newkey", "rsa:2048", "-days", "365",
                "-subj", f"/CN={domain}",
                "-addext", san_ext,
                "-keyout", str(tmp_key), "-out", str(tmp_crt)
            ], check=True)
            
            os.rename(tmp_crt, crt)
            os.rename(tmp_key, key)
            logger.info(f"Created self-signed certificate for {domain} in {target_dir}")
        except Exception as e:
            logger.error(f"Error generating self-signed certificate: {e}")

    # Run in a separate thread so it doesn't block the main thread
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join()  # Wait for completion to ensure certs are ready
    
    return str(crt), str(key)
