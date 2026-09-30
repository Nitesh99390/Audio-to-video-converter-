"""
All keyboards: persistent Reply Keyboard (bottom buttons) + Inline Keyboards (menus).
Callback data format:  "<menu>:<action>:<value>"
"""
from typing import Dict, Any, List

from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

from core.config import Config

# ================================================================
#  PERSISTENT REPLY KEYBOARD  (bottom "keyboard buttons")
# ================================================================
BTN_CONVERT = "🎬 Convert Now"
BTN_SETTINGS = "⚙️ Settings"
BTN_PRESETS = "🎛 Presets"
BTN_STATUS = "📂 My Files"
BTN_CANCEL = "❌ Cancel"
BTN_CLEAR = "🗑 Clear Files"
BTN_HELP = "❓ Help"
BTN_STATS = "📊 My Stats"
BTN_ABOUT = "ℹ️ About"
BTN_QUICK = "⚡ Quick Modes"

REPLY_BUTTONS = {
    BTN_CONVERT, BTN_SETTINGS, BTN_PRESETS, BTN_STATUS, BTN_CANCEL,
    BTN_CLEAR, BTN_HELP, BTN_STATS, BTN_ABOUT, BTN_QUICK,
}


def main_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_CONVERT), KeyboardButton(BTN_QUICK)],
        [KeyboardButton(BTN_SETTINGS), KeyboardButton(BTN_PRESETS)],
        [KeyboardButton(BTN_STATUS), KeyboardButton(BTN_CLEAR)],
        [KeyboardButton(BTN_STATS), KeyboardButton(BTN_HELP), KeyboardButton(BTN_ABOUT)],
    ]
    if is_admin:
        rows.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True,
                               placeholder="Photo + Audio bhejo, phir Convert dabao 🚀")


def processing_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True)


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ================================================================
#  INLINE KEYBOARD HELPERS
# ================================================================
def _mark(label: str, active: bool) -> str:
    return f"✅ {label}" if active else label


def _grid(buttons: List[InlineKeyboardButton], cols: int) -> List[List[InlineKeyboardButton]]:
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def _back(target: str = "settings", label: str = "🔙 Back") -> List[InlineKeyboardButton]:
    return [InlineKeyboardButton(label, callback_data=f"nav:{target}")]


# ---------------------------------------------------------------- start
def start_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📖 How to use", callback_data="nav:help"),
         InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings")],
        [InlineKeyboardButton("⚡ Quick Modes", callback_data="nav:quick"),
         InlineKeyboardButton("🎛 Presets", callback_data="nav:presets")],
    ]
    links = []
    if Config.UPDATES_LINK:
        links.append(InlineKeyboardButton("📢 Updates", url=Config.UPDATES_LINK))
    if Config.SUPPORT_LINK:
        links.append(InlineKeyboardButton("🛠 Support", url=Config.SUPPORT_LINK))
    if links:
        rows.append(links)
    rows.append([InlineKeyboardButton("➕ Add me to a group", url="https://t.me/share/url?url=Try%20this%20bot")])
    return InlineKeyboardMarkup(rows)


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Image + Audio", callback_data="help:basic"),
         InlineKeyboardButton("🎞 Slideshow", callback_data="help:slideshow")],
        [InlineKeyboardButton("🎥 Video BG", callback_data="help:bgvideo"),
         InlineKeyboardButton("🎵 Visualizer", callback_data="help:visualizer")],
        [InlineKeyboardButton("💧 Watermark & Title", callback_data="help:watermark"),
         InlineKeyboardButton("📋 Commands", callback_data="help:commands")],
        _back("start", "🏠 Home"),
    ])


def force_sub_keyboard(link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=link)],
        [InlineKeyboardButton("🔄 I have joined", callback_data="nav:checksub")],
    ])


# ------------------------------------------------------------ file status
def files_keyboard(session, ready: bool) -> InlineKeyboardMarkup:
    rows = []
    if ready:
        rows.append([InlineKeyboardButton("🚀 CONVERT NOW", callback_data="job:start")])
    rows.append([
        InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings"),
        InlineKeyboardButton("⚡ Quick Modes", callback_data="nav:quick"),
    ])
    row = []
    if session.photos:
        row.append(InlineKeyboardButton(f"🗑 Photos ({len(session.photos)})", callback_data="files:clear_photos"))
    if session.audios:
        row.append(InlineKeyboardButton(f"🗑 Audio ({len(session.audios)})", callback_data="files:clear_audio"))
    if session.bg_video:
        row.append(InlineKeyboardButton("🗑 Video", callback_data="files:clear_video"))
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🗑 Clear everything", callback_data="files:clear_all")])
    return InlineKeyboardMarkup(rows)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="job:cancel")]])


def after_video_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Same files, new settings", callback_data="job:redo"),
         InlineKeyboardButton("🆕 New video", callback_data="files:clear_all")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings"),
         InlineKeyboardButton("⭐ Rate / Share", url="https://t.me/share/url?url=Awesome%20Audio%20to%20Video%20bot!")],
    ])


# ------------------------------------------------------------- quick modes
QUICK_MODES: Dict[str, Dict[str, Any]] = {
    "youtube": {"label": "▶️ YouTube 1080p", "resolution": "1080p", "aspect": "16:9", "fit": "blur",
                "visualizer": "none", "quality": "high", "fps": 30},
    "shorts": {"label": "📱 Shorts / Reels", "resolution": "1080p", "aspect": "9:16", "fit": "blur",
               "visualizer": "waves", "quality": "high", "fps": 30},
    "insta": {"label": "📸 Instagram Square", "resolution": "1080p", "aspect": "1:1", "fit": "crop",
              "visualizer": "bars", "quality": "high", "fps": 30},
    "status": {"label": "💬 WhatsApp Status", "resolution": "720p", "aspect": "9:16", "fit": "blur",
               "visualizer": "none", "quality": "medium", "fps": 30},
    "lyric": {"label": "🎤 Music Video", "resolution": "1080p", "aspect": "16:9", "fit": "blur",
              "visualizer": "spectrum", "quality": "ultra", "fps": 30, "ken_burns": True, "fade": True},
    "podcast": {"label": "🎙 Podcast", "resolution": "720p", "aspect": "16:9", "fit": "pad",
                "visualizer": "waves", "quality": "medium", "fps": 24},
    "fast": {"label": "⚡ Fastest / Smallest", "resolution": "480p", "aspect": "16:9", "fit": "stretch",
             "visualizer": "none", "quality": "low", "fps": 24, "ken_burns": False, "fade": False},
    "4k": {"label": "💎 4K Ultra", "resolution": "2160p", "aspect": "16:9", "fit": "blur",
           "visualizer": "none", "quality": "ultra", "fps": 30},
}


def quick_modes_keyboard() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(v["label"], callback_data=f"quick:{k}") for k, v in QUICK_MODES.items()]
    rows = _grid(btns, 2)
    rows.append(_back("start", "🏠 Home") + [InlineKeyboardButton("⚙️ Custom", callback_data="nav:settings")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------- settings
def settings_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    vis = s["visualizer"]
    wm = "ON" if s.get("watermark_text") else "OFF"
    title = "ON" if s.get("title_text") else "OFF"
    rows = [
        [InlineKeyboardButton(f"📐 Resolution: {s['resolution']}", callback_data="menu:resolution"),
         InlineKeyboardButton(f"🖼 Aspect: {s['aspect']}", callback_data="menu:aspect")],
        [InlineKeyboardButton(f"🧩 Fit: {s['fit']}", callback_data="menu:fit"),
         InlineKeyboardButton(f"🎞 FPS: {s['fps']}", callback_data="menu:fps")],
        [InlineKeyboardButton(f"💎 Quality: {s['quality']}", callback_data="menu:quality"),
         InlineKeyboardButton(f"🎚 Codec: {s['codec'].upper()}", callback_data="menu:codec")],
        [InlineKeyboardButton(f"🎵 Audio: {s['audio_mode']}", callback_data="menu:audio_mode"),
         InlineKeyboardButton(f"🌊 Visualizer: {vis}", callback_data="menu:visualizer")],
        [InlineKeyboardButton(f"🎨 Vis Color: {s['vis_color']}", callback_data="menu:vis_color"),
         InlineKeyboardButton(f"📍 Vis Pos: {s['vis_position']}", callback_data="menu:vis_position")],
        [InlineKeyboardButton(f"🎥 Ken Burns: {'ON' if s['ken_burns'] else 'OFF'}", callback_data="toggle:ken_burns"),
         InlineKeyboardButton(f"🌓 Fade: {'ON' if s['fade'] else 'OFF'}", callback_data="toggle:fade")],
        [InlineKeyboardButton(f"💧 Watermark: {wm}", callback_data="menu:watermark"),
         InlineKeyboardButton(f"🔤 Title: {title}", callback_data="menu:title")],
        [InlineKeyboardButton(f"🎞 Slideshow: {s['slideshow_duration']}s/{s['slideshow_transition']}",
                              callback_data="menu:slideshow"),
         InlineKeyboardButton(f"📤 Output: {s['output_mode']}", callback_data="menu:output")],
        [InlineKeyboardButton(f"🙈 Spoiler: {'ON' if s['spoiler'] else 'OFF'}", callback_data="toggle:spoiler"),
         InlineKeyboardButton(f"🖼 Thumb: {s['thumbnail']}", callback_data="menu:thumbnail")],
        [InlineKeyboardButton("📝 Caption", callback_data="menu:caption"),
         InlineKeyboardButton(f"🌐 Lang: {s['language'].upper()}", callback_data="toggle:language")],
        [InlineKeyboardButton("💾 Save as Preset", callback_data="preset:save"),
         InlineKeyboardButton("♻️ Reset all", callback_data="set:reset:confirm")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:start"),
         InlineKeyboardButton("📂 My Files", callback_data="nav:files")],
    ]
    return InlineKeyboardMarkup(rows)


OPTIONS: Dict[str, List] = {
    "resolution": ["480p", "720p", "1080p", "1440p", "2160p", "original"],
    "aspect": ["16:9", "9:16", "1:1", "4:3", "4:5", "21:9"],
    "fit": ["blur", "crop", "pad", "stretch"],
    "fps": [24, 25, 30, 60],
    "quality": ["low", "medium", "high", "ultra"],
    "codec": ["h264", "h265"],
    "audio_mode": ["copy", "aac128", "aac192", "aac320", "mp3"],
    "visualizer": ["none", "waves", "bars", "spectrum", "vectorscope", "cqt", "circle"],
    "vis_color": ["white", "cyan", "magenta", "yellow", "red", "green", "orange", "rainbow"],
    "vis_position": ["bottom", "center", "top"],
    "watermark_position": ["top_left", "top_right", "center", "bottom_left", "bottom_right"],
    "title_position": ["top", "center", "bottom"],
    "output_mode": ["video", "document"],
    "thumbnail": ["auto", "photo", "none"],
    "slideshow_duration": [2, 3, 5, 8, 10, 15],
    "slideshow_transition": ["fade", "none"],
}

OPTION_TITLES = {
    "resolution": "📐 Output Resolution",
    "aspect": "🖼 Aspect Ratio",
    "fit": "🧩 Image Fit Mode\n\n• blur – blurred background fill\n• crop – fill & crop edges\n• pad – black bars\n• stretch – distort to fit",
    "fps": "🎞 Frame Rate",
    "quality": "💎 Encoding Quality (higher = bigger file)",
    "codec": "🎚 Video Codec\n\n• H264 – best compatibility\n• H265 – ~40% smaller, slower",
    "audio_mode": "🎵 Audio Mode\n\n• copy – no re-encode (fastest)\n• aacXXX – re-encode to AAC bitrate\n• mp3 – re-encode to MP3",
    "visualizer": "🌊 Audio Visualizer Overlay",
    "vis_color": "🎨 Visualizer Color",
    "vis_position": "📍 Visualizer Position",
    "watermark_position": "📍 Watermark Position",
    "title_position": "📍 Title Position",
    "output_mode": "📤 Send As",
    "thumbnail": "🖼 Thumbnail Source",
    "slideshow_duration": "⏱ Seconds per image (slideshow)",
    "slideshow_transition": "✨ Slideshow transition",
}


def option_keyboard(key: str, current: Any, back: str = "settings") -> InlineKeyboardMarkup:
    opts = OPTIONS[key]
    btns = [InlineKeyboardButton(_mark(str(o), str(o) == str(current)), callback_data=f"set:{key}:{o}")
            for o in opts]
    cols = 3 if len(opts) > 4 else 2
    rows = _grid(btns, cols)
    rows.append(_back(back))
    return InlineKeyboardMarkup(rows)


def watermark_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set watermark text", callback_data="input:watermark_text")],
        [InlineKeyboardButton(f"📍 Position: {s['watermark_position']}", callback_data="menu:watermark_position")],
        [InlineKeyboardButton("🗑 Remove watermark", callback_data="set:watermark_text:")],
        _back(),
    ])


def title_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set title text", callback_data="input:title_text")],
        [InlineKeyboardButton(f"📍 Position: {s['title_position']}", callback_data="menu:title_position")],
        [InlineKeyboardButton("🗑 Remove title", callback_data="set:title_text:")],
        _back(),
    ])


def caption_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set custom caption", callback_data="input:custom_caption")],
        [InlineKeyboardButton("♻️ Use default caption", callback_data="set:custom_caption:")],
        _back(),
    ])


def slideshow_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱ Duration: {s['slideshow_duration']}s", callback_data="menu:slideshow_duration"),
         InlineKeyboardButton(f"✨ Transition: {s['slideshow_transition']}", callback_data="menu:slideshow_transition")],
        _back(),
    ])


def input_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel input", callback_data="input:cancel")]])


def confirm_keyboard(yes_cb: str, no_cb: str = "nav:settings") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=yes_cb),
        InlineKeyboardButton("❌ No", callback_data=no_cb),
    ]])


# -------------------------------------------------------------- presets
def presets_keyboard(names: List[str]) -> InlineKeyboardMarkup:
    rows = []
    for n in names:
        rows.append([
            InlineKeyboardButton(f"🎛 {n}", callback_data=f"preset:load:{n}"),
            InlineKeyboardButton("🗑", callback_data=f"preset:del:{n}"),
        ])
    rows.append([InlineKeyboardButton("💾 Save current settings", callback_data="preset:save")])
    rows.append(_back("settings") + [InlineKeyboardButton("🏠 Home", callback_data="nav:start")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------- admin
def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin:stats"),
         InlineKeyboardButton("🖥 Server", callback_data="admin:server")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast_help"),
         InlineKeyboardButton("👥 Users", callback_data="admin:users")],
        [InlineKeyboardButton("🔨 Ban/Unban help", callback_data="admin:ban_help"),
         InlineKeyboardButton("🧹 Cleanup downloads", callback_data="admin:cleanup")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:start")],
    ])
