"""Sara+ issue-escalation bot — poll #saraplus-issues, email the Sara+ support team.

Every run (launchd fires it every 5 min on the mini):
  1. Read the last N messages in the #saraplus-issues channel.
  2. Keep the ones that (a) carry an image and (b) are from an allowed poster
     (config.APPROVED_POSTERS; empty = any member of the private channel).
  3. For each one we haven't handled before, download the screenshot and send
     the escalation email: To = Sara+ support team, CC = our leaders, the photo
     attached. Everyone can reply-all from there.
  4. Record the message ts in a state file so it never sends twice, and add a
     ✅ on the Slack post so the field sees it was escalated.

Safe by default: --dry-run builds and previews the email (writes a .eml) but
sends nothing, and a real run with no recipients configured refuses to send
with a clear message instead of half-escalating.

    # preview against a test channel, no email sent:
    python -m automations.sara_down.run --dry-run --channel C0TEST123

    # look up a leader's Slack id (to fill APPROVED_POSTERS):
    python -m automations.sara_down.run --whois dylanjtwaddle@gmail.com

    # live (only once config is filled + Megan says go):
    python -m automations.sara_down.run

Cross-platform: pure Slack API + Gmail SMTP, no Mac-only calls. The 5-min
schedule is a launchd job on the mini (deploy/com.alphalete.sara-down.plist);
it also runs on demand from the Hub / any machine.
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import tempfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import requests

from automations.sara_down import config
# Reuse the one canonical Gmail send path (same account, app-password, SMTP).
from automations.scheduled_6_days_out.email_send import (
    FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password,
)

_STATE = Path.home() / ".config" / "sara-down" / "state.json"
_LOCK = Path.home() / ".config" / "sara-down" / "sara_down.lock"


class SaraDownError(RuntimeError):
    pass


# ---- singleton lock (never let two runs double-send) ------------------------
# Same idiom as automations.brand_audit.social_inbox: a pid lockfile so an
# overlapping run (e.g. the 5-min launchd tick plus a manual Hub run) can't both
# process the same post before the state file is written.
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


# ---- Slack helpers (reuse the shared Lucy tokens) ---------------------------
def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _user_token() -> str:
    from automations.shared import slack_metrics_post as smp
    return smp._load_token()


def _bot_token() -> str | None:
    from automations.shared import slack_metrics_post as smp
    try:
        return smp._load_bot_token()
    except Exception:
        return None


def _image_files(msg: dict) -> list[dict]:
    return [f for f in (msg.get("files") or [])
            if str(f.get("mimetype", "")).startswith("image/")]


def _download(url: str) -> bytes:
    # url_private needs files:read — prefer the bot token (has it; bot must be in
    # the channel), fall back to the user token.
    tok = _bot_token() or _user_token()
    r = requests.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    r.raise_for_status()
    return r.content


def _poster_name(cl, user_id: str) -> str:
    """A human name for the person who posted, for the 'Reported by' line."""
    try:
        p = cl.users_info(user=user_id)["user"]
        prof = p.get("profile", {})
        return (prof.get("real_name") or p.get("real_name")
                or prof.get("display_name") or user_id)
    except Exception:
        return user_id


def _fmt_when(ts: str) -> str:
    """Slack ts (epoch seconds) -> 'Jul 17, 2:04 PM'. Cross-platform: no %-I /
    %-d (both break on Windows); we strip a leading zero from the hour by hand.
    Left in UTC-derived local naive time is avoided — we render in the mini's
    local zone via the OS by using astimezone()."""
    try:
        dt = datetime.fromtimestamp(float(ts)).astimezone()
    except Exception:
        dt = datetime.now(timezone.utc).astimezone()
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%b')} {int(dt.strftime('%d'))}, {hour}:{dt.strftime('%M %p')}"


def _fmt_date(ts: str) -> str:
    """Slack ts -> 'M/D/YYYY' (e.g. '7/17/2026') for the subject line.
    Built by hand (not %-m/%-d, which break on Windows)."""
    try:
        dt = datetime.fromtimestamp(float(ts)).astimezone()
    except Exception:
        dt = datetime.now(timezone.utc).astimezone()
    return f"{dt.month}/{dt.day}/{dt.year}"


_POLISH_MODEL = "claude-haiku-4-5-20251001"   # fast; this is a light spell/grammar pass
_POLISH_SYSTEM = (
    "You are a strict copy-editor for short internal issue reports typed on a phone. "
    "Correct ONLY genuine spelling errors and clear grammatical mistakes "
    "(e.g. 'isnt' -> \"isn't\", \"differen't\" -> 'different', 'were' -> \"we're\"). "
    "Make the SMALLEST possible edit. Do NOT reword, rephrase, or improve style. "
    "Do NOT reorder, split, merge, or add/remove sentences. Keep the EXACT same "
    "words, numbers, and symbols the writer used — do not turn digits into words "
    "('2' stays '2'), do not change '&' to 'and', do not swap synonyms, do not add "
    "or remove punctuation except to fix an outright error. Preserve every "
    "identifier exactly (SPM numbers, ABP, AT&T, Sara+, dollar amounts). Never add "
    "a greeting, sign-off, quotes, or commentary. Return ONLY the corrected text; "
    "if nothing is misspelled or ungrammatical, return it completely unchanged."
)


def _polish(text: str) -> str:
    """Return `text` with spelling/grammar fixed via Claude. Best-effort: on ANY
    problem (no API key, network/API error, empty reply) return the ORIGINAL text
    unchanged — an escalation is urgent and must never be blocked by this pass."""
    raw = (text or "").strip()
    if not raw:
        return raw
    try:
        import anthropic
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        resp = client.messages.create(
            model=_POLISH_MODEL, max_tokens=600, system=_POLISH_SYSTEM,
            messages=[{"role": "user", "content": raw}],
        )
        out = "".join(b.text for b in resp.content if b.type == "text").strip()
        return out or raw
    except Exception as e:
        print(f"  (grammar pass skipped: {type(e).__name__}: {str(e)[:80]}) — "
              "using the original text")
        return raw


# ---- the email --------------------------------------------------------------
def build_email(image_bytes: bytes, filename: str, *, reporter: str,
                when: str, note: str, date: str) -> EmailMessage:
    """Escalation email: plain, unmistakable, screenshot attached, leaders CC'd.

    Note the CC header — nothing else in this repo CCs anyone, so this is the one
    bit of new email plumbing. smtplib.send_message picks recipients up from the
    To + Cc headers automatically, so setting Cc here puts them on the envelope."""
    to_addrs = list(config.TO_ADDRS)
    cc_addrs = list(config.CC_ADDRS)
    if not to_addrs:
        raise SaraDownError(
            "No escalation recipients set. Fill config.TO_ADDRS with the Sara+ "
            "support address(es) before a live send.")

    subject = f"{config.SUBJECT} — {date}"   # e.g. "Sara+ Issue — 7/17/2026"
    # The issue text is whatever the reporter typed in Slack (which is where the
    # SPM #, "won't let me select ABP", etc. live). Bare screenshot -> a plain
    # default. Written in Raf's voice since these go out over his usual wording.
    issue = note.strip() or config.DEFAULT_NOTE
    body = (
        "Hey team,\n\n"
        f"{issue}\n\n"
        f"Screenshot attached. Reported by {reporter} at {when} CST — please "
        "take a look and reply-all with status.\n\n"
        "Thanks,\n"
        "Alphalete Marketing"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg.set_content(body)

    subtype = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "png")
    if subtype == "jpg":
        subtype = "jpeg"
    msg.add_attachment(image_bytes, maintype="image", subtype=subtype,
                       filename=filename)
    return msg


def _send(msg: EmailMessage) -> None:
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
            s.login(FROM_ADDR, app_password())
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise SaraDownError(
            "Gmail rejected the login. Check the app password + 2-Step "
            f"Verification for {FROM_ADDR}. ({e})") from e


# ---- the polled processor ---------------------------------------------------
def scan(*, dry_run: bool = True, channel: str | None = None,
         limit: int | None = None) -> list[dict]:
    """Walk recent #sara-down messages; escalate the new, approved ones.
    Returns a list of actions taken/proposed (one dict per screenshot)."""
    channel = channel or config.CHANNEL_ID
    if not channel:
        raise SaraDownError(
            "No channel to watch. Create #sara-down, add the Lucy bot, and set "
            "config.CHANNEL_ID (or pass --channel / SARA_DOWN_CHANNEL_ID).")
    limit = limit or config.SCAN_LIMIT

    cl = _client()
    msgs = cl.conversations_history(channel=channel, limit=limit).get("messages", [])
    state = _load_state()
    actions: list[dict] = []

    # Oldest first, so a burst of outage photos escalates in the order posted.
    for m in sorted(msgs, key=lambda x: x.get("ts", "")):
        if m.get("subtype"):            # joins, edits, etc. — not a real post
            continue
        imgs = _image_files(m)
        if not imgs:
            continue

        ts = m["ts"]
        if state.get(ts, {}).get("sent"):
            continue

        poster = m.get("user", "")
        if config.APPROVED_POSTERS and poster not in config.APPROVED_POSTERS:
            actions.append({"ts": ts, "action": "ignored_unapproved",
                            "poster": poster})
            continue

        reporter = _poster_name(cl, poster)
        when = _fmt_when(ts)
        date = _fmt_date(ts)
        # The Slack caption IS the context for support. Clean up its spelling/
        # grammar before it goes out (falls back to the raw text if the pass fails).
        note = _polish(m.get("text", ""))
        img = imgs[0]                    # first image on the post
        filename = img.get("name") or "sara-plus-issue.png"

        act = {"ts": ts, "action": "escalate", "reporter": reporter,
               "when": when, "to": list(config.TO_ADDRS),
               "cc": list(config.CC_ADDRS), "file": filename}

        image_bytes = _download(img["url_private"])
        msg = build_email(image_bytes, filename, reporter=reporter,
                          when=when, note=note, date=date)

        if dry_run:
            eml = Path(tempfile.gettempdir()) / f"sara_down_{ts.replace('.', '_')}.eml"
            eml.write_bytes(bytes(msg))
            act["dry_run"] = True
            act["eml"] = str(eml)
            actions.append(act)
            continue

        _send(msg)
        # Mark handled BEFORE the (best-effort) Slack ack, so a failed reaction
        # or thread reply can never cause a re-send on the next tick.
        state.setdefault(ts, {})["sent"] = True
        state[ts]["to"] = list(config.TO_ADDRS)
        _save_state(state)
        # Reply IN THE THREAD of the posted screenshot so whoever reported it
        # sees it's been handled — the email is out, no need to do anything else.
        cc_note = (f" (CC: {', '.join(config.CC_ADDRS)})" if config.CC_ADDRS else "")
        try:
            cl.reactions_add(channel=channel, timestamp=ts, name="white_check_mark")
            cl.chat_postMessage(
                channel=channel, thread_ts=ts,
                text=(":white_check_mark: *Done — escalation email sent.*\n"
                      f"Emailed Sara+ support ({', '.join(config.TO_ADDRS)})"
                      f"{cc_note} at {when} CST with your screenshot attached. "
                      "Reply-all on that email to add more detail."))
        except Exception:
            pass
        act["sent"] = True
        actions.append(act)

    return actions


def whois(query: str) -> None:
    """Print the Slack user id for an email/name, to fill APPROVED_POSTERS."""
    from automations.shared import slack_metrics_post as smp
    uid = smp._resolve_user_id(_client(), query)
    print(f"{query}  ->  {uid}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sara+ issue-escalation bot.")
    ap.add_argument("--dry-run", action="store_true",
                    help="build + preview the email(s), send nothing")
    ap.add_argument("--channel", default=None,
                    help="channel id to watch (overrides config / env)")
    ap.add_argument("--limit", type=int, default=None,
                    help="how many recent messages to scan")
    ap.add_argument("--whois", metavar="EMAIL_OR_NAME", default=None,
                    help="print a Slack user id and exit (to fill APPROVED_POSTERS)")
    args = ap.parse_args(argv)

    if args.whois:
        whois(args.whois)
        return 0

    if not acquire_lock():
        print("Another sara_down run is active — skipping this tick.")
        return 0
    try:
        actions = scan(dry_run=args.dry_run, channel=args.channel, limit=args.limit)
    finally:
        release_lock()

    if not actions:
        print("No new Sara+ issue screenshots to escalate.")
        return 0
    for a in actions:
        if a["action"] == "ignored_unapproved":
            print(f"  ignored (not an approved poster): {a['poster']}  ts={a['ts']}")
        elif a.get("dry_run"):
            print(f"  WOULD escalate: {a['reporter']} @ {a['when']} -> "
                  f"To={a['to']} Cc={a['cc']}  [eml: {a['eml']}]")
        else:
            print(f"  ESCALATED: {a['reporter']} @ {a['when']} -> To={a['to']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
