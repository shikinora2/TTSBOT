#!/bin/bash
# ============================================================
# Script cài đặt đầy đủ cho Bot TTS trên Ubuntu
# Chạy: bash install.sh
# ============================================================

set -e  # Dừng ngay nếu có lỗi

echo "=============================="
echo " Cài đặt Bot TTS - Valtec-TTS"
echo "=============================="

# 1. PyTorch CPU
echo ""
echo "[1/4] Cài PyTorch CPU..."
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# 2. Tất cả dependencies của valtec-tts
echo ""
echo "[2/4] Cài dependencies..."
pip install \
    numpy scipy soundfile librosa tqdm \
    Unidecode num2words inflect cn2an jieba pypinyin \
    jamo gruut g2p-en anyascii \
    viphoneme underthesea vinorm \
    huggingface_hub eng-to-ipa

# 3. Discord bot packages
echo ""
echo "[3/4] Cài Discord bot packages..."
pip install discord.py==2.6.4 PyNaCl python-dotenv

# 4. Cài valtec-tts editable
echo ""
echo "[4/4] Cài valtec-tts..."
pip install -e ./valtec-tts-src

echo ""
echo "=============================="
echo " Cài đặt hoàn tất!"
echo " Chạy bot: python ttsbot.py"
echo "=============================="
