# Manager Template — Recruiting Reporting for a New Org

Template workbook (File → Make a copy):
https://docs.google.com/spreadsheets/d/10dcDOSbD3XsudcqZezSvsYDpIuZa6mB_DgaGi5XZzIQ/edit

Created 2026-09-21 (Carlos). It is a stripped copy of the live Alphalete
Recruiting Dashboard: the five reporting tabs (Recruiting Dashboard, Goals,
Focus Report, Source Report - Indeed, Ad Plan), their hidden data stores
(Daily Log, WE, Indeed Ad Data, Campaign Log, Info Box, 0Config), all data
cleared, the bound Goal Sync script intact (it copies with the file), and a
"START HERE — Setup" tab carrying the same instructions as this document.

## If you are an AI agent doing this setup

This document and the template's "START HERE — Setup" tab are written to be
executed by a Claude session working for the new manager. Follow the steps in
order; each has a verify. Rules that are not optional:

- Never hand-write values into the built tabs (Recruiting Dashboard, Focus
  Report, Source Report) — the scheduled redraw wipes them. The only
  hand-edited surfaces are Goals, the violet goal column on Focus Report, and
  the violet Info Box answers (Focus rows 87–96).
- Picker cells are strict plain-text dropdowns: write them with
  `valueInputOption=RAW`, never USER_ENTERED (date-coercion kills them).
- Never delete, rename, or "clean up" hidden tabs.
- The bound Goal Sync script travels with every copy; its onEdit fires on
  HUMAN edits only — never design logic assuming an API write triggers it.
- AppStream owner spellings must match the office switcher byte-for-byte; a
  wrong name does not error, it silently mis-reports.
- Credentials never go in the repo (it is public) or in any sheet cell.
- The full incident-derived gotcha list is docs/RECRUITING-STACK-README.md §4
  — scan it before any change beyond these steps.

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

## Setup — on the manager's OWN device (no Alphalete runner involved)

This reporting runs entirely on the manager's machine: their AppStream login,
their workbook copy, their schedule. **It must never be wired to Alphalete's
production runner ("Lucy"), its command queue, or its schedules** — the kit
below doesn't know they exist, and the standalone env (`FUNNEL_NO_SLACK=1`)
keeps runs from posting into Alphalete channels.

1. **Copy the template** (File → Make a copy) into the manager's own Drive.
2. **Clone the repo on their machine** and create its venv
   (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`).
3. **Run the wizard** — it asks everything ("whose data do you want?" =
   managers + office ids + AppStream owner spellings, the workbook id, their
   AppStream login) and writes only local files:

       python -m automations.manager_kit.setup

   It stores the roster at `~/.config/recruiting-reporting/roster.json`, the
   login in the gitignored `ownerville-creds.json` (chmod 600), generates
   `./manager_run.sh`, verifies Google access to the workbook, and offers a
   launchd schedule on THAT Mac (1 AM + 1 PM, label
   `com.recruiting-reporting.daily`).
4. **First run**: `./manager_run.sh` — draws every tab with their roster
   (replacing the Manager 1..8 placeholders). Then once for history:
   `./manager_run.sh --weeks 34` (batch with `--only "A|B|C"` for many
   managers — a full 34-week pull for a big roster runs long).
5. **Ad Plan trackers**: per manager, a hidden tab with
   `=IMPORTRANGE("<tracker url>","A1:Z1000")`, one human "Allow access"
   click, and a row in `Ad Plan!AD:AE`.
6. **Goals**: type on Goals or the violet Focus column — the bundled script
   mirrors them (it copied with the template; human edits only).

How the isolation works under the hood: `FUNNEL_SSID` +
`INDEED_SOURCE_SPREADSHEET_ID` point the engine at their workbook,
`RECRUITING_ROSTER_JSON` replaces the production roster wholesale, and
`FUNNEL_NO_SLACK=1` mutes announcements. Unset, the same code serves
Alphalete production — so pulling repo updates keeps both worlds current.

## What bites (short list — full list in RECRUITING-STACK-README.md §4)

- Never delete/rename the hidden tabs; every visible tab reads them.
- Never hand-type into built tabs; the redraw eats it.
- Picker cells must stay plain-text formatted; Sheets coercing "July 2026"
  into a date is the classic silent killer.
- IMPORTRANGE needs one "Allow access" click per tracker per copy.
- The template ships with generic "Manager 1..8" placeholder rows — the
  first funnel run with YOUR roster replaces them everywhere.

Questions: Carlos Hidalgo — carloshidalgo349@gmail.com
