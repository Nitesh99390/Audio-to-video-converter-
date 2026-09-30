"""All user-facing texts (English)."""
from core.config import Config

START = (
    "👋 Hello **{name}**!\n\n"
    f"Welcome to **{Config.BOT_NAME}** — turn **audio + a photo** into a YouTube-ready MP4, "
    "even 10-hour videos in about a minute.\n\n"
    "**How it works**\n"
    "1️⃣ Send an **intro video** _(optional)_\n"
    "2️⃣ Send a **photo**\n"
    "3️⃣ Send an **outro video** _(optional)_\n"
    "4️⃣ Send an **audio file**\n"
    "5️⃣ Tap **🎬 Convert Now**\n\n"
    "→ You get: `intro` + `photo & audio` + `outro` in one MP4.\n\n"
    "⏱ Want a 2 h / 5 h / 10 h video from a short track? Set the length with **⏱ Duration** — "
    "the audio is looped seamlessly."
)

HELP_MAIN = (
    "📖 **Guide**\n\n"
    "1️⃣ Send an intro video _(optional)_\n"
    "2️⃣ Send a photo (or 2-20 photos for a slideshow)\n"
    "3️⃣ Send an outro video _(optional)_\n"
    "4️⃣ Send an audio / voice / music file\n"
    "5️⃣ Tap **🎬 Convert Now**\n\n"
    "• Order does not matter — the 1st video is the intro, the 2nd the outro. "
    "Each clip gets buttons to move it to another slot.\n"
    "• Audio with embedded album art? It is used automatically.\n"
    "• Several audio files are merged one after another.\n"
    "• **⏱ Duration** loops the audio to 1 h, 5 h, 10 h…\n"
    "• Files are deleted from the server right after the video is sent.\n\n"
    "Pick a topic 👇"
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
    "introoutro": (
        "🎬 **Intro & 🏁 Outro**\n\n"
        "Send a short video **before** and/or **after** your photo + audio:\n"
        "`[ intro ] + [ photo + audio ] + [ outro ]`\n\n"
        "• The **first** video you send becomes the intro, the **second** the outro. "
        "Under every clip there are buttons: Intro / Outro / Background / Remove.\n"
        f"• Max clip length: {Config.MAX_INTRO_OUTRO_SEC // 60} min. Clips keep their own sound; silent clips stay silent.\n"
        "• Clips are fitted into the frame with black bars (nothing is cropped) and matched to the "
        "main video's resolution / fps / codec **once** — the long main part is never re-encoded, "
        "so a 10-hour video with intro + outro is still ready in about a minute.\n"
        "• **⏱ Duration** applies to the main part only; the intro/outro are added on top."
    ),
    "bgvideo": (
        "🎥 **Video background**\n\n"
        "Send a **video** instead of a photo — it is **looped** for the whole length. "
        "Its own sound is removed and your audio is used.\n\n"
        "A video longer than 90 s sent while no photo is set is used as background automatically; "
        "otherwise tap **🎥 Background** under the clip.\n\n"
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
        "/convert – start the conversion\n"
        "/duration `10h` – final video length\n"
        "/settings – output settings\n"
        "/files – uploaded files\n"
        "/clear – delete uploaded files\n"
        "/cancel – cancel the running job\n"
        "/myaccess – access status\n"
        "/stats · /history – your numbers\n"
        "/help – this guide"
    ),
}

ABOUT = (
    f"ℹ️ **{Config.BOT_NAME}**\n\n"
    "🧠 Engine: FFmpeg (loop-copy lite engine + libx264 / libx265)\n"
    "⚙️ Framework: Pyrogram (async MTProto)\n"
    "💾 Storage: SQLite\n\n"
    "🔒 Files are deleted from the server right after upload; idle uploads auto-expire.\n"
    "⏱ Uptime: `{uptime}`\n"
    "🧵 Active jobs: `{active}` / {max_jobs}\n"
    "📦 Version: `3.1.0`"
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

STORAGE_FULL = (
    "🗄 **Server storage is full right now.**\n\n"
    "Other jobs are using the disk. Please try again in a few minutes — "
    "space is freed automatically as soon as they finish."
)

NO_FILES = (
    "📂 **No files found!**\n\n"
    "Send a **Photo** (or video) and an **Audio** first, then tap 🎬 Convert."
)

NEED_MORE = {
    "audio": "🎵 Photo received! Now send the **Audio** file.",
    "visual": "🖼 Audio received! Now send a **Photo** (or a background video).",
    "both": "👍 Clip saved. Now send a **Photo** and an **Audio** file.",
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
