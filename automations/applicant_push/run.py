#!/usr/bin/env python3
"""Applicant Push — run the batch send + the OAT leftovers cleanup on ONE warm
real-Chrome/CDP AppStream session (office 11580, Carlos, Lucy 2).

Flow:
  1. Open ONE warm, logged-in real-Chrome/CDP page on office 11580
     (resume_pushing.warm_appstream_cdp_page — the extractor plugin's service
     worker only runs in real Chrome).
  2. BATCH stage: resume_pushing.run_batch_stage(page) — extract resumes, Send to AI.
  3. LEFTOVERS stage: oat_processing.run_walk(page) — walk the One-App-at-a-time
     queue and send / remove / re-text / flag what the batch pass left behind.
  4. Print a combined summary and record the batch count for the daily scorecard.

KEY BEHAVIOR: if the BATCH stage wedges on Indeed's employer-portal Turnstile
(the current failure mode — the resume fetches get 403'd), the LEFTOVERS stage
STILL runs on the same warm page. OAT's in-ATS sends / removes / re-texts don't
touch Indeed, so the leftovers keep draining even when batch extraction is
blocked. Only a full login failure (no #searchMC) aborts both stages.

Safety: DRY-RUN by default (batch counts only, no Send/extract clicks; OAT reads
+ classifies + prints, no mutations). Pass --live to act. Send-to-AI, removes and
re-texts are IRREVERSIBLE.

  --dry-run       reads + classifies only, nothing pushed (DEFAULT)
  --live          perform batch Send-to-AI + OAT sends/removes/re-texts
  --batch-only    run only the batch stage (skip OAT)
  --oat-only      run only the OAT leftovers stage (skip batch) — uses the same
                  warm CDP session, useful when batch is Indeed-wedged
  --limit N       cap OAT applicants this run (default: OAT's MAX_PER_RUN)
  --max-actions N cap OAT live mutations this run (controlled test)
  --batch-limit N send only the first N batch rows (small live test)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from automations.resume_pushing import run as rp
from automations.oat_processing import run as oat
from automations.recruiting_report import fetch_office

OFFICE_ID = rp.OFFICE_ID
OFFICE_HINT = rp.OFFICE_HINT
DIAG_TAB = "Applicant Push Diag"


def _batch_count_path(day: dt.date) -> str:
    """Per-day file the batch stage appends its Sent-to-AI count to, so the daily
    scorecard (oat_processing.summary) can show a 'batch sent' line alongside the
    OAT leftovers tallies. Lives beside the OAT activity CSV in output/."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "output", f"applicant-push-batch-{day.isoformat()}.json")


def _record_batch_count(sent: int, reached: bool) -> None:
    """Accumulate today's batch Sent-to-AI count (each q10min tick adds to it)."""
    try:
        path = _batch_count_path(dt.date.today())
        cur = {"sent": 0, "runs": 0, "reached": 0}
        if os.path.exists(path):
            try:
                cur = json.loads(open(path).read()) or cur
            except Exception:  # noqa: BLE001
                pass
        cur["sent"] = int(cur.get("sent", 0)) + int(sent or 0)
        cur["runs"] = int(cur.get("runs", 0)) + 1
        cur["reached"] = int(cur.get("reached", 0)) + (1 if reached else 0)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(json.dumps(cur))
    except Exception as e:  # noqa: BLE001
        rp._log(f"[push] could not record batch count: {e}")


def _prep_oat_page(page):
    """Return the shared CDP page to a logged-in classic AppStream console on office
    11580 so the OAT walk can open p=604. The batch stage navigates to the v2
    dashboard (and may open a v2 tab), so re-assert the console + office here, then
    attach the dialog-accept handler OAT needs for its confirm() dialogs."""
    try:
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    if page.locator("#searchMC").count() == 0:
        rp._log("[push] returning the shared tab to the classic console for OAT")
        try:
            page.goto("https://applicantstream.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception as e:  # noqa: BLE001
            rp._log(f"[push] console re-nav error: {e}")
    # Re-assert office 11580 (session-bound, but the v2 hop can change context).
    if not fetch_office._switch_office(page, OFFICE_ID, OFFICE_HINT):
        rp._log(f"[push] WARN: office re-switch to {OFFICE_ID} failed before OAT")
    oat.attach_dialog_accept(page)
    return page


MAX_SESSION_ATTEMPTS = 3


def run(live: bool = False, limit: int = None, max_actions: int = None,
        batch_only: bool = False, oat_only: bool = False,
        batch_limit: int = 0, _attempt: int = 1) -> int:
    """Run the unified batch + leftovers pipeline on one warm CDP session.

    Returns the worst stage rc: 2 if the session never established after retries
    (both stages aborted), else 0. A batch wedge (Indeed Turnstile) is logged but
    does NOT fail the run — the leftovers stage still runs.

    Office 11580 intermittently gets a fresh Cloudflare re-challenge during login or
    the office switch (the console loses #searchMC). That happens BEFORE any applicant
    is touched, so it's safe to retry a clean session up to MAX_SESSION_ATTEMPTS — the
    profile was invalidated on the way out, so each retry re-seeds fresh and self-heals
    (the same pattern resume_pushing._cdp_run and oat_processing.run already use)."""
    mode = "LIVE" if live else "DRY-RUN"
    rp._LOG_BUFFER.clear()
    rp._log(f"[push] Applicant Push — office {OFFICE_ID} ({OFFICE_HINT}) — {mode} "
            f"| batch_only={batch_only} oat_only={oat_only} | attempt {_attempt}"
            f"/{MAX_SESSION_ATTEMPTS}")

    batch = {"reached": False, "sent": 0, "remaining": None}
    oat_rc = None
    try:
        with rp.warm_appstream_cdp_page(diag_tab=DIAG_TAB) as (page, ctx, net):
            # ---- Stage 1: BATCH (Resume Pushing) ----
            if not oat_only:
                rp._log("[push] ===== STAGE 1: BATCH (Resume Pushing) =====")
                try:
                    batch = rp.run_batch_stage(page, dry_run=not live,
                                               limit=batch_limit)
                except rp.ExtractionStalled as e:
                    # Indeed's employer-portal Turnstile is the usual cause. Log it,
                    # but DO NOT abort — the leftovers stage doesn't need Indeed.
                    rp._log("[push] BATCH extractor stalled: " + str(e)[:200])
                    if net.get("indeed_403") or net.get("turnstile"):
                        rp._log("[push][CAUSE] batch resume fetches from "
                                "employers.indeed.com were CHALLENGED (401/403"
                                + (" + Turnstile" if net.get("turnstile") else "")
                                + ") — INDEED's bot protection, not AppStream. Refresh "
                                "the Indeed employer login on Lucy 2. Continuing to "
                                "the LEFTOVERS stage anyway.")
                    else:
                        rp._log("[push][CAUSE] no Indeed-403/Turnstile this pass — "
                                "empty/slow batch or AppStream-side. Continuing to "
                                "the LEFTOVERS stage.")
                except Exception as e:  # noqa: BLE001
                    import traceback
                    rp._log("[push] BATCH stage error (continuing to OAT): "
                            + str(e)[:200])
                    rp._log(traceback.format_exc()[-400:])
                _record_batch_count(batch.get("sent", 0), batch.get("reached", False))

            # ---- Stage 2: LEFTOVERS (OAT Processing) ----
            if not batch_only:
                rp._log("[push] ===== STAGE 2: LEFTOVERS (OAT Processing) =====")
                oat_page = _prep_oat_page(page)
                try:
                    oat_rc = oat.run_walk(oat_page, live=live, limit=limit,
                                          max_actions=max_actions)
                except Exception as e:  # noqa: BLE001
                    import traceback
                    rp._log("[push] OAT stage error: " + str(e)[:200])
                    rp._log(traceback.format_exc()[-400:])
                    oat_rc = 1
    except rp.AppStreamLoginFailed as e:
        # The console never established (login or office-switch Cloudflare
        # re-challenge). This is BEFORE any applicant is touched, so retry a fresh
        # session — the profile was invalidated on the way out, so the retry
        # re-seeds from Default and self-heals.
        if _attempt < MAX_SESSION_ATTEMPTS:
            rp._log(f"[push] session didn't establish ({e}) — retry "
                    f"{_attempt + 1}/{MAX_SESSION_ATTEMPTS} with a fresh profile")
            return run(live=live, limit=limit, max_actions=max_actions,
                       batch_only=batch_only, oat_only=oat_only,
                       batch_limit=batch_limit, _attempt=_attempt + 1)
        rp._log(f"[push][STOP] no AppStream session after {MAX_SESSION_ATTEMPTS} "
                f"attempts ({e}) — both stages aborted. Office 11580 likely needs a "
                "human Cloudflare clear on Lucy 2.")
        return 2

    rp._log("[push] ===== COMBINED SUMMARY =====")
    rp._log(f"[push] mode={mode} | batch reached={batch.get('reached')} "
            f"sent={batch.get('sent')} still-ready={batch.get('remaining')} "
            f"| oat rc={oat_rc}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Applicant Push — batch send + OAT leftovers on one CDP session "
                    "(office 11580, Lucy 2)")
    p.add_argument("--live", action="store_true",
                   help="Perform batch Send-to-AI + OAT sends/removes/re-texts "
                        "(default is dry-run: read + classify + print only)")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (already the default)")
    p.add_argument("--batch-only", action="store_true",
                   help="Run only the batch (Resume Pushing) stage")
    p.add_argument("--oat-only", action="store_true",
                   help="Run only the OAT leftovers stage (still uses the warm CDP "
                        "session — handy when batch is Indeed-wedged)")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap OAT applicants this run (default: OAT's MAX_PER_RUN)")
    p.add_argument("--max-actions", type=int, default=None,
                   help="Cap OAT live mutations this run (controlled test)")
    p.add_argument("--batch-limit", type=int, default=0,
                   help="Send only the first N batch rows (small live test)")
    args = p.parse_args(argv)

    live = args.live and not args.dry_run
    if args.batch_only and args.oat_only:
        print("[push] --batch-only and --oat-only are mutually exclusive", flush=True)
        return 2
    return run(live=live, limit=args.limit, max_actions=args.max_actions,
               batch_only=args.batch_only, oat_only=args.oat_only,
               batch_limit=args.batch_limit)


if __name__ == "__main__":
    sys.exit(main())
