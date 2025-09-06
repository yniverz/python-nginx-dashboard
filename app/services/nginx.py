"""
Nginx configuration generation service.
Generates nginx configuration files for HTTP/HTTPS proxying and load balancing.
"""
from requests import Session
from app.persistence import repos
from app.persistence.models import NginxRoute, NginxRouteHost, NginxRouteProtocol
from app.services.cloudflare import cloudflare_ip_cache
from app.config import settings


class NginxConfigGenerator:
    """
    Generates nginx configuration files from database route definitions.
    Creates HTTP/HTTPS server blocks with upstream load balancing.
    """
    def __init__(self, db: Session, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.generate_config()

    def generate_config(self):
        """Generate all nginx configuration files."""
        self.global_upstream_counter = 0
        self._generate_http_config()
        # Stream configuration generation is currently disabled
        # self._generate_stream_config()




    def _get_upstream_name(self):
        """Generate a unique upstream name for load balancing."""
        self.global_upstream_counter += 1
        return f"upstream_{self.global_upstream_counter}"

    def _get_upstream(self, upstream_name: str, targets: list[NginxRouteHost]):
        """
        Generate nginx upstream block for load balancing.
        Includes health check and backup server configuration.
        """
        upstream_blocks = f"upstream {upstream_name} " + "{\n"
        for target in targets:
            if not target.active:
                continue
            upstream_blocks += f"    server {target.host}"
            if target.weight is not None:
                upstream_blocks += f" weight={target.weight}"
            if target.max_fails is not None:
                upstream_blocks += f" max_fails={target.max_fails}"
            if target.fail_timeout is not None:
                upstream_blocks += f" fail_timeout={target.fail_timeout}"
            if target.is_backup:
                upstream_blocks += " backup"
            upstream_blocks += ";\n"
        upstream_blocks += "}\n"
        return upstream_blocks

    def _get_cf_ip_ranges(self):
        """
        Generate nginx configuration for Cloudflare IP ranges.
        Enables real IP detection from Cloudflare's proxy headers.
        """
        ipv4, ipv6 = cloudflare_ip_cache.get()

        ip_block = ""
        for ip in ipv4:
            if not ip.startswith("#"):
                ip_block += f"set_real_ip_from {ip};\n"
        for ip in ipv6:
            if not ip.startswith("#"):
                ip_block += f"set_real_ip_from {ip};\n"

        if ip_block:
            ip_block += "\n"
            ip_block += "real_ip_header CF-Connecting-IP;\n"
            ip_block += "real_ip_recursive on;\n"
                
        return ip_block
    

    # def _ensure_selfsigned_cert(self, first_label: str, domain: str) -> tuple[str, str]:
    #     """
    #     Make sure /etc/nginx/ssl/<first>.<domain>/{fullchain,privkey}.pem exist.
    #     Returns (crt_path, key_path).  Idempotent & thread-safe.
    #     """
    #     target_dir = Path(f"/etc/nginx/ssl/{first_label}.{domain}")
    #     crt = target_dir / "fullchain.pem"
    #     key = target_dir / "privkey.pem"

    #     if crt.exists() and key.exists():
    #         # refresh every 5 years just for good measure
    #         ts = datetime.datetime.fromtimestamp(crt.stat().st_mtime)
    #         if (datetime.datetime.utcnow() - ts).days < 5*365:
    #             return str(crt), str(key)

    #     target_dir.mkdir(parents=True, exist_ok=True)

    #     def _run():
    #         tmp_crt = crt.with_suffix(".tmp")
    #         tmp_key = key.with_suffix(".tmp")
    #         subprocess.run([
    #             "openssl", "req", "-x509", "-nodes",
    #             "-newkey", "rsa:2048", "-days", "3650",
    #             "-subj", f"/CN=*.{first_label}.{domain}",
    #             "-addext", f"subjectAltName=DNS:{first_label}.{domain},DNS:*.{first_label}.{domain}",
    #             "-keyout", str(tmp_key), "-out", str(tmp_crt)
    #         ], check=True)
    #         os.rename(tmp_crt, crt)
    #         os.rename(tmp_key, key)

    #     # fire-and-forget so UI stays snappy
    #     threading.Thread(target=_run, daemon=True).start()
    #     return str(crt), str(key)


    def _generate_http_config(self):
        """
        Generate the main HTTP configuration file.
        Creates HTTP to HTTPS redirects and HTTPS server blocks with SSL.
        """
        domains = repos.DomainRepo(self.db).list_all()

        # Start with global configuration
        config = f"""
map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

{self._get_cf_ip_ranges()}

"""
        # Generate HTTP to HTTPS redirects for all domains
        for domain in domains:
            routes = repos.NginxRouteRepo(self.db).list_by_domain(domain.id)
            if not any(r.active for r in routes):
                continue

            config += f"""
server {{
    listen 80;
    server_name {domain.name} *.{domain.name};
    return 301 https://$host$request_uri;
}}
"""
            
        # Generate HTTPS server blocks with SSL and proxying
        config += self._generate_http_subdomain_blocks()

        # Write configuration to file unless in dry run mode
        if not self.dry_run:
            with open(settings.NGINX_HTTP_CONF_PATH, 'w') as http_config_file:
                http_config_file.write(config)

    def _generate_http_subdomain_blocks(self):   
        """
        Generate HTTPS server blocks for each subdomain with SSL certificates.
        Groups routes by subdomain and creates server blocks with upstream load balancing.
        """
        subdomain_blocks = ""

        routes = repos.NginxRouteRepo(self.db).list_all_active()

        # Group routes by subdomain
        subdomains = {}
        for route in routes:
            subdomains.setdefault(route.subdomain, []).append(route)

        for subdomain, routes in subdomains.items():
            path_blocks, upstream_blocks = self._generate_http_path_blocks(routes)

            # Determine SSL certificate path based on subdomain structure
            if subdomain in ("@", "") or "." not in subdomain:
                label_key = ""
            else:
                # For multi-level subdomains, use the parent domain for wildcard cert
                label_key = ".".join(subdomain.split(".")[1:]) + "."

            dir_name = f"{label_key}{route.domain.name}"
            crt_path = f"/etc/nginx/ssl/{dir_name}/fullchain.pem"
            key_path = f"/etc/nginx/ssl/{dir_name}/privkey.pem"

            # Generate HTTPS server block with SSL and proxy configuration
            subdomain_blocks += f"""
{upstream_blocks}
server {{
    listen 443 ssl;
    server_name {subdomain + '.' + route.domain.name if subdomain != '@' else route.domain.name};
    ssl_certificate     {crt_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /robots.txt {{
        default_type text/plain;
        return 200 "User-agent: *\nDisallow: /";
    }}

    {path_blocks}
}}
"""
        return subdomain_blocks

    def _generate_http_path_blocks(self, routes: list[NginxRoute]):
        """
        Generate nginx location blocks for proxying requests to backends.
        Handles both redirect and proxy protocols with proper header forwarding.
        """
        proxy_blocks = ""
        upstream_blocks = ""

        for route in routes:
            path = route.path_prefix if route.path_prefix.startswith("/") else f"/{route.path_prefix}"

            if route.protocol == NginxRouteProtocol.REDIRECT:
                # Simple redirect to first host
                host = route.hosts[0] if route.hosts else None
                if host:
                    proxy_blocks += f"""
location {path} {{
    proxy_pass {host};
}}
"""
                    continue

            # Create upstream for load balancing
            upstream_name = self._get_upstream_name()
            protocol = "http://" if route.protocol == NginxRouteProtocol.HTTP else "https://"
            backend_path = route.backend_path
            upstream_blocks += self._get_upstream(upstream_name, route.hosts)

            # Generate path rewriting and proxy headers
            rewrite = "" if route.path_prefix == "/" else f"rewrite ^{route.path_prefix}(.*)$ /$1 break;"
            backend_path_header = f"proxy_set_header X-Forwarded-Prefix {route.path_prefix};" if route.path_prefix else ""
            
            proxy_blocks += f"""
    location {path} {{
        {rewrite}
        proxy_pass {protocol}{upstream_name}{backend_path};
        proxy_redirect http:// https://;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        {backend_path_header}
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }}
    """
        return proxy_blocks, upstream_blocks





#     def _generate_stream_config(self):
#         stream_config = ""

#         self.cloudflare_srv_map = []

#         for subdomain in self.proxy_map["stream"].keys():
#             for port, data in self.proxy_map["stream"][subdomain].items():
#                 if not data["active"]:
#                     continue

#                 if data["type"] == "proxy":
#                     upstream_name = self._get_upstream_name()
#                     upstream_blocks = self._get_upstream(upstream_name, data["targets"])
                    
#                     stream_config += f"""
# {upstream_blocks}
# server {{
#     listen {port};
#     server_name {subdomain + '.' + self.domain if subdomain != '@' else self.domain};
#     proxy_pass {upstream_name};
#     proxy_timeout 10s;
#     proxy_connect_timeout 10s;
# }}
# """
                    
#         # create path recursive directory if it does not exist
#         os.makedirs(os.path.dirname(self.stream_config_path), exist_ok=True)

#         with open(self.stream_config_path, 'w') as stream_config_file:
#             stream_config_file.write(stream_config)
