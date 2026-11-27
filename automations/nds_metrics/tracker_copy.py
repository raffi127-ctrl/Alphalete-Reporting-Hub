"""The NDS Tracker in the NDS Metrics thread.

Carlos 2026-11-27: "lets add in the NDS tracker to this post. the one that has
our name and the org highlighted. you can still post on the tracker thread as
well."

WHICH PICTURE: the one tableau_screenshots posts in today's "Tableau Country
Trackers" thread in #alphalete-gp-sales. That channel's copy is the
highlighted one: Carlos's and Nico's rows yellow, the rest of the org blue
(tableau_screenshots.highlight, CHANNEL_OWNERS). Both threads live in the same
channel, so the copy is simple: find the NDS Tracker reply there, download its
file, and upload it here. There is no second Tableau capture and no second
highlight, and the tracker thread keeps its own copy.

WHY TWO TRIGGERS: the tracker is made on LUCY 3 and waits on Tableau. It can
land before this thread opens (~6:50) or mid-morning (11/27 it came at 10:29).
Both triggers run on Lucy 2, and both are safe to repeat:
  * post_thread (the morning thread) tries at the tracker's slot.
  * tracker_texts (`text_tracker nds`, which Lucy 3 queues on Lucy 2 the
    moment the board posts) tries again. A late tracker therefore lands at
    the end of the thread.
A lock file plus a look at the thread's own replies keeps it to one copy a
day. A tracker that never posts (Tableau down all day) is an honest skip.

Dry check on Lucy 2 (finds and downloads, posts nothing):
    rerun nds_metrics_probe --tracker-copy-dry
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import time
from pathlib import Path

SID = "nds_tracker"
TITLE = "NDS Tracker"
EMOJI = "\U0001F4E1"           # satellite_antenna, the tracker thread's own icon
TRACKER_ID = "nds"             # tableau_screenshots pages.py id
LOCK_WAIT_S = 180


def _run():
    from automations.nds_metrics import run as R
    return R


def _title() -> str:
    """The tracker's own title ('NDS Tracker'), read from pages.py so a rename
    there follows here."""
    try:
        from automations.tableau_screenshots import pages as P
        spec = P.by_id(TRACKER_ID) or {}
        return spec.get("title") or TITLE
    except Exception:  # noqa: BLE001
        return TITLE


def _unescape(text) -> str:
    """Slack hands message text back HTML-escaped."""
    return ((text or "").replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">"))


def tracker_thread_title(today: dt.date) -> str:
    """'Tableau Country Trackers 11/27/2026', tableau_screenshots' own header."""
    try:
        from automations.tableau_screenshots.slack_post import header_title
        return header_title(today)
    except Exception:  # noqa: BLE001
        return "Tableau Country Trackers %d/%d/%d" % (today.month, today.day,
                                                      today.year)


def reply_caption(today: dt.date) -> str:
    """'NDS Tracker - Nov 27', the tracker thread's caption without the bold."""
    return "%s - %s %d" % (_title(), today.strftime("%b"), today.day)


def _history(client, channel: str, today: dt.date, pages: int = 5) -> list:
    """Today's top-level messages in the channel, newest first. Paged, because
    by the afternoon a busy sales day can push the 7am header past 200."""
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    out, cursor = [], None
    for _ in range(pages):
        kw = {"channel": channel, "oldest": str(oldest), "limit": 200}
        if cursor:
            kw["cursor"] = cursor
        resp = client.conversations_history(**kw)
        out += resp.get("messages", []) or []
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return out


def find_tracker_reply(client, today: dt.date, channel: str) -> tuple:
    """(reply, file) for today's NDS Tracker in the Country Trackers thread, or
    (None, None) while it hasn't posted. The newest match wins, so a corrected
    re-post beats the morning one. A reply matches on its caption OR its file
    name (Slack does not always keep the upload's comment as the text)."""
    title = tracker_thread_title(today)
    parents = [m for m in _history(client, channel, today)
               if title in _unescape(m.get("text"))]
    needle = reply_caption(today)
    fname = "%s.png" % _title()
    best = None
    for p in parents:
        pts = p.get("thread_ts") or p.get("ts")
        resp = client.conversations_replies(channel=channel, ts=pts, limit=200)
        for m in resp.get("messages", []) or []:
            if m.get("ts") == pts:
                continue
            imgs = [f for f in (m.get("files") or [])
                    if str(f.get("mimetype") or "").startswith("image/")]
            if not imgs:
                continue
            hit = (needle in _unescape(m.get("text"))
                   or any((f.get("name") or "") == fname for f in imgs))
            if hit and (best is None
                        or float(m.get("ts") or 0) > float(best[0].get("ts") or 0)):
                best = (m, imgs[0])
    return best if best else (None, None)


def caption_note(reply, today: dt.date) -> str:
    """Whatever the tracker thread wrote after its bold caption, e.g.
    '(yesterday isn't fully loaded in Tableau yet)'. It rides along, so a
    board sent before Tableau caught up says so here too."""
    txt = _unescape((reply or {}).get("text"))
    bold = "*%s*" % reply_caption(today)
    return txt.split(bold, 1)[1].strip() if bold in txt else ""


def download(client, f: dict, dest: Path) -> Path:
    """The file's bytes, through the same token (url_private needs it as the
    bearer). A Slack sign-in page comes back as 200 + HTML, so the bytes must
    look like an image or nothing is saved."""
    import requests
    url = f.get("url_private_download") or f.get("url_private")
    if not url:
        info = client.files_info(file=f["id"]).get("file") or {}
        url = info.get("url_private_download") or info.get("url_private")
    if not url:
        raise RuntimeError("the tracker file has no download link")
    r = requests.get(url, headers={"Authorization": "Bearer %s" % client.token},
                     timeout=60)
    r.raise_for_status()
    data = r.content
    if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
        raise RuntimeError("the tracker file came back as %s (%d bytes), not "
                           "an image" % (r.headers.get("content-type"), len(data)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def fetch(today: dt.date, *, client=None, log=print) -> Path:
    """Download today's tracker picture (for --only/--dm previews). Raises
    while it hasn't posted."""
    R = _run()
    client = client or _client()
    reply, f = find_tracker_reply(client, today, R.CHANNEL[1])
    if not f:
        raise RuntimeError("no NDS Tracker in today's Country Trackers thread yet")
    png = download(client, f, R.OUT_DIR / ("nds_tracker_%s.png" % today.isoformat()))
    log("[nds] tracker: %s (%s bytes)" % (png.name, "{:,}".format(png.stat().st_size)))
    return png


def _client():
    from automations.shared.slack_metrics_post import _client as c
    return c()


def thread_has_tracker(client, ts: str, channel: str) -> bool:
    """Is the tracker already in the NDS Metrics thread? The thread itself is
    the truth: two Lucy 2 processes keep their own copy of the state file."""
    R = _run()
    resp = client.conversations_replies(channel=channel, ts=ts, limit=200)
    return any(R.reply_is_section(m, SID, TITLE)
               for m in resp.get("messages", []) or [] if m.get("ts") != ts)


@contextlib.contextmanager
def _lock(path: Path, wait_s: int = LOCK_WAIT_S):
    """One copier at a time on this machine (the morning thread and a
    `text_tracker nds` row can meet)."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        deadline = time.time() + wait_s
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() > deadline:
                    raise RuntimeError("tracker copy lock busy for %ds" % wait_s)
                time.sleep(1)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _mark_posted(sp: Path) -> None:
    state = json.loads(sp.read_text()) if sp.exists() else {}
    posted = state.setdefault("posted", [])
    if SID not in posted:
        posted.append(SID)
    sp.write_text(json.dumps(state))


def copy_to_thread(today: dt.date | None = None, *, client=None, log=print,
                   force: bool = False, dry_run: bool = False) -> str:
    """Put today's NDS Tracker in today's NDS Metrics thread, once.

    Returns what happened: 'posted', 'already' (it is in the thread),
    'no-thread' (the NDS thread hasn't opened; the morning run copies it at
    its slot), 'not-yet' (the tracker hasn't posted; text_tracker nds copies
    it when it does) or 'would-post' (dry_run). Raises only on a real Slack or
    download error, and every caller catches it."""
    R = _run()
    today = today or dt.date.today()
    channel = R.CHANNEL[1]
    sp = R._state_path(today)
    with _lock(R.OUT_DIR / ".nds_tracker.lock"):
        state = json.loads(sp.read_text()) if sp.exists() else {}
        ts = state.get("ts")
        if not ts:
            return "no-thread"
        if SID in (state.get("posted") or []) and not force:
            return "already"
        client = client or _client()
        if not force and thread_has_tracker(client, ts, channel):
            if not dry_run:
                _mark_posted(sp)
            return "already"
        reply, f = find_tracker_reply(client, today, channel)
        if not f:
            return "not-yet"
        png = download(client, f, R.OUT_DIR / ("nds_tracker_%s.png"
                                               % today.isoformat()))
        note = caption_note(reply, today)
        cap = R.caption(SID, EMOJI, TITLE) + ((" " + note) if note else "")
        size = "{:,}".format(png.stat().st_size)
        if dry_run:
            log("[nds] tracker copy DRY: would post %s (%s bytes) as %r"
                % (png.name, size, cap))
            return "would-post"
        client.files_upload_v2(channel=channel, thread_ts=ts, initial_comment=cap,
                               file_uploads=[{"file": str(png),
                                              "filename": png.name}])
        _mark_posted(sp)
        log("[nds] tracker copied into the NDS thread: %s (%s bytes)"
            % (png.name, size))
        return "posted"


def dry_check(today: dt.date | None = None, log=print) -> int:
    """`rerun nds_metrics_probe --tracker-copy-dry`: the live lookup and download
    with this machine's token, plus what the thread copy would do. Posts
    nothing."""
    R = _run()
    today = today or dt.date.today()
    client = _client()
    title = tracker_thread_title(today)
    reply, f = find_tracker_reply(client, today, R.CHANNEL[1])
    if not f:
        log("[nds] tracker dry: no %r reply under %r yet" % (reply_caption(today), title))
    else:
        dest = R.OUT_DIR / ("nds_tracker_dry_%s.png" % today.isoformat())
        png = download(client, f, dest)
        try:
            from PIL import Image
            w, h = Image.open(png).size
            dims = " %dx%d" % (w, h)
        except Exception:  # noqa: BLE001
            dims = ""
        log("[nds] tracker dry: found reply %s, file %r -> %s (%s bytes%s), note %r"
            % (reply.get("ts"), f.get("name"), png.name,
               "{:,}".format(png.stat().st_size), dims, caption_note(reply, today)))
    log("[nds] tracker dry: thread copy would be: %s"
        % copy_to_thread(today, client=client, log=log, dry_run=True))
    print("=== done ===", flush=True)
    return 0
