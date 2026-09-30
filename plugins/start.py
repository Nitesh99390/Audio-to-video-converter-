"""/start, /help, /about, /ping, /stats, /history + reply-keyboard button routing."""
import time
import logging

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db
from core.helpers import gate, gate_cb, is_admin, send_files_panel, uptime_str, check_force_sub
from core.keyboards import (
    main_reply_keyboard, start_keyboard, help_keyboard, quick_modes_keyboard,
    settings_keyboard, presets_keyboard, admin_keyboard, force_sub_keyboard,
    BTN_CONVERT, BTN_SETTINGS, BTN_PRESETS, BTN_STATUS, BTN_CANCEL, BTN_CLEAR,
    BTN_HELP, BTN_STATS, BTN_ABOUT, BTN_QUICK, REPLY_BUTTONS,
)
from core.state import state
from core.strings import START, HELP_MAIN, HELP_TOPICS, ABOUT, FORCE_SUB
from core.utils import humanbytes, format_duration, format_time

logger = logging.getLogger(__name__)


# ================================================================ /start
@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    user = message.from_user
    settings = await db.get_settings(user.id)
    lang = settings.get("language", "hi")
    text = START.get(lang, START["hi"]).format(name=user.first_name)
    await message.reply_text(text, reply_markup=main_reply_keyboard(is_admin(user.id)))
    await message.reply_text("👇 **Quick actions:**", reply_markup=start_keyboard())
    if Config.LOG_CHANNEL and not await db.get_user(user.id):
        pass  # (new-user log handled in gate via add_user; optional extension)


@Client.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    await message.reply_text(HELP_MAIN, reply_markup=help_keyboard())


@Client.on_message(filters.command("about") & filters.private)
async def about_cmd(client: Client, message: Message):
    await message.reply_text(
        ABOUT.format(uptime=uptime_str(), active=state.active_tasks, max_jobs=Config.MAX_CONCURRENT_TASKS),
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command("ping"))
async def ping_cmd(client: Client, message: Message):
    t = time.time()
    m = await message.reply_text("🏓 Pinging...")
    await m.edit_text(f"🏓 **Pong!** `{(time.time() - t) * 1000:.0f} ms`\n⏱ Uptime: `{uptime_str()}`")


@Client.on_message(filters.command("stats") & filters.private)
async def stats_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    await send_user_stats(message, message.from_user.id)


async def send_user_stats(message: Message, user_id: int):
    u = await db.get_user(user_id) or {}
    today = await db.today_usage(user_id)
    premium = "⭐ Premium" if u.get("is_premium") else "🆓 Free"
    limit = "∞" if (u.get("is_premium") or is_admin(user_id)) else Config.DAILY_LIMIT_FREE
    text = (
        "📊 **Your Stats**\n\n"
        f"👤 ID: `{user_id}`\n"
        f"🏷 Plan: {premium}\n"
        f"🎬 Total videos: **{u.get('total_videos', 0)}**\n"
        f"📦 Total output: **{humanbytes(u.get('total_bytes', 0))}**\n"
        f"📅 Today: **{today} / {limit}**\n"
        f"🗓 Joined: {time.strftime('%d %b %Y', time.localtime(u.get('joined_at', time.time())))}"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("history") & filters.private)
async def history_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    rows = await db.user_history(message.from_user.id, 5)
    if not rows:
        await message.reply_text("🕘 Abhi tak koi video nahi banaya.")
        return
    lines = ["🕘 **Last 5 videos**\n"]
    for r in rows:
        lines.append(
            f"• {time.strftime('%d %b %H:%M', time.localtime(r['created_at']))} — "
            f"{r['mode']} • {format_duration(r['duration'])} • {humanbytes(r['size'])} • "
            f"⏱ {format_time(r['render_time'])}"
        )
    await message.reply_text("\n".join(lines))


# ================================================ reply-keyboard buttons
@Client.on_message(filters.private & filters.text & filters.create(lambda _, __, m: m.text in REPLY_BUTTONS))
async def reply_button_router(client: Client, message: Message):
    if not await gate(client, message):
        return
    uid = message.from_user.id
    text = message.text

    if text == BTN_CONVERT:
        from plugins.convert import start_conversion
        await start_conversion(client, message, uid)
    elif text == BTN_SETTINGS:
        s = await db.get_settings(uid)
        await message.reply_text("⚙️ **Settings Panel**\nTap any option to change it.", reply_markup=settings_keyboard(s))
    elif text == BTN_PRESETS:
        names = await db.list_presets(uid)
        await message.reply_text(_presets_text(names), reply_markup=presets_keyboard(names))
    elif text == BTN_STATUS:
        await send_files_panel(message, uid)
    elif text == BTN_CANCEL:
        if state.cancel(uid):
            await message.reply_text("🛑 Cancelling current job...")
        else:
            await message.reply_text("ℹ️ Koi job nahi chal raha.")
    elif text == BTN_CLEAR:
        from plugins.media import clear_session
        clear_session(uid)
        await message.reply_text("🗑 Saari uploaded files delete ho gayi. Naya photo/audio bhejo.")
    elif text == BTN_HELP:
        await message.reply_text(HELP_MAIN, reply_markup=help_keyboard())
    elif text == BTN_STATS:
        await send_user_stats(message, uid)
    elif text == BTN_ABOUT:
        await message.reply_text(
            ABOUT.format(uptime=uptime_str(), active=state.active_tasks, max_jobs=Config.MAX_CONCURRENT_TASKS),
            disable_web_page_preview=True,
        )
    elif text == BTN_QUICK:
        await message.reply_text(_quick_text(), reply_markup=quick_modes_keyboard())


@Client.on_message(filters.private & filters.regex(r"^👑 Admin Panel$"))
async def admin_button(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.reply_text("👑 **Admin Panel**", reply_markup=admin_keyboard())


def _presets_text(names):
    if not names:
        return "🎛 **Presets**\n\nAbhi koi preset save nahi hai. Settings set karke 💾 Save dabao."
    return "🎛 **Your Presets**\n\nTap a preset to load it, 🗑 to delete."


def _quick_text():
    return (
        "⚡ **Quick Modes**\n\n"
        "Ek tap me platform-optimized settings apply karo. "
        "Baad me ⚙️ Settings se fine-tune kar sakte ho."
    )


# ================================================ navigation callbacks
@Client.on_callback_query(filters.regex(r"^nav:(?!menu_)(\w+)$"))
async def nav_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    target = cq.matches[0].group(1)
    uid = cq.from_user.id
    try:
        if target == "start":
            settings = await db.get_settings(uid)
            text = START.get(settings.get("language", "hi"), START["hi"]).format(name=cq.from_user.first_name)
            await cq.message.edit_text(text, reply_markup=start_keyboard())
        elif target == "help":
            await cq.message.edit_text(HELP_MAIN, reply_markup=help_keyboard())
        elif target == "settings":
            s = await db.get_settings(uid)
            await cq.message.edit_text("⚙️ **Settings Panel**\nTap any option to change it.",
                                       reply_markup=settings_keyboard(s))
        elif target == "quick":
            await cq.message.edit_text(_quick_text(), reply_markup=quick_modes_keyboard())
        elif target == "presets":
            names = await db.list_presets(uid)
            await cq.message.edit_text(_presets_text(names), reply_markup=presets_keyboard(names))
        elif target == "files":
            await send_files_panel(cq, uid, edit=True)
        elif target == "checksub":
            link = await check_force_sub(client, uid)
            if link:
                await cq.answer("❌ Aap abhi tak join nahi kiye!", show_alert=True)
                return
            await cq.message.edit_text("✅ Thank you! Ab aap bot use kar sakte ho.\n\n/start dabao.")
        await cq.answer()
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            logger.debug("nav error: %s", e)
        await cq.answer()


@Client.on_callback_query(filters.regex(r"^help:(\w+)$"))
async def help_topic_cb(client: Client, cq: CallbackQuery):
    topic = cq.matches[0].group(1)
    text = HELP_TOPICS.get(topic, HELP_MAIN)
    try:
        await cq.message.edit_text(text, reply_markup=help_keyboard())
    except Exception:
        pass
    await cq.answer()
