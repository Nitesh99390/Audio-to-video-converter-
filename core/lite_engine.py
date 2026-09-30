"""
LITE engine — ultra-fast "audio only matters" renderer.

A static-picture video does not need 10 hours of encoding:

  1. AUDIO   – stream-copied when it is MP4-safe (AAC / MP3). Otherwise it is
               re-encoded ONCE to AAC (only the source length, not the target length).
  2. SEGMENT – ONE short video segment (default 60 s) is encoded from the photo /
               slideshow / background video at a low frame-rate with a single
               keyframe -> usually < 200 KB.
  3. LOOP    – the segment is looped with `-stream_loop -1` and STREAM-COPIED next
               to the (optionally looped) audio into the final MP4. No re-encoding,
               so a 10 h video is written at disk speed (well under 2 minutes).

The result is the lightest possible file that YouTube happily accepts.
"""
import logging
import math
import os
from typing import Dict, List, Optional, Tuple

from core.config import Config
from core.engine import (
    ASPECT_RATIO, RESOLUTION_HEIGHT, FONT, RenderError,
    _fit_filter, _drawtext, write_textfile, render,
)
from core.utils import ceil_even, run_cmd

logger = logging.getLogger(__name__)

# quality -> CRF for the still segment (higher = smaller). Still images compress extremely well.
LITE_CRF = {"low": 32, "medium": 28, "high": 24, "ultra": 20}
LITE_FPS_OPTIONS = [1, 2, 5, 10, 15, 24, 30]

# audio bitrates for lite mode (kbps)
LITE_AUDIO_BITRATE = {"aac64": 64, "aac96": 96, "aac128": 128, "aac192": 192, "aac320": 320, "mp3": 128}
# codecs we can put into MP4 without touching them (YouTube accepts both)
LITE_COPY_SAFE = {"aac", "mp3"}


# ------------------------------------------------------------------ helpers
def lite_dimensions(settings: Dict, src_w: int = 0, src_h: int = 0) -> Tuple[int, int]:
    res = settings.get("resolution", "720p")
    aspect = settings.get("aspect", "16:9")
    if res == "original" and src_w and src_h:
        h = min(src_h, 2160)
        w = src_w * h / src_h
        return ceil_even(w), ceil_even(h)
    ratio = ASPECT_RATIO.get(aspect, 16 / 9)
    h = RESOLUTION_HEIGHT.get(res, 720)
    if ratio < 1:
        w = h
        h = w / ratio
    else:
        w = h * ratio
    return ceil_even(w), ceil_even(h)


def lite_fps(settings: Dict) -> int:
    try:
        fps = int(settings.get("fps", 10))
    except (TypeError, ValueError):
        fps = 10
    return max(1, min(fps, 30))


def _text_overlays(settings: Dict, output: str, w: int, h: int) -> List[str]:
    post: List[str] = []
    if settings.get("title_text") and FONT:
        tf = write_textfile(settings["title_text"], output + ".title.txt")
        post.append(_drawtext(tf, settings.get("title_position", "top"), w, h, max(h // 16, 24), box=False))
    if settings.get("watermark_text") and FONT:
        tf = write_textfile(settings["watermark_text"], output + ".wm.txt")
        post.append(_drawtext(tf, settings.get("watermark_position", "bottom_right"), w, h,
                              max(h // 36, 16), box=True))
    return [p for p in post if p]


def _x264_args(vcodec: str, gop: int, crf: int, preset: str) -> List[str]:
    args = ["-c:v", vcodec, "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0"]
    if vcodec == "libx264":
        args += ["-tune", "stillimage", "-profile:v", "high", "-level", "4.2",
                 "-x264-params", f"keyint={gop}:min-keyint={gop}:scenecut=0:bframes=0"]
    else:
        args += ["-tag:v", "hvc1", "-x265-params", f"keyint={gop}:min-keyint={gop}:scenecut=0"]
    return args


# ------------------------------------------------------------------ audio
def plan_audio(settings: Dict, audio_codec: Optional[str], audio_bitrate: int,
               target_duration: float) -> Tuple[bool, int, str]:
    """
    Decide whether the source audio must be re-encoded (once) before looping.
    Returns (reencode?, aac_kbps, human label).
    Automatically lowers the bitrate if the final file would exceed the upload limit.
    """
    mode = settings.get("audio_mode", "copy")
    codec = (audio_codec or "").lower()
    cap = Config.MAX_OUTPUT_SIZE_MB * 1024 * 1024 * 0.92

    if mode == "copy":
        if codec in LITE_COPY_SAFE:
            est = (audio_bitrate or 128_000) * target_duration / 8
            if est < cap:
                return False, 0, f"copy ({codec.upper()})"
            mode = "aac96"          # too big -> shrink
        else:
            mode = "aac128"         # wav / flac / opus / ogg -> must convert

    kbps = LITE_AUDIO_BITRATE.get(mode, 128)
    while kbps > 64 and (kbps * 1000 * target_duration / 8) > cap:
        kbps = {320: 192, 192: 128, 128: 96, 96: 64}.get(kbps, 64)
    return True, kbps, f"AAC {kbps}k"


def build_audio_command(audio: str, output: str, kbps: int) -> List[str]:
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
            "-i", audio, "-vn", "-map", "0:a:0", "-c:a", "aac", "-b:a", f"{kbps}k", "-ac", "2",
            "-ar", "44100", "-movflags", "+faststart", output]


# ------------------------------------------------------------------ segment
async def build_segment(
    settings: Dict,
    images: List[str],
    output: str,
    w: int,
    h: int,
    fps: int,
    bg_video: Optional[str] = None,
    bg_video_duration: float = 0.0,
    on_process=None,
) -> float:
    """
    Encode the short loop segment (video only). Returns its duration in seconds.

    Single image: the frame is rendered ONCE to a raw yuv420p buffer and then fed to
    x264 via a raw-video loop — this avoids decoding + scaling the picture per frame
    and roughly halves the encode time.
    """
    seg = float(Config.LITE_SEGMENT_SEC)
    fit = settings.get("fit", "blur")
    crf = LITE_CRF.get(settings.get("quality", "medium"), 28)
    vcodec = "libx265" if settings.get("codec") == "h265" else "libx264"
    post = _text_overlays(settings, output, w, h)

    base_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    if Config.FFMPEG_THREADS:
        base_cmd += ["-threads", str(Config.FFMPEG_THREADS)]

    if bg_video:
        # the loop segment IS the (trimmed) background video, so the loop point is seamless
        seg = max(1.0, min(bg_video_duration or seg, float(Config.LITE_MAX_BG_VIDEO_SEC)))
        chain = f"[0:v]{_fit_filter(w, h, fit, fps)},fps={fps},format=yuv420p"
        chain += ("," + ",".join(post)) if post else ""
        frames = max(int(round(seg * fps)), 1)
        gop = min(frames, 300)
        cmd = base_cmd + ["-t", f"{seg:.3f}", "-i", bg_video,
                          "-filter_complex", chain + "[v]", "-map", "[v]", "-an"]
        # moving pictures are repeated hundreds of times -> compress them harder
        cmd += _x264_args(vcodec, gop, min(crf + 4, 40), "veryfast") + ["-r", str(fps), "-t", f"{seg:.3f}",
                                                             "-movflags", "+faststart", output]
        await render(cmd, seg, on_process=on_process, timeout=1800)
        return seg

    if len(images) > 1:
        per = float(settings.get("slideshow_duration", 5))
        n = len(images)
        seg = per * n                      # one full cycle of the slideshow
        cmd = list(base_cmd)
        filters, labels = [], []
        for i, img in enumerate(images):
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", str(per), "-i", img]
            filters.append(f"[{i}:v]{_fit_filter(w, h, fit, fps)},fps={fps},format=yuv420p[s{i}]")
            labels.append(f"[s{i}]")
        filters.append("".join(labels) + f"concat=n={n}:v=1:a=0[base]")
        cur = "[base]"
        if post:
            filters.append(f"{cur}{','.join(post)}[v]")
            cur = "[v]"
        frames = max(int(round(seg * fps)), 1)
        gop = min(frames, max(int(per * fps), 1))
        cmd += ["-filter_complex", ";".join(filters), "-map", cur, "-an"]
        cmd += _x264_args(vcodec, gop, crf, "veryfast") + ["-r", str(fps), "-t", f"{seg:.3f}",
                                                            "-movflags", "+faststart", output]
        await render(cmd, seg, on_process=on_process, timeout=1800)
        return seg

    # ---- single image: pre-render one frame, then raw-loop it into the encoder
    raw = output + ".frame.yuv"
    chain = _fit_filter(w, h, fit, fps) + ",format=yuv420p"
    chain += ("," + ",".join(post)) if post else ""
    code, _, err = await run_cmd(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", images[0],
         "-filter_complex", f"[0:v]{chain}[v]", "-map", "[v]", "-frames:v", "1",
         "-pix_fmt", "yuv420p", "-f", "rawvideo", raw],
        timeout=120,
    )
    if code != 0 or not os.path.exists(raw) or os.path.getsize(raw) < 100:
        raise RenderError(f"Could not render the frame: {err[-400:]}")
    frames = max(int(round(seg * fps)), 1)
    cmd = base_cmd + ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{w}x{h}", "-r", str(fps),
                      "-stream_loop", str(frames - 1), "-i", raw, "-an"]
    cmd += _x264_args(vcodec, frames, crf, "veryfast") + ["-r", str(fps), "-movflags", "+faststart", output]
    try:
        await render(cmd, seg, on_process=on_process, timeout=1800)
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass
    return seg


# ------------------------------------------------------------------ loop / mux
def build_loop_command(segment: str, audio: str, output: str, target_duration: float,
                       loop_audio: bool) -> List[str]:
    """Loop the tiny segment for the full duration and mux with the audio (pure stream copy)."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    cmd += ["-stream_loop", "-1", "-i", segment]
    if loop_audio:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-t", f"{target_duration:.3f}", "-movflags", "+faststart", output]
    return cmd


def estimate_output_size(segment_size: int, segment_dur: float, target_duration: float,
                         audio_bps: int) -> int:
    loops = math.ceil(target_duration / max(segment_dur, 0.1))
    return int(segment_size * loops + (audio_bps or 128_000) * target_duration / 8)


# ------------------------------------------------------------------ pipeline
async def render_lite(
    settings: Dict,
    images: List[str],
    audio: str,
    audio_info: Dict,
    output: str,
    target_duration: float,
    on_stage=None,
    on_progress=None,
    on_process=None,
    bg_video: Optional[str] = None,
    bg_info: Optional[Dict] = None,
    src_w: int = 0,
    src_h: int = 0,
) -> Dict:
    """
    Full lite pipeline. Returns a dict with width/height/fps/segment info/audio label/temp files.
    on_stage(text) is awaited on phase change; on_progress(pct, out_time, speed) during audio
    conversion and the final loop-mux.
    """
    if bg_video and bg_info and not (src_w and src_h):
        src_w, src_h = bg_info.get("width", 0), bg_info.get("height", 0)
    w, h = lite_dimensions(settings, src_w, src_h)
    fps = lite_fps(settings)
    segment = output + ".seg.mp4"
    temps: List[str] = [segment, segment + ".title.txt", segment + ".wm.txt"]

    audio_dur = float(audio_info.get("duration") or 0)
    audio_bps = int(audio_info.get("bitrate") or 0)
    loop_audio = target_duration > audio_dur + 0.5

    # ---- 1. audio (convert once if needed)
    reencode, kbps, label = plan_audio(settings, audio_info.get("audio_codec"), audio_bps, target_duration)
    if reencode:
        conv = output + ".audio.m4a"
        temps.append(conv)
        if on_stage:
            await on_stage(f"🎵 Converting audio to {label} (one time, {max(1, int(audio_dur // 60))} min)...")
        await render(build_audio_command(audio, conv, kbps), audio_dur, on_progress=on_progress,
                     on_process=on_process, timeout=3 * 3600)
        audio = conv
        audio_bps = kbps * 1000

    # ---- 2. loop segment
    if on_stage:
        await on_stage(f"🧩 Building loop segment ({w}x{h} @ {fps} fps)...")
    seg_dur = await build_segment(settings, images, segment, w, h, fps, bg_video=bg_video,
                                  bg_video_duration=(bg_info or {}).get("duration", 0.0), on_process=on_process)
    if not os.path.exists(segment) or os.path.getsize(segment) < 500:
        raise RenderError("Loop segment could not be created.")
    seg_size = os.path.getsize(segment)

    est = estimate_output_size(seg_size, seg_dur, target_duration, audio_bps)
    if est > Config.MAX_OUTPUT_SIZE_MB * 1024 * 1024:
        raise RenderError(
            f"Estimated output ≈ {est / 1024 / 1024:.0f} MB exceeds the {Config.MAX_OUTPUT_SIZE_MB} MB upload "
            f"limit. Choose a shorter duration or a lower audio bitrate / lower fps."
        )

    # ---- 3. loop + mux (stream copy)
    if on_stage:
        await on_stage(f"🔁 Looping & muxing ({label})" + (" • audio looped to fill" if loop_audio else ""))
    await render(build_loop_command(segment, audio, output, target_duration, loop_audio), target_duration,
                 on_progress=on_progress, on_process=on_process, timeout=6 * 3600)

    return {
        "width": w, "height": h, "fps": fps, "segment_dur": seg_dur, "segment_size": seg_size,
        "audio_label": label, "loop_audio": loop_audio, "reencode": reencode, "temps": temps,
    }
