# Source Report - Indeed dashboard

One Google Sheet tab where you pick a **Manager** and a **Period** and see that
manager's Indeed ads for that month, merged to one row per real ad.

Workbook: the **Alphalete Org Applicant Tracker**
(`111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`), tab **Source Report - Indeed**.
The hidden **Indeed Ad Data** tab holds the rows and is the only thing this job
writes.

### That workbook has a hard cell ceiling — respect it

Google caps a spreadsheet at 10,000,000 cells and it cannot be raised. This
workbook hit **98.1%** on 2026-08-19 with only 193k cells free, while `2R`,
`Call List` and `Apps` append every day. It was brought back to ~59% by deleting
EMPTY trailing rows (no data touched) from tabs that had wildly over-allocated
grids — `2R` alone had 50,388 rows allocated against 7,446 used, and the two
Trend tabs 4,000 against ~115. Those tabs grow by COLUMNS, not rows.

Before adding anything wide here, check the headroom first. If it is tight again,
look for over-allocated grids before assuming the data itself is too big.

## What it does

Three times a day (4:00am, 12:00pm, 5:00pm) it re-pulls **the current month**
from AppStream's Source Report for every office in `offices.py`, rewrites those
rows on `DATA`, and recomputes each manager's YTD block. Earlier months are never
touched — a finished month stays frozen exactly as it was last pulled.

The current month always runs **1st → today**, so a partial month is expected.

## Running it

    bash deploy/indeed_source_report.sh                 # live
    bash deploy/indeed_source_report.sh --dry-run       # pull + report, write nothing
    python -m automations.indeed_source_report.run --office 11580
    python -m automations.indeed_source_report.run --month 2026-07   # backfill one month

Logs: `output/logs/indeed_source_report_YYYYMMDD.log`.

Schedule knob: `StartCalendarInterval` in
`deploy/com.alphalete.indeed-source-report.plist`, then
`python -m automations.day_orchestrator.install_agent indeed-source-report`.

## The two things that make this report wrong if you get them wrong

**1. One posting arrives as many rows.** Indeed splits a single ad by language
wording (`(Spanish Needed)`, `*Spanish Needed*`, `- Spanish Necessary -`), by a
`", N locations"` suffix, and by pay/level tails (`| Weekly Pay`). All of them
are folded together in `parse.py`; `# Variants` reports how many pieces merged.
The `", N locations"` case alone once split one ad into four rows across 1,303
applicants. Ads merge only within the same inbox **and** the same city, so two
offices running the same role stay separate.

**2. Column sets differ per office.** Some report a Training stage and
`First Day of Sales`; others only `Brought on Board`. `parse.py` resolves columns
by name with a fallback chain — never by position. Note Carlos Hidalgo's office
does not populate `First Day of Sales Booked` at all, so New Starts Booked comes
through as 0 there; that is the source, not a bug here.

A **blank City** on a detail row means a multi-location posting whose city could
not be determined (the account runs that role in 2+ cities and the wording did
not point at one). It is left alone rather than guessed, and the run prints it.

## Auth

- **AppStream**: `automations.shared.tableau_patchright.appstream_direct_session`
  — reuses the saved session, re-logs in unattended when stale.
- **Sheets**: prefers `~/.config/recruiting-report/oauth-token.json` (Carlos's
  identity, the workbook owner), falling back to the applicant_tracker service
  account. The fallback only works if the workbook has been shared with that
  service account, so on a machine without the token file, do that first.

## Offices

`offices.py` — 28 entries, resolved from AppStream's `#searchMC` picker
(which prints `officeId / Owner / Company`). Joshua Murphy holds two offices and
appears twice, disambiguated by company. **Salik Mallick is not in the list**: no
office matched that name under the `rcaptain` login as of 2026-08-19.

## Scale

28 offices x 3 months is ~4,000 rows on `DATA`, and one manager (Rafael
Hidalgo) alone has a 367-row YTD block. Two limits follow from that and both
have bitten already:

- The Dashboard's `A6` formula uses **open-ended** ranges (`DATA!$C$2:$U`).
  A capped range silently returns nothing for every manager whose rows fall past
  the cap — and `IFERROR` swallows it, so the tab just looks empty.
- The dashboard's formatted / colour-ruled / filtered area runs to **row 600**.
  A block taller than that would render past the formatting.

A full 28-office pass takes roughly 12 minutes and about 90 Sheets writes; the
Sheets API allows 60 writes per minute per user, so the run batches its writes
rather than one call per manager.

## Dashboard picker cells — date-coercion trap (fixed 2026-08-22)

The visible tab's period picker (`'Source Report - Indeed'!B2`) is a ONE_OF_RANGE dropdown over
text values like "July 2026". Sheets coerces that into a DATE on entry (UI pick or USER_ENTERED
write) unless the cell carries a plain-text (`@`) number format — and a coerced write also
*replaces* the `@` format, so the protection erodes. A date-valued B2 displays identically but
matches nothing in the data tab, so the dashboard silently blanks and both dropdowns look dead.

If the visible tab is ever rebuilt, reproduce all three layers:
1. `@` number format on B2:B3;
2. validation `strict: false` (a coerced pick must land, not bounce);
3. the A6 filter matches the period BOTH ways:
   `('Indeed Ad Data'!$B$2:$B=$B$2) + ('Indeed Ad Data'!$B$2:$B=IFERROR(TEXT($B$2,"mmmm yyyy"),""))`
   — works whether B2 holds text or a coerced date. (IFERROR guards "YTD (all months)", where
   TEXT() errors.)

The scheduled job writes only the hidden data tab; it cannot regress this.

Pickers moved to C2 (period) / C3 (manager) on 2026-08-22 — Carlos keeps column B hidden.
C1 is a Group dropdown (Org/Captainship): 'Indeed Ad Data' Y = org roster (17), Z = captainship
roster (13, incl. Carlos & Atef), AA = the active list spilled by a FILTER on C1, and the C3
manager validation points at AA2:AA40. The job clears only A2:U and rewrites W:X, so Y-AA are
safe; a from-scratch rebuild must recreate them (rosters come from funnel_board/roster.py).
