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
   git clone https://github.com/your-repo/python-nginx-dashboard
   cd python-nginx-dashboard
   ```

2. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```

3. Configure `config.json` with your domain and credentials.

## Configuration

```json
{
    "domain": "domain.tld",
    "application_root": "/",
    "proxy_map_file": "proxy_map.json", // Default name
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
python -m python-nginx-dashboard
```

The web interface will be available at `http://127.0.0.1:8080`.
