import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import sys
import re
import json
import logging
import signal
import subprocess
import argparse
import aiohttp
from dotenv import load_dotenv

# -- Logging --
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Tải biến môi trường từ file .env
load_dotenv()

# ---------------------------------------------------------
# CLI ARGUMENTS (cho clone process)
# ---------------------------------------------------------
parser = argparse.ArgumentParser(description="Discord TTS Bot")
parser.add_argument("--token", default=None, help="Bot token (dùng cho clone)")
parser.add_argument("--app-id", default=None, help="Application ID (dùng cho clone)")
parser.add_argument("--clone-id", default=None, help="Clone ID (nội bộ)")
args, _ = parser.parse_known_args()

# ---------------------------------------------------------
# 1. CẤU HÌNH CƠ BẢN
# ---------------------------------------------------------
MAX_TEXT_LENGTH = 150  # Giới hạn ký tự để VPS không bị quá tải (OOM)
SPEAKER = "NF"         # Giọng cố định: Nữ miền Bắc
CLONES_FILE = os.path.join(BASE_DIR, "clones.json")
IS_CLONE = args.clone_id is not None

# Token và App ID: ưu tiên CLI args > env
BOT_TOKEN = args.token or os.getenv("DISCORD_TOKEN")
APP_ID = int(args.app_id or os.getenv("DISCORD_APP_ID", "0"))

# TTS Backend URL
TTS_BACKEND_URL = os.getenv("TTS_BACKEND_URL", "http://127.0.0.1:5050")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, application_id=APP_ID)
tree = bot.tree  # Slash command tree

# HTTP session (tạo khi bot ready, đóng khi shutdown)
http_session = None

# Quản lý trạng thái của từng Server (Guild)
class GuildState:
    def __init__(self):
        self.setup_channel_id = None
        self.queue = asyncio.Queue()
        self.play_task = None

guild_states = {}

def get_state(guild_id):
    if guild_id not in guild_states:
        guild_states[guild_id] = GuildState()
    return guild_states[guild_id]

# ---------------------------------------------------------
# QUẢN LÝ CLONE PROCESSES
# ---------------------------------------------------------
clone_processes = {}  # clone_id -> subprocess.Popen

def load_clones():
    """Đọc danh sách clone từ file JSON."""
    if os.path.exists(CLONES_FILE):
        try:
            with open(CLONES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("clones", [])
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_clones(clones):
    """Lưu danh sách clone vào file JSON."""
    with open(CLONES_FILE, "w", encoding="utf-8") as f:
        json.dump({"clones": clones}, f, indent=2, ensure_ascii=False)

def start_clone_process(clone_info):
    """Khởi chạy subprocess cho 1 clone."""
    clone_id = clone_info["id"]
    token = clone_info["token"]
    app_id = clone_info["app_id"]

    python_exe = sys.executable
    script = os.path.join(BASE_DIR, "ttsbot.py")

    proc = subprocess.Popen(
        [python_exe, script, "--token", token, "--app-id", str(app_id), "--clone-id", clone_id],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    clone_processes[clone_id] = proc
    log.info(f"[Clone] Đã khởi chạy clone '{clone_id}' (PID: {proc.pid})")
    return proc

def stop_clone_process(clone_id):
    """Dừng subprocess của 1 clone."""
    proc = clone_processes.get(clone_id)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.info(f"[Clone] Đã dừng clone '{clone_id}'")
    clone_processes.pop(clone_id, None)

def auto_start_clones():
    """Tự khởi chạy lại tất cả clone khi bot chính khởi động."""
    if IS_CLONE:
        return
    clones = load_clones()
    for clone_info in clones:
        try:
            start_clone_process(clone_info)
        except Exception as e:
            log.error(f"[Clone] Không thể khởi chạy clone '{clone_info['id']}': {e}")

# ---------------------------------------------------------
# 2. XỬ LÝ VĂN BẢN VÀ SINH ÂM THANH (QUA BACKEND API)
# ---------------------------------------------------------
def clean_text(text):
    """Xóa link, tag người dùng, emoji để tránh bot đọc những thứ vô nghĩa"""
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'<@!?\d+>', '', text)  # Xóa tag @user
    text = re.sub(r'<:\w+:\d+>', '', text)  # Xóa custom emoji
    return text.strip()

async def generate_audio(text, filepath):
    """Gọi TTS Backend API để tổng hợp giọng nói."""
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    url = f"{TTS_BACKEND_URL}/synthesize"
    payload = {"text": text, "speaker": SPEAKER}

    try:
        async with http_session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                with open(filepath, "wb") as f:
                    f.write(await resp.read())
                return True
            else:
                error = await resp.text()
                log.error(f"[TTS API] Status {resp.status}: {error}")
                return False
    except aiohttp.ClientError as e:
        log.error(f"[TTS API] Connection error: {e}")
        return False

async def tts_worker(voice_client, state):
    """Tiến trình ngầm chạy liên tục để kiểm tra hàng đợi và phát âm thanh"""
    while True:
        try:
            text = await state.queue.get()

            if not text:
                state.queue.task_done()
                continue

            filepath = os.path.join(BASE_DIR, f"temp_audio_{os.getpid()}_{id(state)}.wav")

            # Gọi Backend API để sinh audio
            success = await generate_audio(text, filepath)

            if not success:
                log.warning(f"[TTS] Không sinh được audio cho: '{text[:50]}...'")
                state.queue.task_done()
                continue

            # Đợi nếu bot đang nói câu trước đó
            while voice_client.is_playing():
                await asyncio.sleep(0.5)

            # Phát âm thanh
            if os.path.exists(filepath):
                audio_source = discord.FFmpegPCMAudio(filepath)
                voice_client.play(audio_source)

                while voice_client.is_playing():
                    await asyncio.sleep(0.1)

                if os.path.exists(filepath):
                    os.remove(filepath)

            state.queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"[Playback] {e}", exc_info=True)

# ---------------------------------------------------------
# 3. CÁC LỆNH (COMMANDS)
# ---------------------------------------------------------
@bot.event
async def on_ready():
    global http_session
    clone_label = f" (Clone: {args.clone_id})" if IS_CLONE else ""
    log.info(f'Đã đăng nhập thành công: {bot.user.name} ({bot.user.id}){clone_label}')

    # Tạo HTTP session
    http_session = aiohttp.ClientSession()

    # Kiểm tra backend
    try:
        async with http_session.get(f"{TTS_BACKEND_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                log.info(f"TTS Backend OK — Speakers: {data.get('speakers', [])}")
            else:
                log.warning(f"TTS Backend trả về status {resp.status}")
    except Exception as e:
        log.warning(f"⚠️  Không kết nối được TTS Backend tại {TTS_BACKEND_URL}: {e}")
        log.warning("   Hãy chạy: python tts_server.py")

    try:
        # Đồng bộ lệnh cho từng server bot đang tham gia (để cập nhật ngay lập tức)
        synced_count = 0
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                synced_count += 1
            except Exception as e:
                log.warning(f"Không thể sync lệnh ở server {guild.name} ({guild.id}): {e}")
                
        # Đồng thời sync global cho các server mới vào
        await bot.tree.sync()
        
        log.info(f"Đã đồng bộ slash command ngay lập tức cho {synced_count} server.")
    except Exception as e:
        log.error(f"[sync slash commands] {e}")

    await bot.change_presence(activity=discord.Game(name="/help | /join | /setup"))

    # Auto-start clone processes (chỉ bot chính)
    if not IS_CLONE:
        auto_start_clones()

# ---------------------------------------------------------
# SLASH COMMANDS (/)
# ---------------------------------------------------------

@tree.command(name="setup", description="Thiết lập kênh text để bot lắng nghe và đọc tin nhắn")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="Kênh văn bản muốn bot lắng nghe (bỏ trống = kênh hiện tại)")
async def slash_setup(interaction: discord.Interaction, channel: discord.TextChannel = None):
    """[/setup] Chọn kênh để bot đọc tin nhắn TTS — CHỈ ADMIN"""
    state = get_state(interaction.guild.id)
    if channel is None:
        channel = interaction.channel
    state.setup_channel_id = channel.id
    await interaction.response.send_message(f"✅ Đã thiết lập kênh lắng nghe TTS tại: {channel.mention}")

@tree.command(name="join", description="Gọi bot vào kênh thoại bạn đang đứng")
async def slash_join(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)

    if interaction.user.voice is None:
        await interaction.response.send_message("⚠️ Bạn phải vào một kênh thoại (Voice Channel) trước!", ephemeral=True)
        return

    # Nếu chưa setup, lấy luôn kênh hiện tại làm kênh chat
    if not state.setup_channel_id:
        state.setup_channel_id = interaction.channel.id
        auto_setup_msg = f"✅ Tự động thiết lập kênh nghe TTS: {interaction.channel.mention}\n"
    else:
        auto_setup_msg = ""


    await interaction.response.defer()

    voice_channel = interaction.user.voice.channel

    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.move_to(voice_channel)
    else:
        await voice_channel.connect()

    if state.play_task is None or state.play_task.done():
        state.play_task = bot.loop.create_task(
            tts_worker(interaction.guild.voice_client, state)
        )

    await interaction.followup.send(f"{auto_setup_msg}👋 Đã tham gia **{voice_channel.name}**. Hãy chat vào kênh đã setup để bot đọc!")

@tree.command(name="leave", description="Bot rời kênh thoại và xóa hàng đợi")
async def slash_leave(interaction: discord.Interaction):
    """[/leave] Bot rời Voice Channel"""
    state = get_state(interaction.guild.id)

    if interaction.guild.voice_client:
        if state.play_task:
            state.play_task.cancel()
            state.play_task = None
        state.queue = asyncio.Queue()
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("🛑 Đã rời kênh thoại và xóa hàng đợi.")
    else:
        await interaction.response.send_message("Bot đang không ở trong kênh thoại nào.", ephemeral=True)

@tree.command(name="skip", description="Bỏ qua câu đang đọc hiện tại")
async def slash_skip(interaction: discord.Interaction):
    """[/skip] Bỏ qua câu hiện tại"""
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ Đã bỏ qua câu đang đọc.")
    else:
        await interaction.response.send_message("Không có gì để bỏ qua.", ephemeral=True)

@tree.command(name="status", description="Xem trạng thái hiện tại của bot trong server này")
@app_commands.default_permissions(administrator=True)
async def slash_status(interaction: discord.Interaction):
    """[/status] Xem kênh đang setup, hàng đợi — CHỈ ADMIN"""
    state = get_state(interaction.guild.id)

    if state.setup_channel_id:
        ch = interaction.guild.get_channel(state.setup_channel_id)
        ch_str = ch.mention if ch else f"(ID: {state.setup_channel_id})"
    else:
        ch_str = "_(chưa thiết lập)_"

    vc = interaction.guild.voice_client
    vc_str = f"**{vc.channel.name}**" if vc else "_(chưa vào kênh)_"
    queue_size = state.queue.qsize()
    clone_label = f"Clone: {args.clone_id}" if IS_CLONE else "Bot chính"

    # Kiểm tra backend status
    backend_status = "🔴 Offline"
    try:
        async with http_session.get(f"{TTS_BACKEND_URL}/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status == 200:
                backend_status = "🟢 Online"
    except Exception:
        pass

    embed = discord.Embed(title="📊 Trạng thái Bot TTS", color=0x5865F2)
    embed.add_field(name="🤖 Instance", value=clone_label, inline=True)
    embed.add_field(name="📝 Kênh lắng nghe", value=ch_str, inline=True)
    embed.add_field(name="🔊 Kênh thoại", value=vc_str, inline=True)
    embed.add_field(name="🎙️ Giọng đọc", value="👩‍🦰 NF — Nữ miền Bắc", inline=True)
    embed.add_field(name="📋 Hàng đợi", value=f"`{queue_size}` câu", inline=True)
    embed.add_field(name="🖥️ TTS Backend", value=backend_status, inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="help", description="Hiện danh sách tất cả lệnh của bot")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Danh sách lệnh Bot TTS",
        description="Giọng đọc cố định: 👩‍🦰 **NF — Nữ miền Bắc**",
        color=0x57F287
    )
    embed.add_field(
        name="⚙️ Thiết lập (Admin)",
        value=(
            "`/setup [kênh]` — Chọn kênh văn bản để bot lắng nghe 🔒\n"
            "`/clone` — Nhân bản thêm 1 bot độc lập 🔒\n"
            "`/unclone` — Xóa 1 bot clone 🔒\n"
            "`/clones` — Xem danh sách bot clone 🔒\n"
            "`/status` — Xem trạng thái bot 🔒"
        ),
        inline=False
    )
    embed.add_field(
        name="🔊 Điều khiển (Mọi người)",
        value=(
            "`/join` — Bot vào kênh thoại bạn đang đứng\n"
            "`/leave` — Bot rời kênh thoại, xóa hàng đợi\n"
            "`/skip` — Bỏ qua câu đang đọc"
        ),
        inline=False
    )
    embed.add_field(
        name="💬 Cách dùng TTS",
        value=(
            "Sau khi `/setup` + `/join`, chỉ cần **gõ text** vào kênh đã setup là bot tự đọc.\n"
            f"Giới hạn tối đa **{MAX_TEXT_LENGTH} ký tự** mỗi tin nhắn."
        ),
        inline=False
    )
    embed.set_footer(text="🔒 = Chỉ Admin · Bot TTS · Valtec-TTS")
    await interaction.response.send_message(embed=embed)

# ---------------------------------------------------------
# CLONE COMMANDS (CHỈ ADMIN — CHỈ BOT CHÍNH)
# ---------------------------------------------------------

@tree.command(name="clone", description="Nhân bản bot — tạo thêm 1 bot TTS độc lập (cần token bot mới)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    token="Bot token mới (lấy từ Discord Developer Portal)",
    app_id="Application ID của bot mới"
)
async def slash_clone(interaction: discord.Interaction, token: str, app_id: str):
    """[/clone] Tạo clone bot mới — CHỈ ADMIN"""
    if IS_CLONE:
        await interaction.response.send_message("⚠️ Không thể clone từ bot clone. Hãy dùng bot chính.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    clones = load_clones()
    clone_num = len(clones) + 1
    clone_id = f"clone_{clone_num}"

    for c in clones:
        if c["token"] == token:
            await interaction.followup.send("❌ Token này đã được dùng cho 1 clone khác!", ephemeral=True)
            return

    clone_info = {
        "id": clone_id,
        "token": token,
        "app_id": app_id,
        "created_by": str(interaction.user.id),
        "guild_id": str(interaction.guild.id),
    }
    clones.append(clone_info)
    save_clones(clones)

    try:
        proc = start_clone_process(clone_info)
        
        # Tạo link mời bot với các quyền cần thiết (Text + Voice)
        # Permissions = 36767808 (Send Messages, Read Message History, Add Reactions, Connect, Speak, Use Voice Activity)
        invite_url = f"https://discord.com/api/oauth2/authorize?client_id={app_id}&permissions=36767808&scope=bot%20applications.commands"
        
        await interaction.followup.send(
            f"✅ Đã tạo và khởi động **{clone_id}**!\n"
            f"• PID: `{proc.pid}`\n"
            f"• App ID: `{app_id}`\n\n"
            f"🔗 **[BẤM VÀO ĐÂY ĐỂ MỜI CLONE NÀY VÀO SERVER]({invite_url})**\n\n"
            f"_Lưu ý: Bạn phải mời nó vào server thì nó mới xuất hiện và hoạt động. Dùng lệnh `/clones` để xem danh sách._",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Lỗi khi khởi chạy clone: {e}", ephemeral=True)

@tree.command(name="unclone", description="Xóa 1 bot clone và dừng hoạt động")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(clone_id="ID của clone cần xóa (vd: clone_1)")
async def slash_unclone(interaction: discord.Interaction, clone_id: str):
    """[/unclone] Xóa clone — CHỈ ADMIN"""
    if IS_CLONE:
        await interaction.response.send_message("⚠️ Không thể quản lý clone từ bot clone.", ephemeral=True)
        return

    clones = load_clones()
    target = None
    for c in clones:
        if c["id"] == clone_id:
            target = c
            break

    if not target:
        await interaction.response.send_message(
            f"❌ Không tìm thấy clone `{clone_id}`. Dùng `/clones` để xem danh sách.",
            ephemeral=True
        )
        return

    stop_clone_process(clone_id)
    clones = [c for c in clones if c["id"] != clone_id]
    save_clones(clones)

    await interaction.response.send_message(f"🗑️ Đã xóa và dừng **{clone_id}**.", ephemeral=True)

@tree.command(name="clones", description="Xem danh sách tất cả bot clone đang chạy")
@app_commands.default_permissions(administrator=True)
async def slash_clones(interaction: discord.Interaction):
    """[/clones] Xem danh sách clone — CHỈ ADMIN"""
    if IS_CLONE:
        await interaction.response.send_message("⚠️ Dùng lệnh này trên bot chính.", ephemeral=True)
        return

    clones = load_clones()

    if not clones:
        await interaction.response.send_message("📋 Chưa có bot clone nào. Dùng `/clone` để tạo.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 Danh sách Bot Clone", color=0xFFA500)

    for c in clones:
        proc = clone_processes.get(c["id"])
        if proc and proc.poll() is None:
            status = "🟢 Online"
            pid = f"PID: {proc.pid}"
        else:
            status = "🔴 Offline"
            pid = "—"

        embed.add_field(
            name=f"{c['id']}",
            value=f"Status: {status}\nApp ID: `{c['app_id']}`\n{pid}",
            inline=True
        )

    embed.set_footer(text="Dùng /unclone <id> để xóa clone")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------------------------------------------------
# LẮNG NGHE TIN NHẮN (MESSAGE EVENT)
# ---------------------------------------------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if not message.guild:
        return

    state = get_state(message.guild.id)

    if message.channel.id == state.setup_channel_id and message.guild.voice_client:
        text = clean_text(message.content)

        if len(text) > MAX_TEXT_LENGTH:
            await message.channel.send(f"⚠️ Tin nhắn quá dài (> {MAX_TEXT_LENGTH} ký tự). Bot sẽ không đọc để tránh kẹt mạng.")
            return

        if text:
            await state.queue.put(text)
            await message.add_reaction("👀")

# ---------------------------------------------------------
# GRACEFUL SHUTDOWN
# ---------------------------------------------------------
async def shutdown():
    """Ngắt kết nối toàn bộ voice client và dừng clone trước khi tắt."""
    global http_session
    log.info("Đang tắt bot, ngắt kết nối voice channels...")

    if not IS_CLONE:
        for clone_id in list(clone_processes.keys()):
            stop_clone_process(clone_id)

    for guild in bot.guilds:
        if guild.voice_client:
            await guild.voice_client.disconnect(force=True)

    if http_session and not http_session.closed:
        await http_session.close()

    await bot.close()

# ---------------------------------------------------------
# CHẠY BOT
# ---------------------------------------------------------
if __name__ == "__main__":
    if not BOT_TOKEN:
        raise ValueError("Không tìm thấy DISCORD_TOKEN trong file .env (hoặc --token)!")
    if not APP_ID:
        raise ValueError("Không tìm thấy DISCORD_APP_ID trong file .env (hoặc --app-id)!")

    clone_label = f" (Clone: {args.clone_id})" if IS_CLONE else ""
    log.info(f"Khởi động bot{clone_label}...")
    log.info(f"TTS Backend: {TTS_BACKEND_URL}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal():
        loop.create_task(shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(bot.start(BOT_TOKEN))
    except (KeyboardInterrupt, SystemExit):
        loop.run_until_complete(shutdown())
    finally:
        loop.close()
