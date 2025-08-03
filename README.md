[![License: NCPUL](https://img.shields.io/badge/license-NCPUL-blue.svg)](./LICENSE.md)

# Python NginX Dashboard

A lightweight wsgi web dashboard to configure and manage NginX Proxy configurations on the fly using Python.

## Features
- Add, edit, and remove HTTP and stream routes dynamically.
- Manage Cloudflare SRV records for stream services.
- Manage Cloudflare Origin CA SSL certificates and Edge dns records.
- Manage [Auto FRP](https://github.com/yniverz/auto-frp) servers and clients.
- Reload NginX configurations seamlessly.
- Simple and intuitive UI.

## Installation

1. Clone this repository:
```sh
git clone https://github.com/yniverz/python-nginx-dashboard
cd python-nginx-dashboard
```

2. Install Service:
```sh
./install.sh
```
>**Note:** This script installs the required dependencies and sets up a virtual environment and redis. BUT The main application will still be located in the cloned repository directory, so be sure to keep it there.

3. Configure `config.json` with your domain and credentials.

## Configuration

Create a `config.json` file in the root directory with the following structure:
- `domain`: The domain name of the server.
- `check_domains`: A list of domains to check for ip changes (for dynamic DNS).
- `application_root`: The root web path of the application behind a possible proxy. Default is `/`.
- `proxy_map_file`: The file to store the proxy map configurations. Default is `proxy_map.json`. Will be created if not found.
- `username`: The username for web authentication.
- `password`: The password for web authentication.
- `cloudflare_token`: The Cloudflare API token to manage SRV records.
- `cloudflare_origin_ca_key`: The Cloudflare Origin CA key to manage SSL certificates.
- `origin_ips`: A list of IPs under which the NginX server is accessible. This is used to ensure proper dns records in CloudFlare.
- `allowed_api_keys`: A list of API keys to allow access to the API endpoints.

```json
{
    "domain": "domain.tld",
    "check_domains": [
        "dyndns.domain.tld",
        "another.domain.tld"
    ],
    "application_root": "/",
    "proxy_map_file": "proxy_map.json",
    "username": "username",
    "password": "password",
    "cloudflare_token": "***cf-token***",
    "cloudflare_origin_ca_key": "***cf-origin-ca-key***",
    "origin_ips": [
        "123.45.67.89",
        "198.51.100.1"
    ],
    "allowed_api_keys": [
        "key1",
        "key2"
    ]
}
```

### Cloudflare Configuration
Make sure to set up your Cloudflare account with the necessary permissions to manage SRV records and SSL certificates. The `cloudflare_token` should have permissions to edit DNS records and manage Origin CA certificates.

Needed Permissions for the api key:
- **Zone.DNS**: Edit
- **Zone.SSL and Certificates**: Edit

And you will need to copy the Origin CA certificate and key to the appropriate directory on your server. This can be found at [Dashboard -> Profile -> API Tokens](https://dash.cloudflare.com/profile/api-tokens).

### TLS
Activating Cloudflare will also enable Proxying and Verified TLS between Cloudflare and your server. Make sure to set the SSL/TLS encryption mode to "Full (strict)" in the Cloudflare dashboard.

If the Origin CA key is not set, the application will automatically use the provided certificates through the configuration file. You will not be able to use multiple layers of subdomains now.
 If those are not provided, it will generate self-signed certificates for the subdomains including layers of subdomains.

## Usage

The application will run deamonized in the background once installed. You can start, stop, or restart the service using:
```sh
sudo systemctl start python-nginx-dashboard
sudo systemctl stop python-nginx-dashboard
sudo systemctl restart python-nginx-dashboard
```

The web interface will be available at `http://127.0.0.1:8080`.


## certbot

There is a handy script to automatically create a certificate for the domain using certbot. This will seamlessly integrate with the NginX configuration. Just run the following command:
```sh
./cert.sh
```
This will prompt you for the domain and some other necessary info, and then create the certificate.