"""
Media intake: photos (single / album), audio, voice, video, documents.
Files are stored in the per-user Session; conversion is triggered by the
user via button/command (or auto if `auto_convert` is desired).
"""
import asyncio
import logging
import os
import time
import uuid

from pyrogram import Client, filters
from pyrogram.types import Message

from core.config import Config
from core.database import db
from core.helpers import gate, send_files_panel
from core.keyboards import cancel_keyboard, input_cancel_keyboard, settings_keyboard
from core.state import state
from core.strings import NEED_MORE
from core.utils import (
    Throttle, progress_callback, ffprobe, extract_cover_art, cleanup,
    humanbytes, format_duration,
)

logger = logging.getLogger(__name__)

IMAGE_MIME = ("image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff")
AUDIO_EXT = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".oga", ".aiff", ".alac", ".amr")
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".gif")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")

# album (media_group) buffering
_album_buffer: dict = {}


def _path(uid: int, kind: str, ext: str) -> str:
    return os.path.join(Config.DOWNLOAD_DIR, f"{kind}_{uid}_{uuid.uuid4().hex[:8]}{ext}")


def clear_session(uid: int):
    old = state.clear(uid)
    cleanup(*old.all_files())


async def _download(message: Message, dest: str, label: str, status=None):
    throttle = Throttle(4)
    start = time.time()
    return await message.download(
        file_name=dest,
        progress=progress_callback if status else None,
        progress_args=(status, label, start, throttle, None) if status else (),
    )


def _size_ok(size: int) -> bool:
    return (size or 0) <= Config.MAX_FILE_SIZE_MB * 1024 * 1024


# ================================================================ PHOTO
@Client.on_message(filters.private & filters.photo)
async def photo_handler(client: Client, message: Message):
    if not await gate(client, message):
        return
    uid = message.from_user.id
    if state.is_processing(uid):
        await message.reply_text("⏳ Abhi ek video ban raha hai. Complete hone ke baad naya bhejo.")
        return
    session = state.get(uid)
    if session.bg_video:
        cleanup(session.bg_video)
        session.bg_video = None
    if len(session.photos) >= Config.MAX_SLIDESHOW_IMAGES:
        await message.reply_text(f"⚠️ Max {Config.MAX_SLIDESHOW_IMAGES} photos allowed.")
        return

    dest = _path(uid, "photo", ".jpg")
    try:
        path = await _download(message, dest, "Photo")
        session.photos.append(path)
        session.touch()
    except Exception as e:
        logger.error("photo download: %s", e)
        await message.reply_text("❌ Photo download fail ho gayi.")
        return

    # album: debounce so we reply once after the last photo arrives
    if message.media_group_id:
        gid = message.media_group_id
        prev = _album_buffer.pop(gid, None)
        if prev:
            prev.cancel()

        async def _delayed():
            await asyncio.sleep(2.0)
            _album_buffer.pop(gid, None)
            n = len(state.get(uid).photos)
            await message.reply_text(f"🎞 **{n} photos** add ho gayi → Slideshow mode ✅")
            await _after_upload(message, uid, kind="visual")

        _album_buffer[gid] = asyncio.create_task(_delayed())
        return

    await _after_upload(message, uid, kind="visual")


# ================================================================ AUDIO
@Client.on_message(filters.private & (filters.audio | filters.voice))
async def audio_handler(client: Client, message: Message):
    if not await gate(client, message):
        return
    media = message.audio or message.voice
    if not _size_ok(media.file_size):
        await message.reply_text(f"⚠️ File too big. Max {Config.MAX_FILE_SIZE_MB} MB.")
        return
    await _ingest_audio(client, message, media)


async def _ingest_audio(client: Client, message: Message, media):
    uid = message.from_user.id
    if state.is_processing(uid):
        await message.reply_text("⏳ Abhi ek video ban raha hai. Complete hone ke baad naya bhejo.")
        return
    session = state.get(uid)

    ext = ".mp3"
    fname = getattr(media, "file_name", None)
    if fname and os.path.splitext(fname)[1]:
        ext = os.path.splitext(fname)[1].lower()
    elif message.voice:
        ext = ".ogg"
    dest = _path(uid, "audio", ext)

    big = (media.file_size or 0) > 8 * 1024 * 1024
    status = await message.reply_text("📥 Audio download ho raha hai...") if big else None
    try:
        path = await _download(message, dest, "📥 Downloading audio", status)
    except Exception as e:
        logger.error("audio download: %s", e)
        if status:
            await status.edit_text("❌ Audio download fail ho gaya.")
        return

    info = await ffprobe(path)
    if not info["has_audio"]:
        cleanup(path)
        msg = "❌ Is file me audio stream nahi mila."
        await (status.edit_text(msg) if status else message.reply_text(msg))
        return
    if info["duration"] > Config.MAX_AUDIO_DURATION_SEC:
        cleanup(path)
        msg = f"⚠️ Audio bahut lamba hai. Max {format_duration(Config.MAX_AUDIO_DURATION_SEC)}."
        await (status.edit_text(msg) if status else message.reply_text(msg))
        return

    session.audios.append(path)
    if len(session.audios) == 1:
        session.audio_info = info
    else:
        session.audio_info["duration"] = session.audio_info.get("duration", 0) + info["duration"]
    session.touch()

    # auto cover art if no photo yet
    if not session.has_visual:
        cover = await extract_cover_art(path, _path(uid, "cover", ".jpg"))
        if cover:
            session.photos.append(cover)
            if status:
                await status.edit_text("🎨 Album art mil gaya — photo ke roop me use hoga.")
            else:
                await message.reply_text("🎨 Audio me embedded album-art mila — photo ke roop me use karunga. "
                                         "Chaaho to dusri photo bhej do.")
    if status:
        try:
            await status.delete()
        except Exception:
            pass
    await _after_upload(message, uid, kind="audio")


# ================================================================ VIDEO (background)
@Client.on_message(filters.private & (filters.video | filters.animation))
async def video_handler(client: Client, message: Message):
    if not await gate(client, message):
        return
    uid = message.from_user.id
    media = message.video or message.animation
    if not _size_ok(media.file_size):
        await message.reply_text(f"⚠️ File too big. Max {Config.MAX_FILE_SIZE_MB} MB.")
        return
    if state.is_processing(uid):
        await message.reply_text("⏳ Abhi ek video ban raha hai.")
        return
    session = state.get(uid)
    status = await message.reply_text("📥 Background video download ho raha hai...")
    dest = _path(uid, "bgvideo", ".mp4")
    try:
        path = await _download(message, dest, "📥 Downloading video", status)
    except Exception as e:
        logger.error("video download: %s", e)
        await status.edit_text("❌ Video download fail ho gaya.")
        return
    info = await ffprobe(path)
    if not info["has_video"]:
        cleanup(path)
        await status.edit_text("❌ Valid video nahi hai.")
        return
    # video replaces photos
    cleanup(*session.photos)
    session.photos.clear()
    if session.bg_video:
        cleanup(session.bg_video)
    session.bg_video = path
    session.touch()
    await status.edit_text(
        f"🎥 Background video set ✅ ({info['width']}x{info['height']}, {format_duration(info['duration'])}). "
        "Yeh audio ki length tak loop hoga."
    )
    await _after_upload(message, uid, kind="visual")


# ================================================================ DOCUMENT (route by type)
@Client.on_message(filters.private & filters.document)
async def document_handler(client: Client, message: Message):
    if not await gate(client, message):
        return
    doc = message.document
    mime = (doc.mime_type or "").lower()
    name = (doc.file_name or "").lower()
    ext = os.path.splitext(name)[1]

    if mime.startswith("audio/") or ext in AUDIO_EXT:
        if not _size_ok(doc.file_size):
            await message.reply_text(f"⚠️ File too big. Max {Config.MAX_FILE_SIZE_MB} MB.")
            return
        await _ingest_audio(client, message, doc)
    elif mime.startswith("image/") or ext in IMAGE_EXT:
        uid = message.from_user.id
        session = state.get(uid)
        if len(session.photos) >= Config.MAX_SLIDESHOW_IMAGES:
            await message.reply_text(f"⚠️ Max {Config.MAX_SLIDESHOW_IMAGES} photos allowed.")
            return
        dest = _path(uid, "photo", ext or ".jpg")
        try:
            path = await _download(message, dest, "Photo")
        except Exception:
            await message.reply_text("❌ Image download fail.")
            return
        info = await ffprobe(path)
        if not info["has_video"]:
            cleanup(path)
            await message.reply_text("❌ Valid image nahi hai.")
            return
        if session.bg_video:
            cleanup(session.bg_video)
            session.bg_video = None
        session.photos.append(path)
        session.touch()
        await message.reply_text("🖼 HD image (document) add ho gayi ✅ — full quality preserve hogi.")
        await _after_upload(message, uid, kind="visual")
    elif mime.startswith("video/") or ext in VIDEO_EXT:
        # treat as background video
        message.video = doc  # duck-type for handler
        await video_handler(client, message)
    else:
        await message.reply_text(
            "⚠️ Yeh file type support nahi hai.\n\nSupported: 🎵 audio (mp3/m4a/wav/flac/ogg...), "
            "🖼 image (jpg/png/webp), 🎥 video (mp4/mkv/mov/webm)."
        )


# ================================================================ TEXT INPUT (settings that need typing)
@Client.on_message(filters.private & filters.text & ~filters.command(
    ["start", "help", "settings", "quick", "presets", "files", "convert", "cancel", "clear", "stats",
     "history", "about", "ping", "admin", "broadcast", "ban", "unban", "premium", "users", "server", "preset"]
), group=1)
async def text_input_handler(client: Client, message: Message):
    uid = message.from_user.id
    session = state.get(uid) if state.exists(uid) else None
    if not session or not session.awaiting:
        return
    key = session.awaiting
    value = message.text.strip()
    if len(value) > 120 and key != "custom_caption":
        await message.reply_text("⚠️ Text bahut lamba hai (max 120 chars).")
        return
    if len(value) > 900:
        await message.reply_text("⚠️ Caption max 900 chars.")
        return
    session.awaiting = None

    if key == "preset_name":
        name = value[:30]
        settings = await db.get_settings(uid)
        await db.save_preset(uid, name, settings)
        await message.reply_text(f"💾 Preset **{name}** save ho gaya! 🎛 Presets se load karo.")
        return

    settings = await db.update_setting(uid, key, value)
    labels = {"watermark_text": "💧 Watermark", "title_text": "🔤 Title", "custom_caption": "📝 Caption"}
    await message.reply_text(f"✅ {labels.get(key, key)} set: `{value}`",
                             reply_markup=settings_keyboard(settings))
    if session.awaiting_msg_id:
        try:
            await client.delete_messages(uid, session.awaiting_msg_id)
        except Exception:
            pass
        session.awaiting_msg_id = None


# ================================================================ helpers
async def _after_upload(message: Message, uid: int, kind: str):
    session = state.get(uid)
    if session.ready:
        await send_files_panel(message, uid)
    else:
        need = "audio" if kind == "visual" else "visual"
        await message.reply_text(NEED_MORE[need])
