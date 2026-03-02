# 🤖 Discord TTS Bot — gTTS

Bot Discord tự động đọc tin nhắn bằng giọng nói Tiếng Việt.  
Giọng đọc: **Google Text-to-Speech (gTTS)** · Không cần GPU · Không cần model AI.

---

## ⚡ Cài đặt VPS — 1 lệnh duy nhất

```bash
git clone https://github.com/shikinora2/TTSBOT.git /root/ttsbot && cd /root/ttsbot && bash setup.sh
```

> ⏱ Hoàn tất trong **~1–2 phút**. Script tự động cài Python packages, ffmpeg, tạo file `.env` mẫu và đăng ký systemd service.

---

## ✅ Sau khi setup xong

### 1. Điền Discord Token

```bash
nano /root/ttsbot/.env
```

```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_APP_ID=your_application_id_here
```

### 2. Khởi động bot

```bash
systemctl start ttsbot
```

### 3. Kiểm tra log

```bash
journalctl -u ttsbot -f
```

---

## 🔄 Cập nhật bot (VPS)

```bash
cd /root/ttsbot && bash setup.sh
```

Script sẽ tự động:
- Pull code mới nhất từ GitHub
- Xóa cache `.pyc` cũ
- Cài packages mới (nếu có)
- Restart service

> Clone bot cũng được cập nhật tự động — khi bot chính restart, nó spawn lại toàn bộ clone với code mới.

---

## 🏗️ Kiến trúc

```
VPS Ubuntu
│
└── ttsbot.py  ←  Discord Bot chính (systemd service)
    │              Gọi Google TTS API để tổng hợp giọng nói
    │
    ├── clone_1  ←  Subprocess bot phụ (tự động restart cùng bot chính)
    ├── clone_2
    └── ...      ←  Đọc từ clones.json, dùng chung codebase
```

> 💡 Không cần backend riêng. Mỗi bot gọi trực tiếp Google TTS — nhẹ, đơn giản, không tốn RAM cho model.

---

## ✅ Yêu cầu VPS

| Thành phần | Tối thiểu |
|---|---|
| OS | Ubuntu 22.04 / 24.04 LTS x64 |
| RAM | **512 MB** |
| Disk | 2 GB |
| CPU | 1 vCPU |
| Python | **3.11** |
| ffmpeg | Bắt buộc (tự cài bởi setup.sh) |

---

## ⚙️ Cấu hình Discord Developer Portal

### 1. Bật Message Content Intent

1. Vào https://discord.com/developers/applications
2. Chọn app → tab **Bot**
3. Bật **MESSAGE CONTENT INTENT** → **Save Changes**

### 2. Tạo link mời bot

1. Tab **OAuth2** → **URL Generator**
2. Scopes: ✅ `bot` + ✅ `applications.commands`
3. Bot Permissions: ✅ `Send Messages` · ✅ `Read Message History` · ✅ `Add Reactions` · ✅ `Connect` · ✅ `Speak` · ✅ `Use Voice Activity`
4. Copy URL → dán vào trình duyệt → chọn server → **Authorize**

---

## 🎮 Lệnh Bot trong Discord

### 🔒 Lệnh Admin (chỉ admin server)

| Lệnh | Chức năng |
|---|---|
| `/setup [#kênh]` | Chọn kênh text để bot lắng nghe |
| `/status` | Xem trạng thái bot + backend |
| `/clone token:<TOKEN> app_id:<ID>` | Nhân bản thêm 1 bot độc lập |
| `/unclone clone_id:<ID>` | Xóa 1 bot clone |
| `/clones` | Xem danh sách bot clone |

### 🌐 Lệnh mọi người

| Lệnh | Chức năng |
|---|---|
| `/join` | Bot vào kênh thoại bạn đang đứng |
| `/leave` | Bot rời kênh thoại, xóa hàng đợi |
| `/skip` | Bỏ qua câu đang đọc |
| `/help` | Xem danh sách lệnh |

### 💬 Cách dùng TTS

1. Admin chạy `/setup #kênh-chat`
2. Ai đó chạy `/join` (phải đang ở voice channel)
3. **Gõ text** vào kênh đã setup → bot tự đọc
4. Bot react 👀 khi nhận tin nhắn
5. Giới hạn **150 ký tự**/tin nhắn

---

## 🔄 Quản lý service

```bash
# TTS Backend
systemctl start   tts-server    # Khởi động backend
systemctl stop    tts-server    # Dừng backend
systemctl restart tts-server    # Khởi động lại
journalctl -u tts-server -f     # Log realtime

# Discord Bot
systemctl start   ttsbot        # Khởi động bot
systemctl stop    ttsbot        # Dừng bot
systemctl restart ttsbot        # Khởi động lại
journalctl -u ttsbot -f         # Log realtime
```

---

## 📁 Cấu trúc thư mục

```
/root/ttsbot/
├── tts_server.py       # Backend HTTP xử lý TTS ⭐
├── ttsbot.py           # Discord Bot ⭐
├── setup.sh            # Script setup all-in-one
├── install.sh          # Script cài packages riêng
├── requirements.txt    # Dependencies
├── clones.json         # Danh sách bot clone (tự tạo)
├── .env                # Token Discord (KHÔNG share)
├── .env.example        # Mẫu file .env
├── README.md
└── valtec-tts-src/     # Source code Valtec-TTS
```

---

## 🔧 Nhân bản bot (/clone)

Để có **2+ bot** hoạt động đồng thời trong 1 server:

1. Tạo bot mới trên [Discord Developer Portal](https://discord.com/developers/applications)
2. Lấy **Token** + **Application ID** mới
3. Mời bot mới vào server (bật Message Content Intent)
4. Admin gõ trong Discord: `/clone token:NEW_TOKEN app_id:NEW_APP_ID`
5. Bot clone online trong vài giây, dùng **chung backend TTS**

> ⚠️ Mỗi bot cần **1 token riêng** — Discord giới hạn 1 bot chỉ ở 1 voice channel/server.

---

## 🔄 Cập nhật code

```bash
cd /root/ttsbot && git pull && systemctl restart tts-server ttsbot
```

---

## ⚠️ Lưu ý

- **Python 3.11** bắt buộc — `vinorm` không tương thích 3.12+
- Giới hạn **150 ký tự** mỗi tin nhắn để tránh OOM
- Bot tự bỏ qua link, @mention, custom emoji
- Model tự tải lần đầu (~500 MB), lưu tại `~/.cache/valtec_tts/`
- Backend chạy trên `127.0.0.1:5050` — không mở ra internet
