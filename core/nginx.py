import json
import os
import subprocess
from dataclasses import dataclass
from core.cloudflare import CloudFlareMapEntry, CloudFlareOriginCAManager, CloudFlareSRVManager, CloudFlareWildcardManager, CloudflareIPCache
from pathlib import Path
import subprocess, threading, os, datetime



@dataclass
class ProxyTarget:
    route: str
    weight: int = None
    max_fails: int = None
    fail_timeout: int = None
    backup: bool = False
    active: bool = True

    def to_json(self):
        return {
            "server": self.route,
            "weight": self.weight,
            "max_fails": self.max_fails,
            "fail_timeout": self.fail_timeout,
            "backup": self.backup,
            "active": self.active
        }



class NginxConfigManager:
    def __init__(self, config_path, stream_config_path, domain, ssl_cert_path, ssl_cert_key_path, json_path, cloudflare_token, origin_ca_key, origin_ips: list[str] = []):
        self.config_path = config_path
        self.stream_config_path = stream_config_path
        self.domain = domain
        self.ssl_cert_path = ssl_cert_path
        self.ssl_cert_key_path = ssl_cert_key_path
        self.json_path = json_path
        self.proxy_map = {
            "http": {},
            "stream": {}
        }

        self.cf = CloudFlareSRVManager(cloudflare_token, origin_ca_key, self.domain)
        self.cf_ip_cache = CloudflareIPCache()
        self.cloudflare_srv_map: list[CloudFlareMapEntry] = []

        self.origin_ips = origin_ips
        self.cloudflare_origin_ca_key_set = bool(origin_ca_key)
        self.cf_wildcard_mgr = CloudFlareWildcardManager(self.cf.cf,
                                                         self.cf.zone_id,
                                                         self.domain)
        self.cf_origin_ca  = CloudFlareOriginCAManager(self.cf.cf,
                                                       self.cf.zone_id,
                                                       self.domain)

        self.global_upstream_counter = 0

        if os.path.exists(self.json_path):
            self.load_from_json()

    def reload_nginx(self):
        self.generate_config()

        subprocess.call(['nginx', '-s', 'reload'], timeout=10)

        if len(self.cloudflare_srv_map) > 0:
            self.cf.ensure_srv_records(self.cloudflare_srv_map)
        
        self.cf_wildcard_mgr.sync_wildcards(self.proxy_map,
                                    origin_ips=self.origin_ips)
        
        need_labels = self.cf_wildcard_mgr.current_labels()
        self.cf_origin_ca.sync(need_labels)
    
    def save_to_json(self):
        with open(self.json_path, 'w') as json_file:
            json.dump(self.proxy_map, json_file)

    def load_from_json(self):
        with open(self.json_path, 'r') as json_file:
            self.proxy_map = json.load(json_file)



    def get_http_proxy_entry(self, protocol: str, backend_path: str, targets: list[ProxyTarget]):
        newDict = self.get_stream_proxy_entry(targets)
        newDict.update({"protocol": protocol, "path": backend_path})
        return newDict

    def get_stream_proxy_entry(self, targets: list[ProxyTarget]):
        return {
            "type": "proxy",
            "targets": [target.to_json() for target in targets],
            "active": True
        }

    def get_http_redirect_path_entry(self, route: str):
        return {
            "type": "redirect",
            "route": route,
            "active": True
        }


    def add_http_proxy(self, subdomain: str, path: str, protocol: str, backend_path: str, targets: list[ProxyTarget]):
        if path == "/robots.txt":
            return

        routes = []
        for target in targets:
            if target.route in routes:
                return

            routes.append(target.route)
        
        if subdomain not in self.proxy_map["http"]:
            self.proxy_map["http"][subdomain] = {}

        self.proxy_map["http"][subdomain][path] = self.get_http_proxy_entry(protocol, backend_path, targets)
        self.save_to_json()
        self.generate_config()

    def add_stream_proxy(self, subdomain: str, port: int, targets: list[ProxyTarget], srv_record: bool = False):
        routes = []
        for target in targets:
            if target.route in routes:
                return

            routes.append(target.route)
        
        if subdomain not in self.proxy_map["stream"]:
            self.proxy_map["stream"][subdomain] = {}

        entry = self.get_stream_proxy_entry(targets)
        if srv_record:
            entry["srv_record"] = srv_record

        self.proxy_map["stream"][subdomain][str(port)] = entry
        self.save_to_json()
        self.generate_config()


    def _remove_proxy(self, serverType: str, subdomain: str, path: str):
        if subdomain not in self.proxy_map[serverType]:
            return

        if path not in self.proxy_map[serverType][subdomain]:
            return
        
        del self.proxy_map[serverType][subdomain][path]
        if len(self.proxy_map[serverType][subdomain]) == 0:
            del self.proxy_map[serverType][subdomain]

        self.save_to_json()
        self.generate_config()

    def remove_http_proxy(self, subdomain: str, path: str):
        self._remove_proxy("http", subdomain, path)

    def remove_stream_proxy(self, subdomain: str, port: int):
        self._remove_proxy("stream", subdomain, str(port))




    def add_redirect(self, subdomain: str, path: str, route: str):
        if path == "/robots.txt":
            return
        
        if subdomain not in self.proxy_map["http"]:
            self.proxy_map["http"][subdomain] = {}

        self.proxy_map["http"][subdomain][path] = self.get_http_redirect_path_entry(route)
        self.save_to_json()
        self.generate_config()

    def update_http_proxy_targets(self, subdomain: str, path: str, protocol: str, backend_path: str, targets: list[ProxyTarget], new_subdomain: str = None):
        if subdomain not in self.proxy_map["http"]:
            return
        if path not in self.proxy_map["http"][subdomain]:
            return

        self.proxy_map["http"][subdomain][path]["targets"] = [target.to_json() for target in targets]
        self.proxy_map["http"][subdomain][path]["protocol"] = protocol
        self.proxy_map["http"][subdomain][path]["path"] = backend_path

        if new_subdomain is not None and new_subdomain != subdomain:
            self.proxy_map["http"][new_subdomain] = self.proxy_map["http"].pop(subdomain)

        self.save_to_json()
        self.generate_config()

    def update_stream_proxy_targets(self, subdomain: str, port: int, targets: list[ProxyTarget], srv_record: bool = None, new_subdomain: str = None):
        if subdomain not in self.proxy_map["stream"]:
            return
        if str(port) not in self.proxy_map["stream"][subdomain]:
            return

        self.proxy_map["stream"][subdomain][str(port)]["targets"] = [target.to_json() for target in targets]
        if srv_record is not None:
            self.proxy_map["stream"][subdomain][str(port)]["srv_record"] = srv_record
        elif "srv_record" in self.proxy_map["stream"][subdomain][str(port)]:
            del self.proxy_map["stream"][subdomain][str(port)]["srv_record"]

        if new_subdomain is not None and new_subdomain != subdomain:
            self.proxy_map["stream"][new_subdomain] = self.proxy_map["stream"].pop(subdomain)

        self.save_to_json()
        self.generate_config()


    def set_active(self, serverType: str, subdomain: str, path: str, active: bool):
        if subdomain not in self.proxy_map[serverType]:
            return
                
        if path not in self.proxy_map[serverType][subdomain]:
            return

        self.proxy_map[serverType][subdomain][path]["active"] = active
        self.save_to_json()
        self.generate_config()

    def set_active_proxy_target(self, serverType: str, subdomain: str, path: str, target_route: str, active: bool):
        if subdomain not in self.proxy_map[serverType]:
            return
                
        if path not in self.proxy_map[serverType][subdomain]:
            return

        if self.proxy_map[serverType][subdomain][path]["type"] != "proxy":
            return
        
        # Extract the targets for this path
        targets = self.proxy_map[serverType][subdomain][path]["targets"]
        
        # Find the target with the specified route
        target_to_edit = next((t for t in targets if t["route"] == target_route), None)
        
        if not target_to_edit:
            return
        
        # Edit the target in the list
        target_to_edit["active"] = active

        # Save the updated configuration
        self.save_to_json()
        self.generate_config()










    def generate_config(self):
        self.global_upstream_counter = 0
        self._generate_http_config()
        self._generate_stream_config()




    def _get_upstream_name(self):
        self.global_upstream_counter += 1
        return f"upstream_{self.global_upstream_counter}"

    def _get_upstream(self, upstream_name: str, targets: dict):
        upstream_blocks = f"upstream {upstream_name} " + "{\n"
        for target in targets:
            upstream_blocks += f"    server {target['server']}"
            if target["weight"] is not None:
                upstream_blocks += f" weight={target['weight']}"
            if target["max_fails"] is not None:
                upstream_blocks += f" max_fails={target['max_fails']}"
            if target["fail_timeout"] is not None:
                upstream_blocks += f" fail_timeout={target['fail_timeout']}"
            if target.get("backup", False):
                upstream_blocks += " backup"
            upstream_blocks += ";\n"
        upstream_blocks += "}\n"
        return upstream_blocks


    def _get_cf_ip_ranges(self):
        ipv4, ipv6 = self.cf_ip_cache.get()

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
    

    def _ensure_selfsigned_cert(self, first_label: str, domain: str) -> tuple[str, str]:
        """
        Make sure /etc/nginx/ssl/<first>.<domain>/{fullchain,privkey}.pem exist.
        Returns (crt_path, key_path).  Idempotent & thread-safe.
        """
        target_dir = Path(f"/etc/nginx/ssl/{first_label}.{domain}")
        crt = target_dir / "fullchain.pem"
        key = target_dir / "privkey.pem"

        if crt.exists() and key.exists():
            # refresh every 5 years just for good measure
            ts = datetime.datetime.fromtimestamp(crt.stat().st_mtime)
            if (datetime.datetime.utcnow() - ts).days < 5*365:
                return str(crt), str(key)

        target_dir.mkdir(parents=True, exist_ok=True)

        def _run():
            tmp_crt = crt.with_suffix(".tmp")
            tmp_key = key.with_suffix(".tmp")
            subprocess.run([
                "openssl", "req", "-x509", "-nodes",
                "-newkey", "rsa:2048", "-days", "3650",
                "-subj", f"/CN=*.{first_label}.{domain}",
                "-addext", f"subjectAltName=DNS:{first_label}.{domain},DNS:*.{first_label}.{domain}",
                "-keyout", str(tmp_key), "-out", str(tmp_crt)
            ], check=True)
            os.rename(tmp_crt, crt)
            os.rename(tmp_key, key)

        # fire-and-forget so UI stays snappy
        threading.Thread(target=_run, daemon=True).start()
        return str(crt), str(key)


    def _generate_http_config(self):
        config = f"""
map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

{self._get_cf_ip_ranges()}

server {{
    listen 80;
    server_name .{self.domain};
    return 301 https://$host$request_uri;
}}

{self._generate_http_subdomain_blocks()}
"""

        with open(self.config_path, 'w') as config_file:
            config_file.write(config)

    def _generate_http_subdomain_blocks(self):   
        subdomain_blocks = ""
        for subdomain in self.proxy_map["http"].keys():
            path_blocks, upstream_blocks = self._generate_http_path_blocks(subdomain)

            crt_path = self.ssl_cert_path
            key_path = self.ssl_cert_key_path

            if self.cloudflare_origin_ca_key_set:
                # ---------- 2. choose cert/key path ----------
                if subdomain in ("@", "") or "." not in subdomain:
                    label_key = ""                    # → _root
                else:
                    label_key = ".".join(subdomain.split(".")[1:])  # drop first label

                dir_name = (label_key or "_root") + f".{self.domain}"
                # /etc/nginx/ssl/_root.{domain}/fullchain.pem
                crt_path = f"/etc/nginx/ssl/{dir_name}/fullchain.pem"
                key_path = f"/etc/nginx/ssl/{dir_name}/privkey.pem"

            elif not crt_path or not key_path:
                crt_path, key_path = self._ensure_selfsigned_cert(subdomain.split('.')[-1], self.domain)

            subdomain_blocks += f"""
{upstream_blocks}
server {{
    listen 443 ssl;
    server_name {subdomain + '.' + self.domain if subdomain != '@' else self.domain};
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

    def _generate_http_path_blocks(self, subdomain: str):
        proxy_blocks = ""
        upstream_blocks = ""
        for path, data in self.proxy_map["http"][subdomain].items():
            if not data["active"]:
                continue
            
            if data["type"] == "redirect": # 307: Temporary Redirect
                proxy_blocks += f"""
    location {path} {{
        return 307 {data["route"]};
    }}
    """
                continue
            
            if data["type"] == "proxy":
                upstream_name = self._get_upstream_name()
                protocol = data["protocol"]
                backend_path = data["path"]
                upstream_blocks += self._get_upstream(upstream_name, data["targets"])

                rewrite = "" if path == "/" else f"rewrite ^{path}(.*)$ /$1 break;"
                proxy_blocks += f"""
    location {path} {{
        {rewrite}
        proxy_pass {protocol}{upstream_name}{backend_path};
        proxy_redirect http:// https://;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }}
    """
        return proxy_blocks, upstream_blocks





    def _generate_stream_config(self):
        stream_config = ""

        self.cloudflare_srv_map = []

        for subdomain in self.proxy_map["stream"].keys():
            for port, data in self.proxy_map["stream"][subdomain].items():
                if not data["active"]:
                    continue

                # Check if srv_record is set
                srv_record = data.get("srv_record", None)
                if srv_record:
                    self.cloudflare_srv_map.append(CloudFlareMapEntry(subdomain, srv_record, int(port)))

                if data["type"] == "proxy":
                    upstream_name = self._get_upstream_name()
                    upstream_blocks = self._get_upstream(upstream_name, data["targets"])
                    
                    stream_config += f"""
{upstream_blocks}
server {{
    listen {port};
    server_name {subdomain + '.' + self.domain if subdomain != '@' else self.domain};
    proxy_pass {upstream_name};
    proxy_timeout 10s;
    proxy_connect_timeout 10s;
}}
"""
                    
        # create path recursive directory if it does not exist
        os.makedirs(os.path.dirname(self.stream_config_path), exist_ok=True)

        with open(self.stream_config_path, 'w') as stream_config_file:
            stream_config_file.write(stream_config)
