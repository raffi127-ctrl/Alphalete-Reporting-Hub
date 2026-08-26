# Ad Sales Board — the Source Report, week by week (pull + names)

One tab on the **Alphalete Recruiting Dashboard**
(`111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`) where you pick a **Manager**
and an **ad-week** and see, per real ad: the **Pull** (processed emails /
applicants) and the **Names** that came in. Built for the Wednesday-morning
look-back Carlos asked for (2026-08-26): "what happened last week, ad by ad,
and who did we get."

* Visible tab **Ad Sales Board** — pickers C1 (Org/Captainship), C2 (week),
  C3 (manager); one FILTER spill at A6; TOTAL is the last row of a block.
* Hidden tab **Ad Sales Data** — the only thing the job writes. Columns
  A..K: Manager, Week, Account, Inbox, Ad Title, City, Pull, To Call List,
  # Names, Names, Week Start (ISO — the freeze/sort key).

## The week

**Wednesday → Tuesday** (`weeks.py`). On Wednesday morning the just-finished
week is complete — not three days stale like a Sun–Sat week would be — and the
job flips the C2 picker to it. The week LABEL ("Aug 19 – 25, 2026") is the join
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
