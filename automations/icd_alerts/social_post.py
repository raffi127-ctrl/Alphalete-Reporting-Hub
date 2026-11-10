"""Post an approved social photo from THIS office's own Zoho, on this computer.

WHY HERE (Megan 2026-11-08). The ICD makes and pays for their own Zoho
Social account and connects their own pages to it. Their Zoho login lives on
their computer, like their SaraPlus and OwnerVille logins -- so the post has
to go out from here. Lucy 3 does everything else: reads the office's Slack
room, edits the photo, writes the caption, collects the approver's check.
Only an APPROVED post ever reaches this computer.

    Lucy 3 -> relay   "social_post for office X: this photo, this caption"
    here   -> relay   "any jobs for me?"          (office_jobs.py asks)
           <- relay   the job, handed out ONCE
    here   -> relay   "posted" / "signed_out" / "no_channels" / ...
    Lucy 3 <- relay   the answer -> 🚀 in the thread, or a DM to the owner

KINDS (dispatched from office_jobs.work)
  zoho_signin  -- open Zoho in Lucy's window on this screen and wait for the
                  owner to sign in (the install call). Never types a password.
  social_check -- is Zoho still signed in, and which pages are connected?
                  Lucy 3 compares that with what the office set up and DMs
                  the owner when one drops off.
  social_post  -- the approved photo + caption, published now.

A POST IS NEVER SENT TWICE. If Zoho's window can't even open (Lucy's browser
is busy), the job goes back as 'deferred' -- untouched, safe to retry. Once
composing has started, whatever happens is answered as a result: a retry
could put the same photo on their page twice.

DRY (the mode is set on Lucy's side): signs in and reads which pages are
connected, says what it WOULD post, posts nothing.
"""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Dict

from automations.icd_alerts import config as C

# Lucy's own Zoho window on this computer -- separate from the OwnerVille and
# SaraPlus profiles, so a knocks read never collides with a post.
PROFILE = C.APP_DIR / "zoho-profile"

# Zoho channel codes we never post a photo to (personal LinkedIn, YouTube,
# TikTok are dropped by zoho_draft.select_channels already).
_NOT_PAGES = {"linkedinprofile", "youtube", "tiktok"}


def _busy() -> bool:
    """Another Lucy browser already has the Zoho window open."""
    return any((PROFILE / n).exists() for n in ("SingletonLock", "lockfile"))


def signin(payload: Dict, log=print) -> Dict:
    from automations.brand_audit import zoho_draft
    if _busy():
        return {"status": "deferred"}
    minutes = int(payload.get("minutes") or 20)
    log("zoho: opening Zoho for the owner to sign in (%d min)" % minutes)
    r = zoho_draft.wait_for_signin(PROFILE, max_minutes=minutes)
    return {"status": "signed_in" if r["logged_in"] else "timed_out",
            "channels": r["channels"]}


def check(payload: Dict, log=print) -> Dict:
    from automations.brand_audit import zoho_draft
    if _busy():
        return {"status": "deferred"}
    r = zoho_draft.channel_check(PROFILE)
    if not r["logged_in"]:
        return {"status": "signed_out", "channels": []}
    return {"status": "ok", "channels": r["channels"], "names": r.get("names") or {}}


def _unpack_album(data: bytes, folder: Path) -> list:
    """The .zip relay.album_bytes made -> photo paths in posting order."""
    import io
    import zipfile
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(z.namelist()):
            base = Path(name).name                      # never write outside folder
            if not base.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            p = folder / base
            p.write_bytes(z.read(name))
            out.append(str(p))
    return out


def post(payload: Dict, live: bool, log=print) -> Dict:
    from automations.brand_audit import zoho_draft
    caption = str(payload.get("caption") or "").strip()
    raw = payload.get("photo_b64") or ""
    if not caption or not raw:
        return {"status": "error", "error": "job had no caption or no photo"}
    if _busy():
        return {"status": "deferred"}
    if not live:
        r = zoho_draft.channel_check(PROFILE)
        if not r["logged_in"]:
            return {"status": "signed_out", "channels": []}
        want = set(payload.get("pages") or ())
        pages = [c for c in r["channels"] if c not in _NOT_PAGES
                 and (not want or zoho_draft.page_of(c) in want)]
        return {"status": "dry_run" if pages else "no_channels",
                "channels": r["channels"], "would_post_to": pages}
    video = payload.get("media") == "video"          # the weekly reel
    album = payload.get("media") == "album"          # several photos, one post
    with tempfile.TemporaryDirectory(prefix="lucy-social-") as tmp:
        if album:
            photo = _unpack_album(base64.b64decode(raw), Path(tmp))
            if not photo:
                return {"status": "error", "error": "album job had no photos in it"}
        else:
            photo = Path(tmp) / ("post.mp4" if video else "post.jpg")
            photo.write_bytes(base64.b64decode(raw))
        # From here on a retry could double-post: every outcome is a RESULT.
        try:
            keep = tuple(payload.get("pages") or ()) or None
            res = zoho_draft.post_now(caption, photo if album else str(photo), "",
                                      media_type="video" if video else "photo",
                                      profile_dir=PROFILE, keep=keep)
        except RuntimeError as e:
            if "session expired" in str(e).lower():
                return {"status": "signed_out", "channels": []}
            return {"status": "error", "error": str(e)[:200]}
    if not res.get("ok"):
        return {"status": "error", "error": res.get("error") or "Zoho didn't confirm",
                "channels": res.get("channels") or []}
    pages = [c for c in (res.get("channels") or []) if c not in _NOT_PAGES]
    if not pages:
        return {"status": "no_channels", "channels": res.get("channels") or []}
    log("zoho: posted to %s" % ", ".join(pages))
    return {"status": "posted", "channels": pages}
