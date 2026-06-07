#!/usr/bin/env bash
# Installs Sonochron as standalone systemd services (without pm2).
# Alternative to deploy.sh if you prefer plain systemd management.
#
# Usage: sudo ./systemd/install-services.sh
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

echo "▸ Creating log directory…"
mkdir -p "$PROJECT/logs"
chown jackc:jackc "$PROJECT/logs"

echo "▸ Building frontend…"
su - jackc -c "npm --prefix $PROJECT/frontend run build"

echo "▸ Installing systemd unit files…"
cp "$PROJECT/systemd/sonochron-api.service" "$SYSTEMD_DIR/"
cp "$PROJECT/systemd/sonochron-ui.service"  "$SYSTEMD_DIR/"

echo "▸ Reloading systemd…"
systemctl daemon-reload

echo "▸ Enabling services (auto-start on boot)…"
systemctl enable sonochron-api.service
systemctl enable sonochron-ui.service

echo "▸ Starting services now…"
systemctl restart sonochron-api.service
systemctl restart sonochron-ui.service

echo ""
echo "✓ Sonochron services installed and started."
echo ""
systemctl status sonochron-api.service --no-pager -l
echo ""
systemctl status sonochron-ui.service --no-pager -l
