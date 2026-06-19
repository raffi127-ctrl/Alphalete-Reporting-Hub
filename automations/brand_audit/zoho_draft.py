"""Zoho Social draft creator.

Zoho Social has no usable public draft API, so we drive a browser that's
ALREADY logged in — the same warm-session pattern as the ownerville session
holder. The human logs into Zoho ONCE in a dedicated persistent profile (2FA
handled normally); nothing sensitive is stored, the login just persists on
disk. The automation then reuses that profile to create DRAFTS only — it never
auto-publishes.

Two phases:
  --login : open the dedicated profile headful so the human can sign in once.
            Holds the window open until you create a `.stop` file in the
            profile dir (or the timeout elapses), then saves + closes.
  (draft creation is added once the Save-as-Draft composer flow is mapped.)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import _launch_persistent, PROFILE_DIR

# Dedicated, isolated profile — separate from the report profiles and from the
# human's everyday Chrome, so the automation can drive it on a schedule.
ZOHO_PROFILE_DIR = PROFILE_DIR.parent / ".browser_profile_zoho"
ZOHO_SOCIAL_URL = "https://social.zoho.com/"
_STOP_FILE = ZOHO_PROFILE_DIR / ".stop"


def launch_login(max_minutes: int = 30) -> int:
    """Open the dedicated Zoho profile in a visible window for a one-time login.
    Cookies persist to ZOHO_PROFILE_DIR as the human signs in."""
    ZOHO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if _STOP_FILE.exists():
        _STOP_FILE.unlink()

    with sync_playwright() as p:
        ctx = _launch_persistent(p, ZOHO_PROFILE_DIR, headless=False,
                                 label="zoho-login")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(ZOHO_SOCIAL_URL, wait_until="domcontentloaded",
                      timeout=60000)
        except Exception:
            pass
        print(f"Chrome is open. Log into Zoho Social (do your 2FA normally).",
              flush=True)
        print(f"When done, this closes on its own once {_STOP_FILE} appears "
              f"(or after {max_minutes} min).", flush=True)

        waited, deadline = 0, max_minutes * 60
        while waited < deadline and not _STOP_FILE.exists():
            time.sleep(2)
            waited += 2
        ctx.close()
    if _STOP_FILE.exists():
        _STOP_FILE.unlink()
    print("Login window closed — profile saved.", flush=True)
    return 0


# Composer selectors (mapped 2026-06-19 from a logged-in session).
_EDITOR = "#content-editor-newpost-content-editor-div"   # caption (contenteditable)
_MEDIA_BTN = "#zs-newpost-composer-footer-option-media"  # opens the media dialog
# after the media dialog uploads, the "Attach" button inserts it into the post
_IMG_PREVIEW = ("#newpost-imgpreview img, #newpost-imglists img, "
                "[class*=imgpreview] img")               # in-composer thumbnail
_NEW_POST = "text=New Post"
_SAVE_DRAFT = "text=Save Draft"


def _launch_zoho(p, headless: bool):
    """Persistent Zoho context with a LARGE viewport — the media dialog's
    'Attach' button sits bottom-right and is off-screen / unclickable at the
    default window size. System Chrome first, bundled Chromium fallback."""
    base = dict(user_data_dir=str(ZOHO_PROFILE_DIR), headless=headless,
                viewport={"width": 1680, "height": 1000},
                args=["--window-size=1700,1050"])
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **base)
    except Exception:
        return p.chromium.launch_persistent_context(**base)


def create_draft(caption: str, image_path: str | None,
                 company_name: str = "", *, headless: bool = False,
                 timeout: int = 60000) -> dict:
    """Create a DRAFT post (image + caption) in Zoho Social via the warm
    logged-in profile, WITHOUT publishing. Runs headful — headless trips Zoho's
    re-auth wall. Raises if the session has expired (re-run `--login`).

    NOTE: channel selection (and excluding Raf's personal LinkedIn per the hard
    rule) stays with the human at PUBLISH time — a draft does not post anywhere.
    """
    from patchright.sync_api import sync_playwright

    ZOHO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=timeout)
            if "accounts.zoho.com" in pg.url:
                raise RuntimeError(
                    "Zoho session expired — run `zoho_draft.py --login` to "
                    "re-authenticate, then retry.")
            pg.wait_for_timeout(2500)

            pg.locator(_NEW_POST).first.click(timeout=15000)
            pg.wait_for_timeout(3000)

            # caption
            ed = pg.locator(_EDITOR).first
            ed.click()
            try:
                ed.fill(caption)
            except Exception:
                pg.keyboard.type(caption)

            # photo: media button -> file chooser -> gallery -> Attach.
            # (set_input_files on the hidden input uploads to the gallery but
            # never inserts it; you must click Attach.)
            if image_path:
                with pg.expect_file_chooser(timeout=15000) as fc:
                    pg.locator(_MEDIA_BTN).first.click(timeout=10000)
                fc.value.set_files(image_path)
                pg.wait_for_timeout(3000)
                pg.get_by_role("button", name="Attach").first.click(timeout=15000)
                # confirm the thumbnail actually landed in the composer
                pg.wait_for_selector(_IMG_PREVIEW, state="visible", timeout=30000)
                pg.wait_for_timeout(1500)

            # Save Draft — the publishing-options popup overlaps it, so click the
            # visible one with force, then fall back to a direct JS click.
            saved = False
            loc = pg.locator(_SAVE_DRAFT)
            for i in range(loc.count()):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        el.click(timeout=8000, force=True)
                        saved = True
                        break
                except Exception:
                    continue
            if not saved:
                saved = bool(pg.evaluate(
                    "() => { for (const n of document.querySelectorAll('*')) {"
                    " if ((n.innerText||'').trim() === 'Save Draft') { n.click();"
                    " return true; } } return false; }"))
            if not saved:
                raise RuntimeError("could not click Save Draft")
            pg.wait_for_timeout(4000)

            from automations.brand_audit.config import OUTPUT_DIR
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            shot = str(OUTPUT_DIR / "_zoho_draft_result.png")
            try:
                pg.screenshot(path=shot, full_page=False)
            except Exception:
                shot = None
            # success = the composer closed (editor gone). If it's still open,
            # the save was blocked (validation) — report it instead of lying.
            try:
                still_open = pg.locator(_EDITOR).is_visible()
            except Exception:
                still_open = False
            if still_open:
                return {"ok": False, "screenshot": shot,
                        "error": "composer still open after Save Draft — likely "
                                 "a channel validation issue"}
            return {"ok": True, "screenshot": shot}
        finally:
            ctx.close()


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="brand_audit.zoho_draft")
    p.add_argument("--login", action="store_true",
                   help="open the dedicated profile for a one-time Zoho login")
    p.add_argument("--minutes", type=int, default=30,
                   help="how long to hold the login window open")
    args = p.parse_args(argv)
    if args.login:
        return launch_login(args.minutes)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
