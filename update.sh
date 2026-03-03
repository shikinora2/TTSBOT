#!/bin/bash
# ============================================================
#  🔄 UPDATE SCRIPT — Discord TTS Bot
#  Chạy: sudo bash update.sh
#  Dùng để cập nhật code mới nhất từ GitHub lên VPS
# ============================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

INSTALL_DIR="/root/ttsbot"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_NAME="ttsbot"

[[ $EUID -ne 0 ]] && die "Chạy với quyền root: sudo bash update.sh"
[[ ! -d "$INSTALL_DIR/.git" ]] && die "Không tìm thấy $INSTALL_DIR — hãy chạy setup.sh trước."

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           🔄  TTS Bot — Update từ GitHub                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── 1. Dừng bot ───────────────────────────────────────────────
log "Dừng bot..."
systemctl stop "$SERVICE_NAME" || true
# Chờ Discord giải phóng session voice cũ (tránh 4017)
log "Chờ 5s để Discord giải phóng session cũ..."
sleep 5

# ── 2. Pull code mới nhất ─────────────────────────────────────
log "Pull code mới từ GitHub..."
cd "$INSTALL_DIR"
git fetch --all
git reset --hard origin/main

# Xóa bytecode cache cũ
find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_DIR" -name "*.pyc" -delete 2>/dev/null || true

ok "Code đã cập nhật: $(git log -1 --oneline)"

# ── 3. Cài/cập nhật packages ──────────────────────────────────
log "Cài packages mới (nếu có thay đổi)..."
"$VENV_DIR/bin/pip" install --no-cache-dir -q -r requirements.txt
ok "Packages OK."

# ── 4. Cập nhật systemd service (RestartSec, v.v.) ────────────
log "Cập nhật systemd service..."
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Discord TTS Bot (gTTS)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/ttsbot.py
Restart=always
RestartSec=30
ExecStopPost=/bin/sleep 5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
ok "Service đã cập nhật (RestartSec=30)."

# ── 5. Khởi động lại bot ──────────────────────────────────────
log "Khởi động lại bot..."
systemctl start "$SERVICE_NAME"
sleep 3

# Kiểm tra trạng thái
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Bot đang chạy!"
else
    warn "Bot có thể chưa khởi động xong, kiểm tra log:"
fi

echo ""
echo -e "${GREEN}${BOLD}✅ Update hoàn tất!${RESET}"
echo -e "  Commit hiện tại: ${BOLD}$(git log -1 --oneline)${RESET}"
echo ""
echo -e "  📋 ${BOLD}Xem log realtime:${RESET}"
echo -e "     ${BOLD}journalctl -u $SERVICE_NAME -f${RESET}"
echo ""
echo -e "  ⚠️  ${YELLOW}Lưu ý:${RESET} Sau khi restart, chờ ${BOLD}60 giây${RESET} trước khi dùng /join"
echo -e "     (Discord cần thời gian giải phóng session voice cũ)"
echo ""
