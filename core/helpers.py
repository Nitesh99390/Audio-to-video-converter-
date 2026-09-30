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
from core.keyboards import force_sub_keyboard, files_keyboard, request_access_keyboard
from core.policy import apply_policy
from core.state import state, Session
from core.strings import (
    FORCE_SUB, BANNED, ACCESS_REQUIRED, ACCESS_PENDING, ACCESS_EXPIRED, ACCESS_REJECTED,
)
from core.utils import format_duration, format_time

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMINS


def is_owner(user_id: int) -> bool:
    return user_id == Config.OWNER_ID or (not Config.OWNER_ID and user_id in Config.ADMINS)


async def get_settings(user_id: int) -> dict:
    """Settings with the feature policy applied (Pro engine only for admins etc.).
    If the stored row violates the policy it is fixed in the DB as well."""
    s = await db.get_settings(user_id)
    fixed, changed = apply_policy(user_id, s)
    if changed:
        await db.save_settings(user_id, fixed)
    return fixed


def fmt_expiry(expires_at: float) -> str:
    if not expires_at:
        return "never (permanent)"
    return time.strftime("%d %b %Y, %H:%M UTC", time.gmtime(expires_at))


def fmt_left(seconds: Optional[float]) -> str:
    if seconds is None:
        return "no access"
    if seconds == float("inf"):
        return "unlimited"
    return format_time(seconds)


# ---------------------------------------------------------------- force sub
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
    try:
        chat = await client.get_chat(chat_id)
        link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
        if not link:
            link = await client.export_chat_invite_link(chat_id)
        return link
    except Exception:
        return f"https://t.me/{chan.lstrip('@')}" if not chan.lstrip("-").isdigit() else None


# ---------------------------------------------------------------- approval
async def access_block_text(user_id: int) -> Optional[str]:
    """Return the text to show if the user is NOT allowed; None if allowed."""
    if not Config.ACCESS_REQUIRED or is_admin(user_id):
        return None
    if await db.has_access(user_id):
        return None
    a = await db.get_access(user_id)
    if not a:
        return ACCESS_REQUIRED
    if a["status"] == "pending":
        return ACCESS_PENDING
    if a["status"] == "rejected":
        return ACCESS_REJECTED.format(cooldown=Config.REQUEST_COOLDOWN_MIN)
    if a["status"] == "approved":          # approved but expired
        return ACCESS_EXPIRED
    return ACCESS_REQUIRED


async def gate(client: Client, message: Message, need_access: bool = True) -> bool:
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
    if need_access:
        block = await access_block_text(user.id)
        if block:
            await message.reply_text(block, reply_markup=request_access_keyboard())
            return False
    return True


async def gate_cb(client: Client, cq: CallbackQuery, need_access: bool = True) -> bool:
    user = cq.from_user
    if await db.is_banned(user.id) and not is_admin(user.id):
        await cq.answer(BANNED, show_alert=True)
        return False
    if need_access:
        block = await access_block_text(user.id)
        if block:
            await cq.answer("🔐 You need approval to use this. Tap 🔑 My Access.", show_alert=True)
            return False
    return True


# ---------------------------------------------------------------- panels
def session_summary(session: Session, settings: dict) -> str:
    lines = ["📂 **Your files**\n"]
    if session.intro:
        d = format_duration(session.intro_info.get("duration", 0)) if session.intro_info else "?"
        lines.append(f"🎬 Intro ✓ `{d}`")
    if session.bg_video:
        lines.append("🎥 Background video ✓")
    elif session.photos:
        n = len(session.photos)
        lines.append(f"🖼 {n} photo{'s' if n > 1 else ''} ✓" + (" · slideshow" if n > 1 else ""))
    else:
        lines.append("🖼 Photo — _waiting_")
    audio_dur = 0
    if session.audios:
        n = len(session.audios)
        info = session.audio_info
        audio_dur = info.get("duration", 0) if info else 0
        dur = format_duration(audio_dur) if info else "?"
        extra = f" · {n} files merged" if n > 1 else ""
        title = f" · _{info.get('title')}_" if info and info.get("title") else ""
        lines.append(f"🎵 Audio ✓ `{dur}`{extra}{title}")
    else:
        lines.append("🎵 Audio — _waiting_")
    if session.outro:
        d = format_duration(session.outro_info.get("duration", 0)) if session.outro_info else "?"
        lines.append(f"🏁 Outro ✓ `{d}`")
    lines.append("")
    target = int(settings.get("target_duration") or 0)
    engine = "⚡ Lite" if settings.get("engine", "lite") == "lite" else "🎬 Pro"
    extra_len = 0.0
    if session.intro:
        extra_len += float(session.intro_info.get("duration", 0) or 0)
    if session.outro:
        extra_len += float(session.outro_info.get("duration", 0) or 0)
    clip_note = f" + {format_duration(extra_len)} intro/outro" if extra_len else ""
    if target:
        loop_note = " · audio looped" if audio_dur and target > audio_dur else ""
        lines.append(f"⏱ Length: **{format_duration(target)}**{clip_note}{loop_note}")
    else:
        lines.append(f"⏱ Length: **same as audio**{clip_note}")
    lines.append(f"⚙️ {engine} · {settings['resolution']} · {settings['aspect']} · {settings['fps']} fps · audio {settings['audio_mode']}")
    extras = []
    if settings.get("engine") == "pro":
        if settings["visualizer"] != "none":
            extras.append(f"🌊 {settings['visualizer']}")
        if settings.get("ken_burns"):
            extras.append("🎥 Ken Burns")
        if settings.get("fade"):
            extras.append("🌓 fade")
    if settings.get("watermark_text"):
        extras.append("💧 watermark")
    if settings.get("title_text"):
        extras.append("🔤 title")
    if extras:
        lines.append("✨ " + " · ".join(extras))
    if session.ready:
        if session.has_intro_outro:
            parts = (["intro"] if session.intro else []) + ["photo + audio"] + (["outro"] if session.outro else [])
            lines.append("🧩 Order: `" + " → ".join(parts) + "`")
        lines.append("\n🚀 Ready — tap **Convert now**.")
    elif not session.has_visual and not session.has_audio:
        lines.append("\nSend a **photo** and an **audio** file to begin.")
    return "\n".join(lines)


async def send_files_panel(message_or_cq, user_id: int, edit: bool = False):
    session = state.get(user_id)
    settings = await get_settings(user_id)
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


def parse_duration_text(text: str) -> Optional[int]:
    """Parse '10h', '2h30m', '90m', '1:30:00', '5400' -> seconds."""
    import re
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None
    if re.fullmatch(r"\d+", t):
        v = int(t)
        return v * 60 if v <= 24 * 60 and v < 1000 else v   # plain number: minutes if small, else seconds
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", t)
    if m:
        h = int(m.group(1) or 0)
        return h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h(?:ours?|rs?)?)?(?:(\d+)m(?:in(?:utes?)?)?)?(?:(\d+)s(?:ec(?:onds?)?)?)?", t)
    if m and any(m.groups()):
        h = float(m.group(1) or 0)
        return int(h * 3600) + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
    return None
