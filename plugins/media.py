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
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db
from core.helpers import gate, send_files_panel, get_settings
from core.keyboards import settings_keyboard, advanced_keyboard, video_role_keyboard
from core.state import state
from core import storage
from core.strings import NEED_MORE, STORAGE_FULL
from core.utils import Throttle, progress_callback, ffprobe, extract_cover_art, cleanup, format_duration

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


async def _room_for(message: Message, uid: int, size: int) -> bool:
    """Make sure the disk can take this upload; tell the user if not."""
    if storage.ensure_space((size or 0) + 20 * 1024 * 1024, keep_user=uid):
        return True
    await message.reply_text(STORAGE_FULL)
    return False


# ================================================================ PHOTO
@Client.on_message(filters.private & filters.photo)
async def photo_handler(client: Client, message: Message):
    if not await gate(client, message):
        return
    uid = message.from_user.id
    if state.is_processing(uid):
        await message.reply_text("⏳ A video is being rendered right now. Send new files after it finishes.")
        return
    session = state.get(uid)
    if session.bg_video:
        cleanup(session.bg_video)
        session.bg_video = None
    if len(session.photos) >= Config.MAX_SLIDESHOW_IMAGES:
        await message.reply_text(f"⚠️ Max {Config.MAX_SLIDESHOW_IMAGES} photos allowed.")
        return
    if not await _room_for(message, uid, message.photo.file_size or 0):
        return

    dest = _path(uid, "photo", ".jpg")
    try:
        path = await _download(message, dest, "Photo")
        session.photos.append(path)
        session.touch()
    except Exception as e:
        logger.error("photo download: %s", e)
        await message.reply_text("❌ Photo download failed.")
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
            await message.reply_text(f"🎞 **{n} photos** added → Slideshow mode ✅")
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
        await message.reply_text("⏳ A video is being rendered right now. Send new files after it finishes.")
        return
    session = state.get(uid)

    ext = ".mp3"
    fname = getattr(media, "file_name", None)
    if fname and os.path.splitext(fname)[1]:
        ext = os.path.splitext(fname)[1].lower()
    elif message.voice:
        ext = ".ogg"
    dest = _path(uid, "audio", ext)
    if not await _room_for(message, uid, media.file_size or 0):
        return

    big = (media.file_size or 0) > 8 * 1024 * 1024
    status = await message.reply_text("📥 Downloading audio...") if big else None
    try:
        path = await _download(message, dest, "📥 Downloading audio", status)
    except Exception as e:
        logger.error("audio download: %s", e)
        if status:
            await status.edit_text("❌ Audio download failed.")
        return

    info = await ffprobe(path)
    if not info["has_audio"]:
        cleanup(path)
        msg = "❌ No audio stream found in this file."
        await (status.edit_text(msg) if status else message.reply_text(msg))
        return
    if info["duration"] > Config.MAX_AUDIO_DURATION_SEC:
        cleanup(path)
        msg = f"⚠️ Audio is too long. Max {format_duration(Config.MAX_AUDIO_DURATION_SEC)}."
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
                await status.edit_text("🎨 Found embedded album art — it will be used as the picture.")
            else:
                await message.reply_text("🎨 Found embedded album art — I will use it as the picture. "
                                         "Send another photo if you prefer.")
    if status:
        try:
            await status.delete()
        except Exception:
            pass
    await _after_upload(message, uid, kind="audio")


# ================================================================ VIDEO (intro / outro / background)
ROLE_LABEL = {"intro": "🎬 Intro", "outro": "🏁 Outro", "bg": "🎥 Background loop"}


def _auto_role(session) -> str:
    """First video = intro, second = outro, then background loop. Long clips -> background."""
    if not session.intro:
        return "intro"
    if not session.outro:
        return "outro"
    return "bg"


def _set_role(session, role: str, path: str, info: dict):
    """Put `path` into the given slot (dropping whatever was there)."""
    if role == "intro":
        if session.intro and session.intro != path:
            cleanup(session.intro)
        session.intro, session.intro_info = path, info
    elif role == "outro":
        if session.outro and session.outro != path:
            cleanup(session.outro)
        session.outro, session.outro_info = path, info
    else:
        # a background video replaces photos
        cleanup(*session.photos)
        session.photos.clear()
        if session.bg_video and session.bg_video != path:
            cleanup(session.bg_video)
        session.bg_video = path
    session.touch()


def _take_role(session, role: str):
    """Detach the file in `role` slot and return (path, info) without deleting it."""
    if role == "intro":
        p, i = session.intro, session.intro_info
        session.intro, session.intro_info = None, {}
    elif role == "outro":
        p, i = session.outro, session.outro_info
        session.outro, session.outro_info = None, {}
    else:
        p, i = session.bg_video, {}
        session.bg_video = None
    return p, i


def _role_text(role: str, info: dict) -> str:
    dur = format_duration(info.get("duration", 0))
    res = f"{info.get('width', 0)}x{info.get('height', 0)}"
    if role == "intro":
        return f"🎬 **Intro set** ✅ ({res}, {dur})\nIt will play **before** the main video."
    if role == "outro":
        return f"🏁 **Outro set** ✅ ({res}, {dur})\nIt will play **after** the main video."
    return (f"🎥 **Background video set** ✅ ({res}, {dur})\n"
            "It will be looped for the whole video length; your audio replaces its sound.")


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
        await message.reply_text("⏳ A video is being rendered right now.")
        return
    session = state.get(uid)
    if not await _room_for(message, uid, media.file_size or 0):
        return
    status = await message.reply_text("📥 Downloading video...")
    dest = _path(uid, "clip", ".mp4")
    try:
        path = await _download(message, dest, "📥 Downloading video", status)
    except Exception as e:
        logger.error("video download: %s", e)
        await status.edit_text("❌ Video download failed.")
        return
    info = await ffprobe(path)
    if not info["has_video"]:
        cleanup(path)
        await status.edit_text("❌ Not a valid video.")
        return

    role = _auto_role(session)
    long_clip = info["duration"] > Config.INTRO_OUTRO_AUTO_SEC
    if role != "bg" and long_clip and not session.has_visual:
        role = "bg"                       # a long video with no photo yet is almost surely a background loop
    if role != "bg" and info["duration"] > Config.MAX_INTRO_OUTRO_SEC:
        cleanup(path)
        await status.edit_text(
            f"⚠️ Intro/outro clips can be at most **{format_duration(Config.MAX_INTRO_OUTRO_SEC)}** long "
            f"(this one is {format_duration(info['duration'])}).\n"
            "Send a shorter clip, or send it after a photo is set if you want it as a background loop."
        )
        return
    _set_role(session, role, path, info)
    await status.edit_text(_role_text(role, info) + "\n\nWrong slot? Change it here 👇",
                           reply_markup=video_role_keyboard(role))
    await _after_upload(message, uid, kind="visual" if role == "bg" else "clip")


@Client.on_callback_query(filters.regex(r"^vrole:(intro|outro|bg):(intro|outro|bg|remove)$"))
async def video_role_cb(client: Client, cq: CallbackQuery):
    uid = cq.from_user.id
    cur, new = cq.matches[0].group(1), cq.matches[0].group(2)
    session = state.get(uid)
    if state.is_processing(uid):
        await cq.answer("⏳ Wait for the running job to finish.", show_alert=True)
        return
    path, info = _take_role(session, cur)
    if not path or not os.path.exists(path):
        await cq.answer("This clip is no longer available.", show_alert=True)
        try:
            await cq.message.edit_reply_markup(None)
        except Exception:
            pass
        return
    if new == "remove":
        cleanup(path)
        session.touch()
        await cq.answer("Removed")
        try:
            await cq.message.edit_text(f"🗑 {ROLE_LABEL[cur]} removed.")
        except Exception:
            pass
        return
    if new == cur:
        _set_role(session, cur, path, info)
        await cq.answer("Already set")
        return
    if not info:
        info = await ffprobe(path)
    if new != "bg" and info.get("duration", 0) > Config.MAX_INTRO_OUTRO_SEC:
        _set_role(session, cur, path, info)
        await cq.answer(f"Too long for an intro/outro (max {format_duration(Config.MAX_INTRO_OUTRO_SEC)}).",
                        show_alert=True)
        return
    # swap: if the target slot is occupied, the old clip moves to the freed slot
    other, other_info = _take_role(session, new)
    _set_role(session, new, path, info)
    if other and os.path.exists(other) and cur != "bg" and new != "bg":
        _set_role(session, cur, other, other_info or await ffprobe(other))
    elif other:
        cleanup(other)
    await cq.answer(f"Now used as {ROLE_LABEL[new]}")
    try:
        await cq.message.edit_text(_role_text(new, info) + "\n\nWrong slot? Change it here 👇",
                                   reply_markup=video_role_keyboard(new))
    except Exception:
        pass
    await send_files_panel(cq, uid)


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
        if not await _room_for(message, uid, doc.file_size or 0):
            return
        dest = _path(uid, "photo", ext or ".jpg")
        try:
            path = await _download(message, dest, "Photo")
        except Exception:
            await message.reply_text("❌ Image download failed.")
            return
        info = await ffprobe(path)
        if not info["has_video"]:
            cleanup(path)
            await message.reply_text("❌ Not a valid image.")
            return
        if session.bg_video:
            cleanup(session.bg_video)
            session.bg_video = None
        session.photos.append(path)
        session.touch()
        await message.reply_text("🖼 HD image (document) added ✅ — full quality preserved.")
        await _after_upload(message, uid, kind="visual")
    elif mime.startswith("video/") or ext in VIDEO_EXT:
        # treat as background video
        message.video = doc  # duck-type for handler
        await video_handler(client, message)
    else:
        await message.reply_text(
            "⚠️ This file type is not supported.\n\nSupported: 🎵 audio (mp3/m4a/wav/flac/ogg...), "
            "🖼 image (jpg/png/webp), 🎥 video (mp4/mkv/mov/webm)."
        )


# ================================================================ TEXT INPUT (settings that need typing)
@Client.on_message(filters.private & filters.text & ~filters.command(
    ["start", "help", "settings", "quick", "presets", "files", "convert", "cancel", "clear", "stats",
     "history", "about", "ping", "admin", "broadcast", "ban", "unban", "premium", "users", "server", "preset",
     "duration", "request", "myaccess", "approve", "reject", "revoke", "extend", "pending", "approved", "access",
     "storage", "cleanup", "youtube", "yt", "yt_token", "yt_logout", "yt_history"]
), group=1)
async def text_input_handler(client: Client, message: Message):
    uid = message.from_user.id
    session = state.get(uid) if state.exists(uid) else None
    if not session or not session.awaiting:
        return
    key = session.awaiting
    value = message.text.strip()
    if len(value) > 120 and key != "custom_caption":
        await message.reply_text("⚠️ Text is too long (max 120 chars).")
        return
    if len(value) > 900:
        await message.reply_text("⚠️ Caption max 900 chars.")
        return
    session.awaiting = None

    if key == "preset_name":
        name = value[:30]
        settings = await db.get_settings(uid)
        await db.save_preset(uid, name, settings)
        await message.reply_text(f"💾 Preset **{name}** saved. Load it from Settings → 🎛 Presets.")
        return

    if key == "target_duration":
        from core.helpers import parse_duration_text
        from core.keyboards import duration_label
        secs = parse_duration_text(value)
        if secs is None or secs < 0:
            session.awaiting = key
            await message.reply_text("❌ Could not parse that. Examples: `10h`, `2h30m`, `90m`, `1:30:00`, `0`")
            return
        secs = min(secs, Config.MAX_OUTPUT_DURATION_SEC)
        await db.update_setting(uid, key, int(secs))
        settings = await get_settings(uid)
        await message.reply_text(f"✅ Final length: **{duration_label(int(secs))}**",
                                 reply_markup=settings_keyboard(settings, uid))
        if session.awaiting_msg_id:
            try:
                await client.delete_messages(uid, session.awaiting_msg_id)
            except Exception:
                pass
            session.awaiting_msg_id = None
        return

    await db.update_setting(uid, key, value)
    settings = await get_settings(uid)
    labels = {"watermark_text": "💧 Watermark", "title_text": "🔤 Title", "custom_caption": "📝 Caption"}
    await message.reply_text(f"✅ {labels.get(key, key)}: `{value}`",
                             reply_markup=advanced_keyboard(settings))
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
        return
    if kind == "clip":
        if not session.has_visual and not session.has_audio:
            await message.reply_text(NEED_MORE["both"])
        elif not session.has_visual:
            await message.reply_text(NEED_MORE["visual"])
        else:
            await message.reply_text(NEED_MORE["audio"])
        return
    need = "audio" if kind == "visual" else "visual"
    await message.reply_text(NEED_MORE[need])
