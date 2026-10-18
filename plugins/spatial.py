"""
3D / 8D audio: pick the effect right after an audio upload, then either
  • 🎵 receive the processed audio file directly (no photo needed), or
  • 🎬 make the normal photo + audio video — the effect is applied to the audio first.
"""
import logging
import os
import time
import uuid

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from core.config import Config
from core.database import db
from core.engine import render, RenderError
from core.helpers import gate_cb, send_files_panel
from core.keyboards import spatial_keyboard, cancel_keyboard
from core.spatial import MODES, build_command
from core.state import state
from core import storage
from core.strings import NEED_MORE, STORAGE_FULL
from core.utils import ffprobe, cleanup, humanbytes, format_duration, format_time, progress_bar_str, \
    Throttle, progress_callback, safe_filename

logger = logging.getLogger(__name__)


def prompt_text(session) -> str:
    cur = session.spatial
    head = "🎧 **3D / 8D audio?**\n"
    if cur:
        head += f"Selected: **{cur.upper()}** — {MODES[cur]['desc']}.\n\n"
        head += ("🎵 **Send audio** → processed track only, ready in seconds.\n"
                 "🎬 **Make video** → photo + audio video with the effect"
                 + ("" if session.has_visual else " (send a photo first)") + ".")
    else:
        head += "Pick **8D** (sound circles around you) or **3D** (wide surround) — or keep **Normal**."
    return head


@Client.on_callback_query(filters.regex(r"^spatial:(off|8d|3d|video|audio:8d|audio:3d)$"))
async def spatial_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    uid = cq.from_user.id
    action = cq.matches[0].group(1)
    session = state.get(uid)
    if not session.audios:
        await cq.answer("Send an audio file first.", show_alert=True)
        return
    if state.is_processing(uid):
        await cq.answer("⏳ Wait for the running job to finish.", show_alert=True)
        return

    if action in ("off", "8d", "3d"):
        session.spatial = None if action == "off" else action
        session.touch()
        await cq.answer("Normal audio" if action == "off" else f"{action.upper()} selected")
        try:
            await cq.message.edit_text(prompt_text(session), reply_markup=spatial_keyboard(session.spatial, session.has_visual))
        except Exception:
            await send_files_panel(cq, uid, edit=True)
        return

    if action == "video":
        if not session.spatial:
            await cq.answer("Pick 8D or 3D first.", show_alert=True)
            return
        await cq.answer()
        if session.ready:
            from plugins.convert import start_conversion
            await start_conversion(client, cq.message, uid, from_cq=True)
        else:
            await cq.message.reply_text(NEED_MORE["visual"] + f"\n🎧 The **{session.spatial.upper()}** effect will be applied.")
        return

    # audio only
    mode = action.split(":")[1]
    session.spatial = mode
    await cq.answer("🎧 Processing...")
    try:
        await cq.message.edit_reply_markup(None)
    except Exception:
        pass
    async with state.semaphore:
        await send_spatial_audio(client, uid, mode, cq.message)


async def send_spatial_audio(client: Client, uid: int, mode: str, origin):
    session = state.get(uid)
    src = session.audios[0]
    info = session.audio_info or await ffprobe(src)
    dur = float(info.get("duration") or 0)
    need = int(192_000 * max(dur, 1) / 8) + 10 * 1024 * 1024
    if not storage.ensure_space(need, keep_user=uid):
        await origin.reply_text(STORAGE_FULL)
        return

    task_id = uuid.uuid4().hex[:8]
    out = os.path.join(Config.DOWNLOAD_DIR, f"spatial_{uid}_{task_id}.mp3")
    state.register_job_files(uid, out, *session.all_files())
    status = await origin.reply_text(f"🎧 **{mode.upper()} audio** • {format_duration(dur)}\n\n⏳ Processing...",
                                     reply_markup=cancel_keyboard())
    state.reset_cancel(uid)
    t0 = time.time()

    async def on_progress(pct, out_time, speed, total=None):
        try:
            await status.edit_text(
                f"🎧 **{mode.upper()} audio** • {format_duration(dur)}\n\n"
                f"`[{progress_bar_str(pct)}]` **{pct:.1f}%** • ⚡ {speed:.0f}x • ⏱ {format_time(time.time() - t0)}",
                reply_markup=cancel_keyboard())
        except Exception:
            pass

    try:
        await render(build_command(src, out, mode, kbps=192, ext="mp3"), dur, on_progress,
                     on_process=lambda p: state.register_process(uid, p), timeout=2 * 3600)
        if state.was_cancelled(uid):
            raise RenderError("cancelled")
        if not os.path.exists(out) or os.path.getsize(out) < 1000:
            raise RenderError("Output file is empty.")
        size = os.path.getsize(out)
        base = safe_filename(info.get("title") or os.path.splitext(os.path.basename(src))[0], "audio")
        await status.edit_text(f"✅ Done in {format_time(time.time() - t0)} • {humanbytes(size)}\n📤 Uploading...",
                               reply_markup=None)
        throttle = Throttle(4)
        await client.send_audio(
            chat_id=uid, audio=out, duration=int(dur), title=f"{base} ({mode.upper()})",
            performer=info.get("artist") or None, file_name=f"{base}_{mode.upper()}.mp3",
            caption=f"🎧 **{mode.upper()} audio** — {MODES[mode]['desc']} • use headphones 🎧\n"
                    f"⏱ {format_duration(dur)} • 📦 {humanbytes(size)} • MP3 192k",
            progress=progress_callback, progress_args=(status, "📤 Uploading audio", time.time(), throttle, None),
        )
        try:
            await status.delete()
        except Exception:
            pass
        try:
            await db.record_video(uid, f"audio_{mode}", dur, size, time.time() - t0, {})
        except Exception:
            pass
        if session.has_visual:
            await origin.reply_text(f"Want the **{mode.upper()} video** too? Tap **Convert now** 👇")
            await send_files_panel(origin, uid)
    except RenderError as e:
        if "cancel" in str(e).lower() or state.was_cancelled(uid):
            await status.edit_text("🛑 Cancelled.")
        else:
            logger.error("spatial audio uid=%s: %s", uid, e)
            await status.edit_text(f"❌ Processing failed\n\n`{str(e)[-500:]}`")
    except Exception as e:
        logger.exception("spatial audio uid=%s", uid)
        await status.edit_text(f"❌ Unexpected error: `{type(e).__name__}: {str(e)[:300]}`")
    finally:
        state.unregister_process(uid)
        state.reset_cancel(uid)
        cleanup(out)
        state.release_job_files(uid)
        session.touch()
