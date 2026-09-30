"""
Conversion pipeline: validate → queue → (merge audio) → render (lite | pro) → thumbnail → upload → log → cleanup.
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
from core.lite_engine import render_lite
from core.helpers import gate, gate_cb, is_admin, send_files_panel
from core.keyboards import cancel_keyboard, after_video_keyboard
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
            await cq.answer("No job is running.", show_alert=True)
    elif action == "redo":
        session = state.get(uid)
        if session.ready:
            await cq.answer()
            await send_files_panel(cq, uid)
        else:
            await cq.answer("Files were already deleted. Please send new files.", show_alert=True)


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client: Client, message: Message):
    uid = message.from_user.id
    session = state.get(uid) if state.exists(uid) else None
    if session and session.awaiting:
        session.awaiting = None
        await message.reply_text("✅ Input cancelled.")
        return
    if state.cancel(uid):
        await message.reply_text("🛑 Cancelling the job...")
    else:
        await message.reply_text("ℹ️ No job is running.")


@Client.on_message(filters.command(["clear", "files"]) & filters.private)
async def clear_or_files_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    uid = message.from_user.id
    if message.command[0] == "clear":
        from plugins.media import clear_session
        clear_session(uid)
        await message.reply_text("🗑 All files cleared.")
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
            await cq.message.edit_text("🗑 Everything cleared. Send a new **Photo + Audio**.")
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
    if Config.DAILY_LIMIT_FREE and not is_admin(uid) and not await db.is_premium(uid):
        if await db.today_usage(uid) >= Config.DAILY_LIMIT_FREE:
            await message.reply_text(DAILY_LIMIT.format(limit=Config.DAILY_LIMIT_FREE))
            return
    if disk_free(Config.DOWNLOAD_DIR) < 500 * 1024 * 1024:
        await message.reply_text("⚠️ Server storage is low. Please try again later.")
        return

    settings = await db.get_settings(uid)
    state.reset_cancel(uid)

    waiting = state.semaphore.locked()
    status = await message.reply_text(
        "⏳ **Queued...** your job is in line, please wait." if waiting else "🚀 **Starting...**",
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
    temps = []
    t0 = time.time()
    state.register_process(uid, _Dummy())
    engine = settings.get("engine", "lite")

    try:
        # ---- audio (merge if multiple)
        audio = session.audios[0]
        if len(session.audios) > 1:
            await status.edit_text(f"🎵 Merging {len(session.audios)} audio files...", reply_markup=cancel_keyboard())
            merged = os.path.join(out_dir, f"merged_{uid}_{task_id}.m4a")
            audio = await merge_audios(session.audios, merged)
        info = await ffprobe(audio)
        audio_dur = info["duration"]
        if audio_dur <= 0:
            raise RenderError("Could not detect the audio duration.")

        # ---- target duration
        target = int(settings.get("target_duration") or 0) or audio_dur
        target = float(min(target, Config.MAX_OUTPUT_DURATION_SEC))
        looped = target > audio_dur + 0.5

        # ---- visual
        images = list(session.photos)
        bg_video = session.bg_video
        src_w = src_h = 0
        bg_info = None
        if images:
            pi = await ffprobe(images[0])
            src_w, src_h = pi["width"], pi["height"]
        elif bg_video:
            bg_info = await ffprobe(bg_video)
            src_w, src_h = bg_info["width"], bg_info["height"]

        mode = "bgvideo" if bg_video else ("slideshow" if len(images) > 1 else "image")
        header_base = (
            f"{'⚡' if engine == 'lite' else '🎬'} **{engine.upper()} render** • {mode}\n"
            f"🎵 audio {format_duration(audio_dur)} → 🎞 video **{format_duration(target)}**"
            + (" (audio looped)" if looped else "")
        )
        stage_text = {"text": "⏳ Preparing..."}

        async def on_stage(text):
            stage_text["text"] = text
            try:
                await status.edit_text(f"{header_base}\n\n{text}", reply_markup=cancel_keyboard())
            except Exception:
                pass

        async def on_progress(pct, out_time, speed, total=None):
            total = total or target
            elapsed = time.time() - t0
            eta = (total - out_time) / speed if speed > 0 else 0
            text = (
                f"{header_base}\n\n{stage_text['text']}\n\n"
                f"`[{progress_bar_str(pct)}]` **{pct:.1f}%**\n"
                f"⏱ {format_duration(out_time)} / {format_duration(total)}\n"
                f"⚡ Speed: {speed:.0f}x • Elapsed: {format_time(elapsed)}\n"
                f"🕐 ETA: {format_time(eta)}"
            )
            try:
                await status.edit_text(text, reply_markup=cancel_keyboard())
            except Exception:
                pass

        if engine == "lite":
            await on_stage("⏳ Starting lite engine...")
            res = await render_lite(
                settings, images, audio, info, output, target,
                on_stage=on_stage, on_progress=on_progress,
                on_process=lambda p: state.register_process(uid, p),
                bg_video=bg_video, bg_info=bg_info, src_w=src_w, src_h=src_h,
            )
            temps = res.get("temps", [])
            out_w, out_h, out_fps = res["width"], res["height"], res["fps"]
            extra_caption = f"⚡ lite • {res['audio_label']}" + (" • looped" if looped else "")
        else:
            plan = RenderPlan(settings, src_w, src_h)
            if looped:
                # pro engine needs a real audio file of the target length
                await on_stage("🔁 Looping audio to target length...")
                loop_audio = os.path.join(out_dir, f"loop_{uid}_{task_id}.m4a")
                temps.append(loop_audio)
                code = await _loop_audio(audio, loop_audio, target)
                if code:
                    raise RenderError("Audio loop failed.")
                audio = loop_audio
                info = await ffprobe(audio)
            cmd = build_command(plan, images, audio, output, target, info["audio_codec"], bg_video=bg_video)
            await on_stage(f"🎬 Rendering {plan.width}x{plan.height} @ {plan.fps}fps ({plan.codec.upper()})..."
                           + ("\n⚠️ Pro engine re-encodes every frame — long audio takes a long time." if target > 1800 else ""))
            await render(cmd, target, on_progress, on_process=lambda p: state.register_process(uid, p),
                         timeout=12 * 3600)
            out_w, out_h, out_fps = plan.width, plan.height, plan.fps
            extra_caption = f"🎬 pro • {plan.codec.upper()} • {settings['quality']}"

        if state.was_cancelled(uid):
            raise RenderError("cancelled")
        if not os.path.exists(output) or os.path.getsize(output) < 1000:
            raise RenderError("Output file is empty.")

        render_time = time.time() - t0
        size = os.path.getsize(output)
        if size > Config.MAX_OUTPUT_SIZE_MB * 1024 * 1024:
            raise RenderError(f"Output is {humanbytes(size)} — above the {Config.MAX_OUTPUT_SIZE_MB} MB Telegram limit. "
                              f"Lower the audio bitrate (Settings → Audio → aac64/aac96) or shorten the duration.")
        out_info = await ffprobe(output)

        # ---- thumbnail
        thumb_mode = settings.get("thumbnail", "photo")
        if thumb_mode != "none":
            thumb = os.path.join(out_dir, f"thumb_{uid}_{task_id}.jpg")
            src = images[0] if (thumb_mode == "photo" and images) else output
            at = 0 if src != output else min(1.0, target / 2)
            thumb = await make_thumbnail(src, thumb, at=at)

        # ---- upload
        await status.edit_text(
            f"✅ **Render done** in {format_time(render_time)}\n📦 {humanbytes(size)} • {format_duration(out_info['duration'])}\n\n"
            f"📤 Uploading to Telegram...",
            reply_markup=None,
        )
        caption = _build_caption(settings, info, out_info, size, render_time, out_w, out_h, out_fps, extra_caption)
        throttle = Throttle(4)
        t_up = time.time()
        base_name = safe_filename(info.get("title") or os.path.splitext(os.path.basename(session.audios[0]))[0], "video")
        file_name = f"{base_name}_{format_duration(target).replace(':', '-')}_{out_h}p.mp4"

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
                video=output, duration=int(out_info["duration"]), width=out_w, height=out_h,
                supports_streaming=True, has_spoiler=bool(settings.get("spoiler")), file_name=file_name, **common,
            )
        try:
            await status.delete()
        except Exception:
            pass

        await db.record_video(uid, mode, target, size, render_time, settings)

        if Config.LOG_CHANNEL:
            try:
                u = origin.from_user if origin and origin.from_user else None
                who = f"{u.mention} (`{u.id}`)" if u else f"`{uid}`"
                await sent.copy(Config.LOG_CHANNEL,
                                caption=f"#NEW_VIDEO\n👤 {who}\n🎛 {engine}/{mode} • {out_w}x{out_h} • "
                                        f"{format_duration(target)} • {humanbytes(size)} • ⏱ {format_time(render_time)}")
            except Exception as e:
                logger.warning("log channel: %s", e)

    except RenderError as e:
        if "cancel" in str(e).lower() or state.was_cancelled(uid):
            await _safe_edit(status, "🛑 **Job cancelled.** Your files are still here — you can convert again.")
        else:
            logger.error("Render error uid=%s: %s", uid, e)
            await _safe_edit(status, f"❌ **Render failed**\n\n`{str(e)[-700:]}`\n\n"
                                     "💡 Tip: try Settings → Audio → `aac128` or Fit → `pad`.")
    except Exception as e:
        logger.exception("Job error uid=%s", uid)
        await _safe_edit(status, f"❌ Unexpected error: `{type(e).__name__}: {str(e)[:300]}`")
    finally:
        state.unregister_process(uid)
        state.reset_cancel(uid)
        cleanup(output, thumb, merged, output + ".title.txt", output + ".wm.txt", *temps)
        session.touch()


async def _loop_audio(src: str, dst: str, target: float) -> int:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", src,
        "-t", f"{target:.3f}", "-vn", "-c:a", "aac", "-b:a", "128k", dst,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    return await proc.wait()


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


def _build_caption(settings, info, out_info, size, render_time, w, h, fps, extra) -> str:
    custom = settings.get("custom_caption")
    if custom:
        try:
            return custom.format(
                title=info.get("title") or "", artist=info.get("artist") or "",
                duration=format_duration(out_info["duration"]), size=humanbytes(size),
                resolution=f"{w}x{h}", bot_name=Config.BOT_NAME,
            )[:1024]
        except Exception:
            return custom[:1024]
    title = info.get("title")
    artist = info.get("artist")
    head = f"🎵 **{title}**" + (f" — {artist}" if artist else "") + "\n" if title else ""
    return (
        f"{head}"
        f"🎬 {w}x{h} • {fps}fps • {extra}\n"
        f"⏱ {format_duration(out_info['duration'])} • 📦 {humanbytes(size)} • ⚡ ready in {format_time(render_time)}\n"
        f"{Config.DEFAULT_CAPTION.format(bot_name=Config.BOT_NAME)}"
    )[:1024]
