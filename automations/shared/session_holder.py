"""Continuous session holder — keeps the ownerville login warm so SCHEDULED,
UNATTENDED report runs never hit Cloudflare's 'verify you're human'.

WHY (Megan 2026-06-17): Cloudflare globally tightened — the interactive Turnstile
now appears on a FRESH login even in a normal browser, on every machine. There is
no headless way past a forced interactive challenge, and the vendors won't expose
an API. The only thing that ALWAYS works unattended is to NEVER do a fresh login.

ownerville is the session this holds warm: with a fresh exported ownerville
storage_state, a HEADLESS run reaches Tableau via ownerville SSO. So the holder
keeps ownerville logged in — that one session covers every Tableau/ownerville
report.

AppStream is NO LONGER held here (2026-06-30): its Cloudflare wall came down, so
each AppStream report self-heals by driving the rcaptain login at run time
(appstream_direct_session, allow_form_login default). The holder is OV-ONLY now —
one warm session, one window, no 3rd tab.

HOW: a human clears Cloudflare ONCE in the holder's window, then it keeps that
session alive 24/7 (never closes → never re-challenged) and every few minutes
EXPORTS the live cookies into the storage_state file the reports reuse
(tableau_patchright._reuse_ownerville_storage_state). Scheduled runs load that and
skip the login + Turnstile entirely.

SEED is non-disruptive: a SEPARATE validation page polls v2.ownerville for a live
rqst token while the human logs in on the login page — it never navigates the
human's page out from under them (the bug in the first cut).

DEGRADES SAFELY: if the session goes stale it does NOT drive the form (that hits
the Turnstile). It alerts loudly, keeps the last good export, and the human logs
back in RIGHT THERE — same warm window, no new escalation.

Run on the always-on schedule machine (Mac mini; a laptop works while awake):

    python -m automations.shared.session_holder
    python -m automations.shared.session_holder --interval 6

Cross-platform (mac + windows). Ctrl-C to stop.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import (
    PROFILE_DIR,
    _launch_persistent,
    _ownerville_session_valid,
    OWNERVILLE_STORAGE_STATE,
    OWNERVILLE_V2_URL,
)

# The holder runs CONTINUOUSLY, so it must NOT use the reports' profile —
# a held-open persistent profile would lock out every report run. It keeps the
# session in its OWN profile and shares it via the exported storage_state.
HOLDER_PROFILE_DIR = PROFILE_DIR.parent / ".browser_profile_holder"


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _browser_alive(ctx) -> bool:
    """Cheap liveness probe for the holder's Chrome. A persistent context's
    .browser is None, so is_connected() isn't available; instead confirm at
    least one page exists and isn't closed. A crashed browser reports its pages
    closed (or raises on access) -> False, which the loop turns into a clean
    exit so launchd relaunches the job (fixes the 2026-06-30 dead-Chrome /
    live-Python orphan where the session silently went cold)."""
    try:
        pages = ctx.pages
        return bool(pages) and any(not pg.is_closed() for pg in pages)
    except Exception:
        return False


def _export_ownerville(ctx) -> int:
    """Write the live ownerville (master SSO) cookies to OWNERVILLE_STORAGE_STATE.
    Only called when the session is confirmed live, so a good export is never
    clobbered with dead cookies."""
    cookies = ctx.storage_state().get("cookies", [])
    ov = [c for c in cookies if "ownerville" in (c.get("domain") or "")]
    OWNERVILLE_STORAGE_STATE.write_text(json.dumps({"cookies": ov, "origins": []}))
    return len(ov)




def main() -> int:
    ap = argparse.ArgumentParser(
        description="Keep the ownerville session warm for unattended report runs.")
    ap.add_argument("--interval", type=float, default=8.0,
                    help="Minutes between keep-alive refreshes + exports (default 8; "
                         "keep it well under Cloudflare's clearance lifetime).")
    ap.add_argument("--seed-timeout", type=float, default=15.0,
                    help="Minutes to wait for the human to log in on first start.")
    args = ap.parse_args()

    HOLDER_PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    # A crashed Chrome leaves a stale Singleton* lock in the profile that makes
    # the next launch fail with "profile already in use" — which would defeat the
    # whole point of a launchd restart. Clear them so a watchdog/launchd relaunch
    # actually relaunches instead of dying at startup.
    for _lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (HOLDER_PROFILE_DIR / _lock).unlink()
        except OSError:
            pass
    with sync_playwright() as p:
        ctx = _launch_persistent(p, HOLDER_PROFILE_DIR, headless=False,
                                 label="session_holder", verbose=False)
        login_page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # --- Seed: open ownerville for the human; poll a separate page for a
        #     live session. The holder never drives the form or navigates the
        #     human's page — a pure human login is what keeps Cloudflare quiet. ---
        try:
            login_page.goto(OWNERVILLE_V2_URL, wait_until="domcontentloaded")
        except Exception:
            pass
        print(f"[{_stamp()}] SEED: log into ownerville in the window and clear any "
              f"'verify you're human' box. (This one session covers every "
              f"Tableau/ownerville report.) Waiting up to {args.seed_timeout:g} min…",
              flush=True)
        waited, deadline = 0, args.seed_timeout * 60
        seeded = False
        while waited < deadline:
            # PASSIVE detection — read the login page's URL (a property read, NO
            # navigation) so we never re-trigger Cloudflare while the human is
            # mid-login. The old cut polled by NAVIGATING a check page every 15s,
            # which kept the Turnstile alive and fought the login (Megan
            # 2026-06-18). The post-login redirect lands on v2 with an rqst token.
            if "rqst=" in (login_page.url or ""):
                seeded = True
                break
            time.sleep(5)
            waited += 5
        if seeded:
            ovn = _export_ownerville(ctx)
            print(f"[{_stamp()}] seeded ✓ — exported {ovn} ownerville cookies. "
                  f"Keep-alive every {args.interval:g} min. Leave running. Ctrl-C to stop.",
                  flush=True)
        else:
            print(f"[{_stamp()}] not seeded within {args.seed_timeout:g} min — will keep "
                  f"checking; finish logging in in the window.", flush=True)

        # --- AppStream no longer lives in the holder (2026-06-30). Its Cloudflare
        #     wall came down, so every AppStream report self-heals by driving the
        #     rcaptain login at run time (appstream_direct_session, allow_form_login
        #     default). The holder is OV-ONLY now — one warm ownerville session
        #     (which also covers Tableau via SSO), no 3rd tab, no AppStream re-seed
        #     babysitting. ---

        # --- Continuous keep-alive + export loop, ONE ownerville tab. When the
        #     session is healthy we navigate that tab to keep it warm; when it
        #     goes stale we STOP navigating and passively watch the SAME tab for
        #     the human's re-login (navigating mid-login fights Cloudflare —
        #     Megan 2026-06-18). No separate poller tab. ---
        # WATCHDOG: launchd's KeepAlive only watches THIS python, not the Chrome
        # child. When Chrome died, the old loop logged "refresh error" forever
        # while the session went cold (the 2026-06-30 failure). Instead: detect a
        # dead/unrecoverable browser and EXIT non-zero so launchd relaunches the
        # whole job — a fresh Chrome on the SAME persistent profile re-warms from
        # the still-valid cookies, no human needed.
        def _passive_rqst() -> bool:
            """Read the CURRENT tab for a live rqst — URL or in-page SSO link. No
            navigation, so it never disturbs a human mid-login."""
            try:
                if re.search(r"rqst=([A-Za-z0-9_]+)", login_page.url or ""):
                    return True
                href = login_page.evaluate(
                    "() => { const a=[...document.querySelectorAll('a')]"
                    ".find(x=>/rqst=/.test(x.getAttribute('href')||'')); "
                    "return a?a.getAttribute('href'):''; }")
                return bool(re.search(r"rqst=([A-Za-z0-9_]+)", href or ""))
            except Exception:
                return False

        awaiting_login = not seeded
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 3
        # Self-heal the LOGIN-lapsed-but-browser-alive gap (2026-07-09): the old
        # watchdog only exits on a DEAD browser, so when the ownerville login went
        # stale while Chrome stayed up, the loop sat in awaiting_login logging
        # "waiting for ownerville login…" for HOURS until a human / the re-seed email
        # — even though a plain relaunch re-seeds UNATTENDED from the persistent
        # profile's still-valid cookies (proven: `lucy restart_holder` recovered the
        # session in seconds today). So if we haven't managed a good export in this
        # long, EXIT(1) → launchd relaunches → the fresh-start goto re-navigates and
        # re-seeds with no human. 25 min >> the 6–8 min export cadence (so it only
        # fires when genuinely stuck) and >> any real human login (which _passive_rqst
        # detects instantly anyway), so it won't interrupt someone mid-login.
        NO_EXPORT_MAX_MIN = 25
        last_export_ok = time.time()   # the seed export above counts as the first
        while True:
            try:
                if not _browser_alive(ctx):
                    print(f"[{_stamp()}] browser is gone — exiting (rc=1) so launchd "
                          f"restarts the holder fresh on the persistent profile.",
                          flush=True)
                    return 1
                stale_min = (time.time() - last_export_ok) / 60
                if stale_min >= NO_EXPORT_MAX_MIN:
                    print(f"[{_stamp()}] no good ownerville export in {stale_min:.0f} min "
                          f"(login lapsed, browser still alive) — exiting (rc=1) so "
                          f"launchd relaunches + re-seeds from the persistent profile.",
                          flush=True)
                    return 1
                if awaiting_login:
                    # Human is (re)logging in on the tab — DON'T navigate it.
                    if _passive_rqst():
                        awaiting_login = False
                        ovn = _export_ownerville(ctx)
                        last_export_ok = time.time()
                        print(f"[{_stamp()}] re-seeded ✓ — exported {ovn} ownerville "
                              f"cookies.", flush=True)
                    else:
                        print(f"[{_stamp()}]  ⏳ waiting for ownerville login in the "
                              f"window…", flush=True)
                else:
                    # Healthy → navigate the one tab to keep the session warm.
                    if _ownerville_session_valid(login_page, verbose=False):
                        ovn = _export_ownerville(ctx)
                        last_export_ok = time.time()
                        print(f"[{_stamp()}] warm ✓ — {ovn} ownerville cookies "
                              f"(stale = kept last good export)", flush=True)
                    else:
                        awaiting_login = True
                        print(f"[{_stamp()}]  ⚠️ ownerville STALE — log back in in the "
                              f"window (kept last good export).", flush=True)
                consecutive_errors = 0   # a clean pass clears the strike count
            except KeyboardInterrupt:
                print(f"[{_stamp()}] holder stopped.", flush=True)
                return 0
            except Exception as e:
                consecutive_errors += 1
                emsg = f"{type(e).__name__}: {str(e)[:140]}"
                dead = any(s in emsg.lower() for s in
                           ("closed", "crash", "disconnect", "target page",
                            "browser has been"))
                print(f"[{_stamp()}] refresh error #{consecutive_errors}: {emsg}",
                      flush=True)
                if dead or consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"[{_stamp()}] browser unrecoverable — exiting (rc=1) so "
                          f"launchd restarts the holder fresh.", flush=True)
                    return 1
            try:
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                print(f"[{_stamp()}] holder stopped.", flush=True)
                return 0


if __name__ == "__main__":
    sys.exit(main())
