"""
Storage guard — keeps the working directory from ever filling the disk.

Kaggle / Colab give ~20 GB of scratch space and simply crash the notebook
when it is full, so nothing may be left behind:

  * startup purge      – every file from a previous run is removed (sessions
                         live in RAM, so leftovers are always garbage).
  * routine sweep      – every few minutes: orphan files (not part of any
                         session / running job) older than ORPHAN_TTL, stray
                         temp files (.seg.mp4 / .audio.m4a / .temp / .txt) and
                         sessions idle for longer than SESSION_TTL are deleted.
  * quota              – the downloads folder may not exceed MAX_STORAGE_MB;
                         above that, idle sessions are evicted oldest-first.
  * emergency watchdog – if free disk drops under MIN_FREE_MB, everything that
                         is not owned by a *running* job is evicted at once.
  * ensure_space()     – called before every download and before every render
                         with an estimate of the bytes needed; evicts if needed
                         and refuses the job when space really is not there.

Files are named  <kind>_<user_id>_<hex>.<ext>  so ownership can be recovered
from the file name alone — no DB lookups, works even after a crash.
"""
import glob
import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

from core.config import Config
from core.state import state
from core.utils import cleanup, humanbytes

logger = logging.getLogger(__name__)

MB = 1024 * 1024

# never touch files that were written in the last N seconds (in-flight download / render)
RECENT_GRACE_SEC = 120
TEMP_SUFFIXES = (".temp", ".seg.mp4", ".audio.m4a", ".title.txt", ".wm.txt", ".part")


@dataclass
class Entry:
    path: str
    size: int
    mtime: float
    owner: Optional[int]      # user id parsed from the file name
    in_session: bool
    in_job: bool
    recent: bool

    @property
    def protected(self) -> bool:
        return self.in_job or self.recent


def _owner_from_name(path: str) -> Optional[int]:
    base = os.path.basename(path)
    parts = base.split("_")
    if len(parts) >= 3 and parts[1].isdigit():
        return int(parts[1])
    return None


def _job_files() -> Set[str]:
    """Files of running jobs + finished videos waiting for the admin's YouTube decision."""
    return set(state.all_job_files()) | set(state.pending_files())


def _session_files() -> Dict[str, int]:
    files: Dict[str, int] = {}
    for uid, sess in state.sessions_items():
        for f in sess.all_files():
            files[f] = uid
    return files


def scan() -> List[Entry]:
    """Inventory of the downloads folder with ownership flags."""
    now = time.time()
    job = _job_files()
    sess = _session_files()
    processing = {uid for uid in state.processing_users()}
    out: List[Entry] = []
    for f in glob.glob(os.path.join(Config.DOWNLOAD_DIR, "*")):
        if not os.path.isfile(f):
            continue
        try:
            st = os.stat(f)
        except OSError:
            continue
        owner = _owner_from_name(f)
        in_job = f in job or (owner is not None and owner in processing)
        out.append(Entry(
            path=f, size=st.st_size, mtime=st.st_mtime, owner=owner,
            in_session=f in sess, in_job=in_job, recent=(now - st.st_mtime) < RECENT_GRACE_SEC,
        ))
    return out


def folder_size(entries: Optional[Iterable[Entry]] = None) -> int:
    entries = list(entries) if entries is not None else scan()
    return sum(e.size for e in entries)


def disk_free() -> int:
    try:
        return shutil.disk_usage(Config.DOWNLOAD_DIR).free
    except Exception:
        return 0


def disk_total() -> int:
    try:
        return shutil.disk_usage(Config.DOWNLOAD_DIR).total
    except Exception:
        return 0


def reserve_bytes() -> int:
    """Free space we always keep. MIN_FREE_MB, but never more than 8 % of the disk
    so a small test machine does not lock the bot out completely."""
    total = disk_total()
    cap = int(total * 0.08) if total else Config.MIN_FREE_MB * MB
    return max(64 * MB, min(Config.MIN_FREE_MB * MB, cap))


# ------------------------------------------------------------------ actions
def purge_all() -> int:
    """Startup: remove everything (sessions from the previous run are gone anyway)."""
    os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)
    n = 0
    freed = 0
    for f in glob.glob(os.path.join(Config.DOWNLOAD_DIR, "*")):
        try:
            if os.path.isdir(f):
                shutil.rmtree(f, ignore_errors=True)
            else:
                freed += os.path.getsize(f)
                os.remove(f)
            n += 1
        except OSError:
            pass
    # stray pyrogram default folder (if DOWNLOAD_DIR was changed at some point)
    if os.path.isdir("downloads") and os.path.abspath("downloads") != os.path.abspath(Config.DOWNLOAD_DIR):
        shutil.rmtree("downloads", ignore_errors=True)
    if n:
        logger.info("Storage: purged %d leftover files (%s)", n, humanbytes(freed))
    return n


def _delete(entries: Iterable[Entry]) -> int:
    freed = 0
    for e in entries:
        cleanup(e.path)
        freed += e.size
    return freed


def _evict_sessions(uids: Iterable[int]) -> int:
    """Drop whole sessions (files + RAM). Returns bytes freed."""
    freed = 0
    for uid in uids:
        if state.is_processing(uid):
            continue
        sess = state.clear(uid)
        for f in sess.all_files():
            try:
                freed += os.path.getsize(f)
            except OSError:
                pass
            cleanup(f)
    return freed


def sweep(orphan_ttl: Optional[float] = None, session_ttl: Optional[float] = None) -> Dict[str, int]:
    """Routine cleanup. Safe to call often."""
    orphan_ttl = Config.ORPHAN_TTL_SEC if orphan_ttl is None else orphan_ttl
    session_ttl = Config.SESSION_TTL_SEC if session_ttl is None else session_ttl
    now = time.time()
    # 0. finished videos the admin never decided about (YouTube prompt) — drop after their TTL
    freed = files = 0
    freed += expire_pending(force=(session_ttl == 0))
    entries = scan()

    # 1. orphans: not in a session, not in a job, old enough (temps get no TTL)
    victims = [e for e in entries
               if not e.in_session and not e.protected
               and (e.path.endswith(TEMP_SUFFIXES) or now - e.mtime > orphan_ttl)]
    freed += _delete(victims)
    files += len(victims)

    # 2. idle sessions
    idle = [uid for uid in state.stale_sessions(session_ttl) if not state.is_processing(uid)]
    freed += _evict_sessions(idle)

    # 3. quota
    q = enforce_quota()
    freed += q["freed"]

    if files or idle or q["freed"]:
        logger.info("Storage sweep: %d orphan files, %d idle sessions, quota-evicted %s → freed %s | folder %s | free %s",
                    files, len(idle), humanbytes(q["freed"]), humanbytes(freed),
                    humanbytes(folder_size()), humanbytes(disk_free()))
    return {"files": files, "sessions": len(idle), "freed": freed}


def expire_pending(force: bool = False) -> int:
    """Delete finished outputs whose YouTube decision timed out. Returns bytes freed."""
    freed = 0
    for uid, p in state.pending_items():
        if p.uploading:
            continue
        if force or p.expired:
            state.pop_pending(uid)
            for f in p.files():
                try:
                    freed += os.path.getsize(f)
                except OSError:
                    pass
                cleanup(f)
            logger.info("Storage: pending YouTube output of %s expired (%s)", uid, humanbytes(freed))
    return freed


def enforce_quota() -> Dict[str, int]:
    """Keep the downloads folder under MAX_STORAGE_MB by evicting idle sessions oldest-first."""
    limit = Config.MAX_STORAGE_MB * MB
    if not limit:
        return {"freed": 0}
    size = folder_size()
    if size <= limit:
        return {"freed": 0}
    freed = 0
    for uid, sess in sorted(state.sessions_items(), key=lambda kv: kv[1].updated_at):
        if size - freed <= limit:
            break
        if state.is_processing(uid):
            continue
        freed += _evict_sessions([uid])
    # still over? remove unprotected orphans regardless of age
    if size - freed > limit:
        victims = [e for e in scan() if not e.protected and not e.in_session]
        freed += _delete(victims)
    return {"freed": freed}


def emergency_evict(need: int = 0) -> int:
    """
    Free at least `need` bytes (or until MIN_FREE_MB is satisfied). Deletes everything
    that is not part of a running job: orphans first, then idle sessions oldest-first.
    """
    target = max(need, reserve_bytes() - disk_free())
    if target <= 0:
        return 0
    freed = 0
    victims = [e for e in scan() if not e.protected and not e.in_session]
    freed += _delete(victims)
    if freed < target:
        for uid, _ in sorted(state.sessions_items(), key=lambda kv: kv[1].updated_at):
            if freed >= target:
                break
            freed += _evict_sessions([uid])
    logger.warning("Storage EMERGENCY: freed %s (needed %s) | free now %s",
                   humanbytes(freed), humanbytes(target), humanbytes(disk_free()))
    return freed


def ensure_space(needed: int, keep_user: Optional[int] = None) -> bool:
    """
    Make sure `needed` bytes can be written while keeping MIN_FREE_MB spare.
    Tries a sweep, then an emergency eviction (never touching `keep_user`'s session
    or any running job). Returns False if there still is not enough room.
    """
    reserve = reserve_bytes()
    if disk_free() - needed >= reserve:
        return True
    sweep()
    if disk_free() - needed >= reserve:
        return True
    # emergency: protect the requesting user's own uploads
    keep = state.get(keep_user).all_files() if keep_user is not None and state.exists(keep_user) else []
    keep_set = set(keep)
    victims = [e for e in scan() if not e.protected and e.path not in keep_set]
    _delete(victims)
    for uid, _ in sorted(state.sessions_items(), key=lambda kv: kv[1].updated_at):
        if disk_free() - needed >= reserve:
            break
        if uid == keep_user or state.is_processing(uid):
            continue
        _evict_sessions([uid])
    ok = disk_free() - needed >= reserve
    if not ok:
        logger.error("Storage: cannot free enough space (need %s, free %s)", humanbytes(needed), humanbytes(disk_free()))
    return ok


def report() -> str:
    entries = scan()
    total = folder_size(entries)
    in_job = sum(e.size for e in entries if e.in_job)
    in_sess = sum(e.size for e in entries if e.in_session and not e.in_job)
    orphan = total - in_job - in_sess
    free = disk_free()
    du_total = disk_total()
    limit = Config.MAX_STORAGE_MB * MB
    pct = (total / limit * 100) if limit else 0
    return (
        "🗄 **Storage**\n\n"
        f"📀 Disk: free **{humanbytes(free)}** of {humanbytes(du_total)}"
        f" (reserve {humanbytes(reserve_bytes())})\n"
        f"📂 Work folder: **{humanbytes(total)}** / {Config.MAX_STORAGE_MB} MB quota ({pct:.0f}%)\n"
        f"   • running jobs: {humanbytes(in_job)}\n"
        f"   • waiting uploads: {humanbytes(in_sess)} ({len(list(state.sessions_items()))} sessions)\n"
        f"   • orphans: {humanbytes(orphan)}\n"
        f"🧹 Auto-clean: every {Config.CLEANUP_INTERVAL_SEC // 60} min • idle uploads {Config.SESSION_TTL_SEC // 60} min"
        f" • orphans {Config.ORPHAN_TTL_SEC // 60} min"
    )
