"""Apex (apex.herbjoyent.com) weekly payroll ENTRY — Lucy 2, real Chrome/CDP.

Carlos's post-payroll chore (2026-07-23 spec): once the Commission sheet is
final, each rep's payout gets typed into Apex under Payroll → Payroll Entry.
This module automates it under hard guardrails:

  * NO credential handling, ever. The run rides the logged-in session in the
    copied everyday-Chrome profile (same technique as vantura_churn's Tableau
    pull). If Apex shows a login page, the run STOPS and reports — Carlos
    logs in himself once on Lucy 2's Chrome and the next run carries on.
  * --probe    : open Apex, report login state + page structure, screenshot
                 to the 'Apex Shot' tab. Read-only, always safe.
  * --preview  : also read the Payroll Entry roster + week ending, match
                 names against the Commission sheet (Name Aliases honoured)
                 and print the full name→amount plan + SKIPPED list.
                 Writes nothing.
  * --live     : enter amounts, but ONLY for exact/alias-verified matches.
                 Anyone ambiguous or unmatched is SKIPPED and reported for
                 Carlos ("if you're ever unsure, ask me first" — his rule).
                 Wrong week ending on the page = hard abort.

Isolation invariants (do not collide with the other CDP modules):
  * profile dir /tmp/apex_cdp_profile  (vantura: /tmp/vantura_cdp_profile,
    resume_pushing: /tmp/rp_cdp_profile)
  * debug port 9247                    (vantura 9246, resume 9245)
  * pkill filter matches ONLY 'apex_cdp_profile'
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

APEX_URL = "https://apex.herbjoyent.com/"
CDP_PROFILE = "/tmp/apex_cdp_profile"
CDP_PORT = "9247"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
SHOT_TAB = "Apex Shot"
QUEUE_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _nrm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _kill_ours() -> None:
    subprocess.run(["pkill", "-f", "apex_cdp_profile"], capture_output=True)
    time.sleep(2)


def _copy_default_profile() -> str:
    """Copy Carlos's everyday Chrome data (read-only on the source) into our
    dedicated dir so the debug port works and his Apex session rides along.
    2026-07-23: copies ALL profiles (Default + 'Profile N') — the login may
    live in a named profile, not Default. Returns the profile-directory name
    Chrome last used, so _launch can select it."""
    import json
    import os
    home = os.path.expanduser("~")
    src = f"{home}/Library/Application Support/Google/Chrome"
    _kill_ours()
    subprocess.run(["rm", "-rf", CDP_PROFILE], capture_output=True)
    os.makedirs(CDP_PROFILE, exist_ok=True)
    subprocess.run(["rsync", "-a", f"{src}/Local State",
                    f"{CDP_PROFILE}/Local State"], capture_output=True)
    excludes = []
    for pat in ("Cache", "Code Cache", "GPUCache", "DawnCache",
                "GraphiteDawnCache", "Application Cache",
                "Service Worker/CacheStorage"):
        excludes += ["--exclude", pat]
    profiles = [d for d in os.listdir(src)
                if d == "Default" or d.startswith("Profile ")]
    for prof in profiles:
        subprocess.run(["rsync", "-a", *excludes,
                        f"{src}/{prof}/", f"{CDP_PROFILE}/{prof}/"],
                       capture_output=True)
    last = "Default"
    try:
        st = json.loads(Path(f"{CDP_PROFILE}/Local State").read_text())
        cand = st.get("profile", {}).get("last_used", "Default")
        if cand in profiles:
            last = cand
    except Exception:  # noqa: BLE001
        pass
    print(f"[profiles] copied {profiles}; launching with {last!r}", flush=True)
    return last


def _launch(url: str, profile_dir: str = "Default"):
    return subprocess.Popen(
        [CHROME, f"--user-data-dir={CDP_PROFILE}",
         f"--profile-directory={profile_dir}",
         f"--remote-debugging-port={CDP_PORT}",
         "--no-first-run", "--no-default-browser-check",
         "--restore-last-session=false", "--disable-session-crashed-bubble",
         "--disable-infobars", "--window-size=1600,1000", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _upload_png(png: bytes, log=_log) -> None:
    import base64
    from automations.recruiting_report import fill as _fill
    b64 = base64.b64encode(png).decode()
    chunks = [b64[i:i + 45000] for i in range(0, len(b64), 45000)]
    sh = _fill._client().open_by_key(QUEUE_SHEET)
    try:
        t = sh.worksheet(SHOT_TAB)
    except Exception:  # noqa: BLE001
        t = sh.add_worksheet(title=SHOT_TAB, rows=100, cols=1)
    t.clear()
    t.update([[c] for c in chunks], "A1")
    log(f"screenshot -> '{SHOT_TAB}' tab ({len(chunks)} chunk(s))")


def _looks_logged_out(page) -> bool:
    url = (page.url or "").lower()
    if "/identity/account/login" in url or "/account/login" in url:
        return True
    try:
        return page.locator('input[type="password"]').count() > 0
    except Exception:  # noqa: BLE001
        return False


def _attach(p):
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return browser, page


def probe(log=_log) -> int:
    """Open Apex in the copied-profile Chrome and report the state. Safe:
    navigates and reads only."""
    from patchright.sync_api import sync_playwright
    prof = _copy_default_profile()
    proc = _launch(APEX_URL, prof)
    time.sleep(8)
    try:
        with sync_playwright() as p:
            _browser, page = _attach(p)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(3)
            log(f"url: {page.url}")
            log(f"title: {page.title()}")
            if _looks_logged_out(page):
                log("STATE: LOGIN PAGE — no Apex session in the Chrome "
                    "profile. Carlos must log in once in Lucy 2's everyday "
                    "Chrome (remember-this-device on the 2FA prompt), then "
                    "re-run the probe. NO credentials are typed by this "
                    "automation, by design.")
            else:
                log("STATE: LOGGED IN — session rode along. Left-nav text "
                    "follows:")
                try:
                    nav = page.locator("nav, .sidebar, [class*=menu]").first
                    log("nav: " + " | ".join(
                        (nav.inner_text(timeout=5000) or "").split("\n"))[:600])
                except Exception as e:  # noqa: BLE001
                    log(f"nav read failed: {type(e).__name__}: {e}")
            _upload_png(page.screenshot(full_page=False), log=log)
            return 0
    finally:
        proc.terminate()
        _kill_ours()


def explore(log=_log) -> int:
    """Session required. Navigate Payroll -> Payroll Entry, then dump the
    page structure (week-ending text, row names, input inventory) + a
    screenshot. Read-only — shapes the preview/live modes."""
    from patchright.sync_api import sync_playwright
    prof = _copy_default_profile()
    proc = _launch(APEX_URL, prof)
    time.sleep(8)
    try:
        with sync_playwright() as p:
            _browser, page = _attach(p)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(3)
            if _looks_logged_out(page):
                log("STOP: login page — session didn't ride along.")
                _upload_png(page.screenshot(full_page=False), log=log)
                return 3
            log(f"logged in at {page.url}")
            # left-nav: Payroll, then Payroll Entry
            for label in ("Payroll", "Payroll Entry"):
                clicked = False
                for sel in (f'a:has-text("{label}")',
                            f'button:has-text("{label}")',
                            f'[role="menuitem"]:has-text("{label}")',
                            f'text="{label}"'):
                    loc = page.locator(sel).first
                    try:
                        if loc.count():
                            loc.click(timeout=8000)
                            page.wait_for_load_state("domcontentloaded",
                                                     timeout=20000)
                            time.sleep(3)
                            clicked = True
                            log(f"clicked {label!r} -> {page.url}")
                            break
                    except Exception:  # noqa: BLE001
                        continue
                if not clicked:
                    log(f"could not click {label!r} — dumping page for "
                        "inspection instead")
                    break
            # structure dump
            try:
                body = page.inner_text("body", timeout=10000) or ""
                log("PAGE TEXT (first 1800 chars):")
                for ln in body[:1800].split("\n"):
                    if ln.strip():
                        log("  | " + ln.strip()[:120])
            except Exception as e:  # noqa: BLE001
                log(f"text dump failed: {e}")
            try:
                inputs = page.locator("input, select, textarea")
                n = min(inputs.count(), 60)
                log(f"INPUT INVENTORY ({inputs.count()} total, first {n}):")
                for i in range(n):
                    el = inputs.nth(i)
                    log("  # " + " ".join(
                        f"{k}={el.get_attribute(k)!r}"
                        for k in ("name", "id", "type", "placeholder",
                                  "aria-label", "value")
                        if el.get_attribute(k)))
            except Exception as e:  # noqa: BLE001
                log(f"input dump failed: {e}")
            _upload_png(page.screenshot(full_page=True), log=log)
            return 0
    finally:
        proc.terminate()
        _kill_ours()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apex payroll entry (Lucy 2).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true",
                      help="read-only: report login state + screenshot")
    mode.add_argument("--explore", action="store_true",
                      help="read-only: open Payroll Entry + dump structure")
    mode.add_argument("--preview", action="store_true",
                      help="read roster + match vs Commission; write nothing")
    mode.add_argument("--live", action="store_true",
                      help="enter matched amounts (unsure = skip + report)")
    args = ap.parse_args(argv)
    if args.probe:
        return probe()
    if args.explore:
        return explore()
    _log("preview/live not built yet — --explore captures the Payroll Entry "
         "DOM that shapes them.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
