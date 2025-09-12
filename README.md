[![License: NCPUL](https://img.shields.io/badge/license-NCPUL-blue.svg)](./LICENSE.md)

# Multi-Domain Edge Manager (Python Nginx Dashboard)

A lightweight FastAPI web app to define domains, routes, and proxy endpoints — then **publish** them by generating Nginx config, syncing **Cloudflare DNS** (and Origin-CA certs), and emitting **FRP** client/server configs. Uses SQLite, SQLAlchemy, and Jinja2.

---

## Highlights

* 🌐 Domains & DNS: user/system/imported records, archive on change, Cloudflare sync/import
* 🛣️ HTTP routes → Nginx config writer (TLS-ready paths & CF real-IP support)
* 🔒 Cloudflare Origin-CA certificates (auto issue/renew/write to `/etc/nginx/ssl/<label>/`)
* 🚇 FRP: generate **server** + **client** TOML, with per-connection options
* 🚀 One-click **Publish**: writes Nginx, syncs Cloudflare, (optionally) reloads Nginx
* 🧰 Self-contained: FastAPI + SQLite; no external DB required

---

## Quick start (dev)

```bash
git clone https://github.com/yniverz/python-nginx-dashboard
cd python-nginx-dashboard
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# create a .env (see example below)
cp .env.example .env  # if you create one; or craft your own

python run.py
# UI: http://127.0.0.1:8000  (user/pass: admin/admin)
```

### Using Stream routes
To enable STREAM protocol handling in Nginx, you need to install the appropriate module. On Debian-based systems, you can do this by installing the `libnginx-mod-stream` package. Here’s how to do it:

```bash
sudo apt update
sudo apt install libnginx-mod-stream
```

Then it needs to be enabled in your Nginx configuration.
To find the necessary module path run:

```bash
sudo find /usr/lib*/nginx/modules /etc/nginx/modules -name 'ngx_stream_module.so' 2>/dev/null
```

Once you have the path, add the following line to your main Nginx configuration file (usually located at `/etc/nginx/nginx.conf`):

```nginx
load_module /path/to/ngx_stream_module.so;
```

---

## Configuration (.env)

All settings live in `.env` (parsed by Pydantic). Common options:

```ini
# App
APP_NAME="Multi-Domain Edge Manager"
LISTEN_PORT=8000
ROOT_PATH=""                       # set if served behind a prefix
DATA_DIR="data"                    # sqlite lives here unless SQLITE_PATH set
SQLITE_PATH=""                     # absolute path overrides DATA_DIR/app.db
SESSION_SECRET="supersecret"       # set to a random string for cookie security
WEB_USERNAME="admin"
WEB_PASSWORD="admin"

# Nginx integration
ENABLE_NGINX=false                 # set true to actually write & reload
NGINX_HTTP_CONF_PATH="/etc/nginx/conf.d/edge_http.conf"
NGINX_STREAM_CONF_PATH="/etc/nginx/stream.d/edge_stream.conf"
NGINX_RELOAD_CMD="nginx -s reload"

# Cloudflare integration
ENABLE_CLOUDFLARE=false            # set true to create/sync DNS + Origin-CA
CLOUDFLARE_API_TOKEN=""            # API Token (Zone.DNS + Zone.SSL permissions)
CF_ORIGIN_CA_KEY=""                # Origin CA key (for certificate issuance)
CF_CERT_DAYS=5475                  # validity (days); default ~15 years
CF_RENEW_SOON=30                   # renew if < N days to expiry
CF_SSL_DIR="/etc/nginx/ssl"        # where certs/keys are written

# Networking
LOCAL_IP="127.0.0.1"               # used for auto FRP origin connections

# SSL Configuration
USE_SSL=false                      # set true to enable HTTPS with self-signed cert

# Debug
DEBUG_MODE=true
```

> **Permissions:** if you enable Nginx/Cloudflare, the service must be able to write to `NGINX_*_CONF_PATH` and `CF_SSL_DIR`, and `nginx -s reload` must be allowed.

### Cloudflare token scopes

> **Important:** If you want to use multiple layers of subdomains (e.g., `a.b.domain.tld`), you must purchase `Advanced Certificate Manager` from Cloudflare found under [SSL/TLS -> Edge Certificates](https://dash.cloudflare.com/?to=/:account/:zone/ssl-tls/edge-certificates). Otherwise, only single-level subdomains (e.g., `a.domain.tld`) will be supported using full to client encryption with valid certificates.

* **Zone.DNS**: Edit
* **Zone.SSL and Certificates**: Edit

---

## Install as a service (systemd)

```bash
./install.sh
# Logs: /var/log/python-nginx-dashboard/python-nginx-dashboard.log
# Manage:
sudo systemctl restart python-nginx-dashboard
sudo systemctl status  python-nginx-dashboard
```

> The script sets up a **venv** and a **systemd** service. It does **not** install Nginx for you. Make sure Nginx is present and your paths are writable.

---

## Using the UI

1. **Domains**: add your domain(s). Optionally toggle:

   * `auto_wildcard` (reserved for future use)
   * `use_for_direct_prefix` → auto-create `server.direct.<domain>` A records (unproxied)
2. **Proxies**:

   * Create a **Gateway Server** (host, bind port, auth token)
   * Create a **Gateway Client** (choose server; mark **Is Origin** if it fronts the Nginx box)
   * Optional: extra **Gateway Connections**
3. **Routes**:

   * Add HTTP(S) routes per subdomain + path, with one or more upstream hosts
4. **DNS**:

   * Manage records; imported/auto records are muted/read-only
5. **Publish** (Dashboard → Publish):

   * Writes Nginx config, syncs Cloudflare DNS, manages Origin-CA certs, and reloads Nginx (if enabled)

> The app also **imports** existing Cloudflare records into the DB (tagged `IMPORTED`) so you can see and later reconcile them.

---

## FRP configs (API)

The app emits TOML for FRP servers/clients as managed by [Auto FRP](https://github.com/yniverz/auto-frp). Use the **name** as `{id}` and pass the **server’s auth token**:

```bash
# Server config
curl -H "X-Gateway-Token: <SERVER_AUTH_TOKEN>" \
  http://<app>/api/gateway/server/<server_name>

# Client config
curl -H "X-Gateway-Token: <SERVER_AUTH_TOKEN>" \
  http://<app>/api/gateway/client/<client_name>
```

* The client config includes all active connections for that client.
* Connections flagged as inactive aren’t emitted.

---

## How publishing works (under the hood)

* **Nginx**: generates an HTTP/TLS config per domain/subdomain/path, sets CF real-IP ranges, writes to `NGINX_HTTP_CONF_PATH`.
* **DNS**:

  * Clears previously **SYSTEM**/`IMPORTED` entries in DB, (re)imports Cloudflare zone records, keeps **USER** records.
  * Ensures wildcard/`@`/multi-level subdomain A records for origin IPs when appropriate.
* **Origin-CA**:

  * Issues/renews certificates per needed label + wildcard (`label` and `*.label`), writes `fullchain.pem` + `privkey.pem` to `CF_SSL_DIR`.
* **Reload**: runs `NGINX_RELOAD_CMD` if `ENABLE_NGINX=true`.

---

### Example `.env`

```ini
LISTEN_PORT=8000
WEB_USERNAME=admin
WEB_PASSWORD=admin
SESSION_SECRET=supersecret
ENABLE_NGINX=false
ENABLE_CLOUDFLARE=false
CLOUDFLARE_API_TOKEN=
CF_ORIGIN_CA_KEY=
CF_SSL_DIR=/etc/nginx/ssl
NGINX_HTTP_CONF_PATH=/etc/nginx/conf.d/edge_http.conf
NGINX_RELOAD_CMD="nginx -s reload"
```
