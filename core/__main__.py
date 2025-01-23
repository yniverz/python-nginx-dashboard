
import json
import threading
import time
import traceback

import dns.resolver
from core.nginx import NginxConfigManager
from core.webserver import ProxyManager



def get_dns(domain: str):
    answers = dns.resolver.resolve(domain,'A')
    return answers[0].address

def dns_watcher(config_manager: NginxConfigManager, domain: str):
    domain = domain
    ip = get_dns(domain)
    print(f'Home IP: {ip}')

    time.sleep(60)

    while True:
        try:
            new_ip = get_dns(domain)
            if new_ip != ip:
                print(f'New IP: {new_ip}')
                ip = new_ip

                try:
                    config_manager.reload_nginx()
                except Exception as e:
                    print(traceback.format_exc())

        except Exception as e:
            print(e)

        time.sleep(60)




if __name__ == '__main__':
    # read config from json
    with open('config.json', 'r') as f:
        config = json.load(f)




    DOMAIN = config['domain']
    config_manager = NginxConfigManager(
        config_path='/etc/nginx/conf.d/'+ DOMAIN + '.conf',
        stream_config_path='/etc/nginx/conf.stream.d/' + DOMAIN + '.conf',
        domain=DOMAIN,
        ssl_cert_path='/etc/letsencrypt/live/' + DOMAIN + '/fullchain.pem',
        ssl_cert_key_path='/etc/letsencrypt/live/' + DOMAIN + '/privkey.pem',
        json_path=config['proxy_map_path'],
        cloudflare_token=config['cloudflare_token'],
    )

    thread = threading.Thread(target=dns_watcher, args=(config_manager,))
    thread.start()

    proxy_manager = ProxyManager(
        config_manager, 
        config["application_root"] if "application_root" in config else "/",
        config["username"], 
        config["password"], 
        config["allowed_api_keys"] if "allowed_api_keys" in config else [])
    proxy_manager.run()