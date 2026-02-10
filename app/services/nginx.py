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
        self._generate_stream_config()




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
    
    # ACME challenge location for Let's Encrypt
    location /.well-known/acme-challenge/ {{
        alias {settings.LE_ACME_DIR}/;
        try_files $uri =404;
    }}
    
    # Redirect all other traffic to HTTPS
    location / {{
        return 301 https://$host$request_uri;
    }}
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
        Groups routes by subdomain and domain to create separate server blocks per domain.
        """
        subdomain_blocks = ""

        routes = repos.NginxRouteRepo(self.db).list_all_active()

        # Group routes by both subdomain and domain
        subdomains = {}
        for route in routes:
            key = (route.subdomain, route.domain.id)
            subdomains.setdefault(key, []).append(route)

        for (subdomain, domain_id), routes in subdomains.items():
            domain = routes[0].domain
            path_blocks, upstream_blocks = self._generate_http_path_blocks(routes)

            if len(path_blocks.strip()) == 0:
                continue

            # Determine SSL certificate path based on subdomain structure and SSL provider
            if settings.ENABLE_LETSENCRYPT:
                # Use Let's Encrypt certificates
                if subdomain in ("@", ""):
                    safe_name = domain.name
                elif subdomain.startswith("*."):
                    safe_name = f"wildcard.{domain.name}"
                elif "*" in subdomain:
                    safe_name = subdomain.replace("*.", "wildcard.").replace("*", "wildcard")
                else:
                    safe_name = f"{subdomain}.{domain.name}"
                
                crt_path = f"{settings.LE_SSL_DIR}/{safe_name}/fullchain.pem"
                key_path = f"{settings.LE_SSL_DIR}/{safe_name}/privkey.pem"
            else:
                # Use Cloudflare Origin CA certificates (default)
                if subdomain in ("@", "") or "." not in subdomain:
                    label_key = ""
                else:
                    # For multi-level subdomains, use the parent domain for wildcard cert
                    label_key = ".".join(subdomain.split(".")[1:]) + "."

                dir_name = f"{label_key}{domain.name}"
                crt_path = f"{settings.CF_SSL_DIR}/{dir_name}/fullchain.pem"
                key_path = f"{settings.CF_SSL_DIR}/{dir_name}/privkey.pem"

            # Generate HTTPS server block with SSL and proxy configuration
            subdomain_blocks += f"""
{upstream_blocks}
server {{
    listen 443 ssl;
    server_name {subdomain + '.' + domain.name if subdomain != '@' else domain.name};
    ssl_certificate     {crt_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # ACME challenge location for Let's Encrypt certificate renewal
    location /.well-known/acme-challenge/ {{
        alias {settings.LE_ACME_DIR}/;
        try_files $uri =404;
    }}

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

            if route.protocol == NginxRouteProtocol.STREAM:
                continue

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





    def _generate_stream_config(self):
        """
        Generate the NGINX stream configuration file.
        Uses path_prefix as the listen port value.
        """
        import os
        
        # Get all active routes with STREAM protocol
        routes = repos.NginxRouteRepo(self.db).list_all_active()
        stream_routes = [r for r in routes if r.protocol == NginxRouteProtocol.STREAM]
        
        if not stream_routes:
            # No stream routes found, create empty config
            if not self.dry_run:
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(settings.NGINX_STREAM_CONF_PATH), exist_ok=True)
                with open(settings.NGINX_STREAM_CONF_PATH, 'w') as stream_config_file:
                    stream_config_file.write("# No stream configurations found\n")
            return
        
        # Start with global configuration
        stream_config = ""
        
        # Generate stream server blocks for each route
        for route in stream_routes:
            # For stream configs, path_prefix is used as the port number
            try:
                # Remove any leading slash and convert to integer
                port = route.path_prefix.lstrip('/')
                port = int(port)
            except (ValueError, AttributeError):
                # Skip routes with invalid port numbers
                continue
                
            # Skip routes without active hosts
            if not any(h.active for h in route.hosts):
                continue
                
            # Create upstream for load balancing
            upstream_name = self._get_upstream_name()
            upstream_blocks = self._get_upstream(upstream_name, route.hosts)
            
            # Generate server block with proxy configuration
            stream_config += f"""
{upstream_blocks}
server {{
    listen {port};
    proxy_pass {upstream_name};
    proxy_timeout 10s;
    proxy_connect_timeout 10s;
}}
"""
        
        # Write configuration to file unless in dry run mode
        if not self.dry_run:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(settings.NGINX_STREAM_CONF_PATH), exist_ok=True)
            with open(settings.NGINX_STREAM_CONF_PATH, 'w') as stream_config_file:
                stream_config_file.write(stream_config)
