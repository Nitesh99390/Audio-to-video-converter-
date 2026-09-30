"""Settings panel, option menus, toggles, quick modes, presets, text inputs."""
import logging

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from core.database import db, DEFAULT_SETTINGS
from core.helpers import gate, gate_cb
from core.keyboards import (
    settings_keyboard, option_keyboard, OPTIONS, OPTION_TITLES, watermark_keyboard, title_keyboard,
    caption_keyboard, slideshow_keyboard, input_cancel_keyboard, confirm_keyboard, presets_keyboard,
    quick_modes_keyboard, QUICK_MODES,
)
from core.state import state

logger = logging.getLogger(__name__)

SETTINGS_TEXT = "⚙️ **Settings Panel**\nTap any option to change it."
INT_KEYS = {"fps", "slideshow_duration"}


async def _edit(cq: CallbackQuery, text: str, kb):
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            logger.debug("edit fail: %s", e)


# ================================================================ commands
@Client.on_message(filters.command("settings") & filters.private)
async def settings_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    s = await db.get_settings(message.from_user.id)
    await message.reply_text(SETTINGS_TEXT, reply_markup=settings_keyboard(s))


@Client.on_message(filters.command("quick") & filters.private)
async def quick_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    await message.reply_text("⚡ **Quick Modes**\nEk tap me platform-ready settings.", reply_markup=quick_modes_keyboard())


@Client.on_message(filters.command("presets") & filters.private)
async def presets_cmd(client: Client, message: Message):
    if not await gate(client, message):
        return
    names = await db.list_presets(message.from_user.id)
    await message.reply_text("🎛 **Presets**", reply_markup=presets_keyboard(names))


@Client.on_message(filters.command("preset") & filters.private)
async def preset_cmd(client: Client, message: Message):
    """/preset save <name>  |  /preset load <name>  |  /preset del <name>"""
    if not await gate(client, message):
        return
    uid = message.from_user.id
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply_text("Usage: `/preset save <name>` | `/preset load <name>` | `/preset del <name>`")
        return
    action, name = parts[1].lower(), parts[2].strip()[:30]
    if action == "save":
        await db.save_preset(uid, name, await db.get_settings(uid))
        await message.reply_text(f"💾 Preset **{name}** saved.")
    elif action == "load":
        data = await db.get_preset(uid, name)
        if not data:
            await message.reply_text("❌ Preset nahi mila.")
            return
        await db.save_settings(uid, data)
        await message.reply_text(f"✅ Preset **{name}** loaded.", reply_markup=settings_keyboard(data))
    elif action in ("del", "delete"):
        await db.delete_preset(uid, name)
        await message.reply_text(f"🗑 Preset **{name}** deleted.")


# ================================================================ menus
@Client.on_callback_query(filters.regex(r"^menu:(\w+)$"))
async def menu_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    key = cq.matches[0].group(1)
    uid = cq.from_user.id
    s = await db.get_settings(uid)

    if key == "watermark":
        wm = s.get("watermark_text") or "_(none)_"
        await _edit(cq, f"💧 **Watermark**\n\nCurrent: {wm}\nPosition: {s['watermark_position']}", watermark_keyboard(s))
    elif key == "title":
        t = s.get("title_text") or "_(none)_"
        await _edit(cq, f"🔤 **Title Text**\n\nCurrent: {t}\nPosition: {s['title_position']}", title_keyboard(s))
    elif key == "caption":
        c = s.get("custom_caption") or "_(default)_"
        await _edit(cq, "📝 **Custom Caption**\n\nCurrent: " + c +
                    "\n\nPlaceholders: `{title}` `{artist}` `{duration}` `{size}` `{resolution}` `{bot_name}`",
                    caption_keyboard())
    elif key == "slideshow":
        await _edit(cq, "🎞 **Slideshow settings**\n\n2+ photos bhejne par apply hota hai.", slideshow_keyboard(s))
    elif key == "output":
        await _edit(cq, OPTION_TITLES["output_mode"], option_keyboard("output_mode", s["output_mode"]))
    elif key in OPTIONS:
        back = "settings"
        if key in ("watermark_position",):
            back = "menu_watermark"
        elif key in ("title_position",):
            back = "menu_title"
        elif key in ("slideshow_duration", "slideshow_transition"):
            back = "menu_slideshow"
        await _edit(cq, OPTION_TITLES.get(key, key), option_keyboard(key, s.get(key), back=back))
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^nav:menu_(\w+)$"))
async def nav_submenu_cb(client: Client, cq: CallbackQuery):
    """Back buttons from nested option menus (e.g. back to watermark menu)."""
    sub = cq.matches[0].group(1)
    s = await db.get_settings(cq.from_user.id)
    if sub == "watermark":
        await _edit(cq, "💧 **Watermark**", watermark_keyboard(s))
    elif sub == "title":
        await _edit(cq, "🔤 **Title Text**", title_keyboard(s))
    elif sub == "slideshow":
        await _edit(cq, "🎞 **Slideshow settings**", slideshow_keyboard(s))
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
            await _edit(cq, "♻️ **Reset all settings to default?**", confirm_keyboard("set:reset:yes"))
            await cq.answer()
            return
        await db.reset_settings(uid)
        s = await db.get_settings(uid)
        await _edit(cq, "♻️ Settings reset ho gayi.\n\n" + SETTINGS_TEXT, settings_keyboard(s))
        await cq.answer("Reset done ✅")
        return

    if key in INT_KEYS:
        try:
            value = int(value)
        except ValueError:
            await cq.answer("Invalid value")
            return
    if key in OPTIONS and str(value) not in [str(o) for o in OPTIONS[key]]:
        await cq.answer("Invalid option")
        return

    s = await db.update_setting(uid, key, value)
    await cq.answer(f"✅ {key.replace('_', ' ').title()} → {value or 'off'}")

    # return to the right menu
    if key in ("watermark_text", "watermark_position"):
        await _edit(cq, f"💧 **Watermark**\n\nCurrent: {s.get('watermark_text') or '_(none)_'}", watermark_keyboard(s))
    elif key in ("title_text", "title_position"):
        await _edit(cq, f"🔤 **Title Text**\n\nCurrent: {s.get('title_text') or '_(none)_'}", title_keyboard(s))
    elif key in ("slideshow_duration", "slideshow_transition"):
        await _edit(cq, "🎞 **Slideshow settings**", slideshow_keyboard(s))
    else:
        await _edit(cq, SETTINGS_TEXT, settings_keyboard(s))


# ================================================================ toggles
@Client.on_callback_query(filters.regex(r"^toggle:(\w+)$"))
async def toggle_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    key = cq.matches[0].group(1)
    uid = cq.from_user.id
    s = await db.get_settings(uid)
    if key == "language":
        new = "en" if s.get("language") == "hi" else "hi"
    elif key in ("ken_burns", "fade", "spoiler"):
        new = not bool(s.get(key))
    else:
        await cq.answer("Unknown toggle")
        return
    s = await db.update_setting(uid, key, new)
    await cq.answer(f"{key.replace('_', ' ').title()}: {'ON' if new is True else new if isinstance(new, str) else 'OFF'}")
    await _edit(cq, SETTINGS_TEXT, settings_keyboard(s))


# ================================================================ quick modes
@Client.on_callback_query(filters.regex(r"^quick:(\w+)$"))
async def quick_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    mode = cq.matches[0].group(1)
    if mode not in QUICK_MODES:
        await cq.answer("Unknown mode")
        return
    uid = cq.from_user.id
    s = await db.get_settings(uid)
    preset = {k: v for k, v in QUICK_MODES[mode].items() if k != "label"}
    s.update(preset)
    await db.save_settings(uid, s)
    await cq.answer(f"✅ {QUICK_MODES[mode]['label']} applied", show_alert=False)
    session = state.get(uid) if state.exists(uid) else None
    hint = "\n\n🚀 Files ready hain — 🎬 **Convert Now** dabao!" if session and session.ready else \
           "\n\n📥 Ab Photo + Audio bhejo."
    await _edit(cq, f"⚡ **{QUICK_MODES[mode]['label']}** applied!{hint}\n\n" + SETTINGS_TEXT, settings_keyboard(s))


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
        await _edit(cq, "💾 **Preset name type karo** (max 30 chars):", input_cancel_keyboard())
        await cq.answer()
        return
    if action == "load":
        data = await db.get_preset(uid, name)
        if not data:
            await cq.answer("Preset nahi mila", show_alert=True)
            return
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        await db.save_settings(uid, merged)
        await cq.answer(f"✅ Preset '{name}' loaded")
        await _edit(cq, f"🎛 Preset **{name}** loaded.\n\n" + SETTINGS_TEXT, settings_keyboard(merged))
        return
    if action == "del":
        await db.delete_preset(uid, name)
        names = await db.list_presets(uid)
        await cq.answer("🗑 Deleted")
        await _edit(cq, "🎛 **Presets**", presets_keyboard(names))


# ================================================================ text input requests
@Client.on_callback_query(filters.regex(r"^input:(\w+)$"))
async def input_cb(client: Client, cq: CallbackQuery):
    if not await gate_cb(client, cq):
        return
    key = cq.matches[0].group(1)
    uid = cq.from_user.id
    session = state.get(uid)
    if key == "cancel":
        session.awaiting = None
        s = await db.get_settings(uid)
        await _edit(cq, SETTINGS_TEXT, settings_keyboard(s))
        await cq.answer("Cancelled")
        return
    prompts = {
        "watermark_text": "💧 **Watermark text bhejo** (e.g. `@YourChannel`):",
        "title_text": "🔤 **Title text bhejo** (e.g. song name):",
        "custom_caption": ("📝 **Caption bhejo.** Placeholders:\n`{title}` `{artist}` `{duration}` "
                           "`{size}` `{resolution}` `{bot_name}`"),
    }
    if key not in prompts:
        await cq.answer("Unknown")
        return
    session.awaiting = key
    session.awaiting_msg_id = cq.message.id
    await _edit(cq, prompts[key], input_cancel_keyboard())
    await cq.answer("Type your text ✍️")
