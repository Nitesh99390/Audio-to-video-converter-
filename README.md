# 🎬 Audio → Video Telegram Bot (Lite engine + Approval system)

Private Telegram bot that turns **Audio + Photo** into a light, YouTube-ready **MP4** —
a **10-hour video in about 1-2 minutes**. Built for channels where people only *listen*:
the picture is static, the file is tiny, the upload is fast.
Optionally add a short **intro** and **outro** clip: `[ intro ] + [ photo + audio ] + [ outro ]`.

**How it works (in the bot)**

1. Send an intro video *(optional)*
2. Send a photo
3. Send an outro video *(optional)*
4. Send an audio file
5. Tap **🎬 Convert Now**

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

A **Pro engine** (full re-encode, visualizer, Ken-Burns, fade, 4K) exists as well — **admins only**
(`PRO_ENGINE_ADMIN_ONLY=true`). Every other approved user gets Lite; Pro options are never shown to them
and any stored Pro setting is silently downgraded before rendering.

---

## 🎬 Intro / Outro (no re-encode of the long part)

| Step | What happens | Time |
|---|---|---|
| 1. Normalize | Each clip (≤ 5 min) is re-encoded **once** to the main video's exact size / fps / codec / audio format. Clips without sound get a silent track. Nothing is cropped — black bars are added. | a few seconds |
| 2. Join | `concat` demuxer joins `intro + main + outro` with `-c copy` | disk speed |
| 3. Fallback | If the main audio codec cannot be matched (e.g. FLAC), the main **audio** is re-packed to AAC once (video still copied) and the join is retried | ~1x audio length |

Measured: 10 min lite video + 4 s intro + 3 s outro → joined in **2.6 s**.

* The **first** video a user sends becomes the intro, the **second** the outro. A video longer than
  `INTRO_OUTRO_AUTO_SEC` (90 s) sent while no photo is set is treated as a background loop.
* Under every received clip: `🎬 Intro · 🏁 Outro · 🎥 Background · 🗑 Remove` — one tap moves it (slots swap).
* The files panel shows the order (`intro → photo + audio → outro`), a `🔃 Swap` button and per-slot remove buttons.
* **⏱ Duration** applies to the main part; intro/outro length is added on top.

---

## 🧭 UI philosophy — show only what is needed

* Bottom keyboard: **2 rows** for users (`🎬 Convert Now · ⏱ Duration` / `⚙️ Settings · 📂 My Files · ❓ Help`),
  admins get one extra `👑 Admin` row. Everything else is reachable from inline menus.
* **Settings is tiered:** the main panel has Length · Resolution · Aspect · FPS · Audio.
  `🔧 Advanced` holds fit / quality / codec / watermark / title / caption / thumbnail / reset.
  `✨ Effects` (visualizer, Ken-Burns, fade) appears only for admins who switched to Pro.
* Buttons the user cannot use (Pro engine, Pro quick modes, 4K, 60 fps, transitions) are **not rendered**.
* Owner approval message shows 6 common durations + `⋯ More` instead of 11 buttons at once.
* The `/` command menu lists 8 commands for users; admin commands are registered for admins only.

---

## 🗄 Disk guard (Kaggle / Colab safe)

Kaggle gives ~20 GB of scratch space and the kernel dies when it is full, so nothing is ever left behind:

| When | What |
|---|---|
| Startup / shutdown | `downloads/` is purged completely (sessions live in RAM, leftovers are garbage) |
| Before **every** download | `ensure_space(file_size)` – sweeps, then evicts other idle uploads if needed; refuses politely if still no room |
| Before **every** render | output size is estimated (audio bitrate × length + video + temps) and space is reserved the same way |
| Right after upload | output, thumbnail, merged / looped audio and all temps are deleted immediately |
| Every 3 min (watchdog) | orphan & temp files > 10 min, uploads idle > 45 min, quota (`MAX_STORAGE_MB`) enforced oldest-first |
| Free disk < `MIN_FREE_MB` | emergency eviction of everything not owned by a *running* job |

Files of running jobs are registered in `state` and are never touched. Admin: `/storage` shows the breakdown,
`/cleanup` (or 👑 Admin → 🧹 Clean now) frees everything idle right away.

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
* 🎬 **Intro + 🏁 Outro** clips joined by stream copy — the long main video is never re-encoded
* 📐 480p → 4K, all aspect ratios, blur / crop / pad / stretch fit
* 🎞 FPS 1-30 in Lite mode (1 fps = smallest possible file)
* 🔐 Pro engine locked to admins; users only ever see Lite options
* 🗄 Disk guard – auto-clean, quota, emergency eviction, never fills a Kaggle disk
* 🎵 Audio copy or AAC 64-320k / MP3 (auto-lowered to stay under Telegram's 2 GB cap)
* 💧 Watermark & 🔤 Title text (work in Lite mode too)
* ⚡ Quick Modes: Fast 720p · Fast 1080p · Smallest file · Vertical 9:16 (+ Pro profiles for admins)
* 🎛 Presets, live progress with ETA, cancel button, job queue
* 👑 Admin: stats, server & storage info, broadcast, ban/unban, one-tap cleanup

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

**User (in the `/` menu):** `/start` `/convert` `/duration [10h]` `/settings` `/files` `/cancel` `/myaccess` `/help`
(also work: `/quick` `/presets` `/clear` `/stats` `/history` `/about` `/request` `/ping`)

**Owner / admin:** `/admin` `/pending` `/approved` `/approve <id> [duration]` `/extend <id> <duration>` `/reject <id>` `/revoke <id>` `/access <id>` `/broadcast` `/storage` `/cleanup` `/server` `/users` `/ban` `/unban` `/premium`

---

## 🗂 Project structure
```
bot.py                 # entry point, command registration, background tasks
core/
  config.py            # env config (owner, approval, limits, policy, storage guard)
  policy.py            # who may use what (Pro engine = admins only) + settings downgrade
  storage.py           # 🗄 disk guard: purge / sweep / quota / emergency eviction / ensure_space
  database.py          # aiosqlite layer (users/settings/presets/access/history)
  engine.py            # Pro FFmpeg render + progress runner
  lite_engine.py       # ⚡ loop-copy engine (segment → stream-copy loop)
  intro_outro.py       # 🎬 normalize intro/outro clips once → concat stream-copy (AAC fallback)
  keyboards.py         # minimal reply keyboard + tiered inline menus (Settings / Advanced / Effects)
  state.py             # per-user sessions, job registry, cancel
  helpers.py           # access gate, force-sub, files panel, duration parser
  strings.py           # UI texts (English)
  utils.py             # ffprobe, progress bar, formatting, cleanup
plugins/
  start.py             # /start /help /stats + reply-button router
  access.py            # 🔐 request / approve / extend / revoke / expiry watcher
  media.py             # photo / album / audio / voice / video (intro / outro / background) / document intake
  convert.py           # pipeline (queue → lite|pro render → upload → log)
  settings.py          # settings menus, duration menu, quick modes, presets
  admin.py             # admin panel & moderation
```

## 📄 License
MIT
