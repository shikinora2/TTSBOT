#!/bin/bash
# ============================================================
#  🚀 ALL-IN-ONE SETUP & CLEANUP — Discord TTS Bot (gTTS)
#  Chạy: sudo bash setup.sh
# ============================================================

set -euo pipefail

# ── Màu sắc ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║      🤖  Discord TTS Bot (gTTS) Setup & Cleanup Script   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── 0. Kiểm tra chạy với sudo/root ───────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "Script phải chạy với quyền root. Dùng: sudo bash setup.sh"
fi

# ── Biến cấu hình ────────────────────────────────────────────
INSTALL_DIR="/root/ttsbot"
VENV_DIR="$INSTALL_DIR/.venv"
PYTHON_BIN="python3.11"
SERVICE_NAME="ttsbot"
BOT_REPO="https://github.com/shikinora2/TTSBOT.git"

# Cho phép ghi đè từ env:
INSTALL_DIR="${TTSBOT_DIR:-$INSTALL_DIR}"

# ── 1. Dừng và gỡ bỏ service tts-server cũ ───────────────────
echo ""
echo -e "${BOLD}[1/6] Dọn dẹp service cũ...${RESET}"

if systemctl is-active --quiet tts-server.service; then
    log "Đang dừng tts-server..."
    systemctl stop tts-server || true
fi

if systemctl is-enabled --quiet tts-server.service 2>/dev/null; then
    log "Đang vô hiệu hóa tts-server..."
    systemctl disable tts-server || true
fi

if [[ -f "/etc/systemd/system/tts-server.service" ]]; then
    rm -f /etc/systemd/system/tts-server.service
    systemctl daemon-reload
    ok "Đã gỡ bỏ service tts-server."
else
    ok "Không tìm thấy service tts-server."
fi

if systemctl is-active --quiet ttsbot.service; then
    log "Tạm dừng ttsbot..."
    systemctl stop ttsbot || true
fi

# ── 2. Clone repo bot từ GitHub ───────────────────────────────
echo ""
echo -e "${BOLD}[2/6] Clone Code Bot...${RESET}"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Đã có sẵn thư mục $INSTALL_DIR. Đang reset về code mới nhất từ remote..."
    cd "$INSTALL_DIR"
    git fetch --all
    git reset --hard origin/main
    # Xóa cache bytecode Python (tránh chạy nhầm file .pyc cũ)
    find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$INSTALL_DIR" -name "*.pyc" -delete 2>/dev/null || true
    ok "Đã reset về origin/main: $(git log -1 --oneline)"
else
    log "Thư mục $INSTALL_DIR chưa có hoặc chưa init git. Đang clone..."
    rm -rf "$INSTALL_DIR"
    git clone "$BOT_REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 3. Dọn Dẹp File Cũ (AI Models) ────────────────────────────
echo ""
echo -e "${BOLD}[3/6] Xóa dọn các tập tin tts-server cũ & Model...${RESET}"

# Xóa các file/folder của valtec-tts nặng vài chục/vài Gb
rm -rf "$INSTALL_DIR/valtec-tts-src" \
       "$INSTALL_DIR/pretrained" \
       "$INSTALL_DIR/temp_audio" \
       "$INSTALL_DIR/tts-server.py" \
       "$INSTALL_DIR/clones.json" \
       "$INSTALL_DIR/install.sh" \
       "$INSTALL_DIR/"*.wav

# Xoá cả cache HuggingFace nếu có (nơi lưu các model vài GB)
rm -rf /root/.cache/huggingface /root/.cache/valtec_tts ~/.cache/valtec_tts

ok "Đã dọn sạch bong tài nguyên Valtec-TTS cũ. Mọi thứ trở nên mỏng nhẹ!"

# ── 4. Cài ffmpeg + Python packages ──────────────────────────
echo ""
echo -e "${BOLD}[4/6] Cài ffmpeg và Python packages...${RESET}"

# Cài ffmpeg nếu chưa có (cần cho FFmpegPCMAudio của discord.py)
if ! command -v ffmpeg &>/dev/null; then
    log "Đang cài ffmpeg..."
    apt-get update -q && apt-get install -y -q ffmpeg
    ok "Đã cài ffmpeg."
else
    ok "ffmpeg đã có sẵn."
fi

# Xóa cache cũ của pip
rm -rf ~/.cache/pip

# Chúng ta xóa .venv cũ đi luôn cho sạch (Phòng khi còn đọng lại torch vài GB)
if [[ -d "$VENV_DIR" ]]; then
    log "Xoá ảo hoá cũ..."
    rm -rf "$VENV_DIR"
fi

log "Tạo virtual environment mới tại $VENV_DIR..."
"$PYTHON_BIN" -m venv "$VENV_DIR"

PIP="$VENV_DIR/bin/pip"
"$PIP" install --no-cache-dir --upgrade pip setuptools wheel -q

log "Đang cài đặt Requirements..."
"$PIP" install --no-cache-dir -r requirements.txt

ok "Tất cả packages đã được cài đặt."

# ── 5. Tạo file .env ─────────────────────────────────────────
echo ""
echo -e "${BOLD}[5/6] Cấu hình file .env...${RESET}"
ENV_FILE="$INSTALL_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    ok "File .env đã tồn tại — giữ nguyên thiết lập."
else
    cat > "$ENV_FILE" << 'EOF'
# Discord Bot Token — lấy từ https://discord.com/developers/applications
DISCORD_TOKEN=your_bot_token_here

# Application ID (Developer Portal > General Information > Application ID)
DISCORD_APP_ID=your_application_id_here
EOF
    echo ""
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    warn " Chưa điền token! Hãy chạy lệnh sau để cấu hình:"
    echo ""
    echo -e "   ${BOLD}nano $ENV_FILE${RESET}"
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi

# ── 6. Tạo Service Systemd cho ttsbot gTTS────────────
echo ""
echo -e "${BOLD}[6/6] Cài đặt systemd services...${RESET}"

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
systemctl enable "$SERVICE_NAME" > /dev/null 2>&1
ok "Service '$SERVICE_NAME' đã được đăng ký và thiết lập."

# ── Hoàn tất ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                  ✅  Setup hoàn tất!                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# Kiểm tra token
TOKEN_VALUE=$(grep 'DISCORD_TOKEN=' "$ENV_FILE" | cut -d'=' -f2 || echo "")
if [[ "$TOKEN_VALUE" == "your_bot_token_here" || -z "$TOKEN_VALUE" ]]; then
    echo -e "  ${YELLOW}⚠️  Bước tiếp theo:${RESET}"
    echo -e "     1. Điền token:   ${BOLD}nano $ENV_FILE${RESET}"
    echo -e "     2. Khởi động bot: ${BOLD}systemctl start $SERVICE_NAME${RESET}"
else
    log "Token đã được cấu hình — khởi động bot..."
    systemctl restart "$SERVICE_NAME"
    ok "Bot đã chạy!"
    echo ""
    echo -e "  📋 ${BOLD}Lệnh quản lý:${RESET}"
fi

echo ""
echo -e "  ${BOLD}systemctl start   $SERVICE_NAME${RESET}   # Khởi động"
echo -e "  ${BOLD}systemctl stop    $SERVICE_NAME${RESET}   # Dừng"
echo -e "  ${BOLD}systemctl restart $SERVICE_NAME${RESET}   # Khởi động lại"
echo -e "  ${BOLD}systemctl status  $SERVICE_NAME${RESET}   # Xem trạng thái"
echo -e "  ${BOLD}journalctl -u $SERVICE_NAME -f${RESET}    # Xem log realtime"
echo ""
