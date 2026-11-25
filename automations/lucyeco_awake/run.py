"""Keep the public LucyEco page awake.

Megan 2026-11-25: lucyeco.streamlit.app/lucyeco was found showing Streamlit's
"This app has gone to sleep due to inactivity" page -- to every ICD who opened
it, and on Lucy 1's screen. Streamlit Community Cloud puts an app to sleep after
a stretch with no visitors, and Lucy 1 keeping a tab open did not count.

Each run opens the page the way a visitor does (hidden browser, nothing on the
screen) and, if it is asleep, presses "Yes, get this app back up!" and waits
until the app is drawn again. The visit itself is the traffic that keeps it up.

    python -m automations.lucyeco_awake.run             # visit; wake it if asleep
    python -m automations.lucyeco_awake.run --dry-run   # only say awake/asleep

Exit 1 only when it is asleep and could not be woken: a page ICDs open that
shows a sleep screen is a failure, not "nothing to do".
"""
import argparse
import re
import sys

URL = "https://lucyeco.streamlit.app/lucyeco"
WAKE = re.compile(r"get this app back up", re.I)
ASLEEP_TEXT = "has gone to sleep"
LOAD_MS = 60_000
WAKE_MS = 240_000  # a cold start can take a few minutes ("Your app is in the oven")


def _asleep(page) -> bool:
    try:
        page.get_by_role("button", name=WAKE).wait_for(timeout=20_000)
        return True
    except Exception:  # noqa: BLE001 — no wake button = it is up (or loading)
        return ASLEEP_TEXT in (page.content() or "")


def _app_up(page) -> bool:
    """Streamlit Cloud draws the app in a frame of its own; up = that frame has
    the app's own content and the sleep page is gone."""
    for frame in page.frames:
        try:
            if frame.locator('[data-testid="stApp"]').count():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def check(wake: bool) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001 — no bundled Chromium on this Lucy
            browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(URL, wait_until="domcontentloaded", timeout=LOAD_MS)
            if not _asleep(page):
                page.wait_for_timeout(5_000)
                return "awake"
            if not wake:
                return "asleep"
            page.get_by_role("button", name=WAKE).click()
            waited = 0
            while waited < WAKE_MS:
                page.wait_for_timeout(5_000)
                waited += 5_000
                if _app_up(page) and ASLEEP_TEXT not in page.content():
                    return "woken"
            return "still asleep"
        finally:
            browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="only report awake/asleep; never press the wake button")
    a = ap.parse_args()
    state = check(wake=not a.dry_run)
    print(f"LucyEco ({URL}): {state}")
    return 1 if state == "still asleep" else 0


if __name__ == "__main__":
    sys.exit(main())
