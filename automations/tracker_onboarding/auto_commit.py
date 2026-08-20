"""Auto-commit confirmed tracker enrollments so they survive the morning pull.

The gap this closes: Megan's "Confirm + wire up" makes the mini apply the
enrollment into its WORKING TREE (posts start next morning), but the morning
orchestrator self-update resets uncommitted onboarded_trackers.json drift when
main has also moved that file — which can silently drop a confirmed office
from the run (the jamis lesson). Committing the enrollment to origin/main is
the durable state, and that has to happen from a machine with push access.

What it does (idempotent, safe to run any time):
  1. Reads the 'Tracker Onboarding' tab (WIRED rows only — apply.plan()
     hard-skips pending requests).
  2. apply --write regenerates automations/tableau_screenshots/
     onboarded_trackers.json.
  3. If — and only if — that ONE file changed, commits JUST it and pushes
     (pull --rebase --autostash first). Other sessions' work-in-progress in
     the tree is never staged.

Runs on LUCY 1 (always-on) as the com.alphalete.tracker-auto-commit
LaunchAgent, daily 03:15 + 17:30 — the laptop isn't reliably awake (Megan,
2026-08-20). Needs Google creds (~/.config/recruiting-report/oauth-token.json,
same file the poller uses) + git push access (one-time mini_control
`git_push_setup`). Also runs fine by hand from the laptop:
  .venv/bin/python -m automations.tracker_onboarding.auto_commit
Exit 0 = committed or nothing to do; 1 = blocked/failed (message says why).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from automations.tracker_onboarding import apply as A, store

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = "automations/tableau_screenshots/onboarded_trackers.json"


def _client():
    """gspread client from the laptop's oauth token (same fallback the form
    uses). Raises with a clear message if creds are missing."""
    import gspread
    from google.oauth2.credentials import Credentials

    tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
    if not tok.exists():
        raise RuntimeError(f"no Google creds at {tok} — run on Megan's laptop")
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
    try:
        store.set_client(_client())
    except Exception as e:                            # noqa: BLE001
        print(f"BLOCKED: {e}")
        return 1

    # Regenerate the committed registry from the Sheet (wired rows only).
    rc = A.main(["--write"])
    if rc != 0:
        print("BLOCKED: apply refused (validation problems above) — nothing "
              "committed.")
        return 1

    changed = _git("status", "--porcelain", "--", TARGET).stdout.strip()
    if not changed:
        print("No enrollment changes — everything confirmed is already "
              "committed. Nothing to do.")
        return 0

    diff = _git("diff", "--", TARGET).stdout
    print(f"--- {TARGET} changed ---\n{diff}\n---")

    _git("add", "--", TARGET)
    msg = ("tracker enrollments: auto-commit confirmed offices\n\n"
           "- regenerated from the Tracker Onboarding tab (wired rows only)\n"
           "- committed so the enrollment survives the mini's morning "
           "self-update\n\n"
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
