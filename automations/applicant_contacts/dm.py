"""The Jiraiya branch: a DM with applicant info -> reception's Contacts.

Wired in due_diligence/bot.py's _handler, BEFORE the plain-text DM paths
(knocks, the /dd corrected-name reply), because those drop any message with a
subtype -- and a DM with a screenshot arrives as subtype "file_share".

wants() is deliberately narrow: an allowed user, AND an image or a phone/email
in the text. A DD rep name or "knocks …" has neither, so this never steals a
message meant for another feature.
"""
from __future__ import annotations  # Lucy runs Python 3.9

import json
import threading
import traceback
from pathlib import Path
from typing import List, Tuple

from automations.applicant_contacts import contacts as K
from automations.applicant_contacts import extract as X

# Who Jiraiya adds contacts for. Raf asked; Megan + Eve to test and cover.
ALLOWED_USERS = {
    "U045Z8N0ZQC": "Raf",      # Rafael Hidalgo
    "U04G5HJBGFN": "Megan",    # Megan Hidalgo
    "U088E2KJEV8": "Eve",      # Evelyn Sobrino
}

# What Claude can read. iPhone photos can come in as HEIC -- told, not guessed.
_MEDIA = {"image/png", "image/jpeg", "image/gif", "image/webp"}

# Socket Mode redelivers an event it thinks wasn't acked; never add twice.
_HANDLED = (Path(__file__).resolve().parents[2] / "output"
            / "applicant_contacts" / "handled.json")
_lock = threading.Lock()


def _images(ev: dict) -> List[dict]:
    return [f for f in ev.get("files") or []
            if str(f.get("mimetype", "")).startswith("image/")]


def wants(ev: dict) -> bool:
    if ev.get("type") != "message" or ev.get("channel_type") != "im":
        return False
    if ev.get("bot_id") or ev.get("subtype") not in (None, "", "file_share"):
        return False
    if ev.get("user") not in ALLOWED_USERS:
        return False
    return bool(_images(ev)) or X.looks_like_applicant_text(ev.get("text", ""))


def _claim(ts: str) -> bool:
    """True the first time a message ts is seen (then recorded)."""
    with _lock:
        try:
            seen = json.loads(_HANDLED.read_text(encoding="utf-8"))
        except Exception:
            seen = []
        if ts in seen:
            return False
        seen = (seen + [ts])[-500:]
        _HANDLED.parent.mkdir(parents=True, exist_ok=True)
        _HANDLED.write_text(json.dumps(seen), encoding="utf-8")
        return True


def _download(web, f: dict) -> Tuple[bytes, str]:
    import requests
    url = f.get("url_private_download") or f.get("url_private") or ""
    if not url:
        raise RuntimeError("Slack gave no download link for the picture.")
    r = requests.get(url, headers={"Authorization": "Bearer " + web.token},
                     timeout=60)
    if r.status_code == 403 or "redir=" in r.url:
        # Same missing scope, other shape: Slack bounces to the workspace
        # sign-in page (?redir=...) and that page answers 403.
        raise RuntimeError("Jiraiya can't open pictures yet (Slack app needs "
                           "the files:read permission).")
    r.raise_for_status()
    data = r.content
    if data[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        # Slack hands back its sign-in page (HTTP 200) when the token
        # can't read files -- the Jiraiya app is missing files:read.
        raise RuntimeError("Jiraiya can't open pictures yet (Slack app needs "
                           "the files:read permission).")
    return data, f.get("mimetype", "")


def _react(web, ch: str, ts: str, name: str, add: bool = True) -> None:
    try:
        (web.reactions_add if add else web.reactions_remove)(
            channel=ch, timestamp=ts, name=name)
    except Exception:
        pass


def handle(web, ev: dict) -> None:
    """Read the DM, add the applicant(s), reply in its thread. Never raises:
    an error is told to the sender instead of taking the listener down."""
    ch, ts = ev.get("channel"), ev.get("ts")
    if not ch or not ts or not _claim(ts):
        return
    who = ALLOWED_USERS.get(ev.get("user"), "")
    _react(web, ch, ts, "eyes")
    try:
        imgs, bad = [], []
        for f in _images(ev):
            if f.get("mimetype") not in _MEDIA:
                bad.append(f.get("name") or f.get("mimetype"))
                continue
            imgs.append(_download(web, f))
        if bad and not imgs and not X.looks_like_applicant_text(ev.get("text", "")):
            raise RuntimeError("I can't read %s. Send a screenshot (PNG/JPG) "
                               "instead." % ", ".join(bad))
        applicants = X.extract(ev.get("text", ""), imgs)
        rows = K.add_all(applicants, write=True, added_by=who)
        reply = K.summary(rows, write=True)
        ok = any(r["status"] in ("add", "exists") for r in rows)
        print("[applicant_contacts] %s: %d found, %d added" % (
            ts, len(rows), sum(1 for r in rows if r.get("done"))), flush=True)
    except Exception as e:  # noqa: BLE001 — never crash the listener
        traceback.print_exc()
        reply = ":x: Didn't add anyone: %s" % str(e)[:300]
        ok = False
    try:
        web.chat_postMessage(channel=ch, thread_ts=ts, text=reply)
    except Exception as e:  # noqa: BLE001
        print("[applicant_contacts] reply failed %s: %s" % (type(e).__name__, e),
              flush=True)
    _react(web, ch, ts, "eyes", add=False)
    _react(web, ch, ts, "white_check_mark" if ok else "warning")
