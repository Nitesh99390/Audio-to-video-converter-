"""
Feature policy: who may use what.

* ⚡ Lite engine  – everyone.
* 🎬 Pro engine   – admins only (full re-encode, visualizer, Ken-Burns, fade, 4K, 60 fps).

`apply_policy()` is the single source of truth: every place that reads a
user's settings for rendering or display passes them through it, so a normal
user can never end up with a Pro render even if the DB row says "pro"
(e.g. an old preset, a quick-mode from before the change, a demoted admin).
"""
from typing import Any, Dict, Tuple

from core.config import Config

LITE_FPS = [1, 2, 5, 10, 15, 24, 30]
PRO_FPS = [24, 25, 30, 60]

# keys that only make sense with the Pro engine
PRO_ONLY_KEYS = ("visualizer", "vis_color", "vis_position", "ken_burns", "fade")


def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMINS


def can_use_pro(user_id: int) -> bool:
    if not Config.PRO_ENGINE_ADMIN_ONLY:
        return True
    return is_admin(user_id)


def allowed_engines(user_id: int):
    return ["lite", "pro"] if can_use_pro(user_id) else ["lite"]


def fps_options(settings: Dict[str, Any]):
    return PRO_FPS if settings.get("engine") == "pro" else LITE_FPS


def apply_policy(user_id: int, settings: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Return (settings, changed). Downgrades a Pro configuration to Lite for users
    who are not allowed to use Pro and keeps fps inside the engine's valid range.
    """
    s = dict(settings)
    changed = False

    if s.get("engine") not in ("lite", "pro"):
        s["engine"] = "lite"
        changed = True

    if s["engine"] == "pro" and not can_use_pro(user_id):
        s["engine"] = "lite"
        changed = True

    try:
        fps = int(s.get("fps", 10))
    except (TypeError, ValueError):
        fps = 10
    if s["engine"] == "lite":
        if fps not in LITE_FPS:
            s["fps"] = 10
            changed = True
        # 4K / 1440p on lite is pointless for static pictures and huge on disk
        if s.get("resolution") in ("1440p", "2160p") and not can_use_pro(user_id):
            s["resolution"] = "1080p"
            changed = True
    else:
        if fps not in PRO_FPS:
            s["fps"] = 30
            changed = True

    return s, changed
