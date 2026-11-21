"""Lucy Transcriber -- the bot reps DM their pitch recordings to.

Megan 2026-11-21: "a bot, not a channel -- like the 2nd round auditor bot."

  1. A rep DMs Lucy Transcriber a recording (Voice Memo, Slack audio clip,
     any audio/video file). She answers "Got it" in that DM right away.
  2. One recording at a time, on this machine: Whisper hears the words,
     Claude marks each line Rep or Customer (transcribe.py).
  3. The transcript goes back in the rep's DM, under their recording.
  4. Each coach (config.COACHES) gets a copy in their own DM with the bot:
     a short parent line ("📝 Jordan's pitch · 4:32 · Rep 70% / Customer 30%")
     and the transcript in its thread.
  5. Any reply under either copy is saved next to the transcript in
     output/lucy_transcriber/records/ and gets a ✅ -- the coached examples
     Phase 2 will learn from.

Its own Slack app (slack_app_manifest.json), Socket Mode: no inbound HTTP,
one always-on process (deploy/com.alphalete.lucy-transcriber.plist,
KeepAlive). On start it picks up recordings DM'd while it was down (last
config.CATCHUP_HOURS). Posts only as the bot, only into DMs with the bot.

    python -m automations.lucy_transcriber.bot          # the listener
"""
from __future__ import annotations  # Lucy runs Python 3.9

import datetime as dt
import json
import os
import queue
import ssl
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from automations.lucy_transcriber import config as C
from automations.lucy_transcriber import render as R
from automations.lucy_transcriber import transcribe as T

REPORT_ID = "lucy_transcriber"
REPORT_NAME = "Lucy Transcriber"
HELP_EVERY_S = 6 * 3600
RETRY_AFTER_S = 60

_lock = threading.RLock()       # state.json + records/*.json
_jobs: "queue.Queue[Dict]" = queue.Queue()


def _log(msg: str) -> None:
    print("[{}] {}".format(dt.datetime.now().strftime("%m-%d %H:%M:%S"), msg), flush=True)


# ---------------------------------------------------------------- state

def load_state() -> Dict:
    try:
        s = json.loads(C.STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        s = {}
    for k in ("done", "threads", "helped"):
        s.setdefault(k, {})
    return s


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def save_state(s: Dict) -> None:
    _save_json(C.STATE, s)


# ---------------------------------------------------------------- Slack

def web(token: str):
    import certifi
    from slack_sdk import WebClient
    return WebClient(token=token, ssl=ssl.create_default_context(cafile=certifi.where()))


def audio_file(msg: Dict) -> Optional[Dict]:
    for f in msg.get("files") or []:
        mt = str(f.get("mimetype") or "")
        ft = str(f.get("filetype") or "").lower()
        if (mt.startswith(("audio/", "video/")) or ft in C.AUDIO_TYPES
                or f.get("subtype") == "slack_audio"):
            return f
    return None


def _from_a_person(ev: Dict) -> bool:
    return (ev.get("type") == "message" and ev.get("channel_type") == "im"
            and not ev.get("bot_id") and bool(ev.get("user")))


def is_recording(ev: Dict) -> bool:
    return (_from_a_person(ev) and ev.get("subtype") in (None, "", "file_share")
            and audio_file(ev) is not None)


def thread_key(channel: str, ts: str) -> str:
    return "{}:{}".format(channel, ts)


def feedback_for(ev: Dict, state: Dict) -> Optional[str]:
    """The record a thread reply is feedback on, or None."""
    th = ev.get("thread_ts")
    if (not _from_a_person(ev) or ev.get("subtype") or not th or th == ev.get("ts")
            or not (ev.get("text") or "").strip()):
        return None
    return state["threads"].get(thread_key(ev.get("channel", ""), th))


def _name(webc, uid: str) -> str:
    try:
        p = webc.users_info(user=uid)["user"].get("profile") or {}
        return (p.get("real_name") or p.get("display_name") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _download(f: Dict, token: str, dest: Path) -> Path:
    import requests
    url = f.get("url_private_download") or f.get("url_private")
    r = requests.get(url, headers={"Authorization": "Bearer " + token}, timeout=600)
    r.raise_for_status()
    head = r.content[:200].lstrip().lower()
    # A token without files:read gets a 200 with Slack's sign-in page.
    if head.startswith((b"<!doctype", b"<html")):
        raise RuntimeError("Slack sent a sign-in page instead of the file -- "
                           "the bot token lacks files:read")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def _say(webc, channel: str, thread: str, text: str) -> str:
    r = webc.chat_postMessage(channel=channel, thread_ts=thread, text=text,
                              unfurl_links=False, unfurl_media=False)
    return r["ts"]


def post_transcript(webc, channel: str, thread: str, got: Dict, end: str,
                    who: Optional[str] = None, head: bool = True) -> None:
    msgs = R.slack_messages(got, end=end, who=who, head=head)
    if msgs:
        for m in msgs:
            _say(webc, channel, thread, m)
        return
    # Too long to read as messages -- one file, header on top.
    webc.files_upload_v2(channel=channel, thread_ts=thread,
                         content=R.as_text(got, who), filename="transcript.txt",
                         title="Transcript",
                         initial_comment=(R.header(got, who) + "\n\n" + end).strip())


def _publish(status: str) -> None:
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(REPORT_ID, REPORT_NAME, status)
    except Exception as e:  # noqa: BLE001 -- the Hub pill never blocks a reply
        _log("hub publish skipped: {}".format(e))


# ---------------------------------------------------------------- one recording

def process(webc, token: str, ev: Dict, state: Dict) -> str:
    """Transcribe one DM'd recording and send it to the rep and the coaches.
    Returns posted / told (a can't-do reply went out). Raises to retry."""
    ts, ch, f = ev["ts"], ev["channel"], audio_file(ev)
    thread = ev.get("thread_ts") or ts
    rep = ev.get("user") or ""
    with _lock:
        st = state["done"].setdefault(ts, {"tries": 0})
        st["tries"] = st.get("tries", 0) + 1
        tries = st["tries"]
    mb = (f.get("size") or 0) / 1024 / 1024
    _log("recording {} from {} ({}, {:.1f} MB, try {})".format(
        ts, rep, f.get("name"), mb, tries))
    if mb > C.MAX_MB:
        _say(webc, ch, thread, R.TOO_BIG.format(mb=int(mb)))
        return "told"
    ext = (f.get("filetype") or "audio").lower()
    dest = _download(f, token, C.AUDIO / "{}.{}".format(ts, ext))
    try:
        got = T.transcribe(dest, max_seconds=C.MAX_SECONDS)
    except T.TooLong as e:
        _say(webc, ch, thread, R.TOO_LONG.format(len=e))
        return "told"
    except T.TranscribeError as e:
        _log("  unreadable: {}".format(e))
        _say(webc, ch, thread, R.UNREADABLE)
        return "told"
    if not got["lines"]:
        _say(webc, ch, thread, R.NO_TALK)
        return "told"

    name = _name(webc, rep) or "A rep"
    first = name.split()[0]
    coaches = [uid for uid in C.COACHES if uid != rep]
    post_transcript(webc, ch, thread, got,
                    end=R.REP_END if coaches else "")
    threads = [{"who": "rep", "channel": ch, "ts": thread}]
    for uid in coaches:
        try:
            dm = webc.conversations_open(users=uid)["channel"]["id"]
            parent = webc.chat_postMessage(
                channel=dm, text=R.header(got, who=name), unfurl_links=False)["ts"]
            post_transcript(webc, dm, parent, got, head=False,
                            end=R.COACH_ASK.format(first=first))
            threads.append({"who": C.COACHES[uid], "channel": dm, "ts": parent})
        except Exception:  # noqa: BLE001 -- the rep already has theirs
            traceback.print_exc()

    rec = dict(got, ts=ts, user=rep, name=name, file=f.get("name"),
               sent_text=ev.get("text") or "",
               received=dt.datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds"),
               threads=threads, feedback=[])
    with _lock:
        _save_json(C.RECORDS / "{}.json".format(ts), rec)
        for t in threads:
            state["threads"][thread_key(t["channel"], t["ts"])] = ts
    _log("  posted: {} lines, {}s, talk {}, copies to {}".format(
        len(got["lines"]), got["seconds"], got["talk"],
        [C.COACHES[u] for u in coaches]))
    return "posted"


def save_feedback(webc, ev: Dict, key: str) -> None:
    path = C.RECORDS / "{}.json".format(key)
    with _lock:
        rec = json.loads(path.read_text(encoding="utf-8"))
        if any(x.get("ts") == ev["ts"] for x in rec.get("feedback") or []):
            return
        where = next((t["who"] for t in rec.get("threads") or []
                      if t["channel"] == ev.get("channel")), "?")
        rec.setdefault("feedback", []).append({
            "ts": ev["ts"], "user": ev.get("user"), "name": _name(webc, ev.get("user") or ""),
            "where": where, "text": ev.get("text") or ""})
        _save_json(path, rec)
    try:
        webc.reactions_add(channel=ev["channel"], timestamp=ev["ts"], name=R.SAVED)
    except Exception:  # noqa: BLE001
        pass
    _log("feedback saved on {} from {} ({})".format(key, ev.get("user"), where))


# ---------------------------------------------------------------- the loop

def worker(webc, token: str, state: Dict) -> None:
    """One recording at a time: Whisper wants the whole machine."""
    while True:
        ev = _jobs.get()
        ts = ev["ts"]
        try:
            status = process(webc, token, ev, state)
        except Exception:  # noqa: BLE001 -- one bad file never stops the bot
            traceback.print_exc()
            status = "error"
            tries = state["done"].get(ts, {}).get("tries", 0)
            if tries < C.TRIES:
                threading.Timer(RETRY_AFTER_S, _jobs.put, args=(ev,)).start()
            else:
                try:
                    _say(webc, ev["channel"], ev.get("thread_ts") or ts, R.GAVE_UP)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                status = "told"
                _publish("failed")
        with _lock:
            state["done"].setdefault(ts, {})["status"] = status
            save_state(state)
        if status == "posted":
            _publish("success")


def claim(state: Dict, ts: str) -> bool:
    """True the first time a recording is seen. Socket Mode redelivers an
    event it thinks wasn't acked -- never transcribe one twice."""
    with _lock:
        if ts in state["done"]:
            return False
        state["done"][ts] = {"tries": 0, "status": "queued"}
        save_state(state)
        return True


def on_event(webc, ev: Dict, state: Dict) -> None:
    if is_recording(ev):
        if claim(state, ev["ts"]):
            _say(webc, ev["channel"], ev.get("thread_ts") or ev["ts"], R.GOT_IT)
            _jobs.put(ev)
        return
    key = feedback_for(ev, state)
    if key:
        save_feedback(webc, ev, key)
        return
    if (_from_a_person(ev) and not ev.get("subtype") and not ev.get("thread_ts")):
        with _lock:
            last = state["helped"].get(ev["user"], 0)
            if time.time() - last < HELP_EVERY_S:
                return
            state["helped"][ev["user"]] = time.time()
            save_state(state)
        _say(webc, ev["channel"], ev["ts"], R.HELP)


def catch_up(webc, state: Dict) -> int:
    """Recordings DM'd while the bot was down, never answered."""
    oldest = "{:.6f}".format(time.time() - C.CATCHUP_HOURS * 3600)
    ims, cur = [], None
    while True:
        r = webc.users_conversations(types="im", limit=200, cursor=cur)
        ims += r.get("channels") or []
        cur = (r.get("response_metadata") or {}).get("next_cursor")
        if not cur:
            break
    n = 0
    for im in ims:
        hist = webc.conversations_history(channel=im["id"], oldest=oldest, limit=200)
        for m in sorted(hist.get("messages") or [], key=lambda m: float(m["ts"])):
            m = dict(m, channel=im["id"], channel_type="im")
            st = state["done"].get(m["ts"])
            again = st and st.get("status") in ("queued", "error") \
                and st.get("tries", 0) < C.TRIES
            if is_recording(m) and (not st or again):
                state["done"].setdefault(m["ts"], {"tries": 0, "status": "queued"})
                _jobs.put(m)
                n += 1
    return n


def _handler(client, req) -> None:
    from slack_sdk.socket_mode.response import SocketModeResponse
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
    if req.type != "events_api":
        return
    try:
        on_event(client.web_client, (req.payload or {}).get("event") or {}, _STATE)
    except Exception:  # noqa: BLE001 -- never crash the listener
        traceback.print_exc()


_STATE: Dict = {}


def run() -> int:
    global _STATE
    bt = C.token(C.BOT_TOKEN_FILE, "LUCY_TRANSCRIBER_BOT_TOKEN")
    at = C.token(C.APP_TOKEN_FILE, "LUCY_TRANSCRIBER_APP_TOKEN")
    if not bt.startswith("xoxb-") or not at.startswith("xapp-"):
        _log("missing tokens: put the xoxb- token in {} and the xapp- token in {}"
             .format(C.BOT_TOKEN_FILE, C.APP_TOKEN_FILE))
        return 2
    from slack_sdk.socket_mode.builtin import SocketModeClient
    webc = web(bt)
    me = webc.auth_test()
    _log("Lucy Transcriber is {} ({})".format(me.get("user"), me.get("user_id")))
    _STATE = load_state()
    threading.Thread(target=worker, args=(webc, bt, _STATE), daemon=True).start()
    client = SocketModeClient(app_token=at, web_client=webc)
    client.socket_mode_request_listeners.append(_handler)
    client.connect()
    _log("connected -- DMs are live")
    try:
        n = catch_up(webc, _STATE)
        if n:
            _log("picked up {} recording(s) sent while I was down".format(n))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(run())
