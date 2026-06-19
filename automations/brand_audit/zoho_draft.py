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


def create_draft(caption: str, image_path: str,
                 company_name: str = "") -> dict:
    """Create a DRAFT post (image + caption) in Zoho Social using the warm
    logged-in profile, without publishing. Not yet wired — the Save-as-Draft
    composer flow still needs to be mapped from a logged-in session.

    Raises NotImplementedError until then; callers (social_inbox) catch it and
    leave the submission pending so it drafts automatically once this is built.
    """
    raise NotImplementedError(
        "Zoho Save-as-Draft composer not mapped yet — log in via "
        "`zoho_draft.py --login`, then map New Post -> upload -> caption -> "
        "Save as Draft.")


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
