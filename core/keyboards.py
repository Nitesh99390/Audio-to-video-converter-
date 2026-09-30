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
BTN_DURATION = "⏱ Duration"
BTN_ACCESS = "🔑 My Access"
BTN_ADMIN = "👑 Admin Panel"

REPLY_BUTTONS = {
    BTN_CONVERT, BTN_SETTINGS, BTN_PRESETS, BTN_STATUS, BTN_CANCEL,
    BTN_CLEAR, BTN_HELP, BTN_STATS, BTN_ABOUT, BTN_QUICK, BTN_DURATION, BTN_ACCESS,
}


def main_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_CONVERT), KeyboardButton(BTN_DURATION)],
        [KeyboardButton(BTN_SETTINGS), KeyboardButton(BTN_QUICK)],
        [KeyboardButton(BTN_STATUS), KeyboardButton(BTN_CLEAR)],
        [KeyboardButton(BTN_ACCESS), KeyboardButton(BTN_STATS), KeyboardButton(BTN_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(BTN_ADMIN), KeyboardButton(BTN_PRESETS)])
    else:
        rows.append([KeyboardButton(BTN_PRESETS), KeyboardButton(BTN_ABOUT)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True,
                               placeholder="Send Photo + Audio, then tap Convert 🚀")


def request_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_ACCESS)], [KeyboardButton(BTN_HELP)]],
                               resize_keyboard=True, is_persistent=True)


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
        [InlineKeyboardButton("⏱ Duration", callback_data="menu:target_duration"),
         InlineKeyboardButton("⚡ Quick Modes", callback_data="nav:quick")],
    ]
    links = []
    if Config.UPDATES_LINK:
        links.append(InlineKeyboardButton("📢 Updates", url=Config.UPDATES_LINK))
    if Config.SUPPORT_LINK:
        links.append(InlineKeyboardButton("🛠 Support", url=Config.SUPPORT_LINK))
    if links:
        rows.append(links)
    return InlineKeyboardMarkup(rows)


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Image + Audio", callback_data="help:basic"),
         InlineKeyboardButton("⚡ Lite engine", callback_data="help:lite")],
        [InlineKeyboardButton("⏱ Duration / Loop", callback_data="help:duration"),
         InlineKeyboardButton("🎞 Slideshow", callback_data="help:slideshow")],
        [InlineKeyboardButton("🎥 Video BG", callback_data="help:bgvideo"),
         InlineKeyboardButton("🌊 Visualizer", callback_data="help:visualizer")],
        [InlineKeyboardButton("💧 Watermark & Title", callback_data="help:watermark"),
         InlineKeyboardButton("📋 Commands", callback_data="help:commands")],
        _back("start", "🏠 Home"),
    ])


def force_sub_keyboard(link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=link)],
        [InlineKeyboardButton("🔄 I have joined", callback_data="nav:checksub")],
    ])


# ------------------------------------------------------------ access / approval
# label -> seconds (0 = permanent)
APPROVE_DURATIONS: Dict[str, int] = {
    "30 min": 30 * 60,
    "1 hour": 3600,
    "2 hours": 2 * 3600,
    "3 hours": 3 * 3600,
    "5 hours": 5 * 3600,
    "10 hours": 10 * 3600,
    "1 day": 86400,
    "3 days": 3 * 86400,
    "7 days": 7 * 86400,
    "30 days": 30 * 86400,
    "♾ Permanent": 0,
}


def request_access_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📨 Request Access", callback_data="access:request")]])


def approve_keyboard(uid: int) -> InlineKeyboardMarkup:
    """Shown to the owner under every access request."""
    btns = [InlineKeyboardButton(f"✅ {label}", callback_data=f"approve:{uid}:{secs}")
            for label, secs in APPROVE_DURATIONS.items()]
    rows = _grid(btns, 3)
    rows.append([InlineKeyboardButton("❌ Reject", callback_data=f"reject:{uid}"),
                 InlineKeyboardButton("🚫 Ban", callback_data=f"banuser:{uid}")])
    return InlineKeyboardMarkup(rows)


def manage_user_keyboard(uid: int) -> InlineKeyboardMarkup:
    """Owner controls for an already approved user."""
    btns = [InlineKeyboardButton(f"➕ {label}", callback_data=f"extend:{uid}:{secs}")
            for label, secs in APPROVE_DURATIONS.items() if secs]
    rows = _grid(btns, 3)
    rows.append([InlineKeyboardButton("♾ Make permanent", callback_data=f"approve:{uid}:0"),
                 InlineKeyboardButton("🔒 Revoke", callback_data=f"revoke:{uid}")])
    rows.append([InlineKeyboardButton("🔙 Approved list", callback_data="admin:approved")])
    return InlineKeyboardMarkup(rows)


def approved_list_keyboard(rows_data: List[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in rows_data[:30]:
        name = (r.get("first_name") or str(r["user_id"]))[:20]
        rows.append([InlineKeyboardButton(f"👤 {name} ({r['user_id']})", callback_data=f"manage:{r['user_id']}")])
    rows.append([InlineKeyboardButton("🔙 Admin", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def pending_list_keyboard(rows_data: List[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in rows_data[:30]:
        name = (r.get("first_name") or str(r["user_id"]))[:20]
        rows.append([InlineKeyboardButton(f"⏳ {name} ({r['user_id']})", callback_data=f"showreq:{r['user_id']}")])
    rows.append([InlineKeyboardButton("🔙 Admin", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------ file status
def files_keyboard(session, ready: bool) -> InlineKeyboardMarkup:
    rows = []
    if ready:
        rows.append([InlineKeyboardButton("🚀 CONVERT NOW", callback_data="job:start")])
    rows.append([
        InlineKeyboardButton("⏱ Duration", callback_data="menu:target_duration"),
        InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings"),
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
        [InlineKeyboardButton("⏱ Duration", callback_data="menu:target_duration"),
         InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings")],
    ])


# ------------------------------------------------------------- quick modes
QUICK_MODES: Dict[str, Dict[str, Any]] = {
    "lite": {"label": "⚡ Lite 720p (fastest)", "engine": "lite", "resolution": "720p", "aspect": "16:9",
             "fit": "blur", "fps": 10, "quality": "medium", "visualizer": "none", "audio_mode": "copy"},
    "lite1080": {"label": "⚡ Lite 1080p", "engine": "lite", "resolution": "1080p", "aspect": "16:9",
                 "fit": "blur", "fps": 10, "quality": "medium", "visualizer": "none", "audio_mode": "copy"},
    "tiny": {"label": "🪶 Tiniest file", "engine": "lite", "resolution": "480p", "aspect": "16:9",
             "fit": "stretch", "fps": 1, "quality": "low", "visualizer": "none", "audio_mode": "aac64"},
    "youtube": {"label": "▶️ YouTube Pro 1080p", "engine": "pro", "resolution": "1080p", "aspect": "16:9",
                "fit": "blur", "visualizer": "none", "quality": "high", "fps": 30},
    "shorts": {"label": "📱 Shorts / Reels", "engine": "pro", "resolution": "1080p", "aspect": "9:16",
               "fit": "blur", "visualizer": "waves", "quality": "high", "fps": 30},
    "lyric": {"label": "🎤 Music Video", "engine": "pro", "resolution": "1080p", "aspect": "16:9",
              "fit": "blur", "visualizer": "spectrum", "quality": "ultra", "fps": 30, "ken_burns": True,
              "fade": True},
    "podcast": {"label": "🎙 Podcast", "engine": "pro", "resolution": "720p", "aspect": "16:9",
                "fit": "pad", "visualizer": "waves", "quality": "medium", "fps": 24},
    "4k": {"label": "💎 4K Ultra", "engine": "pro", "resolution": "2160p", "aspect": "16:9", "fit": "blur",
           "visualizer": "none", "quality": "ultra", "fps": 30},
}


def quick_modes_keyboard() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(v["label"], callback_data=f"quick:{k}") for k, v in QUICK_MODES.items()]
    rows = _grid(btns, 2)
    rows.append(_back("start", "🏠 Home") + [InlineKeyboardButton("⚙️ Custom", callback_data="nav:settings")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------- duration
# label -> seconds ; 0 = same as audio
DURATION_PRESETS: Dict[str, int] = {
    "🎵 Same as audio": 0,
    "30 min": 1800,
    "1 hour": 3600,
    "2 hours": 7200,
    "3 hours": 10800,
    "5 hours": 18000,
    "8 hours": 28800,
    "10 hours": 36000,
    "12 hours": 43200,
}


def duration_label(seconds: int) -> str:
    if not seconds:
        return "same as audio"
    for label, s in DURATION_PRESETS.items():
        if s == seconds:
            return label
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def duration_keyboard(current: int, back: str = "settings") -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(_mark(label, secs == current), callback_data=f"set:target_duration:{secs}")
            for label, secs in DURATION_PRESETS.items()]
    rows = _grid(btns, 3)
    rows.append([InlineKeyboardButton("✏️ Custom (e.g. 4h30m)", callback_data="input:target_duration")])
    rows.append(_back(back))
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------- settings
def settings_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    lite = s.get("engine", "lite") == "lite"
    vis = s["visualizer"]
    wm = "ON" if s.get("watermark_text") else "OFF"
    title = "ON" if s.get("title_text") else "OFF"
    rows = [
        [InlineKeyboardButton(f"🚀 Engine: {'⚡ Lite' if lite else '🎬 Pro'}", callback_data="toggle:engine"),
         InlineKeyboardButton(f"⏱ Duration: {duration_label(int(s.get('target_duration') or 0))}",
                              callback_data="menu:target_duration")],
        [InlineKeyboardButton(f"📐 Resolution: {s['resolution']}", callback_data="menu:resolution"),
         InlineKeyboardButton(f"🖼 Aspect: {s['aspect']}", callback_data="menu:aspect")],
        [InlineKeyboardButton(f"🧩 Fit: {s['fit']}", callback_data="menu:fit"),
         InlineKeyboardButton(f"🎞 FPS: {s['fps']}", callback_data="menu:fps")],
        [InlineKeyboardButton(f"💎 Quality: {s['quality']}", callback_data="menu:quality"),
         InlineKeyboardButton(f"🎚 Codec: {s['codec'].upper()}", callback_data="menu:codec")],
        [InlineKeyboardButton(f"🎵 Audio: {s['audio_mode']}", callback_data="menu:audio_mode"),
         InlineKeyboardButton(f"📤 Output: {s['output_mode']}", callback_data="menu:output")],
        [InlineKeyboardButton(f"💧 Watermark: {wm}", callback_data="menu:watermark"),
         InlineKeyboardButton(f"🔤 Title: {title}", callback_data="menu:title")],
    ]
    if not lite:
        rows += [
            [InlineKeyboardButton(f"🌊 Visualizer: {vis}", callback_data="menu:visualizer"),
             InlineKeyboardButton(f"🎨 Vis Color: {s['vis_color']}", callback_data="menu:vis_color")],
            [InlineKeyboardButton(f"📍 Vis Pos: {s['vis_position']}", callback_data="menu:vis_position"),
             InlineKeyboardButton(f"🎥 Ken Burns: {'ON' if s['ken_burns'] else 'OFF'}",
                                  callback_data="toggle:ken_burns")],
            [InlineKeyboardButton(f"🌓 Fade: {'ON' if s['fade'] else 'OFF'}", callback_data="toggle:fade"),
             InlineKeyboardButton(f"🙈 Spoiler: {'ON' if s['spoiler'] else 'OFF'}", callback_data="toggle:spoiler")],
        ]
    rows += [
        [InlineKeyboardButton(f"🎞 Slideshow: {s['slideshow_duration']}s/{s['slideshow_transition']}",
                              callback_data="menu:slideshow"),
         InlineKeyboardButton(f"🖼 Thumb: {s['thumbnail']}", callback_data="menu:thumbnail")],
        [InlineKeyboardButton("📝 Caption", callback_data="menu:caption"),
         InlineKeyboardButton("💾 Save as Preset", callback_data="preset:save")],
        [InlineKeyboardButton("♻️ Reset all", callback_data="set:reset:confirm"),
         InlineKeyboardButton("📂 My Files", callback_data="nav:files")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:start")],
    ]
    return InlineKeyboardMarkup(rows)


OPTIONS: Dict[str, List] = {
    "engine": ["lite", "pro"],
    "resolution": ["480p", "720p", "1080p", "1440p", "2160p", "original"],
    "aspect": ["16:9", "9:16", "1:1", "4:3", "4:5", "21:9"],
    "fit": ["blur", "crop", "pad", "stretch"],
    "fps": [1, 2, 5, 10, 15, 24, 25, 30, 60],
    "quality": ["low", "medium", "high", "ultra"],
    "codec": ["h264", "h265"],
    "audio_mode": ["copy", "aac64", "aac96", "aac128", "aac192", "aac320", "mp3"],
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
    "engine": "🚀 Engine\n\n• lite – loop-copy, 10 h in ~2 min, tiny file (recommended)\n• pro – full render, effects & visualizer (slow for long audio)",
    "resolution": "📐 Output resolution\n\n720p is plenty for audio-only videos.",
    "aspect": "🖼 Aspect ratio",
    "fit": "🧩 Image fit mode\n\n• blur – blurred background fill\n• crop – fill & crop edges\n• pad – black bars\n• stretch – distort to fit",
    "fps": "🎞 Frame rate\n\nLite: 1-30 (10 recommended; 1 = smallest file).\nPro: 24 / 25 / 30 / 60.",
    "quality": "💎 Encoding quality (higher = bigger file)",
    "codec": "🎚 Video codec\n\n• H264 – best compatibility\n• H265 – smaller, slower",
    "audio_mode": "🎵 Audio mode\n\n• copy – keep original MP3/AAC (fastest)\n• aacXX – re-encode once to AAC bitrate\n• mp3 – re-encode to MP3",
    "visualizer": "🌊 Audio visualizer overlay (Pro engine)",
    "vis_color": "🎨 Visualizer color",
    "vis_position": "📍 Visualizer position",
    "watermark_position": "📍 Watermark position",
    "title_position": "📍 Title position",
    "output_mode": "📤 Send as\n\n• video – streamable in Telegram\n• document – original file, no compression",
    "thumbnail": "🖼 Thumbnail source",
    "slideshow_duration": "⏱ Seconds per image (slideshow)",
    "slideshow_transition": "✨ Slideshow transition (Pro engine)",
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
def admin_keyboard(pending: int = 0, approved: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏳ Pending ({pending})", callback_data="admin:pending"),
         InlineKeyboardButton(f"✅ Approved ({approved})", callback_data="admin:approved")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin:stats"),
         InlineKeyboardButton("🖥 Server", callback_data="admin:server")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast_help"),
         InlineKeyboardButton("👥 Users", callback_data="admin:users")],
        [InlineKeyboardButton("🔨 Commands help", callback_data="admin:ban_help"),
         InlineKeyboardButton("🧹 Cleanup downloads", callback_data="admin:cleanup")],
        [InlineKeyboardButton("🏠 Home", callback_data="nav:start")],
    ])
