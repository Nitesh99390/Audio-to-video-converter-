"""Utility helpers: formatting, progress bars, ffprobe, filesystem."""
import asyncio
import json
import math
import os
import shutil
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


# ------------------------------------------------------------ formatting
def humanbytes(size: float) -> str:
    if not size:
        return "0 B"
    power = 1024
    n = 0
    units = ["B", "KB", "MB", "GB", "TB"]
    while size >= power and n < len(units) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def format_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def progress_bar_str(percent: float, length: int = 12) -> str:
    filled = int(length * percent / 100)
    return "█" * filled + "░" * (length - filled)


def safe_filename(name: str, default: str = "file") -> str:
    keep = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    cleaned = "".join(c for c in (name or "") if c in keep).strip()
    return cleaned[:60] or default


# ------------------------------------------------------- progress callback
class Throttle:
    """Per-message throttle so we don't hit Telegram flood limits."""
    def __init__(self, interval: float = 4.0):
        self.interval = interval
        self.last = 0.0

    def ready(self) -> bool:
        now = time.time()
        if now - self.last >= self.interval:
            self.last = now
            return True
        return False


async def progress_callback(current: int, total: int, status_msg, action: str,
                            start_time: float, throttle: Throttle, cancel_markup=None):
    """Pyrogram-compatible progress callback with ETA + speed."""
    if current != total and not throttle.ready():
        return
    try:
        elapsed = max(time.time() - start_time, 0.001)
        percent = current * 100 / total if total else 0
        speed = current / elapsed
        eta = (total - current) / speed if speed > 0 else 0
        text = (
            f"**{action}**\n\n"
            f"`[{progress_bar_str(percent)}]` **{percent:.1f}%**\n\n"
            f"📦 {humanbytes(current)} / {humanbytes(total)}\n"
            f"⚡ Speed: {humanbytes(speed)}/s\n"
            f"⏱ ETA: {format_time(eta)}"
        )
        await status_msg.edit_text(text, reply_markup=cancel_markup)
    except Exception:
        pass


# ------------------------------------------------------------- ffprobe
async def run_cmd(cmd: list, timeout: Optional[float] = None) -> tuple:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")


async def ffprobe(path: str) -> Dict[str, Any]:
    """Return {'duration', 'width', 'height', 'audio_codec', 'video_codec', 'bitrate', 'sample_rate'}."""
    info: Dict[str, Any] = {"duration": 0.0, "width": 0, "height": 0, "audio_codec": None,
                            "video_codec": None, "bitrate": 0, "sample_rate": 0, "has_audio": False,
                            "has_video": False, "title": None, "artist": None}
    try:
        code, out, _ = await run_cmd([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path
        ], timeout=60)
        if code != 0:
            return info
        data = json.loads(out or "{}")
        fmt = data.get("format", {})
        info["duration"] = float(fmt.get("duration") or 0)
        info["bitrate"] = int(fmt.get("bit_rate") or 0)
        tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
        info["title"] = tags.get("title")
        info["artist"] = tags.get("artist")
        for s in data.get("streams", []):
            if s.get("codec_type") == "audio" and not info["has_audio"]:
                info["has_audio"] = True
                info["audio_codec"] = s.get("codec_name")
                info["sample_rate"] = int(s.get("sample_rate") or 0)
                if not info["duration"] and s.get("duration"):
                    info["duration"] = float(s["duration"])
            elif s.get("codec_type") == "video":
                # skip embedded cover art
                if s.get("disposition", {}).get("attached_pic"):
                    continue
                info["has_video"] = True
                info["video_codec"] = s.get("codec_name")
                info["width"] = int(s.get("width") or 0)
                info["height"] = int(s.get("height") or 0)
    except Exception as e:
        logger.warning("ffprobe failed for %s: %s", path, e)
    return info


async def extract_cover_art(audio_path: str, out_path: str) -> Optional[str]:
    """Extract embedded album art from an audio file, if present."""
    try:
        code, _, _ = await run_cmd(
            ["ffmpeg", "-y", "-v", "quiet", "-i", audio_path, "-an", "-vcodec", "copy", out_path],
            timeout=60,
        )
        if code == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            return out_path
    except Exception:
        pass
    if os.path.exists(out_path):
        os.remove(out_path)
    return None


async def make_thumbnail(video_path: str, out_path: str, at: float = 1.0) -> Optional[str]:
    try:
        code, _, _ = await run_cmd(
            ["ffmpeg", "-y", "-v", "quiet", "-ss", str(at), "-i", video_path,
             "-vframes", "1", "-vf", "scale=320:-2", out_path],
            timeout=60,
        )
        if code == 0 and os.path.exists(out_path):
            return out_path
    except Exception:
        pass
    return None


# ---------------------------------------------------------- filesystem
def cleanup(*paths):
    for p in paths:
        if not p:
            continue
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def disk_free(path: str = ".") -> int:
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return 0


def ceil_even(n: float) -> int:
    """FFmpeg h264 requires even dimensions."""
    n = int(math.ceil(n))
    return n if n % 2 == 0 else n + 1
