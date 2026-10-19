"""Lucy Broadcast — poll one Slack channel, re-send each new post everywhere.

Every run (launchd fires it every 5 min on Lucy 1):
  1. Read the last N top-level messages in config.SOURCE_CHANNEL_ID.
  2. Keep real posts from members (not Lucy's own replies, not joins/edits,
     not blank) that are at least SETTLE_SECONDS old.
  3. For each one, send it to every config.SLACK_DESTINATIONS channel (as
     Lucy, text + every attached file) and every config.IMESSAGE_GROUPS group
     (text, then the pictures/files).
  4. Record per-destination success in a state file, so a destination that
     failed is retried next tick and one that worked is NEVER sent twice.
  5. When every destination has it: ✅ on the post + a thread reply listing
     where it went. If one still fails after MAX_ATTEMPTS: ⚠️ + a reply naming it.

Same shape as automations.sara_down (the #saraplus-issues scanner): same lock,
same first-run BASELINE (installing never re-sends old posts), same verified
Slack downloads (a token missing files:read hands back an HTML page with
HTTP 200 — every file's bytes are checked).

LIMITATION (tell users): only TOP-LEVEL messages are read. Text and pictures
must be in the SAME message; a picture added as a thread reply is not sent.

    python -m automations.lucy_broadcast.run --dry-run          # preview, send nothing
    python -m automations.lucy_broadcast.run --dry-run --channel C0TEST123
    python -m automations.lucy_broadcast.run --whois raffi127@gmail.com
    python -m automations.lucy_broadcast.run                    # live (Lucy 1)

iMessage only works on a Mac signed into Messages (Lucy 1). On any other
machine the iMessage legs are recorded as failed and retried — the Hub card
routes runs to Lucy 1 so this doesn't happen in practice.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from automations.lucy_broadcast import config

_DIR = Path.home() / ".config" / "lucy-broadcast"
_STATE = _DIR / "state.json"
_LOCK = _DIR / "lucy_broadcast.lock"
# Downloaded attachments live here for the length of a run. Messages can't read
# from here (sandbox) — text_post copies each into ~/Pictures before sending.
_WORK = Path(tempfile.gettempdir()) / "lucy-broadcast"


class BroadcastError(RuntimeError):
    pass


# ---- lock + state (same idiom as sara_down) ---------------------------------
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


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


# ---- which messages count ----------------------------------------------------
# Plain posts have no subtype; "file_share" is how older clients mark a post
# with an upload. Everything else (joins, bot_message, channel_topic…) is noise.
_POST_SUBTYPES = (None, "", "file_share")


def is_broadcast_post(m: dict, *, own_user: str, now: float,
                      settle: int) -> bool:
    if m.get("subtype") not in _POST_SUBTYPES:
        return False
    if m.get("bot_id") or (own_user and m.get("user") == own_user):
        return False                        # Lucy's own ✅ replies etc.
    if not (m.get("text") or "").strip() and not m.get("files"):
        return False                        # never relay a blank post
    try:
        if now - float(m.get("ts", "0")) < settle:
            return False                    # let a quick edit land first
    except ValueError:
        return False
    return True


# ---- Slack markup -> plain text (for iMessage) -------------------------------
_LINK = re.compile(r"<([^<>|]+)(?:\|([^<>]+))?>")


def slack_to_plain(text: str, names: Optional[Dict[str, str]] = None) -> str:
    """Turn Slack's wire format into what a person would read on a phone:
    <@U123> -> @Name, <#C1|sales> -> #sales, <https://x|Click> -> Click (https://x),
    <!channel> -> dropped, *bold*/_italic_/~strike~ markers removed, &amp; -> &."""
    names = names or {}

    def sub(mt):
        target, label = mt.group(1), mt.group(2)
        if target.startswith("@"):
            uid = target[1:]
            return "@" + (label or names.get(uid) or "someone")
        if target.startswith("#"):
            return "#" + (label or "channel")
        if target.startswith("!"):
            return ""                        # @here/@channel mean nothing in a text
        if label and label != target:
            return "%s (%s)" % (label, target.replace("mailto:", ""))
        return target.replace("mailto:", "")

    out = _LINK.sub(sub, text or "")
    out = re.sub(r"(?<![\w*])\*(\S(?:.*?\S)?)\*(?![\w*])", r"\1", out)
    out = re.sub(r"(?<![\w_])_(\S(?:.*?\S)?)_(?![\w_])", r"\1", out)
    out = re.sub(r"(?<![\w~])~(\S(?:.*?\S)?)~(?![\w~])", r"\1", out)
    out = html.unescape(out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _mention_names(cl, text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for uid in set(re.findall(r"<@([A-Z0-9]+)", text or "")):
        try:
            u = cl.users_info(user=uid)["user"]
            p = u.get("profile") or {}
            out[uid] = (p.get("display_name") or p.get("real_name")
                        or u.get("name") or "someone")
        except Exception:
            pass
    return out


# ---- attachments: download + VERIFY ------------------------------------------
def _looks_like_html(data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def download_files(msg: dict, dest_dir: Path) -> List[Path]:
    """Download every file on the post into dest_dir. Images must sniff as real
    image bytes; any file must not be Slack's HTML sign-in page. Raises
    BroadcastError if any file can't be fetched — the whole post then waits for
    the next tick instead of going out with a broken attachment."""
    from automations.sara_down import run as sd     # shared verified-download helpers
    files = msg.get("files") or []
    if not files:
        return []
    toks = sd._tokens()
    if not toks:
        raise BroadcastError("No Slack token on this machine — can't download "
                             "the attachments.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: List[Path] = []
    for i, f in enumerate(files):
        url = f.get("url_private_download") or f.get("url_private") or ""
        name = f.get("name") or "file-%d" % (i + 1)
        if not url:
            raise BroadcastError("Slack gave no download link for %r." % name)
        is_img = str(f.get("mimetype", "")).startswith("image/")
        got = None
        problems = []
        for label, tok in toks:
            try:
                data = sd._download(url, tok)
            except Exception as e:  # noqa: BLE001
                problems.append("%s: %s" % (label, type(e).__name__))
                continue
            if (is_img and sd._sniff_image(data)) or (
                    not is_img and data and not _looks_like_html(data)):
                got = data
                break
            problems.append("%s: got a sign-in page, not the file" % label)
        if got is None:
            raise BroadcastError(
                "Couldn't download %r (%s). The Lucy Slack token needs the "
                "files:read scope — run `lucy slack_whoami` to check."
                % (name, "; ".join(problems)))
        # Unique name per file so two "image.png" uploads don't overwrite each other.
        p = dest_dir / ("%02d-%s" % (i + 1, re.sub(r"[^\w.\- ]", "_", name)))
        p.write_bytes(got)
        out.append(p)
    return out


# ---- the senders (swappable in tests) ----------------------------------------
def send_slack(cl, channel: str, text: str, files: List[Path]) -> None:
    if files:
        kw = {"channel": channel,
              "file_uploads": [{"file": str(p), "filename": p.name[3:] or p.name}
                               for p in files]}
        if text.strip():
            kw["initial_comment"] = text
        resp = cl.files_upload_v2(**kw)
    else:
        resp = cl.chat_postMessage(channel=channel, text=text,
                                   unfurl_links=True, unfurl_media=True)
    if not resp.get("ok"):
        raise BroadcastError("Slack said not ok: %s" % resp.get("error"))


def send_imessage(group: str, text: str, files: List[Path]) -> None:
    if platform.system() != "Darwin":
        raise BroadcastError("iMessage only sends from a Mac (Lucy 1).")
    from automations.b2b_dispositions import text_post
    if text.strip():
        text_post.send_text_to_group(group, text, dry_run=False)
    if files:
        # text="" -> send_to_group skips the text leg (already sent above,
        # through the path that escapes newlines correctly) and sends files.
        text_post.send_to_group(group, "", files, dry_run=False)


def _preview_imessage(group: str) -> str:
    """Dry-run check that the group name resolves to exactly one chat."""
    if platform.system() != "Darwin":
        return "not checked (not a Mac)"
    try:
        from automations.b2b_dispositions import text_post
        info = text_post.resolve_group(group)
        return "found (%d people)" % len(info.get("participants") or [])
    except Exception as e:  # noqa: BLE001
        return "NOT FOUND: %s" % str(e)[:120]


def _channel_label(cl, cid: str) -> str:
    try:
        return "#" + cl.conversations_info(channel=cid)["channel"]["name"]
    except Exception:
        return cid


def _fmt_when(ts: str) -> str:
    return datetime.fromtimestamp(float(ts)).strftime("%m/%d %I:%M %p").lstrip("0")


# ---- destinations: config + the how-it-works thread ---------------------------
def resolve_destinations(cl, channel: str, own: str, state: dict, *,
                         dry_run: bool,
                         groups_reader: Optional[Callable] = None
                         ) -> Tuple[List[str], List[str], str]:
    """(slack channel ids, iMessage group names, note) for THIS tick.

    config lists are the fixed base; when DESTINATIONS_THREAD_TS is set the
    thread's replies are replayed on top (see destinations.py). New replies get
    a 👀/✅ reaction and ONE summary reply from Lucy (live runs only)."""
    from automations.lucy_broadcast import destinations as dz
    base_slack = [c for c in config.SLACK_DESTINATIONS if c]
    base_groups = [g for g in config.IMESSAGE_GROUPS if g]
    thread = config.DESTINATIONS_THREAD_TS
    if not thread:
        return base_slack, base_groups, ""
    replies = dz.thread_replies(cl, channel, thread, own)
    if not replies:
        return base_slack, base_groups, ""
    groups_known = (groups_reader or dz.imessage_groups)()
    if groups_known is None and not dry_run:
        # Can't see the text groups -> the list would silently lose them and
        # posts would go out Slack-only, marked done. Send nothing this tick.
        raise BroadcastError("Can't read the iMessage group list on this "
                             "machine — run on Lucy 1 (Messages signed in).")
    chans = dz.member_channels(cl)
    slack, texts, per = dz.replay(replies, chans, groups_known or [],
                                  base_slack, base_groups)
    slack = [c for c in slack if c != channel]

    # Tell people what changed — once per reply (re-done if they edit it).
    # First live run: replies already there (e.g. Megan's own instructions)
    # still count, but don't get a "couldn't tell" answer.
    first = "_dest_replies" not in state
    seen = state.setdefault("_dest_replies", {})
    new = [r for r in replies
           if seen.get(r["ts"]) != (r.get("edited") or {}).get("ts", "1")]
    if new and not dry_run:
        added, removed, missing, unclear = [], [], [], 0
        for r in new:
            p = per[r["ts"]]
            names = (["#" + chans.get(c, c) for c in p["slack"]] + p["groups"])
            (removed if p["remove"] else added).extend(
                n for n in names if n not in (removed if p["remove"] else added))
            missing.extend(n for n in p["not_member"] if n not in missing)
            seen[r["ts"]] = (r.get("edited") or {}).get("ts", "1")
            if not names and not p["not_member"]:
                if first or p.get("example"):
                    continue
                unclear += 1
            emoji = "white_check_mark" if names else (
                "warning" if p["not_member"] else "thinking_face")
            try:
                cl.reactions_add(channel=channel, timestamp=r["ts"], name=emoji)
            except Exception:
                pass
        lines = []
        if added:
            lines.append("✅ *Added:* " + ", ".join(added))
        if removed:
            lines.append("➖ *Removed:* " + ", ".join(removed))
        if missing:
            lines.append("⚠️ *Lucy isn't in:* " + ", ".join(missing)
                         + " — invite @Lucy Reporting there, then reply again.")
        if unclear:
            lines.append("🤔 Couldn't tell what to add from %d repl%s. For Slack, "
                         "type # and pick the channel. For texts, write the "
                         "group name exactly as it shows in Messages."
                         % (unclear, "y" if unclear == 1 else "ies"))
        if lines:
            lines.append("")
            lines.append(_dest_summary(slack, texts, chans))
            try:
                cl.chat_postMessage(channel=channel, thread_ts=thread,
                                    text="\n".join(lines))
            except Exception:
                pass
    return slack, texts, _dest_summary(slack, texts, chans)


def _dest_summary(slack: List[str], texts: List[str],
                  chans: Dict[str, str]) -> str:
    s = ", ".join("#" + chans.get(c, c) for c in slack) or "none"
    t = ", ".join(texts) or "none"
    return "*Now sending to:*\n• Slack: %s\n• Texts: %s" % (s, t)


# ---- the polled processor ----------------------------------------------------
def scan(*, dry_run: bool = True, channel: Optional[str] = None,
         limit: Optional[int] = None, cl=None,
         slack_sender: Callable = send_slack,
         imessage_sender: Callable = send_imessage,
         now: Optional[float] = None,
         groups_reader: Optional[Callable] = None) -> List[dict]:
    """Relay every new post. Returns one action dict per post looked at."""
    channel = channel or config.SOURCE_CHANNEL_ID
    if not channel:
        raise BroadcastError(
            "No source channel yet. Put its ID in "
            "automations/lucy_broadcast/config.py (SOURCE_CHANNEL_ID).")
    cl = cl or _client()
    now = now if now is not None else time.time()
    try:
        own = cl.auth_test().get("user_id", "")
    except Exception:
        own = ""
    state = _load_state()
    slack_dests, groups, dest_note = resolve_destinations(
        cl, channel, own, state, dry_run=dry_run, groups_reader=groups_reader)
    if channel in slack_dests:
        raise BroadcastError("The source channel is also listed as a "
                             "destination — that would loop forever.")
    # Nothing to send to yet: posts are left untouched and go out once a
    # destination is added (if still under MAX_POST_AGE_HOURS).
    no_dest = not slack_dests and not groups
    if no_dest:
        print("No destinations yet — reply in the how-it-works thread to add some.")

    # Paged (posts with files are big; one large read gets cut off on Lucy 1).
    from automations.shared import slack_retry
    msgs = slack_retry.read_paged(cl.conversations_history, channel=channel,
                                  limit=limit or config.SCAN_LIMIT,
                                  page=10).get("messages", [])
    # First live run on a machine: mark what's already there as done, send
    # nothing — installing must never re-blast old posts.
    baseline = not state.get("_baselined") and not dry_run
    actions: List[dict] = []

    for m in sorted(msgs, key=lambda x: x.get("ts", "")):
        if not is_broadcast_post(m, own_user=own, now=now,
                                 settle=config.SETTLE_SECONDS):
            continue
        ts = m["ts"]
        st = state.get(ts) or {}
        if st.get("done") or st.get("gave_up"):
            continue
        if now - float(ts) > config.MAX_POST_AGE_HOURS * 3600:
            continue                        # too old to send now
        if config.APPROVED_POSTERS and m.get("user") not in config.APPROVED_POSTERS:
            actions.append({"ts": ts, "action": "ignored_unapproved",
                            "poster": m.get("user", "")})
            continue
        if baseline:
            state[ts] = {"done": True, "baselined": True}
            actions.append({"ts": ts, "action": "baselined"})
            continue
        if no_dest and not dry_run:
            continue

        raw = m.get("text") or ""
        plain = slack_to_plain(raw, _mention_names(cl, raw))
        act = {"ts": ts, "action": "relay", "when": _fmt_when(ts),
               "slack_text": raw, "imessage_text": plain,
               "files": [f.get("name") for f in (m.get("files") or [])],
               "sent": [], "failed": {}}

        if dry_run:
            act["dry_run"] = True
            act["slack"] = [_channel_label(cl, c) for c in slack_dests]
            act["imessage"] = {g: _preview_imessage(g) for g in groups}
            actions.append(act)
            continue

        try:
            files = download_files(m, _WORK / ts.replace(".", "_"))
        except BroadcastError as e:
            # Nothing sent, nothing recorded as an attempt at a destination —
            # but count it so a permanently broken file eventually gives up.
            st["attempts"] = st.get("attempts", 0) + 1
            st.setdefault("errors", {})["download"] = str(e)[:300]
            act["failed"]["download"] = str(e)
            _finish(cl, channel, ts, st, slack_dests, groups, act)
            state[ts] = st
            _save_state(state)
            actions.append(act)
            continue

        done = st.setdefault("delivered", {})
        legs: List[Tuple[str, Callable]] = (
            [("slack:" + c, lambda c=c: slack_sender(cl, c, raw, files))
             for c in slack_dests]
            + [("imessage:" + g, lambda g=g: imessage_sender(g, plain, files))
               for g in groups])
        for key, send in legs:
            if done.get(key):
                continue
            try:
                send()
                done[key] = time.time()
                act["sent"].append(key)
            except Exception as e:  # noqa: BLE001 — one bad leg never blocks the rest
                st.setdefault("errors", {})[key] = "%s: %s" % (
                    type(e).__name__, str(e)[:200])
                act["failed"][key] = str(e)
            # Save after EVERY leg: a crash mid-run must not re-send the
            # destinations that already got it.
            state[ts] = st
            _save_state(state)
        st["attempts"] = st.get("attempts", 0) + (1 if act["failed"] else 0)
        _finish(cl, channel, ts, st, slack_dests, groups, act)
        state[ts] = st
        _save_state(state)
        actions.append(act)

    if baseline:
        state["_baselined"] = True
    if not dry_run:
        _save_state(state)          # baseline + which thread replies were answered
    return actions


def _finish(cl, channel: str, ts: str, st: dict, slack_dests: List[str],
            groups: List[str], act: dict) -> None:
    """Mark the post done / given-up and tell the poster in its thread."""
    done = st.get("delivered") or {}
    want = ["slack:" + c for c in slack_dests] + ["imessage:" + g for g in groups]
    if all(done.get(k) for k in want) and "download" not in act["failed"]:
        st["done"] = True
        chans = [_channel_label(cl, c) for c in slack_dests]
        where = []
        if chans:
            where.append(", ".join(chans))
        if groups:
            where.append("%d text group%s (%s)" % (
                len(groups), "" if len(groups) == 1 else "s", ", ".join(groups)))
        _ack(cl, channel, ts, "white_check_mark",
             ":white_check_mark: *Sent out* to " + " and ".join(where) + ".")
        try:
            from automations.day_orchestrator.hub_publish import publish_done
            publish_done("lucy_broadcast", "Lucy Broadcast", "success")
        except Exception:
            pass
        return
    if st.get("attempts", 0) >= config.MAX_ATTEMPTS:
        st["gave_up"] = True
        missing = [k.split(":", 1)[1] for k in want if not done.get(k)]
        if "download" in act["failed"]:
            missing = ["everywhere (the attachment wouldn't download)"]
        else:
            missing = [_channel_label(cl, x) if x in slack_dests else x
                       for x in missing]
        _ack(cl, channel, ts, "warning",
             ":warning: *Couldn't send this to:* " + ", ".join(missing)
             + ". Everywhere else got it. Please send it there by hand.")
        act["gave_up"] = True


def _ack(cl, channel: str, ts: str, emoji: str, text: str) -> None:
    try:
        cl.reactions_add(channel=channel, timestamp=ts, name=emoji)
    except Exception:
        pass
    try:
        cl.chat_postMessage(channel=channel, thread_ts=ts, text=text)
    except Exception:
        pass


def whois(query: str) -> None:
    from automations.shared import slack_metrics_post as smp
    print("%s  ->  %s" % (query, smp._resolve_user_id(_client(), query)))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Lucy Broadcast relay.")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be sent where, send nothing")
    ap.add_argument("--channel", default=None,
                    help="source channel id (overrides config)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--whois", metavar="EMAIL_OR_NAME", default=None)
    args = ap.parse_args(argv)

    if args.whois:
        whois(args.whois)
        return 0
    if not acquire_lock():
        print("Another lucy_broadcast run is active — skipping this tick.")
        return 0
    try:
        actions = scan(dry_run=args.dry_run, channel=args.channel,
                       limit=args.limit)
    except BroadcastError as e:
        print("NOT RUN: %s" % e)
        return 2
    finally:
        release_lock()

    if not actions:
        print("No new posts to send out.")
        return 0
    rc = 0
    for a in actions:
        if a["action"] == "baselined":
            continue
        if a["action"] == "ignored_unapproved":
            print("  ignored (not an approved poster): %s ts=%s"
                  % (a["poster"], a["ts"]))
            continue
        if a.get("dry_run"):
            print("\nWOULD SEND post from %s  (ts=%s)" % (a["when"], a["ts"]))
            print("  Slack  -> %s" % (", ".join(a["slack"]) or "(none set)"))
            for g, ok in a["imessage"].items():
                print("  Text   -> %s  [%s]" % (g, ok))
            if not a["imessage"]:
                print("  Text   -> (none set)")
            print("  Files  -> %s" % (", ".join(a["files"]) or "none"))
            print("  --- Slack text ---\n  " + a["slack_text"].replace("\n", "\n  "))
            print("  --- iMessage text ---\n  " + a["imessage_text"].replace("\n", "\n  "))
            continue
        print("  post %s: sent to %d, failed %d%s" % (
            a["when"], len(a["sent"]), len(a["failed"]),
            " (GAVE UP)" if a.get("gave_up") else ""))
        for k, err in a["failed"].items():
            print("    ✗ %s: %s" % (k, err[:200]))
            rc = 1
    n_base = sum(1 for a in actions if a["action"] == "baselined")
    if n_base:
        print("BASELINE (first run on this machine): marked %d existing post(s) "
              "as already sent — sent nothing. New posts from here on go out."
              % n_base)
    return rc


if __name__ == "__main__":
    sys.exit(main())
