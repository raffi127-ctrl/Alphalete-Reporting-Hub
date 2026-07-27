# OAT Processing — "One App at a time" leftovers handler

Automates the manual queue the girls work by hand: applicants that
**resume_pushing couldn't auto-send** to the AI call list, which land in the
**classic** ApplicantStream surface under **Applicants → Process Emails → One
App at a time (OAT)**. From Carlos's Loom (2026-07-26), office **11580**, on
**Lucy 2**.

## The decision tree (per applicant)

First match wins. Encoded in [`classify.py`](classify.py); proven by
[`test_classify.py`](test_classify.py) (7/7 branches).

| # | Condition | Action |
|---|-----------|--------|
| 1 | No phone **and** no cell | **Flag no-phone** — parked branch (a human, or later the Octo→Indeed lookup, gets the number) |
| 2 | Interview scheduled in the **future** | **Remove** — don't re-text (they're already booked) |
| 3 | Already sent to the call list **today** (applied again via another ad) | **Remove for duplicate** — no text |
| 4 | Past interview / no-show, system **won't** let you override: | |
| 4a | &nbsp;&nbsp;last interview **> 1 week** ago | **Re-text then remove** — resend the Await Call Email template for the position they applied to, then remove for duplicate |
| 4b | &nbsp;&nbsp;last interview **≤ 1 week** ago | **Remove for duplicate** — too recent, no text |
| 5 | System offers **overwrite + Send to AI**, and **not** sent to the call list today | **Overwrite old applicant + send to AI** |
| 6 | Otherwise (fresh, sendable) | **Send to AI** |

Thresholds (config-overridable, from the Loom): reissue/duplicate window =
**30 days**, re-text cutoff = **1 week**. See [`config.py`](config.py).

## v1 scope

- **In:** every in-ATS branch above (send / override / remove / re-text).
- **Parked:** the no-phone lookup (Octo Browser → the source's Indeed employer
  account → search name → grab phone). No Octo/Indeed code exists in the repo
  and it drives multiple third-party logins Indeed actively blocks — highest
  breakage risk, so v1 just flags these to `output/oat-no-phone-queue.csv` for a
  human. Revisit as Phase 2.

## Safety model

This report **sends real texts/emails** and **removes records** — outward,
effectively irreversible. So:

- **Dry-run is the DEFAULT.** Plain `run` reads + classifies + prints the
  planned action for each applicant and **clicks nothing**.
- **`--live` is required to act**, and only after the dry-run output is
  confirmed correct by Megan/Carlos.
- `config.MAX_PER_RUN` (default 60) bounds how many a single run touches.

## Running

```bash
# 1. FIRST, on Lucy 2: land on the OAT page and dump its controls/labels so we
#    can finalize the selectors the reader/action helpers still need.
python -m automations.oat_processing.run --debug

# 2. Dry-run: read the queue, classify, print planned actions (no clicks).
python -m automations.oat_processing.run

# 3. Only after sign-off: act for real, small batch first.
python -m automations.oat_processing.run --live --limit 5
```

## Status / what's left

- ✅ Decision core (`classify.py`) + tests — complete.
- ✅ `config.py`, no-phone flagging, `run.py` orchestration + `--debug` health
  check — complete.
- ⏳ **Page selectors** — the reads (`read_current_applicant`,
  `advance_to_next`) and action clicks (`do_*`) in `run.py` are marked
  `# >>> VERIFY on Lucy 2`. They need one `--debug` pass (or screenshots) of the
  live classic OAT screen to capture: the action buttons below the fold
  (Send to AI / Remove-for-duplicate / the overwrite dialog), the
  "Interview Assigned" status line + date, and the **Await Call Email** position
  picker. See task #4.
- ⏳ **Lucy 2 launchd deploy** — wrapper + plist + `schedule_config.json` entry,
  modeled on `deploy/resume_pushing_10min.sh`. Wire only after sign-off; never
  runs `--live` before then. See task #5.

## Reuse

- Session + login + office switch: `automations.applicant_tracker.applicantstream`
  (classic ApplicantStream, `#searchMC` office picker, token capture). Office
  11580 is already in its `OFFICE_IDS`.
- Relationship to `automations/resume_pushing/`: that handles the **v2 batch**
  bulk send; this handles the **classic OAT** leftovers it couldn't send.
