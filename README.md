[![License: NCPUL](https://img.shields.io/badge/license-NCPUL-blue.svg)](./LICENSE.md)

# Python NginX Dashboard

A lightweight wsgi web dashboard to configure and manage NginX Proxy configurations on the fly using Python.

## Features
- Add, edit, and remove HTTP and stream routes dynamically.
- Manage Cloudflare SRV records for stream services.
- Reload NginX configurations seamlessly.
- Secure authentication for access.
- Simple and intuitive UI.

## Installation

1. Clone this repository:
   ```sh
   git clone https://github.com/yniverz/python-nginx-dashboard
   cd python-nginx-dashboard
   ```

2. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```

3. Configure `config.json` with your domain and credentials.

## Configuration

Create a `config.json` file in the root directory with the following structure:
- `domain`: The domain name of the server.
- `application_root`: The root web path of the application behind a possible proxy. Default is `/`.
- `proxy_map_file`: The file to store the proxy map configurations. Default is `proxy_map.json`. Will be created if not found.
- `username`: The username for web authentication.
- `password`: The password for web authentication.
- `cloudflare_token`: The Cloudflare API token to manage SRV records.
- `allowed_api_keys`: A list of API keys to allow access to the API endpoints.

```json
{
    "domain": "domain.tld",
    "application_root": "/",
    "proxy_map_file": "proxy_map.json",
    "username": "username",
    "password": "password",
    "cloudflare_token": "***cf-token***",
    "allowed_api_keys": [
        "key1",
        "key2"
    ]
}
```

## Usage

Run the dashboard:
```sh
python -m core
```

The web interface will be available at `http://127.0.0.1:8080`.
