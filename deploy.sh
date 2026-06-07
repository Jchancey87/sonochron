#!/usr/bin/env bash
# =============================================================
# Sonochron Deploy Script
# Usage:
#   ./deploy.sh          — first deploy or redeploy
#   ./deploy.sh restart  — restart services without rebuild
#   ./deploy.sh stop     — stop all services
#   ./deploy.sh logs     — tail live logs
#   ./deploy.sh status   — show pm2 process table
# =============================================================
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJECT/backend/.venv"
FRONTEND="$PROJECT/frontend"
LOGS="$PROJECT/logs"
ECOSYSTEM="$PROJECT/ecosystem.config.cjs"

# ── Colours ──────────────────────────────────────────────────
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_GREEN='\033[32m'
C_AMBER='\033[33m'
C_CYAN='\033[36m'

info()  { echo -e "${C_CYAN}▸${C_RESET} $*"; }
ok()    { echo -e "${C_GREEN}✓${C_RESET} $*"; }
head_() { echo -e "\n${C_BOLD}$*${C_RESET}"; }

# ── Sub-commands ─────────────────────────────────────────────
case "${1:-deploy}" in

  restart)
    head_ "Restarting Sonochron services…"
    pm2 restart "$ECOSYSTEM" --update-env
    pm2 save
    ok "Done. Run './deploy.sh status' to check."
    exit 0
    ;;

  stop)
    head_ "Stopping Sonochron services…"
    pm2 stop "$ECOSYSTEM" || true
    ok "Services stopped."
    exit 0
    ;;

  logs)
    pm2 logs --lines 80
    exit 0
    ;;

  status)
    pm2 status
    exit 0
    ;;

  deploy|"")
    ;;  # fall through to full deploy below

  *)
    echo "Usage: $0 [deploy|restart|stop|logs|status]"
    exit 1
    ;;
esac

# ── Full deploy ───────────────────────────────────────────────
head_ "Sonochron — Full Deploy"

# 1. Create log directory
mkdir -p "$LOGS"
info "Log directory: $LOGS"

# 2. Python venv + backend deps
head_ "Backend dependencies"
if [ ! -d "$VENV" ]; then
  info "Creating Python virtual environment…"
  python3 -m venv "$VENV"
fi
info "Installing/upgrading Python packages…"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$PROJECT/backend/requirements.txt"
ok "Backend dependencies ready"

# 3. Build frontend
head_ "Frontend build"
info "Installing npm packages…"
npm --prefix "$FRONTEND" install --silent
info "Building production bundle…"
npm --prefix "$FRONTEND" run build
ok "Frontend built → $FRONTEND/dist"

# 4. pm2 — delete stale processes and start fresh
head_ "Starting services with pm2"
pm2 delete sonochron-api 2>/dev/null || true
pm2 delete sonochron-ui  2>/dev/null || true
pm2 start "$ECOSYSTEM"
pm2 save
ok "Services started"

# 5. pm2 startup (auto-restart on reboot via systemd)
head_ "Configuring systemd startup"
STARTUP_CMD=$(pm2 startup systemd -u jackc --hp /home/jackc 2>&1 | grep "sudo env" || true)

if [ -n "$STARTUP_CMD" ]; then
  info "Running pm2 startup command (requires sudo)…"
  sudo env PATH="$PATH" pm2 startup systemd -u jackc --hp /home/jackc
  pm2 save
  ok "pm2 will now auto-start on reboot via systemd"
else
  ok "pm2 startup already configured"
fi

# 6. Summary
echo ""
echo -e "${C_BOLD}────────────────────────────────────────${C_RESET}"
echo -e "${C_BOLD}  Sonochron is running${C_RESET}"
echo -e "${C_BOLD}────────────────────────────────────────${C_RESET}"
echo ""
echo -e "  API   →  ${C_AMBER}http://$(hostname -I | awk '{print $1}'):8000${C_RESET}"
echo -e "  UI    →  ${C_AMBER}http://$(hostname -I | awk '{print $1}'):5173${C_RESET}"
echo ""
echo -e "  Logs    ./deploy.sh logs"
echo -e "  Status  ./deploy.sh status"
echo -e "  Restart ./deploy.sh restart"
echo ""

pm2 status
