# Manager Template — Recruiting Reporting for a New Org

Template workbook (File → Make a copy):
https://docs.google.com/spreadsheets/d/10dcDOSbD3XsudcqZezSvsYDpIuZa6mB_DgaGi5XZzIQ/edit

Created 2026-09-21 (Carlos). It is a stripped copy of the live Alphalete
Recruiting Dashboard: the five reporting tabs (Recruiting Dashboard, Goals,
Focus Report, Source Report - Indeed, Ad Plan), their hidden data stores
(Daily Log, WE, Indeed Ad Data, Campaign Log, Info Box, 0Config), all data
cleared, the bound Goal Sync script intact (it copies with the file), and a
"START HERE — Setup" tab carrying the same instructions as this document.

## The mental model

The spreadsheet is the DISPLAY. An automation (this repo) pulls
ApplicantStream nightly, stores history on the hidden Daily Log, and redraws
the visible tabs. Hand-edits to built tabs do not survive the redraw — the
only hand-edited surfaces are the Goals tab, the violet goal column on the
Focus Report (two-way mirrored by the bundled script), and the violet Info
Box answers.

## Prerequisites for a new org

1. An ApplicantStream login that can see every office to report
   (Retention Details + Source Report access).
2. Each manager's office id (AppStream office switcher: `newOfficeId=NNNNN`).
3. A machine that stays on to run the schedule (or Alphalete hosts it).
4. This repo (`raffi127-ctrl/Alphalete-Reporting-Hub`) + a Python venv.
5. Google credentials (service account or OAuth) with edit access to the copy.
6. For Ad Plan: each manager's personal Indeed tracker sheet link.

## Setup

1. **Copy the template**; note the new spreadsheet id from its URL.
2. **Point the code at it**: `automations/funnel_board/build.py` (SSID) and
   your roster in `automations/funnel_board/roster.py` — ORG = one tuple per
   manager: `(display name, office id, AppStream owner spelling)`. A blank
   office id ("") is legal: the nightly run watches the office switcher and
   starts pulling (with history + an announcement) the moment it appears.
3. **Share the copy** with the runner's Google account (editor).
4. **First funnel run**: `python -m automations.funnel_board.run` — pulls the
   offices, fills Daily Log, draws Dashboard/Focus/Goals/Matrix. Add
   `--weeks 34` once for deep history (run it in batches of ~8 managers via
   `--only "A|B|C"`; a full 40-office 34-week pull exceeds the 60-min cap).
5. **First source-report run**: `python -m automations.indeed_source_report.run`
   — fills Source Report - Indeed for the current month.
6. **Ad Plan**: per manager, add a hidden tab that IMPORTRANGEs their tracker
   (`A1:Z1000`), click the one-time "Allow access", then map them in
   `Ad Plan!AD:AE` (AD = name, AE = tab name). The dropdown updates itself.
7. **Goals**: type them on Goals or the violet Focus column — mirrored both
   ways automatically (simple onEdit; no trigger install needed).
8. **Schedule**: daily full run + midday refresh. Copy
   `deploy/recruiting_chain.sh` + the two `com.alphalete.recruiting-chain`
   plists as the starting point (Alphalete runs 1 AM full / 1 PM refresh).

## What bites (short list — full list in RECRUITING-STACK-README.md §4)

- Never delete/rename the hidden tabs; every visible tab reads them.
- Never hand-type into built tabs; the redraw eats it.
- Picker cells must stay plain-text formatted; Sheets coercing "July 2026"
  into a date is the classic silent killer.
- IMPORTRANGE needs one "Allow access" click per tracker per copy.
- The template still shows Alphalete's manager names as placeholders — the
  first funnel run with YOUR roster replaces all of them.

Questions: Carlos Hidalgo — carloshidalgo349@gmail.com
