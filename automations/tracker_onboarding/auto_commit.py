"""Auto-commit confirmed enrollments (trackers AND metrics) so they survive
the morning pull.

The gap this closes: a confirmed enrollment is applied into the RUNNER'S
WORKING TREE only (posts start next morning), but the morning orchestrator
self-update resets uncommitted registry drift when main has also moved those
files — which can silently drop a confirmed office from the runs (the jamis
lesson; nii + drew had to be hand-committed). Committing the registries to
origin/main is the durable state.

What it does (idempotent, safe to run any time):
  1. Tracker leg — reads the 'Tracker Onboarding' tab (WIRED rows only;
     pending requests are hard-skipped) and regenerates
     automations/tableau_screenshots/onboarded_trackers.json.
  2. Metrics leg — reads the 'Office Onboarding' tab and regenerates
     automations/office_metrics/onboarded_offices.json +
     automations/b2b_metrics/onboarded_offices.json via
     office_onboarding.apply --registry-only (schedule_config.json is HOT on
     the runners and is deliberately never auto-committed — schedule entries
     keep flowing through onboard_apply, status quo).
  3. Schedule self-heal — a registry office with NO entry at all in the
     committed schedule_config.json is INVISIBLE to the 4am flow and nothing
     alerts (the nii/drew failure: their mini-only working-tree entries were
     wiped by the 2026-08-20 master-sequence pull and both Metrics threads
     silently stopped). For each clean onboarding whose report_id is missing
     from the schedule, re-add the entry (office_onboarding.apply's own
     _schedule_entry) and commit it with the registries. ADD-ONLY: an entry
     that exists is never touched (hand-tuned fields stay), so on a normal
     day this leg is a no-op and the hot 335KB file is not rewritten. To
     deliberately disable an office, set its entry's on_scheduler to false —
     don't delete the entry (deletion reads as a wipe and gets healed back).
  4. If — and only if — those files changed, commits JUST them and
     pushes (pull --rebase --autostash first). Other sessions' work-in-
     progress in the tree is never staged.

Runs on LUCY 1 (always-on) as the com.alphalete.tracker-auto-commit
LaunchAgent, daily 03:15 + 17:30 — the laptop isn't reliably awake (Megan,
2026-08-20). Needs Google creds (~/.config/recruiting-report/oauth-token.json,
same file the poller uses) + git push access (one-time mini_control
`git_push_setup`). Also runs fine by hand from the laptop:
  .venv/bin/python -m automations.tracker_onboarding.auto_commit
Exit 0 = committed or nothing to do; 1 = a leg was blocked/failed (message
says why; a blocked leg never stops the other from committing).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_CONFIG = "automations/day_orchestrator/schedule_config.json"
TARGETS = [
    "automations/tableau_screenshots/onboarded_trackers.json",
    "automations/office_metrics/onboarded_offices.json",
    "automations/b2b_metrics/onboarded_offices.json",
    # apply pins owner -> OwnerVille account number here (knocks/Time Gaps
    # office resolution) — same durability need as the registries.
    "automations/recruiting_report/icd_office_mappings.json",
    # only ever changed by the ADD-ONLY schedule self-heal (leg 3).
    SCHEDULE_CONFIG,
]


def _client():
    """gspread client from the runner's oauth token (same fallback the forms
    use). Raises with a clear message if creds are missing."""
    import gspread
    from google.oauth2.credentials import Credentials

    tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
    if not tok.exists():
        raise RuntimeError(f"no Google creds at {tok} — run on a machine "
                           "with the reporting oauth token")
    o = json.loads(tok.read_text())
    creds = Credentials(
        token=o.get("token"), refresh_token=o.get("refresh_token"),
        token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=o.get("client_id"), client_secret=o.get("client_secret"),
        scopes=list(o.get("scopes")
                    or ["https://www.googleapis.com/auth/spreadsheets"]))
    return gspread.authorize(creds)


def _git(*args: str) -> "subprocess.CompletedProcess":
    return subprocess.run(["git", *args], cwd=REPO_ROOT, text=True,
                          capture_output=True)


def heal_schedule(apply_mod) -> list:
    """ADD-ONLY schedule reconcile: give every clean onboarded office whose
    report_id has NO entry in schedule_config.json the standard entry apply
    would have written, and return the added report_ids ([] = file untouched).
    Existing entries are never modified — on_scheduler:false is respected as
    the deliberate off switch. Fractional orders after the office-metrics
    block (36.x) keep Megan's integer 1-60 master sequence unrenumbered."""
    path = REPO_ROOT / SCHEDULE_CONFIG
    raw = json.loads(path.read_text())
    reports = raw.setdefault("reports", {})
    healed = []
    for i, p in enumerate(apply_mod.plan()):
        if p["problems"]:
            continue
        rec = p["rec"]
        rid = rec.report_id()
        if rid in reports:
            continue                      # exists (even disabled) -> hands off
        entry = apply_mod._schedule_entry(rec, 36.5 + i * 0.01)
        entry["_note"] += (" RE-ADDED by tracker_onboarding.auto_commit "
                           "schedule self-heal: the entry was missing from "
                           "the committed schedule (never committed, or "
                           "wiped by a pull).")
        reports[rid] = entry
        healed.append(rid)
    if healed:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, indent=2))
        tmp.replace(path)
    return healed


def main() -> int:
    """_run + a Hub Activity row on every exit path.

    Standing rule: LaunchAgent reports publish to the Hub. This job had never
    logged a run, so its card sat on "no run logged" every single day — on
    2026-08-21 the 03:15 run had provably happened (its commit was in git) while
    the Hub said it hadn't run at all. The id must match the library card
    (automations/uploaded/_shared/tracker_auto_commit.py)."""
    import datetime as _dt
    import os
    started_at = _dt.datetime.now()
    rc = 1
    try:
        rc = _run()
        return rc
    finally:
        if not os.environ.get("HUB_REPORT_ID"):
            try:
                from automations.shared import hub_activity
                hub_activity.log_completed(
                    "tracker_auto_commit", "Tracker Auto Commit",
                    status=("success" if rc == 0 else "failed"),
                    started_at=started_at)
            except Exception as e:                    # noqa: BLE001
                print(f"(activity log skipped: {type(e).__name__}: {e})")


def _run() -> int:
    blocked = []

    # --- tracker leg -----------------------------------------------------
    try:
        from automations.tracker_onboarding import apply as TA, store as TS
        TS.set_client(_client())
        if TA.main(["--write"]) != 0:
            blocked.append("trackers: apply refused (validation problems "
                           "above)")
    except Exception as e:                            # noqa: BLE001
        blocked.append(f"trackers: {type(e).__name__}: {e}")

    # --- metrics leg (registries only — NEVER schedule_config.json) ------
    try:
        from automations.office_onboarding import apply as MA, store as MS
        MS.set_client(_client())
        if MA.main(["--write", "--registry-only"]) != 0:
            blocked.append("metrics: apply refused (validation problems "
                           "above)")
    except Exception as e:                            # noqa: BLE001
        blocked.append(f"metrics: {type(e).__name__}: {e}")

    # --- schedule self-heal leg (add-only; no-op when nothing is missing) --
    try:
        from automations.office_onboarding import apply as MA
        healed = heal_schedule(MA)
        if healed:
            print(f"schedule self-heal: re-added missing entries "
                  f"{', '.join(healed)}")
    except Exception as e:                            # noqa: BLE001
        blocked.append(f"schedule-heal: {type(e).__name__}: {e}")

    for b in blocked:
        print(f"BLOCKED — {b}")

    changed = [t for t in TARGETS
               if _git("status", "--porcelain", "--", t).stdout.strip()]
    if not changed:
        print("No enrollment changes — everything confirmed is already "
              "committed. Nothing to do.")
        return 1 if blocked else 0

    for t in changed:
        print(f"--- {t} changed ---\n{_git('diff', '--', t).stdout}\n---")

    _git("add", "--", *changed)
    msg = ("enrollments: auto-commit confirmed offices\n\n"
           "- regenerated from the Tracker Onboarding + Office Onboarding "
           "tabs\n"
           "- committed so the enrollment survives the morning self-update\n"
           "- files: " + ", ".join(Path(t).name for t in changed) + "\n\n"
           "Co-Authored-By: Claude <noreply@anthropic.com>")
    # Explicit committer identity so a runner machine with no git config
    # (Lucy 1/2, the mini) can still commit.
    r = _git("-c", "user.name=Alphalete Runner",
             "-c", "user.email=alphaletereporting@gmail.com",
             "commit", "-m", msg)
    if r.returncode != 0:
        print(f"FAILED to commit:\n{r.stdout}\n{r.stderr}")
        return 1
    r = _git("pull", "--rebase", "--autostash", "origin", "main")
    if r.returncode != 0:
        print(f"FAILED to rebase onto origin/main:\n{r.stdout}\n{r.stderr}\n"
              "The commit exists locally — resolve and push by hand.")
        return 1
    r = _git("push", "origin", "main")
    if r.returncode != 0:
        print(f"FAILED to push:\n{r.stdout}\n{r.stderr}\n"
              "The commit exists locally — push by hand.")
        return 1
    head = _git("log", "--oneline", "-1").stdout.strip()
    print(f"✓ Committed + pushed: {head}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
