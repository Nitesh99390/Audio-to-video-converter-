"""
Conversion pipeline: validate → queue → (merge audio) → render → thumbnail → upload → log → cleanup.
Supports cancellation via /cancel, ❌ button or inline Cancel.
"""
import asyncio
import logging
import os
import time
import uuid

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db
from core.engine import RenderPlan, build_command, render, merge_audios, RenderError
from core.helpers import gate, gate_cb, is_admin, send_files_panel
from core.keyboards import (
    cancel_keyboard, after_video_keyboard,
)
from core.state import state
from core.strings import NO_FILES, BUSY, DAILY_LIMIT
from core.utils import (
    ffprobe, make_thumbnail, cleanup, humanbytes, format_duration, format_time,
    progress_bar_str, Throttle, progress_callback, safe_filename, disk_free,
)

logger = logging.getLogger(__name__)


# ================================================================ entry points
@Client.on_message(filters.command("convert") & filters.private)
async def convert_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    await start_conversion(client, message, message.from_user.id)


@Client.on_callback_query(filters.regex(r"^job:(start|cancel|redo)$"))
async def job_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    action = cq.matches[0].group(1)
    uid = cq.from_user.id
    if action == "start":
        await cq.answer("🚀 Starting...")
        await start_conversion(client, cq.message, uid, from_cq=True)
    elif action == "cancel":
        if state.cancel(uid):
            await cq.answer("🛑 Cancelling...", show_alert=False)
        else:
            await cq.answer("Koi job nahi chal raha.", show_alert=True)
    elif action == "redo":
        session = state.get(uid)
        if session.ready:
            await cq.answer()
            await send_files_panel(cq, uid)
        else:
            await cq.answer("Files already delete ho gayi. Naye files bhejo.", show_alert=True)


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client: Client, message: Message):
    uid = message.from_user.id
    session = state.get(uid) if state.exists(uid) else None
    if session and session.awaiting:
        session.awaiting = None
        await message.reply_text("✅ Input cancel.")
        return
    if state.cancel(uid):
        await message.reply_text("🛑 Job cancel ho raha hai...")
    else:
        await message.reply_text("ℹ️ Koi job nahi chal raha.")


@Client.on_message(filters.command(["clear", "files"]) & filters.private)
async def clear_or_files_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    uid = message.from_user.id
    if message.command[0] == "clear":
        from plugins.media import clear_session
        clear_session(uid)
        await message.reply_text("🗑 Saari files clear ho gayi.")
    else:
        await send_files_panel(message, uid)


@Client.on_callback_query(filters.regex(r"^files:(clear_photos|clear_audio|clear_video|clear_all)$"))
async def files_cb(client: Client, cq: CallbackQuery):
    uid = cq.from_user.id
    action = cq.matches[0].group(1)
    session = state.get(uid)
    if action == "clear_photos":
        cleanup(*session.photos)
        session.photos.clear()
    elif action == "clear_audio":
        cleanup(*session.audios)
        session.audios.clear()
        session.audio_info = {}
    elif action == "clear_video":
        cleanup(session.bg_video)
        session.bg_video = None
    else:
        from plugins.media import clear_session
        clear_session(uid)
        await cq.answer("🗑 Cleared")
        try:
            await cq.message.edit_text("🗑 Sab clear. Naya **Photo + Audio** bhejo.")
        except Exception:
            pass
        return
    await cq.answer("Removed")
    await send_files_panel(cq, uid, edit=True)


# ================================================================ pipeline
async def start_conversion(client: Client, message: Message, uid: int, from_cq: bool = False):
    session = state.get(uid)
    if not session.ready:
        await message.reply_text(NO_FILES)
        return
    if state.is_processing(uid):
        await message.reply_text(BUSY)
        return
    # daily limit
    if not is_admin(uid) and not await db.is_premium(uid):
        if await db.today_usage(uid) >= Config.DAILY_LIMIT_FREE:
            await message.reply_text(DAILY_LIMIT.format(limit=Config.DAILY_LIMIT_FREE))
            return
    if disk_free(Config.DOWNLOAD_DIR) < 300 * 1024 * 1024:
        await message.reply_text("⚠️ Server storage low hai. Thodi der baad try karo.")
        return

    settings = await db.get_settings(uid)
    state.reset_cancel(uid)

    # queue notice
    waiting = state.semaphore.locked()
    status = await message.reply_text(
        "⏳ **Queued...** Aapki job line me hai, thoda wait karo." if waiting else "🚀 **Starting render...**",
        reply_markup=cancel_keyboard(),
    )

    async with state.semaphore:
        if state.was_cancelled(uid):
            await status.edit_text("🛑 Cancelled before start.")
            return
        await _run_job(client, uid, session, settings, status, message)


async def _run_job(client: Client, uid: int, session, settings: dict, status: Message, origin: Message):
    task_id = uuid.uuid4().hex[:8]
    out_dir = Config.DOWNLOAD_DIR
    output = os.path.join(out_dir, f"video_{uid}_{task_id}.mp4")
    thumb = None
    merged = None
    t0 = time.time()
    # placeholder registered so is_processing() is True during merge/probe
    state.register_process(uid, _Dummy())

    try:
        # ---- audio (merge if multiple)
        audio = session.audios[0]
        if len(session.audios) > 1:
            await status.edit_text(f"🎵 Merging {len(session.audios)} audio files...", reply_markup=cancel_keyboard())
            merged = os.path.join(out_dir, f"merged_{uid}_{task_id}.m4a")
            audio = await merge_audios(session.audios, merged)
        info = await ffprobe(audio)
        duration = info["duration"]
        if duration <= 0:
            raise RenderError("Audio duration detect nahi hui.")

        # ---- visual
        images = list(session.photos)
        bg_video = session.bg_video
        src_w = src_h = 0
        if images:
            pi = await ffprobe(images[0])
            src_w, src_h = pi["width"], pi["height"]
        elif bg_video:
            vi = await ffprobe(bg_video)
            src_w, src_h = vi["width"], vi["height"]

        plan = RenderPlan(settings, src_w, src_h)
        mode = "bgvideo" if bg_video else ("slideshow" if len(images) > 1 else "image")
        cmd = build_command(plan, images, audio, output, duration, info["audio_codec"], bg_video=bg_video)

        header = (
            f"🎬 **Rendering {mode}** → {plan.width}x{plan.height} @ {plan.fps}fps ({plan.codec.upper()})\n"
            f"🎵 {format_duration(duration)}"
            + (f" • 🌊 {settings['visualizer']}" if settings["visualizer"] != "none" else "")
        )
        await status.edit_text(header + "\n\n⏳ Starting FFmpeg...", reply_markup=cancel_keyboard())

        async def on_progress(pct, out_time, speed):
            elapsed = time.time() - t0
            eta = (duration - out_time) / speed if speed > 0 else 0
            text = (
                f"{header}\n\n"
                f"`[{progress_bar_str(pct)}]` **{pct:.1f}%**\n"
                f"⏱ {format_duration(out_time)} / {format_duration(duration)}\n"
                f"⚡ Speed: {speed:.2f}x • Elapsed: {format_time(elapsed)}\n"
                f"🕐 ETA: {format_time(eta)}"
            )
            try:
                await status.edit_text(text, reply_markup=cancel_keyboard())
            except Exception:
                pass

        await render(cmd, duration, on_progress, on_process=lambda p: state.register_process(uid, p))

        if state.was_cancelled(uid):
            raise RenderError("cancelled")
        if not os.path.exists(output) or os.path.getsize(output) < 1000:
            raise RenderError("Output file empty.")

        render_time = time.time() - t0
        size = os.path.getsize(output)
        out_info = await ffprobe(output)

        # ---- thumbnail
        thumb_mode = settings.get("thumbnail", "auto")
        if thumb_mode != "none":
            thumb = os.path.join(out_dir, f"thumb_{uid}_{task_id}.jpg")
            src = images[0] if (thumb_mode == "photo" and images) else output
            at = 0 if src != output else min(1.0, duration / 2)
            thumb = await make_thumbnail(src, thumb, at=at)

        # ---- upload
        await status.edit_text(
            f"✅ **Render done** in {format_time(render_time)}\n📦 {humanbytes(size)}\n\n📤 Uploading...",
            reply_markup=None,
        )
        caption = _build_caption(settings, info, out_info, size, render_time, plan)
        throttle = Throttle(4)
        t_up = time.time()
        base_name = safe_filename(info.get("title") or os.path.splitext(os.path.basename(audio))[0], "video")
        file_name = f"{base_name}_{plan.height}p.mp4"

        common = dict(
            chat_id=uid, caption=caption, thumb=thumb,
            progress=progress_callback,
            progress_args=(status, "📤 Uploading video", t_up, throttle, None),
            reply_markup=after_video_keyboard(),
        )
        if settings.get("output_mode") == "document":
            sent = await client.send_document(document=output, file_name=file_name, force_document=True, **common)
        else:
            sent = await client.send_video(
                video=output, duration=int(out_info["duration"]), width=plan.width, height=plan.height,
                supports_streaming=True, has_spoiler=bool(settings.get("spoiler")), file_name=file_name, **common,
            )
        try:
            await status.delete()
        except Exception:
            pass

        await db.record_video(uid, mode, duration, size, render_time, settings)

        # ---- log channel
        if Config.LOG_CHANNEL:
            try:
                u = origin.from_user if origin and origin.from_user else None
                who = f"{u.mention} (`{u.id}`)" if u else f"`{uid}`"
                await sent.copy(Config.LOG_CHANNEL,
                                caption=f"#NEW_VIDEO\n👤 {who}\n🎛 {mode} • {plan.width}x{plan.height} • "
                                        f"{humanbytes(size)} • ⏱ {format_time(render_time)}")
            except Exception as e:
                logger.warning("log channel: %s", e)

    except RenderError as e:
        if "cancel" in str(e).lower() or state.was_cancelled(uid):
            await _safe_edit(status, "🛑 **Job cancelled.** Files abhi bhi saved hain — dobara Convert kar sakte ho.")
        else:
            logger.error("Render error uid=%s: %s", uid, e)
            await _safe_edit(status, f"❌ **Render failed**\n\n`{str(e)[-700:]}`\n\n"
                                     "💡 Tip: Settings me audio mode `aac192` ya fit `pad` try karo.")
    except Exception as e:
        logger.exception("Job error uid=%s", uid)
        await _safe_edit(status, f"❌ Unexpected error: `{type(e).__name__}: {str(e)[:300]}`")
    finally:
        state.unregister_process(uid)
        state.reset_cancel(uid)
        cleanup(output, thumb, merged, output + ".title.txt", output + ".wm.txt")
        # keep source files so user can "redo" with different settings (cleared on /clear or new upload)
        session.touch()


class _Dummy:
    """Placeholder process object before FFmpeg actually spawns."""
    returncode = None

    def kill(self):
        pass


async def _safe_edit(msg: Message, text: str):
    try:
        await msg.edit_text(text, reply_markup=None)
    except Exception:
        try:
            await msg.reply_text(text)
        except Exception:
            pass


def _build_caption(settings, info, out_info, size, render_time, plan) -> str:
    custom = settings.get("custom_caption")
    if custom:
        try:
            return custom.format(
                title=info.get("title") or "", artist=info.get("artist") or "",
                duration=format_duration(out_info["duration"]), size=humanbytes(size),
                resolution=f"{plan.width}x{plan.height}", bot_name=Config.BOT_NAME,
            )[:1024]
        except Exception:
            return custom[:1024]
    title = info.get("title")
    artist = info.get("artist")
    head = f"🎵 **{title}**" + (f" — {artist}" if artist else "") + "\n" if title else ""
    return (
        f"{head}"
        f"🎬 {plan.width}x{plan.height} • {plan.fps}fps • {plan.codec.upper()} • {settings['quality']}\n"
        f"⏱ {format_duration(out_info['duration'])} • 📦 {humanbytes(size)} • ⚡ rendered in {format_time(render_time)}\n"
        f"{Config.DEFAULT_CAPTION.format(bot_name=Config.BOT_NAME)}"
    )[:1024]
