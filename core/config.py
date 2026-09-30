"""
Central configuration. Values are read from environment variables
(Kaggle Secrets / Docker env / .env file).
"""
import os
import sys
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional
    pass

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger("AudioVideoBot")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # ---- Telegram credentials (REQUIRED) ----
    API_ID: int = _int("API_ID", 0)
    API_HASH: str = os.environ.get("API_HASH", "")
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

    # ---- Admin / owner ----
    # The owner receives every access request and can approve / reject it.
    OWNER_ID: int = _int("OWNER_ID", 6069200310)
    ADMINS: set = {
        int(x) for x in os.environ.get("ADMINS", "").replace(",", " ").split() if x.strip().lstrip("-").isdigit()
    }
    if OWNER_ID:
        ADMINS.add(OWNER_ID)

    # ---- Access / approval system ----
    # When ON, every non-admin user must be approved by the owner before using the bot.
    ACCESS_REQUIRED: bool = _bool("ACCESS_REQUIRED", True)
    # Minutes a user has to wait before sending another request after a rejection / expiry.
    REQUEST_COOLDOWN_MIN: int = _int("REQUEST_COOLDOWN_MIN", 10)

    # ---- Optional channels ----
    LOG_CHANNEL: int = _int("LOG_CHANNEL", 0)          # send every generated video here
    FORCE_SUB_CHANNEL: str = os.environ.get("FORCE_SUB_CHANNEL", "")  # @username or -100id
    SUPPORT_LINK: str = os.environ.get("SUPPORT_LINK", "")
    UPDATES_LINK: str = os.environ.get("UPDATES_LINK", "")

    # ---- Limits ----
    MAX_FILE_SIZE_MB: int = _int("MAX_FILE_SIZE_MB", 2000)
    MAX_AUDIO_DURATION_SEC: int = _int("MAX_AUDIO_DURATION_SEC", 24 * 3600)
    MAX_OUTPUT_DURATION_SEC: int = _int("MAX_OUTPUT_DURATION_SEC", 24 * 3600)
    MAX_OUTPUT_SIZE_MB: int = _int("MAX_OUTPUT_SIZE_MB", 1950)   # Telegram bot upload cap (~2 GB)
    MAX_CONCURRENT_TASKS: int = _int("MAX_CONCURRENT_TASKS", 2)
    MAX_SLIDESHOW_IMAGES: int = _int("MAX_SLIDESHOW_IMAGES", 20)
    DAILY_LIMIT_FREE: int = _int("DAILY_LIMIT_FREE", 0)          # 0 = unlimited (approval is the gate)
    FFMPEG_THREADS: int = _int("FFMPEG_THREADS", 0)  # 0 = auto

    # ---- Feature policy ----
    # Pro engine (full re-encode, visualizer, effects, 4K) is heavy. Only admins may use it;
    # everybody else gets the Lite engine. Set to false to open Pro for all approved users.
    PRO_ENGINE_ADMIN_ONLY: bool = _bool("PRO_ENGINE_ADMIN_ONLY", True)

    # ---- Storage guard (Kaggle / Colab have ~20 GB and crash when full) ----
    MAX_STORAGE_MB: int = _int("MAX_STORAGE_MB", 6000)        # quota for the work folder
    MIN_FREE_MB: int = _int("MIN_FREE_MB", 1500)              # always keep this much disk free
    SESSION_TTL_SEC: int = _int("SESSION_TTL_SEC", 45 * 60)   # idle uploads are deleted after this
    ORPHAN_TTL_SEC: int = _int("ORPHAN_TTL_SEC", 10 * 60)     # files not owned by anyone
    CLEANUP_INTERVAL_SEC: int = _int("CLEANUP_INTERVAL_SEC", 180)

    # ---- Lite (fast) engine ----
    # Length of the pre-rendered video segment that gets loop-copied to the full duration.
    LITE_SEGMENT_SEC: int = _int("LITE_SEGMENT_SEC", 60)
    # Max seconds of a background video that will be re-encoded for the loop segment.
    LITE_MAX_BG_VIDEO_SEC: int = _int("LITE_MAX_BG_VIDEO_SEC", 600)

    # ---- Intro / Outro ----
    # Short clips attached before / after the main video. They are re-encoded once to match the
    # main video exactly and then joined by stream copy (no re-encode of the long part).
    MAX_INTRO_OUTRO_SEC: int = _int("MAX_INTRO_OUTRO_SEC", 300)
    # A video shorter than this is treated as an intro/outro candidate, longer ones as background loop.
    INTRO_OUTRO_AUTO_SEC: int = _int("INTRO_OUTRO_AUTO_SEC", 90)

    # ---- Paths ----
    DOWNLOAD_DIR: str = os.environ.get("DOWNLOAD_DIR", "downloads")
    DB_PATH: str = os.environ.get("DB_PATH", "bot_data.db")
    SESSION_NAME: str = os.environ.get("SESSION_NAME", "advanced_audio_video_bot")

    # ---- Branding ----
    BOT_NAME: str = os.environ.get("BOT_NAME", "Audio → Video Bot")
    DEFAULT_CAPTION: str = os.environ.get("DEFAULT_CAPTION", "🎬 Made with {bot_name}")

    @classmethod
    def validate(cls) -> None:
        missing = [k for k in ("API_ID", "API_HASH", "BOT_TOKEN") if not getattr(cls, k)]
        if missing:
            logger.error("Missing required environment variables: %s", ", ".join(missing))
            logger.error("Set them as Kaggle Secrets / env vars / .env file and restart.")
            sys.exit(1)
        os.makedirs(cls.DOWNLOAD_DIR, exist_ok=True)
