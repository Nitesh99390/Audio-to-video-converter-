"""
In-memory per-user session state + global task queue / cancellation registry.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.config import Config


@dataclass
class Session:
    """Everything a user has uploaded for the current job."""
    photos: List[str] = field(default_factory=list)      # 1 photo = normal, >1 = slideshow
    audios: List[str] = field(default_factory=list)      # >1 = merge into one track
    bg_video: Optional[str] = None                        # loop a video instead of image
    intro: Optional[str] = None                           # short clip played BEFORE the main video
    outro: Optional[str] = None                           # short clip played AFTER the main video
    intro_info: dict = field(default_factory=dict)
    outro_info: dict = field(default_factory=dict)
    audio_info: dict = field(default_factory=dict)
    awaiting: Optional[str] = None                        # text input mode e.g. "watermark_text"
    awaiting_msg_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self):
        self.updated_at = time.time()

    @property
    def has_visual(self) -> bool:
        return bool(self.photos or self.bg_video)

    @property
    def has_audio(self) -> bool:
        return bool(self.audios)

    @property
    def ready(self) -> bool:
        return self.has_visual and self.has_audio

    @property
    def has_intro_outro(self) -> bool:
        return bool(self.intro or self.outro)

    def all_files(self) -> List[str]:
        files = list(self.photos) + list(self.audios)
        for f in (self.bg_video, self.intro, self.outro):
            if f:
                files.append(f)
        return files


@dataclass
class PendingOutput:
    """
    A finished video that is kept on disk a little longer because the admin may want to
    upload it to YouTube. Deleted when the admin declines, after the upload, or when
    `YT_PENDING_TTL_SEC` passes (storage.sweep). Files are protected from the disk guard
    while this object exists.
    """
    user_id: int
    path: str
    thumb: Optional[str]
    size: int
    duration: float
    audio_info: dict = field(default_factory=dict)
    audio_files: List[str] = field(default_factory=list)
    audio_durations: List[float] = field(default_factory=list)
    meta: dict = field(default_factory=dict)        # editable YouTube metadata
    prompt_msg_id: Optional[int] = None             # the "Upload to YouTube?" message
    uploading: bool = False
    cancel_upload: bool = False
    created_at: float = field(default_factory=time.time)

    def files(self) -> List[str]:
        return [p for p in (self.path, self.thumb) if p]

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > Config.YT_PENDING_TTL_SEC and not self.uploading


class StateManager:
    def __init__(self):
        self._sessions: Dict[int, Session] = {}
        self._running: Dict[int, asyncio.subprocess.Process] = {}   # user_id -> ffmpeg process
        self._job_files: Dict[int, List[str]] = {}                   # user_id -> temp files of the running job
        self._pending: Dict[int, PendingOutput] = {}                 # user_id -> finished video awaiting YT decision
        self._cancelled: set = set()
        self.semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_TASKS)
        self.queue_size = 0
        self.started_at = time.time()

    # ---- sessions ----
    def get(self, user_id: int) -> Session:
        if user_id not in self._sessions:
            self._sessions[user_id] = Session()
        return self._sessions[user_id]

    def clear(self, user_id: int) -> Session:
        old = self._sessions.pop(user_id, None)
        return old or Session()

    def exists(self, user_id: int) -> bool:
        return user_id in self._sessions

    def sessions_items(self):
        """Snapshot of (user_id, Session) pairs — safe to iterate while mutating."""
        return list(self._sessions.items())

    # ---- files owned by a running job (protected from cleanup) ----
    def register_job_files(self, user_id: int, *paths: str):
        lst = self._job_files.setdefault(user_id, [])
        for p in paths:
            if p and p not in lst:
                lst.append(p)

    def release_job_files(self, user_id: int) -> List[str]:
        return self._job_files.pop(user_id, [])

    def all_job_files(self) -> List[str]:
        out: List[str] = []
        for lst in self._job_files.values():
            out.extend(lst)
        return out

    def processing_users(self) -> List[int]:
        return list(self._running.keys())

    # ---- finished outputs waiting for the YouTube decision (admins) ----
    def set_pending(self, user_id: int, pending: PendingOutput) -> Optional[PendingOutput]:
        """Replace the user's pending output; returns the previous one (caller deletes its files)."""
        old = self._pending.pop(user_id, None)
        self._pending[user_id] = pending
        return old

    def get_pending(self, user_id: int) -> Optional[PendingOutput]:
        return self._pending.get(user_id)

    def pop_pending(self, user_id: int) -> Optional[PendingOutput]:
        return self._pending.pop(user_id, None)

    def pending_items(self):
        return list(self._pending.items())

    def pending_files(self) -> List[str]:
        out: List[str] = []
        for p in self._pending.values():
            out.extend(p.files())
        return out

    # ---- ffmpeg process registry (for /cancel) ----
    def register_process(self, user_id: int, proc):
        self._running[user_id] = proc

    def unregister_process(self, user_id: int):
        self._running.pop(user_id, None)

    def is_processing(self, user_id: int) -> bool:
        return user_id in self._running

    def cancel(self, user_id: int) -> bool:
        self._cancelled.add(user_id)
        proc = self._running.get(user_id)
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return True
        return False

    def was_cancelled(self, user_id: int) -> bool:
        return user_id in self._cancelled

    def reset_cancel(self, user_id: int):
        self._cancelled.discard(user_id)

    @property
    def active_tasks(self) -> int:
        return len(self._running)

    def stale_sessions(self, max_age: float = 3600) -> List[int]:
        now = time.time()
        return [uid for uid, s in self._sessions.items() if now - s.updated_at > max_age]


state = StateManager()
