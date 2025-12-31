import logging
import os
import sys
import re
import atexit

import discord
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# 二重起動防止
LOCK_FILE = os.path.join(os.path.dirname(__file__), ".bot.lock")


def check_already_running():
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE, "r") as f:
            old_pid = f.read().strip()
        # 古いプロセスがまだ動いているか確認
        try:
            os.kill(int(old_pid), 0)
            print(f"Botは既に起動しています (PID: {old_pid})")
            sys.exit(1)
        except (OSError, ValueError):
            # プロセスが存在しない場合はロックファイルを削除
            os.remove(LOCK_FILE)

    # 新しいロックファイルを作成
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def cleanup_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


check_already_running()
atexit.register(cleanup_lock)

TOKEN = os.getenv("DISCORD_TOKEN")
OMIKUJI_API_URL = os.getenv("OMIKUJI_API_URL")
OMIKUJI_API_KEY = os.getenv("OMIKUJI_API_KEY")

# Intentsの設定
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


def format_omikuji(text):
    """おみくじの結果を読みやすく整形"""
    # 第X番〇〇吉/凶の後に改行
    text = re.sub(r"(第.+?番.+?[吉凶])、", r"**\1**\n\n", text)
    # 句点の後に改行
    text = text.replace("。", "。\n")
    return text.strip()


async def call_api(text: str, is_omikuji: bool = False):
    """APIにメッセージを送信して結果を取得"""
    params = {
        "text": text,
        "appkey": OMIKUJI_API_KEY
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(OMIKUJI_API_URL, params=params) as response:
            if response.status == 200:
                data = await response.json()
                result = data.get("text", "応答を取得できませんでした...")
                if is_omikuji:
                    return format_omikuji(result)
                return result
            else:
                return "APIに接続できませんでした..."


@client.event
async def on_ready():
    print(f"{client.user} としてログインしました")


@client.event
async def on_message(message):
    # 自分自身のメッセージは無視
    if message.author == client.user:
        return

    # メッセージログを出力
    logging.info(f"[{message.guild}] #{message.channel} | {message.author}: {message.content}")

    # BOTがメンションされているかチェック
    if client.user in message.mentions:
        # メンションを除去したメッセージ内容を取得
        content = message.content.replace(f"<@{client.user.id}>", "").strip()

        # メッセージに「おみくじ」が含まれているかチェック
        if "おみくじ" in message.content:
            # おみくじを引く
            result = await call_api("おみくじ引きたいな。", is_omikuji=True)
            response = f"🎋 おみくじ結果 🎋\n\n{result}"
            await message.reply(response)
        else:
            # おみくじ以外の場合はメッセージ内容をAPIに送信
            result = await call_api(content)
            await message.reply(result)


# Botを起動
client.run(TOKEN)
