import json
import os
import subprocess
from dataclasses import dataclass
from core.cloudflare import CloudFlareMapEntry, CloudFlareSRVManager


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
    def __init__(self, config_path, stream_config_path, domain, ssl_cert_path, ssl_cert_key_path, json_path, cloudflare_token):
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

        self.cf = CloudFlareSRVManager(cloudflare_token, self.domain)
        self.cloudflare_srv_map: list[CloudFlareMapEntry] = []

        self.global_upstream_counter = 0

        if os.path.exists(self.json_path):
            self.load_from_json()

    def reload_nginx(self):
        self.generate_config()

        subprocess.call(['systemctl', 'restart', 'nginx'])

        if len(self.cloudflare_srv_map) > 0:
            self.cf.ensure_srv_records(self.cloudflare_srv_map)
    
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
            entry["srv_record"] = True

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

    def update_http_proxy_targets(self, subdomain: str, path: str, protocol: str, backend_path: str, targets: list[ProxyTarget]):
        if subdomain not in self.proxy_map["http"]:
            return
        if path not in self.proxy_map["http"][subdomain]:
            return

        self.proxy_map["http"][subdomain][path]["targets"] = [target.to_json() for target in targets]
        self.proxy_map["http"][subdomain][path]["protocol"] = protocol
        self.proxy_map["http"][subdomain][path]["path"] = backend_path

        self.save_to_json()
        self.generate_config()

    def update_stream_proxy_targets(self, subdomain: str, port: int, targets: list[ProxyTarget], srv_record: bool = None):
        if subdomain not in self.proxy_map["stream"]:
            return
        if str(port) not in self.proxy_map["stream"][subdomain]:
            return

        self.proxy_map["stream"][subdomain][str(port)]["targets"] = [target.to_json() for target in targets]
        if srv_record is not None:
            self.proxy_map["stream"][subdomain][str(port)]["srv_record"] = srv_record
        elif "srv_record" in self.proxy_map["stream"][subdomain][str(port)]:
            del self.proxy_map["stream"][subdomain][str(port)]["srv_record"]

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




    def _generate_http_config(self):
        config = f"""
map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

server {{
    listen 80;
    server_name {self.domain} *.{self.domain};
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
            
            subdomain_blocks += f"""
{upstream_blocks}
server {{
    listen 443 ssl;
    server_name {subdomain + '.' + self.domain if subdomain != '@' else self.domain};
    ssl_certificate {self.ssl_cert_path};
    ssl_certificate_key {self.ssl_cert_key_path};
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
                srv_record = data.get("srv_record", False)
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

        with open(self.stream_config_path, 'w') as stream_config_file:
            stream_config_file.write(stream_config)
