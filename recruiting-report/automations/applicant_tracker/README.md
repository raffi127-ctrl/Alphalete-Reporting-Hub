# Applicant Tracker (ApplicantStream → Google Sheet)

Francia's four ApplicantStream reports, **consolidated into one module**
(`run.py`) with two phases that share a single login. Syncs the **Alphalete Org
Applicant Tracker** Sheet. Runs on **Lucy 1** as `rcaptain` (the recruiting
captain login, which sees all 17 owners' offices). One Hub card: **Applicant
Tracker Sync** (🎯 Recruiting).

| Phase | Reads | Does | Writes | When |
|---|---|---|---|---|
| **morning** | yesterday | Export Call List + Update 2R Status | Call List (A, B–H); 2R (H/I/J) | 4am orchestrator, Mon–Sat |
| **evening** | today | Export 2R Retention + Confirm First-Day | 2R (AT, AU–BC); 2R col R | 8pm launchd, Mon–Sat |

The Hub pill turns **orange** after the morning pass and **green** after the
evening pass (`daily_runs: 2`). **First-Day (col R) is dry** — computed and
logged but not written — until `FIRST_DAY_LIVE` is flipped, after it's verified
on a real first-day-of-training day.

## Run it

```bash
# from the repo root:
.venv/bin/python -m automations.applicant_tracker.run morning              # LIVE
.venv/bin/python -m automations.applicant_tracker.run evening --dry-run    # no writes
.venv/bin/python -m automations.applicant_tracker.run morning --office 11280 --dry-run
```
`--dry-run` writes nothing; `--office ID` (repeatable) limits offices; `--date
YYYY-MM-DD` overrides the target day.

Hub buttons route to Lucy 1 automatically: **Run morning phase** / **Run evening
phase** (live), plus dry-run variants under More actions.

## Efficiency

One ApplicantStream login per phase (not four). Each office is selected **once**
and its Retention report loaded **once** — all the detail-page links that phase
needs are collected from that single load (`detail_href` doesn't navigate), then
each is visited. That replaces the old reload-report-before-every-metric pattern.

## One-time setup on Lucy 1

1. **Google key** at repo root as `applicant-tracker-service-account.json`
   (gitignored; the repo is public). — *done via the `set_applicant_service_account`
   queue action.*
2. `.venv/bin/pip install playwright gspread google-auth` + `python -m playwright
   install chromium`. — *done.*
3. **One-time login** — the first live/dry run signs in as `rcaptain` (from the
   sheet's README tab B1/B2) and saves the session to `.browser_profile/`. The
   login drives the two-step ownerville form (username → NEXT → password), the
   same flow as `automations.shared.tableau_patchright`.

## Scheduling

- **Morning** rides the 4am orchestrator (`applicant_sync_morning`,
  `on_scheduler: true`) — no plist.
- **Evening** = `com.alphalete.applicant-evening` (8pm, `deploy/applicant_tracker.sh
  evening`). Install with `lucy rerun install_applicant_evening_agent`.

## Cross-platform / Python 3.9

Lucy 1 (and the mini) run **Python 3.9**. Every module starts with
`from __future__ import annotations` so the `X | None` hints don't crash at
import — do not remove it.
