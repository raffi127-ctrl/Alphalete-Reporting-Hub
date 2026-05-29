"""Discovery session for ApplicantStream — stealth edition.

Uses your real Chrome (channel="chrome", not bundled Chromium) plus a
persistent profile, driven by patchright (a stealth Playwright fork). This
combination passes the Cloudflare Turnstile check that stops vanilla Playwright.

The persistent profile lives at PROFILE_DIR. After your first manual login,
the session cookie is saved there and subsequent runs skip the login flow
entirely (until the cookie expires).

Run:
    .venv/bin/python -m automations.recruiting_report.discover

Keychain creds (still useful for fetch.py, even if not used here):
    security add-generic-password -a applicantstream -s applicantstream-username -w
    security add-generic-password -a applicantstream -s applicantstream-password -w
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

LOGIN_URL = "https://applicantstream.com/"
SELECTORS_PATH = Path(__file__).resolve().parent / "selectors.json"
PROFILE_DIR = Path.home() / ".config" / "recruiting-report" / "chrome-profile"


def main() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"using persistent Chrome profile at: {PROFILE_DIR}")
    print(f"opening {LOGIN_URL} in your real Chrome…")
    print()
    print("Steps:")
    print("  1. Log in manually (Cloudflare should pass with real Chrome).")
    print("  2. Navigate to the Raf Hidalgo recruiting funnel report.")
    print("  3. When you see the export button, click 'Resume' in the Playwright Inspector.")
    print()

    # patchright is itself a stealth fork — no playwright_stealth wrapper needed.
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            accept_downloads=True,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LOGIN_URL)

        # Open Playwright Inspector. Hit Resume after navigating to the report.
        page.pause()

        snapshot = {
            "current_url": page.url,
            "title": page.title(),
            "buttons_seen": [b.text_content() for b in page.locator("button").all()[:30]],
            "links_seen": [a.text_content() for a in page.locator("a").all()[:30]],
            "inputs_seen": [
                {
                    "name": i.get_attribute("name"),
                    "id": i.get_attribute("id"),
                    "type": i.get_attribute("type"),
                    "placeholder": i.get_attribute("placeholder"),
                }
                for i in page.locator("input").all()[:30]
            ],
        }
        snap_path = SELECTORS_PATH.parent / "discovery-snapshot.json"
        snap_path.write_text(json.dumps(snapshot, indent=2, default=str))
        print(f"\nWrote post-resume snapshot to {snap_path}")

        context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
