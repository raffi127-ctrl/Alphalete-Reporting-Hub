"""Lucy Transcriber -- the watcher.

A rep drops a recording (Voice Memo, Slack audio clip, any audio/video file)
in the transcriber channel. Each tick (every 2 min, deploy/lucy_transcriber.sh)
Lucy finds the new ones, transcribes them on this machine, and replies IN THE
THREAD with who said what. Coaches reply in that same thread with feedback;
every 15 min Lucy saves those replies next to the transcript, so Phase 2
(Raf: "teach the AI some things to be on the lookout for") has real coached
examples to learn from.

    python -m automations.lucy_transcriber.run --file "~/Downloads/door 3.m4a"
        # one local file -> prints exactly what Lucy would post. No Slack.
    python -m automations.lucy_transcriber.run --check --dry-run
        # reads the channel, transcribes what's new, prints instead of posting
    python -m automations.lucy_transcriber.run --check
        # the real tick (posts as Lucy -- refuses on a machine whose token isn't Lucy)
"""
from __future__ import annotations  # Lucy runs Python 3.9

import argparse
import datetime as dt
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.lucy_transcriber import config as C
from automations.lucy_transcriber import render as R
from automations.lucy_transcriber import transcribe as T

REPORT_ID = "lucy_transcriber"
REPORT_NAME = "Lucy Transcriber"
LUCY = "U0BCG8F9B5Z"          # Lucy Reporting -- the only identity that posts here
FEEDBACK_EVERY_S = 15 * 60

TOO_BIG = ("🎧 That file is too big for me ({mb} MB). Can you send it in "
           "shorter pieces? One door per recording is perfect.")
TOO_LONG = ("🎧 That one is {len} -- I transcribe up to 3 hours at a time. "
            "Send it in shorter pieces? One door per recording is perfect.")
GAVE_UP = ("🎧 Something went wrong on my side with this one -- I've flagged "
           "it to the team. Sorry! Send it again later?")


def _log(msg: str) -> None:
    print("[{}] {}".format(dt.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


# ---------------------------------------------------------------- local state

def _load_state() -> Dict:
    try:
        s = json.loads(C.STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        s = {}
    s.setdefault("done", {})
    return s


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _lock() -> Optional[Path]:
    """One tick at a time (a long recording can outlast the 2-min interval).
    A lock older than 45 min is a crashed tick and is taken over."""
    path = C.OUT / ".lock"
    C.OUT.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return path
        except FileExistsError:
            if time.time() - path.stat().st_mtime < 45 * 60:
                return None
            path.unlink()
    return None


# ---------------------------------------------------------------- Slack side

def audio_file(msg: Dict) -> Optional[Dict]:
    for f in msg.get("files") or []:
        mt = str(f.get("mimetype") or "")
        ft = str(f.get("filetype") or "").lower()
        if (mt.startswith(("audio/", "video/")) or ft in C.AUDIO_TYPES
                or f.get("subtype") == "slack_audio"):
            return f
    return None


def new_uploads(client, channel: str, me: str, state: Dict) -> List[Dict]:
    """Top-level messages with a recording that haven't been answered yet,
    oldest first."""
    oldest = "{:.6f}".format(time.time() - C.LOOKBACK_HOURS * 3600)
    msgs, cursor = [], None
    while True:
        r = client.conversations_history(channel=channel, oldest=oldest,
                                         limit=200, cursor=cursor)
        msgs += r.get("messages") or []
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    out = []
    for m in msgs:
        if m.get("user") == me or m.get("bot_id") or not audio_file(m):
            continue
        if (state["done"].get(m["ts"]) or {}).get("status") in ("posted", "told"):
            continue
        out.append(m)
    return sorted(out, key=lambda m: float(m["ts"]))


def _download(f: Dict, token: str, dest: Path) -> Path:
    import requests
    url = f.get("url_private_download") or f.get("url_private")
    r = requests.get(url, headers={"Authorization": "Bearer " + token}, timeout=600)
    r.raise_for_status()
    head = r.content[:200].lstrip().lower()
    # A token without files:read gets a 200 with Slack's sign-in page.
    if head.startswith((b"<!doctype", b"<html")):
        raise RuntimeError("Slack sent a sign-in page instead of the file -- "
                           "this machine's token lacks files:read")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def _react(client, channel, ts, name, on=True) -> None:
    try:
        (client.reactions_add if on else client.reactions_remove)(
            channel=channel, timestamp=ts, name=name)
    except Exception:  # noqa: BLE001 -- a missing reaction never stops a transcript
        pass


def _name(client, uid: str) -> str:
    try:
        p = client.users_info(user=uid)["user"].get("profile") or {}
        return (p.get("real_name") or p.get("display_name") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


class _Say:
    """Where replies go: Slack, or the screen on a dry run."""

    def __init__(self, client, channel: str, dry: bool):
        self.client, self.channel, self.dry = client, channel, dry

    def text(self, thread: str, text: str) -> None:
        if self.dry:
            print("\n--- would reply in thread {} ---\n{}".format(thread, text))
            return
        self.client.chat_postMessage(channel=self.channel, thread_ts=thread,
                                     text=text, unfurl_links=False,
                                     unfurl_media=False)

    def transcript(self, thread: str, got: Dict) -> None:
        msgs = R.slack_messages(got)
        if msgs:
            for m in msgs:
                self.text(thread, m)
            return
        # Too long to read as messages -- one file, header on top.
        comment = R.header(got) + "\n\n" + R.FEEDBACK_ASK
        if self.dry:
            print("\n--- would upload transcript.txt in thread {} ---\n{}\n{}"
                  .format(thread, comment, R.as_text(got)[:1500]))
            return
        self.client.files_upload_v2(channel=self.channel, thread_ts=thread,
                                    content=R.as_text(got),
                                    filename="transcript.txt", title="Transcript",
                                    initial_comment=comment)


def _publish(status: str) -> None:
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(REPORT_ID, REPORT_NAME, status)
    except Exception as e:  # noqa: BLE001 -- the Hub pill never blocks a reply
        _log("hub publish skipped: {}".format(e))


# ---------------------------------------------------------------- one recording

def handle(say: _Say, token: str, msg: Dict, state: Dict) -> str:
    """Transcribe one upload and reply. Returns the status it ends in:
    posted (transcript sent) / told (a can't-do reply sent) / error (retry)."""
    ts, f = msg["ts"], audio_file(msg)
    st = state["done"].setdefault(ts, {"tries": 0})
    st["tries"] = st.get("tries", 0) + 1
    mb = (f.get("size") or 0) / 1024 / 1024
    _log("recording {} from {} ({}, {:.1f} MB, try {})".format(
        ts, msg.get("user"), f.get("name"), mb, st["tries"]))
    if mb > C.MAX_MB:
        say.text(ts, TOO_BIG.format(mb=int(mb)))
        return "told"
    ext = (f.get("filetype") or "audio").lower()
    dest = _download(f, token, C.AUDIO / "{}.{}".format(ts, ext))
    if not say.dry:
        _react(say.client, say.channel, ts, "hourglass_flowing_sand")
    try:
        got = T.transcribe(dest, max_seconds=C.MAX_SECONDS)
    except T.TooLong as e:
        say.text(ts, TOO_LONG.format(len=e))
        return "told"
    except T.TranscribeError as e:
        _log("  unreadable: {}".format(e))
        say.text(ts, R.UNREADABLE)
        return "told"
    finally:
        if not say.dry:
            _react(say.client, say.channel, ts, "hourglass_flowing_sand", on=False)
    if not got["lines"]:
        say.text(ts, R.NO_TALK)
        return "told"
    say.transcript(ts, got)
    if say.dry:
        return "posted"
    _save_json(C.RECORDS / "{}.json".format(ts), dict(
        got, channel=say.channel, ts=ts, user=msg.get("user"),
        name=_name(say.client, msg.get("user") or ""), file=f.get("name"),
        sent_text=msg.get("text") or "",
        received=dt.datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds"),
        replied_at=time.time(), feedback=[]))
    _log("  posted: {} lines, {}s, talk {}".format(len(got["lines"]), got["seconds"],
                                                    got["talk"]))
    return "posted"


# ---------------------------------------------------------------- feedback

def collect_feedback(client, channel: str, me: str) -> int:
    """Every human reply under a transcript, saved on its record. Returns how
    many new ones it found."""
    found = 0
    for p in sorted(C.RECORDS.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("channel") != channel or \
                time.time() - rec.get("replied_at", 0) > C.FEEDBACK_DAYS * 86400:
            continue
        r = client.conversations_replies(channel=channel, ts=rec["ts"], limit=200)
        seen = {x["ts"] for x in rec.get("feedback") or []}
        new = [m for m in (r.get("messages") or [])[1:]
               if m.get("user") != me and not m.get("bot_id")
               and float(m["ts"]) > rec["replied_at"] and m["ts"] not in seen
               and (m.get("text") or "").strip()]
        for m in new:
            rec.setdefault("feedback", []).append({
                "ts": m["ts"], "user": m.get("user"),
                "name": _name(client, m.get("user") or ""), "text": m["text"]})
        if new:
            _save_json(p, rec)
            found += len(new)
    return found


# ---------------------------------------------------------------- the tick

def check(dry: bool = False) -> int:
    channel = C.CHANNEL_ID
    if not channel:
        _log("no channel set yet (lucy_transcriber/config.CHANNEL_ID) -- nothing to do")
        return 0
    lock = _lock()
    if lock is None:
        _log("another tick is still running")
        return 0
    try:
        from automations.shared import slack_metrics_post as smp
        client, token = smp._client(), smp._load_token()
        me = client.auth_test()["user_id"]
        if me != LUCY and not dry:
            _log("this machine's Slack token is {}, not Lucy ({}) -- refusing to "
                 "post. Run on a Lucy, or add --dry-run.".format(me, LUCY))
            return 2
        state = _load_state()
        say = _Say(client, channel, dry)
        rc = 0
        todo = new_uploads(client, channel, me, state)
        if dry:
            _log("{} new recording(s) in {}".format(len(todo), channel))
        for msg in todo:
            try:
                status = handle(say, token, msg, state)
            except Exception:  # noqa: BLE001 -- one bad file never blocks the rest
                traceback.print_exc()
                status = "error"
                if state["done"][msg["ts"]]["tries"] >= C.TRIES:
                    try:
                        say.text(msg["ts"], GAVE_UP)
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
                    status = "told"
                    rc = 1
                    if not dry:
                        _publish("failed")
            state["done"][msg["ts"]]["status"] = status
            if status == "posted" and not dry:
                _publish("success")
            if not dry:
                _save_json(C.STATE, state)
        if not dry and time.time() - state.get("feedback_at", 0) > FEEDBACK_EVERY_S:
            n = collect_feedback(client, channel, me)
            state["feedback_at"] = time.time()
            _save_json(C.STATE, state)
            if n:
                _log("saved {} new feedback repl{}".format(n, "y" if n == 1 else "ies"))
        return rc
    finally:
        lock.unlink()


# ---------------------------------------------------------------- doctor

_PKGS = {"mlx_whisper": "mlx-whisper", "imageio_ffmpeg": "imageio-ffmpeg",
         "numpy": "numpy", "anthropic": "anthropic"}


def doctor(fix: bool = False) -> int:
    """Can THIS machine run the transcriber? Read-only unless --fix, which
    pip-installs a missing package into this venv. Also warms up: a 2-second
    silent clip makes Whisper fetch its model now (one time, ~480 MB) instead
    of on a rep's first recording, and a two-line labelling call proves the
    Claude key works (a fraction of a cent). Posts nothing."""
    import importlib
    import platform
    import subprocess
    ok = True

    def say(good: bool, what: str) -> None:
        nonlocal ok
        ok = ok and good
        print("{}  {}".format("PASS" if good else "FAIL", what), flush=True)

    say(platform.machine() == "arm64",
        "Apple chip ({}) -- mlx-whisper needs one".format(platform.machine()))
    for mod, pkg in _PKGS.items():
        try:
            importlib.import_module(mod)
            say(True, "python package " + pkg)
        except ImportError:
            if fix:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg],
                                   capture_output=True, text=True)
                try:
                    importlib.invalidate_caches()
                    importlib.import_module(mod)
                    say(True, "python package {} (installed just now)".format(pkg))
                    continue
                except ImportError:
                    print((r.stderr or "")[-400:])
            say(False, "python package {} missing{}".format(
                pkg, "" if fix else " -- rerun with --fix"))
    try:
        from automations.brand_audit import credentials
        say(bool(credentials.anthropic_api_key()), "Anthropic key found")
    except Exception as e:  # noqa: BLE001
        say(False, "Anthropic key: {}".format(e))
    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        auth = client.auth_test()
        scopes = set((auth.headers.get("x-oauth-scopes") or "").split(","))
        say(auth["user_id"] == LUCY, "Slack token is Lucy ({})".format(auth["user_id"]))
        for need in ("channels:history", "files:read", "chat:write"):
            say(need in scopes, "Slack scope " + need)
        info = client.conversations_info(channel=C.CHANNEL_ID)["channel"]
        say(bool(info.get("is_member")),
            "Lucy is in #{} ({})".format(info.get("name"), C.CHANNEL_ID))
    except Exception as e:  # noqa: BLE001
        say(False, "Slack: {}".format(e))
    if ok:
        try:
            import numpy as np
            T.words(np.zeros(2 * T.SAMPLE_RATE, dtype=np.float32))
            say(True, "Whisper model ready ({})".format(T.MODEL))
            labels = T.label([
                {"n": 1, "start": 0.0, "end": 2.0,
                 "text": "Hi, I'm Jordan with AT&T, fiber just went live on your street."},
                {"n": 2, "start": 2.5, "end": 3.5, "text": "We already have Spectrum."}])
            say(labels == ["R", "C"], "Claude labels a test exchange ({})".format(labels))
        except Exception as e:  # noqa: BLE001
            say(False, "warm-up: {}".format(e))
    print("READY" if ok else "NOT READY", flush=True)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="transcribe one local file and print it (no Slack)")
    ap.add_argument("--check", action="store_true", help="one watcher tick")
    ap.add_argument("--dry-run", action="store_true", help="print instead of posting")
    ap.add_argument("--doctor", action="store_true",
                    help="can this machine run it? (posts nothing)")
    ap.add_argument("--fix", action="store_true",
                    help="with --doctor: pip-install a missing package")
    a = ap.parse_args(argv)
    if a.doctor or a.file:
        # A question, not a delivery: never colour the Hub card. (A laptop
        # --doctor, rightly failing "token is not Lucy", turned it red once.)
        try:
            from automations.shared import hub_autopublish
            hub_autopublish.nothing_to_report()
        except Exception:  # noqa: BLE001
            pass
    if a.doctor:
        return doctor(fix=a.fix)
    if a.file:
        got = T.transcribe(Path(a.file).expanduser(), max_seconds=C.MAX_SECONDS)
        print(("\n\n----- next message -----\n\n").join(
            R.slack_messages(got) or [R.as_text(got)]))
        return 0
    if a.check:
        return check(dry=a.dry_run)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
