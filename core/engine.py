"""
FFmpeg rendering engine.

Builds a single FFmpeg command from user settings and renders:
  • single image + audio
  • slideshow (many images) + audio
  • looping background video + audio
with optional visualizer overlay, Ken-Burns motion, fade, watermark, title.

Progress is parsed from `-progress pipe:1` and reported via a callback.
"""
import asyncio
import glob
import logging
import os
import re
import time
from typing import Awaitable, Callable, Dict, List, Optional

from core.config import Config
from core.utils import ceil_even, run_cmd

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ tables
RESOLUTION_HEIGHT = {"480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}

ASPECT_RATIO = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "4:5": 4 / 5, "21:9": 21 / 9}

# CRF values (lower = better)
QUALITY_CRF = {"h264": {"low": 30, "medium": 25, "high": 20, "ultra": 17},
               "h265": {"low": 32, "medium": 28, "high": 24, "ultra": 20}}
QUALITY_PRESET = {"low": "ultrafast", "medium": "veryfast", "high": "fast", "ultra": "medium"}

COLORS = {
    "white": "white", "cyan": "0x00FFFF", "magenta": "0xFF00FF", "yellow": "0xFFFF00",
    "red": "0xFF3B30", "green": "0x34C759", "orange": "0xFF9500",
    "rainbow": "0xFF0000|0xFF7F00|0xFFFF00|0x00FF00|0x0000FF|0x4B0082|0x9400D3",
}

AUDIO_ARGS = {
    "copy": ["-c:a", "copy"],
    "aac128": ["-c:a", "aac", "-b:a", "128k"],
    "aac192": ["-c:a", "aac", "-b:a", "192k"],
    "aac320": ["-c:a", "aac", "-b:a", "320k"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
}
# codecs that can be stream-copied into MP4 safely
MP4_COPY_SAFE = {"aac", "mp3", "alac", "ac3", "eac3", "opus", "flac"}

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def find_font() -> Optional[str]:
    for f in _FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    hits = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    return hits[0] if hits else None


FONT = find_font()


def write_textfile(text: str, path: str) -> str:
    """drawtext escaping is fragile; write text to a file and use textfile= instead."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace("\r", "").strip())
    return path


class RenderError(Exception):
    pass


class RenderPlan:
    """Resolved parameters for a render."""

    def __init__(self, settings: Dict, src_w: int, src_h: int):
        self.s = settings
        self.codec = settings.get("codec", "h264")
        self.fps = int(settings.get("fps", 30))
        self.quality = settings.get("quality", "high")
        self.width, self.height = self._dimensions(src_w, src_h)

    def _dimensions(self, src_w: int, src_h: int):
        res = self.s.get("resolution", "1080p")
        aspect = self.s.get("aspect", "16:9")
        if res == "original" and src_w and src_h:
            # keep source ratio, cap at 2160 height
            h = min(src_h, 2160)
            w = src_w * h / src_h
            return ceil_even(w), ceil_even(h)
        ratio = ASPECT_RATIO.get(aspect, 16 / 9)
        h = RESOLUTION_HEIGHT.get(res, 1080)
        # for portrait, "1080p" means width 1080
        if ratio < 1:
            w = h
            h = w / ratio
        else:
            w = h * ratio
        return ceil_even(w), ceil_even(h)

    @property
    def crf(self) -> int:
        return QUALITY_CRF[self.codec][self.quality]

    @property
    def preset(self) -> str:
        return QUALITY_PRESET[self.quality]


# ------------------------------------------------------------------ builder
def _fit_filter(w: int, h: int, fit: str, fps: int) -> str:
    """Scale an input to exactly w×h using selected fit mode. Output label [bg]."""
    if fit == "stretch":
        return f"scale={w}:{h}:flags=lanczos,setsar=1"
    if fit == "crop":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1"
    if fit == "pad":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    # blur (default): blurred, zoomed copy behind sharp fitted image
    return (
        f"split=2[bgsrc][fgsrc];"
        f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"boxblur=luma_radius=min(h\\,w)/20:luma_power=1:chroma_radius=min(cw\\,ch)/20:chroma_power=1,"
        f"eq=brightness=-0.08[bgblur];"
        f"[fgsrc]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
        f"[bgblur][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )


def _ken_burns(w: int, h: int, fps: int, duration: float) -> str:
    """Slow zoom-in over the duration."""
    frames = max(int(duration * fps), 1)
    # zoom from 1.0 to 1.15 across the whole clip, centered
    return (f"scale={w * 2}:{h * 2},zoompan=z='min(1+0.15*on/{frames},1.15)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}")


def _visualizer(kind: str, w: int, h: int, fps: int, color: str) -> Optional[str]:
    """Return an audio→video filter producing [vis] of size vw×vh."""
    col = COLORS.get(color, "white")
    vh = h // 4
    if kind == "waves":
        return f"showwaves=s={w}x{vh}:mode=cline:colors={col}:rate={fps}:scale=sqrt,format=rgba"
    if kind == "bars":
        return (f"showfreqs=s={w}x{vh}:mode=bar:ascale=sqrt:fscale=log:win_size=1024:"
                f"colors={col}:rate={fps},format=rgba")
    if kind == "spectrum":
        return (f"showspectrum=s={w}x{vh}:mode=combined:color=intensity:scale=cbrt:"
                f"slide=scroll:fps={fps},format=rgba")
    if kind == "cqt":
        return f"showcqt=s={w}x{vh}:fps={fps}:bar_g=2:sono_g=4:bar_v=9:sono_v=17:axis=0,format=rgba"
    if kind == "vectorscope":
        side = min(w, h) // 2
        return f"avectorscope=s={side}x{side}:mode=lissajous_xy:draw=line:rate={fps}:zoom=1.5,format=rgba"
    if kind == "circle":
        side = min(w, h) // 2
        return f"avectorscope=s={side}x{side}:mode=polar:draw=dot:rate={fps}:zoom=2,format=rgba"
    return None


def _vis_overlay_pos(position: str) -> str:
    if position == "top":
        return "x=(W-w)/2:y=0"
    if position == "center":
        return "x=(W-w)/2:y=(H-h)/2"
    return "x=(W-w)/2:y=H-h"


def _drawtext(textfile: str, position: str, w: int, h: int, size: int, box: bool = True) -> str:
    if not FONT or not textfile:
        return ""
    pos_map = {
        "top_left": "x=20:y=20", "top_right": "x=w-tw-20:y=20",
        "center": "x=(w-tw)/2:y=(h-th)/2",
        "bottom_left": "x=20:y=h-th-20", "bottom_right": "x=w-tw-20:y=h-th-20",
        "top": "x=(w-tw)/2:y=h*0.06", "bottom": "x=(w-tw)/2:y=h-th-h*0.06",
    }
    pos = pos_map.get(position, "x=w-tw-20:y=h-th-20")
    boxpart = ":box=1:boxcolor=black@0.45:boxborderw=12" if box else ":shadowcolor=black@0.7:shadowx=2:shadowy=2"
    return (f"drawtext=fontfile={FONT}:textfile={textfile}:fontsize={size}:fontcolor=white@0.92:"
            f"{pos}{boxpart}")


def build_command(
    plan: RenderPlan,
    images: List[str],
    audio: str,
    output: str,
    duration: float,
    audio_codec: Optional[str],
    bg_video: Optional[str] = None,
) -> List[str]:
    s = plan.s
    w, h, fps = plan.width, plan.height, plan.fps
    filters: List[str] = []
    inputs: List[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    if Config.FFMPEG_THREADS:
        inputs += ["-threads", str(Config.FFMPEG_THREADS)]

    slideshow = len(images) > 1
    per_image = float(s.get("slideshow_duration", 5))
    transition = s.get("slideshow_transition", "fade")
    fade_dur = 0.8 if transition == "fade" else 0.0

    # ----------------------------------------------------- video inputs
    if bg_video:
        inputs += ["-stream_loop", "-1", "-i", bg_video]
        filters.append(f"[0:v]{_fit_filter(w, h, s.get('fit', 'blur'), fps)},fps={fps},format=yuv420p[base]")
        video_input_count = 1
    elif slideshow:
        # each image shown `per_image` seconds; loop the set until audio ends
        n = len(images)
        step = max(per_image - fade_dur, 0.5)          # effective seconds each image adds
        needed = int(duration / step) + 2               # enough segments to outlast the audio
        needed = min(max(needed, n), Config.MAX_SLIDESHOW_IMAGES * 6)  # cap filter-graph size
        seq = [images[i % n] for i in range(needed)]
        for img in seq:
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", str(per_image), "-i", img]
        video_input_count = len(seq)
        fit = s.get("fit", "blur")
        labels = []
        for i in range(video_input_count):
            filters.append(f"[{i}:v]{_fit_filter(w, h, fit, fps)},format=yuv420p,fps={fps}[s{i}]")
            labels.append(f"[s{i}]")
        if fade_dur and video_input_count > 1:
            prev = "[s0]"
            offset = per_image - fade_dur
            for i in range(1, video_input_count):
                out = "[base]" if i == video_input_count - 1 else f"[x{i}]"
                filters.append(f"{prev}[s{i}]xfade=transition=fade:duration={fade_dur}:offset={offset:.3f}{out}")
                prev = out
                offset += per_image - fade_dur
        else:
            filters.append("".join(labels) + f"concat=n={video_input_count}:v=1:a=0[base]")
    else:
        img = images[0]
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", img]
        video_input_count = 1
        chain = _fit_filter(w, h, s.get("fit", "blur"), fps)
        if s.get("ken_burns"):
            chain += "," + _ken_burns(w, h, fps, duration)
        else:
            chain += f",fps={fps}"
        filters.append(f"[0:v]{chain},format=yuv420p[base]")

    # ----------------------------------------------------- audio input
    audio_idx = video_input_count
    inputs += ["-i", audio]

    # ----------------------------------------------------- visualizer
    vis = _visualizer(s.get("visualizer", "none"), w, h, fps, s.get("vis_color", "white"))
    cur = "[base]"
    if vis:
        filters.append(f"[{audio_idx}:a]{vis}[vis]")
        filters.append(f"{cur}[vis]overlay={_vis_overlay_pos(s.get('vis_position', 'bottom'))}:format=auto[v1]")
        cur = "[v1]"

    # ----------------------------------------------------- text overlays
    post: List[str] = []
    if s.get("title_text"):
        tf = write_textfile(s["title_text"], output + ".title.txt")
        post.append(_drawtext(tf, s.get("title_position", "top"), w, h, max(h // 16, 24), box=False))
    if s.get("watermark_text"):
        tf = write_textfile(s["watermark_text"], output + ".wm.txt")
        post.append(_drawtext(tf, s.get("watermark_position", "bottom_right"), w, h,
                              max(h // 36, 16), box=True))
    if s.get("fade") and duration > 3:
        fd = min(1.5, duration / 4)
        post.append(f"fade=t=in:st=0:d={fd},fade=t=out:st={duration - fd:.3f}:d={fd}")
    post = [p for p in post if p]
    if post:
        filters.append(f"{cur}{','.join(post)}[vout]")
        cur = "[vout]"

    # ----------------------------------------------------- audio filters
    audio_map = f"{audio_idx}:a"
    audio_mode = s.get("audio_mode", "copy")
    need_reencode = (
        audio_mode != "copy"
        or (audio_codec or "").lower() not in MP4_COPY_SAFE
        or (s.get("fade") and duration > 3)
    )
    if need_reencode:
        if audio_mode == "copy":
            audio_mode = "aac192"
        if s.get("fade") and duration > 3:
            fd = min(1.5, duration / 4)
            filters.append(f"[{audio_idx}:a]afade=t=in:st=0:d={fd},afade=t=out:st={duration - fd:.3f}:d={fd}[aout]")
            audio_map = "[aout]"
        audio_args = AUDIO_ARGS[audio_mode]
    else:
        audio_args = AUDIO_ARGS["copy"]

    # ----------------------------------------------------- encode args
    vcodec = "libx265" if plan.codec == "h265" else "libx264"
    cmd = inputs + [
        "-filter_complex", ";".join(filters),
        "-map", cur, "-map", audio_map,
        "-c:v", vcodec, "-preset", plan.preset, "-crf", str(plan.crf),
        "-pix_fmt", "yuv420p", "-r", str(fps),
    ]
    if plan.codec == "h264":
        cmd += ["-tune", "stillimage", "-profile:v", "high", "-level", "4.2"]
    else:
        cmd += ["-tag:v", "hvc1"]
    cmd += audio_args
    cmd += ["-t", f"{duration:.3f}", "-movflags", "+faststart", "-shortest", output]
    return cmd


# ------------------------------------------------------------------ runner
ProgressCb = Callable[[float, float, float], Awaitable[None]]  # (percent, out_time_sec, speed)


async def render(
    cmd: List[str],
    duration: float,
    on_progress: Optional[ProgressCb] = None,
    on_process: Optional[Callable] = None,
    timeout: float = 3 * 3600,
) -> None:
    """Run ffmpeg, streaming progress. Raises RenderError on failure."""
    logger.info("FFmpeg: %s", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    if on_process:
        on_process(proc)

    stderr_chunks: List[bytes] = []

    async def read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line)
            if len(stderr_chunks) > 200:
                stderr_chunks.pop(0)

    async def read_progress():
        last_emit = 0.0
        out_time = 0.0
        speed = 0.0
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="ignore").strip()
            if text.startswith("out_time_ms=") or text.startswith("out_time_us="):
                try:
                    out_time = int(text.split("=")[1]) / 1_000_000
                except ValueError:
                    pass
            elif text.startswith("speed="):
                m = re.search(r"([\d.]+)x", text)
                if m:
                    speed = float(m.group(1))
            elif text.startswith("progress="):
                now = time.time()
                if on_progress and (now - last_emit > 3 or text.endswith("end")):
                    last_emit = now
                    pct = min(out_time / duration * 100, 100) if duration else 0
                    try:
                        await on_progress(pct, out_time, speed)
                    except Exception:
                        pass

    try:
        await asyncio.wait_for(asyncio.gather(read_stderr(), read_progress(), proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RenderError("Render timed out")

    if proc.returncode != 0:
        err = b"".join(stderr_chunks).decode(errors="ignore").strip()
        if proc.returncode in (-9, 137):
            raise RenderError("cancelled")
        raise RenderError(err[-1500:] or f"ffmpeg exited with {proc.returncode}")


async def merge_audios(paths: List[str], output: str) -> str:
    """Concatenate multiple audio files into one (re-encoded to AAC)."""
    inputs = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in paths:
        inputs += ["-i", p]
    n = len(paths)
    fc = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
    cmd = inputs + ["-filter_complex", fc, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", output]
    code, _, err = await run_cmd(cmd, timeout=1800)
    if code != 0:
        raise RenderError(f"Audio merge failed: {err[-500:]}")
    return output
