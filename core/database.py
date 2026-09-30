"""
Async SQLite database layer (aiosqlite).
Stores users, per-user settings, usage stats, presets, and bans.
"""
import json
import time
import logging
from typing import Any, Dict, List, Optional

import aiosqlite

from core.config import Config

logger = logging.getLogger(__name__)

# ----- Default settings for every new user -----
DEFAULT_SETTINGS: Dict[str, Any] = {
    "resolution": "1080p",        # 480p / 720p / 1080p / 1440p / 2160p / original
    "aspect": "16:9",             # 16:9 / 9:16 / 1:1 / 4:3 / 4:5 / 21:9
    "fit": "blur",                # blur / crop / pad / stretch
    "fps": 30,                    # 24 / 25 / 30 / 60
    "quality": "high",            # low / medium / high / ultra
    "codec": "h264",              # h264 / h265
    "audio_mode": "copy",         # copy / aac128 / aac192 / aac320 / mp3
    "visualizer": "none",         # none / waves / bars / spectrum / vectorscope / cqt
    "vis_color": "white",         # white / cyan / magenta / yellow / red / green / rainbow
    "vis_position": "bottom",     # bottom / center / top
    "ken_burns": False,           # slow zoom / pan effect
    "fade": False,                # fade-in / fade-out (video + audio)
    "watermark_text": "",
    "watermark_position": "bottom_right",  # 5 positions
    "title_text": "",             # big title on video
    "title_position": "top",      # top / center / bottom
    "spoiler": False,
    "output_mode": "video",       # video (streamable) / document
    "slideshow_duration": 5,      # seconds per image
    "slideshow_transition": "fade",  # fade / none
    "loop_bg_video": True,
    "custom_caption": "",
    "thumbnail": "auto",          # auto / photo / none
    "language": "hi",             # hi / en
}

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    joined_at REAL,
    last_seen REAL,
    is_banned INTEGER DEFAULT 0,
    is_premium INTEGER DEFAULT 0,
    total_videos INTEGER DEFAULT 0,
    total_bytes INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER PRIMARY KEY,
    data TEXT
);
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    data TEXT,
    UNIQUE(user_id, name)
);
CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER,
    day TEXT,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS stats (
    key TEXT PRIMARY KEY,
    value INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    created_at REAL,
    mode TEXT,
    duration REAL,
    size INTEGER,
    render_time REAL,
    settings TEXT
);
"""


class Database:
    def __init__(self, path: str = Config.DB_PATH):
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(CREATE_SQL)
        await self._db.commit()
        logger.info("Database ready at %s", self.path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ------------------------------------------------------------ users
    async def add_user(self, user) -> bool:
        """Insert or refresh a user. Returns True if newly created."""
        now = time.time()
        cur = await self._db.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,))
        exists = await cur.fetchone()
        if exists:
            await self._db.execute(
                "UPDATE users SET first_name=?, username=?, last_seen=? WHERE user_id=?",
                (user.first_name, user.username, now, user.id),
            )
            await self._db.commit()
            return False
        await self._db.execute(
            "INSERT INTO users (user_id, first_name, username, joined_at, last_seen) VALUES (?,?,?,?,?)",
            (user.id, user.first_name, user.username, now, now),
        )
        await self._db.commit()
        return True

    async def get_user(self, user_id: int) -> Optional[dict]:
        cur = await self._db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def all_user_ids(self) -> List[int]:
        cur = await self._db.execute("SELECT user_id FROM users WHERE is_banned=0")
        return [r[0] for r in await cur.fetchall()]

    async def total_users(self) -> int:
        cur = await self._db.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]

    async def set_ban(self, user_id: int, banned: bool) -> None:
        await self._db.execute("UPDATE users SET is_banned=? WHERE user_id=?", (int(banned), user_id))
        await self._db.commit()

    async def is_banned(self, user_id: int) -> bool:
        cur = await self._db.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return bool(row and row[0])

    async def set_premium(self, user_id: int, premium: bool) -> None:
        await self._db.execute("UPDATE users SET is_premium=? WHERE user_id=?", (int(premium), user_id))
        await self._db.commit()

    async def is_premium(self, user_id: int) -> bool:
        cur = await self._db.execute("SELECT is_premium FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return bool(row and row[0])

    # --------------------------------------------------------- settings
    async def get_settings(self, user_id: int) -> Dict[str, Any]:
        cur = await self._db.execute("SELECT data FROM settings WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        data = dict(DEFAULT_SETTINGS)
        if row:
            try:
                data.update(json.loads(row[0]))
            except json.JSONDecodeError:
                pass
        return data

    async def save_settings(self, user_id: int, data: Dict[str, Any]) -> None:
        await self._db.execute(
            "INSERT INTO settings (user_id, data) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
            (user_id, json.dumps(data)),
        )
        await self._db.commit()

    async def update_setting(self, user_id: int, key: str, value: Any) -> Dict[str, Any]:
        data = await self.get_settings(user_id)
        data[key] = value
        await self.save_settings(user_id, data)
        return data

    async def reset_settings(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM settings WHERE user_id=?", (user_id,))
        await self._db.commit()

    # ---------------------------------------------------------- presets
    async def save_preset(self, user_id: int, name: str, data: Dict[str, Any]) -> None:
        await self._db.execute(
            "INSERT INTO presets (user_id, name, data) VALUES (?,?,?) "
            "ON CONFLICT(user_id, name) DO UPDATE SET data=excluded.data",
            (user_id, name, json.dumps(data)),
        )
        await self._db.commit()

    async def list_presets(self, user_id: int) -> List[str]:
        cur = await self._db.execute("SELECT name FROM presets WHERE user_id=? ORDER BY name", (user_id,))
        return [r[0] for r in await cur.fetchall()]

    async def get_preset(self, user_id: int, name: str) -> Optional[Dict[str, Any]]:
        cur = await self._db.execute("SELECT data FROM presets WHERE user_id=? AND name=?", (user_id, name))
        row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def delete_preset(self, user_id: int, name: str) -> None:
        await self._db.execute("DELETE FROM presets WHERE user_id=? AND name=?", (user_id, name))
        await self._db.commit()

    # ------------------------------------------------------- usage/stats
    async def today_usage(self, user_id: int) -> int:
        day = time.strftime("%Y-%m-%d")
        cur = await self._db.execute("SELECT count FROM usage WHERE user_id=? AND day=?", (user_id, day))
        row = await cur.fetchone()
        return row[0] if row else 0

    async def increment_usage(self, user_id: int) -> None:
        day = time.strftime("%Y-%m-%d")
        await self._db.execute(
            "INSERT INTO usage (user_id, day, count) VALUES (?,?,1) "
            "ON CONFLICT(user_id, day) DO UPDATE SET count=count+1",
            (user_id, day),
        )
        await self._db.commit()

    async def record_video(self, user_id: int, mode: str, duration: float, size: int,
                           render_time: float, settings: Dict[str, Any]) -> None:
        await self._db.execute(
            "UPDATE users SET total_videos=total_videos+1, total_bytes=total_bytes+? WHERE user_id=?",
            (size, user_id),
        )
        await self._db.execute(
            "INSERT INTO history (user_id, created_at, mode, duration, size, render_time, settings) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, time.time(), mode, duration, size, render_time, json.dumps(settings)),
        )
        for key, inc in (("total_videos", 1), ("total_bytes", size), ("total_render_time", int(render_time))):
            await self._db.execute(
                "INSERT INTO stats (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value",
                (key, inc),
            )
        await self._db.commit()
        await self.increment_usage(user_id)

    async def global_stats(self) -> Dict[str, int]:
        cur = await self._db.execute("SELECT key, value FROM stats")
        out = {r[0]: r[1] for r in await cur.fetchall()}
        out["total_users"] = await self.total_users()
        cur = await self._db.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
        out["banned_users"] = (await cur.fetchone())[0]
        cur = await self._db.execute("SELECT COUNT(*) FROM users WHERE is_premium=1")
        out["premium_users"] = (await cur.fetchone())[0]
        cur = await self._db.execute("SELECT COUNT(*) FROM users WHERE last_seen > ?", (time.time() - 86400,))
        out["active_24h"] = (await cur.fetchone())[0]
        return out

    async def user_history(self, user_id: int, limit: int = 5) -> List[dict]:
        cur = await self._db.execute(
            "SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit)
        )
        return [dict(r) for r in await cur.fetchall()]


db = Database()
