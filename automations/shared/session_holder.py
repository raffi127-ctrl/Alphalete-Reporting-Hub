"""Continuous session holder — keeps the ownerville login warm so SCHEDULED,
UNATTENDED report runs never hit Cloudflare's 'verify you're human'.

WHY (Megan 2026-06-17): Cloudflare globally tightened — the interactive Turnstile
now appears on a FRESH login even in a normal browser, on every machine. There is
no headless way past a forced interactive challenge, and the vendors won't expose
an API. The only thing that ALWAYS works unattended is to NEVER do a fresh login.

ownerville is the MASTER session: a soak test (2026-06-17) confirmed that with a
fresh exported ownerville storage_state, a HEADLESS run reaches BOTH Tableau
(ownerville SSO) AND AppStream (appstream_session also SSOs through
v2.ownerville). So this holder only needs ownerville logged in — that one session
covers every Tableau report and the AppStream recruiter pull.

HOW: a human clears Cloudflare ONCE in the holder's window, then it keeps that
session alive 24/7 (never closes → never re-challenged) and every few minutes
EXPORTS the live cookies into the storage_state files the reports already reuse
(tableau_patchright._reuse_ownerville_storage_state / _reuse_appstream_storage_state).
Scheduled runs load those and skip the login + Turnstile entirely.

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
)

# The holder runs CONTINUOUSLY, so it must NOT use the reports' profile —
# a held-open persistent profile would lock out every report run. It keeps the
# session in its OWN profile and shares it via the exported storage_state.
HOLDER_PROFILE_DIR = PROFILE_DIR.parent / ".browser_profile_holder"


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _export(ctx) -> tuple[int, int]:
    """Write the live ownerville (master) + AppStream cookies to their
    storage_state files. ownerville is what the reports actually need; the
    AppStream file is a best-effort bonus (its console also SSOs via ownerville)."""
    cookies = ctx.storage_state().get("cookies", [])
    ov = [c for c in cookies if "ownerville" in (c.get("domain") or "")]
    ap = [c for c in cookies if "applicantstream" in (c.get("domain") or "")]
    OWNERVILLE_STORAGE_STATE.write_text(json.dumps({"cookies": ov, "origins": []}))
    if ap:
        APPSTREAM_STORAGE_STATE.write_text(json.dumps({"cookies": ap, "origins": []}))
    return len(ov), len(ap)


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
    with sync_playwright() as p:
        ctx = _launch_persistent(p, HOLDER_PROFILE_DIR, headless=False,
                                 label="session_holder", verbose=False)
        login_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        val_page = ctx.new_page()   # SEPARATE page for polling — never disturbs login_page

        # --- Seed: open ownerville for the human; poll a separate page for a
        #     live session. The holder never drives the form or navigates the
        #     human's page — a pure human login is what keeps Cloudflare quiet. ---
        try:
            login_page.goto(OWNERVILLE_V2_URL, wait_until="domcontentloaded")
        except Exception:
            pass
        print(f"[{_stamp()}] SEED: log into ownerville in the window and clear any "
              f"'verify you're human' box. (This one session covers Tableau AND "
              f"AppStream.) Waiting up to {args.seed_timeout:g} min…", flush=True)
        waited, deadline = 0, args.seed_timeout * 60
        seeded = False
        while waited < deadline:
            if _ownerville_session_valid(val_page, verbose=False):
                seeded = True
                break
            time.sleep(15)
            waited += 15
        if seeded:
            ovn, apn = _export(ctx)
            print(f"[{_stamp()}] seeded ✓ — exported {ovn} ownerville + {apn} appstream "
                  f"cookies. Keep-alive every {args.interval:g} min. Leave running. Ctrl-C to stop.",
                  flush=True)
        else:
            print(f"[{_stamp()}] not seeded within {args.seed_timeout:g} min — will keep "
                  f"checking; finish logging in in the window.", flush=True)

        # --- Continuous keep-alive + export loop (uses val_page so login_page
        #     stays available for a human re-login if ever needed). ---
        while True:
            try:
                if _ownerville_session_valid(val_page, verbose=False):
                    ovn, apn = _export(ctx)
                    print(f"[{_stamp()}] warm ✓ — exported {ovn} ownerville + {apn} appstream cookies",
                          flush=True)
                else:
                    print(f"[{_stamp()}]  ⚠️ STALE — log back into ownerville in the window "
                          f"(kept last good export).", flush=True)
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
