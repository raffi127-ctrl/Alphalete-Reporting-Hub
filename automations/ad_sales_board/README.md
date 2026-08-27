# Ad Sales Board — day-by-day names per ad, dressed as a sales board

One tab on the **Alphalete Recruiting Dashboard**
(`111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`) that LOOKS like the AT&T
sales boards (Carlos's spec, 2026-08-26: "it needs to look like a sales
board... day by day i want to see how many names each ad is getting"): ads
down the side, the ad-week's seven days across, and each cell = how many
NAMES that ad produced that day. Weekly Pull (processed emails), the total
names, Account/City and the week's name list ride alongside.

* Visible tab **Ad Sales Board** — ONE STACKED SCROLL of every week for the
  picked manager, newest first (Carlos 2026-08-27: "no dropdown i just have to
  scroll down"): row 1 dark control strip (**B1 manager**, **D1
  Org/Captainship** — the only pickers), row 2 navy banner, row 3 a scroll
  hint, row 4 static navy header `# | Account | City | AD | Pull | Names |
  Mon..Sun`, rows 5+ one FILTER spill at A5. Every week block opens with a
  blue **WEEK ENDING m/d** band row (written into the data by the job), ads
  carry a per-week rank (#), TOTAL closes the block grey, amber row = names
  that matched no ad. Everything centered; the week name LIST stays on the
  data tab col J, deliberately not shown.
* Hidden tab **Ad Sales Data** — the only thing the job writes. Columns
  A..S: Manager, Week, Account, Inbox, Ad Title, City, Pull, To Call List,
  # Names, Names, Week Start (ISO — the freeze/sort key), L..R = names per
  day (Mon..Sun), S = the ad's rank in its week. Each block's first row is
  the WEEK ENDING band (marker text in the Ad Title column). TOTAL rows carry the label in the Ad Title column (the
  board's first visible column). Blank counts mean "no name feed" (the
  captainship-only offices); zeros mean "an ad that produced nobody".

## The week

**Monday → Sunday** (`weeks.py`) — Carlos's call the first evening ("weeks are
monday - sunday"), matching the fleet's WE convention; the original Wed→Tue cut
lived for a few hours and its rows were dropped with `run.py --reset` before
the year was re-pulled on Monday anchors. There is no week picker any more —
the board shows every week stacked, newest on top. The
week LABEL ("Aug 24 – 30, 2026") is the join key across runs; never change its
format OR anchor day without rewriting the data tab.

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
