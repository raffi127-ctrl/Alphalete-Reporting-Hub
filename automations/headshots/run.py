"""Headshot bot — watch the Monday headshot threads, return finished headshots.

Raf's ask (2026-08-23, #l10-alphalete "Headshot Orientation posting"), shaped
by Megan 2026-08-23: weekly_thread.py starts a thread each Monday in
#11280-alphalete-marketing-inc-rafael-hidalgo asking people to reply with the
headshot photo AND the person's name. This side runs on a tick and:

  1. Finds this week's and last week's Monday threads (by their marker line —
     last week's still catches stragglers).
  2. For each unhandled reply that carries an image: the reply text is the
     person's name ("First Last" — capitalization is fixed automatically).
     Photo but no name -> ask once in the thread and retry next tick.
  3. Cut the background, put the person on pure white, crop to
     head-and-shoulders. No text on the photo — the name is the FILENAME.
  4. Post the finished image back in the thread and ✅ the reply.
     A copy is archived in output/headshots/ for the Roadmap upload —
     automating the Roadmap portal itself is Phase 2.
  5. Record the reply ts in a state file so nothing processes twice.
     (No go-live baseline needed: the threads only exist because WE post
     them, so every reply in them is real work.)

Safe by default: --dry-run (the default until Megan flips it live) processes
the photos and writes previews locally but posts NOTHING to Slack.

    # preview: process replies in the current threads, post nothing
    python -m automations.headshots.run --dry-run

    # one local file end-to-end, no Slack at all:
    python -m automations.headshots.run --file photo.jpg --name "First Last"

    # live (after Megan's go):
    python -m automations.headshots.run

Cross-platform: Slack API + Pillow + rembg; no Mac-only paths.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from automations.headshots import config
from automations.shared.name_case import titlecase_name

_STATE = Path.home() / ".config" / "headshots" / "state.json"
_LOCK = Path.home() / ".config" / "headshots" / "headshots.lock"


class HeadshotError(RuntimeError):
    pass


# ---- singleton lock / state (same idiom as sara_down) ------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def acquire_lock() -> bool:
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    if _LOCK.exists():
        try:
            old = int(_LOCK.read_text().strip() or "0")
        except ValueError:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            return False
    _LOCK.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        if _LOCK.exists() and _LOCK.read_text().strip() == str(os.getpid()):
            _LOCK.unlink()
    except OSError:
        pass


def _load_state() -> dict:
    try:
        return json.loads(_STATE.read_text())
    except Exception:
        return {}


def _save_state(s: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(s, indent=2))


# ---- Slack plumbing (shared Lucy tokens; downloads verified like sara_down) --
def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _image_files(msg: dict) -> list[dict]:
    return [f for f in (msg.get("files") or [])
            if str(f.get("mimetype", "")).startswith("image/")]


def _download_image(f: dict) -> bytes:
    """Download one Slack file, verified to be real image bytes (a token
    missing files:read gets an HTML sign-in page with HTTP 200 — the exact
    trap sara_down documents). Reuses its sniffer + token fallback."""
    from automations.sara_down.run import SaraDownError, _download_image as dl
    try:
        data, _subtype = dl(f)
    except SaraDownError as e:
        raise HeadshotError(str(e)) from e
    return data


# ---- the name comes from the caption ----------------------------------------
_MENTION = re.compile(r"<[@#!][^>]*>|<https?://[^>]*>|:[a-z0-9_+-]+:")

# Words that mean the caption is chatter, not a name. Keeps "headshot for
# roadmap pls" from becoming somebody called Headshot For Roadmap Pls.
_NOT_NAMES = {
    "headshot", "headshots", "photo", "photos", "pic", "picture", "picture.",
    "new", "hire", "hires", "start", "starts", "for", "the", "a", "an",
    "please", "pls", "plz", "here", "is", "this", "team", "roadmap", "and",
    "today", "orientation", "submission", "upload", "needs", "need", "asap",
}


def name_from_caption(text: str) -> str | None:
    """Pull "First Last" out of the post's caption, or None if it isn't one.

    Strips mentions/links/emoji, then accepts 2-4 capitalizable words that
    look like a name (letters, hyphens, apostrophes, a roman suffix). The
    admins' habit is to post the photo with just the name as the caption.
    """
    cleaned = _MENTION.sub(" ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    words = cleaned.split()
    if not 2 <= len(words) <= 4:
        return None
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", w) for w in words):
        return None
    if any(w.lower().strip(".") in _NOT_NAMES for w in words):
        return None
    return titlecase_name(cleaned)


# ---- outputs -----------------------------------------------------------------
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _archive_dir() -> Path:
    d = _repo_root() / config.OUTPUT_DIR / datetime.now().strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 '-]", "", name).strip() or "headshot"


def process_one(data: bytes, name: str) -> Path:
    """Run the pipeline and archive the finished headshot, named for the
    person so the admins (and Phase 2) know whose it is."""
    from automations.headshots import process as P
    out = P.process(data)
    path = _archive_dir() / f"{_safe_stem(name)} - Headshot.png"
    out.save(path)
    return path


# ---- the polled processor ----------------------------------------------------
def _week_anchors(cl, channel: str) -> list[dict]:
    """This week's and last week's Monday threads (last week's catches
    stragglers who reply over the weekend)."""
    import datetime as dt

    from automations.headshots import weekly_thread as wt
    anchors = []
    this_mon = wt.week_monday()
    for monday in (this_mon, this_mon - dt.timedelta(days=7)):
        a = wt.find_week_anchor(cl, channel, monday=monday)
        if a and all(a["ts"] != b["ts"] for b in anchors):
            anchors.append(a)
    return anchors


def scan(*, dry_run: bool = True, channel: str | None = None) -> list[dict]:
    channel = channel or config.CHANNEL_ID
    if not channel:
        raise HeadshotError(
            "No channel to watch. Set config.CHANNEL_ID (or pass --channel / "
            "HEADSHOTS_CHANNEL_ID).")

    cl = _client()
    me = None            # Lucy's own user id — never process our own replies
    try:
        me = cl.auth_test().get("user_id")
    except Exception:
        pass

    anchors = _week_anchors(cl, channel)
    if not anchors:
        print("No Monday headshot thread up yet (weekly_thread posts it).")
        return []

    state = _load_state()
    actions: list[dict] = []

    for anchor in anchors:
        replies = cl.conversations_replies(
            channel=channel, ts=anchor["ts"], limit=200).get("messages", [])
        for m in sorted(replies, key=lambda x: x.get("ts", "")):
            if m.get("ts") == anchor["ts"]:
                continue
            if me and m.get("user") == me:
                continue
            imgs = _image_files(m)
            if not imgs:
                continue
            ts = m["ts"]
            st = state.get(ts, {})
            if st.get("done"):
                continue

            name = name_from_caption(m.get("text", ""))
            if not name:
                # Ask once; the reply retries every tick, so an edited reply
                # gets picked up without re-asking.
                if not st.get("asked"):
                    actions.append({"ts": ts, "action": "ask_name"})
                    if not dry_run:
                        try:
                            who = m.get("user", "")
                            cl.chat_postMessage(
                                channel=channel, thread_ts=anchor["ts"],
                                text=(f"<@{who}> got the photo — who is it? "
                                      "Edit your reply to include the "
                                      "person's *First Last* name and I'll "
                                      "make the headshot."))
                            state.setdefault(ts, {})["asked"] = True
                            _save_state(state)
                        except Exception:
                            pass
                continue

            try:
                data = _download_image(imgs[0])
            except HeadshotError as e:
                print(f"  ⚠ SKIPPED ts={ts} — {e}")
                actions.append({"ts": ts, "action": "download_failed",
                                "error": str(e)})
                continue

            out_p = process_one(data, name)
            act = {"ts": ts, "action": "processed", "name": name,
                   "file": str(out_p)}

            if dry_run:
                act["dry_run"] = True
                actions.append(act)
                continue

            # Post the finished image into the week's thread + ✅ the reply.
            with open(out_p, "rb") as fh:
                cl.files_upload_v2(
                    channel=channel, thread_ts=anchor["ts"], file=fh,
                    filename=out_p.name,
                    initial_comment=f"*{name}* — headshot ready ⤵")
            state.setdefault(ts, {})["done"] = True
            state[ts]["name"] = name
            _save_state(state)
            try:
                cl.reactions_add(channel=channel, timestamp=ts,
                                 name="white_check_mark")
            except Exception:
                pass
            try:
                from automations.day_orchestrator.hub_publish import publish_done
                publish_done("headshots", "Headshot Bot", "success")
            except Exception:
                pass
            act["posted"] = True
            actions.append(act)

    return actions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="White-background headshot bot.")
    ap.add_argument("--dry-run", action="store_true",
                    help="process + save previews locally, post nothing")
    ap.add_argument("--channel", default=None,
                    help="channel id to watch (overrides config / env)")
    ap.add_argument("--file", default=None,
                    help="process ONE local photo instead of polling Slack")
    ap.add_argument("--name", default=None,
                    help="the person's name (with --file)")
    args = ap.parse_args(argv)

    if args.file:
        if not args.name:
            ap.error("--file needs --name \"First Last\"")
        out_p = process_one(Path(args.file).read_bytes(),
                            titlecase_name(args.name))
        print(f"headshot: {out_p}")
        return 0

    if not acquire_lock():
        print("Another headshots run is active — skipping this tick.")
        return 0
    try:
        actions = scan(dry_run=args.dry_run, channel=args.channel)
    finally:
        release_lock()

    if not actions:
        print("No new headshot replies.")
        return 0
    for a in actions:
        if a["action"] == "ask_name":
            print(f"  needs a name (reply text wasn't one): ts={a['ts']}")
        elif a["action"] == "download_failed":
            print(f"  download failed: ts={a['ts']}")
        elif a.get("dry_run"):
            print(f"  WOULD post: {a['name']}  [{a['file']}]")
        else:
            print(f"  POSTED: {a['name']}")
    if any(a["action"] == "download_failed" for a in actions):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
