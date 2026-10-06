"""
📺 YouTube upload — admins only.

After `convert.py` delivers a video to an admin it keeps the file as a `PendingOutput` and
calls `ask_upload()` here. The admin taps **Yes** → if no token is stored we ask for
`token.pickle` (document handler below) → metadata is generated from an SEO template →
review / edit → **🚀 Upload now** → progress bar → link. **No** (or the TTL) deletes the file.

Callback data:  yt:<action>[:<value>]
"""
import logging
import os
import time
import uuid
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db
from core.helpers import is_admin
from core.keyboards import (
    yt_prompt_keyboard, yt_token_wait_keyboard, yt_meta_keyboard, yt_templates_keyboard, yt_edit_keyboard,
    yt_upload_progress_keyboard, yt_done_keyboard, yt_panel_keyboard, yt_default_templates_keyboard,
    yt_default_privacy_keyboard,
)
from core.state import state, PendingOutput
from core import youtube as yt
from core.strings import (
    YT_PROMPT, YT_TOKEN_OK_LINE, YT_TOKEN_MISSING_LINE, YT_NEED_TOKEN, YT_TOKEN_SAVED, YT_TOKEN_SAVED_NOVERIFY,
    YT_NOTHING_PENDING, YT_EXPIRED, YT_SKIPPED, YT_EDIT_PROMPT, YT_UPLOADING, YT_DONE, YT_FAILED, YT_TOKEN_BAD,
)
from core.utils import cleanup, humanbytes, format_duration, format_time, progress_bar_str

logger = logging.getLogger(__name__)

admin_filter = filters.create(lambda _, __, m: bool(m.from_user and is_admin(m.from_user.id)))

# cache of channel titles so the prompt can show them without an API call
_channel_cache: dict = {}


def enabled() -> bool:
    return Config.YT_UPLOAD_ENABLED


# ================================================================ entry from convert.py
async def ask_upload(client: Client, uid: int, pending: PendingOutput, reply_to: Optional[Message] = None):
    """Called by the pipeline right after the video reached Telegram (admins only)."""
    if not enabled() or not is_admin(uid):
        cleanup(*pending.files())
        return
    old = state.set_pending(uid, pending)
    if old and old is not pending and not old.uploading:
        cleanup(*old.files())
    has_token = yt.has_token(uid)
    channel = _channel_cache.get(uid)
    line = YT_TOKEN_OK_LINE.format(channel=channel or "your channel") if has_token else YT_TOKEN_MISSING_LINE
    text = YT_PROMPT.format(size=humanbytes(pending.size), duration=format_duration(pending.duration),
                            token_line=line, ttl=Config.YT_PENDING_TTL_SEC // 60)
    try:
        if reply_to:
            msg = await reply_to.reply_text(text, reply_markup=yt_prompt_keyboard(has_token), quote=True)
        else:
            msg = await client.send_message(uid, text, reply_markup=yt_prompt_keyboard(has_token))
        pending.prompt_msg_id = msg.id
    except Exception as e:
        logger.warning("yt prompt: %s", e)


# ================================================================ helpers
def _pending_or_none(uid: int) -> Optional[PendingOutput]:
    p = state.get_pending(uid)
    if not p:
        return None
    if not os.path.isfile(p.path):
        state.pop_pending(uid)
        cleanup(*p.files())
        return None
    return p


async def _edit(cq_or_msg, text: str, kb=None):
    try:
        if isinstance(cq_or_msg, CallbackQuery):
            await cq_or_msg.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        else:
            await cq_or_msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            logger.debug("yt edit: %s", e)


async def _defaults(uid: int) -> tuple:
    s = await db.get_settings(uid)
    tpl = s.get("yt_template") or Config.YT_DEFAULT_TEMPLATE
    if tpl not in yt.TEMPLATES:
        tpl = "music"
    priv = s.get("yt_privacy") or Config.YT_DEFAULT_PRIVACY
    if priv not in yt.PRIVACY_OPTIONS:
        priv = "public"
    return tpl, priv


def _chapters(p: PendingOutput):
    """Timestamps for merged audio files: [(start_sec, name), ...]."""
    if len(p.audio_files) < 2 or len(p.audio_durations) != len(p.audio_files):
        return None
    out, t = [], 0.0
    for f, d in zip(p.audio_files, p.audio_durations):
        name, _ = yt.guess_title_artist({}, f)
        out.append((t, name))
        t += float(d or 0)
    return out


async def _generate_meta(uid: int, p: PendingOutput, template: Optional[str] = None, privacy: Optional[str] = None):
    d_tpl, d_priv = await _defaults(uid)
    template = template or p.meta.get("template") or d_tpl
    privacy = privacy or p.meta.get("privacy") or d_priv
    title, artist = yt.guess_title_artist(p.audio_info, p.audio_files[0] if p.audio_files else "")
    meta = yt.build_metadata(template, title, artist, p.duration, privacy, chapters=_chapters(p))
    meta["_title"], meta["_artist"] = title, artist
    p.meta = meta
    return meta


def _ctx(p: PendingOutput) -> dict:
    hours, _ = yt._hours_label(p.duration)
    return {"title": p.meta.get("_title", ""), "artist": p.meta.get("_artist", ""), "hours": hours or "1",
            "duration": format_duration(p.duration), "hashtags": "", "chapters": ""}


async def _show_meta(cq_or_msg, p: PendingOutput, status_line: str = ""):
    text = yt.metadata_preview(p.meta, humanbytes(p.size), status_line)
    await _edit(cq_or_msg, text, yt_meta_keyboard(p.meta, bool(p.thumb)))


async def _after_token(client: Client, uid: int, msg: Message):
    """Token is in place → go on with the pending video (if any) or show the panel."""
    p = _pending_or_none(uid)
    if p:
        await _generate_meta(uid, p)
        sent = await msg.reply_text(yt.metadata_preview(p.meta, humanbytes(p.size)),
                                    reply_markup=yt_meta_keyboard(p.meta, bool(p.thumb)),
                                    disable_web_page_preview=True)
        p.prompt_msg_id = sent.id
    else:
        await send_panel(msg, uid)


# ================================================================ panel  (/youtube, Admin → 📺)
async def panel_text(uid: int) -> str:
    has = yt.has_token(uid)
    p = _pending_or_none(uid)
    tpl, priv = await _defaults(uid)
    rows = await db.yt_uploads(uid, 5)
    lines = ["📺 **YouTube**", ""]
    if has:
        ch = _channel_cache.get(uid)
        lines.append("🔑 Token: ✅ stored" + (f" · 📡 **{ch}**" if ch else ""))
    else:
        lines.append("🔑 Token: ❌ not set — send **token.pickle** as a file any time.")
    if p:
        left = max(0, int((Config.YT_PENDING_TTL_SEC - (time.time() - p.created_at)) // 60))
        lines.append(f"📦 Waiting video: {humanbytes(p.size)} · {format_duration(p.duration)} (deleted in {left} min)")
    lines.append(f"🎨 Default template: {yt.TEMPLATES[tpl].label} · 🔒 {priv}")
    if rows:
        lines += ["", f"🕘 **Last uploads** ({await db.yt_upload_count()} total)"]
        for r in rows:
            lines.append(f"• [{(r['title'] or '?')[:40]}](https://youtu.be/{r['video_id']}) — "
                         f"{time.strftime('%d %b', time.localtime(r['created_at']))} · {r['privacy']}")
    return "\n".join(lines)


async def send_panel(message_or_cq, uid: int):
    has = yt.has_token(uid)
    tpl, priv = await _defaults(uid)
    kb = yt_panel_keyboard(has, _pending_or_none(uid) is not None, tpl, priv)
    text = await panel_text(uid)
    if isinstance(message_or_cq, CallbackQuery):
        await _edit(message_or_cq, text, kb)
    else:
        await message_or_cq.reply_text(text, reply_markup=kb, disable_web_page_preview=True)


@Client.on_message(filters.command(["youtube", "yt"]) & filters.private & admin_filter)
async def youtube_cmd(client: Client, message: Message):
    if not enabled():
        await message.reply_text("📺 YouTube upload is disabled (`YT_UPLOAD_ENABLED=false`).")
        return
    await send_panel(message, message.from_user.id)


@Client.on_message(filters.command("yt_token") & filters.private & admin_filter)
async def yt_token_cmd(client: Client, message: Message):
    await message.reply_text(yt.token_howto(), disable_web_page_preview=True)


@Client.on_message(filters.command("yt_logout") & filters.private & admin_filter)
async def yt_logout_cmd(client: Client, message: Message):
    uid = message.from_user.id
    ok = yt.delete_token(uid)
    _channel_cache.pop(uid, None)
    await message.reply_text("🗑 Token deleted." if ok else "ℹ️ No token was stored.")


@Client.on_message(filters.command("yt_history") & filters.private & admin_filter)
async def yt_history_cmd(client: Client, message: Message):
    rows = await db.yt_uploads(None, 15)
    if not rows:
        await message.reply_text("🕘 No YouTube uploads yet.")
        return
    lines = [f"🕘 **YouTube uploads** ({await db.yt_upload_count()} total)\n"]
    for r in rows:
        lines.append(f"• [{(r['title'] or '?')[:45]}](https://youtu.be/{r['video_id']}) — `{r['user_id']}` · "
                     f"{time.strftime('%d %b %H:%M', time.localtime(r['created_at']))} · {humanbytes(r['size'])} · "
                     f"{r['privacy']} · ⏱ {format_time(r['upload_time'])}")
    await message.reply_text("\n".join(lines), disable_web_page_preview=True)


# ================================================================ token.pickle intake
def _looks_like_token(doc) -> bool:
    name = (doc.file_name or "").lower()
    return name.endswith((".pickle", ".pkl")) or name in ("token.json", "token", "credentials.json") \
        or (name.endswith(".json") and "token" in name)


# group=-1 → runs before media.document_handler (group 0); propagation stops when we take the file
@Client.on_message(filters.private & filters.document & admin_filter, group=-1)
async def token_document(client: Client, message: Message):
    if not enabled():
        return
    doc = message.document
    if not _looks_like_token(doc):
        return
    try:
        await _handle_token_document(client, message)
    except Exception as e:
        logger.exception("token intake: %s", e)
    message.stop_propagation()          # raises StopPropagation -> media.document_handler never sees it


async def _handle_token_document(client: Client, message: Message):
    doc = message.document
    uid = message.from_user.id
    if (doc.file_size or 0) > 512 * 1024:
        await message.reply_text("⚠️ That does not look like a token file (too big).")
        return
    status = await message.reply_text("🔑 Checking the token…")
    tmp = os.path.join(Config.DOWNLOAD_DIR, f"token_{uid}_{uuid.uuid4().hex[:6]}.tmp")
    try:
        await message.download(file_name=tmp)
        try:
            info = await yt.import_token(tmp, uid, verify=True)
        except yt.TokenError as e:
            await status.edit_text(YT_TOKEN_BAD.format(error=str(e)),
                                   reply_markup=yt_token_wait_keyboard() if _pending_or_none(uid) else None)
            return
        except yt.YouTubeError as e:
            await status.edit_text(f"⚠️ Could not verify the token right now: {e}\nTry again in a minute.")
            return
    except Exception as e:
        logger.warning("token download: %s", e)
        await status.edit_text("❌ Could not download the file. Send it again.")
        return
    finally:
        cleanup(tmp)
    # remove the secret from the chat
    try:
        await message.delete()
    except Exception:
        pass
    nxt = ("📤 Continuing with your video below 👇" if _pending_or_none(uid)
           else "You will be asked **Upload to YouTube?** after every finished video.")
    if info:
        _channel_cache[uid] = info.get("title")
        url = f" (youtube.com/{info['custom_url']})" if info.get("custom_url") else ""
        await status.edit_text(YT_TOKEN_SAVED.format(title=info.get("title", "?"), url=url, subs=info.get("subs", "?"),
                                                     videos=info.get("videos", "?"), next=nxt))
    else:
        await status.edit_text(YT_TOKEN_SAVED_NOVERIFY.format(reason="API unreachable", next=nxt))
    await _after_token(client, uid, status)


# ================================================================ text input for title / description / tags
# group=-2 → before media.text_input_handler (group 1) so "yt_*" awaiting keys never reach it
@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/") & admin_filter, group=-2)
async def yt_text_input(client: Client, message: Message):
    uid = message.from_user.id
    session = state.get(uid) if state.exists(uid) else None
    if not session or not (session.awaiting or "").startswith("yt_"):
        return
    from core.keyboards import REPLY_BUTTONS, ADMIN_BUTTONS
    if message.text in REPLY_BUTTONS or message.text in ADMIN_BUTTONS:
        session.awaiting = None                   # bottom-keyboard tap = leave edit mode, let start.py handle it
        session.awaiting_msg_id = None
        return
    try:
        await _handle_yt_text(client, message, session)
    except Exception as e:
        logger.exception("yt text input: %s", e)
    message.stop_propagation()


async def _handle_yt_text(client: Client, message: Message, session):
    uid = message.from_user.id
    field = session.awaiting[3:]
    session.awaiting = None
    p = _pending_or_none(uid)
    if not p:
        await message.reply_text(YT_EXPIRED)
        return
    value = message.text.strip()
    ctx = _ctx(p)
    if field == "title":
        value = yt._fill(value, ctx).strip()
        if not value:
            session.awaiting = "yt_title"
            await message.reply_text("⚠️ Title cannot be empty.")
            return
        p.meta["title"] = value[:yt.MAX_TITLE]
    elif field == "description":
        tpl = yt.TEMPLATES.get(p.meta.get("template", ""), yt.TEMPLATES["music"])
        hctx = {**ctx, "title_tag": yt._tag_word(ctx["title"]) or "music",
                "artist_tag": yt._tag_word(ctx["artist"]) or "music"}
        ctx["hashtags"] = " ".join(yt._dedupe([yt._fill(h, hctx) for h in tpl.hashtags])[:6])
        chapters = _chapters(p)
        if chapters:
            ctx["chapters"] = "⏰ Timestamps:\n" + "\n".join(
                f"{('00:' + format_duration(s)) if len(format_duration(s)) == 5 else format_duration(s)} {n}"
                for s, n in chapters) + "\n"
        p.meta["description"] = yt._fill(value, ctx).strip()[:yt.MAX_DESC]
    elif field == "tags":
        tags = yt._dedupe(value.replace("\n", ",").split(","))
        total, clipped = 0, []
        for t in tags:
            if total + len(t) + 2 > yt.MAX_TAGS_CHARS:
                break
            clipped.append(t[:60])
            total += len(t) + 2
        p.meta["tags"] = clipped
    try:
        await message.delete()
    except Exception:
        pass
    preview = yt.metadata_preview(p.meta, humanbytes(p.size), f"✅ {field} updated")
    if session.awaiting_msg_id:
        mid, session.awaiting_msg_id = session.awaiting_msg_id, None
        try:
            await client.edit_message_text(uid, mid, preview, reply_markup=yt_meta_keyboard(p.meta, bool(p.thumb)),
                                           disable_web_page_preview=True)
            return
        except Exception:
            pass
    sent = await message.reply_text(preview, reply_markup=yt_meta_keyboard(p.meta, bool(p.thumb)),
                                    disable_web_page_preview=True)
    p.prompt_msg_id = sent.id


# ================================================================ callbacks
@Client.on_callback_query(filters.regex(r"^yt:(\w+)(?::([\w\-]+))?$"))
async def yt_cb(client: Client, cq: CallbackQuery):
    uid = cq.from_user.id
    if not is_admin(uid):
        await cq.answer("⛔ Admins only", show_alert=True)
        return
    if not enabled():
        await cq.answer("YouTube upload is disabled.", show_alert=True)
        return
    action = cq.matches[0].group(1)
    value = cq.matches[0].group(2)

    # ---- panel & defaults (no pending video needed)
    if action == "panel":
        await send_panel(cq, uid)
        await cq.answer()
        return
    if action == "howto":
        kb = yt_token_wait_keyboard() if _pending_or_none(uid) else \
            yt_panel_keyboard(yt.has_token(uid), False, *(await _defaults(uid)))
        await _edit(cq, yt.token_howto(), kb)
        await cq.answer()
        return
    if action == "check":
        await cq.answer("📡 Asking YouTube…")
        d = await _defaults(uid)
        try:
            info = await yt.channel_info(uid)
            _channel_cache[uid] = info.get("title")
            url = f"\nhttps://youtube.com/{info['custom_url']}" if info.get("custom_url") else ""
            await _edit(cq, f"📡 **Channel OK**\n\n📺 **{info['title']}**{url}\n👥 {info['subs']} subscribers · "
                            f"🎞 {info['videos']} videos\n\n" + await panel_text(uid),
                        yt_panel_keyboard(True, _pending_or_none(uid) is not None, *d))
        except yt.TokenError as e:
            await _edit(cq, YT_TOKEN_BAD.format(error=str(e)), yt_panel_keyboard(yt.has_token(uid), False, *d))
        except Exception as e:
            await _edit(cq, f"❌ {type(e).__name__}: {str(e)[:200]}", yt_panel_keyboard(True, False, *d))
        return
    if action == "logout":
        yt.delete_token(uid)
        _channel_cache.pop(uid, None)
        await cq.answer("🗑 Token deleted", show_alert=True)
        await send_panel(cq, uid)
        return
    if action == "deftpl":
        if value and value in yt.TEMPLATES:
            await db.update_setting(uid, "yt_template", value)
            await cq.answer(f"Default: {yt.TEMPLATES[value].label}")
            await send_panel(cq, uid)
        else:
            tpl, _ = await _defaults(uid)
            await _edit(cq, "🎨 **Default SEO template** — used for every new upload:", yt_default_templates_keyboard(tpl))
            await cq.answer()
        return
    if action == "defpriv":
        if value and value in yt.PRIVACY_OPTIONS:
            await db.update_setting(uid, "yt_privacy", value)
            await cq.answer(f"Default privacy: {value}")
            await send_panel(cq, uid)
        else:
            _, priv = await _defaults(uid)
            await _edit(cq, "🔒 **Default privacy** for new uploads:", yt_default_privacy_keyboard(priv))
            await cq.answer()
        return

    # ---- everything below needs the pending video
    p = _pending_or_none(uid)
    if action == "skip":
        if p and not p.uploading:
            state.pop_pending(uid)
            cleanup(*p.files())
        session = state.get(uid) if state.exists(uid) else None
        if session and (session.awaiting or "").startswith("yt_"):
            session.awaiting = None
            session.awaiting_msg_id = None
        await _edit(cq, YT_SKIPPED)
        await cq.answer()
        return
    if action == "cancel_upload":
        if p and p.uploading:
            p.cancel_upload = True
            await cq.answer("🛑 Cancelling the upload…")
        else:
            await cq.answer("No upload is running.", show_alert=True)
        return
    if not p:
        await _edit(cq, YT_NOTHING_PENDING if action == "ask" else YT_EXPIRED)
        await cq.answer()
        return
    if p.uploading:
        await cq.answer("⏳ Upload in progress…", show_alert=True)
        return

    if action == "ask":
        if not yt.has_token(uid):
            await _edit(cq, YT_NEED_TOKEN, yt_token_wait_keyboard())
            await cq.answer()
            return
        if not p.meta:
            await _generate_meta(uid, p)
        p.prompt_msg_id = cq.message.id
        await _show_meta(cq, p)
        await cq.answer()
        return
    if action == "meta":
        session = state.get(uid)
        if (session.awaiting or "").startswith("yt_"):
            session.awaiting = None
            session.awaiting_msg_id = None
        if not p.meta:
            await _generate_meta(uid, p)
        await _show_meta(cq, p)
        await cq.answer()
        return
    if action == "regen":
        await _generate_meta(uid, p)
        await _show_meta(cq, p, "🔁 Regenerated from the template")
        await cq.answer("Regenerated")
        return
    if action == "templates":
        await _edit(cq, "🎨 **SEO template** — title, description, tags & hashtags are rebuilt:",
                    yt_templates_keyboard(p.meta.get("template", "music")))
        await cq.answer()
        return
    if action == "template" and value in yt.TEMPLATES:
        await _generate_meta(uid, p, template=value)
        await _show_meta(cq, p, f"🎨 Template: {yt.TEMPLATES[value].label}")
        await cq.answer()
        return
    if action == "privacy" and value in yt.PRIVACY_OPTIONS:
        p.meta["privacy"] = value
        await _show_meta(cq, p)
        await cq.answer(f"🔒 {value}")
        return
    if action == "preview":
        meta = p.meta
        text = (f"🏷 **{meta['title']}**\n\n{meta['description']}\n\n🔖 `{', '.join(meta['tags'])}`")[:4000]
        await _edit(cq, text, yt_edit_keyboard())
        await cq.answer()
        return
    if action == "edit" and value in YT_EDIT_PROMPT:
        session = state.get(uid)
        session.awaiting = f"yt_{value}"
        session.awaiting_msg_id = cq.message.id
        cur = p.meta.get(value, "")
        if isinstance(cur, list):
            cur = ", ".join(cur)
        cur_s = f"\n\nCurrent:\n`{cur[:600]}`" if cur else ""
        await _edit(cq, YT_EDIT_PROMPT[value] + cur_s, yt_edit_keyboard())
        await cq.answer("Send the text as a message")
        return
    if action == "upload":
        await cq.answer("🚀 Uploading…")
        await run_upload(client, uid, p, cq.message)
        return
    await cq.answer()


# ================================================================ upload
async def run_upload(client: Client, uid: int, p: PendingOutput, status: Message):
    if not p.meta:
        await _generate_meta(uid, p)
    p.uploading = True
    p.cancel_upload = False
    t0 = time.time()
    last = {"t": 0.0}

    async def on_progress(sent: int, total: int):
        now = time.time()
        if sent < total and now - last["t"] < 4:
            return
        last["t"] = now
        elapsed = max(now - t0, 0.001)
        speed = sent / elapsed
        eta = (total - sent) / speed if speed > 0 else 0
        pct = sent * 100 / total if total else 0
        try:
            await status.edit_text(
                YT_UPLOADING.format(bar=progress_bar_str(pct), pct=pct, sent=humanbytes(sent), total=humanbytes(total),
                                    speed=humanbytes(speed), eta=format_time(eta), title=p.meta.get("title", "")),
                reply_markup=yt_upload_progress_keyboard(), disable_web_page_preview=True)
        except Exception:
            pass

    try:
        await status.edit_text("📤 **Uploading to YouTube…** connecting", reply_markup=yt_upload_progress_keyboard())
    except Exception:
        pass
    try:
        result = await yt.upload_video(uid, p.path, p.meta, p.thumb, on_progress=on_progress,
                                       is_cancelled=lambda: p.cancel_upload)
        took = time.time() - t0
        await db.record_yt_upload(uid, result["video_id"], result["title"], result["privacy"], p.size, p.duration,
                                  p.meta.get("template", ""), took)
        state.pop_pending(uid)
        cleanup(*p.files())
        thumb_s = "✅" if result.get("thumbnail") else ("⚠️ not set" if p.thumb else "—")
        await _edit(status, YT_DONE.format(title=result["title"], privacy=result["privacy"], thumb=thumb_s,
                                           took=format_time(took), url=result["url"]),
                    yt_done_keyboard(result["url"], result["studio"]))
        if Config.LOG_CHANNEL:
            try:
                await client.send_message(Config.LOG_CHANNEL,
                                          f"#YT_UPLOAD\n👤 `{uid}`\n🏷 {result['title']}\n🔒 {result['privacy']} · "
                                          f"{humanbytes(p.size)} · ⏱ {format_time(took)}\n{result['url']}",
                                          disable_web_page_preview=True)
            except Exception:
                pass
    except yt.TokenError as e:
        yt.delete_token(uid)
        _channel_cache.pop(uid, None)
        p.created_at = time.time()
        await _edit(status, YT_TOKEN_BAD.format(error=str(e)), yt_token_wait_keyboard())
    except yt.YouTubeError as e:
        if "cancel" in str(e).lower():
            p.created_at = time.time()      # give the admin the full TTL again
            await _edit(status, "🛑 **Upload cancelled.** The video is still here — tap 🚀 to try again.",
                        yt_meta_keyboard(p.meta, bool(p.thumb)))
        else:
            logger.error("YouTube upload failed uid=%s: %s", uid, e)
            await _edit(status, YT_FAILED.format(error=str(e)), yt_meta_keyboard(p.meta, bool(p.thumb)))
    except Exception as e:
        logger.exception("YouTube upload crashed uid=%s", uid)
        await _edit(status, YT_FAILED.format(error=f"`{type(e).__name__}: {str(e)[:300]}`"),
                    yt_meta_keyboard(p.meta, bool(p.thumb)))
    finally:
        p.uploading = False
