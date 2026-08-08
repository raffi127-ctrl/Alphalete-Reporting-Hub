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

CHANNEL_ID = os.environ.get("NSF_CHANNEL_ID", "C06881A7WLV")  # #rafs-office-recruiting
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
                },
                "required": ["interviewer", "name", "last_name"],
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
    "above, repeat that same interviewer."
)


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


def _find_roster_image(client, monday_iso: Optional[str] = None) -> Optional[dict]:
    """Newest 'New Starts Scheduled for Monday' post's roster image.
    Returns the Slack file dict (with url_private_download) for the LARGEST image
    in that post's thread (the roster table, not the small funnel-count image)."""
    hist = client.conversations_history(channel=CHANNEL_ID, limit=200)
    parent = None
    for m in hist.get("messages", []):
        if POST_RE.search(m.get("text", "") or ""):
            parent = m
            break  # history is newest-first
    if not parent:
        return None
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


def fetch_roster_rows(monday_iso: Optional[str] = None) -> List[dict]:
    """End-to-end: find Aisha's weekly screenshot, download it, OCR it.
    Returns [{'interviewer','name','last_name'}]. Raises if no post/image found."""
    client = smp._client()
    img = _find_roster_image(client, monday_iso)
    if not img:
        raise RuntimeError("No 'New Starts Scheduled for Monday' roster image found "
                           f"in {CHANNEL_ID}. Did Aisha post it yet?")
    path = _download(img, smp._load_token())
    try:
        rows = extract_rows(path)
    finally:
        try:
            path.unlink()
        except Exception:
            pass
    return rows


if __name__ == "__main__":
    import sys
    rows = fetch_roster_rows()
    by = {}
    for r in rows:
        by.setdefault(r["interviewer"].strip(), []).append(
            f"{r['name']} {r['last_name']}".strip())
    print(f"{len(rows)} new starts across {len(by)} interviewers:\n")
    for intv in sorted(by):
        print(f"  {intv} ({len(by[intv])}): {', '.join(by[intv])}")
    sys.exit(0)
