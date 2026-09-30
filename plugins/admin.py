"""Admin panel: stats, server info, broadcast, ban/unban, premium, cleanup."""
import asyncio
import glob
import logging
import os
import platform
import shutil
import time

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, PeerIdInvalid
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db
from core.helpers import is_admin, uptime_str
from core.keyboards import admin_keyboard, approved_list_keyboard, pending_list_keyboard
from core.state import state
from core.utils import humanbytes, format_time, cleanup

logger = logging.getLogger(__name__)

admin_filter = filters.create(lambda _, __, m: bool(m.from_user and is_admin(m.from_user.id)))


# ================================================================ /admin
@Client.on_message(filters.command("admin") & admin_filter)
async def admin_cmd(client: Client, message: Message):
    c = await db.access_counts()
    await message.reply_text("👑 **Admin panel**", reply_markup=admin_keyboard(c["pending"], c["approved"]))


async def stats_text() -> str:
    g = await db.global_stats()
    c = await db.access_counts()
    return (
        "📊 **Global stats**\n\n"
        f"👥 Users: **{g.get('total_users', 0)}** (active 24h: {g.get('active_24h', 0)})\n"
        f"🔑 Approved: {c['approved']} • ⏳ Pending: {c['pending']} • 🚫 Banned: {g.get('banned_users', 0)}\n"
        f"🎬 Videos: **{g.get('total_videos', 0)}**\n"
        f"📦 Output: {humanbytes(g.get('total_bytes', 0))}\n"
        f"⏱ Render time: {format_time(g.get('total_render_time', 0))}\n"
        f"🧵 Active jobs: {state.active_tasks}/{Config.MAX_CONCURRENT_TASKS}\n"
        f"⏳ Uptime: `{uptime_str()}`"
    )


def _mem_info() -> str:
    try:
        with open("/proc/meminfo") as f:
            d = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in f if ":" in l}
        total, avail = d.get("MemTotal", 0), d.get("MemAvailable", 0)
        return f"{humanbytes(total - avail)} / {humanbytes(total)}"
    except Exception:
        return "n/a"


def server_text() -> str:
    du = shutil.disk_usage(".")
    try:
        load = os.getloadavg()
        load_s = f"{load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}"
    except (AttributeError, OSError):
        load_s = "n/a"
    dl_files = glob.glob(os.path.join(Config.DOWNLOAD_DIR, "*"))
    dl_size = sum(os.path.getsize(f) for f in dl_files if os.path.isfile(f))
    return (
        "🖥 **Server**\n\n"
        f"🐧 {platform.system()} {platform.release()} • Python {platform.python_version()}\n"
        f"🧠 CPU cores: {os.cpu_count()} • Load: {load_s}\n"
        f"💾 RAM: {_mem_info()}\n"
        f"📀 Disk: {humanbytes(du.used)} / {humanbytes(du.total)} (free {humanbytes(du.free)})\n"
        f"📂 Downloads dir: {len(dl_files)} files, {humanbytes(dl_size)}\n"
        f"🧵 FFmpeg threads: {Config.FFMPEG_THREADS or 'auto'}"
    )


def cleanup_downloads(max_age: float = 3600):
    """Remove files in downloads dir not referenced by any session and older than max_age."""
    active = set()
    for uid in list(state._sessions.keys()):
        active.update(state.get(uid).all_files())
    n = freed = 0
    now = time.time()
    for f in glob.glob(os.path.join(Config.DOWNLOAD_DIR, "*")):
        if f in active or not os.path.isfile(f):
            continue
        if now - os.path.getmtime(f) > max_age:
            freed += os.path.getsize(f)
            cleanup(f)
            n += 1
    return n, freed


@Client.on_callback_query(filters.regex(r"^admin:(\w+)$"))
async def admin_cb(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    action = cq.matches[0].group(1)
    text = "👑 **Admin panel**"
    if action == "pending":
        rows = await db.pending_requests()
        text = (f"⏳ **Pending requests: {len(rows)}**\n\nTap a user to see approval buttons."
                if rows else "✅ No pending requests.")
        try:
            await cq.message.edit_text(text, reply_markup=pending_list_keyboard(rows))
        except Exception:
            pass
        await cq.answer()
        return
    if action == "approved":
        rows = await db.approved_users()
        now = time.time()
        lines = [f"✅ **Approved users: {len(rows)}**\n"]
        for r in rows[:30]:
            left = "∞" if not r["expires_at"] else format_time(r["expires_at"] - now)
            lines.append(f"• {(r.get('first_name') or '?')[:20]} `{r['user_id']}` — {left}")
        lines.append("\nTap a user to extend / revoke.")
        try:
            await cq.message.edit_text("\n".join(lines), reply_markup=approved_list_keyboard(rows))
        except Exception:
            pass
        await cq.answer()
        return
    if action == "stats":
        text = await stats_text()
    elif action == "server":
        text = server_text()
    elif action == "broadcast_help":
        text = ("📢 **Broadcast**\n\nReply to any message with `/broadcast` — it will be copied to all users.\n"
                "`/broadcast -pin` also pins it.")
    elif action == "users":
        ids = await db.all_user_ids()
        text = f"👥 **Users:** {len(ids)}\n\nLast 20 IDs:\n" + "\n".join(f"`{i}`" for i in ids[-20:])
    elif action == "ban_help":
        text = ("🔨 **Admin commands**\n\n"
                "**Access:**\n"
                "`/approve <id> [1h|2h|5h|10h|3d|permanent]`\n"
                "`/extend <id> <duration>` — add time\n"
                "`/reject <id>` • `/revoke <id>`\n"
                "`/pending` — list requests with buttons\n"
                "`/approved` — list active users\n"
                "`/access <id>` — manage one user\n\n"
                "**Moderation:**\n"
                "`/ban <id> [reason]` • `/unban <id>`\n"
                "`/premium <id>` (toggle)\n`/users` — stats • `/server` — server info\n"
                "`/broadcast` (reply to a message)")
    elif action == "cleanup":
        n, freed = cleanup_downloads(max_age=0)
        text = f"🧹 Cleaned **{n}** stale files, freed {humanbytes(freed)}."
    c = await db.access_counts()
    try:
        await cq.message.edit_text(text, reply_markup=admin_keyboard(c["pending"], c["approved"]))
    except Exception:
        pass
    await cq.answer()


# ================================================================ commands
@Client.on_message(filters.command("users") & admin_filter)
async def users_cmd(client: Client, message: Message):
    await message.reply_text(await stats_text())


@Client.on_message(filters.command("server") & admin_filter)
async def server_cmd(client: Client, message: Message):
    await message.reply_text(server_text())


def _target_id(message: Message):
    if len(message.command) >= 2 and message.command[1].lstrip("-").isdigit():
        return int(message.command[1])
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


@Client.on_message(filters.command("ban") & admin_filter)
async def ban_cmd(client: Client, message: Message):
    uid = _target_id(message)
    if not uid:
        await message.reply_text("Usage: `/ban <user_id> [reason]`")
        return
    reason = " ".join(message.command[2:]) or "No reason"
    await db.set_ban(uid, True)
    await message.reply_text(f"🚫 User `{uid}` banned.\nReason: {reason}")
    try:
        await client.send_message(uid, f"🚫 You have been banned from this bot.\nReason: {reason}")
    except Exception:
        pass


@Client.on_message(filters.command("unban") & admin_filter)
async def unban_cmd(client: Client, message: Message):
    uid = _target_id(message)
    if not uid:
        await message.reply_text("Usage: `/unban <user_id>`")
        return
    await db.set_ban(uid, False)
    await message.reply_text(f"✅ User `{uid}` unbanned.")


@Client.on_message(filters.command("premium") & admin_filter)
async def premium_cmd(client: Client, message: Message):
    uid = _target_id(message)
    if not uid:
        await message.reply_text("Usage: `/premium <user_id>` (toggles premium)")
        return
    new = not await db.is_premium(uid)
    await db.set_premium(uid, new)
    await message.reply_text(f"⭐ User `{uid}` premium: **{'ON' if new else 'OFF'}**")
    try:
        await client.send_message(
            uid, "⭐ You now have **Premium**! Unlimited daily conversions." if new
            else "ℹ️ Your premium has been removed.")
    except Exception:
        pass


@Client.on_message(filters.command("broadcast") & admin_filter)
async def broadcast_cmd(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("↩️ Reply to a message with `/broadcast`.")
        return
    pin = "-pin" in message.text
    ids = await db.all_user_ids()
    status = await message.reply_text(f"📢 Broadcasting to {len(ids)} users...")
    ok = fail = 0
    t0 = time.time()
    for i, uid in enumerate(ids, 1):
        try:
            sent = await message.reply_to_message.copy(uid)
            if pin:
                try:
                    await sent.pin(disable_notification=True)
                except Exception:
                    pass
            ok += 1
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                await message.reply_to_message.copy(uid)
                ok += 1
            except Exception:
                fail += 1
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            fail += 1
        except Exception as e:
            logger.debug("broadcast %s: %s", uid, e)
            fail += 1
        if i % 25 == 0:
            try:
                await status.edit_text(f"📢 {i}/{len(ids)} • ✅ {ok} • ❌ {fail}")
            except Exception:
                pass
        await asyncio.sleep(0.05)
    await status.edit_text(
        f"✅ **Broadcast done** in {format_time(time.time() - t0)}\n\n"
        f"👥 Total: {len(ids)}\n✅ Sent: {ok}\n❌ Failed: {fail}"
    )
