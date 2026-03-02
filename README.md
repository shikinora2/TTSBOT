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
### 🔒 Lệnh Admin

| Lệnh | Chức năng |
|---|---|
| `/setup [kênh]` | Chọn kênh text để bot lắng nghe |
| `/status` | Xem trạng thái bot trong server |
| `/clone <token> <app_id>` | Tạo thêm 1 bot clone độc lập |
| `/unclone <id>` | Xóa và dừng 1 bot clone |
| `/clones` | Xem danh sách clone đang chạy |

### 🔊 Lệnh Mọi người

| Lệnh | Chức năng |
|---|---|
| `/join` | Bot vào kênh thoại bạn đang đứng |
| `/leave` | Bot rời kênh thoại, xóa hàng đợi |
| `/skip` | Bỏ qua câu đang đọc |
| `/skip_emoji` | Bật/tắt bỏ qua emoji khi đọc |
| `/ping` | Kiểm tra độ trễ |
| `/help` | Xem danh sách lệnh |

### 💬 Cách dùng TTS

1. Admin chạy `/setup` để chọn kênh lắng nghe
2. Chạy `/join` để bot vào kênh thoại
3. **Gõ text** vào kênh đã setup → bot tự đọc
4. Bot react 👀 khi nhận tin nhắn
5. Giới hạn **100 ký tự** mỗi tin nhắn · Tối đa **5 câu** trong hàng đợi

---

## 🤖 Tính năng Clone Bot

Chạy nhiều bot TTS độc lập từ 1 VPS duy nhất:

1. Tạo bot mới tại [Discord Developer Portal](https://discord.com/developers/applications)
2. Lấy **Token** + **Application ID** của bot mới
3. Bật **Message Content Intent** cho bot mới
4. Admin gõ trong Discord: `/clone token:NEW_TOKEN app_id:NEW_APP_ID`
5. Bot clone online trong vài giây

> ⚠️ Mỗi bot cần **1 token riêng** — Discord giới hạn 1 bot chỉ ở 1 voice channel/server.  
> Khi bot chính cập nhật và restart, **toàn bộ clone tự động restart theo**.

---

## 🛠️ Lệnh quản lý service

```bash
systemctl start ttsbot      # Khởi động
systemctl stop ttsbot       # Dừng
systemctl restart ttsbot    # Khởi động lại
systemctl status ttsbot     # Xem trạng thái
journalctl -u ttsbot -f     # Xem log realtime
```

---

## 📁 Cấu trúc thư mục

```
/root/ttsbot/
├── ttsbot.py           # Discord Bot ⭐
├── setup.sh            # Script setup all-in-one
├── requirements.txt    # Python dependencies
├── clones.json         # Danh sách bot clone (tự tạo)
├── .env                # Token Discord (KHÔNG share)
└── README.md
```