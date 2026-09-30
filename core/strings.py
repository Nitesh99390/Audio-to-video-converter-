"""All user-facing texts (Hinglish + English)."""
from core.config import Config

START = {
    "hi": (
        "👋 Namaste **{name}**!\n\n"
        f"🚀 **{Config.BOT_NAME}** me aapka swagat hai.\n\n"
        "Main aapke **Audio + Photo** ko seconds me professional **Video** bana deta hoon — "
        "YouTube, Shorts, Reels, WhatsApp Status sab ke liye ready.\n\n"
        "✨ **Features:**\n"
        "• 📐 480p → 4K, har aspect ratio (16:9, 9:16, 1:1 ...)\n"
        "• 🌊 Audio Visualizer (waves, bars, spectrum...)\n"
        "• 🎞 Multi-photo **Slideshow** with fade\n"
        "• 🎥 Video background loop\n"
        "• 💧 Watermark + 🔤 Title text\n"
        "• 🎥 Ken-Burns zoom, 🌓 Fade in/out\n"
        "• 🎛 Presets & ⚡ Quick Modes\n\n"
        "📥 **Shuru karo:** ek **Photo** aur ek **Audio** bhejo, phir 🎬 **Convert Now** dabao.\n"
        "⌨️ Neeche keyboard buttons use karo."
    ),
    "en": (
        "👋 Hello **{name}**!\n\n"
        f"🚀 Welcome to **{Config.BOT_NAME}**.\n\n"
        "I turn your **Audio + Photo** into a professional **Video** in seconds — "
        "ready for YouTube, Shorts, Reels and WhatsApp Status.\n\n"
        "✨ **Features:**\n"
        "• 📐 480p → 4K, any aspect ratio (16:9, 9:16, 1:1 ...)\n"
        "• 🌊 Audio Visualizer (waves, bars, spectrum...)\n"
        "• 🎞 Multi-photo **Slideshow** with fade\n"
        "• 🎥 Looping video background\n"
        "• 💧 Watermark + 🔤 Title text\n"
        "• 🎥 Ken-Burns zoom, 🌓 Fade in/out\n"
        "• 🎛 Presets & ⚡ Quick Modes\n\n"
        "📥 **Get started:** send a **Photo** and an **Audio**, then tap 🎬 **Convert Now**.\n"
        "⌨️ Use the keyboard buttons below."
    ),
}

HELP_MAIN = (
    "📖 **Help / Guide**\n\n"
    "**Basic flow:**\n"
    "1️⃣ Photo bhejo (ya 2-20 photos → slideshow)\n"
    "2️⃣ Audio / Voice / Music file bhejo\n"
    "3️⃣ 🎬 **Convert Now** dabao\n\n"
    "**Tips:**\n"
    "• Audio pehle bhejo ya photo pehle — koi farak nahi.\n"
    "• Sirf audio bhejo aur usme album-art hai? Main automatically use kar lunga.\n"
    "• Multiple audio bhejoge to sab merge ho jayenge (ek ke baad ek).\n"
    "• ⚙️ Settings se resolution, ratio, visualizer, watermark sab customize karo.\n"
    "• ⚡ Quick Modes se ek click me platform-ready output.\n\n"
    "Neeche topics choose karo 👇"
)

HELP_TOPICS = {
    "basic": (
        "🖼 **Image + Audio**\n\n"
        "Ek photo aur ek audio bhejo. Photo ko selected **aspect ratio** me fit kiya jayega:\n"
        "• **blur** – background me blurred copy (YouTube style)\n"
        "• **crop** – photo se frame fill, edges cut\n"
        "• **pad** – black bars\n"
        "• **stretch** – kheench kar fit\n\n"
        "🎥 **Ken Burns** ON karo to photo par slow zoom effect aayega."
    ),
    "slideshow": (
        "🎞 **Slideshow**\n\n"
        f"2 se {Config.MAX_SLIDESHOW_IMAGES} photos bhejo (album ya ek-ek karke). "
        "Har photo `Settings → Slideshow` me set duration tak dikhegi aur audio khatam hone tak loop hogi.\n\n"
        "Transition: **fade** (smooth cross-fade) ya **none** (hard cut)."
    ),
    "bgvideo": (
        "🎥 **Video Background**\n\n"
        "Photo ke bajaye ek chhota **video** bhejo — wo audio ki length tak **loop** hoga. "
        "Video ka apna audio hata diya jayega aur aapka audio use hoga.\n\n"
        "Perfect for: lo-fi loops, animated backgrounds, lyric videos."
    ),
    "visualizer": (
        "🌊 **Audio Visualizer**\n\n"
        "• **waves** – smooth waveform line\n"
        "• **bars** – frequency bars (equalizer)\n"
        "• **spectrum** – scrolling spectrogram\n"
        "• **cqt** – musical spectrum (piano-style)\n"
        "• **vectorscope** – lissajous curves\n"
        "• **circle** – polar dots\n\n"
        "Color aur position (top/center/bottom) bhi set kar sakte ho.\n"
        "⚠️ Visualizer ke saath render time badhta hai."
    ),
    "watermark": (
        "💧 **Watermark & 🔤 Title**\n\n"
        "• **Watermark** – chhota text with semi-transparent box, 5 positions.\n"
        "• **Title** – bada text (song name etc.) top/center/bottom.\n\n"
        "Settings → Watermark / Title → ✏️ Set text → apna text type karo.\n"
        "Emoji support depends on server font."
    ),
    "commands": (
        "📋 **Commands**\n\n"
        "/start – bot start / home\n"
        "/help – yeh guide\n"
        "/settings – settings panel\n"
        "/quick – quick modes\n"
        "/presets – saved presets\n"
        "/files – current uploaded files\n"
        "/convert – start conversion\n"
        "/cancel – running job cancel\n"
        "/clear – uploaded files delete\n"
        "/stats – aapke stats\n"
        "/history – last 5 videos\n"
        "/about – bot info\n"
        "/ping – bot alive check\n\n"
        "**Admin:** /admin /broadcast /ban /unban /premium /users /server"
    ),
}

ABOUT = (
    f"ℹ️ **{Config.BOT_NAME}**\n\n"
    "🧠 Engine: FFmpeg (libx264 / libx265)\n"
    "⚙️ Framework: Pyrogram (async MTProto)\n"
    "💾 Storage: SQLite (settings, presets, stats)\n"
    "🐍 Python 3.10+\n\n"
    "🔒 Files are deleted from server immediately after upload.\n"
    "⏱ Uptime: `{uptime}`\n"
    "🧵 Active jobs: `{active}` / {max_jobs}\n"
    "📦 Version: `2.0.0`"
)

FORCE_SUB = (
    "🔒 **Access Locked**\n\n"
    "Bot use karne ke liye pehle hamara channel join karo, phir **I have joined** dabao."
)

BANNED = "🚫 Aap is bot se banned hain. Support se contact karein."

DAILY_LIMIT = (
    "⏳ **Daily limit reached**\n\n"
    "Aaj ke {limit} free conversions ho gaye. Kal wapas aao ya premium ke liye admin se contact karo."
)

BUSY = "⚠️ Aapka ek video already process ho raha hai. Pehle usko complete/cancel karo."

NO_FILES = (
    "📂 **Koi file nahi mili!**\n\n"
    "Pehle ek **Photo** (ya video) aur ek **Audio** bhejo, phir 🎬 Convert dabao."
)

NEED_MORE = {
    "audio": "🎵 Photo mil gayi! Ab **Audio** file bhejo (ya 🎬 Convert dabao jab ready ho).",
    "visual": "🖼 Audio mil gaya! Ab **Photo** bhejo (ya video background).",
}
