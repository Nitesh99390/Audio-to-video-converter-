"""Settings panels (main / advanced / effects), option menus, toggles, quick modes, presets, text inputs."""
import logging

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from core.config import Config
from core.database import db, DEFAULT_SETTINGS
from core.helpers import gate, gate_cb, get_settings
from core.keyboards import (
    settings_keyboard, advanced_keyboard, effects_keyboard, option_keyboard, options_for, OPTIONS, OPTION_TITLES,
    PANEL_OF, watermark_keyboard, title_keyboard, caption_keyboard, slideshow_keyboard, input_cancel_keyboard,
    confirm_keyboard, presets_keyboard, quick_modes_keyboard, quick_modes_for, QUICK_MODES,
    duration_keyboard, duration_label,
)
from core.policy import can_use_pro, apply_policy
from core.state import state

logger = logging.getLogger(__name__)

SETTINGS_TEXT = "⚙️ **Settings**\nTap an option to change it."
ADVANCED_TEXT = "🔧 **Advanced**\nFine-tuning — the defaults are fine for most videos."
EFFECTS_TEXT = "✨ **Effects** (Pro engine)\nVisualizer and motion effects. Renders take longer."
QUICK_TEXT = "⚡ **Quick Modes**\nOne tap applies a ready-made profile. Fine-tune later in Settings."
DURATION_TEXT = ("⏱ **Final video length**\n\nLonger than the audio → the audio is looped seamlessly. "
                 "Shorter → the video is trimmed.\n\nCurrent: **{cur}**")
INT_KEYS = {"fps", "slideshow_duration", "target_duration"}
TOGGLE_KEYS = {"engine", "ken_burns", "fade", "spoiler"}
PRO_ONLY_MENUS = {"visualizer", "vis_color", "vis_position", "slideshow_transition", "engine"}


async def _edit(cq: CallbackQuery, text: str, kb):
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            logger.debug("edit fail: %s", e)


def _presets_text(names):
    if not names:
        return "🎛 **Presets**\n\nNothing saved yet. Configure Settings, then tap 💾 Save."
    return "🎛 **Presets**\n\nTap to load · 🗑 to delete."


async def show_panel(cq: CallbackQuery, uid: int, panel: str, prefix: str = ""):
    """Render one of the settings panels into an existing message."""
    s = await get_settings(uid)
    if panel == "advanced":
        await _edit(cq, prefix + ADVANCED_TEXT, advanced_keyboard(s))
    elif panel == "effects":
        if not (can_use_pro(uid) and s.get("engine") == "pro"):
            await _edit(cq, prefix + SETTINGS_TEXT, settings_keyboard(s, uid))
        else:
            await _edit(cq, prefix + EFFECTS_TEXT, effects_keyboard(s))
    elif panel == "menu_watermark":
        await _edit(cq, _wm_text(s), watermark_keyboard(s))
    elif panel == "menu_title":
        await _edit(cq, _title_text(s), title_keyboard(s))
    elif panel == "menu_slideshow":
        await _edit(cq, "🎞 **Slideshow**\n\nApplies when you send 2+ photos.", slideshow_keyboard(s, uid))
    elif panel == "quick":
        await _edit(cq, prefix + QUICK_TEXT, quick_modes_keyboard(uid))
    elif panel == "presets":
        names = await db.list_presets(uid)
        await _edit(cq, _presets_text(names), presets_keyboard(names))
    else:
        await _edit(cq, prefix + SETTINGS_TEXT, settings_keyboard(s, uid))


def _wm_text(s):
    return f"💧 **Watermark**\n\nText: {s.get('watermark_text') or '_none_'}\nPosition: {s['watermark_position']}"


def _title_text(s):
    return f"🔤 **Title**\n\nText: {s.get('title_text') or '_none_'}\nPosition: {s['title_position']}"


# ================================================================ commands
@Client.on_message(filters.command("settings") & filters.private)
async def settings_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    uid = message.from_user.id
    s = await get_settings(uid)
    await message.reply_text(SETTINGS_TEXT, reply_markup=settings_keyboard(s, uid))


@Client.on_message(filters.command("quick") & filters.private)
async def quick_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    await message.reply_text(QUICK_TEXT, reply_markup=quick_modes_keyboard(message.from_user.id))


@Client.on_message(filters.command("duration") & filters.private)
async def duration_cmd(client: Client, message: Message):
    """/duration -> menu | /duration 10h -> set directly"""
    if not await gate(client, message):
        return
    uid = message.from_user.id
    if len(message.command) > 1:
        from core.helpers import parse_duration_text
        secs = parse_duration_text(" ".join(message.command[1:]))
        if secs is None or secs < 0:
            await message.reply_text("❌ Could not parse. Examples: `10h`, `2h30m`, `90m`, `1:30:00`, `0` (same as audio)")
            return
        secs = min(secs, Config.MAX_OUTPUT_DURATION_SEC)
        await db.update_setting(uid, "target_duration", int(secs))
        await message.reply_text(f"✅ Final length: **{duration_label(int(secs))}**")
        return
    s = await get_settings(uid)
    cur = int(s.get("target_duration") or 0)
    await message.reply_text(DURATION_TEXT.format(cur=duration_label(cur)), reply_markup=duration_keyboard(cur))


@Client.on_message(filters.command("presets") & filters.private)
async def presets_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    names = await db.list_presets(message.from_user.id)
    await message.reply_text(_presets_text(names), reply_markup=presets_keyboard(names))


@Client.on_message(filters.command("preset") & filters.private)
async def preset_cmd(client: Client, message: Message):
    """/preset save <name> | /preset load <name> | /preset del <name>"""
    if not await gate(client, message):
        return
    uid = message.from_user.id
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply_text("Usage: `/preset save <name>` · `/preset load <name>` · `/preset del <name>`")
        return
    action, name = parts[1].lower(), parts[2].strip()[:30]
    if action == "save":
        await db.save_preset(uid, name, await get_settings(uid))
        await message.reply_text(f"💾 Preset **{name}** saved.")
    elif action == "load":
        data = await db.get_preset(uid, name)
        if not data:
            await message.reply_text("❌ Preset not found.")
            return
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        merged, _ = apply_policy(uid, merged)
        await db.save_settings(uid, merged)
        await message.reply_text(f"✅ Preset **{name}** loaded.", reply_markup=settings_keyboard(merged, uid))
    elif action in ("del", "delete"):
        await db.delete_preset(uid, name)
        await message.reply_text(f"🗑 Preset **{name}** deleted.")


# ================================================================ panels / navigation
@Client.on_callback_query(filters.regex(r"^nav:(advanced|effects|quick|presets)$"))
async def panel_nav_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    await show_panel(cq, cq.from_user.id, cq.matches[0].group(1))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^nav:menu_(\w+)$"))
async def nav_submenu_cb(client: Client, cq: CallbackQuery):
    """Back buttons from nested option menus (e.g. back to watermark menu)."""
    if not await gate_cb(client, cq):
        return
    await show_panel(cq, cq.from_user.id, "menu_" + cq.matches[0].group(1))
    await cq.answer()


# ================================================================ option menus
@Client.on_callback_query(filters.regex(r"^menu:(\w+)$"))
async def menu_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    key = cq.matches[0].group(1)
    uid = cq.from_user.id
    s = await get_settings(uid)

    if key in PRO_ONLY_MENUS and not can_use_pro(uid):
        await cq.answer("This option is part of the Pro engine (admins only).", show_alert=True)
        return

    if key == "target_duration":
        cur = int(s.get("target_duration") or 0)
        await _edit(cq, DURATION_TEXT.format(cur=duration_label(cur)), duration_keyboard(cur))
    elif key == "watermark":
        await _edit(cq, _wm_text(s), watermark_keyboard(s))
    elif key == "title":
        await _edit(cq, _title_text(s), title_keyboard(s))
    elif key == "caption":
        c = s.get("custom_caption") or "_default_"
        await _edit(cq, "📝 **Caption**\n\nCurrent: " + c +
                    "\n\nPlaceholders: `{title}` `{artist}` `{duration}` `{size}` `{resolution}` `{bot_name}`",
                    caption_keyboard(s))
    elif key == "slideshow":
        await show_panel(cq, uid, "menu_slideshow")
    elif key == "output":
        await _edit(cq, OPTION_TITLES["output_mode"], option_keyboard("output_mode", s["output_mode"], back="advanced"))
    elif key in OPTIONS:
        back = PANEL_OF.get(key, "settings")
        await _edit(cq, OPTION_TITLES.get(key, key), option_keyboard(key, s.get(key), back=back, opts=options_for(key, s, uid)))
    await cq.answer()


# ================================================================ set value
@Client.on_callback_query(filters.regex(r"^set:(\w+):(.*)$"))
async def set_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    key, value = cq.matches[0].group(1), cq.matches[0].group(2)
    uid = cq.from_user.id

    if key == "reset":
        if value == "confirm":
            await _edit(cq, "♻️ **Reset every setting to default?**", confirm_keyboard("set:reset:yes"))
            await cq.answer()
            return
        await db.reset_settings(uid)
        s = await get_settings(uid)
        await _edit(cq, "♻️ Settings reset.\n\n" + SETTINGS_TEXT, settings_keyboard(s, uid))
        await cq.answer("Reset done")
        return

    if key in INT_KEYS:
        try:
            value = int(value)
        except ValueError:
            await cq.answer("Invalid value")
            return
    s = await get_settings(uid)
    if key in OPTIONS and str(value) not in [str(o) for o in options_for(key, s, uid)]:
        await cq.answer("That option is not available for your account.", show_alert=True)
        return
    if key == "engine" and value == "pro" and not can_use_pro(uid):
        await cq.answer("Pro engine is available to admins only.", show_alert=True)
        return
    if key == "target_duration":
        value = max(0, min(int(value), Config.MAX_OUTPUT_DURATION_SEC))

    s = await db.update_setting(uid, key, value)
    s, _ = apply_policy(uid, s)
    await db.save_settings(uid, s)

    if key == "target_duration":
        await cq.answer(f"Final length: {duration_label(int(value))}")
    else:
        await cq.answer(f"{key.replace('_', ' ').title()}: {value or 'off'}")
    await show_panel(cq, uid, PANEL_OF.get(key, "settings"))


# ================================================================ toggles
@Client.on_callback_query(filters.regex(r"^toggle:(\w+)$"))
async def toggle_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    key = cq.matches[0].group(1)
    uid = cq.from_user.id
    if key not in TOGGLE_KEYS:
        await cq.answer("Unknown toggle")
        return
    s = await get_settings(uid)
    if key == "engine":
        if not can_use_pro(uid):
            await cq.answer("Pro engine is available to admins only.", show_alert=True)
            return
        new = "pro" if s.get("engine", "lite") == "lite" else "lite"
    else:
        if key in ("ken_burns", "fade") and not can_use_pro(uid):
            await cq.answer("Effects need the Pro engine (admins only).", show_alert=True)
            return
        new = not bool(s.get(key))
    s[key] = new
    s, _ = apply_policy(uid, s)
    await db.save_settings(uid, s)
    label = new.upper() if isinstance(new, str) else ("on" if new else "off")
    await cq.answer(f"{key.replace('_', ' ').title()}: {label}")
    if key == "engine":
        note = ("⚡ **Lite** — 10 h video in ~2 min, tiny file.\n\n" if new == "lite"
                else "🎬 **Pro** — full re-encode with effects. Long audio takes long!\n\n")
        await show_panel(cq, uid, "settings", prefix=note)
    else:
        await show_panel(cq, uid, PANEL_OF.get(key, "settings"))


# ================================================================ quick modes
@Client.on_callback_query(filters.regex(r"^quick:(\w+)$"))
async def quick_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    mode = cq.matches[0].group(1)
    uid = cq.from_user.id
    allowed = quick_modes_for(uid)
    if mode not in allowed:
        if mode in QUICK_MODES:
            await cq.answer("This profile uses the Pro engine (admins only).", show_alert=True)
        else:
            await cq.answer("Unknown mode")
        return
    s = await get_settings(uid)
    preset = {k: v for k, v in QUICK_MODES[mode].items() if k != "label"}
    s.update(preset)
    s, _ = apply_policy(uid, s)
    await db.save_settings(uid, s)
    await cq.answer(f"{QUICK_MODES[mode]['label']} applied")
    session = state.get(uid) if state.exists(uid) else None
    hint = "🚀 Files are ready — tap **🎬 Convert Now**." if session and session.ready else "📥 Now send a photo + audio."
    await _edit(cq, f"✅ **{QUICK_MODES[mode]['label']}**\n{hint}\n\n" + SETTINGS_TEXT, settings_keyboard(s, uid))


# ================================================================ presets
@Client.on_callback_query(filters.regex(r"^preset:(save|load|del):?(.*)$"))
async def preset_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    action, name = cq.matches[0].group(1), cq.matches[0].group(2)
    uid = cq.from_user.id
    if action == "save":
        session = state.get(uid)
        session.awaiting = "preset_name"
        session.awaiting_msg_id = cq.message.id
        await _edit(cq, "💾 **Send a name for this preset** (max 30 characters):", input_cancel_keyboard())
        await cq.answer()
        return
    if action == "load":
        data = await db.get_preset(uid, name)
        if not data:
            await cq.answer("Preset not found", show_alert=True)
            return
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        merged, downgraded = apply_policy(uid, merged)
        await db.save_settings(uid, merged)
        await cq.answer(f"Preset '{name}' loaded" + (" (Lite engine)" if downgraded else ""))
        await _edit(cq, f"🎛 **{name}** loaded.\n\n" + SETTINGS_TEXT, settings_keyboard(merged, uid))
        return
    if action == "del":
        await db.delete_preset(uid, name)
        names = await db.list_presets(uid)
        await cq.answer("Deleted")
        await _edit(cq, _presets_text(names), presets_keyboard(names))


# ================================================================ text input requests
@Client.on_callback_query(filters.regex(r"^input:(\w+)$"))
async def input_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    key = cq.matches[0].group(1)
    uid = cq.from_user.id
    session = state.get(uid)
    if key == "cancel":
        prev = session.awaiting
        session.awaiting = None
        await show_panel(cq, uid, PANEL_OF.get(prev or "", "settings"))
        await cq.answer("Cancelled")
        return
    prompts = {
        "watermark_text": "💧 **Send the watermark text** (e.g. `@YourChannel`):",
        "title_text": "🔤 **Send the title text** (e.g. the song name):",
        "custom_caption": ("📝 **Send the caption.** Placeholders:\n`{title}` `{artist}` `{duration}` "
                           "`{size}` `{resolution}` `{bot_name}`"),
        "target_duration": ("⏱ **Send the final video length.**\nExamples: `10h`, `2h30m`, `90m`, `1:30:00`, "
                            "`0` = same as audio"),
    }
    if key not in prompts:
        await cq.answer("Unknown")
        return
    session.awaiting = key
    session.awaiting_msg_id = cq.message.id
    await _edit(cq, prompts[key], input_cancel_keyboard())
    await cq.answer("Type your text")
