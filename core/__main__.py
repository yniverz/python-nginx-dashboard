
import json
import threading
import time
import traceback
import dns.resolver
import dns.exception
from core.autofrp import AutoFRPManager
from core.nginx import NginxConfigManager
from core.webserver import ProxyManager

resolver = dns.resolver.Resolver()
resolver.timeout   = 2.0     # per try
resolver.lifetime  = 5.0     # total
resolver.retry_servfail = True
resolver.use_edns(0)         # disables EDNS, see 17

def get_dns(domain):
    try:
        return resolver.resolve(domain, 'A', udp_size=1232)[0].address
    except (dns.resolver.NXDOMAIN, dns.exception.Timeout):
        return None

def dns_watcher(config_manager: NginxConfigManager, domains: list[str]):
    domain_store = {}

    for domain in domains:
        ip = get_dns(domain)
        domain_store[domain] = ip
        print(f'Initial IP for {domain}: {ip}')

    time.sleep(60)

    while True:
        try:
            needs_reload = False
            for domain in domains:
                new_ip = get_dns(domain)
                if new_ip != domain_store[domain]:
                    print(f'New IP for {domain}: {new_ip}')
                    domain_store[domain] = new_ip
                    needs_reload = True

            try:
                if needs_reload:
                    config_manager.reload_nginx()
            except Exception as e:
                print(traceback.format_exc())

        except Exception as e:
            print(e)

        time.sleep(300)




if __name__ == '__main__':
    # read config from json
    with open('config.json', 'r') as f:
        config = json.load(f)




    DOMAIN = config['domain']
    CHECK_DOMAINS = config['check_domains'] if 'check_domains' in config else []
    nginx_manager = NginxConfigManager(
        config_path='/etc/nginx/conf.d/'+ DOMAIN + '.conf',
        stream_config_path='/etc/nginx/conf.stream.d/' + DOMAIN + '.conf',
        domain=DOMAIN,
        ssl_cert_path='/etc/letsencrypt/live/' + DOMAIN + '/fullchain.pem',
        ssl_cert_key_path='/etc/letsencrypt/live/' + DOMAIN + '/privkey.pem',
        json_path=config['proxy_map_file'],
        cloudflare_token=config['cloudflare_token'],
    )

    frp_manager = AutoFRPManager(config['gateway_proxy_map_file'])

    if CHECK_DOMAINS:
        thread = threading.Thread(target=dns_watcher, args=(nginx_manager, CHECK_DOMAINS))
        thread.start()

    proxy_manager = ProxyManager(
        nginx_manager,
        frp_manager,
        config["application_root"] if "application_root" in config else "/",
        config["username"], 
        config["password"], 
        config["allowed_api_keys"] if "allowed_api_keys" in config else [])
    proxy_manager.run()