# 🎬 Advanced Audio → Video Telegram Bot

Professional, production-ready Telegram bot that turns **Audio + Photo(s)/Video** into a polished **MP4 video** — ready for YouTube, Shorts, Reels, Instagram and WhatsApp Status.

Built with **Pyrogram** (async MTProto) + **FFmpeg** + **SQLite**.

---

## ✨ Features

### 🎥 Rendering
| Feature | Options |
|---|---|
| Resolution | 480p · 720p · 1080p · 1440p · 4K (2160p) · original |
| Aspect ratio | 16:9 · 9:16 · 1:1 · 4:3 · 4:5 · 21:9 |
| Image fit | **blur** (blurred bg fill) · crop · pad · stretch |
| FPS | 24 · 25 · 30 · 60 |
| Quality | low · medium · high · ultra (CRF based) |
| Codec | H.264 (compat) · H.265/HEVC (smaller) |
| Audio | stream-copy (fastest) · AAC 128/192/320k · MP3 |
| Visualizer | waves · bars · spectrum · CQT · vectorscope · circle — 8 colors, 3 positions |
| Effects | Ken-Burns slow zoom · fade in/out (video + audio) |
| Overlays | Watermark text (5 positions) · Title text (3 positions) |
| Modes | Single image · **Slideshow** (2–20 photos, cross-fade) · **Looping video background** |
| Extras | Multi-audio merge · auto album-art extraction · custom thumbnail · spoiler · send as video/document |

### ⌨️ UI
- **Persistent reply keyboard** (bottom buttons): Convert Now · Quick Modes · Settings · Presets · My Files · Clear · Stats · Help · About (+ Admin Panel)
- **Inline settings panel** – every option one tap away, live values shown on buttons
- **⚡ Quick Modes** – YouTube 1080p, Shorts/Reels, Instagram Square, WhatsApp Status, Music Video, Podcast, Fastest, 4K
- **🎛 Presets** – save / load / delete your own setting bundles
- **Live progress** – download → merge → render (%, speed, ETA) → upload, with ❌ Cancel button
- **After-video actions** – re-render same files with new settings, start new

### 🛡 Platform
- Job **queue** with concurrency limit · per-user single job · cancel kills FFmpeg instantly
- **SQLite** persistence: users, settings, presets, usage, history, global stats
- Daily free limit + **premium** users · **ban/unban** · **force-subscribe** channel · **log channel**
- **Admin panel**: stats, server info (CPU/RAM/disk), broadcast (with pin), cleanup
- Auto maintenance: stale sessions & orphan files purged
- Hinglish/English UI toggle · bot command menu auto-registered

---

## 🚀 Setup

### 1. Credentials
- `API_ID`, `API_HASH` → https://my.telegram.org
- `BOT_TOKEN` → [@BotFather](https://t.me/BotFather)

### 2. Run locally
```bash
git clone <repo> && cd <repo>
cp .env.example .env        # fill in values
pip install -r requirements.txt
sudo apt install ffmpeg fonts-dejavu-core   # Debian/Ubuntu
python bot.py
```

### 3. Docker
```bash
cp .env.example .env && nano .env
docker compose up -d --build
```

### 4. Kaggle / Colab
Add `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID` as **Secrets**, then:
```python
!apt-get -qq install -y ffmpeg fonts-dejavu-core
!pip -q install -r requirements.txt
!python bot.py
```

---

## ⚙️ Environment variables
See [`.env.example`](.env.example). Only `API_ID`, `API_HASH`, `BOT_TOKEN` are required.

| Var | Default | Purpose |
|---|---|---|
| `OWNER_ID` / `ADMINS` | – | Admin access (`/admin`, broadcast, ban…) |
| `LOG_CHANNEL` | – | Copy every generated video here |
| `FORCE_SUB_CHANNEL` | – | Require channel join (bot must be admin) |
| `MAX_CONCURRENT_TASKS` | 3 | Parallel FFmpeg renders |
| `DAILY_LIMIT_FREE` | 30 | Free conversions/day (premium = unlimited) |
| `MAX_SLIDESHOW_IMAGES` | 20 | Photos per slideshow |
| `MAX_FILE_SIZE_MB` | 2000 | Upload size cap |

---

## 📋 Commands

**User:** `/start` `/convert` `/settings` `/quick` `/presets` `/preset save|load|del <name>` `/files` `/clear` `/cancel` `/stats` `/history` `/help` `/about` `/ping`

**Admin:** `/admin` `/broadcast [-pin]` (reply to a message) `/users` `/server` `/ban <id> [reason]` `/unban <id>` `/premium <id>`

---

## 🗂 Project structure
```
bot.py                 # entry point, command registration, maintenance loop
core/
  config.py            # env config
  database.py          # aiosqlite layer (users/settings/presets/stats/history)
  engine.py            # FFmpeg command builder + progress-streaming runner
  keyboards.py         # reply keyboard + all inline menus
  state.py             # per-user sessions, job registry, cancel, semaphore
  helpers.py           # access gate, force-sub, files panel
  strings.py           # UI texts
  utils.py             # ffprobe, progress bar, formatting, cleanup
plugins/
  start.py             # /start /help /about /stats /history + reply-button router
  media.py             # photo / album / audio / voice / video / document intake
  convert.py           # conversion pipeline (queue → render → upload → log)
  settings.py          # settings menus, toggles, quick modes, presets, text input
  admin.py             # admin panel & moderation
```

---

## 🧪 Tested
The FFmpeg engine was validated against 15 configurations (all fit modes, all visualizers, slideshow with/without fade, looping video background, H.265, "original" resolution, AAC re-encode, watermark + title + fade) plus an end-to-end pipeline test covering audio merge, mid-render cancel and document output.

## 📄 License
MIT
