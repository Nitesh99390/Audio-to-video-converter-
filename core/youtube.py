"""
YouTube upload (admins only).

Flow
----
1. After a render the admin is asked  "📤 Upload to YouTube?"  (plugins/youtube.py).
2. The bot needs an OAuth token: the admin sends `token.pickle` (created once on a PC with the
   Google quickstart / `youtube-upload` style script) as a Telegram document. It is validated,
   refreshed if expired and stored in `YT_TOKEN_DIR/<admin_id>.pickle` — outside the downloads
   folder so the disk guard never touches it. From then on no token is asked again until it stops
   working (revoked / expired refresh token).
3. Title / description / tags are generated from an **SEO template** (sleep, lofi, meditation,
   music, study, plain) with shortcuts the admin can tweak inline, then the file is uploaded with
   the resumable protocol (chunked, retried) while a progress bar is shown in Telegram.

Everything blocking (pickle load, token refresh, googleapiclient calls) runs in a worker thread
so the bot stays responsive.

token.pickle format
-------------------
A pickled `google.oauth2.credentials.Credentials` (what every quickstart writes) — also accepted:
a pickled dict with `token / refresh_token / client_id / client_secret / token_uri / scopes`,
or a plain JSON "authorized user" file (same keys), or an `oauth2client` credentials pickle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pickle
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.config import Config
from core.utils import format_duration

logger = logging.getLogger(__name__)

SCOPES_UPLOAD = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
)
PRIVACY_OPTIONS = ("public", "unlisted", "private")
CATEGORIES = {"10": "Music", "22": "People & Blogs", "24": "Entertainment", "26": "Howto & Style",
              "27": "Education", "19": "Travel", "20": "Gaming"}
MAX_TITLE = 100
MAX_DESC = 5000
MAX_TAGS_CHARS = 480          # API limit is 500 for the whole tag list
MAX_RETRIES = 8


class YouTubeError(Exception):
    """Human readable error for the chat."""


class TokenError(YouTubeError):
    """token.pickle is missing / invalid / revoked — the admin must send a new one."""


# =====================================================================================
#  SEO templates — "Bahut sara video search mein aur jaldi user ke paas pahunche"
# =====================================================================================
# Placeholders: {title} {artist} {duration} {hours} {channel} {year} {hashtags} {chapters}
@dataclass
class Template:
    key: str
    label: str
    title: str                 # title pattern (<= 100 chars after fill)
    description: str
    tags: List[str]
    category: str = "10"
    hashtags: List[str] = field(default_factory=list)


TEMPLATES: Dict[str, Template] = {
    "music": Template(
        key="music", label="🎵 Music / Song",
        title="{title} – {artist} | Full Audio {dur_label}",
        description=(
            "🎵 {title}{by_artist}\n"
            "⏱ Duration: {duration}\n\n"
            "Enjoy the full track in high quality. If you like it, please 👍 Like, 💬 Comment and 🔔 Subscribe "
            "to {channel} for more music every week.\n\n"
            "{chapters}"
            "📌 Keywords: {title}, {artist}, {title} full song, {title} audio, {title} lyrics, {title} {hours} hours\n\n"
            "{hashtags}\n\n"
            "⚠️ Copyright: This upload is for listening / promotional purposes only. All rights belong to their "
            "respective owners. For any issue please contact us before striking and we will remove it right away."
        ),
        tags=["{title}", "{artist}", "{title} full song", "{title} audio", "{title} lyrics", "music", "song",
              "full audio", "{title} {artist}", "new song", "trending song", "{title} slowed", "{title} {hours} hours"],
        hashtags=["#{title_tag}", "#{artist_tag}", "#music", "#song", "#fullaudio"],
    ),
    "sleep": Template(
        key="sleep", label="😴 Sleep / Relax",
        title="{title} | {hours} Hours Relaxing Sleep Music 😴 Deep Sleep, Stress Relief",
        description=(
            "😴 {hours} hours of {title}{by_artist} to help you fall asleep fast, relax and release stress.\n\n"
            "Perfect for:\n"
            "• 🌙 Deep sleep & insomnia relief\n• 🧘 Meditation & yoga\n• 📚 Studying & focus\n"
            "• 🌧 Background ambience\n\n"
            "Put your phone down, close your eyes and let the music carry you. Loop it all night long.\n\n"
            "{chapters}"
            "If this helps you sleep, please 👍 Like and 🔔 Subscribe to {channel} — it supports the channel a lot.\n\n"
            "📌 Keywords: sleep music, relaxing music, deep sleep, {hours} hours sleep music, calm music, stress relief, "
            "insomnia, meditation music, {title}\n\n"
            "{hashtags}\n\n"
            "⚠️ All rights belong to their respective owners. Contact us for any copyright concern."
        ),
        tags=["sleep music", "relaxing music", "deep sleep music", "{hours} hours sleep music", "calm music",
              "stress relief", "insomnia", "meditation music", "relaxing sleep music", "sleep", "{title}",
              "soothing music", "peaceful music", "night music", "fall asleep fast"],
        hashtags=["#sleepmusic", "#relaxingmusic", "#deepsleep", "#meditation", "#{hours}hours"],
    ),
    "lofi": Template(
        key="lofi", label="🎧 Lo-fi / Chill",
        title="{title} 🎧 {hours} Hour Lofi Hip Hop Mix | Chill Beats to Relax / Study to",
        description=(
            "🎧 {hours} hour lofi mix: {title}{by_artist}\n\n"
            "Chill beats to relax, study, code, work or sleep to. Press play and let the vibes flow ☕️\n\n"
            "{chapters}"
            "👍 Like · 💬 Comment what you're doing right now · 🔔 Subscribe to {channel} for weekly mixes\n\n"
            "📌 Keywords: lofi, lofi hip hop, chill beats, study music, lofi mix, {hours} hour lofi, relax, "
            "beats to study to, chillhop, {title}\n\n"
            "{hashtags}\n\n"
            "⚠️ All rights belong to their respective owners. Contact us for any copyright concern."
        ),
        tags=["lofi", "lofi hip hop", "lofi mix", "chill beats", "study music", "beats to relax to",
              "beats to study to", "{hours} hour lofi", "chillhop", "lofi radio", "aesthetic", "{title}",
              "lofi sleep", "lofi chill", "focus music"],
        hashtags=["#lofi", "#lofihiphop", "#chillbeats", "#studymusic", "#relax"],
        category="10",
    ),
    "meditation": Template(
        key="meditation", label="🧘 Meditation / Spiritual",
        title="{title} | {hours} Hours Meditation Music 🧘 Healing, Positive Energy, Inner Peace",
        description=(
            "🧘 {hours} hours of {title}{by_artist} for meditation, healing and positive energy.\n\n"
            "Use it for:\n• 🕉 Morning meditation & mantra chanting\n• 🙏 Prayer, puja & spiritual practice\n"
            "• 🌿 Yoga, reiki & healing\n• 🌅 Peaceful background for the whole day\n\n"
            "{chapters}"
            "Share it with someone who needs peace today 🙏 Like & Subscribe to {channel}.\n\n"
            "📌 Keywords: meditation music, healing music, positive energy, {title}, mantra, spiritual music, "
            "{hours} hours meditation, inner peace, relaxing music, yoga music\n\n"
            "{hashtags}\n\n"
            "⚠️ All rights belong to their respective owners. Contact us for any copyright concern."
        ),
        tags=["meditation music", "healing music", "positive energy", "{title}", "mantra", "spiritual music",
              "{hours} hours meditation", "inner peace", "yoga music", "relaxing music", "chanting",
              "morning meditation", "calm mind", "peaceful music", "devotional"],
        hashtags=["#meditation", "#healingmusic", "#positiveenergy", "#{title_tag}", "#peace"],
    ),
    "study": Template(
        key="study", label="📚 Study / Focus",
        title="{title} | {hours} Hours Study Music 📚 Deep Focus, Concentration & Productivity",
        description=(
            "📚 {hours} hours of {title}{by_artist} — music for deep focus, studying, reading and work.\n\n"
            "Boost your concentration, block distractions and get more done. Great for exam preparation, "
            "coding sessions and long work days.\n\n"
            "{chapters}"
            "👍 Like · 🔔 Subscribe to {channel} · 💬 Tell us what you're studying!\n\n"
            "📌 Keywords: study music, focus music, concentration music, {hours} hours study, deep focus, "
            "productivity music, work music, reading music, exam music, {title}\n\n"
            "{hashtags}\n\n"
            "⚠️ All rights belong to their respective owners. Contact us for any copyright concern."
        ),
        tags=["study music", "focus music", "concentration music", "{hours} hours study music", "deep focus",
              "productivity music", "work music", "reading music", "exam music", "{title}", "brain power",
              "background music", "calm study", "music for studying", "study with me"],
        hashtags=["#studymusic", "#focusmusic", "#concentration", "#productivity", "#{hours}hours"],
        category="27",
    ),
    "plain": Template(
        key="plain", label="📝 Plain (title only)",
        title="{title}{dash_artist}",
        description="{title}{by_artist}\n⏱ {duration}\n\n{hashtags}",
        tags=["{title}", "{artist}"],
        hashtags=["#{title_tag}"],
    ),
}
TEMPLATE_ORDER = ["music", "sleep", "lofi", "meditation", "study", "plain"]


def _tag_word(s: str) -> str:
    """'Rain Sounds – Vol.2' -> 'RainSoundsVol2' (hashtag safe)."""
    return re.sub(r"[^0-9A-Za-z\u0900-\u097F]", "", (s or "").title())[:40]


def _hours_label(seconds: float) -> Tuple[str, str]:
    """(hours, dur_label) -> ('10', '(10 Hours)') / ('1', '(1 Hour)') / ('', '(45 Min)')."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h >= 1:
        hours = str(h) if m < 30 else f"{h}.5"
        label = f"({hours} Hour{'s' if hours != '1' else ''})"
        return hours, label
    return "", f"({max(m, 1)} Min)" if seconds < 3600 else ""


def _fill(pattern: str, ctx: Dict[str, str]) -> str:
    class _Safe(dict):
        def __missing__(self, k):
            return ""
    try:
        return pattern.format_map(_Safe(ctx))
    except Exception:
        return pattern


def _dedupe(items: List[str]) -> List[str]:
    seen, out = set(), []
    for it in items:
        k = it.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(it.strip())
    return out


def build_metadata(template_key: str, title: str, artist: str = "", duration: float = 0.0,
                   privacy: Optional[str] = None, chapters: Optional[List[Tuple[float, str]]] = None,
                   extra_tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Fill a template → dict(title, description, tags, category, privacy, template).
    Everything is clipped to the YouTube limits (100 / 5000 / 500).
    """
    tpl = TEMPLATES.get(template_key) or TEMPLATES[Config.YT_DEFAULT_TEMPLATE] if template_key else None
    tpl = tpl or TEMPLATES.get(Config.YT_DEFAULT_TEMPLATE) or TEMPLATES["music"]
    title = (title or "Untitled").strip()
    artist = (artist or "").strip()
    hours, dur_label = _hours_label(duration)
    channel = Config.YT_CHANNEL_NAME or "the channel"
    ctx = {
        "title": title, "artist": artist, "duration": format_duration(duration),
        "hours": hours or "1", "dur_label": dur_label, "channel": channel,
        "year": time.strftime("%Y"),
        "by_artist": f" by {artist}" if artist else "",
        "dash_artist": f" – {artist}" if artist else "",
        "title_tag": _tag_word(title) or "music", "artist_tag": _tag_word(artist) or "music",
    }
    # chapters block (only when we actually have several audio files)
    ch_lines = []
    if chapters and len(chapters) > 1:
        ch_lines.append("⏰ Timestamps:")
        for start, name in chapters:
            ts = format_duration(start)
            if len(ts) == 5:
                ts = "00:" + ts
            ch_lines.append(f"{ts} {name}")
        ch_lines.append("")
    ctx["chapters"] = "\n".join(ch_lines) + ("\n" if ch_lines else "")

    hashtags = _dedupe([_fill(h, ctx) for h in tpl.hashtags])
    hashtags = [h for h in hashtags if len(h) > 2 and h != "#"]
    ctx["hashtags"] = " ".join(hashtags[:6])

    out_title = _fill(tpl.title, ctx).replace("  ", " ").replace(" – |", " |").strip(" –|-")
    if not artist:
        out_title = out_title.replace("–  |", "|").replace(" – ", " ")
    out_title = re.sub(r"\s{2,}", " ", out_title).strip()
    if len(out_title) > MAX_TITLE:
        out_title = out_title[:MAX_TITLE - 1].rstrip() + "…"
    description = _fill(tpl.description, ctx)
    description = re.sub(r"\n{3,}", "\n\n", description).strip()[:MAX_DESC]

    tags = [_fill(t, ctx) for t in tpl.tags]
    tags += [t for t in (extra_tags or [])]
    tags += [t.strip() for t in Config.YT_EXTRA_TAGS.split(",") if t.strip()]
    if Config.YT_CHANNEL_NAME:
        tags.append(Config.YT_CHANNEL_NAME)
    tags = [t for t in _dedupe(tags) if 1 < len(t) <= 60 and t.lower() not in ("none", "unknown")]
    total, clipped = 0, []
    for t in tags:
        if total + len(t) + 2 > MAX_TAGS_CHARS:
            break
        clipped.append(t)
        total += len(t) + 2
    return {
        "template": tpl.key, "title": out_title, "description": description, "tags": clipped,
        "category": tpl.category or Config.YT_DEFAULT_CATEGORY,
        "privacy": privacy if privacy in PRIVACY_OPTIONS else Config.YT_DEFAULT_PRIVACY,
    }


def metadata_preview(meta: Dict[str, Any], size_text: str = "", status_line: str = "") -> str:
    tpl = TEMPLATES.get(meta.get("template", ""), TEMPLATES["music"])
    desc = meta.get("description", "")
    short = desc if len(desc) <= 450 else desc[:450].rstrip() + "…"
    tags = meta.get("tags", [])
    tags_s = ", ".join(tags[:10]) + (f" … (+{len(tags) - 10})" if len(tags) > 10 else "")
    lines = [
        "📺 **YouTube upload**" + (f" · {size_text}" if size_text else ""),
        "",
        f"🏷 **Title** ({len(meta.get('title', ''))}/100)\n`{meta.get('title', '')}`",
        "",
        f"📝 **Description** ({len(desc)}/5000)\n{short}",
        "",
        f"🔖 **Tags** ({len(tags)}): {tags_s}",
        "",
        f"🎨 Template: {tpl.label} · 🔒 {meta.get('privacy', 'public')} · "
        f"📂 {CATEGORIES.get(str(meta.get('category')), meta.get('category'))}",
    ]
    if status_line:
        lines += ["", status_line]
    return "\n".join(lines)


# =====================================================================================
#  token.pickle handling
# =====================================================================================
def token_path(admin_id: int) -> str:
    return os.path.join(Config.YT_TOKEN_DIR, f"{admin_id}.pickle")


def has_token(admin_id: int) -> bool:
    return os.path.isfile(token_path(admin_id))


def delete_token(admin_id: int) -> bool:
    p = token_path(admin_id)
    try:
        os.remove(p)
        return True
    except OSError:
        return False


def _creds_from_obj(obj: Any):
    """Turn whatever was pickled / dumped into google.oauth2.credentials.Credentials."""
    from google.oauth2.credentials import Credentials

    if isinstance(obj, Credentials):
        return obj
    # oauth2client (old quickstarts): has .refresh_token/.client_id/.client_secret/.token_uri
    if all(hasattr(obj, a) for a in ("refresh_token", "client_id", "client_secret")):
        return Credentials(
            token=getattr(obj, "access_token", None),
            refresh_token=obj.refresh_token, client_id=obj.client_id, client_secret=obj.client_secret,
            token_uri=getattr(obj, "token_uri", "https://oauth2.googleapis.com/token"),
            scopes=list(getattr(obj, "scopes", None) or SCOPES_UPLOAD),
        )
    if isinstance(obj, dict):
        d = obj
        if "installed" in d or "web" in d:
            raise TokenError("This is a **client_secret.json**, not a token. Run the OAuth flow once on your PC "
                             "and send the generated **token.pickle** (or token.json).")
        if not d.get("refresh_token") and not d.get("token"):
            raise TokenError("The token file has no `refresh_token` / `token` field.")
        return Credentials(
            token=d.get("token") or d.get("access_token"),
            refresh_token=d.get("refresh_token"), client_id=d.get("client_id"),
            client_secret=d.get("client_secret"),
            token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
            scopes=d.get("scopes") or list(SCOPES_UPLOAD),
        )
    raise TokenError(f"Unsupported token format: `{type(obj).__name__}`.")


def _load_creds_sync(path: str):
    with open(path, "rb") as f:
        raw = f.read()
    if not raw:
        raise TokenError("The token file is empty.")
    obj = None
    try:
        obj = pickle.loads(raw)
    except Exception:
        try:
            obj = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            raise TokenError("Could not read the file — it is neither a pickle nor JSON.")
    return _creds_from_obj(obj)


def _refresh_if_needed_sync(creds) -> bool:
    """Refresh the access token when expired. Returns True if refreshed."""
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError

    if creds.valid and not creds.expired:
        return False
    if not creds.refresh_token:
        raise TokenError("Token expired and has no refresh_token — create a new token.pickle.")
    try:
        creds.refresh(Request())
        return True
    except RefreshError as e:
        raise TokenError(f"Google refused to refresh the token (revoked or expired): `{str(e)[:160]}`\n"
                         "Create a new **token.pickle** and send it again.")
    except Exception as e:
        raise YouTubeError(f"Token refresh failed: `{type(e).__name__}: {str(e)[:160]}`")


def _save_creds_sync(creds, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(creds, f)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _build_service_sync(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _channel_info_sync(service) -> Dict[str, Any]:
    resp = service.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        raise TokenError("This Google account has **no YouTube channel** — create one first.")
    it = items[0]
    sn, st = it.get("snippet", {}), it.get("statistics", {})
    return {
        "id": it.get("id"), "title": sn.get("title", "?"), "custom_url": sn.get("customUrl", ""),
        "subs": st.get("subscriberCount", "?"), "videos": st.get("videoCount", "?"),
    }


def _import_token_sync(src_path: str, admin_id: int, verify: bool = True) -> Dict[str, Any]:
    creds = _load_creds_sync(src_path)
    scopes = set(creds.scopes or [])
    if scopes and not (scopes & set(SCOPES_UPLOAD)):
        raise TokenError("This token has **no YouTube upload scope**. Create it with "
                         "`https://www.googleapis.com/auth/youtube.upload` (or `.../auth/youtube`).")
    _refresh_if_needed_sync(creds)
    info = {}
    if verify:
        try:
            info = _channel_info_sync(_build_service_sync(creds))
        except TokenError:
            raise
        except Exception as e:
            msg = str(e)
            if "insufficient" in msg.lower() or "403" in msg:
                raise TokenError("Google rejected the token (insufficient permission / API not enabled). "
                                 "Enable **YouTube Data API v3** in the Google Cloud project and re-create the token.")
            if "401" in msg or "invalid_grant" in msg.lower():
                raise TokenError("Token is invalid or revoked (401). Create a new one.")
            logger.warning("channel lookup failed, token still saved: %s", e)
    _save_creds_sync(creds, token_path(admin_id))
    return info


async def import_token(src_path: str, admin_id: int, verify: bool = True) -> Dict[str, Any]:
    """Validate + refresh + store a token.pickle the admin sent. Returns channel info (may be {})."""
    return await asyncio.to_thread(_import_token_sync, src_path, admin_id, verify)


async def channel_info(admin_id: int) -> Dict[str, Any]:
    def _run():
        if not has_token(admin_id):
            raise TokenError("No token stored.")
        creds = _load_creds_sync(token_path(admin_id))
        if _refresh_if_needed_sync(creds):
            _save_creds_sync(creds, token_path(admin_id))
        return _channel_info_sync(_build_service_sync(creds))
    return await asyncio.to_thread(_run)


# =====================================================================================
#  Upload
# =====================================================================================
def _is_retryable(exc: Exception) -> bool:
    from googleapiclient.errors import HttpError
    if isinstance(exc, HttpError):
        return exc.resp.status in (500, 502, 503, 504, 429)
    name = type(exc).__name__
    return name in ("ConnectionError", "TimeoutError", "ServerNotFoundError", "ProtocolError",
                    "IncompleteRead", "RemoteDisconnected", "socket.timeout", "timeout", "SSLError", "OSError")


def _explain_http_error(exc) -> str:
    try:
        body = json.loads(exc.content.decode("utf-8", "ignore"))
        err = body.get("error", {})
        reason = ""
        if err.get("errors"):
            reason = err["errors"][0].get("reason", "")
        msg = err.get("message", str(exc))
    except Exception:
        reason, msg = "", str(exc)
    hints = {
        "quotaExceeded": "Daily YouTube API quota exhausted (10 000 units ≈ 6 uploads/day). Try after midnight Pacific time.",
        "uploadLimitExceeded": "The channel reached its daily upload limit. Try again tomorrow.",
        "forbidden": "Access forbidden — the token lacks the upload scope or the channel is restricted.",
        "youtubeSignupRequired": "This Google account has no YouTube channel.",
        "invalidTitle": "YouTube rejected the title (too long or forbidden characters).",
        "invalidDescription": "YouTube rejected the description.",
        "invalidTags": "YouTube rejected the tags (too long).",
        "mediaBodyRequired": "No media body — internal error.",
    }
    hint = hints.get(reason, "")
    return f"HTTP {exc.resp.status} {reason}: {msg[:200]}" + (f"\n💡 {hint}" if hint else "")


def _upload_sync(admin_id: int, video_path: str, meta: Dict[str, Any], thumb_path: Optional[str],
                 progress: Callable[[int, int], None], cancelled: Callable[[], bool]) -> Dict[str, Any]:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    if not has_token(admin_id):
        raise TokenError("No token stored — send **token.pickle** first.")
    creds = _load_creds_sync(token_path(admin_id))
    if _refresh_if_needed_sync(creds):
        _save_creds_sync(creds, token_path(admin_id))
    service = _build_service_sync(creds)

    body = {
        "snippet": {
            "title": (meta.get("title") or "Untitled")[:MAX_TITLE],
            "description": (meta.get("description") or "")[:MAX_DESC],
            "tags": list(meta.get("tags") or [])[:60],
            "categoryId": str(meta.get("category") or Config.YT_DEFAULT_CATEGORY),
        },
        "status": {
            "privacyStatus": meta.get("privacy") if meta.get("privacy") in PRIVACY_OPTIONS else Config.YT_DEFAULT_PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }
    if meta.get("publish_at"):
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = meta["publish_at"]
    if meta.get("playlist_id"):
        pass  # added after the upload

    size = os.path.getsize(video_path)
    chunk = max(1, int(Config.YT_CHUNK_MB)) * 1024 * 1024
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=chunk, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retry = 0
    sent = 0
    progress(0, size)
    while response is None:
        if cancelled():
            raise YouTubeError("cancelled")
        try:
            status, response = request.next_chunk(num_retries=0)
            retry = 0
            if status:
                sent = int(status.resumable_progress)
                progress(sent, size)
        except HttpError as e:
            if _is_retryable(e) and retry < MAX_RETRIES:
                retry += 1
                sleep = min(60, 2 ** retry + random.random())
                logger.warning("YouTube chunk error %s (retry %d/%d in %.0fs)", e.resp.status, retry, MAX_RETRIES, sleep)
                time.sleep(sleep)
                continue
            if e.resp.status in (401, 403) and "invalid" in str(e).lower():
                raise TokenError(_explain_http_error(e))
            raise YouTubeError(_explain_http_error(e))
        except Exception as e:  # network hiccups
            if _is_retryable(e) and retry < MAX_RETRIES:
                retry += 1
                sleep = min(60, 2 ** retry + random.random())
                logger.warning("YouTube upload network error %s (retry %d/%d in %.0fs)", e, retry, MAX_RETRIES, sleep)
                time.sleep(sleep)
                continue
            raise YouTubeError(f"Upload failed: `{type(e).__name__}: {str(e)[:200]}`")
    progress(size, size)

    video_id = response.get("id")
    result = {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "studio": f"https://studio.youtube.com/video/{video_id}/edit",
        "title": response.get("snippet", {}).get("title", body["snippet"]["title"]),
        "privacy": response.get("status", {}).get("privacyStatus", body["status"]["privacyStatus"]),
        "thumbnail": False, "playlist": False,
    }

    # thumbnail (needs a verified channel; failure is not fatal)
    if thumb_path and os.path.isfile(thumb_path):
        try:
            service.thumbnails().set(videoId=video_id,
                                     media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")).execute()
            result["thumbnail"] = True
        except Exception as e:
            logger.warning("thumbnail set failed: %s", str(e)[:200])
            result["thumbnail_error"] = str(e)[:160]
    if meta.get("playlist_id"):
        try:
            service.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": meta["playlist_id"],
                "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
            result["playlist"] = True
        except Exception as e:
            logger.warning("playlist add failed: %s", str(e)[:200])
    return result


async def upload_video(admin_id: int, video_path: str, meta: Dict[str, Any], thumb_path: Optional[str] = None,
                       on_progress: Optional[Callable[[int, int], Any]] = None,
                       is_cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """
    Resumable upload in a worker thread. `on_progress(sent, total)` may be a coroutine function —
    it is scheduled on the loop (throttling is the caller's job).
    """
    loop = asyncio.get_running_loop()

    def _progress(sent: int, total: int):
        if not on_progress:
            return
        try:
            res = on_progress(sent, total)
            if asyncio.iscoroutine(res):
                asyncio.run_coroutine_threadsafe(res, loop)
        except Exception:
            pass

    def _cancelled() -> bool:
        try:
            return bool(is_cancelled and is_cancelled())
        except Exception:
            return False

    return await asyncio.to_thread(_upload_sync, admin_id, video_path, meta, thumb_path, _progress, _cancelled)


# =====================================================================================
#  helpers for the plugin
# =====================================================================================
def guess_title_artist(audio_info: Dict[str, Any], fallback_filename: str = "") -> Tuple[str, str]:
    """Title / artist from the audio tags, else from the file name ('Artist - Title.mp3')."""
    title = (audio_info or {}).get("title") or ""
    artist = (audio_info or {}).get("artist") or ""
    if not title and fallback_filename:
        base = os.path.splitext(os.path.basename(fallback_filename))[0]
        base = re.sub(r"[_\.]+", " ", base)
        base = re.sub(r"\b(official|video|audio|lyrics?|hd|4k|mp3|\d{2,3}\s?kbps|full song|with lyrics)\b",
                      "", base, flags=re.I)
        base = re.sub(r"[\(\[\{]\s*[\)\]\}]", "", base)          # leftover empty ( ) [ ]
        base = re.sub(r"\s{2,}", " ", base).strip(" -–|")
        if " - " in base and not artist:
            artist, title = [p.strip() for p in base.split(" - ", 1)]
        else:
            title = base
    return (title or "Untitled").strip()[:MAX_TITLE], artist.strip()[:60]


def token_howto() -> str:
    return (
        "🔑 **How to create token.pickle (one time, on a PC)**\n\n"
        "1. Google Cloud Console → create a project → enable **YouTube Data API v3**\n"
        "2. OAuth consent screen → *External* → add your Google account as a **test user**\n"
        "3. Credentials → **OAuth client ID** → *Desktop app* → download `client_secret.json`\n"
        "4. Run this once (`pip install google-auth-oauthlib`):\n"
        "```python\n"
        "import pickle\n"
        "from google_auth_oauthlib.flow import InstalledAppFlow\n"
        "SCOPES=['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube']\n"
        "creds=InstalledAppFlow.from_client_secrets_file('client_secret.json',SCOPES).run_local_server(port=0)\n"
        "pickle.dump(creds,open('token.pickle','wb'))\n"
        "```\n"
        "5. Log in with the **channel's Google account** and allow access\n"
        "6. Send the created **token.pickle** here as a file 📎\n\n"
        "The token is stored for you only and reused for every upload. "
        "Use `/yt_logout` to delete it."
    )
