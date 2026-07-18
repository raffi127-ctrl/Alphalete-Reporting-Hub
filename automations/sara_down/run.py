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
def build_email(images: list[tuple[str, bytes]], *, note: str, date: str,
                to_addrs: list[str] | None = None,
                cc_addrs: list[str] | None = None) -> EmailMessage:
    """Escalation email: plain, unmistakable, screenshot(s) attached, leaders CC'd.

    images: list of (filename, bytes) — EVERY image is attached, so a post with
    several photos comes through as one email with all of them.
    to_addrs/cc_addrs default to config; pass explicit lists to override (the
    --test-to path sends to one address with no CC).

    Note the CC header — nothing else in this repo CCs anyone, so this is the one
    bit of new email plumbing. smtplib.send_message picks recipients up from the
    To + Cc headers automatically, so setting Cc here puts them on the envelope."""
    to_addrs = list(to_addrs if to_addrs is not None else config.TO_ADDRS)
    cc_addrs = list(cc_addrs if cc_addrs is not None else config.CC_ADDRS)
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

    for filename, data in images:
        subtype = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "png")
        if subtype == "jpg":
            subtype = "jpeg"
        msg.add_attachment(data, maintype="image", subtype=subtype,
                           filename=filename)
    return msg


def _send(msg: EmailMessage) -> None:
    # Use the certifi CA bundle (the stock context can't find a local issuer on
    # the mini / python.org builds — same fix as shared/hub_notify_email.py).
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
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
         limit: int | None = None, test_to: str | None = None) -> list[dict]:
    """Walk recent #saraplus-issues messages; escalate the new ones.
    Returns a list of actions taken/proposed (one dict per screenshot).

    test_to: send the email to THIS address only (no CC, never support@saraplus),
    and post a clearly-labelled TEST reply in the thread — the safe live dry-run
    before pointing it at Sara+ support."""
    channel = channel or config.CHANNEL_ID
    if not channel:
        raise SaraDownError(
            "No channel to watch. Set config.CHANNEL_ID to #saraplus-issues "
            "(or pass --channel / SARA_DOWN_CHANNEL_ID).")
    limit = limit or config.SCAN_LIMIT

    # First real run on a fresh machine (no state file yet): BASELINE instead of
    # sending. We mark every screenshot already in the channel as handled and
    # email nothing — otherwise installing on the mini would blast Sara+ support
    # for every pre-existing post (test posts included). Only posts made AFTER
    # this baseline escalate. (dry-run / --test-to never baseline.)
    baseline = (not _STATE.exists()) and (not dry_run) and (not test_to)

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

        if baseline:
            st = state.setdefault(ts, {})
            st["sent"] = True
            st["baselined"] = True     # pre-existing at go-live; not a real send
            actions.append({"ts": ts, "action": "baselined"})
            continue

        when = _fmt_when(ts)
        date = _fmt_date(ts)
        # The Slack caption IS the context for support. Clean up its spelling/
        # grammar before it goes out (falls back to the raw text if the pass fails).
        note = _polish(m.get("text", ""))
        # Download EVERY image on the post so a multi-photo upload comes through
        # as one email with all of them attached.
        images: list[tuple[str, bytes]] = []
        for i, f in enumerate(imgs):
            fn = f.get("name") or (
                f"sara-plus-issue-{i + 1}.png" if len(imgs) > 1
                else "sara-plus-issue.png")
            images.append((fn, _download(f["url_private"])))

        # Effective recipients: a test run emails only test_to (no CC, never the
        # vendor); a real run uses the configured To + CC.
        if test_to:
            eff_to, eff_cc = [test_to], []
        else:
            eff_to, eff_cc = list(config.TO_ADDRS), list(config.CC_ADDRS)

        act = {"ts": ts, "action": "escalate", "when": when,
               "to": eff_to, "cc": eff_cc, "test": bool(test_to),
               "files": [fn for fn, _ in images]}

        msg = build_email(images, note=note, date=date,
                          to_addrs=eff_to, cc_addrs=eff_cc)

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
        state[ts]["to"] = eff_to
        if test_to:
            state[ts]["test"] = True
        _save_state(state)
        # Reply IN THE THREAD of the posted screenshot so whoever reported it
        # sees it's been handled — the email is out, no need to do anything else.
        if test_to:
            react, reply = "test_tube", (
                ":test_tube: *TEST — Sara+ escalation bot dry run.*\n"
                f"A test email was sent to {test_to} only (NOT Sara+ support, no "
                "CC). Verifying the flow works; nothing went to the vendor.")
        else:
            cc_note = (f" (CC: {', '.join(eff_cc)})" if eff_cc else "")
            react, reply = "white_check_mark", (
                ":white_check_mark: *Done — escalation email sent.*\n"
                f"Emailed Sara+ support ({', '.join(eff_to)}){cc_note} at {when} "
                "CST with your screenshot attached. Reply-all on that email to "
                "add more detail.")
        try:
            cl.reactions_add(channel=channel, timestamp=ts, name=react)
            cl.chat_postMessage(channel=channel, thread_ts=ts, text=reply)
        except Exception:
            pass
        act["sent"] = True
        actions.append(act)

    # Persist the baseline even if the channel had zero screenshots, so this
    # machine's NEXT run isn't treated as a first run (and start escalating).
    if baseline:
        state["_baselined"] = True
        _save_state(state)

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
    ap.add_argument("--test-to", metavar="EMAIL", default=None,
                    help="LIVE test: email only this address (no CC, not the "
                         "vendor) and post a TEST reply in the thread")
    args = ap.parse_args(argv)

    if args.whois:
        whois(args.whois)
        return 0

    if not acquire_lock():
        print("Another sara_down run is active — skipping this tick.")
        return 0
    try:
        actions = scan(dry_run=args.dry_run, channel=args.channel,
                       limit=args.limit, test_to=args.test_to)
    finally:
        release_lock()

    if not actions:
        print("No new Sara+ issue screenshots to escalate.")
        return 0
    baselined = [a for a in actions if a["action"] == "baselined"]
    if baselined:
        print(f"BASELINE (first run on this machine): marked {len(baselined)} "
              "existing screenshot(s) as seen — sent nothing. New posts from here "
              "on will escalate.")
    for a in actions:
        if a["action"] in ("ignored_unapproved", "baselined"):
            if a["action"] == "ignored_unapproved":
                print(f"  ignored (not an approved poster): {a['poster']}  ts={a['ts']}")
        elif a.get("dry_run"):
            print(f"  WOULD escalate: @ {a['when']} -> "
                  f"To={a['to']} Cc={a['cc']}  [eml: {a['eml']}]")
        elif a.get("test"):
            print(f"  TEST SENT: @ {a['when']} -> To={a['to']} "
                  "(test only, no CC, not the vendor)")
        else:
            print(f"  ESCALATED: @ {a['when']} -> To={a['to']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
