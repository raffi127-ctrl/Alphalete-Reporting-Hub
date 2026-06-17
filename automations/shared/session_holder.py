"""Continuous session holder — keeps the ownerville + AppStream logins warm so
SCHEDULED, UNATTENDED report runs never hit Cloudflare's 'verify you're human'.

WHY (Megan 2026-06-17): Cloudflare globally tightened — the interactive Turnstile
now appears on a FRESH login even in a normal browser, on every machine. There is
no headless way past a forced interactive challenge, and the vendors won't expose
an API. The only thing that ALWAYS works unattended is to NEVER do a fresh login:
a human clears Cloudflare ONCE in this holder's windows, the holder keeps that
exact browser session alive 24/7 (it never closes, so Cloudflare never
re-challenges it), and every few minutes it EXPORTS the live cookies into the
storage_state files the reports already reuse
(tableau_patchright._reuse_ownerville_storage_state / _reuse_appstream_storage_state).
Scheduled runs load those cookies and skip the login — and the Turnstile —
entirely.

HOW IT DEGRADES: if a session ever does go stale (cf_clearance force-expired,
machine slept), the holder does NOT try to re-login (that would hit the
Turnstile). It keeps its window open and alerts loudly so a human can log back in
RIGHT THERE — same warm browser, no new escalation — and keeps the last good
export until then. It only overwrites a site's storage_state while that site is
confirmed live, so a stale moment never corrupts a good cookie file.

Run it on the always-on machine that runs the schedule (the Mac mini; a laptop
works while it's awake). Seed once, leave it running:

    python -m automations.shared.session_holder
    python -m automations.shared.session_holder --interval 6

Cross-platform (mac + windows). Ctrl-C to stop.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import (
    PROFILE_DIR,
    _launch_persistent,
    _ownerville_session_valid,
    OWNERVILLE_STORAGE_STATE,
    APPSTREAM_STORAGE_STATE,
    OWNERVILLE_V2_URL,
    APPSTREAM_BASE,
)

SEARCHMC = "#searchMC"  # the logged-in AppStream console marker


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _appstream_valid(page) -> bool:
    """True iff AppStream's authenticated console loads (cookies still live)."""
    try:
        page.goto(f"{APPSTREAM_BASE}?p=701", wait_until="domcontentloaded")
        page.wait_for_selector(SEARCHMC, timeout=8_000)
        return True
    except Exception:
        return False


def _export_site(cookies: list, substr: str, path) -> int:
    """Write the cookies for one site (domain contains `substr`) to its
    storage_state file in the Playwright format the reuse consumers read."""
    site = [c for c in cookies if substr in (c.get("domain") or "")]
    path.write_text(json.dumps({"cookies": site, "origins": []}))
    return len(site)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Keep ownerville + AppStream sessions warm for unattended runs.")
    ap.add_argument("--interval", type=float, default=8.0,
                    help="Minutes between keep-alive refreshes + exports (default 8; "
                         "keep it well under Cloudflare's clearance lifetime).")
    ap.add_argument("--seed-timeout", type=float, default=15.0,
                    help="Minutes to wait for the human to log in on first start.")
    args = ap.parse_args()

    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE_DIR, headless=False,
                                 label="session_holder", verbose=False)
        ov_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        as_page = ctx.new_page()

        # --- Seed: open both login pages and wait for the HUMAN to log in. ---
        # The holder never drives the form itself — a pure human login is what
        # keeps Cloudflare quiet.
        for pg, url in ((ov_page, OWNERVILLE_V2_URL), (as_page, APPSTREAM_BASE)):
            try:
                pg.goto(url, wait_until="domcontentloaded")
            except Exception:
                pass
        print(f"[{_stamp()}] SEED: log into BOTH windows (ownerville + AppStream) and "
              f"clear any 'verify you're human' box. Waiting up to "
              f"{args.seed_timeout:g} min…", flush=True)
        waited, deadline = 0, args.seed_timeout * 60
        while waited < deadline:
            if _ownerville_session_valid(ov_page, verbose=False) and _appstream_valid(as_page):
                break
            time.sleep(10)
            waited += 10
        print(f"[{_stamp()}] starting keep-alive every {args.interval:g} min. "
              f"Leave this running. Ctrl-C to stop.", flush=True)

        # --- Continuous keep-alive + per-site export loop. ---
        while True:
            try:
                ov_ok = _ownerville_session_valid(ov_page, verbose=False)
                as_ok = _appstream_valid(as_page)
                cookies = ctx.storage_state().get("cookies", [])
                msgs = []
                if ov_ok:
                    n = _export_site(cookies, "ownerville", OWNERVILLE_STORAGE_STATE)
                    msgs.append(f"ownerville ✓ ({n} cookies exported)")
                else:
                    msgs.append("ownerville ✗ STALE — log back in in its window")
                if as_ok:
                    n = _export_site(cookies, "applicantstream", APPSTREAM_STORAGE_STATE)
                    msgs.append(f"appstream ✓ ({n} cookies exported)")
                else:
                    msgs.append("appstream ✗ STALE — log back in in its window")
                flag = "" if (ov_ok and as_ok) else "  ⚠️"
                print(f"[{_stamp()}]{flag} " + " | ".join(msgs), flush=True)
            except KeyboardInterrupt:
                print(f"[{_stamp()}] holder stopped.", flush=True)
                return 0
            except Exception as e:
                print(f"[{_stamp()}] refresh error: {type(e).__name__}: {str(e)[:140]}",
                      flush=True)
            try:
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                print(f"[{_stamp()}] holder stopped.", flush=True)
                return 0


if __name__ == "__main__":
    sys.exit(main())
