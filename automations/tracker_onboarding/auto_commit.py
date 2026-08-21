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
  3. If — and only if — those registry files changed, commits JUST them and
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
TARGETS = [
    "automations/tableau_screenshots/onboarded_trackers.json",
    "automations/office_metrics/onboarded_offices.json",
    "automations/b2b_metrics/onboarded_offices.json",
    # apply pins owner -> OwnerVille account number here (knocks/Time Gaps
    # office resolution) — same durability need as the registries.
    "automations/recruiting_report/icd_office_mappings.json",
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


def main() -> int:
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
