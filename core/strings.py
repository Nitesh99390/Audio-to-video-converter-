"""All user-facing texts (English)."""
from core.config import Config

START = (
    "👋 Hello **{name}**!\n\n"
    f"🚀 Welcome to **{Config.BOT_NAME}**.\n\n"
    "I turn **Audio + Photo** into a YouTube-ready **MP4** in a couple of minutes — "
    "even for **10-hour** videos. The video is kept as light as possible so uploads are quick "
    "and your listeners can simply play the audio.\n\n"
    "✨ **What I can do:**\n"
    "• ⚡ **Lite engine** – 10 h video in ~2 min, tiny file size\n"
    "• 🔁 **Loop audio** – 1 h track → 2 h / 5 h / 10 h video\n"
    "• 🖼 Photo, slideshow or looping video background\n"
    "• 🎬 Optional **Pro engine** – visualizer, Ken-Burns, fade, 4K\n"
    "• 💧 Watermark & 🔤 Title text\n\n"
    "📥 **Get started:** send a **Photo** and an **Audio**, then tap 🎬 **Convert Now**.\n"
    "⌨️ Use the keyboard buttons below."
)

HELP_MAIN = (
    "📖 **Help / Guide**\n\n"
    "**Basic flow:**\n"
    "1️⃣ Send a photo (or 2-20 photos for a slideshow)\n"
    "2️⃣ Send an audio / voice / music file\n"
    "3️⃣ Tap 🎬 **Convert Now**\n\n"
    "**Tips:**\n"
    "• Order does not matter – photo first or audio first.\n"
    "• Audio with embedded album-art? I will use it automatically.\n"
    "• Several audio files are merged one after another.\n"
    "• ⏱ **Duration** lets you loop the audio to 1 h, 2 h, 5 h, 10 h…\n"
    "• ⚡ **Lite** engine is the default – fastest & smallest. Switch to 🎬 **Pro** in Settings for effects.\n\n"
    "Pick a topic below 👇"
)

HELP_TOPICS = {
    "basic": (
        "🖼 **Image + Audio**\n\n"
        "Send one photo and one audio. The photo is fitted into the selected **aspect ratio**:\n"
        "• **blur** – blurred copy in the background (YouTube style)\n"
        "• **crop** – fill the frame, cut the edges\n"
        "• **pad** – black bars\n"
        "• **stretch** – stretch to fit"
    ),
    "lite": (
        "⚡ **Lite engine (default)**\n\n"
        "Only a short loop segment is encoded; it is then repeated for the whole length and the audio is "
        "attached **without re-encoding**. A 10-hour video is ready in about 1-2 minutes and the file is "
        "barely bigger than the audio itself.\n\n"
        "• FPS 1-30 (10 recommended)\n"
        "• Audio is stream-copied (MP3/AAC) or converted once to AAC\n"
        "• Title & watermark text still work\n"
        "• Visualizer / Ken-Burns / fade need the 🎬 **Pro** engine"
    ),
    "duration": (
        "⏱ **Duration / Loop**\n\n"
        "Settings → Duration lets you choose the final length: *same as audio*, 30 min, 1 h, 2 h, 3 h, "
        "5 h, 8 h, 10 h, 12 h or a custom value.\n\n"
        "If the target is longer than the audio, the audio is looped seamlessly. "
        "If it is shorter, the video is trimmed.\n\n"
        f"Max output: {Config.MAX_OUTPUT_DURATION_SEC // 3600} h / {Config.MAX_OUTPUT_SIZE_MB} MB "
        "(Telegram upload limit)."
    ),
    "slideshow": (
        "🎞 **Slideshow**\n\n"
        f"Send 2-{Config.MAX_SLIDESHOW_IMAGES} photos (as an album or one by one). Each photo is shown for the "
        "duration set in `Settings → Slideshow` and the set is looped until the audio ends."
    ),
    "bgvideo": (
        "🎥 **Video background**\n\n"
        "Send a short **video** instead of a photo — it is **looped** for the whole length. "
        "Its own sound is removed and your audio is used.\n\n"
        "Perfect for lo-fi loops, animated backgrounds, lyric videos."
    ),
    "visualizer": (
        "🌊 **Audio visualizer (Pro engine)**\n\n"
        "• **waves** – smooth waveform line\n"
        "• **bars** – frequency bars (equalizer)\n"
        "• **spectrum** – scrolling spectrogram\n"
        "• **cqt** – musical spectrum\n"
        "• **vectorscope** / **circle**\n\n"
        "⚠️ Pro renders take much longer for long audio."
    ),
    "watermark": (
        "💧 **Watermark & 🔤 Title**\n\n"
        "• **Watermark** – small text with a translucent box, 5 positions.\n"
        "• **Title** – big text (song name etc.) top / center / bottom.\n\n"
        "Settings → Watermark / Title → ✏️ Set text."
    ),
    "commands": (
        "📋 **Commands**\n\n"
        "/start – home\n"
        "/help – this guide\n"
        "/settings – settings panel\n"
        "/quick – quick modes\n"
        "/presets – saved presets\n"
        "/files – current uploaded files\n"
        "/convert – start conversion\n"
        "/cancel – cancel running job\n"
        "/clear – delete uploaded files\n"
        "/myaccess – your access status\n"
        "/request – request access\n"
        "/stats – your stats\n"
        "/history – last 5 videos\n"
        "/about – bot info\n"
        "/ping – alive check\n\n"
        "**Admin:** /admin /approve /reject /revoke /extend /pending /approved /broadcast /ban /unban /users /server"
    ),
}

ABOUT = (
    f"ℹ️ **{Config.BOT_NAME}**\n\n"
    "🧠 Engine: FFmpeg (loop-copy lite engine + libx264 / libx265)\n"
    "⚙️ Framework: Pyrogram (async MTProto)\n"
    "💾 Storage: SQLite\n\n"
    "🔒 Files are deleted from the server right after upload.\n"
    "⏱ Uptime: `{uptime}`\n"
    "🧵 Active jobs: `{active}` / {max_jobs}\n"
    "📦 Version: `3.0.0`"
)

FORCE_SUB = (
    "🔒 **Access locked**\n\n"
    "Please join our channel first, then tap **I have joined**."
)

BANNED = "🚫 You are banned from this bot. Contact support."

DAILY_LIMIT = (
    "⏳ **Daily limit reached**\n\n"
    "You used all {limit} free conversions today. Come back tomorrow or ask the admin for premium."
)

BUSY = "⚠️ One of your videos is already being processed. Finish or cancel it first."

NO_FILES = (
    "📂 **No files found!**\n\n"
    "Send a **Photo** (or video) and an **Audio** first, then tap 🎬 Convert."
)

NEED_MORE = {
    "audio": "🎵 Photo received! Now send the **Audio** file.",
    "visual": "🖼 Audio received! Now send a **Photo** (or a background video).",
}

# ---------------------------------------------------------------- access
ACCESS_REQUIRED = (
    "🔐 **Approval required**\n\n"
    "This bot is private. Tap the button below to send an access request to the owner. "
    "You will be notified as soon as it is approved."
)
ACCESS_PENDING = (
    "⏳ **Request pending**\n\n"
    "Your access request was sent to the owner. Please wait for approval — "
    "you will get a message here when it is decided."
)
ACCESS_SENT = (
    "✅ **Request sent!**\n\n"
    "The owner has been notified. You will receive a message as soon as your access is approved."
)
ACCESS_REJECTED = (
    "❌ **Request declined**\n\n"
    "Your last request was declined. You can send a new one after {cooldown} minutes."
)
ACCESS_COOLDOWN = "⏳ Please wait **{left}** before sending another request."
ACCESS_EXPIRED = (
    "⌛ **Access expired**\n\n"
    "Your access time is over. Tap the button below to request more time."
)
ACCESS_GRANTED_USER = (
    "🎉 **Access approved!**\n\n"
    "⏱ Duration: **{duration}**\n"
    "📅 Expires: {expires}\n\n"
    "Send a **Photo + Audio** and tap 🎬 Convert Now. Enjoy!"
)
ACCESS_EXTENDED_USER = (
    "➕ **Access extended!**\n\n"
    "⏱ Added: **{duration}**\n"
    "📅 New expiry: {expires}"
)
ACCESS_REVOKED_USER = "🔒 Your access has been revoked by the owner."
ACCESS_REJECTED_USER = "❌ Sorry, your access request was declined by the owner."
ACCESS_EXPIRED_USER = (
    "⌛ **Your access has expired.**\n\n"
    "Thanks for using the bot! Tap the button below if you need more time."
)
ACCESS_STATUS = (
    "🔑 **Your access**\n\n"
    "Status: {status}\n"
    "⏱ Time left: **{left}**\n"
    "📅 Expires: {expires}"
)

ADMIN_NEW_REQUEST = (
    "🔔 **New access request**\n\n"
    "👤 {mention}\n"
    "🆔 `{uid}`\n"
    "📛 Username: {username}\n"
    "🕐 {when}\n"
    "{note}\n"
    "How long should this user get access?"
)
