import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time
import os
import sys
import re
import json
import logging
import signal
import subprocess
import argparse
import emoji
from gtts import gTTS
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
MAX_TEXT_LENGTH = 100  # Giảm xuống 100 ký tự (chống spam/quá tải CPU)
MAX_QUEUE_SIZE = 5     # Số lượng câu tối đa chờ đọc trong 1 server
CLONES_FILE = os.path.join(BASE_DIR, "clones.json")
IS_CLONE = args.clone_id is not None

# Token và App ID: ưu tiên CLI args > env
BOT_TOKEN = args.token or os.getenv("DISCORD_TOKEN")
APP_ID = int(args.app_id or os.getenv("DISCORD_APP_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, application_id=APP_ID)
tree = bot.tree  # Slash command tree

# Quản lý trạng thái của từng Server (Guild)
class GuildState:
    def __init__(self):
        self.setup_channel_id = None
        self._queue = None          # Khởi tạo lazy để tránh "bound to different event loop"
        self.play_task = None
        self.skip_emoji = False
        self.leave_timer = None

    @property
    def queue(self):
        # Luôn trả về Queue gắn với event loop hiện tại
        if self._queue is None or self._queue._loop.is_closed():
            self._queue = asyncio.Queue()
        return self._queue

    @queue.setter
    def queue(self, value):
        self._queue = value

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
        stdout=None,
        stderr=None,
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
def clean_text(text, state):
    """Xóa link, tag người dùng, custom emoji để tránh bot đọc những thứ vô nghĩa"""
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'<@!?\d+>', '', text)  # Xóa tag @user
    text = re.sub(r'<:\w+:\d+>', '', text)  # Xóa custom emoji
    if state.skip_emoji:
        text = emoji.replace_emoji(text, replace='') # Xóa unicode emoji
    return text.strip()

async def generate_audio(text, filepath):
    """Sử dụng gTTS để đọc văn bản và lưu ra file."""
    try:
        def _tts_task():
            tts = gTTS(text=text, lang='vi', slow=False)
            tts.save(filepath)
            
        # Chạy trong luồng riêng để tránh khóa (block) bot Discord
        await asyncio.to_thread(_tts_task)
        return True
    except Exception as e:
        log.error(f"[Google TTS] Lỗi: {e}")
        return False

async def tts_worker(guild, state):
    """Tiến trình ngầm chạy liên tục để kiểm tra hàng đợi và phát âm thanh"""
    while True:
        try:
            # Lấy tin nhắn từ hàng đợi
            text = await state.queue.get()

            if not text:
                state.queue.task_done()
                continue

            # Lấy voice_client tươi mỗi lần phát (tránh stale reference)
            voice_client = guild.voice_client
            if voice_client is None or not voice_client.is_connected():
                log.warning("[TTS] Bot không còn ở kênh thoại, bỏ qua tin nhắn.")
                state.queue.task_done()
                continue

            filepath = os.path.join(BASE_DIR, f"temp_audio_{os.getpid()}_{id(state)}.mp3")

            # Sinh audio
            success = await generate_audio(text, filepath)

            if not success:
                log.warning(f"[TTS] Không sinh được audio cho: '{text[:50]}...'")
                state.queue.task_done()
                continue

            # Đợi nếu bot đang nói câu trước đó
            while voice_client.is_playing():
                await asyncio.sleep(0.3)

            # Phát âm thanh
            if os.path.exists(filepath):
                try:
                    audio_source = discord.FFmpegPCMAudio(filepath)
                    voice_client.play(audio_source)
                    log.info(f"[TTS] Đang phát: '{text[:60]}'")

                    while voice_client.is_playing():
                        await asyncio.sleep(0.1)
                except Exception as e:
                    log.error(f"[Playback Lỗi FFMPEG] {e}")
                finally:
                    await asyncio.sleep(0.2)
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception:
                            pass

            state.queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"[Worker Exception] {e}", exc_info=True)

# ---------------------------------------------------------
# 3. CÁC LỆNH (COMMANDS)
# ---------------------------------------------------------
@bot.event
async def on_ready():
    clone_label = f" (Clone: {args.clone_id})" if IS_CLONE else ""
    log.info(f'Đã đăng nhập thành công: {bot.user.name} ({bot.user.id}){clone_label}')

    try:
        # Sync as Global commands only. Do not copy to guilds to prevent duplication.
        await bot.tree.sync()
        log.info(f"Đã đồng bộ slash command toàn cục.")
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

    # Nếu chưa setup, hoặc người dùng gọi /join ở kênh khác, cập nhật lại kênh text
    if not state.setup_channel_id or state.setup_channel_id != interaction.channel.id:
        state.setup_channel_id = interaction.channel.id
        auto_setup_msg = f"✅ Tự động chuyển kênh nghe TTS hiện tại sang: {interaction.channel.mention}\n"
    else:
        auto_setup_msg = ""

    voice_channel = interaction.user.voice.channel

    # Nếu bot đã ở đúng kênh → đảm bảo worker chạy
    vc = interaction.guild.voice_client
    if vc is not None and vc.is_connected() and vc.channel == voice_channel:
        if state.play_task is None or state.play_task.done():
            state.play_task = bot.loop.create_task(tts_worker(interaction.guild, state))
        await interaction.response.send_message(
            f"✅ Bot đang ở **{voice_channel.name}** rồi!", ephemeral=True
        )
        return

    # Nếu bot đang ở kênh khác → chặn cướp kênh
    if vc is not None and vc.is_connected() and vc.channel != voice_channel:
        await interaction.response.send_message(
            f"⛔ Bot đang hoạt động ở kênh **{vc.channel.name}** rồi!\n"
            f"Vui lòng vào kênh đó hoặc dùng `/leave` để giải phóng bot trước.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        # Nếu còn voice client cũ (dù không connected) → disconnect để xóa session Discord
        if vc is not None:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
            # Gửi VOICE_STATE_UPDATE channel_id=null để Discord server xóa session cũ
            await interaction.guild.change_voice_state(channel=None)
            await asyncio.sleep(2.0)

        log.info(f"[Join] Kết nối tới '{voice_channel.name}'...")
        await voice_channel.connect(timeout=60.0, reconnect=False, self_deaf=True)
        log.info(f"[Join] Kết nối thành công tới '{voice_channel.name}'.")

    except Exception as e:
        err_msg = str(e) if str(e) else type(e).__name__
        log.error(f"[Tham gia Voice] Lỗi: {err_msg}")
        await interaction.followup.send(
            f"❌ Không thể kết nối tới kênh thoại.\n"
            f"Lỗi: `{err_msg}`\n"
            f"💡 _Thử `/leave` rồi `/join` lại sau vài giây._"
        )
        return

    if state.play_task is None or state.play_task.done():
        state.play_task = bot.loop.create_task(tts_worker(interaction.guild, state))

    await interaction.followup.send(
        f"{auto_setup_msg}👋 Đã tham gia **{voice_channel.name}**. Hãy chat vào kênh đã setup để bot đọc!"
    )

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
        # Gửi VOICE_STATE_UPDATE channel_id=null để Discord xóa session ngay
        try:
            await interaction.guild.change_voice_state(channel=None)
        except Exception:
            pass
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

@tree.command(name="skip_emoji", description="Bật/Tắt chế độ bot bỏ qua emoji khi đọc")
async def slash_skip_emoji(interaction: discord.Interaction):
    """[/skip_emoji] Bật tắt bỏ qua Emoji"""
    state = get_state(interaction.guild.id)
    state.skip_emoji = not state.skip_emoji
    
    status_str = "**BẬT** (Bot sẽ bỏ qua không đọc emoji)" if state.skip_emoji else "**TẮT** (Bot sẽ cố gắng đọc emoji)"
    await interaction.response.send_message(f"✅ Đã **{status_str}** chế độ bỏ qua Unicode Emoji.")

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

    embed = discord.Embed(title="📊 Trạng thái Bot TTS", color=0x5865F2)
    embed.add_field(name="🤖 Instance", value=clone_label, inline=True)
    embed.add_field(name="📝 Kênh lắng nghe", value=ch_str, inline=True)
    embed.add_field(name="💬 Hàng đợi", value=f"`{queue_size}` câu", inline=True)
    embed.add_field(name="🎙️ Giọng đọc", value="🤖 Google Dịch", inline=True)
    embed.add_field(name="🚫 Bỏ qua Emoji", value="Bật" if state.skip_emoji else "Tắt", inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="help", description="Hiện danh sách tất cả lệnh của bot")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Danh sách lệnh Bot TTS",
        description="Bot đọc văn bản thành giọng nói Tiếng Việt.",
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
            "`/skip` — Bỏ qua câu đang đọc\n"
            "`/skip_emoji` — Bật/tắt bỏ đọc Emoji (Biểu tượng cảm xúc)\n"
            "`/ping` — Kiểm tra độ trễ của Bot"
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

@tree.command(name="ping", description="Kiểm tra độ trễ của bot")
async def slash_ping(interaction: discord.Interaction):
    """[/ping] Kiểm tra kết nối Bot"""
    await interaction.response.defer()
    
    bot_latency = round(bot.latency * 1000)

    embed = discord.Embed(title="🏓 Pong!", color=0x57F287)
    embed.add_field(name="🤖 Bot Latency", value=f"`{bot_latency}ms`", inline=True)
        
    await interaction.followup.send(embed=embed)

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
    # Cần dòng này để các lệnh cũ (nếu có) vẫn hoạt động và không chặn event nội bộ
    await bot.process_commands(message)

    if message.author.bot:
        return
    if not message.guild:
        return

    state = get_state(message.guild.id)

    # Bỏ qua nếu không phải kênh đã setup
    if state.setup_channel_id is None or message.channel.id != state.setup_channel_id:
        return

    voice_client = message.guild.voice_client
    if voice_client is None or not voice_client.is_connected():
        return

    # Đảm bảo worker đang chạy (phòng trường hợp worker chết bất ngờ)
    if state.play_task is None or state.play_task.done():
        state.play_task = bot.loop.create_task(tts_worker(message.guild, state))
        log.info("[on_message] Đã khởi động lại TTS worker.")

    text = clean_text(message.content, state)
    log.info(f"[on_message] '{message.author}': '{text[:80]}' (queue={state.queue.qsize()})")

    if not text:
        return

    if len(text) > MAX_TEXT_LENGTH:
        await message.channel.send(f"⚠️ Tin nhắn quá dài (> {MAX_TEXT_LENGTH} ký tự). Bot sẽ không đọc để tránh kẹt mạng.")
        return

    if state.queue.qsize() >= MAX_QUEUE_SIZE:
        await message.add_reaction("⏳")
        return

    await state.queue.put(text)
    try:
        await message.add_reaction("👀")
    except Exception:
        pass

# ---------------------------------------------------------
# XỬ LÝ SỰ KIỆN VOICE (TỰ ĐỘNG THOÁT)
# ---------------------------------------------------------
@bot.event
async def on_voice_state_update(member, before, after):
    # Bỏ qua nếu là hành động của chính bot (tự join/leave/mute)
    if member.id == bot.user.id:
        return

    guild = member.guild
    voice_client = guild.voice_client

    if voice_client is None or not voice_client.is_connected():
        return

    state = get_state(guild.id)
    
    # Kiểm tra kênh thoại hiện tại của Bot
    bot_channel = voice_client.channel
    
    # Có người tham gia lại phòng Bot đang đứng -> Hủy đồng hồ đếm ngược (nếu có)
    if after.channel == bot_channel:
        if state.leave_timer and not state.leave_timer.done():
            state.leave_timer.cancel()
            state.leave_timer = None
            log.info(f"[Auto-Leave] Đã hủy hẹn giờ rời kênh ở server {guild.name} do có người vào.")

    # Có người rời khỏi phòng Bot đang đứng -> Kiểm tra phòng còn trống không
    elif before.channel == bot_channel and after.channel != bot_channel:
        # Số lượng người còn lại trong phòng (kể cả Bot)
        # Nếu == 1 tức là chỉ còn mỗi Bot bơ vơ
        if len(bot_channel.members) == 1:
            log.info(f"[Auto-Leave] Kênh {bot_channel.name} trống, bắt đầu đếm ngược 20s...")
            
            async def _auto_disconnect():
                try:
                    await asyncio.sleep(20)
                    if voice_client and voice_client.is_connected() and len(voice_client.channel.members) == 1:
                        # Dọn dẹp hàng đợi và task nhạc
                        if state.play_task:
                            state.play_task.cancel()
                            state.play_task = None
                        state.queue = asyncio.Queue()
                        
                        await voice_client.disconnect()
                        
                        # Gửi thông báo vô text channel
                        if state.setup_channel_id:
                            text_channel = guild.get_channel(state.setup_channel_id)
                            if text_channel:
                                await text_channel.send("👋 Mọi người đi hết rồi, bot cũng xin phép out kênh thoại đây! Trả lại sự tĩnh lặng...")
                        log.info(f"[Auto-Leave] Đã tự động rời kênh ở server {guild.name}.")
                except asyncio.CancelledError:
                    pass

            # Hủy timer cũ nếu có và tạo timer mới 20s
            if state.leave_timer and not state.leave_timer.done():
                state.leave_timer.cancel()
            state.leave_timer = bot.loop.create_task(_auto_disconnect())

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
