import datetime
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from cryptography import x509
from cryptography.hazmat.backends import default_backend

from app.config import settings
from app.persistence import repos


@dataclass
class CertificateInfo:
    """Information about a certificate on disk."""
    domain: str
    cert_path: Path
    key_path: Path
    expires: datetime.datetime
    issuer: str
    
    @property
    def days_until_expiry(self) -> int:
        """Calculate days until certificate expires."""
        delta = self.expires - datetime.datetime.now(datetime.timezone.utc)
        return max(0, delta.days)
    
    @property
    def is_expired(self) -> bool:
        """Check if certificate has expired."""
        return datetime.datetime.now(datetime.timezone.utc) >= self.expires
    
    @property
    def needs_renewal(self) -> bool:
        """Check if certificate needs renewal based on configured threshold."""
        return self.days_until_expiry <= settings.LE_RENEW_SOON


class LetsEncryptManager:
    """
    Manages SSL certificates from Let's Encrypt using certbot.
    Handles certificate creation, renewal, and validation via certbot CLI.
    """

    def __init__(self, db: requests.Session, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self._ensure_directories()
        self._check_certbot()

    def _check_certbot(self):
        """Check if certbot is installed."""
        try:
            subprocess.run(['certbot', '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError(
                "certbot not found. Please install it: sudo apt install certbot"
            )

    def _ensure_directories(self):
        """Create necessary directories for ACME challenges."""
        Path(settings.LE_ACME_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.LE_SSL_DIR).mkdir(parents=True, exist_ok=True)

    def _get_certbot_base_cmd(self) -> list[str]:
        """Get base certbot command with common options."""
        cmd = [
            'certbot', 'certonly',
            '--webroot',
            '-w', settings.LE_ACME_DIR,
            '--email', settings.LE_EMAIL,
            '--agree-tos',
            '--non-interactive',
            '--config-dir', settings.LE_SSL_DIR,
            '--work-dir', f'{settings.LE_SSL_DIR}/work',
            '--logs-dir', f'{settings.LE_SSL_DIR}/logs',
        ]
        
        if not settings.LE_PRODUCTION:
            cmd.append('--staging')
        
        return cmd

    def sync(self):
        """
        Synchronize certificates for all managed domains.
        Creates new certificates or renews expiring ones.
        """
        if not settings.LE_EMAIL:
            print("[Let's Encrypt] LE_EMAIL not configured, skipping certificate sync")
            return

        domains = self._get_domains_to_manage()
        print(f"[Let's Encrypt] Managing certificates for {len(domains)} domains")
        
        for domain_name, subdomains in domains.items():
            self._sync_domain(domain_name, subdomains)

    def _get_domains_to_manage(self) -> dict[str, set[str]]:
        """
        Get domains and subdomains that need Let's Encrypt certificates.
        Groups subdomains by their parent domain.
        """
        domains = repos.DomainRepo(self.db).list_all()
        domain_subdomains: dict[str, set[str]] = {}

        for domain in domains:
            routes = repos.NginxRouteRepo(self.db).list_by_domain(domain.id)
            active_routes = [r for r in routes if r.active]
            
            if not active_routes:
                continue

            domain_subdomains[domain.name] = set()
            
            for route in active_routes:
                subdomain = route.subdomain
                # Handle root domain
                if subdomain in ("@", ""):
                    domain_subdomains[domain.name].add(domain.name)
                # Handle wildcard subdomains
                elif "*" in subdomain:
                    # Let's Encrypt supports wildcards but requires DNS-01 challenge
                    # For now, skip wildcards or use the parent domain
                    domain_subdomains[domain.name].add(f"*.{domain.name}")
                # Handle regular subdomains
                else:
                    fqdn = f"{subdomain}.{domain.name}"
                    domain_subdomains[domain.name].add(fqdn)

        return domain_subdomains

    def _sync_domain(self, domain_name: str, subdomains: set[str]):
        """
        Synchronize certificates for a specific domain and its subdomains.
        """
        print(f"[Let's Encrypt] Processing domain: {domain_name}")
        
        # Filter out wildcards (would need DNS-01 challenge)
        non_wildcard_subdomains = [s for s in subdomains if not s.startswith("*")]
        
        if not non_wildcard_subdomains:
            print(f"  ! No non-wildcard subdomains for {domain_name}, skipping")
            return
        
        # Check if certificate exists and is valid
        cert_info = self._get_certificate_info(domain_name)
        
        if cert_info and not cert_info.needs_renewal:
            print(f"  ✓ {domain_name}: valid until {cert_info.expires.strftime('%Y-%m-%d')} "
                  f"({cert_info.days_until_expiry} days)")
            return
        
        if cert_info and cert_info.needs_renewal:
            print(f"  ⟳ {domain_name}: expires in {cert_info.days_until_expiry} days, renewing...")
        else:
            print(f"  + {domain_name}: no valid certificate, creating...")
        
        # Create or renew certificate
        self._create_certificate(domain_name, non_wildcard_subdomains)

    def _get_certificate_info(self, domain_name: str) -> Optional[CertificateInfo]:
        """
        Get information about an existing certificate.
        Returns None if certificate doesn't exist or is invalid.
        """
        cert_dir = Path(settings.LE_SSL_DIR, "live", domain_name)
        cert_path = cert_dir / "fullchain.pem"
        key_path = cert_dir / "privkey.pem"
        
        if not cert_path.exists() or not key_path.exists():
            return None
        
        try:
            with open(cert_path, 'rb') as f:
                cert_data = f.read()
                cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            
            # Extract expiration date
            expires = cert.not_valid_after_utc
            
            # Extract issuer
            issuer_attrs = cert.issuer.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
            issuer = issuer_attrs[0].value if issuer_attrs else "Unknown"
            
            return CertificateInfo(
                domain=domain_name,
                cert_path=cert_path,
                key_path=key_path,
                expires=expires,
                issuer=issuer
            )
        except Exception as e:
            print(f"  ! Error reading certificate for {domain_name}: {e}")
            return None

    def _create_certificate(self, primary_domain: str, domains: list[str]):
        """
        Create or renew a certificate using certbot.
        If initial attempt fails, retries with HTTP-only nginx config.
        """
        if self.dry_run:
            print(f"  [DRY RUN] Would create certificate for: {', '.join(domains)}")
            return
        
        # Try to create certificate with current nginx config
        success = self._run_certbot(primary_domain, domains)
        
        if success:
            return
        
        # If failed, try with HTTP-only nginx config
        print(f"  ⚠ Initial certbot attempt failed, retrying with HTTP-only nginx config...")
        success = self._retry_with_http_only_config(primary_domain, domains)
        
        if not success:
            raise RuntimeError(f"Certbot failed even with HTTP-only config for {primary_domain}")

    def _run_certbot(self, primary_domain: str, domains: list[str]) -> bool:
        """
        Run certbot to obtain a certificate.
        Returns True if successful, False otherwise.
        """
        try:
            cmd = self._get_certbot_base_cmd()
            
            # Add certificate name
            cmd.extend(['--cert-name', primary_domain])
            
            # Add all domains
            for domain in sorted(domains):
                cmd.extend(['-d', domain])
            
            # Force renewal if certificate exists
            cmd.append('--force-renewal')
            
            print(f"  Running certbot: {' '.join(cmd)}")
            
            # Run certbot
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                print(f"  ✓ Certificate created successfully for: {', '.join(domains)}")
                return True
            else:
                print(f"  ✗ Certbot failed with exit code {result.returncode}")
                if result.stdout:
                    print(f"  stdout: {result.stdout}")
                if result.stderr:
                    print(f"  stderr: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"  ✗ Certbot timed out after 5 minutes")
            return False
        except Exception as e:
            print(f"  ✗ Error running certbot for {primary_domain}: {e}")
            return False

    def _retry_with_http_only_config(self, primary_domain: str, domains: list[str]) -> bool:
        """
        Retry certbot with a temporary HTTP-only nginx configuration.
        This helps when SSL config is blocking ACME challenges.
        """
        from app.services.nginx import NginxConfigGenerator
        
        backup_config_path = f"{settings.NGINX_HTTP_CONF_PATH}.backup"
        
        try:
            # Backup current nginx config
            if Path(settings.NGINX_HTTP_CONF_PATH).exists():
                print(f"  📋 Backing up nginx config to {backup_config_path}")
                subprocess.run(
                    ['cp', settings.NGINX_HTTP_CONF_PATH, backup_config_path],
                    check=True
                )
            
            # Generate HTTP-only nginx config
            print(f"  🔧 Generating HTTP-only nginx config...")
            self._generate_http_only_nginx_config()
            
            # Reload nginx
            print(f"  🔄 Reloading nginx with HTTP-only config...")
            result = subprocess.run(
                settings.NGINX_RELOAD_CMD.split(" "),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"  ✗ Nginx reload failed: {result.stderr}")
                self._restore_nginx_config(backup_config_path)
                return False
            
            # Retry certbot with HTTP-only config
            print(f"  🔁 Retrying certbot with HTTP-only config...")
            success = self._run_certbot(primary_domain, domains)

            # Restore original nginx config
            if Path(backup_config_path).exists():
                print(f"  📥 Restoring original nginx config...")
                self._restore_nginx_config(backup_config_path)
                
                # Reload nginx with restored config
                print(f"  🔄 Reloading nginx with full config...")
                subprocess.run(settings.NGINX_RELOAD_CMD.split(" "), check=False)
            
            return success
            
        except Exception as e:
            print(f"  ✗ Error during HTTP-only retry: {e}")
            # Try to restore backup
            if Path(backup_config_path).exists():
                self._restore_nginx_config(backup_config_path)
                subprocess.run(settings.NGINX_RELOAD_CMD.split(" "), check=False)
            return False

    def _generate_http_only_nginx_config(self):
        """
        Generate a temporary HTTP-only nginx configuration for ACME challenges.
        This config only serves HTTP traffic and ACME challenges, no HTTPS.
        """
        from app.persistence.db import DBSession
        
        with DBSession() as db:
            domains = repos.DomainRepo(db).list_all()
            
            # Start with global configuration
            config = f"""
map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

"""
            
            # Generate HTTP-only server blocks for all domains
            for domain in domains:
                routes = repos.NginxRouteRepo(db).list_by_domain(domain.id)
                if not any(r.active for r in routes):
                    continue

                config += f"""
server {{
    listen 80;
    server_name {domain.name} *.{domain.name};
    
    # ACME challenge location for Let's Encrypt
    location /.well-known/acme-challenge/ {{
        alias {settings.LE_ACME_DIR}/;
        try_files $uri =404;
    }}
    
    # Temporary: serve all traffic over HTTP (no HTTPS redirect)
    location / {{
        return 200 'ACME challenge mode - certificate generation in progress';
        add_header Content-Type text/plain;
    }}
}}
"""
            
            # Write temporary HTTP-only config
            with open(settings.NGINX_HTTP_CONF_PATH, 'w') as f:
                f.write(config)
            print(f"  ✓ HTTP-only nginx config written to {settings.NGINX_HTTP_CONF_PATH}")

    def _restore_nginx_config(self, backup_path: str):
        """Restore nginx config from backup."""
        return # FIXME: OPnly for Debugging, remove this line to enable restore functionality
        try:
            subprocess.run(['mv', backup_path, settings.NGINX_HTTP_CONF_PATH], check=True)
            print(f"  ✓ Nginx config restored from backup")
        except Exception as e:
            print(f"  ✗ Error restoring nginx config: {e}")

    def get_certificate_path(self, domain_name: str, subdomain: str) -> tuple[str, str]:
        """
        Get the certificate and key paths for a given domain and subdomain.
        Returns (cert_path, key_path).
        """
        # Certbot uses the primary domain name for the cert directory
        # For subdomains, we need to find which cert contains this subdomain
        cert_dir = Path(settings.LE_SSL_DIR, "live", domain_name)
        cert_path = cert_dir / "fullchain.pem"
        key_path = cert_dir / "privkey.pem"
        
        return str(cert_path), str(key_path)

    def list_certificates(self) -> list[CertificateInfo]:
        """
        List all managed certificates with their status.
        Returns list of CertificateInfo objects.
        """
        certificates = []
        live_dir = Path(settings.LE_SSL_DIR, "live")
        
        if not live_dir.exists():
            return certificates
        
        for cert_dir in live_dir.iterdir():
            if not cert_dir.is_dir() or cert_dir.name == "README":
                continue
            
            cert_info = self._get_certificate_info(cert_dir.name)
            if cert_info:
                certificates.append(cert_info)
        
        return sorted(certificates, key=lambda c: c.expires)

    def revoke_certificate(self, domain_name: str):
        """
        Revoke and delete a certificate using certbot.
        """
        if self.dry_run:
            print(f"[DRY RUN] Would revoke certificate: {domain_name}")
            return
        
        try:
            cmd = [
                'certbot', 'delete',
                '--cert-name', domain_name,
                '--non-interactive',
                '--config-dir', settings.LE_SSL_DIR,
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"[Let's Encrypt] Certificate deleted: {domain_name}")
            else:
                print(f"[Let's Encrypt] Error deleting certificate {domain_name}: {result.stderr}")
        except Exception as e:
            print(f"[Let's Encrypt] Error deleting certificate {domain_name}: {e}")
