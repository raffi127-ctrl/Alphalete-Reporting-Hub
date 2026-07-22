# Applicant Tracker (ApplicantStream → Google Sheet)

Four recruiting reports built by **Francia** (2026-07-21). Each logs into
**ApplicantStream** (Playwright headless Chromium) and syncs into the
**Alphalete Org Applicant Tracker** Sheet. They run on **Lucy 2** (Carlos's
mini) and appear on the Hub as four cards under **🎯 Recruiting**.

| Module | Hub card | Reads | Writes | Scheduled |
|---|---|---|---|---|
| `export_call_list` | Export Call List → Call List tab | Retention → **yesterday** → "Sent to Call List" | Call List tab: owner **A**, data **B–H** | 7:00am CST Mon–Sat |
| `update_second_round` | Update Second-Round Status (2R) | Retention → **yesterday** → 2nd-round lists + calendar | 2R tab: Offered **H**, Follow-up **I**, Notes **J** | 7:00am CST Mon–Sat |
| `export_2r_retention` | Export 2R Retention → 2R tab | Retention → **today** → "Total Second Interviews" | 2R tab: owner **AT**, 9 cols **AU–BC** | 8:00pm CST Mon–Sat |
| `confirm_first_day` | Confirm First-Day Training Show-Up | Retention → **today** → Total Training / Showed Up | 2R tab: col **R** = Y/N | ⚠️ NOT live yet (dry-run only) |

## Run it

```bash
# from the repo root, on any machine that has the login + key:
.venv/bin/python -m automations.applicant_tracker.export_call_list            # LIVE (writes)
.venv/bin/python -m automations.applicant_tracker.export_call_list --dry-run  # writes NOTHING
.venv/bin/python -m automations.applicant_tracker.export_call_list --office 11280 --dry-run  # one office
```

`--dry-run` exercises the whole report (login + scrape) and prints what it
*would* write. `--office ID` (repeatable) limits the run. `--date YYYY-MM-DD`
overrides the target day.

The Hub cards route "play" to Lucy 2 automatically (`run_machine: "Lucy 2"`).
The **Preview** button = `--dry-run`; **Run live** = a real write.

## One-time setup on Lucy 2

1. **Google service-account key** — drop it at the repo root as
   `applicant-tracker-service-account.json` (gitignored; the repo is public so
   it is **never** committed). The sheet is already shared with
   `applicants@applicants-503123.iam.gserviceaccount.com`.
2. **Playwright + Chromium** (vanilla `playwright`, not patchright):
   ```bash
   .venv/bin/pip install playwright gspread google-auth python-dotenv
   .venv/bin/python -m playwright install chromium
   ```
3. **One-time headed ApplicantStream login** (clears Cloudflare, saves the
   session to `.browser_profile/` in this package):
   ```bash
   HEADLESS=0 .venv/bin/python -m automations.applicant_tracker.applicantstream
   ```
   Log in if prompted (creds live in the sheet's README tab B1/B2). Close the
   Inspector to exit. Every scheduled run reuses that session headlessly.
4. **Install the LaunchAgents** (from the laptop, routes to Lucy 2):
   ```bash
   lucy rerun install_applicant_am_agent --machine "Lucy 2"   # 7:00am job
   lucy rerun install_applicant_pm_agent --machine "Lucy 2"   # 8:00pm job
   ```

## Still to verify (do NOT tick "ran clean" until done)

- **`confirm_first_day`** — the build day had **zero** first-day-training rows,
  so the "Total Training" / "Training Showed Up" detail pages were never seen
  with data. Confirm on a real training day, and confirm "First Day of
  Training" maps to the **"Total Training"** row (not "Total New Starts
  Scheduled"). It is **dry-run only** and its live agent is **not** in the pm
  plist until then.
- **Login form selectors** — the `login()` field selectors were never exercised
  (the original session was already active). Rare (saved session), but confirm
  on the first headed login.
- **Office list** — one id was ambiguous in the source doc (22151 vs 21151).
  Confirm the 17-office list in `config.py` is current.

Full architecture notes are at the top of `applicantstream.py`.

## Cross-platform / Python 3.9

Lucy 2 (and the mini) run **Python 3.9**. Every module starts with
`from __future__ import annotations` so the `X | None` type hints stay lazy and
don't crash at import — do not remove it.
