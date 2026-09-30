#!/usr/bin/env python3
"""
Advanced Audio → Video Telegram Bot
===================================
Entry point. Loads config, opens the database, registers bot commands,
starts background maintenance and runs the Pyrogram client with plugins.

Run:  python bot.py
Env:  API_ID, API_HASH, BOT_TOKEN  (+ optional OWNER_ID, ADMINS, LOG_CHANNEL, FORCE_SUB_CHANNEL ...)
"""
import asyncio
import logging
import shutil
import sys

from pyrogram import Client, idle
from pyrogram.types import BotCommand, BotCommandScopeChat

from core.config import Config, logger
from core.database import db
from core.state import state
from core.utils import cleanup

Config.validate()

if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
    logger.error("ffmpeg / ffprobe not found in PATH. Install ffmpeg first.")
    sys.exit(1)

app = Client(
    Config.SESSION_NAME,
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins=dict(root="plugins"),
    workers=16,
    max_concurrent_transmissions=4,
    sleep_threshold=30,
)

USER_COMMANDS = [
    BotCommand("start", "🚀 Start / Home"),
    BotCommand("convert", "🎬 Convert uploaded files"),
    BotCommand("settings", "⚙️ Output settings"),
    BotCommand("quick", "⚡ Quick modes (YouTube, Reels...)"),
    BotCommand("presets", "🎛 Saved presets"),
    BotCommand("files", "📂 Show uploaded files"),
    BotCommand("clear", "🗑 Clear uploaded files"),
    BotCommand("cancel", "❌ Cancel running job"),
    BotCommand("stats", "📊 Your stats"),
    BotCommand("history", "🕘 Last videos"),
    BotCommand("help", "❓ Help & guide"),
    BotCommand("about", "ℹ️ About the bot"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand("admin", "👑 Admin panel"),
    BotCommand("broadcast", "📢 Broadcast (reply to msg)"),
    BotCommand("users", "👥 Global stats"),
    BotCommand("server", "🖥 Server info"),
    BotCommand("ban", "🚫 Ban user"),
    BotCommand("unban", "✅ Unban user"),
    BotCommand("premium", "⭐ Toggle premium"),
]


async def maintenance_loop():
    """Every 15 min: drop stale sessions (1h idle) and orphan files."""
    from plugins.admin import cleanup_downloads
    while True:
        await asyncio.sleep(900)
        try:
            for uid in state.stale_sessions(3600):
                if not state.is_processing(uid):
                    old = state.clear(uid)
                    cleanup(*old.all_files())
            n, freed = cleanup_downloads(max_age=7200)
            if n:
                logger.info("Maintenance: removed %d orphan files", n)
        except Exception as e:
            logger.warning("Maintenance error: %s", e)


async def main():
    await db.connect()
    await app.start()
    me = await app.get_me()

    try:
        await app.set_bot_commands(USER_COMMANDS)
        for admin_id in Config.ADMINS:
            try:
                await app.set_bot_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception:
                pass
    except Exception as e:
        logger.warning("set_bot_commands: %s", e)

    asyncio.create_task(maintenance_loop())

    logger.info("✅ %s is online as @%s | admins=%s | max_jobs=%d",
                Config.BOT_NAME, me.username, sorted(Config.ADMINS) or "-", Config.MAX_CONCURRENT_TASKS)
    if Config.LOG_CHANNEL:
        try:
            await app.send_message(Config.LOG_CHANNEL, f"🟢 **{Config.BOT_NAME}** started as @{me.username}")
        except Exception as e:
            logger.warning("LOG_CHANNEL unreachable: %s", e)

    await idle()

    logger.info("Shutting down...")
    await app.stop()
    await db.close()


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        pass
