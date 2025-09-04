#!/usr/bin/env bash
# Install & register a systemd service that runs `python -m core` from a venv.
# Logs are written to /var/log/<APP_NAME>/<APP_NAME>.log

set -euo pipefail

########## EDIT THESE IF NEEDED ##########
APP_NAME="python-nginx-dashboard"          # becomes: python-nginx-dashboard.service  +  /var/log/python-nginx-dashboard/python-nginx-dashboard.log
VENV_DIR=".venv"       # virtualenv folder in repo
PY_FILE="run.py"         # python <file> to run
##########################################

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"

LOG_DIR="/var/log/${APP_NAME}"
LOG_FILE="${LOG_DIR}/${APP_NAME}.log"

echo "➤ Installing python3-venv (if needed)…"
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv #redis-server

# echo "➤ Enabling & starting Redis …"
# sudo systemctl enable --now redis-server

if [[ ! -d "$REPO_DIR/$VENV_DIR" ]]; then
  echo "➤ Creating virtualenv $VENV_DIR …"
  python3 -m venv "$REPO_DIR/$VENV_DIR"
fi

echo "➤ Installing Python deps …"
"$REPO_DIR/$VENV_DIR/bin/pip" install --upgrade pip
[[ -f "$REPO_DIR/requirements.txt" ]] && \
  "$REPO_DIR/$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

echo "➤ Creating log directory $LOG_DIR …"
sudo mkdir -p "$LOG_DIR"
sudo touch "$LOG_FILE"
sudo chown "$RUN_USER":"$RUN_USER" "$LOG_DIR" "$LOG_FILE"

SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
echo "➤ Writing systemd unit $SERVICE_FILE …"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=${APP_NAME} Python module
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${REPO_DIR}/${VENV_DIR}/bin/python ${PY_FILE}
Restart=always
RestartSec=5
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=multi-user.target
EOF

echo "➤ Enabling & starting service …"
sudo systemctl daemon-reload
sudo systemctl enable --now "$(basename "$SERVICE_FILE")"

cat <<EOM

✅ ${APP_NAME} installed and running!

• Log file   : ${LOG_FILE}   (tail -f ${LOG_FILE})
• Journalctl : journalctl -u ${APP_NAME} -f
• Restart    : sudo systemctl restart ${APP_NAME}
EOM
