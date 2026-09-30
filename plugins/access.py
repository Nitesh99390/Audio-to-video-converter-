"""
Approval / access system.

User side:   /request, 🔑 My Access button, "📨 Request Access" inline button.
Owner side:  every request arrives as a message with one-tap duration buttons
             (30 min · 1 h · 2 h · 3 h · 5 h · 10 h · 1 d · 3 d · 7 d · 30 d · permanent),
             plus Reject / Ban. Commands: /approve /reject /revoke /extend /pending /approved /access.
A background task notifies users when their time is over.
"""
import asyncio
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, User

from core.config import Config
from core.database import db
from core.helpers import is_admin, fmt_expiry, fmt_left, parse_duration_text
from core.keyboards import (
    approve_keyboard, manage_user_keyboard, request_access_keyboard, main_reply_keyboard,
    APPROVE_DURATIONS,
)
from core.strings import (
    ACCESS_SENT, ACCESS_PENDING, ACCESS_COOLDOWN, ACCESS_GRANTED_USER, ACCESS_EXTENDED_USER,
    ACCESS_REVOKED_USER, ACCESS_REJECTED_USER, ACCESS_EXPIRED_USER, ACCESS_STATUS, ADMIN_NEW_REQUEST,
    ACCESS_REQUIRED, ACCESS_EXPIRED, BANNED,
)
from core.utils import format_time

logger = logging.getLogger(__name__)

admin_filter = filters.create(lambda _, __, m: bool(m.from_user and is_admin(m.from_user.id)))


def _human(seconds: float) -> str:
    if not seconds:
        return "Permanent"
    for label, s in APPROVE_DURATIONS.items():
        if s == seconds:
            return label.replace("♾ ", "")
    return format_time(seconds)


def _mention(u: User) -> str:
    return u.mention if u else "unknown"


# ================================================================ user side
async def send_request(client: Client, user: User, origin: Message = None, cq: CallbackQuery = None,
                       note: str = ""):
    """Create a pending request and notify all admins with approval buttons."""
    uid = user.id
    if is_admin(uid):
        text = "👑 You are an admin — you always have access."
        return await (cq.answer(text, show_alert=True) if cq else origin.reply_text(text))
    if await db.is_banned(uid):
        return await (cq.answer(BANNED, show_alert=True) if cq else origin.reply_text(BANNED))
    if await db.has_access(uid):
        left = await db.access_remaining(uid)
        text = f"✅ You already have access. Time left: **{fmt_left(left)}**"
        return await (cq.answer(text.replace("**", ""), show_alert=True) if cq else origin.reply_text(text))

    a = await db.get_access(uid)
    now = time.time()
    if a:
        if a["status"] == "pending":
            # allow re-ping only after cooldown
            if now - (a["requested_at"] or 0) < Config.REQUEST_COOLDOWN_MIN * 60:
                text = ACCESS_PENDING
                return await (cq.answer("⏳ Your request is still pending.", show_alert=True) if cq
                              else origin.reply_text(text))
        elif a["status"] == "rejected":
            wait = Config.REQUEST_COOLDOWN_MIN * 60 - (now - (a["requested_at"] or 0))
            if wait > 0:
                text = ACCESS_COOLDOWN.format(left=format_time(wait))
                return await (cq.answer(text.replace("**", ""), show_alert=True) if cq else origin.reply_text(text))

    await db.request_access(uid, note)

    # notify owner / admins
    username = f"@{user.username}" if user.username else "—"
    note_line = f"📝 Note: _{note}_\n" if note else ""
    prev = ""
    if a and a["status"] == "approved":
        prev = f"ℹ️ Previous access expired {fmt_expiry(a['expires_at'])}\n"
    text = ADMIN_NEW_REQUEST.format(
        mention=_mention(user), uid=uid, username=username,
        when=time.strftime("%d %b %Y, %H:%M UTC", time.gmtime(now)), note=note_line + prev,
    )
    targets = [Config.OWNER_ID] if Config.OWNER_ID else sorted(Config.ADMINS)
    delivered = False
    for admin_id in targets:
        try:
            await client.send_message(admin_id, text, reply_markup=approve_keyboard(uid))
            delivered = True
        except Exception as e:
            logger.warning("Could not notify admin %s: %s", admin_id, e)
    if not delivered:
        logger.error("No admin could be notified about request from %s (owner must /start the bot first)", uid)

    if cq:
        await cq.answer("✅ Request sent!")
        try:
            await cq.message.edit_text(ACCESS_SENT)
        except Exception:
            pass
    else:
        await origin.reply_text(ACCESS_SENT)


@Client.on_message(filters.command("request") & filters.private)
async def request_cmd(client: Client, message: Message):
    await db.add_user(message.from_user)
    note = " ".join(message.command[1:])[:200]
    await send_request(client, message.from_user, origin=message, note=note)


@Client.on_callback_query(filters.regex(r"^access:request$"))
async def request_cb(client: Client, cq: CallbackQuery):
    await db.add_user(cq.from_user)
    await send_request(client, cq.from_user, cq=cq)


async def send_access_status(message: Message, uid: int):
    if is_admin(uid):
        await message.reply_text("👑 **Admin** — unlimited access.")
        return
    a = await db.get_access(uid)
    left = await db.access_remaining(uid)
    if left is not None:
        status = "✅ Approved"
        await message.reply_text(ACCESS_STATUS.format(status=status, left=fmt_left(left),
                                                      expires=fmt_expiry(a["expires_at"])))
        return
    if a and a["status"] == "pending":
        await message.reply_text(ACCESS_PENDING)
    elif a and a["status"] == "approved":
        await message.reply_text(ACCESS_EXPIRED, reply_markup=request_access_keyboard())
    else:
        await message.reply_text(ACCESS_REQUIRED, reply_markup=request_access_keyboard())


@Client.on_message(filters.command("myaccess") & filters.private)
async def myaccess_cmd(client: Client, message: Message):
    await db.add_user(message.from_user)
    await send_access_status(message, message.from_user.id)


# ================================================================ owner side: buttons
async def _notify(client: Client, uid: int, text: str, markup=None):
    try:
        await client.send_message(uid, text, reply_markup=markup)
        return True
    except Exception as e:
        logger.debug("notify %s failed: %s", uid, e)
        return False


async def _user_label(uid: int) -> str:
    u = await db.get_user(uid)
    if not u:
        return f"`{uid}`"
    name = u.get("first_name") or ""
    un = f" (@{u['username']})" if u.get("username") else ""
    return f"{name}{un} `{uid}`"


@Client.on_callback_query(filters.regex(r"^approve:(\d+):(\d+)$"))
async def approve_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    uid, secs = int(cq.matches[0].group(1)), int(cq.matches[0].group(2))
    expires = await db.grant_access(uid, secs, cq.from_user.id)
    label = _human(secs)
    ok = await _notify(client, uid, ACCESS_GRANTED_USER.format(duration=label, expires=fmt_expiry(expires)),
                       main_reply_keyboard(False))
    await cq.answer(f"✅ Approved for {label}")
    try:
        await cq.message.edit_text(
            f"✅ **Approved** {await _user_label(uid)}\n⏱ {label} • expires {fmt_expiry(expires)}\n"
            f"👮 by {cq.from_user.mention}" + ("" if ok else "\n⚠️ User could not be notified (blocked bot?)"),
            reply_markup=manage_user_keyboard(uid),
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^extend:(\d+):(\d+)$"))
async def extend_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    uid, secs = int(cq.matches[0].group(1)), int(cq.matches[0].group(2))
    expires = await db.extend_access(uid, secs, cq.from_user.id)
    label = _human(secs)
    await _notify(client, uid, ACCESS_EXTENDED_USER.format(duration=label, expires=fmt_expiry(expires)))
    await cq.answer(f"➕ Added {label}")
    try:
        await cq.message.edit_text(
            f"➕ **Extended** {await _user_label(uid)} by {label}\n📅 New expiry: {fmt_expiry(expires)}",
            reply_markup=manage_user_keyboard(uid),
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^reject:(\d+)$"))
async def reject_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    uid = int(cq.matches[0].group(1))
    await db.reject_access(uid)
    await _notify(client, uid, ACCESS_REJECTED_USER)
    await cq.answer("❌ Rejected")
    try:
        await cq.message.edit_text(f"❌ **Rejected** {await _user_label(uid)}\n👮 by {cq.from_user.mention}",
                                   reply_markup=approve_keyboard(uid))
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^revoke:(\d+)$"))
async def revoke_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    uid = int(cq.matches[0].group(1))
    await db.revoke_access(uid)
    await _notify(client, uid, ACCESS_REVOKED_USER, request_access_keyboard())
    await cq.answer("🔒 Revoked")
    try:
        await cq.message.edit_text(f"🔒 **Revoked** {await _user_label(uid)}", reply_markup=approve_keyboard(uid))
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^banuser:(\d+)$"))
async def banuser_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    uid = int(cq.matches[0].group(1))
    await db.set_ban(uid, True)
    await db.revoke_access(uid)
    await _notify(client, uid, BANNED)
    await cq.answer("🚫 Banned")
    try:
        await cq.message.edit_text(f"🚫 **Banned** {await _user_label(uid)}\nUse `/unban {uid}` to undo.")
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^manage:(\d+)$"))
async def manage_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    uid = int(cq.matches[0].group(1))
    a = await db.get_access(uid)
    left = await db.access_remaining(uid)
    text = (f"👤 {await _user_label(uid)}\n"
            f"Status: {'✅ approved' if left is not None else (a['status'] if a else 'none')}\n"
            f"⏱ Left: {fmt_left(left)}\n📅 Expires: {fmt_expiry(a['expires_at']) if a else '—'}")
    try:
        await cq.message.edit_text(text, reply_markup=manage_user_keyboard(uid))
    except Exception:
        pass
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^showreq:(\d+)$"))
async def showreq_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    uid = int(cq.matches[0].group(1))
    a = await db.get_access(uid) or {}
    text = (f"🔔 **Access request**\n👤 {await _user_label(uid)}\n"
            f"🕐 {time.strftime('%d %b %Y, %H:%M UTC', time.gmtime(a.get('requested_at') or time.time()))}\n"
            + (f"📝 _{a['request_note']}_\n" if a.get("request_note") else "")
            + "\nHow long should this user get access?")
    try:
        await cq.message.edit_text(text, reply_markup=approve_keyboard(uid))
    except Exception:
        pass
    await cq.answer()


# ================================================================ owner side: commands
def _parse_target(message: Message):
    if len(message.command) >= 2 and message.command[1].lstrip("-").isdigit():
        return int(message.command[1]), message.command[2:]
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id, message.command[1:]
    return None, []


@Client.on_message(filters.command("approve") & admin_filter)
async def approve_cmd(client: Client, message: Message):
    """/approve <user_id> [duration]  e.g. /approve 123456 10h  (default: permanent)"""
    uid, rest = _parse_target(message)
    if not uid:
        await message.reply_text("Usage: `/approve <user_id> [duration]`\nExamples: `/approve 123 2h`, "
                                 "`/approve 123 10h`, `/approve 123 7d`, `/approve 123` (permanent)")
        return
    secs = 0
    if rest:
        secs = _parse_admin_duration(rest[0])
        if secs is None:
            await message.reply_text("❌ Could not parse duration. Use e.g. `1h`, `2h30m`, `10h`, `3d`, `permanent`.")
            return
    expires = await db.grant_access(uid, secs, message.from_user.id)
    label = _human(secs)
    ok = await _notify(client, uid, ACCESS_GRANTED_USER.format(duration=label, expires=fmt_expiry(expires)),
                       main_reply_keyboard(False))
    await message.reply_text(f"✅ Approved {await _user_label(uid)} for **{label}**\n📅 Expires: {fmt_expiry(expires)}"
                             + ("" if ok else "\n⚠️ User could not be notified."),
                             reply_markup=manage_user_keyboard(uid))


@Client.on_message(filters.command("extend") & admin_filter)
async def extend_cmd(client: Client, message: Message):
    uid, rest = _parse_target(message)
    if not uid or not rest:
        await message.reply_text("Usage: `/extend <user_id> <duration>` e.g. `/extend 123 5h`")
        return
    secs = _parse_admin_duration(rest[0])
    if not secs:
        await message.reply_text("❌ Invalid duration.")
        return
    expires = await db.extend_access(uid, secs, message.from_user.id)
    await _notify(client, uid, ACCESS_EXTENDED_USER.format(duration=_human(secs), expires=fmt_expiry(expires)))
    await message.reply_text(f"➕ Extended {await _user_label(uid)} by {_human(secs)}\n📅 {fmt_expiry(expires)}",
                             reply_markup=manage_user_keyboard(uid))


@Client.on_message(filters.command(["reject", "revoke"]) & admin_filter)
async def reject_revoke_cmd(client: Client, message: Message):
    uid, _ = _parse_target(message)
    if not uid:
        await message.reply_text(f"Usage: `/{message.command[0]} <user_id>`")
        return
    if message.command[0] == "reject":
        await db.reject_access(uid)
        await _notify(client, uid, ACCESS_REJECTED_USER)
        await message.reply_text(f"❌ Rejected {await _user_label(uid)}")
    else:
        await db.revoke_access(uid)
        await _notify(client, uid, ACCESS_REVOKED_USER, request_access_keyboard())
        await message.reply_text(f"🔒 Revoked {await _user_label(uid)}")


@Client.on_message(filters.command("pending") & admin_filter)
async def pending_cmd(client: Client, message: Message):
    rows = await db.pending_requests()
    if not rows:
        await message.reply_text("✅ No pending requests.")
        return
    await message.reply_text(f"⏳ **{len(rows)} pending request(s)** — sending each one with buttons:")
    for r in rows[:15]:
        name = r.get("first_name") or str(r["user_id"])
        un = f" (@{r['username']})" if r.get("username") else ""
        text = (f"🔔 **Access request**\n👤 {name}{un}\n🆔 `{r['user_id']}`\n"
                f"🕐 {time.strftime('%d %b %H:%M UTC', time.gmtime(r['requested_at'] or 0))}\n"
                + (f"📝 _{r['request_note']}_\n" if r.get("request_note") else ""))
        await message.reply_text(text, reply_markup=approve_keyboard(r["user_id"]))
        await asyncio.sleep(0.2)


@Client.on_message(filters.command("approved") & admin_filter)
async def approved_cmd(client: Client, message: Message):
    rows = await db.approved_users()
    if not rows:
        await message.reply_text("ℹ️ No approved users right now.")
        return
    lines = [f"✅ **Approved users ({len(rows)})**\n"]
    now = time.time()
    for r in rows:
        name = r.get("first_name") or "?"
        left = "∞" if not r["expires_at"] else format_time(r["expires_at"] - now)
        lines.append(f"• {name} `{r['user_id']}` — {left} left")
    lines.append("\nUse `/access <id>` to manage a user.")
    await message.reply_text("\n".join(lines))


@Client.on_message(filters.command("access") & admin_filter)
async def access_cmd(client: Client, message: Message):
    uid, _ = _parse_target(message)
    if not uid:
        await message.reply_text("Usage: `/access <user_id>`")
        return
    a = await db.get_access(uid)
    left = await db.access_remaining(uid)
    text = (f"👤 {await _user_label(uid)}\n"
            f"Status: {'✅ approved' if left is not None else (a['status'] if a else 'none')}\n"
            f"⏱ Left: {fmt_left(left)}\n📅 Expires: {fmt_expiry(a['expires_at']) if a else '—'}")
    await message.reply_text(text, reply_markup=manage_user_keyboard(uid) if left is not None
                             else approve_keyboard(uid))


def _parse_admin_duration(text: str):
    t = text.strip().lower()
    if t in ("0", "perm", "permanent", "forever", "inf", "unlimited"):
        return 0
    import re
    m = re.fullmatch(r"(\d+(?:\.\d+)?)d(?:ays?)?", t)
    if m:
        return int(float(m.group(1)) * 86400)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)w(?:eeks?)?", t)
    if m:
        return int(float(m.group(1)) * 7 * 86400)
    v = parse_duration_text(t)
    return v if v else None


# ================================================================ expiry watcher
async def expiry_watcher(client: Client):
    """Every minute: tell users whose access just expired, and ping the owner."""
    while True:
        await asyncio.sleep(60)
        try:
            for uid in await db.newly_expired():
                await _notify(client, uid, ACCESS_EXPIRED_USER, request_access_keyboard())
                if Config.OWNER_ID:
                    await _notify(client, Config.OWNER_ID,
                                  f"⌛ Access expired for {await _user_label(uid)}",
                                  manage_user_keyboard(uid))
        except Exception as e:
            logger.warning("expiry watcher: %s", e)
