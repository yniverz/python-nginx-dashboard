[![License: NCPUL](https://img.shields.io/badge/license-NCPUL-blue.svg)](./LICENSE.md)

# Python NginX Dashboard

A lightweight wsgi web dashboard to configure and manage NginX Proxy configurations on the fly using Python.

## Features
- Add, edit, and remove HTTP and stream routes dynamically.
- Manage Cloudflare SRV records for stream services.
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