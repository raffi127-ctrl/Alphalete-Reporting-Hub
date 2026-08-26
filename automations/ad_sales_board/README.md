# Ad Sales Board — day-by-day names per ad, dressed as a sales board

One tab on the **Alphalete Recruiting Dashboard**
(`111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`) that LOOKS like the AT&T
sales boards (Carlos's spec, 2026-08-26: "it needs to look like a sales
board... day by day i want to see how many names each ad is getting"): ads
down the side, the ad-week's seven days across, and each cell = how many
NAMES that ad produced that day. Weekly Pull (processed emails), the total
names, Account/City and the week's name list ride alongside.

* Visible tab **Ad Sales Board** — layout lifted from the live Sales Board
  mirror: row 1 dark control strip (**B1 manager**, **D1 Org/Captainship**),
  row 2 navy AD SALES BOARD banner, row 3 blue WE strip (**B3 week picker**
  in the cream cell + computed week label), row 4 navy bordered header
  `# | AD | Pull | Names | Wed..Tue | Account | City` with real dates, rows 5+
  the bordered grid spilled by one FILTER at B5 — everything centered, banner
  merged across the board. The week name LIST is deliberately not shown
  (Carlos 2026-08-26: "i dont need all the names on the right") — it stays on
  the data tab, col J. TOTAL row grey; amber row = names that matched no ad.
  Day headers compute their dates from the picked week via the data tab's AB1
  helper.
* Hidden tab **Ad Sales Data** — the only thing the job writes. Columns
  A..R: Manager, Week, Account, Inbox, Ad Title, City, Pull, To Call List,
  # Names, Names, Week Start (ISO — the freeze/sort key), then L..R = names
  per day (Wed..Tue). TOTAL rows carry the label in the Ad Title column (the
  board's first visible column). Blank counts mean "no name feed" (the
  captainship-only offices); zeros mean "an ad that produced nobody".

## The week

**Wednesday → Tuesday** (`weeks.py`). On Wednesday morning the just-finished
week is complete — not three days stale like a Sun–Sat week would be — and the
job flips the B3 picker to it. The week LABEL ("Aug 19 – 25, 2026") is the join
key across runs; never change its format without rewriting the data tab.

## Where the numbers come from

* **Pull** — AppStream Source Report (p=702) run per office for the week's
  date range, through the SAME fetch/parse as the monthly Source Report -
  Indeed job (variant merge, junk filter, city rule, Carlos/Jamis city-agnostic
  merge — `CITY_AGNOSTIC` is imported from that job, one list, never two).
* **Names** — the old org tracker's **Call List** tab (applicant_tracker's
  morning import), matched to merged ad rows by base role + city. Honest
  limits, also stated on the tab: org offices only (the 11 captainship-only
  offices have no name feed — Pull fills, Names stay blank); names are the
  sent-to-call-list applicants, so Pull normally exceeds the name count;
  SATURDAY arrivals are never imported upstream (the morning phase reads
  yesterday and skips Sunday); a name can land a day after the email its Pull
  counted (edge-of-week skew). Names that match no ad row land on an amber
  "(names with no matching ad row)" line rather than disappearing.

## The wrapper subjects (found building this, 2026-08-26)

Some real applications arrive as **"[Action required] New application for
<ad title>"**. `parse.NOISE` matches "action required" (meant for Indeed's
billing mail) and throws those rows away. This job strips the wrapper BEFORE
parsing (`names.WRAPPER`), keeps the applicants, and prints how many it kept —
**the monthly Source Report - Indeed tab still junk-filters them**, so its
Applicants column undercounts by that much (37 of Carlos's 375 call-list names
in the 8/19 week wore the wrapper). Fixing the monthly parser is a deliberate,
separate decision because it shifts current-month numbers upward.

## Running it

    python -m automations.ad_sales_board.run              # current + previous ad-week
    python -m automations.ad_sales_board.run --dry-run    # pull + report, write nothing
    python -m automations.ad_sales_board.run --weeks 4    # backfill: current + 3 back
    python -m automations.ad_sales_board.run --anchor 08-12-2026
    python -m automations.ad_sales_board.run --office 11580

Freeze rule: a run rewrites ONLY the (manager, week) pairs it pulled; weeks
that fall out of the default two-week horizon stay frozen exactly as last
written, same philosophy as the monthly job's months.

## Schedule

Lucy 2, **daily 7:50am** (`deploy/com.alphalete.ad-sales-board.plist`,
installed via `lucy rerun install_ad_sales_board_agent`). 7:50 is deliberate:
applicant_tracker's morning phase (Lucy 1, 6:45am Mon–Sat) must land
yesterday's call-list names first, and the 4am AppStream cluster is long done.
A full 28-office × 2-week pass is ~25 minutes.

## One-time setup

`build_tab.py` creates/dresses both tabs (idempotent; `--force-view` redresses
the visible one). The scheduled job never rebuilds layout — if the tabs are
missing it aborts at the preflight probe with instructions.

## Auth

Same chain as indeed_source_report (its sheet module is imported directly):
applicant_tracker service account first, Carlos's OAuth token as fallback. The
Call List read uses the same session — the service account writes that tab
daily, so it can always read it.
