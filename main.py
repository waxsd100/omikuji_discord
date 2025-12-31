import json
import logging
import os
import sys
import re
import atexit

import discord
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 二重起動防止
LOCK_FILE = os.path.join(os.path.dirname(__file__), ".bot.lock")

# おみくじキャッシュファイル
OMIKUJI_CACHE_FILE = os.path.join(os.path.dirname(__file__), "omikuji_cache.json")


def load_omikuji_cache():
    """おみくじキャッシュを読み込む"""
    if os.path.exists(OMIKUJI_CACHE_FILE):
        with open(OMIKUJI_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_omikuji_cache(cache):
    """おみくじキャッシュを保存する"""
    with open(OMIKUJI_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def has_drawn_omikuji(guild_id: int, user_id: int) -> bool:
    """ユーザーが既におみくじを引いたか確認"""
    cache = load_omikuji_cache()
    guild_cache = cache.get(str(guild_id), {})
    return str(user_id) in guild_cache


def save_omikuji_result(guild_id: int, user_id: int, result: str, message_url: str):
    """おみくじ結果を保存"""
    cache = load_omikuji_cache()
    if str(guild_id) not in cache:
        cache[str(guild_id)] = {}
    cache[str(guild_id)][str(user_id)] = {
        "result": result,
        "message_url": message_url
    }
    save_omikuji_cache(cache)


def get_omikuji_data(guild_id: int, user_id: int) -> dict:
    """保存されたおみくじデータを取得"""
    cache = load_omikuji_cache()
    guild_cache = cache.get(str(guild_id), {})
    return guild_cache.get(str(user_id), {})


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
    logging.info(f"{client.user} としてログインしました")


@client.event
async def on_message(message):
    # 自分自身のメッセージは無視
    if message.author == client.user:
        return

    # メッセージログを出力
    logging.info(f"[{message.guild}] #{message.channel} | {message.author}: {message.content}")

    # Botへのリプライかどうかチェック
    is_reply_to_bot = False
    bot_reply_content = None
    if message.reference:
        try:
            replied_message = await message.channel.fetch_message(message.reference.message_id)
            if replied_message.author == client.user:
                is_reply_to_bot = True
                bot_reply_content = replied_message.content
        except discord.NotFound:
            pass

    # BOTがメンションされているか、Botへのリプライかチェック
    if client.user in message.mentions or is_reply_to_bot:
        # メンションを除去したメッセージ内容を取得
        content = message.content.replace(f"<@{client.user.id}>", "").strip()

        # メッセージに「おみくじ」が含まれているかチェック
        if "おみくじ" in message.content:
            guild_id = message.guild.id
            user_id = message.author.id

            # 既に引いているか確認
            if has_drawn_omikuji(guild_id, user_id):
                data = get_omikuji_data(guild_id, user_id)
                message_url = data.get("message_url", "")
                response = f"既におみくじを引いています\n{message_url}"
                await message.reply(response)
            else:
                # おみくじを引く
                result = await call_api("おみくじ引きたいな。", is_omikuji=True)
                response = f"🎋 おみくじ結果 🎋\n\n{result}"
                reply_message = await message.reply(response)
                # メッセージURLを生成して保存
                message_url = f"https://discord.com/channels/{guild_id}/{message.channel.id}/{reply_message.id}"
                save_omikuji_result(guild_id, user_id, result, message_url)
        else:
            # Botへのリプライの場合は直前のBot返信 + 今のメッセージを送信
            if is_reply_to_bot and bot_reply_content:
                conversation_text = f"「{bot_reply_content}」に対して「{content}」"
                result = await call_api(conversation_text)
            else:
                # 最初のメンションの場合はメッセージ内容をそのまま送信
                result = await call_api(content)
            await message.reply(result)


# Botを起動
client.run(TOKEN)
