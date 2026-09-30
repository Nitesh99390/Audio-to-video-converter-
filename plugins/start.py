"""/start, /help, /about, /ping, /stats, /history + reply-keyboard button routing."""
import time
import logging

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db
from core.helpers import (
    gate, gate_cb, is_admin, send_files_panel, uptime_str, check_force_sub, access_block_text,
)
from core.keyboards import (
    main_reply_keyboard, request_reply_keyboard, start_keyboard, help_keyboard, quick_modes_keyboard,
    settings_keyboard, presets_keyboard, admin_keyboard, request_access_keyboard, duration_keyboard,
    duration_label,
    BTN_CONVERT, BTN_SETTINGS, BTN_PRESETS, BTN_STATUS, BTN_CANCEL, BTN_CLEAR,
    BTN_HELP, BTN_STATS, BTN_ABOUT, BTN_QUICK, BTN_DURATION, BTN_ACCESS, BTN_ADMIN, REPLY_BUTTONS,
)
from core.state import state
from core.strings import START, HELP_MAIN, HELP_TOPICS, ABOUT
from core.utils import humanbytes, format_duration, format_time

logger = logging.getLogger(__name__)


# ================================================================ /start
@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    # /start is allowed for everyone (banned / force-sub still enforced), so new users can request access
    if not await gate(client, message, need_access=False):
        return
    user = message.from_user
    block = await access_block_text(user.id)
    if block:
        await message.reply_text(
            f"👋 Hello **{user.first_name}**!\n\n" + block,
            reply_markup=request_reply_keyboard(),
        )
        await message.reply_text("👇 Tap to request access:", reply_markup=request_access_keyboard())
        return
    text = START.format(name=user.first_name)
    await message.reply_text(text, reply_markup=main_reply_keyboard(is_admin(user.id)))
    await message.reply_text("👇 **Quick actions:**", reply_markup=start_keyboard())


@Client.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    if not await gate(client, message, need_access=False):
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
    left = await db.access_remaining(user_id)
    if is_admin(user_id):
        plan = "👑 Admin"
    elif left == float("inf"):
        plan = "♾ Permanent access"
    elif left:
        plan = f"✅ Access ({format_time(left)} left)"
    else:
        plan = "🔒 No access"
    text = (
        "📊 **Your stats**\n\n"
        f"👤 ID: `{user_id}`\n"
        f"🏷 Plan: {plan}\n"
        f"🎬 Total videos: **{u.get('total_videos', 0)}**\n"
        f"📦 Total output: **{humanbytes(u.get('total_bytes', 0))}**\n"
        f"📅 Today: **{today}**\n"
        f"🗓 Joined: {time.strftime('%d %b %Y', time.localtime(u.get('joined_at', time.time())))}"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("history") & filters.private)
async def history_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    rows = await db.user_history(message.from_user.id, 5)
    if not rows:
        await message.reply_text("🕘 You have not created any videos yet.")
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
    uid = message.from_user.id
    text = message.text

    # buttons that work without approval
    if text == BTN_ACCESS:
        if not await gate(client, message, need_access=False):
            return
        from plugins.access import send_access_status
        await send_access_status(message, uid)
        return
    if text == BTN_HELP:
        if not await gate(client, message, need_access=False):
            return
        await message.reply_text(HELP_MAIN, reply_markup=help_keyboard())
        return

    if not await gate(client, message):
        return

    if text == BTN_CONVERT:
        from plugins.convert import start_conversion
        await start_conversion(client, message, uid)
    elif text == BTN_DURATION:
        s = await db.get_settings(uid)
        cur = int(s.get("target_duration") or 0)
        await message.reply_text(
            "⏱ **Final video length**\n\nIf longer than the audio, the audio is looped seamlessly. "
            f"If shorter, the video is trimmed.\n\nCurrent: **{duration_label(cur)}**",
            reply_markup=duration_keyboard(cur),
        )
    elif text == BTN_SETTINGS:
        s = await db.get_settings(uid)
        await message.reply_text("⚙️ **Settings panel**\nTap any option to change it.", reply_markup=settings_keyboard(s))
    elif text == BTN_PRESETS:
        names = await db.list_presets(uid)
        await message.reply_text(_presets_text(names), reply_markup=presets_keyboard(names))
    elif text == BTN_STATUS:
        await send_files_panel(message, uid)
    elif text == BTN_CANCEL:
        if state.cancel(uid):
            await message.reply_text("🛑 Cancelling the current job...")
        else:
            await message.reply_text("ℹ️ No job is running.")
    elif text == BTN_CLEAR:
        from plugins.media import clear_session
        clear_session(uid)
        await message.reply_text("🗑 All uploaded files deleted. Send a new photo / audio.")
    elif text == BTN_STATS:
        await send_user_stats(message, uid)
    elif text == BTN_ABOUT:
        await message.reply_text(
            ABOUT.format(uptime=uptime_str(), active=state.active_tasks, max_jobs=Config.MAX_CONCURRENT_TASKS),
            disable_web_page_preview=True,
        )
    elif text == BTN_QUICK:
        await message.reply_text(_quick_text(), reply_markup=quick_modes_keyboard())


@Client.on_message(filters.private & filters.regex(rf"^{BTN_ADMIN}$"))
async def admin_button(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    c = await db.access_counts()
    await message.reply_text("👑 **Admin panel**", reply_markup=admin_keyboard(c["pending"], c["approved"]))


def _presets_text(names):
    if not names:
        return "🎛 **Presets**\n\nNo presets saved yet. Configure settings and tap 💾 Save."
    return "🎛 **Your presets**\n\nTap a preset to load it, 🗑 to delete."


def _quick_text():
    return (
        "⚡ **Quick Modes**\n\n"
        "Apply platform-optimized settings with one tap. "
        "Fine-tune later in ⚙️ Settings."
    )


# ================================================ navigation callbacks
@Client.on_callback_query(filters.regex(r"^nav:(?!menu_)(\w+)$"))
async def nav_cb(client: Client, cq: CallbackQuery):
    target = cq.matches[0].group(1)
    if not await gate_cb(client, cq, need_access=target not in ("help", "start", "checksub")):
        return
    uid = cq.from_user.id
    try:
        if target == "start":
            block = await access_block_text(uid)
            if block:
                await cq.message.edit_text(block, reply_markup=request_access_keyboard())
            else:
                await cq.message.edit_text(START.format(name=cq.from_user.first_name), reply_markup=start_keyboard())
        elif target == "help":
            await cq.message.edit_text(HELP_MAIN, reply_markup=help_keyboard())
        elif target == "settings":
            s = await db.get_settings(uid)
            await cq.message.edit_text("⚙️ **Settings panel**\nTap any option to change it.",
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
                await cq.answer("❌ You have not joined yet!", show_alert=True)
                return
            await cq.message.edit_text("✅ Thank you! You can use the bot now.\n\nTap /start.")
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
