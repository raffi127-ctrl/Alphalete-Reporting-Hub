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

Attachments (fixed 2026-08-11, Dylan's "the files are unable to be read"):
EVERY image on a post is downloaded, VERIFIED to be real image bytes by its
magic number, given a unique filename with the correct extension, and attached
with the content-type the bytes actually are. A Slack token missing `files:read`
returns HTTP 200 with an HTML sign-in page, not a 401 — that page used to be
attached as "IMG_5203.jpg" and no recipient could open it. Now a post whose
images won't download is SKIPPED (and alerted) so it retries, rather than
escalating something Sara+ support can't read.

    # preview against a test channel, no email sent:
    python -m automations.sara_down.run --dry-run --channel C0TEST123

    # look up a leader's Slack id (to fill APPROVED_POSTERS):
    python -m automations.sara_down.run --whois dylanjtwaddle@gmail.com

    # READ-ONLY: can this machine actually download the posted screenshots?
    python -m automations.sara_down.run --diag

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


# ---- image bytes: download, VERIFY, normalise --------------------------------
# Magic bytes for every image format Slack hands us. This table is the whole
# point of the 2026-08-11 fix: a Slack token WITHOUT `files:read` doesn't get a
# 401 from files.slack.com — it gets HTTP 200 with a ~61KB HTML sign-in page.
# raise_for_status() is happy, so that page used to sail straight into the email
# as "IMG_5203.jpg" and every recipient saw an attachment their mail client
# couldn't open. Never trust the filename or the Content-Type — sniff the bytes.
def _sniff_image(data: bytes) -> str | None:
    """Return the real image subtype ('png'/'jpeg'/'heic'/…) or None if these
    bytes are not an image at all (an HTML error page, an empty body, …)."""
    if not data or len(data) < 12:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    if data[:2] in (b"II", b"MM") and data[2:4] in (b"*\x00", b"\x00*"):
        return "tiff"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12].lower()
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"hevm",
                     b"hevs", b"mif1", b"msf1"):
            return "heic"
        if brand in (b"avif", b"avis"):
            return "avif"
    return None


def _tokens() -> list[tuple[str, str]]:
    """Every Slack token this machine has, as (label, token), most-likely-first.

    The USER token goes first now (2026-08-11). The old code preferred the BOT
    token on the comment "has it; bot must be in the channel" — but the Lucy app
    was created with chat:write + files:write + im:write and NO `files:read`, so
    on the mini (which has a bot token; Megan's laptop doesn't) every download
    silently returned an HTML page. We still try the bot token as a fallback,
    and we verify the bytes either way, so neither token being wrong can put a
    broken attachment in front of Sara+ support again."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, getter in (("user token", _user_token), ("bot token", _bot_token)):
        try:
            tok = getter()
        except Exception:
            tok = None
        if tok and tok not in seen:
            seen.add(tok)
            out.append((label, tok))
    return out


def _download(url: str, token: str) -> bytes:
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                     timeout=60)
    r.raise_for_status()
    return r.content


def _download_image(f: dict) -> tuple[bytes, str]:
    """Download ONE Slack file and return (real image bytes, subtype).

    Tries every token this machine has and accepts only bytes that actually
    sniff as an image. Raises SaraDownError — naming the exact Slack fix — if
    none of them do, so the caller can skip the post and retry next tick rather
    than emailing the vendor a screenshot they can't open."""
    url = f.get("url_private") or f.get("url_private_download") or ""
    name = f.get("name") or f.get("id") or "image"
    if not url:
        raise SaraDownError(f"Slack gave no url_private for {name!r}.")

    toks = _tokens()
    if not toks:
        raise SaraDownError(
            "No Slack token on this machine — can't download the screenshots.")

    problems: list[str] = []
    for label, tok in toks:
        try:
            data = _download(url, tok)
        except Exception as e:
            problems.append(f"{label}: {type(e).__name__} {str(e)[:80]}")
            continue
        subtype = _sniff_image(data)
        if subtype:
            expected = int(f.get("size") or 0)
            if expected and len(data) != expected:
                print(f"  note: {name} downloaded {len(data)} bytes, Slack said "
                      f"{expected} — attaching what we got")
            return data, subtype
        head = data[:40].decode("utf-8", "replace").strip().replace("\n", " ")
        problems.append(f"{label}: {len(data)} bytes, not an image ({head!r})")

    raise SaraDownError(
        f"Slack returned a sign-in page instead of the image {name!r}.\n"
        f"    tried -> " + "\n    tried -> ".join(problems) + "\n"
        "    FIX: the Slack app whose token this machine uses is missing the "
        "`files:read` scope. api.slack.com/apps -> the Lucy app -> OAuth & "
        "Permissions -> add `files:read` -> Reinstall to Workspace -> push the "
        "new token with  lucy set_slack_user_token <xoxp-…>  (or "
        "set_slack_token for the bot token). The app must also be a member of "
        "the private #saraplus-issues channel.")


# Photos straight off an iPhone are 5-7 MB each; three of them blow past Gmail's
# 25 MB message cap and the whole escalation bounces. Budget on the ENCODED size
# — base64 is 4/3 of the raw bytes, so 20 MB of photos is a 27 MB email — and
# shrink only when we're actually near the cap, so a single screenshot still
# goes out pixel-for-pixel as posted.
_GMAIL_LIMIT = 25 * 1024 * 1024
_MAX_ENCODED_BYTES = 22 * 1024 * 1024    # headroom for the body + MIME overhead
_B64_RATIO = 4 / 3
# Each step is (longest edge, JPEG quality). A Sara+ error dialog is readable
# well below the first step; we stop as soon as the batch fits.
_SHRINK_STEPS = ((2400, 85), (1800, 80), (1280, 75))


def _to_jpeg(data: bytes, *, max_dim: int | None = None,
             quality: int = 85) -> bytes | None:
    """Re-encode to JPEG (optionally downscaled). None if Pillow can't do it."""
    try:
        import io
        from PIL import Image
        try:                              # iPhone .heic needs the plugin
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if max_dim and max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception as e:                # noqa: BLE001 — never block a send
        print(f"  (re-encode skipped: {type(e).__name__}: {str(e)[:80]})")
        return None


def _prepare(images: list[tuple[str, bytes, str]]) -> list[tuple[str, bytes, str]]:
    """Make every image openable by the recipient and the set small enough to send.

    1. HEIC -> JPEG. iPhone .heic attachments are a real dead end in Outlook and
       most webmail, which is the other half of "unable to be read".
    2. If the batch would bust Gmail's cap, downscale the big ones to JPEG.
    3. Unique filenames with the RIGHT extension — two attachments called
       image.png (or a PNG named .jpg) is how clients end up showing one.
    """
    out: list[tuple[str, bytes, str]] = []
    for name, data, subtype in images:
        if subtype in ("heic", "avif"):
            jpg = _to_jpeg(data)
            if jpg:
                print(f"  converted {name} ({subtype}) -> jpeg so it opens "
                      "outside Apple Mail")
                name, data, subtype = name.rsplit(".", 1)[0] + ".jpg", jpg, "jpeg"
        out.append((name, data, subtype))

    def encoded(items) -> float:
        return sum(len(d) for _, d, _ in items) * _B64_RATIO

    if encoded(out) > _MAX_ENCODED_BYTES:
        print(f"  {encoded(out)/1e6:.1f} MB encoded — over Gmail's "
              f"{_GMAIL_LIMIT // (1024 * 1024)} MB cap, downscaling the photos")
        for max_dim, quality in _SHRINK_STEPS:
            shrunk: list[tuple[str, bytes, str]] = []
            for name, data, subtype in out:
                small = _to_jpeg(data, max_dim=max_dim, quality=quality)
                if small and len(small) < len(data):
                    name = name.rsplit(".", 1)[0] + ".jpg"
                    data, subtype = small, "jpeg"
                shrunk.append((name, data, subtype))
            out = shrunk
            print(f"  -> {encoded(out)/1e6:.1f} MB at {max_dim}px/q{quality}")
            if encoded(out) <= _MAX_ENCODED_BYTES:
                break
        else:
            # Still too big after the smallest step — send anyway rather than
            # swallow the escalation, but say so loudly in the log.
            print("  ⚠ still over the cap after downscaling — Gmail may reject "
                  "this one; the post stays unmarked so it retries.")

    final: list[tuple[str, bytes, str]] = []
    used: set[str] = set()
    for i, (name, data, subtype) in enumerate(out):
        ext = "jpg" if subtype == "jpeg" else subtype
        stem = name.rsplit(".", 1)[0] if "." in name else name
        stem = stem.strip() or f"sara-plus-issue-{i + 1}"
        candidate = f"{stem}.{ext}"
        n = 2
        while candidate.lower() in used:
            candidate = f"{stem}-{n}.{ext}"
            n += 1
        used.add(candidate.lower())
        final.append((candidate, data, subtype))
    return final


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
def build_email(images: list[tuple[str, bytes, str]], *, note: str, date: str,
                to_addrs: list[str] | None = None,
                cc_addrs: list[str] | None = None) -> EmailMessage:
    """Escalation email: plain, unmistakable, screenshot(s) attached, leaders CC'd.

    images: list of (filename, bytes, subtype) — EVERY image is attached, so a
    post with several photos comes through as one email with all of them. The
    subtype comes from SNIFFING the bytes (see _download_image), never from the
    filename, and this function refuses to attach anything that isn't an image.
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

    if not images:
        raise SaraDownError("No images to attach — refusing to send an empty "
                            "escalation.")
    for filename, data, subtype in images:
        # Last line of defence: a non-image can never reach the vendor, no
        # matter what changes upstream of here.
        real = _sniff_image(data)
        if not real:
            raise SaraDownError(
                f"{filename} is not image data ({len(data)} bytes) — refusing "
                "to attach it. See _download_image for the files:read fix.")
        msg.add_attachment(data, maintype="image", subtype=real,
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


# ---- loud alert when the screenshots can't be fetched ------------------------
_CORRECTIONS_CHANNEL = "C0BK5PRG259"      # #claudecorrections-and-requests
_ALERT_STAMP = Path.home() / ".config" / "sara-down" / "download_alert.txt"


def _alert_download_failure(detail: str, *, dry_run: bool = False) -> None:
    """Post ONCE a day into #claudecorrections-and-requests when Slack won't hand
    over the screenshots. This is the alarm that was missing: from 7/21 to 8/10
    every escalation went to Sara+ support with an HTML sign-in page renamed
    .jpg, and the only signal was Dylan noticing weeks later.

    Never raises — an alert must not stop the retry. [[project_corrections_slack_channel]]"""
    today = datetime.now().date().isoformat()
    try:
        if _ALERT_STAMP.read_text().strip() == today:
            return
    except Exception:
        pass
    # Parent = the headline only; the raw `detail` (a traceback or a page of
    # renamed HTML) goes in the thread so one alert can't own the channel
    # (Megan 2026-08-13). Chunked, never truncated.
    text = (
        "🚨 *Sara+ issue escalation* couldn't download the screenshots — the "
        "email was NOT sent (it will retry every 5 min).\n"
        "Nothing went to Sara+ support with a broken attachment. "
        "_Detail in the thread ↓_")
    from automations.shared import alert_thread
    replies = alert_thread.chunk(["```", str(detail), "```"])
    if dry_run:
        print("  --- corrections alert (dry-run, not sent) ---")
        print("  [channel post]")
        print("  " + text.replace("\n", "\n  "))
        for i, r in enumerate(replies, 1):
            print(f"  [thread reply {i}/{len(replies)}]")
            print("  " + r.replace("\n", "\n  "))
        return
    try:
        # This outage ran for three weeks in July/August. Once a day for three
        # weeks is 21 near-identical posts, which is what buried the channel —
        # so day 2 onward replies in day 1's thread (Eve 2026-08-14). It closes
        # itself the moment a download works again (_clear_download_alert).
        posted = None
        try:
            from automations.shared import incident_thread as _inc
            posted = _inc.open_or_followup(key="sara-down-download",
                                           title=text, body=[], details=replies,
                                           channel=_CORRECTIONS_CHANNEL)
        except Exception as e:  # noqa: BLE001 — fall back to a plain post
            print(f"  ⚠ incident thread unavailable ({type(e).__name__}: "
                  f"{str(e)[:80]}) — posting standalone")
        if not posted:
            resp = _client().chat_postMessage(channel=_CORRECTIONS_CHANNEL,
                                              text=text)
            for r in replies:
                kw = {"channel": _CORRECTIONS_CHANNEL, "text": r}
                if resp.get("ts"):
                    kw["thread_ts"] = resp.get("ts")
                _client().chat_postMessage(**kw)
        _ALERT_STAMP.parent.mkdir(parents=True, exist_ok=True)
        _ALERT_STAMP.write_text(today)
        print("  🚨 posted a download-failure alert to #claudecorrections-and-requests")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ alert didn't post ({type(e).__name__}: {str(e)[:100]})")


def _clear_download_alert(*, dry_run: bool = False) -> None:
    """Downloads work again — say so in the open alert thread and close it.

    Without this the alarm was write-only: it told the channel the day it broke
    and never said it came back, so the last thing anyone read about Sara+ was
    always bad news (Eve 2026-08-14). Free when nothing is open."""
    try:
        from automations.shared import incident_thread as _inc
        if "sara-down-download" not in _inc.open_keys():
            return
        _inc.resolve(key="sara-down-download",
                     lines=["✅ *Sara+ screenshots download again* — RESOLVED. "
                            "Escalations are going out normally.",
                            "_Closed. A new outage opens a fresh post._"],
                     channel=_CORRECTIONS_CHANNEL, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — never break a working run
        print(f"  ⚠ couldn't close the download alert ({type(e).__name__}: "
              f"{str(e)[:80]})")


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
        # as one email with all of them attached. Each one is verified to be
        # real image bytes; if ANY of them can't be fetched we skip the whole
        # post — no state written, so the next 5-min tick retries it once the
        # token is fixed, instead of burning the one escalation on a broken
        # attachment (2026-08-11).
        images: list[tuple[str, bytes, str]] = []
        try:
            for i, f in enumerate(imgs):
                fn = f.get("name") or f"sara-plus-issue-{i + 1}"
                data, subtype = _download_image(f)
                images.append((fn, data, subtype))
            images = _prepare(images)
        except SaraDownError as e:
            print(f"  ⚠ SKIPPED ts={ts} — {e}")
            _alert_download_failure(str(e), dry_run=dry_run)
            actions.append({"ts": ts, "action": "download_failed",
                            "error": str(e)})
            continue
        # Real image bytes in hand — if an outage was being alerted, it's over.
        _clear_download_alert(dry_run=dry_run)

        # Effective recipients: a test run emails only test_to (no CC, never the
        # vendor); a real run uses the configured To + CC.
        if test_to:
            eff_to, eff_cc = [test_to], []
        else:
            eff_to, eff_cc = list(config.TO_ADDRS), list(config.CC_ADDRS)

        act = {"ts": ts, "action": "escalate", "when": when,
               "to": eff_to, "cc": eff_cc, "test": bool(test_to),
               "files": [fn for fn, _, _ in images]}

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
        # Light up the Hub card — ONLY on a real escalation (never on a test /
        # baseline / quiet tick), so the activity log records issues escalated
        # rather than 288 heartbeats a day. Best-effort; never blocks the send.
        if not test_to:
            try:
                from automations.day_orchestrator.hub_publish import publish_done
                publish_done("sara_down", "Sara+ Issue Escalation", "success")
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


def diag(channel: str | None = None, limit: int | None = None) -> int:
    """READ-ONLY: can THIS machine actually download the posted screenshots?

    Sends nothing, writes nothing, touches no state. For every recent post it
    tries each token and reports whether real image bytes came back — the check
    that would have caught the missing `files:read` scope in July instead of
    three weeks of unreadable attachments. Run it on the mini after any token
    change:  lucy rerun sara_down --diag  (or python -m … --diag)."""
    channel = channel or config.CHANNEL_ID
    toks = _tokens()
    print(f"channel: {channel}")
    print(f"tokens on this machine: {', '.join(l for l, _ in toks) or 'NONE'}")
    for label, tok in toks:
        try:
            import ssl as _ssl

            import certifi
            from slack_sdk import WebClient
            w = WebClient(token=tok,
                          ssl=_ssl.create_default_context(cafile=certifi.where())
                          ).auth_test()
            scopes = [s for s in (w.headers.get("x-oauth-scopes") or ""
                                  ).replace(" ", "").split(",") if s]
            ok = "files:read" in scopes
            print(f"  {label}: {w.get('user') or w.get('bot_id')} — "
                  f"files:read {'YES' if ok else 'MISSING  <-- this is the bug'}")
        except Exception as e:  # noqa: BLE001
            print(f"  {label}: auth.test failed ({type(e).__name__})")

    msgs = _client().conversations_history(
        channel=channel, limit=limit or config.SCAN_LIMIT).get("messages", [])
    bad = 0
    for m in sorted(msgs, key=lambda x: x.get("ts", "")):
        imgs = _image_files(m)
        if not imgs:
            continue
        print(f"\n  post {_fmt_when(m['ts'])}  ({len(imgs)} image"
              f"{'s' if len(imgs) != 1 else ''})")
        for f in imgs:
            try:
                data, subtype = _download_image(f)
                print(f"    ✅ {f.get('name')}  {len(data):,} bytes  ({subtype})")
            except SaraDownError as e:
                bad += 1
                print(f"    ❌ {f.get('name')}  {str(e).splitlines()[0]}")
    print("\n" + ("All screenshots download as real images." if not bad else
                  f"{bad} file(s) UNREADABLE — see the FIX above."))
    return 1 if bad else 0


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
    ap.add_argument("--diag", action="store_true",
                    help="READ-ONLY: check this machine can actually download "
                         "the posted screenshots (sends nothing)")
    ap.add_argument("--test-to", metavar="EMAIL", default=None,
                    help="LIVE test: email only this address (no CC, not the "
                         "vendor) and post a TEST reply in the thread")
    args = ap.parse_args(argv)

    if args.whois:
        whois(args.whois)
        return 0

    if args.diag:
        return diag(channel=args.channel, limit=args.limit)

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
    failed = [a for a in actions if a["action"] == "download_failed"]
    for a in actions:
        if a["action"] in ("ignored_unapproved", "baselined", "download_failed"):
            if a["action"] == "ignored_unapproved":
                print(f"  ignored (not an approved poster): {a['poster']}  ts={a['ts']}")
        elif a.get("dry_run"):
            print(f"  WOULD escalate: @ {a['when']} -> "
                  f"To={a['to']} Cc={a['cc']}  [eml: {a['eml']}]")
        elif a.get("test"):
            print(f"  TEST SENT: @ {a['when']} -> To={a['to']} "
                  "(test only, no CC, not the vendor)")
        else:
            print(f"  ESCALATED: @ {a['when']} -> To={a['to']} "
                  f"({len(a['files'])} image(s): {', '.join(a['files'])})")
    if failed:
        # Non-zero so the Hub / orchestrator sees a real failure — these posts
        # have NOT been escalated and will retry on the next tick.
        print(f"\n{len(failed)} post(s) NOT escalated — the screenshots could "
              "not be downloaded. Run --diag for the exact Slack fix.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
