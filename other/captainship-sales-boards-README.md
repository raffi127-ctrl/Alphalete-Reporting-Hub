# Captainship Sales Boards — System README


_ENTRY POINT for new chats: read ~/Desktop/CAPTAINSHIP-MASTER-README.md FIRST — it consolidates this file, the Vantura doc and the session history (8/25)._

> **⚠️ 2026-09-07 — THE CAPTAINSHIP DASHBOARD (14_T4fySy…) IS IN THE DRIVE
> TRASH** (permanent deletion after ~30 days). Trashed Sheets still answer
> the API, so `captainship_boards` keeps filling its hidden MT tabs every
> morning without erroring — but Carlos is retiring the workbook. The org
> **Alphalete Recruiting Dashboard's Focus Report** is the captainship's
> sales-metrics home now: since 9/7 `automations/org_campaign_metrics`
> COMPUTES every owner's b2b block from the order log + tracker crosstabs
> (no MT-tab copy). Next step (not yet done): stop `captainship_boards`
> writing the MT tabs / master — mind that the 11 owner boards' Focus
> Report glass tabs still IMPORTRANGE off this workbook, and they break the
> day it is permanently deleted.
_Last updated: 2026-08-22. Maintained by Claude for Carlos. If you are Claude
reading this after a context reset: this file is the source of truth for the
owner-board project. Read it fully before touching any of these sheets.
Companion scripts live in `scripts/` next to this file._

## What this is

A fleet of AT&T-B2B-only sales boards — one **template**, **11 owner copies**,
and one **Captain Master Mirror** — filled from the Tableau **order log by
date** (NOT Slack parsing, NOT Sara, NOT any office workbook). Built so it can
be handed to owners outside the org: everything the automation needs comes from
the order-log export alone. Managers still hand-edit some things (attendance,
statuses, stations), which is why the mirror imports from the owner sheets
rather than being rebuilt from the order log (Carlos's explicit decision).

## The sheets

| Sheet | ID |
|---|---|
| **TEMPLATE** (blank, master copy) | `1L85fRMTkVhpBqglsrjqrmktn42Nc9xZudyczXG17NdA` |
| **Captain Master Mirror** | `14_T4fySyQhRPsyWZLGEs6Sarc0jyJ4oD-gV8E97WZU8` |
| Jackie LeRoy - Sales Board | `1gK_QL06yPzHdSh6cNbaQ9lp7qSofoneti3kWxOgdf8I` |
| Justin Wood - Sales Board | `1TJpMQWJXnunqs3yrL_LV0-JZrjZEsGKtVzu5skGue6s` |
| Joshua Murphy - Sales Board | `1VZEEpW--Us6_4UHhBJX8fYhY44Wu6CtJ3AdFtppZccc` |
| Jamis Garay - Sales Board | `1wDWeiS0IuzwsYFGF-s6mA6by8CtBtI5eOEnNmahBd6s` |
| Dhyey Patel - Sales Board | `1-gJfYtz8teNIMpYpMPVk5bBqomZWqu5yRfUGTfjqTlQ` |
| Jeff Starr - Sales Board | `1CmUEyC_rwidScsLeuE1WywKUvqHE7avtytFLQgzD1pU` |
| Kinsey Guenther - Sales Board | `1MxORzw6WFGxSXCuJf1hVok68eMOvRX02T9fhauVDFq0` |
| George Hipolito - Sales Board | `1XtKmB-C_hXFgBKyyBWbW9h8fG5riVXAM5ckaOClxQAs` |
| Atef Choudhury - Sales Board | `1PZwxUYDodOJ6LkxGrgB5ytDi0Fbd4h-mZJdM5q4ADnU` |
| Joey Ramirez - Sales Board | `1n2d5vDiwwj6d3bFBIe5OcuEWEEc1OFn2Hp28wuaSFOY` |
| Vincent Smith - Sales Board | `1LOi7JPQ8j0qlbe3PvgZumaHuWCd2HKLNYDRGZOBxrnE` |

Source of everything: Vantura Master Sales Board
`1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY` (Carlos's own live board — the
original the template was distilled from; never write to it from this project).

Chrome: bookmarks-bar folder **"Captainship Sales Boards"** (Default profile,
carloshidalgo349) holds all 12 links. Editing Chrome bookmarks requires Chrome
fully quit; relaunch with `open -a "Google Chrome" --args --restore-last-session`.

## Template architecture (identical in every owner copy)

Tabs: **Setup / Sales Board / Roll Call / Stations / Daily Update** + hidden
**WeekData** + hidden **RollCallData**. Single campaign: campaign dropdowns
exist everywhere but "AT&T B2B" is the only option (Carlos's requirement —
format matches multi-campaign boards without the clutter).

- **Setup** — gold cells (office, owner), Teams / Leaders-Trainers / Recruiters
  lists that feed every dropdown via ONE_OF_RANGE (`Setup!$A$9:$A$28`,
  `$B$9:$B$28`, `$C$9:$C$28`), HOW IT WORKS instructions, and a CURRENT REPS
  one-time roster table (rows 44–83) whose column order (Trainer / Field
  Status / Team / Leadership) pastes straight into Sales Board M:P.
- **Sales Board** — headers **row 3** (day name + date, two lines via CHAR(10),
  auto-dated from the week picker), reps **rows 4–43**, TOTAL **row 44**,
  analytics rows 46–50 (% on board), Headcount K46:P47, Averages K49:P50,
  Team table B53:E61 (pulls team names from Setup), legend row 63.
  - The gold **B2** is a TEXT-formatted dropdown (ONE_OF_RANGE
    `WeekData!$J$2:$J$40`). Day cells E4:K43 are
    `INDEX/MATCH(WeekData, $B<row>&"|"&$B$2)` lookups; Last Wk col D sums the
    `TEXT($R$2-7,"m.d")` week. Hidden col **R**: R2 = date anchor parsed from
    B2, R4:R43 = Term? flag (`COUNTIF(row,"T")>0`).
  - Basic **filter** on A3:P43 (TOTAL row deliberately outside).
  - Day-cell meanings: number = sales, 0 = worked no sale, X = didn't work,
    T = terminated, F = floater/manager. CF colors all of these.
- **Roll Call** — header row 2, data rows 3–202 (Week Ending / Status /
  Campaign / Rep Name / 2nd Rounder / Trainer / Mon–Sat / Date Gone / Days
  Lasted / Reason Lost). Columns E:F are grouped (+/− above D). **H1** is the
  "View wk ▶" week dropdown; G3:L202 are lookups against **RollCallData**
  (key `Rep|WE`, cols B–G = Mon–Sat). Managers picking an attendance value
  type over the formula for the live week — the daily automation is expected
  to upsert typed marks into RollCallData and eventually restore formulas.
  Snapshot panel Q2:R6 (active / new starts / lost 7d / terminated).
- **Stations** — legend chips row 3, section bands row 4, headers row 5,
  **grid rows 6–25** (20 deep, capacity 60 names in the rep pool). Car Rides
  A:F, Rep Pools G:J (G6 = `WRAPCOLS(FILTER(Sales Board roster), 20)`;
  J6 = FILTER of Roll Call New Starts), Stations K:P. Red CF = name placed
  twice; green/yellow CF on territory status.
- **Daily Update** — 26-col recruiting pipeline, exact clone of Vantura's
  "New DU": statuses `1 - Orientation Scheduled` … `5 - Leader`, checkbox
  cols W–Z, solid **black** grid borders, six column groups
  (B:E, G:H collapsed · J:K open · M:Q, S collapsed · U:Z open), frozen
  **0 rows / 9 cols** (matches master exactly).
- Everything is center-aligned (Carlos asked) except instruction paragraphs
  and legends.

## The order-log fill (THE core recipe)

- Export: `https://us-east-1.online.tableau.com/t/sci/views/ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes&Start%20Date=YYYY-MM-DD&End%20Date=YYYY-MM-DD`
- Auth from this mini: `automations.shared.tableau_patchright.tableau_session`
  (repo `~/recruiting-report`, venv `.venv/bin/python`) — ownerville
  storage_state → Tableau SSO, then `page.context.request.get(url)`.
  If the state is stale, self-heal needs **headless=False** and
  `_CLOUDFLARE_WAIT_MS = 35_000` (headless form login fails). Once healed,
  subsequent runs reuse the session headlessly.
- Parse: `automations.att_order_log.clean.load_rows(path, owner_prefix=...)`
  — handles the 4-rows-per-line measure pivot and merged headers.
  Slice per owner by `Owner & Office` first line (uppercase person name).
- **Counting rule** (⚠️ CHANGED 2026-09-07, Carlos — tracker parity): rep's
  day count = **SUM of `Unit Count` over rows with `sp.Order Date (copy)` =
  that date**, but ONLY `config.COUNTED_PRODUCTS` (NEW INTERNET + WIRELESS +
  AIR/AWB — what the D2D1 tracker counts). VOICE / TABLET-WEARABLE / VIDEO /
  UPGRADE INTERNET rows no longer count (no day-cell units, no seller credit,
  no rank weight, no auto Here mark); VoIP Line Count still sums every row.
  The original all-products rule had been verified 1:1 vs the Sara-finalized
  board — board numbers now deliberately run below Sara's when non-counted
  products sell. Board history before 9/8 keeps the old counting.
- Names: use the log's **legal names as-is** (Carlos's decision — no alias
  table for outside owners). One mapping to know: "Jeff Starr" appears as
  **JEFFREY STARR**. On Carlos's OWN board reconciliation, the master's hidden
  `Name Aliases` tab + nickname prefix matching (will~william) was needed.
- The tracker lags ~a day: "today" usually has no rows yet; a daily job should
  stamp **yesterday**.
- Filling a board = write rep-week rows into **WeekData** (`Rep|WE` key,
  Mon–Sun in B:H, week label appended to J list) and Here-marks into
  **RollCallData** — never the visible grid (the grid is lookups).
  Week labels are `m.d` text ("8.23"); write RAW (never USER_ENTERED — date
  coercion) and keep cells TEXT-formatted.

## Captain Master Mirror

Option-1 IMPORTRANGE design (Carlos rejected building it from the order log —
manager hand-edits must show). All Allow-access grants are DONE (11 sources).

- Tabs Sales Board / Roll Call / Stations / Daily Update / Setup; each has an
  **owner dropdown in B1** (from hidden `Mirror Config` A2:B12 name↔id map);
  each tab's owner selection is independent.
- Stations / Daily Update / Setup: one whole-tab IMPORTRANGE at A2 (everything
  sits +1 row vs the source), painted bands + cloned CF on top.
- **Sales Board & Roll Call are computed views** so their week dropdowns work:
  hidden `SRC WD` / `SRC RCD` tabs import the selected owner's WeekData /
  RollCallData; SB gold picker at **B3**, RC picker at **H2**; day/attendance
  cells are local lookups. Sectional imports: SB col A (A2), roster
  `Sales Board!B3:B45` at B4 (**must stop at B45 — importing B3:B70 collides
  with the analytics import in col B**), attrs `L3:P45` at L4, analytics
  `B46:P64` at B47 (values → reflects the OWNER's selected week, not the
  mirror picker — accepted trade-off). RC: `A1:F210` at A2, `M1:O210` at M2,
  snapshot `Q2:R6` at Q3.
- Has its own SB filter (A4:P44), Stations/DU borders, 56+ cloned CF rules
  (rows shifted +1; regex bump guarded so "B2B" isn't mangled).
- Read-only by design — edits belong in owner sheets (bar note says so).

## Manager Trend + Goals tabs (added 8/22)

Every board (template + 11 + mirror) has two more tabs:

- **Goals** — one manager's weekly recruiting targets. The NINE amber cells are
  typed (Sent to Call List, Removal %, Retention to Call List, 1st Show %,
  2nd Booked %, 2nd Show %, Offer %, BOB Conversion, New Start Show %); grey
  cells derive exactly like the org Goals tab (Applies = Sent/(1−Removal%),
  1st Booked = Sent × Retention, chain continues; NS Scheduled = BOB). Seeded
  from the org tracker's Goals captainship rows. Trend's GOAL column reads this
  tab live, and the goals drive the trend colors.
- **Manager Trend** — the office's weekly funnel, FULL history (34 weeks,
  back to WE 1/4, newest first; WK total + Mon–Sun in collapsible column
  groups), rows 4–27 in the exact org layout (SOURCING / FIRST ROUND /
  SECOND ROUND / OFFER / NEW STARTS). Styled to match the org original:
  Inter + Roboto Mono, ink #0B1220 header, section band colors
  475569/0F766E/1D4ED8/7E22CE/B45309, GOAL + weekend cols #F1F5F9, row-line
  borders, gridlines hidden, pastel CF chips D6F5DF/FDF0C8/FBDDDD with dark
  chip text, date strip in row 2 (serials, m/d), org color-key block rows
  30–38. Rebuild everything with `scripts/rebuild_trend_full.py`.
  **Static values** (Carlos: independent numbers, NOT mirrored) painted from
  the org tracker's Daily Log. Colors: only the nine goal metrics — within 5%
  of goal green, 5–10% yellow, >10% red, beating goal green, **Removal %
  inverted**; counts other than Sent to CL stay uncolored (org convention).

**Data source — Alphalete Org Applicant Tracker**
`1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo` (shared, owned by
everforwardmanagement). Its own "FUNNEL BOARD README" tab is the manual. THE
GOLDEN RULE: the funnel tabs there are automation-owned (Lucy 1, hourly) —
never write to them; **`Daily Log` is the single source of truth** (one row
per manager per day; A date-serial, C manager, E Applies, F Sent, G Removed,
H Processed, I Ret Booked, J 1st Booked, K 1st Showed, L 2nd Booked,
M 2nd Showed, N Offered, O BOB, P NS Sched, Q NS Showed). Read it directly —
no dropdown flipping needed. **Removal % = Removed / Processed** (NOT /Applies
— verified vs org; also the org trend's own GOAL VLOOKUP for Removal % points
at the Retention column, a bug we did not replicate). Rates: Retention =
Ret Booked/Sent; Show/conversion rates = stage/prior stage. Verified 19/19
metrics vs the org's Captainship Manager Trend for Jackie WK 8/23.

**Campaign block (8/22 pm):** Manager Trend rows 28-29 blank, row 30 band
"AT&T B2B — CAMPAIGN", rows 31-46 campaign metrics under the same week
columns (values land in WK columns; day cols unused): Headcount ✎ ·
Leaders in Training ✎ (✎ = manual entry, amber label) · Active Headcount on
Tableau · Total Apps · Rank on the Tracker · Sales per Rep · New Internet /
CRU Internet / Wireless / AIR-AWB Sales · CRU % · BYOD / CRU BYOD / IRU BYOD
Sales · Activation Rate (31-60 Day) · 0-30 Day Churn Rate. Screenshot areas
reserved: row 48 band "B2B AT&T METRICS — SCREENSHOT" (rows 49-64) and row 66
band "FOUR-WEEK AVERAGE — SCREENSHOT" (rows 67-82); color key relocated to
rows 84-92. Structure only — data wiring TBD with Carlos (candidates: Total
Apps/product splits from the ORDERLOG export by product type; activation +
churn from ATTTRACKER-B2B CHURNRATES/ACTIVATIONRATES views, cf.
`automations/b2b_metrics`; rank from the tracker; screenshots via the same
b2b_metrics capture pipeline). Script: `scripts/campaign_block.py`.

Mirror has a 'Manager Trend' tab (owner dropdown B1, import at A2, +1 row,
same CF against the imported GOAL column). The daily automation should refresh
Manager Trend values on all 11 from Daily Log (same loop as the sales stamp).

## Campaign metrics — sourcing map (researched 8/22, repo ~/recruiting-report)

Two existing engines cover most of the block. Everything B2B runs on **Lucy 2**
(the ATTTRACKER-B2B custom views carry Carlos's Tableau identity).

- **OPT metric engine** `automations/recruiting_report/opt_phase_carlos.py` —
  already writes per-owner numbers to Focus-Report tabs (Mondays,
  `carlos_focus`). Source: one crosstab `ATTTRACKER-B2B/D2D1-PAGERV3` custom
  view **ALLTEAMS**, worksheet "ICD Summary - ATT (V2) (TW)", keyed
  `ICD Owner Name`, current-week only (no week filter — hardwired).
  Row-by-row map: `resources/opt-section/carlos-tableau-source-map.md`.
- **Image/thread engine** `automations/b2b_metrics/` — 11 Slack items per
  office daily; the per-owner **B2B AT&T Sales Metrics screenshot** is item
  `sales_metrics` (`B2BATTSalesMetrics` view, `?Owner Name=` slice).

Per metric (campaign block rows 31-46):
| Metric | Exists? | Source |
|---|---|---|
| Headcount / Leaders in Training | manual (Carlos's call) | — |
| Active Headcount on Tableau | YES | ALLTEAMS col `Rep Count` (opt_phase_carlos.py:178). ⚠️ = reps who PRODUCED that week, NOT roster (icd_sales_board/campaigns.py:280) |
| Total Apps | YES | sum of NI+Voice+Wireless+AIR cols (opt_phase_carlos.py:437) — or our own ORDERLOG Unit Count |
| Rank on the Tracker | YES (numeric) | ALLTEAMS col `Ranking` (:186). Tiered-bonus rank is image-only |
| Sales per Rep | derived | Total Apps ÷ Rep Count (:439); per-owner `Sales / Rep` col exists but only read at Grand Total — easy win |
| New Internet / Wireless / AIR-AWB | YES | ALLTEAMS cols (:179-182) |
| CRU Internet + CRU % + BYOD splits | **GAP** | ingredients: ORDERLOG cols `CRU/IRU` + `Wireless Installment Plan` (=="BYOD"; vantura_churn/compute.py:46,213) or SALESSUMMARY un-summed CRU/IRU cols (shared/b2b_sales_summary.py:73-78 — currently sums the split away; needs canvas click EXPAND_XY to get rep level) |
| Activation 31-60 | YES | ACTIVATIONRATES "Activation Office" col `31-60 Days` (:214-237); richer: vantura_churn/activation_rates.py (0-30 rebuilt by summing num/den, never averaging rates; week filter MUST stay off or the 31-60 col vanishes) |
| 0-30 Churn | YES | CHURNRATES ALLTEAMCHURN "ICD Churn" col `0-30 Day` (:238-268); per-product per-rep via att_order_log/churn_run.py |
| B2B metrics screenshot | YES | b2b_metrics `sales_metrics` image (daily, per owner) or att_order_log/metrics_shot.py (manual) |
| 4-week average screenshot | **GAP** (sales) | exists only for Rep Count: carlos_captainship_headcount (4 newest week cols, Sheets PDF→PNG via image_export.py — that PDF→PNG pipeline is reusable) |

Three real gaps, all computable from data already pulled daily: **CRU %**,
**BYOD/CRU BYOD/IRU BYOD counts**, **sales-side 4-week average**. Note
'Updated Wireless Type' does NOT exist in the export — BYOD lives in
`Wireless Installment Plan`.

**Carlos's sourcing decisions (8/22 pm):**
- **Total Apps = OUR order-log count** (same rule as the sales board), NOT the
  tracker's component sum — the tracker's per-manager weekly total serves as a
  cross-check only (they should match; flag if not).
- **Sales per Rep** = read from the tracker per owner (the ALLTEAMS crosstab's
  per-owner `Sales / Rep` column — currently only read at Grand Total by
  opt_phase_carlos; flip `is_global` off / add a second ViewMetric).
- **Two national rows added below churn (rows 47-48): "National AVG
  Headcount" (0.0 fmt) + "National Sales per Rep" (0.00 fmt)** on all boards +
  mirror (screenshot bands now rows 50 & 68, key 86-94; mirror import extends
  to row 94). National Sales per Rep = the ALLTEAMS **Grand Total** row's
  `Sales / Rep` (exactly what opt_phase_carlos row-40 "National AVG Apps"
  reads, `is_global=True`). National AVG Headcount = Grand Total `Rep Count`
  ÷ number of owner rows in the crosstab (no existing report reads it, but
  same crosstab, trivial).
- **B2B metrics screenshot** = the daily `b2b_metrics` item `sales_metrics`
  (the one posted to Slack) — approved, reuse as-is.
- **4-week average screenshot** = the SAME B2BATTSalesMetrics view with (a)
  the week-ending filter multi-pinned to the last 4 weeks — proven pattern:
  `out_of_bounds` pins 3 weeks via URL (`offices.py` VIEW_META week_filter /
  week_count, render-verified) — and (b) the view's Totals/Averages control
  set to **Averages**: if it's a Tableau parameter it's URL-settable
  (`&Param=Average`); if it's an in-viz radio, use an after_load click hook
  (pattern: b2b_quality.apply_sort, b2b_sales_summary EXPAND_XY canvas click).
  Needs one live probe of the view to learn the exact field/param names —
  run it on Lucy 2 (or the mini with Carlos's session).

### Campaign block — data state (8/22 evening)

FILLED on all 11 owner boards: order-log rows (Total Apps 34, product splits
37-44 incl CRU% 41) for weeks 8.2/8.9/8.16/8.23 from `orderlog_4wk.csv`
(definitions: NI/WL/AIR from `Product Type (Broken Out)`; CRU% = CRU/(CRU+IRU);
BYOD = `Wireless Installment Plan`=="BYOD"). Tableau rows (33 Active Headcount,
35 Rank, 36 Sales per Rep, 45 Activation 31-60, 46 0-30 Churn, 47/48 national)
filled for the CURRENT week only — those views are current-snapshot (D2D1
ALLTEAMS has no week filter; activation/churn are cohort views). Pulled from
the mini via `opt_phase_carlos.download_view_crosstab` + `VIEWS` configs
(scripts `fill_campaign_orderlog.py` / `fill_campaign_tableau.py`).
Cross-check result: per-product counts match the tracker ±1-2 (timing); the
tracker's visible columns omit VOICE/VIDEO, so its 3-column sum runs below our
all-products Total Apps — ours is the sales-board rule, keep it. BONUS: this
ALLTEAMS crosstab exposes `CRU %` and `IRU BYOD%` columns directly (extra
cross-check sources), and lacks Voice/totals columns (drifted from what
opt_phase_carlos row-34 expects). National 8/22: Sales/Rep 6.4, AVG headcount
11.3 (833 reps / 74 owners). **Rolling semantics (Carlos 8/22 pm): row 33 Active HC day cells = CUMULATIVE
distinct sellers Monday→that day (week-to-date, like the tracker); row 36
Sales/Rep day cells = cumulative apps ÷ cumulative sellers. WK cells = full-week
values; current week's WK cells hold the tracker readings. Number formats rows
36/48 = 0.0 (no trailing zero). CRU% (row 41, ours = CRU/(CRU+IRU) all lines)
runs within ~0-2pts of the tracker's own CRU % column for most owners (Joey/
Vincent ~4-6pts off — denominator definition likely differs; unresolved).
Aggregation cache: scratchpad campaign_cache.json (owner→date→apps+sellers).**
STILL EMPTY: Headcount+Leaders (manual), history
for Tableau rows (views are current-only), screenshot areas (Lucy 2 build).

## Source Report - Indeed tabs (added 8/23 from the org-dashboard chat)

ALL 11 owner boards + the Captainship Dashboard + the TEMPLATE have a visible
**Source Report - Indeed** tab (period picker C2; the dashboard adds a
captainship-wide manager dropdown C3; the template is an empty shell) backed by
a hidden local 'Indeed Ad Data' tab holding ONLY that owner's slice (values, no
IMPORTRANGE — an owner board never holds other managers' numbers). Refreshed at
4am/12pm/5pm by `automations/indeed_source_report` on Lucy 2 (`push_boards()`
in run.py; all 12 data targets in `BOARD_PUSH`). Minting a new board from the
template: seed its hidden tab + add it to BOARD_PUSH.

## Fleet rules & gotchas

0. **VANTURA IS NEVER PART OF A FLEET CHANGE (Carlos, 2026-08-24).**
   "The boards" / "everyone" / "fleet-wide" = the 11 owner boards +
   template + (where relevant) the Captainship Dashboard — NOT the
   Vantura Master Sales Board. Vantura is touched ONLY when Carlos
   names it explicitly. (Standing nightly automations that already
   cover Vantura by his design — termination sync, DU fill — stay.)
1. **Any template improvement must be applied to all 12 (+ mirror where
   relevant).** Owner sheets are detached copies. Loop the file-ID list in
   `scripts/` (see `center_all.py` for the canonical loop pattern).
2. Sheets API traps hit repeatedly: can't merge across a frozen boundary and
   can't freeze through a merge (create unfrozen → merge → freeze; titles are
   overflow text, not merges). CF number comparisons treat `""` as > any
   number — guard with ISNUMBER. USER_ENTERED coerces "8.23"/dates — RAW +
   TEXT format for week labels. IMPORTRANGE needs a human Allow-access click
   per source (done for the mirror).
3. Roll Call auto-sync rules (Carlos, 8/21): any Sales Board rep missing from
   Roll Call gets added; a sale-day mark is **raise-only Here** — never
   overwrite a manual Off/NoShow (flag the conflict instead). No sale ≠
   absent; only positive evidence is written.
4. Sales Board sorting via the filter is safe: day cells key on `$B<row>`, so
   formulas travel with the rep.
5. The Google auth for all Sheets writes: refresh token at
   `~/.config/recruiting-report/oauth-token.json` (spreadsheets scope) —
   helper `scripts/sheets_api.py`. Drive copies/renames go through the Drive
   MCP connector (Sheets token can't touch Drive).
6. Do NOT touch other tabs of the Vantura master; its own automations
   (att_order_log etc.) run on Lucy 2 and own those tabs.

## Current data state (as of 2026-08-22)

Owner boards hold weeks **8.2, 8.9, 8.16, 8.23** (from a single 4-week pull,
7/27–8/22: 24k lines, 78 owners visible to Carlos's Tableau identity).
4-week totals: Atef 1155 · Jamis 485 · Murphy 472 · Hipolito 432 · Kinsey
428 · Wood 398 · LeRoy 315 · Patel 306 · Ramirez 287 · Smith 261 · Starr 139.
Rosters are the log's sellers (largest: Atef 34). Setup office/owner cells
stamped. Roll Call: Active + Here on sale days, 4 weeks archived.

## Next steps (agreed direction, not yet built)

- **Daily automation**: one scheduled pull (yesterday's date) → per owner:
  upsert WeekData row for the current week, append new week labels each
  Monday, add missing reps to Sales Board + Roll Call, raise-only Here marks,
  flag conflicts. Parameterize by owner_prefix + sheet id (the table above).
  Likely home: Lucy 2 (see `/lucy2` skill) or this mini via launchd.
- Weekly close-out ("Start New Week") can eventually restore attendance
  formulas over typed marks after archiving them to RollCallData.

## Session 8/22 (evening) — layout NOW, email backfill, new rows

**Manager Trend campaign block CURRENT layout** (supersedes the 8/22-pm
paragraph above; all 11 boards + template; mirror = +1 row):
row 30 band · 31 Headcount ✎ · 32 Leaders in Training ✎ · 33 Active
Headcount on Tableau (rolling wk-to-date distinct sellers Mon→day) · 34 Total
Apps · 35 Rank on the Tracker · 36 Sales per Rep (cumulative apps ÷ cumulative
sellers; fmt 0.0) · 37 New Internet · 38 CRU Internet · 39 **Wireless Sales
(excl. BYOD)** · 40 AIR/AWB · 41 CRU % · 42 BYOD · 43 CRU BYOD · 44 IRU BYOD ·
45 Activation Rate 31–60 · 46 0–30 Churn · **47 VoIP Line Count** (order-log
`Voice Line Count` sum) · **48 ABP %** (Auto Bill Pay Y/(Y+N) units) · **49
BYOD %** (BYOD ÷ wireless units incl BYOD) · 50 National AVG Headcount ·
51 National Sales per Rep (fmt 0.0) · band 53 "B2B AT&T METRICS — SCREENSHOT"
· band 71 "FOUR-WEEK AVERAGE — SCREENSHOT" · color key 89–97. Rows 47-49
backfilled day-by-day for all 34 weeks from the order-log chunks
(`scripts/email_backfill.py` phase 2). Mirror import is `A1:JN97`.

**Email-image backfill (rows 45/46/50/51, DONE for 33 historical weeks)**:
Sunday "B2B ATT SBS Daily Tracker" emails (noreply@thesmartcircle.com) carry a
Salesforce image of the D2D1 tracker. URL
`https://smartcircle.my.salesforce.com/servlet/servlet.ImageServer?id=<id>&oid=00D1I00000032FwUAI`
(id = '01' + chars after `id\x01` in the QP-decoded htmlBody; images stay
downloadable for the whole year). Pipeline: macOS Vision OCR binary
(`scratchpad ocr.swift`; band-tile ~700px, x/y/w/text). Parse rules that
survived: Grand-Total row = leftmost 'Grand Total' token; the ranked summary
in it reads 'Gra..' → next int = national Rep Count → next d.d = national
Sales/Rep; owner census = ALL-CAPS x<0.05 rows in the SAME section (above or
below GT, whichever is bigger); National AVG HC = RepCount ÷ census.
Activation/churn panel exists from **WE 6/28 cutover** — header tokens
'(31-60'/' (0-30' give the two column x-anchors (media ~0.905/0.952); owner
rows matched by needle on concatenated x<0.35 tokens. Ten weeks the OCR
couldn't read were EYEBALLED from crops (gtfix_*.png) — values in
`scripts/email_backfill_fix.py` sibling write (see FIX dict in session
scratch): 1/11 929/5.9 · 1/18 894/6.1 · 1/25 875/6.1 · 2/1 810/5.8 · 2/22
891/5.8 · 3/22 887/6.6 · 4/5 852/6.5 · 6/28 961/7.0 · 7/5 921/6.0 · 8/9
884/6.8 (RepCount/SPR; HC = ÷census). Scripts: `email_backfill.py` (33-image
OCR + writes + phase-2 new rows), `email_backfill_fix.py` (hardened re-parse).

**B2BATTSalesMetrics cross-reference (in progress)**: the "B2B AT&T Sales
Metrics" workbook tab = dashboard `ATTTRACKER-B2B/B2BATTSalesMetrics`. The
CarlosTeamExpandedMetrics CUSTOM VIEW IS BROKEN ("re-create the custom view")
— it falls back to the original all-owner view, which is fine. The grid sheet
renders in ~10 s headless (default viewport; a big set_viewport_size BLANKS
it). Crosstab sheets after the 2026-08 republish: 'Sales.Quality Metrics (2)'
(owner rows), 'Sales.Quality Metrics (3)', 'Activation & Churn (2)'. The
top-left week picker is filter field `Time Frame (order date) (copy)_…` — URL
params CANNOT drive it; drive the UI: first [role=combobox] → checkbox rows
`div.FIItem:has(a.FIText[title="2026-08-09"])` (check target, uncheck prior,
verify aria-checked) → `button.apply` (waits enabled). 'Last Week' = WE 8/16;
explicit dates start 2026-08-09. Columns seen: Sales, Rep Count, Sales Per
Rep, Order Count, Early/Late Order %, Internet Sales, VOIP Line Count,
Wireless Lines, AIR/AWB Sales, Weekend Selling Rep %, Rep Tier Attainment %,
ABP %, BYOD %, CRU BYOD %, IRU BYOD %, CRU %, New Wireless %, Activation Rate
31-60, Churn Rate 0-30. NOTE the view's BYOD % ≠ ours (Atef this wk: view 46%
vs our 14.5% = 38/262) — denominator differs; reconcile from the 8-week pulls
(`scripts/xref_pull.py`) before redefining row 49. Also to do from the pulls:
fill remaining act/churn OCR gaps (rows 45/46) from 'Activation & Churn (2)',
report per-owner deltas vs rows 34/36/37/40/41/45/46/47/48/49.

## Cross-reference RESULTS (8/22 late — 8 weeks × 11 managers vs B2BATTSalesMetrics)

Pulled WE 6/28–8/16 crosstabs (`scripts/xref_pull.py`; sqm2 = owner sheet
'Sales.Quality Metrics (2)', per-owner Activation/Churn included; the
'Activation & Churn (2)' sheet never renders for crosstab — not needed).
Comparison + stamping in `scripts/xref_compare.py` (report:
scratch `xref_report.txt` / `.json`).

**Line-up verdict:**
- EXACT match everywhere: Rep Count (row 33), Sales per Rep (36), AIR/AWB
  (40), CRU % (41), VoIP Line Count (47). Wireless: view "Wireless Lines" =
  our row 39 + row 42 (it includes BYOD) — matches within cancellations.
- Total Apps (34): exact on recent weeks; view runs 3–9% BELOW our order-log
  counts as weeks age — the view drops later-cancelled orders, the order log
  (and Sara's board convention = ours) keeps sales credited to the week.
  Both "correct"; ours is the sales-board semantics. Leave as is.
- "Internet Sales." in the view ≠ our row 37 New Internet: the view counts
  internet orders beyond NEW internet (Justin shows 4–8/wk there with 0 new).
  Our row is the DU/product-split semantics. Leave as is.
- ABP % / BYOD % (48/49): the view's basis is NOT reproducible from the
  ORDERLOG export (tested unit-, BAN-, BAN+time-order-, rep-average-, and
  WIP-real bases; each matches some owners, none matches all — the view
  computes off a different underlying line table). RESOLUTION: rows 45-49 for
  the 8 pulled weeks are STAMPED with the view's own numbers (authoritative);
  pre-6/28 weeks keep order-log approximations (48/49) and stay blank (45/46,
  no panel pre-cutover). Go-forward daily automation should stamp 45-49 from
  this view weekly (pull recipe in xref_pull.py) and 47 from the order log
  (which matches exactly).
- Order grain discovery: view "Order Count" = distinct (Account BAN, Order
  Time) — 100/100 exact for Atef 8/16.
- Nationals check: sqm3 GT sheet tracks the week filter (8/16: 878 reps /
  6.5 SPR final vs email-Sunday-morning 868/6.4). Rows 50/51 stay on the
  email/D2D1 basis for 33-week consistency.

## Campaign block REORGANIZED (8/22 night) — CURRENT row map

Carlos asked for a logical read-down order + better visuals. The block is now
five themed sub-sections styled exactly like the recruiting funnel (same band
palette, Inter labels / Roboto Mono data, GOAL-column chip stripe, weekend
chips, row-line borders + week separators, 28px band rows). Script:
`scripts/reorg_campaign.py` (idempotent; per-board pre-reorg value snapshots
in scratch `reorg_backup_<fid8>.json`).

**NEW map (all 11 boards + template; mirror = +1):**
30 AT&T B2B — CAMPAIGN (ink super-band) · 31 TEAM band (475569) ·
32 Headcount ✎ · 33 Leaders in Training ✎ · 34 Active Headcount on Tableau ·
35 PRODUCTION band (0F766E) · 36 Total Apps · 37 Sales per Rep (0.0, bold) ·
38 Rank on the Tracker · 39 PRODUCT MIX band (1D4ED8) · 40 New Internet ·
41 CRU Internet · 42 Wireless (excl. BYOD) · 43 BYOD · 44 CRU BYOD ·
45 IRU BYOD · 46 AIR/AWB · 47 VoIP Line Count · 48 QUALITY band (7E22CE) ·
49 CRU % · 50 ABP % · 51 BYOD % · 52 Activation 31–60 · 53 0–30 Churn
(0.0%) · 54 NATIONAL BENCHMARK band (B45309) · 55 National AVG Headcount ·
56 National Sales per Rep. Screenshot bands now 58 & 76; color key 94–102.
Mirror import range is `A1:JN102`.

**OLD→NEW row map** (every script written before this reorg uses OLD rows —
translate before reusing, incl. the future daily automation):
31→32 · 32→33 · 33→34 · 34→36 · 35→38 · 36→37 · 37→40 · 38→41 · 39→42 ·
40→46 · 41→49 · 42→43 · 43→44 · 44→45 · 45→52 · 46→53 · 47→47 · 48→50 ·
49→51 · 50→55 · 51→56.

## Campaign goals + grading (8/22, after the reorg) — row map is now +1 below TEAM

TEAM manual rows split (Carlos): Headcount✎ / Leaders in Training✎ became
**32 Head Count✎ · 33 Leaders✎ · 34 People in Training✎** (35 Active HC).
Everything below shifted +1 vs the previous section's map: 36 PRODUCTION band ·
37 Total Apps · 38 Sales per Rep · 39 Rank · 40 PRODUCT MIX band · 41-48
products (NI, CRU NI, Wireless excl BYOD, BYOD, CRU BYOD, IRU BYOD, AIR/AWB,
VoIP) · 49 QUALITY band · 50-54 (CRU%, ABP%, BYOD%, Activation, Churn) ·
55 NATIONAL band · 56 Nat AVG HC · 57 Nat SPR. Screenshot bands 59 & 77;
color key 95-103. Mirror = +1 more; import `A1:JN103`.

**Goal column B** (only these three; nothing on Rank, per Carlos):
- B32 Head Count goal = **30**, AMBER write-in cell (B33/B34 also amber,
  empty — write-in spots). Amber = you type it; chip = automated.
- B37 Total Apps goal = `=ROUND(C56*C57,0)` — live national avg apps/office
  (NatHC × NatSPR), chip bg.
- B38 SPR goal = `=C57` — live national SPR, chip bg.

**Grading CF** (script `scripts/campaign_goals.py`): WK columns only, rows
32/37/38. Same chips as recruiting (≥95% of goal green, 90–95% yellow, <90%
red; blank-safe ISNUMBER guards). Head Count grades vs the static B32=30;
Total Apps + SPR grade each week against THAT WEEK's national (C$56*C$57 /
C$57 relative-column), so history is judged by its own week's bar. Carlos
said "5/10/15" — implemented as the recruiting 5/10 bands for consistency;
if he wants the red line at 15% instead, edit the 0.9 factors to 0.85/0.90.
Mirror carries the same CF at +1 rows against imported values.
NOTE: the daily automation must keep goal formulas/CF anchored if it ever
inserts week columns (they reference relative columns + rows 56/57).

## Goal fix v2 (8/22, Carlos round 2) — SUPERSEDES the goal bullet above

- Total Apps goal B37 = `=ROUND($B$32*C57,0)` — **Head Count goal x national
  SPR** (30 x 6.4 = 192), replacing the incoherent NatAvgHC*NatSPR (72 = a
  national-average-SIZED office, wrong bar next to a 30-rep HC goal). Goals
  cascade: edit B32 and the apps goal follows. CF row 37 re-anchored to
  `$B$32*C$57` (that-week national SPR).
- Goal cells are ALL chip gray now (B32/B33/B34 amber removed — Carlos:
  "they can be gray like the other ones"). Amber remains on the A-column
  labels of the three manual TEAM rows only.
- Graded rows confirmed: Head Count (32), Total Apps (37), Sales per Rep
  (38). Nothing else ("That's it for now").
- Reading the two graded production rows together: SPR red = productivity
  below national; Total Apps red = output below a full-size (30-rep) team at
  national productivity — small-but-productive vs big-but-unproductive
  offices fail different rows. Script: `scripts/campaign_goals_v2.py`.

## Goal cells v3 (8/22, Carlos round 3) — FINAL goal-cell scheme

Amber = a goal lives here and drives its row's coloring. The three goal
cells are AMBER again: boards/template **B32 / B37 / B38** (mirror B33 /
B38 / B39). Leaders + People in Training goal cells stay gray chip (no
goals). CF is now CELL-DRIVEN: each graded row compares its WK cells against
its own $B$ goal cell (not the national rows directly) — so overtyping a
goal cell immediately re-colors the row. The cells still carry the live
formulas (B37 = $B$32 x C57 NatSPR = 192; B38 = C57 = 6.4) until someone
overtypes them. Historical weeks therefore grade against the CURRENT goal
value (the earlier per-week-national grading was dropped in favor of
Carlos's fill-in-the-goal model). Script: `scripts/campaign_goals_v3.py`.

## Day-cell semantics + polish (8/22 late night, Carlos live session)

**Day-cell semantics (NOW THE LAW for the daily automation):**
- Rows 50 CRU% / 51 ABP% / 52 BYOD%: day cells are WEEK-TO-DATE CUMULATIVE
  from the order log (Mon..that-day pooled), like Active Headcount — never
  per-day (a lone all-CRU day used to print 100%). Rewritten for all 34 weeks
  (`scripts/cumulative_quality.py`). WK cells untouched (view stamps stand).
- Rows 53 Activation / 54 Churn / 56 Nat AVG HC / 57 Nat SPR: day cells =
  the DAILY tracker email's reading that day ("whatever the tracker says").
  `scripts/daily_tracker_stamp.py` = the reusable stamper (proven on WE 8/23
  Mon-Sat: natSPR built 2.9→3.7→4.7→5.5→6.4). NOTE: the Monday-morning email
  still shows the COMPLETED prior week (10.7/6.5 on 8/17), so Monday cells
  read like last week's finals — accepted per Carlos's rule. Daily automation:
  fetch the day's 'B2B ATT SBS Daily Tracker' email image and stamp cols D-J.

**Polish + goal UX:**
- A-column labels de-ambered (Carlos); ✎ glyph remains. Amber lives ONLY on
  the three goal cells B32/B37/B38 (mirror B33/B38/B39).
- Every NO-goal metric row has A:B MERGED, label centered (boards+template).
  The MIRROR CANNOT HOLD MERGES (they block the IMPORTRANGE spill) — its B
  cells are painted white instead (gridlines hidden = looks merged).
- Atef's Total Apps goal B37 = typed 300 (formula replaced; CF keys off the
  cell, so colors follow). Other boards keep the live formula.
- Mirror 'Manager Trend' has warningOnly protection "mirror-glass" over
  A2:JN103: typing into the spill area (which BLANKS the whole view — what
  happened to Carlos) now pops a warning first. Row 1 (owner picker) free.
  `scripts/block_polish.py`.

## ⚠️ ARCHITECTURE FLIP (8/22 night) — Manager Trend now LIVES IN THE MASTER

Carlos wanted to EDIT trend data from the Captain Master Mirror. Done by
INVERTING the flow for this one tab (`scripts/mirror_flip.py`):

- The MASTER (14_T4fySyQhRPsyWZLGEs6Sarc0jyJ4oD-gV8E97WZU8) now holds 11
  REAL, EDITABLE tabs: **MT · Jackie / Justin / Joshua / Jamis / Dhyey /
  Jeff / Kinsey / George / Atef / Joey / Vincent** — full copies (values,
  formats, CF, merges, week column-groups). THESE ARE THE SOURCE OF TRUTH
  for Manager Trend. Carlos types here (headcounts, goals — e.g. Atef apps
  goal 300 lives in MT · Atef!B37).
- Recruiting GOAL col B5:B27 on the MT tabs is now STATIC VALUES (the
  '=Goals!' refs would dangle in the master). The MT tabs' B column IS the
  live recruiting-goal source now; board Goals tabs are seed/history.
- Every owner BOARD's Manager Trend is now GLASS: values cleared, A1 =
  IMPORTRANGE(master, 'MT · <First>'!A1:JN103); merges removed (they block
  spills) with white-B paint simulating them; warningOnly protection
  'trend-glass'. Formats/CF stay local and color the imported values.
  ONE-TIME: each board needs a human 'Allow access' click on its Manager
  Trend A1 (#REF! until then).
- The master's glass 'Manager Trend' display tab (owner dropdown B1) now
  uses same-workbook INDIRECT on the MT tabs — instant, no importrange.
- ALL FUTURE Manager Trend WRITES (daily automation, backfills, screenshot
  inserts) target the MASTER's 'MT · <First>' tabs — NEVER the boards.
  Scripts written before this flip target board fids: TRANSLATE before
  reuse. Screenshot images must ALSO be inserted on the master MT tabs
  (images do not travel through IMPORTRANGE).
- Minting a future board from the template: give it a painted Manager Trend
  (template unchanged) OR add an MT tab in the master + flip its trend the
  same way — follow mirror_flip.py.
- Pre-flip value backups: scratch flip_backup_<fid8>.json (one per board).

## Rename (8/22): the master workbook is now titled "Captainship Dashboard"
(was "Captain Master Mirror"; same file id 14_T4fySyQhRPsyWZLGEs6Sarc0jyJ4oD-gV8E97WZU8
— every IMPORTRANGE keys on the id, nothing breaks). Glass-tab header note in
D1 updated to point editors at the MT · tabs. The Chrome bookmark label still
says the old name — rename it next time Chrome is closed (bookmark edits need
a Chrome quit/relaunch).

## MT tabs HIDDEN + dropdown-editing script (8/22, Carlos: "fix it")

Carlos rejected the 11 visible MT · tabs. Now: all 11 are HIDDEN (still the
source of truth — boards import them, automation writes them, INDIRECT reads
them fine hidden). The dashboard shows only the original tab set with the
B1 owner dropdown.

To EDIT from the dropdown view (his original ask), a bound Apps Script is
required (API tokens cannot install one): `dashboard_sync.gs` in this
folder, install steps in its header. Simple triggers, same-file only, no
auth popup. Behavior: dropdown change loads that owner's hidden MT tab into
the grid (first switch converts the INDIRECT view to a real editable grid);
every grid edit writes back to the MT tab instantly → flows to the owner's
board. onOpen + '↻ Trend view' menu refresh the grid (needed to see
overnight automation writes; mid-session automation writes to MT tabs do
NOT appear until refresh/re-pick).

UNTIL the script is pasted: the view stays the read-only INDIRECT glass
(accurate; typing in it breaks the spill until undone — protection was
removed in anticipation of editability). Automation note stands: ALL trend
writes target the hidden 'MT · <First>' tabs.

## Dashboard editing LIVE (8/22 late — installed via Claude-in-Chrome)

Carlos asked Claude to do everything by driving his Chrome. DONE:
- Apps Script (`dashboard_sync.gs`, v2 with robust MT-tab lookup + try/catch
  + dbg breadcrumb to 'Mirror Config'!H1) is INSTALLED in the dashboard's
  bound project ("Untitled project"). Simple triggers only — no auth needed.
- The dropdown grid is CONVERTED to script-managed real values (INDIRECT
  gone). Verified end-to-end: dropdown switch loads the owner; a grid edit
  synced to 'MT · Atef' storage.
- All 11 boards' 'Allow access' grants are DONE — every board's Manager
  Trend is live-fed from the master ('MANAGER TREND — <name>' + data
  verified on all 11).
- GOTCHAS learned: (1) clipboard pastes of the script need
  `LANG=en_US.UTF-8 pbcopy` or the '·' mangles and the tab lookup dies;
  (2) grid B-cells of no-goal rows map to merge-COVERED MT cells — writes
  there are swallowed (harmless; no goals live there); (3) the reliable way
  to click Sheets' 'Allow access' card programmatically is JS
  mousedown/mouseup/click dispatch — extension coordinate/ref clicks were
  flaky; (4) 'Trend view → Refresh from storage' menu (or reopening) pulls
  automation updates into the grid.

## ✅ DAILY AUTOMATION LIVE ON LUCY 2 (built + deployed 8/22 night)

Module: `automations/captainship_boards/` in the repo (built in worktree
~/recruiting-report-capt, branch captainship-daily, merged to main + delivered
via `push origin HEAD:resume-pushing-v2`; Lucy 2 pulled it).

**Schedule: Report Library card `captainship_boards`, DAILY 6:30 AM CST,
args --write, assignee Lucy 2** (card_scheduler launchd runs it). Manual runs:
queue `rerun captainship_boards` (dry preview) / `rerun captainship_boards
--write`. Remote dry-run VERIFIED CLEAN 8/22 17:53 (CDP order-log pull ✓ auth
OK ✓ 11 boards ✓ recruiting ✓ exit 0).

What it does every morning (all order-log; Carlos's rule):
- Pulls current-week ORDERLOG via the shared CDP Chrome (9246 lock, same as
  att_order_log).
- Per owner board: WeekData upsert (Rep|WE), roster appends (SB B4:B43 + Roll
  Call A:D), RollCallData raise-only Here marks.
- Focus Report (master 'MT · <First>' tabs): current-week rows 35/37/38/39/
  41-48/50-52 (WK + day cells; rolling HC/SPR; cumulative quality %s; rolling
  rank among ALL owners in the export) + recruiting rows 5-27 from the LIVE
  org book 111Bmxx… ('Alphalete Recruiting Dashboard' — NOT 1Y3Rx…, NOT the
  old 1nOuJ… whose tabs moved).
- Monday: ensure_week_block auto-rolls each MT tab (insert 8 cols at C, copy
  formats from old block, drop tail week, repoint goal formulas B37/B38 if
  still formulas, rebuild the 9 campaign CF rules, re-add the day group).
  ⚠️ FIRST LIVE ROLL = Monday 8/24 6:30am — UNTESTED against real sheets;
  check it Monday morning (failures are per-owner-contained; sales boards
  still update).

Learned during deploy:
- Lucy 2's fill (Sheets OAuth) identity can open ALL the captainship sheets
  (it behaves as Carlos's own auth). The PermissionErrors during bring-up were
  READ-QUOTA 403s (gspread raises them as PermissionError) — fixed by pacing
  (sleep 2/board + 20s before recruiting). The alphaletereporting@gmail.com
  shares added to the 11 boards + 111Bmxx (reader) are harmless belt-and-
  suspenders; the Captainship Dashboard itself is NOT shared to it (share
  dialog kept dying; turned out unnecessary).
- Rows 53/54 (activation/churn) + 56/57 (nationals) are NOT in the daily job
  yet (need the D2D1 crosstab section — planned v2 with --with-tableau).
- Weekly view-stamp of rows 50-54 from B2BATTSalesMetrics (xref_pull recipe):
  also v2.

## Daily Update fill AUTOMATED (8/23) — the VA's "claude prompts.pdf" runbook

`automations/daily_update_fill/` (deployed to main; runs on **Lucy 1**, card
`daily_update_fill` DAILY 8:45 PM CT with --write). Automates the VA's evening
New DU pass on the Vantura master from ApplicantStream office 11580:
today's Total Second Interviews roster (name/email/phone/1st/2nd/ad) + showed
/ offered / BOB from the same Retention Details load (collect ALL detail
hrefs BEFORE scraping — they navigate away), calendar best-effort for
follow-up wording (LM / Letting us know / Declined) + 'Brought on Board'
orientation dates (calendar shows TODAY by default → nightly runs get these;
past-date backfills usually can't). Appends A + I..S in the VA's exact
vocabulary ('1 - Orientation Scheduled' / 'Not Active', "Didn't offer them "
with trailing space); no-shows keep Offered/BOB blank (VA convention).
DEDUP by name → re-runs + VA overlap safe. Verified vs the VA's own 8/21
entries (9/9 roster incl. accents; statuses match; the one LM nuance needs
the live calendar). AppStream week picker: Sat-Fri weeks, #weekStart
datepicker only accepts SUNDAYS, then the **Get Report** button reloads.
Generalization ready: --office / --sheet-id / --tab args — captainship
managers' offices (ids in funnel_board/roster.py) can each fill their own
board's 'Daily Update' tab (same 22-col schema, verified on Atef's).

## Daily Update fill v2 (8/23) — ALL offices + CR column + moved to LUCY 2

- Card `daily_update_fill` now assignee **Lucy 2** (8:45 PM CT daily,
  --write, offices=all); registry machine Lucy 2; Lucy 2's AppStream session
  verified (remote dry-run clean).
- Covers ALL 12 offices: Vantura New DU (11580) + the 11 captainship boards'
  'Daily Update' tabs (AppStream ids from funnel_board roster: Atef 23467,
  Jamis 19592, Jackie 22358, Jeff 15031, Kinsey 11906, Vincent 23318,
  George 11296, Justin 22192, Joshua 21770, Joey 23206, Dhyey 22767).
- NEW column T (Carlos): classroom retention from the SAME retention report —
  'Total Training' roster + 'Training Showed Up' => 'Showed To CR' /
  'CR No Show'. Existing rows: filled only when T is blank (never stomps the
  VA). Appended candidates who reached training also get R = training date
  and A = '2 - Showed to classroom' (recovers orientation dates WITHOUT the
  calendar — backfills fully).
- AppStream week widget decoded: DEFAULT view is Sat-Fri, but PICKING a
  Sunday (the only selectable days) shows Sun-Sat — group by pick_sunday(),
  probe for the Sunday's header.
- 4-week backfill (7/27-8/23, all offices, --write) run 8/23 — log:
  scratch du_backfill.log.

## Session close-out 8/23 (context-reset handoff — READ THIS FIRST NEXT TIME)

**Backfill RESULTS (4 weeks, 7/27–8/23, ran clean 8/23 ~1pm):** 1,380
candidates appended — Justin 275 · Jackie 239 · Joshua 220 · Kinsey 177 ·
George 145 · Jamis 125 · Atef 117 · Joey 52 · Vantura New DU +15 (dedup
correctly skipped everything the VA had). **Jeff Starr / Vincent Smith /
Dhyey Patel = 0 by reality, not bug**: their AppStream offices (15031/23318/
22767) only went live ~8/19 and hold no recruiting data yet — the nightly
run picks them up automatically when they start. Their past-week nav logs
"did not land" because empty offices render no picker grid; harmless.

**Post-backfill repair applied:** being on the Training roster proves
offered+BOB, so rows with T ∈ {Showed To CR, CR No Show} got P=Y / Q=BOB
(286 rows fixed across 6 boards; rule now baked into the module).

**Terminations (Carlos asked 8/23): NOT automatable from ApplicantStream.**
Full retention-report row list dumped — it is recruiting-only (First/Second/
Third interview rows, Removed/Disqualified/Declined From X Calendar, Offered
From Second/Third, Total Daily Bob, Total Training / Training Showed Up,
Total New Starts Scheduled / New Starts Showed Up). Nothing about employed
reps. Convention on the DU: human sets Secondary Status B='Terminated' and
A='Not Active'. **OFFERED but NOT YET BUILT (awaiting Carlos's yes): nightly
sync rule B ∈ {Terminated, Resigned, Declined Position} ⇒ A='Not Active'.**
Alternative real source would be Sara Plus dispositions — not wired.

**Machine/state facts for the next session:**
- Worktree `~/recruiting-report-capt` (branch captainship-daily, rebased on
  origin/main, everything PUSHED to main + resume-pushing-v2). Gitignored
  extras there: ownerville-creds.json (copied from main checkout),
  .appstream_storage_state.json (mini AppStream session, auto-refreshes).
- `playwright` pip package installed into ~/recruiting-report/.venv (import
  shim only — applicant_tracker hard-imports it; patchright does the work).
- Live Lucy 2 cards: `captainship_boards` 6:30 AM CT (--write) and
  `daily_update_fill` 8:45 PM CT (--write, offices=all). Handles:
  `lucy rerun captainship_boards|daily_update_fill` (dry by default).
- ⚠️ Monday 8/24 6:30 AM = captainship_boards' FIRST live week-roll
  (untested on real sheets; failures are per-owner-contained) — CHECK IT.
- captainship_boards v2 backlog: rows 53/54 (activation/churn) + 56/57
  (nationals) daily via d2d1/activation/churn crosstabs; weekly WK-stamp of
  rows 50-54 from B2BATTSalesMetrics (recipe = scripts/xref_pull.py).
- daily_update_fill calendar nuances (nightly-only fields): LM / Letting us
  know / Declined wording + orientation dates for people not yet in
  training. Backfills recover orientation via training dates instead.

## Termination sync BUILT + LIVE (8/23, Carlos approved a board-driven rule)

Supersedes the "offered but not built" note above. In every nightly
daily_update_fill pass, per office: names marked terminated on the BOARD —
Sales Board 'Field Status' col ~ /^t$|termin/i OR a literal 'T' in a day
cell, Roll Call 'Status' col ~ same OR a 'T' in a Mon-Sat attendance cell —
get their Daily Update row set A='Not Active' (+ B='Terminated' when blank).
Header rows are discovered by text ('REP' / 'Rep Name' / 'Field Status' /
'Status'), so it works on both the Vantura master and the captainship
boards. First live pass 8/23: Vantura had 5 marked (Emmanuel Nieto, David
Gutierrez, Adabella Amaya Gallegos + 2 already inactive) -> 3 stale
statuses flipped. Captainship boards had no marks yet (fresh fills).

## Status lifecycle SIMPLIFIED (8/23, Carlos): Active / Showed to Classroom / Not Active / Admin

The DU Status (col A) ladder is retired. Nightly `sync_statuses` (in
daily_update_fill, runs every pass on all 12 offices) enforces, in order:
board-terminated -> **Not Active**; any sale seen (WeekData rows or Sales
Board numbers; nickname-tolerant last-name+first-3 matching, will~william)
-> **Active**; old '3 - In Training' off-roster -> **Showed to Classroom**;
old 4-7 ladder off-roster -> Not Active; '1 - Orientation' -> Not Active;
fresh classroom shows -> **Showed to Classroom**. 'Not Active' is never
resurrected except by a sale; **Admin rows are never touched**. Migration ran
8/23: 463 flips (Vantura 203 incl. 132 Not Active->Active current sellers).
Status dropdowns on all 12 DU tabs + template now list exactly the four
values. Appends now start at Not Active (or Showed to Classroom if already
CR-shown); orientation date no longer drives status.

## Leaders Retention tab (8/23) + DU row-1 filters — ALL 13 workbooks

`scripts/leaders_retention.py` built a formula-driven **Leaders Retention**
tab on the Vantura master + 11 boards + template (NO automation needed — it
recalculates live off the Daily Update). Five stacked tables per LEADER (the
DU '2nd Rounder' col N): SECOND ROUNDS CONDUCTED (O='Showed' only — a no-show
means no interview happened) · OFFERED (P='Y') · BOB (Q='BOB') · ORIENTATION
SCHEDULED (R non-blank) · SHOWED TO CLASSROOM (T='Showed To CR'). Columns =
TOTAL + 12 week-endings, NEWEST FIRST, self-rolling (`=TODAY()-WEEKDAY(
TODAY(),2)+7` header chain). Leader rows auto-appear via a UNIQUE spill
(25 slots; tables 2-5 mirror table 1's spill). Hidden helper cols AA:AH
mirror DU L/N/O/P/Q/R/T with DATEVALUE + week-ending computed (L dates are
TEXT 'm/d' — DATEVALUE assumes current year). Fleet styling (ink header,
5-color bands, mono numbers, frozen panes). Also set the row-1 basicFilter
(A1:V) on every Daily Update / New DU tab per Carlos.
Verified live: Justin — Brandon Guyton 28 2Rs/18 offers (12 2Rs this week);
Vantura history flows (Cinthya Reyes 56 all-time). A '?' leader row on
Vantura = literal '?' entries in the VA's 2nd Rounder column (real data).

## Leaders Retention v2 (8/23) — two views, one screen (v1's 5 stacked tables scrapped)

Carlos found v1 too scrolly (looking at Jamis's). Rebuilt on all 13 books
(`scripts/leaders_retention_v2.py`, delete+recreate, idempotent):
- **View 1 FUNNEL** (rows 4-22): WEEK ▶ gold picker in B4 (All Time / This
  Week / Last Week / last 12 WE dates, dropdown fed from hidden AJ). One
  table: LEADER | 2ND ROUNDS (O='Showed' only) | OFFERED | OFFER % | BOB |
  ORIENT SCHED | SHOWED CR | CR SHOW % + a TOTAL row.
- **View 2 WEEKLY TREND** (rows 25-42): METRIC ▶ gold picker in B26 (the 5
  metrics); LEADER × TOTAL + 12 self-rolling week-ending columns.
- Resolvers: AK1 = picked week serial (0=All Time), AK2 = metric index;
  trend counts use CHOOSE(AK2, range...) inside COUNTIFS.
- GOTCHA fixed: helper cols are ARRAYFORMULA text ("" for blanks), so a
  "<>" COUNTIFS criterion counts EVERYTHING — non-blank tests against
  helpers must use "?*".
Verified on Jamis: 73 2Rs -> 52 offered (71%) -> 39 BOB -> 17 orient -> 8
showed CR; Asylai Uzenkulova 16/13/10, 80% CR show.

### v2.1 (8/23) — sorting

Carlos: "filters so I can sort highest to lowest". A NATIVE filter would
physically scramble the spilled leader column, so instead the spills sort
themselves (same `scripts/leaders_retention_v2.py`, rerun on all 13):
- Funnel: gold **SORT ▶** picker in E4 (merged E4:F4) — A→Z / 2nd Rounds /
  Offered / Offer % / BOB / Orient Sched / Showed CR / CR Show %, default
  2nd Rounds desc. Resolver AK3 (MATCH, 0 = A→Z); the A7 spill is
  LET+MAP+LAMBDA computing each leader's week-aware key, SORT desc, ties A→Z.
  %-sorts use -1 for zero denominators so blanks sink.
- Trend: no new picker — the A28 spill ranks leaders by the picked metric's
  all-time TOTAL desc (matches the TOTAL column).
Verified on Jamis: 2nd Rounds → Asylai 16 / Megan 15 / Eniola 12;
Offer % → the three 100%s on top. Week filter re-sorts live.
- 8/23 widths: columns were clipping → A=230, B-H=118, I-N=84 on all 13
  (patched live + builder updated). Auto-fit would NOT work: it sizes col A
  to the long A2 subtitle.

## Dashboard Leaders Retention + Source Report color fix (8/23 PM)

**Leaders Retention on the Captainship Dashboard** — new tab, same two-view
layout as the boards plus a gold **MANAGER ▶** picker (B3): one dynamic
IMPORTRANGE pulls the picked board's DU L2:T3000 into hidden AA:AI, local
helpers AK:AR recompute everything (resolvers AX1-3, manager table AT1:AV12,
week list AZ). Builder: `scripts/dashboard_leaders_retention.py`
(build|probes|unprobe). The IMPORTRANGE pair-grants were ALREADY connected
(mirror-era grants work both directions) — probes all resolved, no clicks.
Verified: Jamis matches his board exactly (73/52/71%/39/17/8); Kinsey and
Vantura flip live. NOTE Vantura shows OFFER % >100% for some leaders — the
VA marks P='Y' on rows whose O isn't 'Showed'; same semantics as the boards.

**Source Report - Indeed was all-white everywhere** (Carlos: "missing a lot
of colors") — ROOT CAUSE: every numeric cell in 'Indeed Ad Data' was TEXT
(early seeds; refreshes recycle "kept existing rows", so text never healed),
and numeric CF conditions skip strings. Fixed three layers:
1. one-time re-type org (48.9k cells) + dashboard (17.8k) + 11 boards;
2. PERCENT '0%' format on visible cols G/K/N/S (org+dash+11+template);
3. pipeline `_numeric()` in indeed_source_report/run.py at BOTH writes
   (org write + push_boards) — committed, pushed main+resume-pushing-v2,
   Lucy 2 `update` queued (row 2761); 5pm run exercises it.
Traffic lights verified rendering on org, dashboard, Jamis (green/yellow/red
+ 31%-style display). Manager flip on the dashboard SR verified (Kinsey).

## 2R audit — Vantura, 2026 (8/23, READ-ONLY — no sheets changed)

Carlos: "maybe he did more than 66 second rounds." He did: AppStream 2026
alone shows **William Bautista 117 conducted 2Rs / 93 offered / 76 BOB** vs
the funnel's 66 (= DU rows with O='Showed', all-time). Root causes, in order
of damage: (1) the VA leaves O blank on most conducted interviews — every
real leader is undercounted roughly 2x (Cinthya 106 vs 50, Olivia 91 vs 46,
Jayden 71 vs 23, Kendric 42 vs 7, Robert Polanco 28 vs 0); (2) 125 AppStream
2026 interviews have NO DU row at all (mostly setter-attributed no-shows);
(3) DU column L has NO YEAR and rows aren't strictly chronological — late-
2025 rows are indistinguishable from 2026 and DATEVALUE puts 11/20 etc. on
FUTURE week-endings in the LR weekly views; (4) for no-shows the AppStream
2ND column holds the SETTER (Miroslava 377 rows / 8 showed, the Camilas,
Luisana, Ania, Melissa) — the funnel's ≥1-Showed filter screens most out.
Calendar day-views can't be walked historically on a headless session
(known); week of 2025-12-28 wouldn't load (Jan 1-3 not covered).
Artifacts in scripts/: audit_2r_year.py (harvester, Total-column link
validated), analyze_2r_audit.py, audit_2r_2026.json (34 weeks),
audit_du_side.json, audit_missing_rows.json. Offered fix (NOT run): mark
DU O='Showed' from AppStream showed lists.

### 2R cleanup APPLIED (8/23, Carlos approved — "no reps added to active")

`scripts/cleanup_2r_du.py` (plan|apply) on Vantura New DU: blank-only fills
O=435 'Showed' + P=26 'Y' + Q=264 'BOB' (VA's 6 explicit No Shows respected,
listed in plan output); 164 missing interviews appended at the true data end
(r2330-2493), ALL Status='Not Active'. Verified: zero pre-existing statuses
touched (spot-checks r1087/1337/2077 intact; the apply script's own "196
changed" was a phantom-row shift artifact — rows 2330-2715 had stray cells).
Minutes later the STANDING lifecycle filled col T + flipped 12 new rows
(9 Showed to Classroom, 3 Active = real sellers) — that's the approved
sale=>Active rule, not the cleanup. Funnel after: William Bautista 110 2Rs /
101 off (92%) / 76 BOB; office TOTAL 792 / 732 (92%) / 523. Offer%>100%
anomaly gone. Residual gaps: pre-2026 rows unverifiable (outside pull),
name-dedup keeps one row per person.

### Dupe sweep after the cleanup (8/23 evening)

The 8:45pm-card daily_update_fill ALSO ran ~4pm (likely re-fired by the
15:12 queue `update` restarting card state) and raced the cleanup append —
its ~20 rows landed at r2310-2329 minutes before mine. Result: machine-made
doubles. Swept New DU with ascii-normalized + token-subset matching,
verified EVERY pair by email/phone before touching: **20 dupes deleted**
(race copies, short-vs-legal-name variants like 'Kentrell Ellison' vs
'Kentrell Deon Ellison', AppStream double-listings, re-booked no-show
second events). Same-name DIFFERENT people kept (Hector Sanchez x2, Jesse
vs Jesus Martinez, Jonathan Montes x2, Alejandra vs Alexus Calderon — all
different contacts). Of the 12 lifecycle-flipped rows: 11 were genuinely
new people (no prior row, any spelling); 1 (Ashley Tapia) duped 'Ashley
Del Angel Tapia' r1449 — my copy deleted, hers kept.
Sales Board: 51 reps, 0 dupes. Roll Call: 198 rows, 0 same-week dupes
(cleanup never wrote to either). Funnel final: William 108 2Rs / 99 off
(92%) / 74 BOB; office TOTAL 785 / 725 (92%).
NOT touched: the VA's own historical dupes (~115 emails appear 2+ times,
e.g. Carol Arreola x4) — pre-existing, needs Carlos's go-ahead; use the
same verify-by-contact method (scripts/cleanup_2r_du.py patterns).

### Status colors on col A (8/23 fix)

The 8/23 dropdown replacement (4-value lifecycle) WIPED the old chip colors
— setDataValidation via API carries no colors, so every DU status column
went white. Restored via 4 CF TEXT_EQ rules on A2:A6000, all 13 books +
template (idempotent: skips books already carrying the 4 rules): Active
green C6EECE · Showed to Classroom yellow FFEB9B · Not Active red FFC7CE ·
Admin gray D9D9D9. Same trap as Source Report chips: dropdown CHIP colors
are NOT API-accessible; color statuses with CF, never chips.

## Leaders Retention v3 (8/23 night) — polish + per-book slots + ACTIVE NOW

`scripts/leaders_retention_v3.py` is now THE canonical builder (supersedes
v2.1 + style_leaders_retention.py, whose polish it bakes in). Changes:
- **Visual polish on all 14** (13 books + dashboard, via style script for
  the 12 untouched books): medium ink frames + thin inner grid, zebra slot
  rows F4F7FB, DOUBLE top border on TOTAL, outlined gold pickers, traffic
  lights on OFFER %/CR SHOW % (>=65 green / >=35 yellow / red), self-scaling
  blue heat map on trend weekly cells with zeros DISPLAYED BLANK
  ('#,##0;-#,##0;' zero-section-empty pattern), taller title/header rows.
- **Per-book SLOTS**: the fixed 15 was silently hiding leaders (ARRAY_
  CONSTRAIN cap) — Vantura has 84 distinct showed-leaders (69 hidden, incl
  Carlos + Nico Murrugarra); Joshua 16. Rebuilt Vantura slots=90, Joshua 25.
  Grid rows derived (TEND+4); trend rows follow the same slot count.
- **ACTIVE NOW column (Vantura only)**: funnel col I = COUNTIFS(leader,
  status col A='Active') via new AI helper — deliberately NOT week-filtered
  (active is a now-state). Also a SORT ▶ option; left picker ON 'Active Now'.
  Answer to Carlos 8/23: Olivia 16 actives, William Bautista 13, Jayden 8,
  Nick Smedra 8, Kendric 7, Will Mills 7 — TOTAL 142.
- Known noise: leader-name aliases split rows ('Will Mills' vs 'William
  Mills', 'Kendrick/Kendric', three Sandys, '?', 'PR', 'Didi') and pre-2026
  rows with blank O inflate Offer % (>100%) for small-volume leaders —
  alias cleanup offered, not yet approved.

### Vantura status rules split from the fleet (8/23 late)

Carlos: Vantura master = TERMINATION-DRIVEN ONLY. Changes in
daily_update_fill/run.py (deployed, Lucy 2 update queued):
- `NO_SALE_ACTIVE = {"Carlos Hidalgo"}` — empties sellers AND roster in
  sync_statuses for the master: NO sale=>Active of any flavor there (the
  WeekData-all-history seller set had resurrected 132 ex-reps; that rule
  STAYS on the 11 captainship boards, per Carlos).
- terminated_names: RC name-column header now matches 'Roll Call' (exact —
  containment would hit the tab title) in addition to 'Rep Name'. That
  unlocked the VA's OWN 151 'Terminated' Status marks on Vantura's Roll
  Call -> 223 terminated names detected (was: RC branch silently dead).
Ran live: 50 flips, DU Actives 162->122, funnel ACTIVE NOW total 142->98.
Remaining ~90 stale Actives were never marked Terminated anywhere — the
lever is now RC marks (VA marks -> nightly flips); no bulk flip without
Carlos's say-so.

## 8/24 board reshape + Roll Call automation (11 boards + template, NOT Vantura)

`scripts/board_reshape_aug24.py` (idempotent; guards on B46='% on the Board'):
- **Sales Board**: one row inserted at 46 (old 46+ shifted down); **r45 =
  LAST WEEK (M.D)** day-totals row (chip bg, boxed) — REFRESHED EVERY
  MORNING by captainship_boards/update_board (code deployed; computes from
  WeekData keys '|<last WE>'), so after the Monday roll the new board still
  answers "what did we do last Tuesday". The **Averages block (Avg by
  Lead / Avg by Rep / Week 2-4, K50:P51 post-shift) is REMOVED** per
  Carlos. Medium-ink boxes added: % block B47:H51, Headcount K47:P48, TEAM
  B54:E63; % rows 24px tall.
- **Roll Call**: basicFilter on header row 2 (A2:N250); blank '2nd
  Rounder' (E) and 'Week Ending' (A) backfilled from the DU (N; R ->
  week-ending Sunday label) — 39 cells filled fleet-wide, typed values
  never touched.
- **rollcall_sync** in daily_update_fill (runs nightly 8:45 after
  sync_statuses; `NO_ROLLCALL_SYNC={"Carlos Hidalgo"}` — the master keeps
  its manual flow): DU rows with T='Showed To CR' AND orientation within
  the last 14 days that are missing from the RC append as
  [WE, 'New Start', campaign(mode of col C), name, DU 2nd Rounder]; rows
  with Status='New Start' whose WE < current week's Sunday flip to
  'Active'; blank E/A cells keep backfilling. Historical CR marks skipped
  (dry-run wanted +53 on Justin; with the guard: Justin +31 real recent
  starts, Jamis +4, Kinsey +17). First live run: tonight 8:45 PM.
- **Stations**: Justin's stray A1 "Hello, everyone" cleared; banner/section
  coloring verified intact.
- Confirmed schedules: captainship_boards 6:30 AM daily (order log ->
  boards; Monday roll = B2 WE flip + WeekData archive, first live roll
  8/24), daily_update_fill 8:45 PM, indeed_source_report 4am/12pm/5pm,
  Focus Report = part of the 6:30 run, Leaders Retention = pure formulas
  (recalcs live off the DU; no job needed).

### 8/23 evening — boards fill moved to Lucy 2's 4 AM BATCH

The 6:30 AM card NEVER FIRED: card_scheduler fires only within
[time, time+20min) with NO catch-up, and Lucy 2 sleeps at 6:30 (cards get
no wake; the machine wakes for the day-orchestrator's 4am batch and stays
up from ~8 via the resume pusher). Carlos wants EARLY, so the fix is the
orchestrator: schedule_config.json `captainship_boards` now on_scheduler
true, machine Lucy 2, cadence daily, **order 10001** (dead-last in the
Tableau wave ON PURPOSE — it shares the 9246 CDP Chrome with att_order_log)
, base_args ['--write'], timeout 25. Lands ~6:00-7:00 AM daily; orchestrator
handles wake, retries, and failure alerts. The Report Library card keeps
its Run button but its schedule was stripped (no double-runs). Also
learned: queue `rerun <id>` runs registry DEFAULTS (dry-run) — use
`rerun captainship_boards --write` for a live manual kick. Any future card
scheduled before ~8 AM on Lucy 2 will silently never run — register such
jobs with the orchestrator instead.

## 1on1 headcount backfill (8/24) — Focus rows 32-34 from "AT&T B2B 1 on 1's"

Workbook 1sxauFjNjq4_rRYM2PAl5cyOyHF3Hg4OkO-t_hLKDJB8 (Caitlyn/NextLevel's;
tabs are '<Name> <office id>'; Jamis's tab is mislabeled 22358). Rows are
dated by the MONDAY 1:1 meeting -> map to our week-ENDING label minus one
day (their 8/17 row = our WK 8/16 — the "817 vs 816" Carlos flagged). Cols:
B Active -> r32 Head Count, C Leaders -> r33, E Training -> r34 (D Dist
ignored). `scripts/oneonone_hc_fill.py` (plan|apply) wrote ~728 cells
across all 11 MT tabs (Jan 4 - Aug 16 2026; blank 1:1 weeks skipped; 2025
history predates the MT columns; WK 8/23 untouched until their 8/24 row
exists). Verified: Joshua 8/17 row (19/16/7) -> MT WK 8/16 = 19/16/7.
1:1 values WIN over typed cells. NOT automated — rerun the script after
Mondays to pull the newest row, or ask Carlos if he wants it scheduled.

## 8/24 misc: org Focus backfill · Setup verdict · RC week-endings · Stations dropdowns

- **Carlos's own HC/Leaders/Training**: org dashboard 'Focus Report' ✎ rows
  read hidden 'Campaign Log' keyed `manager|yyyy-mm-dd|slot` (J key, K mgr,
  L date, M slot 3=HC/4=Leaders/5=Training, N value; date = week-ending
  SUNDAY from row 2). One-time backfill of 72 rows (2026 weeks 1/4-8/16)
  from his 'Carlos Hidalgo 11580' 1on1 tab (scriptless, in-session). NO
  automation on purpose — Carlos maintains it by hand now.
- **Setup tab: KEEP.** Data validations on Sales Board, Roll Call AND Daily
  Update reference Setup ranges (it feeds the leader/trainer dropdown
  lists). Deleting it breaks pickers on three tabs.
- **Roll Call Week Ending, everyone**: blanks remained where the DU had no
  orientation date (pre-backfill reps). Filled fleet-wide (228 cells, 0
  left blank) from each rep's EARLIEST WeekData week = first week on the
  board.
- **Stations dropdowns fleet-wide** (Vantura already had them): A6:A25
  Territory Status ONE_OF_LIST (need new t / extension needed / New T given
  / T Extended / good); B6:F25 Leader + Rep #1-4 ONE_OF_RANGE
  '=Stations!$G$6:$J$25' (the auto REP POOLS: G Rep List, J New Starts).
  Names reach the pools via the auto formulas; people get PICKED into
  car-ride rows via the new dropdowns.

## Stations mechanics — full port (8/24, deep-read of Vantura's tab)

How Vantura's Stations WORKS (now replicated fleet-wide):
- Pools are LIVE FILTERs (already on the boards): Rep List = SB roster
  minus Terminated; New Starts = Roll Call Status='New Start' with no Date
  Gone. TERMINATION = people fall out of the pools automatically; while an
  RC row says Terminated the pool name shows RED.
- Car-ride grid B6:F25 and stations grid K6:P25 both pick from the pools
  via ONE_OF_RANGE '=Stations!$G$6:$J$25' dropdowns (typing part of a name
  autocompletes the full name — that's native dropdown behavior; free-text
  like 'jaiden' matches nothing, which is what broke placement counting).
- Pool coloring (Vantura had it HAND-PAINTED; fleet gets CF so it self-
  maintains): gray D9D9D9 in a car ride, blue CEE1F3 in a station, green
  C6EECE in both, red F4CCCC RC-terminated. Legend chips G3:J3 painted.
- Territory Status colors (Vantura palette): good / T Extended / New T
  given = B7E0B7; extension needed / need new t = FFEA99.
- Duplicate placement (same name in two car rows or two stations) = bold
  red text.
Applied by the 8/24 fleet pass (saved as scripts/stations_mechanics.py,
idempotent — deletes the tab's CF and re-adds). Vantura untouched.
- 8/24: DU col F 'Campaign' now auto-stamped 'AT&T B2B' by daily_update_fill
  appends on the 11 boards (NOT Vantura — B2B+BOX there, VA sorts it);
  1,350 existing blank F cells backfilled fleet-wide.
- 8/24 late: SB blank-rep basicFilter (NOT_BLANK on col B, rows 4-43) set
  fleet-wide AND re-applied by update_board on every morning write; to add
  someone by hand, Data > Remove filter, type into a blank slot (rare — the
  order log auto-adds anyone with a sale). SB rep table got Vantura-style
  full grid borders (thin inner 9AA5B1, medium ink outline + header/TOTAL
  rules). Empty-DU mystery (Jeff/Dhyey/Vincent) CONFIRMED source-side:
  harvester logs in + opens their offices fine, but their retention reports
  have no interview weeks (offices new 8/19, teams not using AppStream 2Rs);
  DUs fill automatically the day they start logging interviews.
- 8/24: Setup tab HIDDEN on all 11 boards + template (Carlos — "don't see
  the point"). NOT deleted: SB/RC/DU dropdown validations still read its
  ranges. Unhide via right-click any tab > Setup if a leader list needs
  editing. Future nice-to-have: repoint those dropdowns to living sources
  (Stations rep pools / DU 2nd Rounders), THEN delete.
- 8/24: Jeff/Dhyey/Vincent AppStream offices individually CONFIRMED empty
  (login + office switch fine; retention report has no interview weeks).
  Their DUs seeded from board data — SB reps as Active + RC New Starts as
  Showed to Classroom, campaign stamped (Jeff 10, Dhyey 25, Vincent 21).
  Interview columns stay blank until their teams use AppStream; nightly
  dedup + status sync maintain the seeded rows either way.
- 8/24: DU columns U+ (BGC/Logins, Blueink) DELETED on 10 boards + template
  (Carlos: useless for the captainship). KEPT on Atef's board and Vantura.
  Safe: automations + LR helpers only touch A-T.

## Board sharing (8/24) — each owner is WRITER on their own board

Emails harvested from Carlos's calendar invites (B2B Training / Monday
Night B2B Call attendee lists). The owner<->email map (also the map the
future Slack support bot needs):
  Jackie LeRoy    jackieleroyatt@gmail.com
  Justin Wood     justinryanwood.93@gmail.com
  Joshua Murphy   murphjjm@gmail.com
  Jamis Garay     jamisgaray18@gmail.com
  Dhyey Patel     pateldhyeyb@gmail.com
  Jeff Starr      jeffcstarr@gmail.com
  Kinsey Guenther kinseyguenther@gmail.com
  George Hipolito georgehipolito2@gmail.com
  Atef Choudhury  atefchoudhury349@gmail.com
  Joey Ramirez    joeyrmz2002@gmail.com
  Vincent Smith   vincentsmith24.att@gmail.com
Each shared WRITER on their own board ONLY (Drive MCP share_file). Nobody
got the dashboard/template/master. Google emailed each an invite.

### Monday roll bug + fix (8/24)

FIRST LIVE MONDAY ROLL FAILED: the orderlog-not-ready clean exit (added by
the incident tooling the same morning) returned BEFORE update_board, so an
empty Monday export skipped the entire roll — boards sat on WE 8.23. Fixed:
empty export now proceeds with an empty dataset (B2 flips, LAST WEEK row +
total, Field Status ages, filters re-apply, Focus columns roll; sales fill
later). Plus a MINI launchd job com.carlos.captainship-monday-topup
(Mondays 18:05 CT, script scripts/monday_topup_queue.py) queues a
`rerun captainship_boards` so Monday's sales land Monday evening instead
of Tuesday 4am.
- 8/24: dashboard Focus Report picker fixed — the bound Apps Script still
  had GRID_TAB='Manager Trend' from before the tab rename, so onEdit
  ignored every B1 change (stuck on last-loaded owner). Repasted the .gs
  (local copy dashboard_sync.gs updated too, GRID_TAB='Focus Report') via
  Chrome; verified live: B1 -> George flipped the whole grid instantly.
