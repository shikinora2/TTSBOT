"""
🔊 TTS Backend Server — Valtec-TTS
Chạy: python tts_server.py [--port 5050] [--host 127.0.0.1]

HTTP API server xử lý TTS, model chỉ tải 1 lần duy nhất.
Tất cả bot instances gọi API này để tổng hợp giọng nói.
"""

import os
import sys
import time
import uuid
import asyncio
import logging
import argparse
from pathlib import Path

# --- CHỐNG QUÁ TẢI CPU ---
# Giới hạn OpenMP và các thư viện toán học chỉ dùng 1 luồng CPU
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tts_server")

# Path setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VALTEC_REPO = os.path.join(BASE_DIR, "valtec-tts-src")
if VALTEC_REPO not in sys.path:
    sys.path.insert(0, VALTEC_REPO)

# CLI arguments
parser = argparse.ArgumentParser(description="TTS Backend Server")
parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
parser.add_argument("--port", type=int, default=5050, help="Port (default: 5050)")
args = parser.parse_args()

from aiohttp import web
from valtec_tts import TTS

try:
    import torch
    torch.set_num_threads(1)
    log.info("Đã giới hạn PyTorch sử dụng 1 luồng CPU.")
except ImportError:
    pass

# ── Tải model TTS 1 lần duy nhất ─────────────────────────────
log.info("Đang tải mô hình Valtec-TTS vào RAM...")
tts = TTS()
SPEAKERS = tts.list_speakers()
log.info(f"Model sẵn sàng! Speakers: {SPEAKERS}")

# Lock chống tràn RAM: chỉ 1 request TTS xử lý cùng lúc
tts_lock = asyncio.Lock()

# Thư mục tạm cho file audio
TEMP_DIR = os.path.join(BASE_DIR, "temp_audio")
os.makedirs(TEMP_DIR, exist_ok=True)

# ── API Handlers ──────────────────────────────────────────────

async def handle_health(request):
    """GET /health — Kiểm tra server status."""
    return web.json_response({
        "status": "ok",
        "speakers": SPEAKERS,
        "model": "valtec-tts",
    })

async def handle_speakers(request):
    """GET /speakers — Danh sách speakers."""
    return web.json_response({"speakers": SPEAKERS})

async def handle_synthesize(request):
    """POST /synthesize — Tổng hợp giọng nói.
    
    Body JSON:
        text: str — Văn bản cần đọc
        speaker: str — Speaker (default: NF)
    
    Response: file WAV
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    text = data.get("text", "").strip()
    speaker = data.get("speaker", "NF")

    if not text:
        return web.json_response({"error": "text is required"}, status=400)

    if speaker not in SPEAKERS:
        return web.json_response(
            {"error": f"Invalid speaker '{speaker}'. Available: {SPEAKERS}"},
            status=400
        )

    # Tạo file tạm
    filename = f"tts_{uuid.uuid4().hex}.wav"
    filepath = os.path.join(TEMP_DIR, filename)

    try:
        t0 = time.time()

        # Lock để đảm bảo chỉ 1 request xử lý TTS cùng lúc (tiết kiệm RAM)
        async with tts_lock:
            await asyncio.to_thread(tts.speak, text, speaker=speaker, output_path=filepath)

        elapsed = time.time() - t0
        filesize = os.path.getsize(filepath)

        log.info(f"[TTS] '{text[:50]}...' | speaker={speaker} | {elapsed:.2f}s | {filesize:,}B")

        # Trả file WAV
        response = web.FileResponse(
            filepath,
            headers={
                "Content-Type": "audio/wav",
                "X-TTS-Duration": str(round(elapsed, 3)),
            }
        )

        # Xóa file sau khi gửi xong (dùng background task)
        async def cleanup():
            await asyncio.sleep(2)
            try:
                os.remove(filepath)
            except OSError:
                pass

        asyncio.ensure_future(cleanup())
        return response

    except Exception as e:
        log.error(f"[TTS Error] {e}", exc_info=True)
        # Dọn file nếu lỗi
        if os.path.exists(filepath):
            os.remove(filepath)
        return web.json_response({"error": str(e)}, status=500)

# ── App Setup ─────────────────────────────────────────────────

app = web.Application()
app.router.add_get("/health", handle_health)
app.router.add_get("/speakers", handle_speakers)
app.router.add_post("/synthesize", handle_synthesize)

# ── Startup / Shutdown ────────────────────────────────────────

async def on_startup(app):
    log.info(f"TTS Backend đang chạy tại http://{args.host}:{args.port}")
    log.info(f"Endpoints: GET /health | GET /speakers | POST /synthesize")

async def on_shutdown(app):
    # Dọn file tạm
    for f in Path(TEMP_DIR).glob("tts_*.wav"):
        try:
            f.unlink()
        except OSError:
            pass
    log.info("TTS Backend đã tắt.")

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

# ── Run ───────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"Khởi động TTS Backend trên {args.host}:{args.port}...")
    web.run_app(app, host=args.host, port=args.port, print=None)
