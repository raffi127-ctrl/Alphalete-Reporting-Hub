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
    _reuse_appstream_storage_state,
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


def _export_ownerville(ctx) -> int:
    """Write the live ownerville (master SSO) cookies to OWNERVILLE_STORAGE_STATE.
    Only called when the session is confirmed live, so a good export is never
    clobbered with dead cookies."""
    cookies = ctx.storage_state().get("cookies", [])
    ov = [c for c in cookies if "ownerville" in (c.get("domain") or "")]
    OWNERVILLE_STORAGE_STATE.write_text(json.dumps({"cookies": ov, "origins": []}))
    return len(ov)


def _export_appstream(ctx) -> int:
    """Write the live applicantstream cookies (CFID/CFTOKEN + rqst SSO token) to
    APPSTREAM_STORAGE_STATE. Only called when the console is confirmed live.

    GUARD (Megan 2026-06-25): only export if the session actually carries an
    rqst SSO token. A degraded/SSO-only console can have applicantstream cookies
    but ZERO rqst tokens — writing that clobbers a good manual rcaptain login
    and kills the direct-session reports (daily_focus, recruiter_retention).
    No token → keep the last good export untouched."""
    cookies = ctx.storage_state().get("cookies", [])
    ap = [c for c in cookies if "applicantstream" in (c.get("domain") or "")]
    n_rqst = sum(1 for c in ap if (c.get("name") or "").lower().startswith("rqst"))
    if ap and n_rqst:
        APPSTREAM_STORAGE_STATE.write_text(json.dumps({"cookies": ap, "origins": []}))
        return len(ap)
    return 0


def _warm_appstream(ctx, page, verbose: bool = False) -> bool:
    """Keep the AppStream (applicantstream) console session alive in the holder's
    context so unattended reports (daily_focus, recruiting) can reuse it.

    AppStream sits behind its OWN Cloudflare wall — it CANNOT be seeded via
    ownerville — so a human seeds it once with `--appstream-login`; this keeps
    that session warm. Strategy: reload the open console to refresh the
    ColdFusion session; if it dropped (or hasn't loaded yet), restore it from
    the saved storage_state (which still holds live CFID/CFTOKEN + the rqst SSO
    token). Returns True if the office switcher (#searchMC) is present."""
    # Lightweight keep-alive: reload the live console if we're on it.
    try:
        if "applicantstream" in (page.url or ""):
            page.reload(wait_until="domcontentloaded")
            if page.locator("#searchMC").count() > 0:
                return True
    except Exception:
        pass
    # Console dropped or not loaded yet — restore from the saved session.
    try:
        return _reuse_appstream_storage_state(ctx, page, verbose=verbose)
    except Exception:
        return False


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

        # --- AppStream: restore the console in its own page + keep it warm in the
        #     same context. AppStream has its OWN Cloudflare wall (can't be seeded
        #     via ownerville), so it relies on a one-time --appstream-login seed;
        #     the holder keeps that warm + re-exports it for unattended runs. ---
        appstream_page = ctx.new_page()
        if APPSTREAM_STORAGE_STATE.exists():
            if _warm_appstream(ctx, appstream_page, verbose=False):
                apn = _export_appstream(ctx)
                print(f"[{_stamp()}] AppStream ✓ — console restored ({apn} cookies).",
                      flush=True)
            else:
                print(f"[{_stamp()}]  ⚠️ AppStream session stale — re-seed once:  "
                      f"PYTHONPATH=. .venv/bin/python -m "
                      f"automations.shared.tableau_patchright --appstream-login", flush=True)
        else:
            print(f"[{_stamp()}]  ⚠️ AppStream not seeded — recruiting/daily-focus need it. "
                  f"Seed once:  PYTHONPATH=. .venv/bin/python -m "
                  f"automations.shared.tableau_patchright --appstream-login", flush=True)

        # --- Continuous keep-alive + export loop. ownerville uses val_page so
        #     login_page stays free for a human re-login; AppStream uses its own
        #     appstream_page. Each source exports only when confirmed live. ---
        while True:
            try:
                ov_ok = _ownerville_session_valid(val_page, verbose=False)
                as_ok = _warm_appstream(ctx, appstream_page, verbose=False)
                ovn = _export_ownerville(ctx) if ov_ok else None
                apn = _export_appstream(ctx) if as_ok else None
                ov_s = f"{ovn} ownerville" if ov_ok else "ownerville STALE"
                as_s = f"{apn} appstream" if as_ok else "appstream STALE"
                mark = "warm ✓" if (ov_ok and as_ok) else " ⚠️ partial"
                print(f"[{_stamp()}] {mark} — {ov_s} | {as_s} (stale = kept last good export)",
                      flush=True)
                if not ov_ok:
                    print(f"[{_stamp()}]     → log back into ownerville in the window.",
                          flush=True)
                if not as_ok:
                    print(f"[{_stamp()}]     → re-seed AppStream:  --appstream-login",
                          flush=True)
                # Predict the AppStream session dying + recover from it: ping
                # Megan ONCE with the re-seed command if it won't survive to the
                # next 4am batch, and auto-rerun daily_focus once it's healthy
                # again. Isolated so a watch hiccup never disturbs the holder
                # (Megan 2026-06-26 — "Eve needs to remotely help the glitch").
                try:
                    from automations.shared import appstream_watch
                    appstream_watch.watch()
                except Exception as e:
                    print(f"[{_stamp()}] appstream_watch skipped: "
                          f"{type(e).__name__}: {str(e)[:120]}", flush=True)
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
