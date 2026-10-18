"""
3D / 8D spatial audio (FFmpeg only, no extra deps — runs fine on Kaggle CPU).

  8D  – the sound slowly circles around the head (apulsator) + room echo + wide stereo.
  3D  – wide, "outside the headphones" stereo (haas / extrastereo / stereowiden) + soft echo,
        no rotation.

The processed track is written once as AAC (stereo, 44.1 kHz). It can be sent as an
audio file directly, or fed into the normal photo+audio video pipeline (the lite engine
then stream-copies it, so a 8D video costs the same as a normal one).
"""
from typing import List, Optional

MODES = {
    "8d": {"label": "🎧 8D", "desc": "sound circles around your head"},
    "3d": {"label": "🌀 3D", "desc": "wide surround stereo"},
}

# one full rotation every 8 s (hz=0.125) — the classic 8D feel
FILTER_8D = (
    "aformat=channel_layouts=stereo,"
    "apulsator=hz=0.125:amount=1:width=1,"
    "aecho=0.8:0.88:60:0.4,"
    "stereowiden=delay=20:feedback=0.3:crossfeed=0.3:drymix=0.8,"
    "alimiter=limit=0.95"
)
FILTER_3D = (
    "aformat=channel_layouts=stereo,"
    "extrastereo=m=1.8,"
    "haas=middle_source=mid,"
    "stereowiden=delay=18:feedback=0.35:crossfeed=0.4:drymix=0.7,"
    "aecho=0.8:0.85:40|70:0.25|0.2,"
    "alimiter=limit=0.95"
)
FILTERS = {"8d": FILTER_8D, "3d": FILTER_3D}


def label(mode: Optional[str]) -> str:
    return MODES.get(mode or "", {}).get("label", "")


def build_command(src: str, dst: str, mode: str, kbps: int = 192, ext: str = "m4a") -> List[str]:
    """ffmpeg command that writes the spatial track (progress on stdout for engine.render)."""
    codec = ["-c:a", "libmp3lame"] if ext == "mp3" else ["-c:a", "aac", "-movflags", "+faststart"]
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
            "-i", src, "-vn", "-map", "0:a:0", "-af", FILTERS[mode],
            *codec, "-b:a", f"{kbps}k", "-ac", "2", "-ar", "44100", dst]
