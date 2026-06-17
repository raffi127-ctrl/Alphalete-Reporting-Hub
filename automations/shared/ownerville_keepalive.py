"""Keep the ownerville session warm for unattended scheduled report runs.

WHY: every Tableau pull signs in through ownerville, whose Cloudflare
"verify you're human" clearance EXPIRES and then re-challenges
*interactively* — which a headless/scheduled run can't pass (the 8am
"9 Daily Metrics" failure, Eve 2026-06-17). This holder is seeded ONCE by
a human clearing Cloudflare, then keeps the shared persistent profile's
session fresh so report runs reuse it and never hit a cold challenge.

HOW (open -> refresh -> close cycle, per Megan 2026-06-17): every
--interval minutes it briefly opens the persistent profile, re-validates
the session (re-logging in from saved creds if the cookie went stale,
waiting for a human ONLY if Cloudflare actually blocks), then CLOSES the
browser so the profile is free for report runs in between. As long as the
interval is shorter than Cloudflare's clearance lifetime, the session
never goes cold and no human is needed after the first seed. Profile
collisions with a report run are handled by tableau_patchright's existing
launch wait+retry, so a run that starts mid-refresh just rides it out.

Cross-platform (macOS + Windows). Run it on each machine that runs the
scheduled reports (laptops / Mac mini / Windows):

    # default: refresh every 12 min, headed so a human can seed/rescue
    python -m automations.shared.ownerville_keepalive

    python -m automations.shared.ownerville_keepalive --interval 10
    python -m automations.shared.ownerville_keepalive --once     # one refresh + exit (cron-style)
    python -m automations.shared.ownerville_keepalive --headless # only AFTER a human has seeded

Keep it running in the background (a terminal that stays open, nohup/&, a
login item, or a Windows scheduled task set to "run at log on"). The first
refresh opens a window — clear any Cloudflare box once; later refreshes
reuse that clearance.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import (
    PROFILE_DIR,
    _launch_persistent,
    _ensure_ownerville_logged_in,
    _ownerville_session_valid,
)


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def refresh_once(headless: bool = False, verbose: bool = True) -> bool:
    """Open the persistent profile, ensure a LIVE ownerville session, then
    close it (releasing the profile for report runs). Returns True if the
    session is warm on exit.

    When the session is already warm this returns fast. When the cookie has
    gone stale it re-logs in from saved creds; if Cloudflare actually blocks
    the automated submit it waits up to 5 min for a human to clear the box in
    the (headed) window. Raises only on a genuine login failure.
    """
    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(
            p, PROFILE_DIR, headless=headless,
            label="ownerville_keepalive", verbose=verbose,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _ensure_ownerville_logged_in(page, verbose=verbose)
            return _ownerville_session_valid(page, verbose=False)
        finally:
            ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Keep the ownerville session warm for unattended report runs.")
    ap.add_argument("--interval", type=float, default=12.0,
                    help="Minutes between refreshes (default 12). Keep it under "
                         "Cloudflare's clearance lifetime so the session never "
                         "goes cold.")
    ap.add_argument("--once", action="store_true",
                    help="Do a single refresh and exit (e.g. from a cron/Task "
                         "Scheduler job that fires every N minutes).")
    ap.add_argument("--headless", action="store_true",
                    help="Run headless. Only safe AFTER a human has seeded the "
                         "login once — a cold Cloudflare challenge cannot be "
                         "cleared headless.")
    args = ap.parse_args()

    if args.once:
        try:
            ok = refresh_once(headless=args.headless)
        except Exception as e:
            print(f"[{_stamp()}] refresh failed: {type(e).__name__}: "
                  f"{str(e)[:200]}", flush=True)
            return 1
        print(f"[{_stamp()}] ownerville session {'WARM ✓' if ok else 'STALE ✗'}",
              flush=True)
        return 0 if ok else 1

    print(f"[{_stamp()}] ownerville keep-alive started — refreshing every "
          f"{args.interval:g} min. The first refresh seeds the login: clear any "
          f"Cloudflare 'verify you're human' box in the window. Ctrl-C to stop.",
          flush=True)
    fails = 0
    while True:
        try:
            ok = refresh_once(headless=args.headless)
            if ok:
                fails = 0
                print(f"[{_stamp()}] session warm ✓", flush=True)
            else:
                fails += 1
                print(f"[{_stamp()}] session STALE ✗ (couldn't validate; {fails} "
                      f"in a row) — a human may need to clear Cloudflare in the "
                      f"window.", flush=True)
        except KeyboardInterrupt:
            print(f"[{_stamp()}] keep-alive stopped.", flush=True)
            return 0
        except Exception as e:
            fails += 1
            print(f"[{_stamp()}] refresh failed ({fails} in a row): "
                  f"{type(e).__name__}: {str(e)[:160]}", flush=True)
        try:
            time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print(f"[{_stamp()}] keep-alive stopped.", flush=True)
            return 0


if __name__ == "__main__":
    sys.exit(main())
