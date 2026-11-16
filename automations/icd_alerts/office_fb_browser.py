"""Answer a Facebook review the way a person does, from this office's computer.

WHY THIS EXISTS (Megan 2026-11-16: "we need it to automatically happen as
that's going to be a ton of accounts to go in and respond to"). Facebook's API
lets a Page comment on a review written by another Page, and REFUSES one
written by a person ("Permissions error") -- 24 of Alphalete's 26 reviews.
The same comment typed on facebook.com as the Page goes through (Megan checked
Wanda Moore Price's review by hand 11/16). So when the API says no, this
computer opens the review in a browser signed in as someone who manages the
Page, comments AS THE PAGE, and checks the comment is there.

  fb_signin -- PERSON: a window opens, the owner signs in to Facebook once.
               The sign-in stays in this computer's own browser folder.
  browser_reply(story, text, page_name) -- called by office_facebook.reply_job
               only after the API refused. Hidden: on a Mac a real window kept
               out of sight (quiet_window.Guard), elsewhere headless.

NEVER GETS AROUND A CHECK. A Facebook security check / "confirm it's you" page
stops the reply at once and answers "checkpoint"; Lucy 3 holds every reply for
that office and DMs the owner. Lucy 3 also sends at most one reply at a time,
spaced out (eco_fb.OUTBOX_GAP_MIN), so nothing here bursts.
"""
from __future__ import annotations

import platform
import time
from typing import Dict

from automations.icd_alerts import config as C

PROFILE = C.APP_DIR / "facebook-browser"
SIGNIN_MAX_MINUTES = 14
FB = "https://www.facebook.com"

_CHECK_WORDS = ("checkpoint", "confirm it's you", "confirm its you", "security check",
                "suspicious activity", "we suspended", "temporarily blocked",
                "you're temporarily", "your account has been locked")


def _busy() -> bool:
    return any((PROFILE / n).exists() for n in ("SingletonLock", "lockfile"))


def signed_in_here() -> bool:
    """A sign-in was saved on this computer (cookies folder exists)."""
    return (PROFILE / "Default").is_dir()


def _launch(p, *, visible: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = ["--disable-sync", "--window-size=1280,900"]
    quiet = not visible and platform.system() == "Darwin"
    if quiet:
        from automations.icd_alerts import quiet_window as QW
        args += QW.FLAGS
    base = dict(user_data_dir=str(PROFILE), headless=not visible and not quiet, args=args,
                no_viewport=False)
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **base), quiet
    except Exception:  # noqa: BLE001 -- no Google Chrome installed: patchright's own
        return p.chromium.launch_persistent_context(**base), quiet


def _logged_in(ctx) -> bool:
    try:
        return any(c.get("name") == "c_user" for c in ctx.cookies(FB))
    except Exception:  # noqa: BLE001
        return False


def _checkpoint(pg) -> bool:
    try:
        if "checkpoint" in (pg.url or "").lower():
            return True
        body = (pg.inner_text("body", timeout=4000) or "").lower()[:6000]
    except Exception:  # noqa: BLE001
        return False
    return any(w in body for w in _CHECK_WORDS)


# ---- sign-in (a person is at the screen) -------------------------------------------
def signin_job(payload: Dict, log=print) -> Dict:
    if _busy():
        return {"status": "busy", "error": "Lucy's Facebook window is already open"}
    minutes = int(payload.get("minutes") or SIGNIN_MAX_MINUTES)
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx, _ = _launch(p, visible=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(FB + "/login", wait_until="domcontentloaded", timeout=60000)
            end = time.time() + minutes * 60
            while time.time() < end:
                if _logged_in(ctx) and "checkpoint" not in (pg.url or ""):
                    time.sleep(3)                     # let Facebook finish saving
                    return {"status": "signed_in"}
                time.sleep(2)
            return {"status": "timed_out", "error": "nobody signed in within %d min" % minutes}
        finally:
            ctx.close()


# ---- one reply, hidden --------------------------------------------------------------
def _comment_box(pg, page_name: str):
    """The comment box, set to post AS THE PAGE. None when it can't be."""
    want = "comment as %s" % page_name.lower()
    boxes = pg.locator('div[contenteditable="true"][role="textbox"]')
    for i in range(min(boxes.count(), 6)):
        b = boxes.nth(i)
        label = ((b.get_attribute("aria-label") or "") + " " + (b.inner_text() or "")).lower()
        if want in label:
            return b
    # Signed in as the person: the little avatar menu beside the box switches who
    # comments. Pick the Page there, then look again.
    # "Switch to a different profile or Page" is the name Facebook gave it on
    # 11/16 (read off Wanda Moore Price's review in Megan's own Chrome).
    for sel in ('[aria-label="Switch to a different profile or Page"]', '[aria-label*="Choose who"]',
                '[aria-label*="Select profile"]', '[aria-label*="Voice selector"]'):
        try:
            btn = pg.locator(sel).first
            if btn.count():
                btn.click(timeout=4000)
                pg.get_by_text(page_name, exact=True).first.click(timeout=6000)
                pg.wait_for_timeout(1500)
                break
        except Exception:  # noqa: BLE001
            continue
    for i in range(min(boxes.count(), 6)):
        b = boxes.nth(i)
        label = ((b.get_attribute("aria-label") or "") + " " + (b.inner_text() or "")).lower()
        if want in label:
            return b
    return None


def _already(pg, page_name: str, text: str) -> bool:
    try:
        body = pg.inner_text("body", timeout=5000)
    except Exception:  # noqa: BLE001
        return False
    return page_name in body and text[:60] in body


def browser_reply(story: str, text: str, page_name: str, log=print, *, practice: bool = False) -> Dict:
    """practice=True stops once the 'Comment as <page>' box is found: nothing typed."""
    if not signed_in_here():
        return {"status": "needs_signin", "story": story,
                "error": "Facebook isn't signed in on this computer yet"}
    if _busy():
        return {"status": "busy", "story": story, "error": "Lucy's Facebook window is open"}
    from patchright.sync_api import sync_playwright
    guard = None
    with sync_playwright() as p:
        ctx, quiet = _launch(p, visible=False)
        try:
            if quiet:
                from automations.icd_alerts import quiet_window as QW
                guard = QW.Guard(PROFILE).start()
            if not _logged_in(ctx):
                return {"status": "needs_signin", "story": story, "error": "Facebook signed out"}
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto("%s/%s" % (FB, story), wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(4000)
            if _checkpoint(pg):
                return {"status": "checkpoint", "story": story,
                        "error": "Facebook is asking for a security check"}
            if "/login" in (pg.url or ""):
                return {"status": "needs_signin", "story": story, "error": "Facebook signed out"}
            if _already(pg, page_name, text):
                return {"status": "replied", "story": story, "via": "browser", "note": "already there"}
            box = _comment_box(pg, page_name)
            if box is None:
                return {"status": "not_page", "story": story,
                        "error": "this Facebook sign-in can't comment as %s" % page_name}
            if practice:
                return {"status": "found_box", "story": story, "via": "browser"}
            box.click(timeout=8000)
            pg.wait_for_timeout(600)
            # Typed like a person, one line at a time (Enter alone would send).
            lines = text.split("\n")
            for n, line in enumerate(lines):
                pg.keyboard.type(line, delay=25)
                if n < len(lines) - 1:
                    pg.keyboard.press("Shift+Enter")
            pg.wait_for_timeout(500)
            pg.keyboard.press("Enter")
            for _ in range(15):
                pg.wait_for_timeout(1000)
                if _checkpoint(pg):
                    return {"status": "checkpoint", "story": story,
                            "error": "Facebook asked for a security check after sending"}
                if _already(pg, page_name, text):
                    return {"status": "replied", "story": story, "via": "browser"}
            return {"status": "error", "story": story,
                    "error": "sent, but the comment didn't show up under the review"}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "story": story, "error": ("%s: %s" % (type(e).__name__, e))[:200]}
        finally:
            if guard:
                guard.stop()
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def main(argv=None) -> int:
    """By hand, for trying it out: sign in, or a practice run on one review.
        python -m automations.icd_alerts.office_fb_browser --signin
        python -m automations.icd_alerts.office_fb_browser --practice STORY "Page Name"
    """
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--signin", action="store_true")
    ap.add_argument("--practice", nargs=2, metavar=("STORY", "PAGE"))
    ap.add_argument("--visible", action="store_true", help="practice in a window you can watch")
    a = ap.parse_args(argv)
    if a.signin:
        print(json.dumps(signin_job({})))
    elif a.practice:
        if a.visible:
            global _launch
            real = _launch
            _launch = lambda p, visible: real(p, visible=True)
        print(json.dumps(browser_reply(a.practice[0], "practice", a.practice[1], practice=True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
