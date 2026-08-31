#!/usr/bin/env python3
"""Applicant Push — run the batch send + the OAT leftovers cleanup on ONE warm
real-Chrome/CDP AppStream session, for ONE ApplicantStream office, on Lucy 2.

Offices are declared in `offices.py` (11580 Carlos, 23467 Atef) and chosen with
--office; the default is Carlos, so a call with no flag behaves as it always
has. The scheduled agent rotates offices one per tick — it never runs two warm
sessions at once.

Flow:
  1. Open ONE warm, logged-in real-Chrome/CDP page on the chosen office
     (resume_pushing.warm_appstream_cdp_page — the extractor plugin's service
     worker only runs in real Chrome). It lands on the classic console.
  2. LEFTOVERS stage FIRST: oat_processing.run_walk(page) — walk the
     One-App-at-a-time queue (classic p=604) and send / remove / re-text / flag.
     Runs on the console the session handed us, with NO navigation.
  3. BATCH stage: hop classic-home → v2, resume_pushing.run_batch_stage(page) —
     extract resumes, Send to AI.
  4. Print a combined summary and record the batch count for the daily scorecard.

WHY OAT FIRST: office 11580 re-triggers Cloudflare on a v2→classic transition, so
doing batch (v2) first and then navigating BACK to classic for OAT wedges (proven
8/4). Running OAT on the freshly-established classic console, then hopping to v2
last (a one-way classic→v2), only ever uses the known-good navigation direction.
Neither stage switches office, so no office re-switch (that reload is what
re-challenges) is needed between them.

KEY BEHAVIOR: if the BATCH stage wedges on Indeed's employer-portal Turnstile
(the current failure mode — the resume fetches get 403'd), it does NOT fail the
run — the LEFTOVERS stage already ran (OAT's in-ATS sends / removes / re-texts
don't touch Indeed). Only a full login failure (no #searchMC) aborts both stages.

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
  --office ID     which office to work (default 11580 = Carlos)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from automations.resume_pushing import run as rp
from automations.oat_processing import run as oat
from automations.applicant_push import offices

# Set by _use_office(); the defaults are Carlos's office, so a caller that
# never passes --office behaves exactly as before.
OFFICE = offices.get(offices.DEFAULT_OFFICE)
OFFICE_ID = OFFICE["office_id"]
OFFICE_HINT = OFFICE["hint"]
DIAG_TAB = OFFICE["push_diag_tab"]


def _use_office(office_id: str) -> dict:
    """Point this process (and resume_pushing + oat_processing under it) at one
    office. ONE office per process — see offices.py for why the agent rotates
    offices tick-by-tick instead of running two warm sessions at once."""
    global OFFICE, OFFICE_ID, OFFICE_HINT, DIAG_TAB
    OFFICE = offices.activate(office_id)
    OFFICE_ID = OFFICE["office_id"]
    OFFICE_HINT = OFFICE["hint"]
    DIAG_TAB = OFFICE["push_diag_tab"]
    return OFFICE


def _batch_count_path(day: dt.date) -> str:
    """Per-day file the batch stage appends its Sent-to-AI count to, so the daily
    scorecard (oat_processing.summary) can show a 'batch sent' line alongside the
    OAT leftovers tallies. Lives beside the OAT activity CSV in output/."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "output",
                        f"applicant-push-batch-{day.isoformat()}"
                        f"{OFFICE['suffix']}.json")


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


MAX_SESSION_ATTEMPTS = 3


def _run_stage(name: str, work):
    """Open a FRESH warm CDP session (classic console, office 11580) and run
    ``work(page, ctx, net)`` on it. Each stage (leftovers, batch) gets its own
    session so batch starts from a clean console and goes straight console → v2
    (the proven path) instead of a fragile mid-run re-navigation.

    Retries the session OPEN up to MAX_SESSION_ATTEMPTS on AppStreamLoginFailed — a
    Cloudflare re-challenge during login/office-switch, which happens BEFORE any
    applicant is touched, so a fresh-profile retry is safe and self-heals. Returns
    ``work``'s value, or None if the session never established after all retries
    (the other stage still runs — a batch session failure never blocks leftovers)."""
    for attempt in range(1, MAX_SESSION_ATTEMPTS + 1):
        try:
            with rp.warm_appstream_cdp_page(diag_tab=DIAG_TAB) as (page, ctx, net):
                return work(page, ctx, net)
        except rp.AppStreamLoginFailed as e:
            if attempt < MAX_SESSION_ATTEMPTS:
                rp._log(f"[push] {name}: session didn't establish ({e}) — retry "
                        f"{attempt + 1}/{MAX_SESSION_ATTEMPTS} with a fresh profile")
                continue
            rp._log(f"[push][STOP] {name}: no AppStream session after "
                    f"{MAX_SESSION_ATTEMPTS} attempts ({e}) — stage skipped. "
                    f"Office {OFFICE_ID} may need a human Cloudflare clear "
                    "on Lucy 2.")
            return None


def run(live: bool = False, limit: int = None, max_actions: int = None,
        batch_only: bool = False, oat_only: bool = False,
        batch_limit: int = 0, office: str = None,
        recheck_nophone: bool = False) -> int:
    """Run the unified pipeline: LEFTOVERS (OAT) then BATCH (Resume Pushing), each in
    its OWN fresh warm CDP session (see _run_stage for why — batch needs a clean
    console→v2 start, not a mid-run hop).

    Always returns 0 (the agent's success is "it ran"); a stage that can't establish a
    session or that wedges is logged and skipped, never fatal to the other stage. A
    batch Indeed-Turnstile wedge still counts as reached=True (it got to the batch
    page). Office-11580 Cloudflare re-challenges during login are retried per stage."""
    _use_office(office or offices.DEFAULT_OFFICE)
    if recheck_nophone:
        # Drop today's "already checked, no number" cache so this walk re-reads
        # those resumes. For use right after a fix to the resume READ itself —
        # otherwise the cache pins yesterday's wrong verdict until midnight.
        oat.reset_nophone_cache()
    mode = "LIVE" if live else "DRY-RUN"
    rp._LOG_BUFFER.clear()
    rp._log(f"[push] Applicant Push — office {OFFICE_ID} ({OFFICE_HINT}) — {mode} "
            f"| batch_only={batch_only} oat_only={oat_only}")

    batch = {"reached": False, "sent": 0, "remaining": None}
    oat_rc = None

    # ---- Stage 1: LEFTOVERS (OAT, classic p=604) — its OWN fresh session ----
    if not batch_only:
        rp._log("[push] ===== STAGE 1: LEFTOVERS (OAT Processing) =====")

        def _oat_work(page, ctx, net):
            oat.attach_dialog_accept(page)
            try:
                return oat.run_walk(page, live=live, limit=limit,
                                    max_actions=max_actions)
            except Exception as e:  # noqa: BLE001
                import traceback
                rp._log("[push] OAT stage error: " + str(e)[:200])
                rp._log(traceback.format_exc()[-400:])
                return 1

        oat_rc = _run_stage("leftovers", _oat_work)

    # ---- Stage 2: BATCH (Resume Pushing, v2) — its OWN fresh session ----
    # Batch runs on a SEPARATE fresh session, NOT a mid-run hop off the OAT tab.
    # warm_appstream_cdp_page hands batch a clean classic console, and
    # run_batch_stage goes straight console → v2 → Process in Batches — the exact
    # path standalone Resume Pushing has always used. This avoids the fragile
    # mid-run classic↔v2 transition that office-11580 Cloudflare kept wedging
    # (batch reached=False all of 8/5-8/6 with the one-session design).
    if not oat_only:
        rp._log("[push] ===== STAGE 2: BATCH (Resume Pushing) =====")

        def _batch_work(page, ctx, net):
            try:
                return rp.run_batch_stage(page, dry_run=not live, limit=batch_limit)
            except rp.ExtractionStalled as e:
                # Reached the batch page but the extractor wedged (usually Indeed's
                # Turnstile on the resume fetches). NON-fatal — and it DID reach.
                rp._log("[push] BATCH extractor stalled: " + str(e)[:200])
                if net.get("indeed_403") or net.get("turnstile"):
                    rp._log("[push][CAUSE] batch resume fetches from "
                            "employers.indeed.com were CHALLENGED (401/403"
                            + (" + Turnstile" if net.get("turnstile") else "")
                            + ") — INDEED's bot protection, not AppStream.")
                else:
                    rp._log("[push][CAUSE] no Indeed-403/Turnstile this pass — "
                            "empty/slow batch or AppStream-side.")
                return {"reached": True, "sent": 0, "remaining": None}
            except Exception as e:  # noqa: BLE001
                import traceback
                rp._log("[push] BATCH stage error: " + str(e)[:200])
                rp._log(traceback.format_exc()[-400:])
                return {"reached": False, "sent": 0, "remaining": None}

        res = _run_stage("batch", _batch_work)
        if res:
            batch = res
        _record_batch_count(batch.get("sent", 0), batch.get("reached", False))

    rp._log("[push] ===== COMBINED SUMMARY =====")
    rp._log(f"[push] mode={mode} | batch reached={batch.get('reached')} "
            f"sent={batch.get('sent')} still-ready={batch.get('remaining')} "
            f"| oat rc={oat_rc}")
    return 0


# HARD-CODED: the ONLY offices a LIVE push may ever work. Carlos, 2026-08-30,
# after unexplained captain-login sends in Vincent's office: "hard-code it so
# that you're only pushing resumes for Atef and my office." An audit of another
# office must say so out loud with --audit-office — and still runs behind the
# per-click office guard in oat_processing.
PUSH_ALLOWED = {"11580", "23467"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Applicant Push — batch send + OAT leftovers on one CDP "
                    "session, for one ApplicantStream office (Lucy 2)")
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
    p.add_argument("--only-names", default="", metavar="PATH",
                   help="allowlist file (one applicant name per line) — the walk "
                        "touches ONLY these people and pages past everyone else. "
                        "Written by restore_removed --names-out; sets "
                        "OAT_ONLY_NAMES for the OAT stage.")
    p.add_argument("--audit-office", action="store_true",
                   help="explicit acknowledgement that this live push targets an "
                        "office OUTSIDE the hard-coded {11580, 23467} allowlist — "
                        "for supervised audit runs only")
    p.add_argument("--recheck-nophone", action="store_true",
                   help="Re-read the resumes of applicants already flagged "
                        "no-number TODAY (archives the day's cache first). Use "
                        "after fixing the resume read itself; normally the cache "
                        "is what stops us reopening dead-end resumes q5min.")
    p.add_argument("--office", default=offices.DEFAULT_OFFICE,
                   choices=sorted(offices.OFFICES),
                   help="Which ApplicantStream office to work this run "
                        "(default %(default)s = Carlos). Each office has its own "
                        "browser profile, day files and Slack settings — see "
                        "automations/applicant_push/offices.py.")
    args = p.parse_args(argv)
    if getattr(args, "only_names", ""):
        os.environ["OAT_ONLY_NAMES"] = args.only_names
    if (args.live and args.office not in PUSH_ALLOWED
            and not getattr(args, "audit_office", False)):
        raise SystemExit(
            f"[push] REFUSED: live push for office {args.office} — only "
            f"{sorted(PUSH_ALLOWED)} are ever pushed. An audit run must pass "
            f"--audit-office explicitly.")

    live = args.live and not args.dry_run
    if args.batch_only and args.oat_only:
        print("[push] --batch-only and --oat-only are mutually exclusive", flush=True)
        return 2
    return run(live=live, limit=args.limit, max_actions=args.max_actions,
               batch_only=args.batch_only, oat_only=args.oat_only,
               batch_limit=args.batch_limit, office=args.office,
               recheck_nophone=args.recheck_nophone)


if __name__ == "__main__":
    sys.exit(main())
