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


# Our own posts, recognised WITHOUT trusting a single API call. The 5-min
# tick spent 2026-08-25 asking itself "who is this?" about every headshot it
# had already made: the only guard was `user == auth_test().user_id`, and
# auth_test() sits in a bare try/except — one failed call set `me` to None
# and the guard quietly became a no-op. A finished headshot is an image
# reply like any other, so the loop fed on its own output. Now ANY of these
# marks a message as ours, and no single failure can open the loop again.
_MAX_ASKS_PER_RUN = 3
_OURS_MARKERS = ("— headshot ready", "-- headshot ready", "headshot ready")


def _is_our_post(m: dict, me: str | None) -> bool:
    if m.get("bot_id"):                       # posted by an app (us)
        return True
    if m.get("subtype") == "bot_message":
        return True
    if me and m.get("user") == me:
        return True
    text = (m.get("text") or "").lower()
    if any(k in text for k in _OURS_MARKERS):
        return True
    # Our own output files are always "<Name> - Headshot.png".
    for f in (m.get("files") or []):
        if str(f.get("name", "")).lower().endswith(" - headshot.png"):
            return True
    return False


# ---- OwnerVille upload (Phase 2) ---------------------------------------------
def _ov_upload_note(name: str, photo, act: dict) -> str:
    """Upload to the rep's OV profile; return the line to append to the
    thread reply. Never raises — an OV problem must not stop the photo post."""
    from automations.headshots import config as _cfg
    if not _cfg.OV_UPLOAD_ENABLED:
        return ""
    try:
        from automations.headshots.ov_upload import upload
        res = upload(name, photo, dry_run=False, headless=True, verbose=True)
        act["ov"] = res
        # A forgiven typo must be VISIBLE — say whose profile it landed on.
        as_who = (f" (matched to *{res['matched_as']}* in OwnerVille)"
                  if res.get("matched_as") else "")
        if res["status"] == "uploaded":
            ok = "" if res.get("verified") else " (verify pill manually)"
            return (f"\nOwnerVille: uploaded to their profile ✅{ok}{as_who}"
                    + _sheet_note(name, act))
        if res["status"] == "already_uploaded":
            return ("\nOwnerVille: a photo is already on their profile — "
                    f"left as-is{as_who}" + _sheet_note(name, act))
        return (f"\n⚠ OwnerVille: couldn't find *{name}* in View Progress "
                "(tried every campaign + Show All) — please upload this one "
                "manually")
    except Exception as e:  # noqa: BLE001
        act["ov"] = {"status": "error", "error": str(e)[:200]}
        print(f"  ⚠ OV upload failed for {name}: {type(e).__name__}: "
              f"{str(e)[:150]}")
        return ("\n⚠ OwnerVille: upload didn't go through — please upload "
                "this one manually")


def _sheet_note(name: str, act: dict) -> str:
    """Tick the rep's "Headshot Photo" box on the week's D2D OBCL tab and
    return the line for the thread reply. Never raises — the photo and the
    OV upload already happened; a sheet problem must not hide that.

    Only NEW STARTS have a row (the tab's Name/Last Name columns). Office
    staff submitting their own headshot have no row to tick, which is not an
    error — it is just reported quietly."""
    from automations.headshots import config as _cfg
    if not getattr(_cfg, "SHEET_LOG_ENABLED", True):
        return ""
    try:
        from automations.headshots.sheet_log import log_upload
        res = log_upload(name, verbose=True)
        act["sheet"] = res
        if res["status"] == "marked":
            as_who = (f" (as *{res['matched_as']}*)"
                      if res.get("matched_as", "").lower() != name.lower()
                      else "")
            return f"\nOBCL Sheet: Headshot Photo ✅ ticked{as_who}"
        if res["status"] == "already_marked":
            return "\nOBCL Sheet: already ticked"
        # Not on the tab (or too close to two names to be sure). One plain
        # line, Megan's wording (2026-08-24) — the admin just needs to know
        # to log this one by hand; the reason is in the run log.
        return "\nNot found on OBCL Sheet"
    except Exception as e:  # noqa: BLE001
        act["sheet"] = {"status": "error", "error": str(e)[:200]}
        print(f"  ⚠ sheet log failed for {name}: {type(e).__name__}: "
              f"{str(e)[:150]}")
        return "\n⚠ OBCL sheet: couldn't tick the Headshot Photo box"


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
    asked_this_run = 0

    for anchor in anchors:
        replies = cl.conversations_replies(
            channel=channel, ts=anchor["ts"], limit=200).get("messages", [])
        for m in sorted(replies, key=lambda x: x.get("ts", "")):
            if m.get("ts") == anchor["ts"]:
                continue
            if _is_our_post(m, me):
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
                # Hard cap: however wrong we are about WHAT needs a name, a
                # single run can never storm the thread again (2026-08-25).
                if asked_this_run >= _MAX_ASKS_PER_RUN:
                    print(f"  ask cap reached ({_MAX_ASKS_PER_RUN}) — "
                          f"skipping the rest this run")
                    continue
                # Ask once; the reply retries every tick, so an edited reply
                # gets picked up without re-asking.
                if not st.get("asked"):
                    asked_this_run += 1
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

            # Phase 2: push the clean headshot onto the rep's OwnerVille
            # profile. Best-effort — the thread post below goes out either
            # way, carrying the OV outcome so a miss gets handled by hand.
            ov_note = _ov_upload_note(name, out_p, act)

            # Post the finished image into the week's thread + ✅ the reply.
            with open(out_p, "rb") as fh:
                cl.files_upload_v2(
                    channel=channel, thread_ts=anchor["ts"], file=fh,
                    filename=out_p.name,
                    initial_comment=f"*{name}* — headshot ready ⤵{ov_note}")
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


def diag(channel: str | None = None) -> int:
    """READ-ONLY: say exactly what the tick sees and why it skips each reply.

    Added 2026-08-24 when two submissions sat unprocessed while the tick
    kept logging "No new headshot replies" — the per-reply decision was
    invisible. Touches nothing."""
    channel = channel or config.CHANNEL_ID
    cl = _client()
    try:
        me = cl.auth_test().get("user_id")
    except Exception:
        me = None
    print(f"channel: {channel}   this bot: {me}")
    anchors = _week_anchors(cl, channel)
    print(f"anchors found: {len(anchors)}")
    state = _load_state()
    print(f"state entries: {len(state)}  ({_STATE})")
    for a in anchors:
        print(f"\nanchor ts={a['ts']}  {(a.get('text') or '')[:60]!r}")
        replies = cl.conversations_replies(
            channel=channel, ts=a["ts"], limit=200).get("messages", [])
        print(f"  replies: {len(replies)}")
        for m in sorted(replies, key=lambda x: x.get("ts", "")):
            if m.get("ts") == a["ts"]:
                continue
            ts = m["ts"]
            st = state.get(ts, {})
            imgs = _image_files(m)
            why = []
            if m.get("subtype"):
                why.append(f"subtype={m['subtype']}")
            if _is_our_post(m, me):
                why.append("own message")
            if not imgs:
                why.append(f"no image (files={len(m.get('files') or [])})")
            if st.get("done"):
                why.append("state=DONE")
            nm = name_from_caption(m.get("text", ""))
            verdict = "SKIP: " + ", ".join(why) if why else (
                f"WOULD PROCESS as {nm!r}" if nm else "SKIP: name not parsed")
            print(f"    {ts} u={m.get('user')} "
                  f"txt={(m.get('text') or '')[:28]!r} -> {verdict}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="White-background headshot bot.")
    ap.add_argument("--dry-run", action="store_true",
                    help="process + save previews locally, post nothing")
    ap.add_argument("--channel", default=None,
                    help="channel id to watch (overrides config / env)")
    ap.add_argument("--diag", action="store_true",
                    help="READ-ONLY: show what the tick sees per reply")
    ap.add_argument("--file", default=None,
                    help="process ONE local photo instead of polling Slack")
    ap.add_argument("--name", default=None,
                    help="the person's name (with --file)")
    args = ap.parse_args(argv)

    if args.diag:
        return diag(channel=args.channel)

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
