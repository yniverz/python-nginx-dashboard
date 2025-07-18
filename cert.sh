#!/usr/bin/env bash
# cert.sh ── Obtain a wildcard cert via Certbot + Cloudflare DNS
#   • Prompts for base domain and API token
#   • Installs required packages
#   • Stores token in ~/.secrets/certbot/cloudflare.ini (chmod 600)
#   • Requests cert for domain and *.domain
#   • Performs a renewal dry‑run

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────
err() { echo "❌  $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null || err "Command '$1' not found. Aborting."
}

# ── Check prerequisites (must be able to sudo) ───────────────────────
need_cmd sudo
need_cmd apt

[[ $EUID -eq 0 ]] && err "Run this script as a normal user that can sudo, not as root."

# ── Ask for domain and token ─────────────────────────────────────────
read -rp "Enter base domain (e.g. example.com): " DOMAIN
[[ -z $DOMAIN || $DOMAIN != *.* ]] && err "Invalid domain."

read -rsp "Enter Cloudflare API token (no echo): " CF_TOKEN
echo
[[ -z $CF_TOKEN ]] && err "Token cannot be empty."

# ── Install certbot + Cloudflare plugin ──────────────────────────────
echo "➤ Installing certbot DNS Cloudflare plugin…"
sudo apt-get update -qq
sudo apt-get install -y certbot python3-certbot-dns-cloudflare

# ── Store token securely ─────────────────────────────────────────────
SECRET_DIR="$HOME/.secrets/certbot"
INI_FILE="$SECRET_DIR/cloudflare.ini"

mkdir -p "$SECRET_DIR"
cat > "$INI_FILE" <<EOF
dns_cloudflare_api_token = $CF_TOKEN
EOF
chmod 600 "$INI_FILE"
echo "✓ Saved token to $INI_FILE (chmod 600)."

# ── Request / renew certificate ──────────────────────────────────────
echo "➤ Requesting certificate for $DOMAIN and *.$DOMAIN …"
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials "$INI_FILE" \
  --dns-cloudflare-propagation-seconds 60 \
  -d "$DOMAIN" \
  -d "*.$DOMAIN" \
  --non-interactive --agree-tos --email "admin@$DOMAIN"

# ── Dry‑run renewal test ─────────────────────────────────────────────
echo "➤ Testing automatic renewal (dry-run)…"
sudo certbot renew --dry-run

echo "✅  All done!  Production certificates now live at: /etc/letsencrypt/live/$DOMAIN/"
echo "   Attach them to your services and relax—Certbot will renew automatically."
