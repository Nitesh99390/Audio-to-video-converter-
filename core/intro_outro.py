"""
Intro / Outro attachment.

    [ intro clip ] + [ main video (photo + audio, maybe 10 h) ] + [ outro clip ]

The main video is produced by the lite / pro engine and may be many hours long, so it is
NEVER re-encoded here. Instead:

  1. NORMALIZE  – every intro / outro clip is re-encoded ONCE (they are short) so that its
                  video (codec, size, fps, pix_fmt, profile, timebase) and audio (codec,
                  sample-rate, channels) match the main video bit-for-bit on the container level.
                  Clips without sound get a silent track so the streams line up.
  2. JOIN       – the concat demuxer joins the normalized clips and the main video with
                  `-c copy` (pure stream copy, disk-speed).
  3. FALLBACK   – if the stream copy still fails (exotic audio codec etc.), the main video's
                  *audio* is re-encoded to AAC once, the clips are re-normalized to AAC and the
                  join is retried. Video is never touched.
"""
import logging
import os
from typing import Callable, Dict, List, Optional, Tuple

from core.config import Config
from core.engine import RenderError, render
from core.utils import ffprobe, run_cmd

logger = logging.getLogger(__name__)

# audio codecs we know how to reproduce with an encoder so that the clip matches the main video
_AUDIO_ENCODERS = {
    "aac": ["-c:a", "aac"],
    "mp3": ["-c:a", "libmp3lame"],
}


def _fit_chain(w: int, h: int, fit: str) -> str:
    """Scale the clip into the main video's frame. Default = pad (never crop away branding)."""
    if fit == "stretch":
        return f"scale={w}:{h}:flags=lanczos,setsar=1"
    if fit == "crop":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1"
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def _video_args(main: Dict, fps: float) -> List[str]:
    """Encoder args that reproduce the main video's stream parameters."""
    vcodec = (main.get("video_codec") or "h264").lower()
    gop = max(int(round(fps * 10)), 1)
    if vcodec == "hevc":
        return ["-c:v", "libx265", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
                "-tag:v", "hvc1", "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
                "-x265-params", f"keyint={gop}:min-keyint={gop}:scenecut=0"]
    profile = (main.get("video_profile") or "high").lower().replace(" ", "")
    if profile not in ("baseline", "main", "high", "high10", "high422", "high444"):
        profile = "high"
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-profile:v", profile, "-level", "4.2",
            "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
            "-x264-params", f"keyint={gop}:min-keyint={gop}:scenecut=0:bframes=0"]


def _audio_args(codec: str, sample_rate: int, channels: int, kbps: int) -> List[str]:
    enc = _AUDIO_ENCODERS.get(codec)
    if not enc:
        return []
    return enc + ["-b:a", f"{kbps}k", "-ar", str(sample_rate), "-ac", str(channels)]


async def normalize_clip(
    clip: str,
    clip_info: Dict,
    main_info: Dict,
    output: str,
    fit: str = "pad",
    audio_codec_override: Optional[str] = None,
    on_process: Optional[Callable] = None,
) -> str:
    """Re-encode `clip` so that it can be stream-copied next to the main video."""
    w, h = int(main_info["width"]), int(main_info["height"])
    fps = float(main_info.get("fps") or 0) or 10.0
    acodec = (audio_codec_override or main_info.get("audio_codec") or "aac").lower()
    sr = int(main_info.get("sample_rate") or 44100)
    ch = int(main_info.get("channels") or 2)
    ch = 1 if ch == 1 else 2
    kbps = 128 if acodec == "aac" else 128
    if acodec == "mp3" and sr not in (32000, 44100, 48000, 22050, 24000, 16000, 11025, 12000, 8000):
        sr = 44100

    dur = min(float(clip_info.get("duration") or 0) or Config.MAX_INTRO_OUTRO_SEC, Config.MAX_INTRO_OUTRO_SEC)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-t", f"{dur:.3f}", "-i", clip]
    vchain = f"[0:v]{_fit_chain(w, h, fit)},fps={fps:g},format=yuv420p[v]"
    if clip_info.get("has_audio"):
        achain = f"[0:a:0]aresample={sr}:async=1,aformat=sample_fmts=fltp:channel_layouts={'mono' if ch == 1 else 'stereo'}[a]"
        cmd += ["-filter_complex", f"{vchain};{achain}", "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r={sr}:cl={'mono' if ch == 1 else 'stereo'}",
                "-filter_complex", vchain, "-map", "[v]", "-map", "1:a", "-shortest"]
    cmd += _video_args(main_info, fps) + ["-r", f"{fps:g}"]
    cmd += _audio_args(acodec, sr, ch, kbps)
    cmd += ["-t", f"{dur:.3f}", "-movflags", "+faststart", output]
    if Config.FFMPEG_THREADS:
        cmd[1:1] = ["-threads", str(Config.FFMPEG_THREADS)]
    await render(cmd, dur, on_process=on_process, timeout=1800)
    if not os.path.exists(output) or os.path.getsize(output) < 500:
        raise RenderError("Intro/outro clip could not be prepared.")
    return output


def _concat_list(paths: List[str], list_path: str) -> str:
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            ap = os.path.abspath(p).replace("'", r"'\''")
            f.write(f"file '{ap}'\n")
    return list_path


async def concat_copy(parts: List[str], output: str, total: float,
                      on_progress=None, on_process=None) -> None:
    lst = _concat_list(parts, output + ".concat.txt")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v:0", "-map", "0:a:0",
           "-c", "copy", "-movflags", "+faststart", output]
    try:
        await render(cmd, total, on_progress=on_progress, on_process=on_process, timeout=6 * 3600)
    finally:
        try:
            os.remove(lst)
        except OSError:
            pass


async def _reencode_main_audio(main: str, output: str, total: float, on_progress=None, on_process=None) -> Dict:
    """Video stream copy, audio -> AAC. Used only as a fallback."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-i", main, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", output]
    await render(cmd, total, on_progress=on_progress, on_process=on_process, timeout=6 * 3600)
    return await ffprobe(output)


async def _verify(path: str, expected: float) -> bool:
    info = await ffprobe(path)
    return bool(info.get("has_video") and info.get("has_audio")) and abs(info["duration"] - expected) < max(2.0, expected * 0.02)


async def attach_intro_outro(
    main: str,
    output: str,
    intro: Optional[str] = None,
    intro_info: Optional[Dict] = None,
    outro: Optional[str] = None,
    outro_info: Optional[Dict] = None,
    fit: str = "pad",
    on_stage=None,
    on_progress=None,
    on_process=None,
) -> Tuple[Dict, List[str]]:
    """
    Produce `output` = intro + main + outro. Returns (ffprobe info of output, temp files to delete).
    `main` is not modified.
    """
    temps: List[str] = []
    main_info = await ffprobe(main)
    if not main_info.get("has_video"):
        raise RenderError("Main video is not readable.")
    main_dur = float(main_info["duration"])
    clips = [(k, p, i or {}) for k, p, i in (("intro", intro, intro_info), ("outro", outro, outro_info)) if p]
    if not clips:
        return main_info, temps
    for k, p, i in clips:
        if not i:
            i.update(await ffprobe(p))

    async def build(audio_override: Optional[str], main_path: str, minfo: Dict) -> Tuple[List[str], float]:
        parts, total = [], float(minfo["duration"])
        for k, p, i in clips:
            if k == "outro":
                continue
            if on_stage:
                await on_stage("🎬 Preparing intro clip...")
            n = await normalize_clip(p, i, minfo, output + f".{k}.mp4", fit, audio_override, on_process)
            temps.append(n)
            parts.append(n)
            total += (await ffprobe(n))["duration"]
        parts.append(main_path)
        for k, p, i in clips:
            if k == "intro":
                continue
            if on_stage:
                await on_stage("🎬 Preparing outro clip...")
            n = await normalize_clip(p, i, minfo, output + f".{k}.mp4", fit, audio_override, on_process)
            temps.append(n)
            parts.append(n)
            total += (await ffprobe(n))["duration"]
        return parts, total

    # ---- attempt 1: match the main video's own codecs and stream-copy everything
    acodec = (main_info.get("audio_codec") or "").lower()
    try:
        if acodec not in _AUDIO_ENCODERS:
            raise RenderError(f"audio codec {acodec} cannot be matched")
        parts, total = await build(None, main, main_info)
        if on_stage:
            await on_stage("🔗 Joining intro + video + outro (stream copy)...")
        await concat_copy(parts, output, total, on_progress=on_progress, on_process=on_process)
        if await _verify(output, total):
            return await ffprobe(output), temps
        raise RenderError("joined file failed verification")
    except RenderError as e:
        if "cancel" in str(e).lower():
            raise
        logger.warning("intro/outro stream-copy join failed (%s) — falling back to AAC audio", e)

    # ---- attempt 2: main audio -> AAC once (video still copied), clips re-done in AAC
    if on_stage:
        await on_stage("🎵 Re-packing audio track for a clean join (one time)...")
    main_aac = output + ".mainaac.mp4"
    temps.append(main_aac)
    minfo = await _reencode_main_audio(main, main_aac, main_dur, on_progress=on_progress, on_process=on_process)
    parts, total = await build("aac", main_aac, minfo)
    if on_stage:
        await on_stage("🔗 Joining intro + video + outro...")
    await concat_copy(parts, output, total, on_progress=on_progress, on_process=on_process)
    if not await _verify(output, total):
        raise RenderError("Could not attach the intro/outro. Try removing them or use a different clip.")
    return await ffprobe(output), temps
