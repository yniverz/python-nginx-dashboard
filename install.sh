#!/usr/bin/env bash
# One‑shot installer:
#   • Installs system deps (python3‑venv, screen)
#   • Creates a venv called "my-venv"
#   • Installs requirements.txt into that venv
#   • Writes a launcher that executes:  my-venv/bin/python -m core
#   • Registers & starts a systemd service that runs the launcher in screen

set -euo pipefail

########## EDITABLE VALUES ##########
APP_NAME="python-nginx-dashboard"          # logical name: screen session + systemd service
VENV_DIR="py-venv"       # folder for the virtualenv (relative to repo root)
PY_MODULE="core"         # module to run via  python -m
#####################################

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"

echo "➤ Installing APT packages …"
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv screen

if [[ ! -d "$REPO_DIR/$VENV_DIR" ]]; then
  echo "➤ Creating virtualenv $VENV_DIR …"
  python3 -m venv "$REPO_DIR/$VENV_DIR"
fi

echo "➤ Installing Python deps …"
"$REPO_DIR/$VENV_DIR/bin/pip" install --upgrade pip
if [[ -f "$REPO_DIR/requirements.txt" ]]; then
  "$REPO_DIR/$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
fi

echo "➤ Writing launcher …"
LAUNCHER="$REPO_DIR/run_${APP_NAME}.sh"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Auto‑generated: starts $PY_MODULE inside screen
exec /usr/bin/screen -DmS "$APP_NAME" "$REPO_DIR/$VENV_DIR/bin/python" -m "$PY_MODULE"
EOF
chmod +x "$LAUNCHER"

SERVICE_FILE="/etc/systemd/system/${APP_NAME}-screen.service"
echo "➤ Creating systemd unit $SERVICE_FILE …"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=${APP_NAME} module in GNU Screen
After=network.target

[Service]
Type=forking
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${LAUNCHER}
ExecStop=/usr/bin/screen -S ${APP_NAME} -X quit
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "➤ Enabling & starting service …"
sudo systemctl daemon-reload
sudo systemctl enable --now "$(basename "$SERVICE_FILE")"

echo
echo "✅ ${APP_NAME} installed!"
echo "  • Attach:  screen -r ${APP_NAME}"
echo "  • Logs  :  journalctl -u ${APP_NAME}-screen -f"
