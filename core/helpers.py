"""Shared helpers for plugins: access checks, message building."""
import logging
import time
from typing import Optional

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChannelPrivate
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db
from core.keyboards import force_sub_keyboard, files_keyboard
from core.state import state, Session
from core.strings import FORCE_SUB, BANNED
from core.utils import format_duration, humanbytes

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMINS


async def check_force_sub(client: Client, user_id: int) -> Optional[str]:
    """Return invite link if the user must join; None if OK."""
    if not Config.FORCE_SUB_CHANNEL or is_admin(user_id):
        return None
    chan = Config.FORCE_SUB_CHANNEL
    try:
        chat_id = int(chan) if chan.lstrip("-").isdigit() else chan
        member = await client.get_chat_member(chat_id, user_id)
        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            raise UserNotParticipant
        return None
    except UserNotParticipant:
        pass
    except (ChatAdminRequired, ChannelPrivate) as e:
        logger.warning("Force-sub check failed (bot not admin?): %s", e)
        return None
    except Exception as e:
        logger.warning("Force-sub error: %s", e)
        return None
    # build link
    try:
        chat = await client.get_chat(chat_id)
        link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
        if not link:
            link = await client.export_chat_invite_link(chat_id)
        return link
    except Exception:
        return f"https://t.me/{chan.lstrip('@')}" if not chan.lstrip("-").isdigit() else None


async def gate(client: Client, message: Message) -> bool:
    """Common access gate. Returns True if user may continue."""
    user = message.from_user
    if not user:
        return False
    await db.add_user(user)
    if await db.is_banned(user.id) and not is_admin(user.id):
        await message.reply_text(BANNED)
        return False
    link = await check_force_sub(client, user.id)
    if link:
        await message.reply_text(FORCE_SUB, reply_markup=force_sub_keyboard(link))
        return False
    return True


async def gate_cb(client: Client, cq: CallbackQuery) -> bool:
    user = cq.from_user
    if await db.is_banned(user.id) and not is_admin(user.id):
        await cq.answer(BANNED, show_alert=True)
        return False
    return True


def session_summary(session: Session, settings: dict) -> str:
    lines = ["📂 **Current Files**\n"]
    if session.bg_video:
        lines.append("🎥 Background video: ✅")
    elif session.photos:
        n = len(session.photos)
        lines.append(f"🖼 Photos: **{n}** " + ("(slideshow)" if n > 1 else ""))
    else:
        lines.append("🖼 Photos: ❌ _(send a photo)_")
    if session.audios:
        n = len(session.audios)
        info = session.audio_info
        dur = format_duration(info.get("duration", 0)) if info else "?"
        extra = f" ({n} files merged)" if n > 1 else ""
        title = f" – _{info.get('title')}_" if info and info.get("title") else ""
        lines.append(f"🎵 Audio: ✅ `{dur}`{extra}{title}")
    else:
        lines.append("🎵 Audio: ❌ _(send an audio)_")
    lines.append("")
    vis = settings["visualizer"]
    lines.append(
        f"⚙️ **Output:** {settings['resolution']} • {settings['aspect']} • {settings['fit']} • "
        f"{settings['fps']}fps • {settings['quality']} • {settings['codec'].upper()}"
    )
    extras = []
    if vis != "none":
        extras.append(f"🌊 {vis}/{settings['vis_color']}")
    if settings.get("ken_burns"):
        extras.append("🎥 Ken Burns")
    if settings.get("fade"):
        extras.append("🌓 Fade")
    if settings.get("watermark_text"):
        extras.append("💧 Watermark")
    if settings.get("title_text"):
        extras.append("🔤 Title")
    if extras:
        lines.append("✨ " + " • ".join(extras))
    if session.ready:
        lines.append("\n🚀 **Ready!** Press CONVERT NOW.")
    return "\n".join(lines)


async def send_files_panel(message_or_cq, user_id: int, edit: bool = False):
    session = state.get(user_id)
    settings = await db.get_settings(user_id)
    text = session_summary(session, settings)
    kb = files_keyboard(session, session.ready)
    if edit and isinstance(message_or_cq, CallbackQuery):
        try:
            await message_or_cq.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
    else:
        msg = message_or_cq.message if isinstance(message_or_cq, CallbackQuery) else message_or_cq
        await msg.reply_text(text, reply_markup=kb)


def uptime_str() -> str:
    s = int(time.time() - state.started_at)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}d {h}h {m}m {s}s" if d else f"{h}h {m}m {s}s"
