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
import shutil
import sys

from pyrogram import Client, idle
from pyrogram.types import BotCommand, BotCommandScopeChat

from core.config import Config, logger
from core.database import db
from core import storage

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

# Keep the "/" menu short: only what a user needs. Everything else is reachable from the keyboard.
USER_COMMANDS = [
    BotCommand("start", "Home"),
    BotCommand("convert", "Convert the uploaded files"),
    BotCommand("duration", "Final video length, e.g. /duration 10h"),
    BotCommand("settings", "Output settings"),
    BotCommand("files", "Show / remove uploaded files"),
    BotCommand("cancel", "Cancel the running job"),
    BotCommand("myaccess", "Access status / request access"),
    BotCommand("help", "Guide & commands"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand("admin", "Admin panel"),
    BotCommand("pending", "Pending access requests"),
    BotCommand("approved", "Approved users"),
    BotCommand("approve", "/approve <id> [10h|3d|permanent]"),
    BotCommand("extend", "/extend <id> <5h>"),
    BotCommand("revoke", "/revoke <id>"),
    BotCommand("broadcast", "Broadcast (reply to a message)"),
    BotCommand("storage", "Disk usage & auto-clean status"),
    BotCommand("cleanup", "Delete all idle files now"),
    BotCommand("server", "Server info"),
    BotCommand("ban", "/ban <id> [reason]"),
    BotCommand("unban", "/unban <id>"),
]


async def maintenance_loop():
    """
    Disk watchdog. Runs every CLEANUP_INTERVAL_SEC:
      * deletes orphan / temp files and idle uploads (SESSION_TTL_SEC)
      * enforces the work-folder quota (MAX_STORAGE_MB)
      * if free disk falls under MIN_FREE_MB, evicts everything not owned by a running job
    """
    while True:
        await asyncio.sleep(Config.CLEANUP_INTERVAL_SEC)
        try:
            storage.sweep()
            if storage.disk_free() < storage.reserve_bytes():
                storage.emergency_evict()
        except Exception as e:
            logger.warning("Maintenance error: %s", e)


async def main():
    # a previous run (crash / notebook restart) may have left gigabytes behind
    storage.purge_all()
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
    from plugins.access import expiry_watcher
    asyncio.create_task(expiry_watcher(app))

    logger.info("✅ %s is online as @%s | owner=%s | admins=%s | approval=%s | pro=%s | max_jobs=%d | "
                "storage quota=%dMB min_free=%dMB",
                Config.BOT_NAME, me.username, Config.OWNER_ID, sorted(Config.ADMINS) or "-",
                "ON" if Config.ACCESS_REQUIRED else "OFF",
                "admins only" if Config.PRO_ENGINE_ADMIN_ONLY else "everyone",
                Config.MAX_CONCURRENT_TASKS, Config.MAX_STORAGE_MB, Config.MIN_FREE_MB)
    if Config.OWNER_ID:
        try:
            c = await db.access_counts()
            await app.send_message(
                Config.OWNER_ID,
                f"🟢 **{Config.BOT_NAME}** is online as @{me.username}\n"
                f"🔐 Approval: {'ON' if Config.ACCESS_REQUIRED else 'OFF'} · ⏳ {c['pending']} pending · ✅ {c['approved']} approved\n"
                f"🎬 Pro engine: {'admins only' if Config.PRO_ENGINE_ADMIN_ONLY else 'everyone'}\n"
                f"🗄 Disk free: {storage.disk_free() // (1024 * 1024)} MB · auto-clean every "
                f"{Config.CLEANUP_INTERVAL_SEC // 60} min",
            )
        except Exception as e:
            logger.warning("Owner %s unreachable (they must /start the bot once): %s", Config.OWNER_ID, e)
    if Config.LOG_CHANNEL:
        try:
            await app.send_message(Config.LOG_CHANNEL, f"🟢 **{Config.BOT_NAME}** started as @{me.username}")
        except Exception as e:
            logger.warning("LOG_CHANNEL unreachable: %s", e)

    await idle()

    logger.info("Shutting down...")
    await app.stop()
    await db.close()
    storage.purge_all()


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        pass
