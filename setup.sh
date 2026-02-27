#!/bin/bash
# ============================================================
#  🚀 ALL-IN-ONE SETUP — Discord TTS Bot (Valtec-TTS)
#  Chạy: bash setup.sh
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
echo "║      🤖  Discord TTS Bot — Valtec-TTS  Setup Script      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── 0. Kiểm tra chạy với sudo/root ───────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "Script phải chạy với quyền root. Dùng: sudo bash setup.sh"
fi

# ── Biến cấu hình ────────────────────────────────────────────
INSTALL_DIR="/root/ttsbot"
VALTEC_DIR="$INSTALL_DIR/valtec-tts-src"
VENV_DIR="$INSTALL_DIR/.venv"
PYTHON_BIN="python3.11"
SERVICE_NAME="ttsbot"
SWAP_SIZE="2G"
SWAP_FILE="/swapfile"
BOT_REPO="https://github.com/shikinora2/TTSBOT.git"

# Cho phép ghi đè từ env:
INSTALL_DIR="${TTSBOT_DIR:-$INSTALL_DIR}"

# ── 1. SWAP ───────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[1/8] Kiểm tra SWAP...${RESET}"
TOTAL_SWAP=$(free -b | awk '/^Swap:/{print $2}')
if [[ "$TOTAL_SWAP" -lt $((1 * 1024 * 1024 * 1024)) ]]; then
    if [[ -f "$SWAP_FILE" ]]; then
        warn "Swap file đã tồn tại nhưng chưa đủ — bỏ qua tạo mới."
    else
        log "Tạo swap $SWAP_SIZE tại $SWAP_FILE..."
        fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
        chmod 600 "$SWAP_FILE"
        mkswap "$SWAP_FILE"
        swapon "$SWAP_FILE"
        grep -q "$SWAP_FILE" /etc/fstab || echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
        ok "Swap $SWAP_SIZE đã được tạo và kích hoạt."
    fi
else
    ok "Swap đã đủ ($(free -h | awk '/^Swap:/{print $2}'))."
fi

# ── 2. Gói hệ thống ───────────────────────────────────────────
echo ""
echo -e "${BOLD}[2/8] Cài gói hệ thống...${RESET}"
apt-get update -qq
apt-get install -y -qq \
    git curl wget ffmpeg build-essential \
    software-properties-common ca-certificates > /dev/null
ok "Đã cài: git, ffmpeg, build-essential."

# ── 3. Python 3.11 ────────────────────────────────────────────
echo ""
echo -e "${BOLD}[3/8] Kiểm tra Python 3.11...${RESET}"
if ! command -v "$PYTHON_BIN" &>/dev/null; then
    log "Thêm PPA deadsnakes và cài Python 3.11..."
    add-apt-repository -y ppa:deadsnakes/ppa > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev > /dev/null
    ok "Python 3.11 đã được cài."
else
    ok "$(python3.11 --version) đã có sẵn."
fi

# ── 4. Clone repo bot từ GitHub ───────────────────────────────
echo ""
echo -e "${BOLD}[4/8] Clone Bot TTS từ GitHub...${RESET}"
if [[ -f "$INSTALL_DIR/ttsbot.py" ]]; then
    ok "Thư mục $INSTALL_DIR đã có sẵn — bỏ qua clone."
else
    log "Đang clone từ $BOT_REPO..."
    git clone "$BOT_REPO" "$INSTALL_DIR"
    ok "Clone thành công!"
fi
cd "$INSTALL_DIR"

# ── 5. Kiểm tra Valtec-TTS ────────────────────────────────────
echo ""
echo -e "${BOLD}[5/8] Kiểm tra Valtec-TTS...${RESET}"
if [[ -d "$VALTEC_DIR" ]]; then
    ok "Valtec-TTS đã có sẵn tại $VALTEC_DIR."
else
    die "Không tìm thấy $VALTEC_DIR — repo bị thiếu thư mục valtec-tts-src."
fi

# ── 6. Tạo venv + cài packages ────────────────────────────────
echo ""
echo -e "${BOLD}[6/8] Cài Python packages vào virtual environment...${RESET}"
if [[ ! -d "$VENV_DIR" ]]; then
    log "Tạo virtual environment tại $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Xóa cache cũ nếu bị lỗi từ lần trước để giải phóng ổ cứng
rm -rf ~/.cache/pip

PIP="$VENV_DIR/bin/pip"
"$PIP" install --no-cache-dir --upgrade pip setuptools wheel -q

log "Cài PyTorch CPU (có thể mất vài phút)..."
"$PIP" install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q

log "Cài các thư viện phụ thuộc..."
"$PIP" install --no-cache-dir -q \
    numpy scipy soundfile librosa tqdm \
    Unidecode num2words inflect cn2an jieba pypinyin \
    jamo gruut g2p-en anyascii \
    viphoneme underthesea vinorm \
    huggingface_hub eng-to-ipa

log "Cài Discord + HTTP packages..."
"$PIP" install --no-cache-dir -q discord.py==2.6.4 PyNaCl python-dotenv aiohttp emoji gTTS

log "Cài valtec-tts editable..."
"$PIP" install --no-cache-dir -q -e "$VALTEC_DIR"

ok "Tất cả packages đã được cài đặt."

# ── 7. Tạo file .env ─────────────────────────────────────────
echo ""
echo -e "${BOLD}[7/8] Cấu hình file .env...${RESET}"
ENV_FILE="$INSTALL_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    ok "File .env đã tồn tại — bỏ qua."
else
    if [[ -f "$INSTALL_DIR/.env.example" ]]; then
        cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
    else
        cat > "$ENV_FILE" << 'EOF'
# Discord Bot Token — lấy từ https://discord.com/developers/applications
DISCORD_TOKEN=your_bot_token_here

# Application ID (Developer Portal > General Information > Application ID)
DISCORD_APP_ID=your_application_id_here

# TTS Backend URL (chạy trên cùng VPS)
TTS_BACKEND_URL=http://127.0.0.1:5050
EOF
    fi
    echo ""
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    warn " Chưa điền token! Hãy chạy lệnh sau để cấu hình:"
    echo ""
    echo -e "   ${BOLD}nano $ENV_FILE${RESET}"
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi

# ── 8. Cài systemd services ───────────────────────────────────
echo ""
echo -e "${BOLD}[8/8] Cài systemd services...${RESET}"

# --- TTS Backend Service (chạy trước bot) ---
TTS_SERVICE_FILE="/etc/systemd/system/tts-server.service"
cat > "$TTS_SERVICE_FILE" << EOF
[Unit]
Description=TTS Backend Server (Valtec-TTS)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/tts-server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl enable tts-server > /dev/null 2>&1
ok "Service 'tts-server' đã được đăng ký."

# --- Discord Bot Service (chạy sau backend) ---
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Discord TTS Bot (Valtec-TTS)
After=network-online.target tts-server.service
Wants=network-online.target
Requires=tts-server.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/ttsbot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" > /dev/null 2>&1
ok "Service '$SERVICE_NAME' đã được đăng ký (phụ thuộc tts-server)."

# ── Hoàn tất ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                  ✅  Setup hoàn tất!                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# Kiểm tra token
TOKEN_VALUE=$(grep 'DISCORD_TOKEN=' "$ENV_FILE" | cut -d'=' -f2)
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
