#!/usr/bin/env bash
# Removes only the systemd unit & screen session; leaves venv and packages.

set -euo pipefail

APP_NAME="core"   # must match install.sh
SERVICE="${APP_NAME}-screen.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE}"

echo "➤ Stopping & disabling ${SERVICE} …"
sudo systemctl stop    "${SERVICE}" 2>/dev/null || true
sudo systemctl disable "${SERVICE}" 2>/dev/null || true

if [[ -f "${SERVICE_FILE}" ]]; then
  sudo rm "${SERVICE_FILE}"
  echo "➤ Removed ${SERVICE_FILE}"
fi

sudo systemctl daemon-reload
echo "✅ Service uninstalled."
