# 🎬 Audio → Video Telegram Bot (Lite engine + Approval system)

Private Telegram bot that turns **Audio + Photo** into a light, YouTube-ready **MP4** —
a **10-hour video in about 1-2 minutes**. Built for channels where people only *listen*:
the picture is static, the file is tiny, the upload is fast.

Built with **Pyrogram** + **FFmpeg** + **SQLite**. UI language: **English**.

---

## ⚡ How the Lite engine is so fast

| Step | What happens | Time (10 h video) |
|---|---|---|
| 1. Audio | MP3/AAC is **stream-copied** (no re-encode). WAV/FLAC/OGG are converted **once** to AAC. | 0 s – 1 min |
| 2. Segment | One **60 s** clip is encoded from the photo (10 fps, single keyframe) → ~70 KB | ~2 s |
| 3. Loop | The segment is looped with `-stream_loop` and **stream-copied** next to the audio | ~20 s |

Result for a 1 h MP3 looped to 10 h: **~600 MB, 1280x720, ready in ~25 s** (mostly disk I/O).
The video part is < 50 MB — the file is basically just your audio.

Measured in the sandbox (2 vCPU):

```
1h mp3 -> 10h video      23.8 s   598 MB   1280x720
1h mp3 -> 1h 1080p 1fps   2.4 s    59 MB   1920x1080
2 photos slideshow 2h     5.3 s   157 MB
title + watermark 1h      4.4 s    60 MB
```

A **Pro engine** (full re-encode, visualizer, Ken-Burns, fade, 4K) is still available in Settings.

---

## 🔐 Approval system (owner ID `6069200310`)

* New users see **📨 Request Access**. One tap sends the request to the owner.
* The owner gets a message with one-tap buttons:
  `30 min · 1 hour · 2 hours · 3 hours · 5 hours · 10 hours · 1 day · 3 days · 7 days · 30 days · ♾ Permanent · ❌ Reject · 🚫 Ban`
* The user is notified instantly, gets the full keyboard and can convert until the time runs out.
* When time expires the user is told automatically and can request again; the owner gets a note with **➕ extend** buttons.
* Owner commands: `/approve <id> [10h]`, `/extend <id> 5h`, `/reject <id>`, `/revoke <id>`, `/pending`, `/approved`, `/access <id>`.
* Admin panel (👑 button) shows pending / approved lists with inline management.

Set `ACCESS_REQUIRED=false` to make the bot public.

---

## ✨ Features

* ⏱ **Duration menu** – same as audio / 30 min / 1 h / 2 h / 3 h / 5 h / 8 h / 10 h / 12 h / custom (`4h30m`). Longer than the audio → audio is looped seamlessly.
* 🖼 Single photo · 2-20 photo **slideshow** · looping **video background**
* 📐 480p → 4K, all aspect ratios, blur / crop / pad / stretch fit
* 🎞 FPS 1-30 in Lite mode (1 fps = smallest possible file)
* 🎵 Audio copy or AAC 64-320k / MP3 (auto-lowered to stay under Telegram's 2 GB cap)
* 💧 Watermark & 🔤 Title text (work in Lite mode too)
* ⚡ Quick Modes: Lite 720p · Lite 1080p · Tiniest file · YouTube Pro · Shorts · Music Video · Podcast · 4K
* 🎛 Presets, live progress with ETA, cancel button, job queue
* 👑 Admin: stats, server info, broadcast, ban/unban, cleanup

---

## 🚀 Setup

```bash
git clone <repo> && cd <repo>
cp .env.example .env        # fill API_ID, API_HASH, BOT_TOKEN (OWNER_ID defaults to 6069200310)
pip install -r requirements.txt
sudo apt install ffmpeg fonts-dejavu-core
python bot.py
```

**Docker:** `cp .env.example .env && docker compose up -d --build`

**Kaggle / Colab:** add `API_ID`, `API_HASH`, `BOT_TOKEN` as secrets, then
`!apt-get -qq install -y ffmpeg fonts-dejavu-core && pip -q install -r requirements.txt && python bot.py`

> The owner must press **/start** in the bot once so it can send them access requests.

---

## 📋 Commands

**User:** `/start` `/convert` `/duration [10h]` `/request` `/myaccess` `/settings` `/quick` `/presets` `/files` `/clear` `/cancel` `/stats` `/history` `/help` `/about` `/ping`

**Owner / admin:** `/admin` `/pending` `/approved` `/approve <id> [duration]` `/extend <id> <duration>` `/reject <id>` `/revoke <id>` `/access <id>` `/broadcast` `/ban` `/unban` `/premium` `/users` `/server`

---

## 🗂 Project structure
```
bot.py                 # entry point, command registration, background tasks
core/
  config.py            # env config (owner, approval, limits, lite engine)
  database.py          # aiosqlite layer (users/settings/presets/access/history)
  engine.py            # Pro FFmpeg render + progress runner
  lite_engine.py       # ⚡ loop-copy engine (segment → stream-copy loop)
  keyboards.py         # reply keyboard + inline menus + approval buttons
  state.py             # per-user sessions, job registry, cancel
  helpers.py           # access gate, force-sub, files panel, duration parser
  strings.py           # UI texts (English)
  utils.py             # ffprobe, progress bar, formatting, cleanup
plugins/
  start.py             # /start /help /stats + reply-button router
  access.py            # 🔐 request / approve / extend / revoke / expiry watcher
  media.py             # photo / album / audio / voice / video / document intake
  convert.py           # pipeline (queue → lite|pro render → upload → log)
  settings.py          # settings menus, duration menu, quick modes, presets
  admin.py             # admin panel & moderation
```

## 📄 License
MIT
