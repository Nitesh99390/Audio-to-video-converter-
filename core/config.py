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


class Config:
    # ---- Telegram credentials (REQUIRED) ----
    API_ID: int = _int("API_ID", 0)
    API_HASH: str = os.environ.get("API_HASH", "")
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

    # ---- Admin / owner ----
    OWNER_ID: int = _int("OWNER_ID", 0)
    ADMINS: set = {
        int(x) for x in os.environ.get("ADMINS", "").replace(",", " ").split() if x.strip().lstrip("-").isdigit()
    }
    if OWNER_ID:
        ADMINS.add(OWNER_ID)

    # ---- Optional channels ----
    LOG_CHANNEL: int = _int("LOG_CHANNEL", 0)          # send every generated video here
    FORCE_SUB_CHANNEL: str = os.environ.get("FORCE_SUB_CHANNEL", "")  # @username or -100id
    SUPPORT_LINK: str = os.environ.get("SUPPORT_LINK", "")
    UPDATES_LINK: str = os.environ.get("UPDATES_LINK", "")

    # ---- Limits ----
    MAX_FILE_SIZE_MB: int = _int("MAX_FILE_SIZE_MB", 2000)
    MAX_AUDIO_DURATION_SEC: int = _int("MAX_AUDIO_DURATION_SEC", 4 * 3600)
    MAX_CONCURRENT_TASKS: int = _int("MAX_CONCURRENT_TASKS", 3)
    MAX_SLIDESHOW_IMAGES: int = _int("MAX_SLIDESHOW_IMAGES", 20)
    DAILY_LIMIT_FREE: int = _int("DAILY_LIMIT_FREE", 30)
    FFMPEG_THREADS: int = _int("FFMPEG_THREADS", 0)  # 0 = auto

    # ---- Paths ----
    DOWNLOAD_DIR: str = os.environ.get("DOWNLOAD_DIR", "downloads")
    DB_PATH: str = os.environ.get("DB_PATH", "bot_data.db")
    SESSION_NAME: str = os.environ.get("SESSION_NAME", "advanced_audio_video_bot")

    # ---- Branding ----
    BOT_NAME: str = os.environ.get("BOT_NAME", "Advanced Audio → Video Bot")
    DEFAULT_CAPTION: str = os.environ.get("DEFAULT_CAPTION", "🎬 Made with {bot_name}")

    @classmethod
    def validate(cls) -> None:
        missing = [k for k in ("API_ID", "API_HASH", "BOT_TOKEN") if not getattr(cls, k)]
        if missing:
            logger.error("Missing required environment variables: %s", ", ".join(missing))
            logger.error("Set them as Kaggle Secrets / env vars / .env file and restart.")
            sys.exit(1)
        os.makedirs(cls.DOWNLOAD_DIR, exist_ok=True)
