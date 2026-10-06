"""Offline tests for the YouTube feature (no network, no Telegram)."""
import os, sys, pickle, time, asyncio, tempfile, types
os.environ.setdefault("API_ID", "1"); os.environ.setdefault("API_HASH", "x"); os.environ.setdefault("BOT_TOKEN", "1:x")
TMP = tempfile.mkdtemp()
os.environ["DOWNLOAD_DIR"] = os.path.join(TMP, "dl"); os.environ["YT_TOKEN_DIR"] = os.path.join(TMP, "tok")
os.environ["YT_PENDING_TTL_SEC"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.environ["DOWNLOAD_DIR"], exist_ok=True); os.makedirs(os.environ["YT_TOKEN_DIR"], exist_ok=True)
asyncio.set_event_loop(asyncio.new_event_loop())      # pyrogram needs a loop at import time (py3.12+)
import pyrogram  # noqa: E402

from core import youtube as yt
from core.state import state, PendingOutput
from core import storage


def test_templates():
    for key in yt.TEMPLATE_ORDER:
        m = yt.build_metadata(key, "Rain Sounds – Vol.2", "Nature", 10 * 3600, "public",
                              chapters=[(0, "Rain"), (3600, "Thunder")])
        assert m["template"] == key
        assert 0 < len(m["title"]) <= 100, (key, m["title"])
        assert len(m["description"]) <= 5000
        assert sum(len(t) + 2 for t in m["tags"]) <= 500
        assert m["privacy"] == "public"
        assert "{" not in m["title"] and "{" not in m["description"], key
        if key != "plain":
            assert "10" in m["title"] or "10" in m["description"]
            assert "01:00:00 Thunder" in m["description"]
    m = yt.build_metadata("sleep", "x" * 200, "", 45 * 60, "bogus")
    assert len(m["title"]) <= 100 and m["privacy"] == "public"
    m = yt.build_metadata("music", "Song", "", 3600)
    assert "–" not in m["title"].split("|")[0].strip()[-1:], m["title"]
    print("  templates ok:", yt.build_metadata("sleep", "Rain Sounds", "", 36000)["title"])


def test_guess():
    assert yt.guess_title_artist({"title": "A", "artist": "B"}) == ("A", "B")
    t, a = yt.guess_title_artist({}, "/x/Arijit Singh - Tum Hi Ho (official audio) 320kbps.mp3")
    assert t == "Tum Hi Ho" and a == "Arijit Singh", (t, a)
    assert yt.guess_title_artist({}, "")[0] == "Untitled"


def test_token_import(monkeypatch=None):
    from google.oauth2.credentials import Credentials
    creds = Credentials(token="abc", refresh_token="r", client_id="c", client_secret="s",
                        token_uri="https://oauth2.googleapis.com/token", scopes=list(yt.SCOPES_UPLOAD))
    src = os.path.join(TMP, "token.pickle")
    pickle.dump(creds, open(src, "wb"))
    # no network: skip refresh (token has no expiry -> valid) and skip verify
    info = asyncio.run(yt.import_token(src, 42, verify=False))
    assert info == {} and yt.has_token(42)
    # dict / json form
    import json
    src2 = os.path.join(TMP, "token.json")
    json.dump({"token": "abc", "refresh_token": "r", "client_id": "c", "client_secret": "s",
               "scopes": list(yt.SCOPES_UPLOAD)}, open(src2, "w"))
    asyncio.run(yt.import_token(src2, 43, verify=False)); assert yt.has_token(43)
    # client_secret.json must be rejected with a helpful message
    src3 = os.path.join(TMP, "client_secret.json")
    json.dump({"installed": {"client_id": "c"}}, open(src3, "w"))
    try:
        asyncio.run(yt.import_token(src3, 44, verify=False)); raise AssertionError("should fail")
    except yt.TokenError as e:
        assert "client_secret" in str(e)
    # wrong scope
    bad = Credentials(token="abc", refresh_token="r", client_id="c", client_secret="s", scopes=["https://www.googleapis.com/auth/drive"])
    pickle.dump(bad, open(src, "wb"))
    try:
        asyncio.run(yt.import_token(src, 45, verify=False)); raise AssertionError("should fail")
    except yt.TokenError as e:
        assert "scope" in str(e)
    assert yt.delete_token(42) and not yt.has_token(42)


def test_upload_mock():
    """Drive _upload_sync with a fake googleapiclient: chunk progress, one retryable error, thumbnail."""
    import googleapiclient.http as gh, googleapiclient.errors as ge, googleapiclient.discovery as gd
    from google.oauth2.credentials import Credentials
    creds = Credentials(token="abc", refresh_token="r", client_id="c", client_secret="s", scopes=list(yt.SCOPES_UPLOAD))
    yt._save_creds_sync(creds, yt.token_path(7))
    video = os.path.join(TMP, "v.mp4"); open(video, "wb").write(b"\0" * 5_000_000)
    thumb = os.path.join(TMP, "t.jpg"); open(thumb, "wb").write(b"\xff\xd8")

    calls = {"chunks": 0, "thumb": 0, "body": None}

    class FakeStatus:
        def __init__(self, p): self.resumable_progress = p

    class FakeRequest:
        def __init__(self, body, size): self.body, self.size, self.sent = body, size, 0
        def next_chunk(self, num_retries=0):
            calls["chunks"] += 1
            if calls["chunks"] == 2:          # transient 503 once
                resp = types.SimpleNamespace(status=503, reason="x")
                raise ge.HttpError(resp, b'{"error":{"message":"backend"}}')
            self.sent = min(self.size, self.sent + 2_000_000)
            if self.sent >= self.size:
                return None, {"id": "VID123", "snippet": {"title": self.body["snippet"]["title"]},
                              "status": {"privacyStatus": self.body["status"]["privacyStatus"]}}
            return FakeStatus(self.sent), None

    class FakeService:
        def videos(self): return self
        def insert(self, part, body, media_body): calls["body"] = body; return FakeRequest(body, 5_000_000)
        def thumbnails(self): return self
        def set(self, videoId, media_body):
            calls["thumb"] += 1
            return types.SimpleNamespace(execute=lambda: {"ok": 1})

    orig_build, orig_sleep = yt._build_service_sync, yt.time.sleep
    yt._build_service_sync = lambda c: FakeService()
    yt.time.sleep = lambda s: None
    try:
        prog = []
        meta = yt.build_metadata("lofi", "Chill", "DJ", 7200, "unlisted")
        res = yt._upload_sync(7, video, meta, thumb, lambda s, t: prog.append(s), lambda: False)
        assert res["video_id"] == "VID123" and res["url"].endswith("VID123") and res["thumbnail"]
        assert res["privacy"] == "unlisted" and calls["thumb"] == 1 and calls["chunks"] >= 4
        assert prog[0] == 0 and prog[-1] == 5_000_000 and prog == sorted(prog)
        assert calls["body"]["snippet"]["categoryId"] == "10" and calls["body"]["status"]["selfDeclaredMadeForKids"] is False
        # cancellation
        calls["chunks"] = 0
        try:
            yt._upload_sync(7, video, meta, None, lambda s, t: None, lambda: True); raise AssertionError
        except yt.YouTubeError as e:
            assert "cancel" in str(e)
        # async wrapper with coroutine progress
        async def run():
            got = []
            async def on_p(s, t): got.append(s)
            calls["chunks"] = 0
            r = await yt.upload_video(7, video, meta, None, on_progress=on_p)
            await asyncio.sleep(0.05)
            return r, got
        r, got = asyncio.run(run())
        assert r["video_id"] == "VID123" and got
    finally:
        yt._build_service_sync, yt.time.sleep = orig_build, orig_sleep


def test_pending_storage():
    from core.config import Config
    f = os.path.join(Config.DOWNLOAD_DIR, "ytpending_9_abc.mp4"); open(f, "wb").write(b"x" * 1000)
    th = os.path.join(Config.DOWNLOAD_DIR, "ytthumb_9_abc.jpg"); open(th, "wb").write(b"y")
    p = PendingOutput(user_id=9, path=f, thumb=th, size=1000, duration=10)
    state.set_pending(9, p)
    assert f in storage._job_files()                       # protected from the sweeper
    storage.sweep(orphan_ttl=0)
    assert os.path.exists(f) and os.path.exists(th)       # survived a zero-TTL sweep
    p.uploading = True
    time.sleep(1.1)
    storage.sweep(orphan_ttl=0)
    assert os.path.exists(f)                              # never deleted while uploading
    p.uploading = False
    assert p.expired
    storage.sweep(orphan_ttl=0)
    assert not os.path.exists(f) and not os.path.exists(th) and state.get_pending(9) is None


def test_preview_and_keyboards():
    from core import keyboards as kb
    meta = yt.build_metadata("meditation", "Om Chanting", "", 3 * 3600)
    txt = yt.metadata_preview(meta, "600 MB", "ok")
    assert "Om Chanting" in txt and "/100" in txt
    for k in (kb.yt_prompt_keyboard(True), kb.yt_prompt_keyboard(False), kb.yt_meta_keyboard(meta),
              kb.yt_templates_keyboard("sleep"), kb.yt_panel_keyboard(True, True, "music", "public"),
              kb.yt_default_templates_keyboard("lofi"), kb.yt_default_privacy_keyboard("private"),
              kb.yt_done_keyboard("https://youtu.be/x", "https://studio.youtube.com/x"), kb.admin_keyboard(1, 2)):
        assert k.inline_keyboard
    from core.strings import YT_PROMPT, YT_EDIT_PROMPT, HELP_TOPICS
    YT_PROMPT.format(size="1", duration="2", token_line="3", ttl=30)
    assert "youtube" in HELP_TOPICS and set(YT_EDIT_PROMPT) == {"title", "description", "tags"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name)
    print("ALL OK")
