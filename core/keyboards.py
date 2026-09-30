"""
All keyboards: persistent Reply Keyboard (bottom buttons) + Inline Keyboards (menus).

Design rules
------------
* The bottom keyboard shows only what is needed *right now* (2 rows, 3 for admins).
* Settings is tiered: the main panel has the 4-5 things people actually change,
  everything else lives in "🔧 Advanced" and (Pro / admins only) "✨ Effects".
* Options that a user is not allowed to use are simply not rendered.
* Callback data format:  "<menu>:<action>:<value>"
"""
from typing import Any, Dict, List, Optional

from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

from core.config import Config
from core.policy import can_use_pro, fps_options

# ================================================================
#  PERSISTENT REPLY KEYBOARD  (bottom "keyboard buttons")
# ================================================================
BTN_CONVERT = "🎬 Convert Now"
BTN_DURATION = "⏱ Duration"
BTN_SETTINGS = "⚙️ Settings"
BTN_STATUS = "📂 My Files"
BTN_HELP = "❓ Help"
BTN_ADMIN = "👑 Admin"
BTN_ACCESS = "🔑 My Access"
# legacy labels – still routed so old keyboards on users' phones keep working
BTN_PRESETS = "🎛 Presets"
BTN_CANCEL = "❌ Cancel"
BTN_CLEAR = "🗑 Clear Files"
BTN_STATS = "📊 My Stats"
BTN_ABOUT = "ℹ️ About"
BTN_QUICK = "⚡ Quick Modes"
BTN_ADMIN_LEGACY = "👑 Admin Panel"

REPLY_BUTTONS = {
    BTN_CONVERT, BTN_DURATION, BTN_SETTINGS, BTN_STATUS, BTN_HELP, BTN_ACCESS,
    BTN_PRESETS, BTN_CANCEL, BTN_CLEAR, BTN_STATS, BTN_ABOUT, BTN_QUICK,
}
ADMIN_BUTTONS = {BTN_ADMIN, BTN_ADMIN_LEGACY}


def main_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_CONVERT), KeyboardButton(BTN_DURATION)],
        [KeyboardButton(BTN_SETTINGS), KeyboardButton(BTN_STATUS), KeyboardButton(BTN_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True,
                               placeholder="Send a photo + audio, then tap Convert")


def request_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_ACCESS), KeyboardButton(BTN_HELP)]],
                               resize_keyboard=True, is_persistent=True)


def processing_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True)


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ================================================================
#  INLINE KEYBOARD HELPERS
# ================================================================
def _mark(label: str, active: bool) -> str:
    return f"• {label} •" if active else label


def _grid(buttons: List[InlineKeyboardButton], cols: int) -> List[List[InlineKeyboardButton]]:
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def _btn(label: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=cb)


def _back(target: str = "settings", label: str = "‹ Back") -> InlineKeyboardButton:
    return _btn(label, f"nav:{target}")


def _home() -> InlineKeyboardButton:
    return _btn("🏠 Home", "nav:start")


def _onoff(v) -> str:
    return "on" if v else "off"


# ---------------------------------------------------------------- start / help
def start_keyboard(uid: Optional[int] = None) -> InlineKeyboardMarkup:
    rows = [[_btn("⚡ Quick Modes", "nav:quick"), _btn("📖 How to use", "nav:help")]]
    links = []
    if Config.UPDATES_LINK:
        links.append(InlineKeyboardButton("📢 Updates", url=Config.UPDATES_LINK))
    if Config.SUPPORT_LINK:
        links.append(InlineKeyboardButton("🛠 Support", url=Config.SUPPORT_LINK))
    if links:
        rows.append(links)
    return InlineKeyboardMarkup(rows)


def help_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [_btn("🖼 Photo + Audio", "help:basic"), _btn("⏱ Duration / Loop", "help:duration")],
        [_btn("🎬 Intro & Outro", "help:introoutro"), _btn("🎥 Video background", "help:bgvideo")],
        [_btn("🎞 Slideshow", "help:slideshow")],
        [_btn("💧 Watermark & Title", "help:watermark"), _btn("📋 Commands", "help:commands")],
    ]
    if is_admin:
        rows.append([_btn("⚡ Lite vs 🎬 Pro", "help:lite"), _btn("🌊 Visualizer", "help:visualizer")])
    rows.append([_btn("🔑 My Access", "nav:access"), _btn("📊 My Stats", "nav:stats"), _btn("ℹ️ About", "nav:about")])
    rows.append([_home()])
    return InlineKeyboardMarkup(rows)


def force_sub_keyboard(link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join channel", url=link)],
        [_btn("✅ I have joined", "nav:checksub")],
    ])


# ------------------------------------------------------------ access / approval
# label -> seconds (0 = permanent). Full list is used for parsing / labels.
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
# the ones shown by default (owner taps "More" for the rest)
APPROVE_QUICK = ["1 hour", "5 hours", "10 hours", "1 day", "7 days", "30 days"]
EXTEND_QUICK = ["1 hour", "10 hours", "1 day", "7 days", "30 days"]


def request_access_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("📨 Request access", "access:request")]])


def approve_keyboard(uid: int, expanded: bool = False) -> InlineKeyboardMarkup:
    """Shown to the owner under every access request."""
    labels = list(APPROVE_DURATIONS) if expanded else APPROVE_QUICK
    btns = [_btn(label, f"approve:{uid}:{APPROVE_DURATIONS[label]}") for label in labels if APPROVE_DURATIONS[label]]
    rows = _grid(btns, 3)
    rows.append([_btn("♾ Permanent", f"approve:{uid}:0"),
                 _btn("⋯ Less" if expanded else "⋯ More", f"approvemore:{uid}:{0 if expanded else 1}")])
    rows.append([_btn("❌ Reject", f"reject:{uid}"), _btn("🚫 Ban", f"banuser:{uid}")])
    return InlineKeyboardMarkup(rows)


def manage_user_keyboard(uid: int) -> InlineKeyboardMarkup:
    """Owner controls for an already approved user."""
    btns = [_btn(f"+{label}", f"extend:{uid}:{APPROVE_DURATIONS[label]}") for label in EXTEND_QUICK]
    rows = _grid(btns, 3)
    rows.append([_btn("♾ Permanent", f"approve:{uid}:0"), _btn("🔒 Revoke", f"revoke:{uid}")])
    rows.append([_btn("‹ Approved list", "admin:approved")])
    return InlineKeyboardMarkup(rows)


def approved_list_keyboard(rows_data: List[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in rows_data[:30]:
        name = (r.get("first_name") or str(r["user_id"]))[:20]
        rows.append([_btn(f"👤 {name} · {r['user_id']}", f"manage:{r['user_id']}")])
    rows.append([_back("admin", "‹ Admin")])
    return InlineKeyboardMarkup(rows)


def pending_list_keyboard(rows_data: List[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in rows_data[:30]:
        name = (r.get("first_name") or str(r["user_id"]))[:20]
        rows.append([_btn(f"⏳ {name} · {r['user_id']}", f"showreq:{r['user_id']}")])
    rows.append([_back("admin", "‹ Admin")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------ files / job
def files_keyboard(session, ready: bool) -> InlineKeyboardMarkup:
    rows = []
    if ready:
        rows.append([_btn("🚀 Convert now", "job:start")])
        rows.append([_btn("⏱ Duration", "menu:target_duration"), _btn("⚙️ Settings", "nav:settings")])
    row = []
    if session.photos:
        row.append(_btn(f"🗑 Photos ({len(session.photos)})", "files:clear_photos"))
    if session.audios:
        row.append(_btn(f"🗑 Audio ({len(session.audios)})", "files:clear_audio"))
    if session.bg_video:
        row.append(_btn("🗑 Video", "files:clear_video"))
    clip_row = []
    if session.intro:
        clip_row.append(_btn("🗑 Intro", "files:clear_intro"))
    if session.outro:
        clip_row.append(_btn("🗑 Outro", "files:clear_outro"))
    if session.intro and session.outro:
        clip_row.append(_btn("🔃 Swap", "files:swap_clips"))
    total = len(row) + len(clip_row)
    if total > 1:
        rows.append(row) if row else None
        if clip_row:
            rows.append(clip_row)
        rows.append([_btn("🗑 Remove all files", "files:clear_all")])
    elif total == 1:
        rows.append([_btn("🗑 Remove file", "files:clear_all")])
    return InlineKeyboardMarkup(rows) if rows else None


def video_role_keyboard(current: str) -> InlineKeyboardMarkup:
    """Shown right after a video is received: lets the user move it to another slot."""
    opts = [("intro", "🎬 Intro"), ("outro", "🏁 Outro"), ("bg", "🎥 Background")]
    row = [_btn(_mark(lbl, k == current), f"vrole:{current}:{k}") for k, lbl in opts]
    return InlineKeyboardMarkup([row, [_btn("🗑 Remove this clip", f"vrole:{current}:remove")]])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("✖ Cancel", "job:cancel")]])


def after_video_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🔁 Convert again", "job:redo"), _btn("🆕 New video", "files:clear_all")],
    ])


# ------------------------------------------------------------- quick modes
QUICK_MODES: Dict[str, Dict[str, Any]] = {
    "lite": {"label": "⚡ Fast 720p · recommended", "engine": "lite", "resolution": "720p", "aspect": "16:9",
             "fit": "blur", "fps": 10, "quality": "medium", "visualizer": "none", "audio_mode": "copy"},
    "lite1080": {"label": "⚡ Fast 1080p", "engine": "lite", "resolution": "1080p", "aspect": "16:9",
                 "fit": "blur", "fps": 10, "quality": "medium", "visualizer": "none", "audio_mode": "copy"},
    "tiny": {"label": "🪶 Smallest file", "engine": "lite", "resolution": "480p", "aspect": "16:9",
             "fit": "stretch", "fps": 1, "quality": "low", "visualizer": "none", "audio_mode": "aac64"},
    "vertical": {"label": "📱 Vertical 9:16", "engine": "lite", "resolution": "1080p", "aspect": "9:16",
                 "fit": "blur", "fps": 10, "quality": "medium", "visualizer": "none", "audio_mode": "copy"},
    # ---- Pro (admins) ----
    "youtube": {"label": "🎬 YouTube Pro 1080p", "engine": "pro", "resolution": "1080p", "aspect": "16:9",
                "fit": "blur", "visualizer": "none", "quality": "high", "fps": 30},
    "shorts": {"label": "🎬 Shorts · waves", "engine": "pro", "resolution": "1080p", "aspect": "9:16",
               "fit": "blur", "visualizer": "waves", "quality": "high", "fps": 30},
    "lyric": {"label": "🎬 Music video · spectrum", "engine": "pro", "resolution": "1080p", "aspect": "16:9",
              "fit": "blur", "visualizer": "spectrum", "quality": "ultra", "fps": 30, "ken_burns": True,
              "fade": True},
    "4k": {"label": "🎬 4K Ultra", "engine": "pro", "resolution": "2160p", "aspect": "16:9", "fit": "blur",
           "visualizer": "none", "quality": "ultra", "fps": 30},
}


def quick_modes_for(uid: int) -> Dict[str, Dict[str, Any]]:
    pro_ok = can_use_pro(uid)
    return {k: v for k, v in QUICK_MODES.items() if pro_ok or v["engine"] == "lite"}


def quick_modes_keyboard(uid: int) -> InlineKeyboardMarkup:
    modes = quick_modes_for(uid)
    btns = [_btn(v["label"], f"quick:{k}") for k, v in modes.items()]
    rows = _grid(btns, 2)
    rows.append([_back("settings", "‹ Settings"), _home()])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------- duration
# label -> seconds ; 0 = same as audio
DURATION_PRESETS: Dict[str, int] = {
    "Same as audio": 0,
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
    items = list(DURATION_PRESETS.items())
    rows = [[_btn(_mark(items[0][0], current == 0), "set:target_duration:0")]]
    rows += _grid([_btn(_mark(label, secs == current), f"set:target_duration:{secs}") for label, secs in items[1:]], 4)
    rows.append([_btn("✏️ Custom length", "input:target_duration"), _back(back)])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------- settings (tiered)
def settings_keyboard(s: Dict[str, Any], uid: int) -> InlineKeyboardMarkup:
    pro_ok = can_use_pro(uid)
    pro = s.get("engine", "lite") == "pro"
    rows = []
    if pro_ok:
        rows.append([_btn(f"🚀 Engine: {'🎬 Pro' if pro else '⚡ Lite'}", "toggle:engine")])
    rows += [
        [_btn(f"⏱ Length: {duration_label(int(s.get('target_duration') or 0))}", "menu:target_duration")],
        [_btn(f"📐 {s['resolution']}", "menu:resolution"), _btn(f"🖼 {s['aspect']}", "menu:aspect"),
         _btn(f"🎞 {s['fps']} fps", "menu:fps")],
        [_btn(f"🎵 Audio: {s['audio_mode']}", "menu:audio_mode"), _btn("🔧 Advanced", "nav:advanced")],
    ]
    if pro and pro_ok:
        rows[-1].append(_btn("✨ Effects", "nav:effects"))
    rows.append([_btn("⚡ Quick Modes", "nav:quick"), _btn("🎛 Presets", "nav:presets"), _home()])
    return InlineKeyboardMarkup(rows)


def advanced_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    wm = _onoff(s.get("watermark_text"))
    title = _onoff(s.get("title_text"))
    return InlineKeyboardMarkup([
        [_btn(f"🧩 Fit: {s['fit']}", "menu:fit"), _btn(f"💎 Quality: {s['quality']}", "menu:quality")],
        [_btn(f"🎚 Codec: {s['codec'].upper()}", "menu:codec"), _btn(f"📤 Send as: {s['output_mode']}", "menu:output")],
        [_btn(f"💧 Watermark: {wm}", "menu:watermark"), _btn(f"🔤 Title: {title}", "menu:title")],
        [_btn(f"🎞 Slideshow: {s['slideshow_duration']}s", "menu:slideshow"),
         _btn(f"🖼 Thumb: {s['thumbnail']}", "menu:thumbnail")],
        [_btn("📝 Caption", "menu:caption"), _btn(f"🙈 Spoiler: {_onoff(s.get('spoiler'))}", "toggle:spoiler")],
        [_btn("♻️ Reset all", "set:reset:confirm"), _back("settings", "‹ Settings")],
    ])


def effects_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(f"🌊 Visualizer: {s['visualizer']}", "menu:visualizer")],
        [_btn(f"🎨 Color: {s['vis_color']}", "menu:vis_color"), _btn(f"📍 Position: {s['vis_position']}", "menu:vis_position")],
        [_btn(f"🎥 Ken Burns: {_onoff(s.get('ken_burns'))}", "toggle:ken_burns"),
         _btn(f"🌓 Fade: {_onoff(s.get('fade'))}", "toggle:fade")],
        [_back("settings", "‹ Settings")],
    ])


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

# which panel each option belongs to (used for the Back button and after saving)
PANEL_OF: Dict[str, str] = {
    "resolution": "settings", "aspect": "settings", "fps": "settings", "audio_mode": "settings",
    "target_duration": "settings", "engine": "settings",
    "fit": "advanced", "quality": "advanced", "codec": "advanced", "output_mode": "advanced",
    "thumbnail": "advanced", "spoiler": "advanced", "custom_caption": "advanced",
    "watermark_text": "menu_watermark", "watermark_position": "menu_watermark",
    "title_text": "menu_title", "title_position": "menu_title",
    "slideshow_duration": "menu_slideshow", "slideshow_transition": "menu_slideshow",
    "visualizer": "effects", "vis_color": "effects", "vis_position": "effects",
    "ken_burns": "effects", "fade": "effects",
}

OPTION_TITLES = {
    "engine": "🚀 **Engine**\n\n• **lite** – loop-copy, 10 h video in ~2 min, tiny file\n• **pro** – full render with visualizer & effects (slow for long audio)",
    "resolution": "📐 **Resolution**\n\n720p is plenty for audio-only videos; 1080p if you want it crisp.",
    "aspect": "🖼 **Aspect ratio**\n\n16:9 for YouTube, 9:16 for Shorts / Reels, 1:1 for posts.",
    "fit": "🧩 **Image fit**\n\n• blur – blurred background fill\n• crop – fill & cut edges\n• pad – black bars\n• stretch – distort to fit",
    "fps": "🎞 **Frame rate**\n\nStatic picture → 10 fps is ideal. 1 fps gives the smallest file.",
    "quality": "💎 **Encoding quality**\n\nHigher = sharper picture, bigger file.",
    "codec": "🎚 **Video codec**\n\n• H264 – best compatibility\n• H265 – smaller, slower",
    "audio_mode": "🎵 **Audio**\n\n• copy – keep the original MP3/AAC (fastest, no quality loss)\n• aacNN – re-encode once to that bitrate (smaller file)\n• mp3 – re-encode to MP3",
    "visualizer": "🌊 **Visualizer overlay** (Pro engine)",
    "vis_color": "🎨 **Visualizer color**",
    "vis_position": "📍 **Visualizer position**",
    "watermark_position": "📍 **Watermark position**",
    "title_position": "📍 **Title position**",
    "output_mode": "📤 **Send as**\n\n• video – streams inside Telegram\n• document – original file, no compression",
    "thumbnail": "🖼 **Thumbnail**\n\n• photo – your picture\n• auto – frame from the video\n• none",
    "slideshow_duration": "⏱ **Seconds per image**",
    "slideshow_transition": "✨ **Slideshow transition** (Pro engine)",
}


def option_keyboard(key: str, current: Any, back: str = "settings",
                    opts: Optional[List] = None) -> InlineKeyboardMarkup:
    opts = OPTIONS[key] if opts is None else opts
    btns = [_btn(_mark(str(o), str(o) == str(current)), f"set:{key}:{o}") for o in opts]
    cols = 4 if len(opts) > 6 else (3 if len(opts) > 4 else 2)
    rows = _grid(btns, cols)
    rows.append([_back(back)])
    return InlineKeyboardMarkup(rows)


def options_for(key: str, s: Dict[str, Any], uid: int) -> List:
    """Options a given user may pick for `key` (engine/policy aware)."""
    if key == "fps":
        return fps_options(s)
    if key == "resolution":
        opts = list(OPTIONS["resolution"])
        if s.get("engine", "lite") == "lite" and not can_use_pro(uid):
            opts = [o for o in opts if o not in ("1440p", "2160p")]
        return opts
    return OPTIONS[key]


def watermark_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows = [[_btn("✏️ Set text", "input:watermark_text"),
             _btn(f"📍 {s['watermark_position']}", "menu:watermark_position")]]
    if s.get("watermark_text"):
        rows.append([_btn("🗑 Remove watermark", "set:watermark_text:")])
    rows.append([_back("advanced")])
    return InlineKeyboardMarkup(rows)


def title_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows = [[_btn("✏️ Set text", "input:title_text"),
             _btn(f"📍 {s['title_position']}", "menu:title_position")]]
    if s.get("title_text"):
        rows.append([_btn("🗑 Remove title", "set:title_text:")])
    rows.append([_back("advanced")])
    return InlineKeyboardMarkup(rows)


def caption_keyboard(s: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows = [[_btn("✏️ Set custom caption", "input:custom_caption")]]
    if s.get("custom_caption"):
        rows.append([_btn("♻️ Use default caption", "set:custom_caption:")])
    rows.append([_back("advanced")])
    return InlineKeyboardMarkup(rows)


def slideshow_keyboard(s: Dict[str, Any], uid: int) -> InlineKeyboardMarkup:
    row = [_btn(f"⏱ {s['slideshow_duration']}s per image", "menu:slideshow_duration")]
    if can_use_pro(uid):
        row.append(_btn(f"✨ {s['slideshow_transition']}", "menu:slideshow_transition"))
    return InlineKeyboardMarkup([row, [_back("advanced")]])


def input_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("✖ Cancel", "input:cancel")]])


def confirm_keyboard(yes_cb: str, no_cb: str = "nav:advanced") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("✅ Yes, reset", yes_cb), _btn("✖ No", no_cb)]])


# -------------------------------------------------------------- presets
def presets_keyboard(names: List[str]) -> InlineKeyboardMarkup:
    rows = []
    for n in names[:10]:
        rows.append([_btn(f"🎛 {n}", f"preset:load:{n}"), _btn("🗑", f"preset:del:{n}")])
    rows.append([_btn("💾 Save current settings", "preset:save")])
    rows.append([_back("settings", "‹ Settings"), _home()])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------- admin
def admin_keyboard(pending: int = 0, approved: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(f"⏳ Pending ({pending})", "admin:pending"), _btn(f"✅ Approved ({approved})", "admin:approved")],
        [_btn("📊 Stats", "admin:stats"), _btn("🖥 Server", "admin:server"), _btn("🗄 Storage", "admin:storage")],
        [_btn("📢 Broadcast", "admin:broadcast_help"), _btn("📋 Commands", "admin:ban_help")],
        [_btn("🧹 Clean now", "admin:cleanup"), _home()],
    ])
