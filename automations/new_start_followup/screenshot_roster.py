"""Read the week's new-start roster off AISHA'S SCREENSHOT in Slack, not the sheet.

Raf's call (2026-08-03): the live OBCL tab carries people we're NOT moving
forward with (plus duplicate/leftover rows), so the only true reach-out list is
the screenshot Aisha posts each week. This module finds that post in
#rafs-office-recruiting, downloads the roster-table image, and reads the
"2ND Round Interviewer -> new start" rows off it with Claude vision — the same
pattern automations/swag_welcome/extract.py uses for the swag roster.

Anh Đinh etc. come back with real accents; roster._norm folds them for matching.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

import requests

from automations.shared import slack_metrics_post as smp
from automations.brand_audit import credentials

# Moved from #rafs-office-recruiting (C06881A7WLV) on 2026-08-21 — Aisha now
# posts the weekly thread in #11280-alphalete-marketing-inc-rafael-hidalgo.
CHANNEL_ID = os.environ.get("NSF_CHANNEL_ID", "C0AUAS88FGW")
# Aisha's weekly post — matched loosely on wording (she has some variance).
POST_RE = re.compile(r"new\s*starts?.*scheduled.*monday", re.I)
MODEL = "claude-opus-4-8"

_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "interviewer": {
                        "type": "string",
                        "description": "The '2ND Round Interviewer' cell EXACTLY as "
                        "shown (this is the LEADER, e.g. 'Jessie Gomez', 'Anh Đinh', "
                        "'rhea mckee'). Copy accents verbatim.",
                    },
                    "name": {"type": "string", "description": "the new-start first name"},
                    "last_name": {"type": "string", "description": "the new-start last name"},
                    "confirmation": {
                        "type": "string",
                        "description": "the LAST status column ('Friday "
                        "Confirmation'), copied EXACTLY, e.g. 'Confirmed: OTP', "
                        "'BOB Friday', 'NA: Sent Text', 'Declined', 'Failed "
                        "Background'. Empty string if the cell is blank.",
                    },
                    "bg_status": {
                        "type": "string",
                        "description": "the 'BG Status : Last Checked' cell, "
                        "copied EXACTLY, e.g. 'Passed', 'Taken - Pending', "
                        "'Review', 'Sent'. Empty string if blank.",
                    },
                },
                "required": ["interviewer", "name", "last_name", "confirmation",
                             "bg_status"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rows"],
    "additionalProperties": False,
}

_PROMPT = (
    "This is a screenshot of a new-start roster table. Each row is one new "
    "start. Columns include a '#', '2ND Round Interviewer', maybe a Trainer/time, "
    "'Name' (first), 'Last Name', and status columns. Read EVERY visible data row "
    "top to bottom and return them in order.\n\n"
    "Rules:\n"
    "- interviewer = the '2ND Round Interviewer' cell, copied EXACTLY including "
    "accents and casing (e.g. 'Anh Đinh', 'rhea mckee', 'De'Avion Allen').\n"
    "- name / last_name = the new start's first and last name cells, exactly.\n"
    "- Only rows that are actually visible in the image — do NOT invent rows and "
    "do NOT skip any visible row. Ignore the header row and any filter icons.\n"
    "- If an interviewer cell is blank because it's a continuation of the row "
    "above, repeat that same interviewer.\n"
    "- confirmation = the LAST status column, headed 'Friday Confirmation'. "
    "Copy the cell text EXACTLY. Some are colour-filled (red for 'Declined' "
    "and 'Failed Background'); read the TEXT, not the colour, and use an empty "
    "string when the cell has none.\n"
    "- bg_status = the 'BG Status : Last Checked' cell, exactly."
)


# A new start who declined, or whose background check failed, is not starting —
# so their interviewer owes them nothing and must not be tagged about them.
# Raf, 2026-08-30: "Lucy is tagging people where the new start has either
# declined the position or failed the BGC, can we make it where it doesn't tag
# those folks please."
#
# Substring matching, not an exact set: the sheet's wording drifts ("Declined",
# "Declined ", "Failed Background", "Failed BGC"), and a status we fail to
# recognise means tagging somebody about a person who isn't coming — the exact
# complaint. The inverse risk (dropping a real new start) is bounded because
# these two phrases don't appear in any live status: the others are Confirmed:
# OTP / Confirmed: Via Sms / BOB Friday / NA: Sent Text / Sent / Passed /
# Taken - Pending / Review.
DROPPED_MARKERS = ("declin", "failed background", "failed bgc", "failed bg check")


def is_dropped(row: dict) -> bool:
    for field in ("confirmation", "bg_status"):
        value = " ".join((row.get(field) or "").lower().split())
        if any(marker in value for marker in DROPPED_MARKERS):
            return True
    return False


def owed_counts(rows):
    """-> (interviewer -> count, [dropped row description, ...]).

    The ONE place screenshot rows become owed counts, so the roll call, the
    snapshot and the checklist can't drift on who counts (they each had their
    own copy of this loop before 2026-08-30).
    """
    owed, dropped = {}, []
    for r in rows:
        intv = (r.get("interviewer") or "").strip()
        if not intv:
            continue
        if is_dropped(r):
            dropped.append("{} — {} {} ({})".format(
                intv, r.get("name", ""), r.get("last_name", ""),
                (r.get("confirmation") or r.get("bg_status") or "?").strip()))
            continue
        owed[intv] = owed.get(intv, 0) + 1
    return owed, dropped


def _image_block(image_path) -> dict:
    path = Path(image_path)
    data = path.read_bytes()
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.standard_b64encode(data).decode()}}


def extract_rows(image_path) -> List[dict]:
    """[{'interviewer','name','last_name'}, ...] read off the screenshot via Claude."""
    import anthropic
    content = [_image_block(image_path), {"type": "text", "text": _PROMPT}]
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    resp = client.messages.create(
        model=MODEL, max_tokens=8000,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": content}])
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text).get("rows", [])


def _find_roster_image(client, monday_iso: Optional[str] = None,
                       poster: Optional[str] = None) -> Optional[dict]:
    """The 'New Starts Scheduled for Monday' post's roster image.
    Returns the Slack file dict (with url_private_download) for the LARGEST image
    in that post's thread (the roster table, not the small funnel-count image).
    With `poster` given, only that author's post counts (one post per funnel
    since the week of 8/24 — see thread.FUNNELS)."""
    hist = client.conversations_history(channel=CHANNEL_ID, limit=200)
    matches = [m for m in hist.get("messages", [])
               if POST_RE.search(m.get("text", "") or "")
               and (not poster or m.get("user") == poster)]
    if not matches:
        return None
    if monday_iso:
        # Two guards, both learned the week of 8/24:
        #  - A week where the roster hasn't been posted yet would otherwise
        #    find LAST week's — which reads fine and stamps itself as this week
        #    (that almost shipped a wrong-week snapshot on 2026-08-22). The
        #    post lands the Friday before, so only this week's window counts.
        #  - There are TWO same-titled Friday posts now (one per funnel), so
        #    without a poster filter take the EARLIEST in-window match (the
        #    main funnel posts first), never the newest.
        import datetime as dt
        monday = dt.date.fromisoformat(monday_iso)

        def _posted(m):
            return dt.datetime.fromtimestamp(float(m["ts"])).date()

        in_week = [m for m in matches
                   if monday - dt.timedelta(days=6) <= _posted(m) <= monday]
        if not in_week:
            raise RuntimeError(
                "Newest roster post in {}{} is from {} — the week of a "
                "different Monday, not {}. This week's roster isn't up yet; "
                "refusing to read last week's screenshot.".format(
                    CHANNEL_ID,
                    " by <@{}>".format(poster) if poster else "",
                    _posted(matches[0]).isoformat(), monday_iso))
        parent = min(in_week, key=lambda m: float(m["ts"]))
    else:
        parent = matches[0]  # history is newest-first
    ts = parent["ts"]
    files = list(parent.get("files", []) or [])
    replies = client.conversations_replies(channel=CHANNEL_ID, ts=ts, limit=100)
    for m in replies.get("messages", []):
        files.extend(m.get("files", []) or [])
    images = [f for f in files if (f.get("mimetype") or "").startswith("image/")]
    if not images:
        return None
    # the roster table is the biggest image; the funnel-count one is tiny (~35 KB)
    images.sort(key=lambda f: f.get("size", 0), reverse=True)
    return images[0]


# PNG / JPEG / GIF / WEBP(RIFF) magic bytes. Slack answers an un-authorised
# url_private with 200 + an HTML sign-in page, which raise_for_status() waves
# through -- the bad bytes then surface much later as an opaque API
# "400 Could not process image" (what broke the 2026-08-08 8am roll call and got
# Bill Hirwa mis-tagged off the sheet fallback). Fail here, where the cause is
# still legible.
_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")


def _download(file_obj: dict, token: str) -> Path:
    url = file_obj.get("url_private_download") or file_obj["url_private"]
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    body = r.content
    if not body.startswith(_IMAGE_MAGIC):
        ctype = r.headers.get("Content-Type", "?")
        raise RuntimeError(
            "Slack returned {} bytes of {!r} instead of the roster image for "
            "{!r}. Usually the token can't read files in that channel "
            "(needs files:read) -- check ~/.config/recruiting-report/"
            "slack-user-token on this machine.".format(
                len(body), ctype, file_obj.get("name", "?")))
    suffix = mimetypes.guess_extension(file_obj.get("mimetype", "image/png")) or ".png"
    fd, path = tempfile.mkstemp(prefix="nsf_roster_", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(body)
    return Path(path)


def fetch_roster_rows(monday_iso: Optional[str] = None,
                      poster: Optional[str] = None) -> List[dict]:
    """End-to-end: find the weekly screenshot, download it, OCR it.
    Returns [{'interviewer','name','last_name'}]. Raises if no post/image found."""
    client = smp._client()
    img = _find_roster_image(client, monday_iso, poster=poster)
    if not img:
        raise RuntimeError(
            "No 'New Starts Scheduled for Monday' roster image found in "
            "{}{}. Has it been posted yet?".format(
                CHANNEL_ID, " by <@{}>".format(poster) if poster else ""))
    path = _download(img, smp._load_token())
    try:
        rows = extract_rows(path)
    finally:
        try:
            path.unlink()
        except Exception:
            pass
    return rows


def diagnose() -> int:
    """Why can't THIS machine read the roster screenshot? Prints identity,
    scopes, and the raw download result. Never calls the vision API, never
    prints the token.

    Exists because the failure is machine-specific and silent: the same file
    reads fine from the laptop and 400'd on the mini (2026-08-08), which is what
    sent the roll call down the sheet fallback and mis-tagged Bill Hirwa.
    """
    print("channel: {}".format(CHANNEL_ID))
    try:
        client = smp._client()
    except Exception as exc:  # noqa: BLE001
        print("FAIL: no usable Slack token on this machine -> {}".format(exc))
        return 1

    try:
        who = client.auth_test()
        print("identity: user={} id={} team={}".format(
            who.get("user"), who.get("user_id"), who.get("team")))
        scopes = (who.headers or {}).get("x-oauth-scopes") or ""
        print("scopes  : {}".format(scopes or "(not reported)"))
        for need in ("files:read", "channels:history", "groups:history"):
            if scopes:
                print("   {} {}".format("OK  " if need in scopes else "MISSING", need))
    except Exception as exc:  # noqa: BLE001
        print("FAIL: auth.test -> {}".format(exc))
        return 1

    try:
        img = _find_roster_image(client)
    except Exception as exc:  # noqa: BLE001
        print("FAIL: couldn't read channel history -> {}".format(exc))
        return 1
    if not img:
        print("FAIL: no roster image found in the newest 'New Starts Scheduled "
              "for Monday' post. Has Aisha posted it?")
        return 1
    print("image   : name={!r} size={} mimetype={} id={}".format(
        img.get("name"), img.get("size"), img.get("mimetype"), img.get("id")))

    url = img.get("url_private_download") or img["url_private"]
    try:
        r = requests.get(url, headers={"Authorization": "Bearer {}".format(
            smp._load_token())}, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print("FAIL: download raised -> {}".format(exc))
        return 1
    body = r.content
    print("download: http={} content-type={} bytes={}".format(
        r.status_code, r.headers.get("Content-Type", "?"), len(body)))
    print("first16 : {!r}".format(body[:16]))
    if body.startswith(_IMAGE_MAGIC):
        print("RESULT  : OK — real image bytes. The vision call should work here.")
        return 0
    print("RESULT  : BAD — this is NOT an image. Slack served a sign-in/error "
          "page, which is what reaches the API as '400 Could not process "
          "image'. This machine's token can't read files in this channel: "
          "it needs files:read AND the token's user must be a member. "
          "Fix: `lucy set_slack_token <xoxp-...>` with the same token the "
          "laptop uses.")
    return 1


if __name__ == "__main__":
    import sys
    if "--diag" in sys.argv:
        raise SystemExit(diagnose())
    rows = fetch_roster_rows()
    by = {}
    for r in rows:
        by.setdefault(r["interviewer"].strip(), []).append(
            f"{r['name']} {r['last_name']}".strip())
    print(f"{len(rows)} new starts across {len(by)} interviewers:\n")
    for intv in sorted(by):
        print(f"  {intv} ({len(by[intv])}): {', '.join(by[intv])}")
    sys.exit(0)
