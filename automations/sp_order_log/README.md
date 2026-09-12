# sp_order_log — the SaraPlus-sourced AT&T B2B order log + activation overview

Built 2026-09-10 → 2026-09-14 with Carlos, in one long working conversation.
This README is the full record of that conversation — what was asked, what was
tried, what turned out to be true, and where everything stands — written so
the work can be continued (in the B2B Metrics thread or a fresh session)
without re-deriving any of it.

---

## 1. What this is

Two of the sections Carlos reads every morning in his **B2B Metrics** Slack
thread were built from Tableau's ATTTRACKER-B2B ORDERLOG extract:

* **#8 — AT&T Order Log**: the Excel workbook uploaded to the thread
  (All Reps / Pending by Rep / Paycheck by Week / one tab per rep).
* **#9 — Activation Report Overview**: the two-week PNG (LAST WEEK / THIS
  WEEK side by side, per-rep Posted / Cancelled / Still Open, colour-banded).

Tableau's DTR feed runs **days behind** reality. SaraPlus (the dealer portal
the orders are actually entered in) is near-live. Carlos (2026-09-12):

> "Tableau is always delayed. SaraPlus updates a lot sooner, which is why I
> want to recreate it through SaraPlus."

`automations/sp_order_log/` rebuilds BOTH deliverables from SaraPlus and,
since 2026-09-14 (Carlos: *"This is perfect. Let's have this replace the one
that was being made through Tableau"*), **is the live source for Carlos's two
sections in the B2B Metrics thread** via `b2b_metrics/capture.py`, with the
old Tableau path kept as an automatic fallback. Other offices (Atef, Jamis,
Sabrina) still use Tableau — the SaraPlus login is Carlos's dealer only.

The rendering code was deliberately NOT rewritten: this module reshapes
SaraPlus data into the exact per-line dicts the Tableau pipeline produced and
calls the same builders (`att_order_log.xlsx.build`,
`att_order_log.payout.build_week_tables`, `box_order_log.png.render`). Same
look, same tabs, same colours — different, fresher source.

---

## 2. How the data flows (one run)

All on **Lucy 2** (SaraPlus creds + browser profile live there; see §7).

1. **Login** — rides `rc_contact_sync`'s machinery unchanged: Carlos's
   SaraPlus login (`~/.config/recruiting-report/saraplus-creds-b2b.json`),
   the already-verified Chrome profile
   (`automations/uploaded/.saraplus_b2b_profile`), and the emailed-passcode
   flow (codes land in alphaletereporting@gmail.com, read via
   `gmail-app-password`).
2. **Sales Order History CSV** — Analytics → Detail Reports → Sales Order
   History, date range = last 31 days (same window as the Tableau log),
   Customer Type **Both** (defaults to Residential — leaving it loses every
   B2B order), Submit, then the native **CSV export button**
   (`MainContent_ImgCSV`). One file, every rep, ~115 columns including
   per-product statuses. No grid scraping.
3. **Wireless per-line report** — same session, the **Wireless panel** (tab
   index "2" on the Reporting Hub tab strip): its own date range
   (`rdpWirelessStartDate/EndDate`), Submit, then its Excel export
   (`btnExportWirelessExcel`) → "Wireless Resolution Report.xls" — every
   wireless order expanded into its **individual lines** (Line / Line Type /
   Device Type / Line Number / Device / Plan / **Line Status** / Ship Date /
   Delivered Date / Port Status).
4. **The activation-date tracker** (`wireless_lines.py`, §4) — folds today's
   per-line statuses into a state file; produces `{line → activation date}`.
5. **Shaping** (`run.py shape_lines`) — one Tableau-style line dict **per
   unit**: wireless orders from the per-line report (fallback: fan-out by
   the grid's line count), internet/voice/video from the SOH CSV.
6. **Building** — the untouched house builders produce the workbook and the
   PNG.

## 3. Counting rules (all Carlos's calls)

* **One unit = one line/application** (Carlos 2026-09-12: "count each
  individual product sold, each unit sold, each application sold as one
  activation or one post"). A 4-line order that activated = 4 Posted.
* **"Posted"** is the activated word (his own rule from the original log:
  keep the label Posted). SaraPlus per-line "Active" → **Posted**, dated by
  the tracker. Everything in-flight keeps SaraPlus's word, coloured yellow
  by his posted=green / in-flight=yellow / terminal=red logic
  ("Delivered", "Shipped", "Porting Issue", "Port Approved", "Pending …").
  "Cancelled"/"Disconnected" (and "Active/Cancelled", "Active/Disconnected"
  — activated then churned) → the plain terminal word, red, dated by cancel.
  Extra SaraPlus spellings are colour-registered **at runtime** in
  `run.py:_EXTRA_COLORS` — `att_order_log/colors.py` itself is untouched.
* **Products**: AIA / gateway / Inseego devices → `AIR/AWB`; iPad/tablet →
  `TABLET`; else `WIRELESS`; internet orders → `NEW INTERNET` (1 unit each).
* **Weeks**: Sun–Sat, same `payout.week_bounds` arithmetic as always.
  Posted & Cancelled are week figures by (tracked) activation date; Still
  Open is all-time in-flight, identical in both tables — unchanged
  semantics from the original.

## 4. The activation-date problem and the tracker

**The problem.** Pay follows *each line's own activation date* (proved
against the actual DD, §5). SaraPlus exposes only:

* order-level `Wireless Active Date` = the FIRST line's activation (fanning
  all lines onto it mis-weeks multi-line orders both directions — proven
  with Ester Perez / Eriberto Salgado traces);
* per-line **status right now** (card + Wireless report) — but never a
  per-line activation **date**. Hunted exhaustively 2026-09-12: SOH grid,
  the View Customer card (its "Order History" button is a who-viewed log,
  not a status log), and the Wireless panel. It is not there.

**The tracker** (`wireless_lines.py`). Since the report runs daily, it
*records the flip itself*: a line's activation date = the day it first shows
"Active" in the Wireless report. State:
`~/.config/recruiting-report/sp_line_activations.json` on Lucy 2 —
`{line key: {first_active, src, status, order_id, last_seen}}`, pruned at
120 days. Line key = the line's 10-digit phone number (fallback
`<orderid>#L<idx>`). `first_active` is **never overwritten** once stamped.

Date sources, in trust order (`src` field):
1. `live` — the tracker saw the flip. Exact. All dates converge here.
2. `tableau` — on first adoption of an already-active line: Tableau
   ORDERLOG's per-line posted date, joined by TN (`spe.TN`), read from the
   newest `output/b2b_metrics/_shared/orderlog_*.csv` on Lucy 2. Accurate
   for settled history (Tableau's only sin is the live edge).
3. `order` — no TN match: the order's first-activation date. Approximate;
   superseded naturally as live flips accrue.

**Convergence:** day-one history inherits Tableau's lag; every day after is
observed truth. Within ~a week the trailing week is pay-true on its own.

## 5. The reconciliation story (read this before doubting any number)

* The morning Tableau image for the settled week 8/30–9/5 said **75** posted.
* The DD that paid that week (Friday 9/12) was checked against the Vantura
  board's hidden **"RAW"** tab (the payroll prep's DD DETAIL load, week key
  "9.6", Campaign `B2B-ATT-SBS`). **Critical gotcha:** each activated line
  appears there as TWO `Category=WIRELESS` rows — a **Base** row (OOF/IF,
  the real payout) *plus* an **Add On** row (Port/BYOD fee) — plus bonus
  rows. Count **only `Commission Type = "Base"`** rows as units. A first
  pass counted 132 by summing both components; that number was wrong and
  briefly made the morning report look like it undercounted a paid week.
* Counting Base rows only: the DD paid **75 lines** (56 wireless + 12 AIR +
  5 internet + 2 tablets), every activation date inside 8/30–9/5.
* The SaraPlus tracked report's first run also showed **75** for that week.

**DD 75 = Tableau 75 = SaraPlus 75.** Settled weeks agree everywhere; the
SaraPlus version's entire edge is the live week (its first run already
showed 64 posted for the in-progress week that Tableau hadn't surfaced).

## 6. What runs where

* **In the thread (live):** `b2b_metrics/capture.py` →
  `order_log_workbook()` and `payout_image()` call
  `sp_order_log.run.build_artifacts()` for **Carlos only** (one SaraPlus
  pull per batch, cached in `_SP_ARTIFACTS`), writing the runner's standard
  filenames (`ATT Order Log MM-DD-YYYY.xlsx`, `activation_overview.png`).
  Any failure logs and **falls back to the Tableau path** — the thread never
  goes without its sections. The Tableau fallback also carries the
  totals-keys remap fix for box png 31ddeb9d's TOTAL-strip change (that
  change would otherwise KeyError every office's #9).
* **Manual:** `lucy rerun sp_order_log` (registry entry, `on_scheduler:
  false`, base_args `--push`) — full build + base64 relay of both artifacts
  into the control sheet's **"SP XLSX"** / **"SP AR Shot"** tabs for the
  mini to decode. Offline: `--from-file <soh.csv> --wireless-file <report.xls>`.
* **Probing:** `lucy rerun sp_status_probe` — the read-only exploration tool
  that found everything (`--export`, `--wireless`, `--view-orders`,
  `--tab-arg`); writes to "SP Status Diag" + shot tabs. Keep it — it is how
  the next SaraPlus question gets answered without a Loom.

## 7. Operational gotchas (each cost a failed run)

* **Everything runs on Lucy 2** through the Mini Control sheet queue
  (~2-min poller latency, single-threaded — a long report ahead of you
  blocks your row; queue rows serially and read results from the row).
* **SaraPlus passcode challenge**: once per browser profile, can
  double-issue codes and die on an empty picker page — a plain re-run
  clears it. Page loads are occasionally flaky (`networkidle` goto timeout)
  — retry before debugging.
* **The CSV/Excel export buttons answer the POST with the file** — click
  with `no_wait_after=True` inside `expect_download` or the click hangs on
  a navigation that never completes.
* **The Wireless .xls is nested HTML tables** and the nesting makes naive
  `<table>` regexes double-count — walk `<tr>`s in document order and dedupe
  per order (`wireless_lines.parse_wireless_xls`).
* **The View Customer RadWindow reuses its iframe** and can briefly show the
  previous customer — only trust a frame carrying the order id you asked for.
* **Customer Type autoposts back and resets the dates** — write the dates
  again after setting it. Telerik date pickers need `_set_telerik_date`,
  never `fill()`.
* **Diag/relay tabs are overwritten by each run** — snapshot "SP Status
  Diag" before queueing a second probe.
* The DD "RAW" tab Base/Add-On double-row trap — §5.

## 8. Key files

| File | What |
|---|---|
| `automations/sp_order_log/run.py` | pull → track → shape → build; `build_artifacts()` is the runner API; `main()` the CLI |
| `automations/sp_order_log/wireless_lines.py` | Wireless report pull + parser, the activation-date tracker + state, the Tableau TN seed |
| `automations/rc_contact_sync/status_probe.py` | the read-only SaraPlus probe (`sp_status_probe`) |
| `automations/rc_contact_sync/sara.py`, `config.py` | SaraPlus login/session machinery (shared with the RingCentral contact sync) |
| `automations/b2b_metrics/capture.py` | the thread integration: SaraPlus-first for Carlos, Tableau fallback |
| `~/.config/recruiting-report/sp_line_activations.json` (Lucy 2) | the tracker state |
| Control sheet tabs `SP XLSX`, `SP AR Shot`, `SP CSV`, `SP Status Diag`, `SP Grid/Cust Shot*` | base64/diag relay Lucy 2 → mini |

## 9. Open items

1. **Watch the first scheduled mornings** — `lucy logtail b2b_metrics
   SARAPLUS 30` should show both Carlos sections taking the SaraPlus path;
   the fallback line firing instead means the pull failed (usually the
   passcode/flaky-load gotchas).
2. **Convergence check (~2026-09-21)**: after a week of daily flips, compare
   a settled week against the DD Base-row count again; expect equality.
3. **Optional**: seed pre-tracker HISTORY from the DD RAW tab's true
   activation dates (join rep+customer, multiset assignment) — makes the
   current lookback pay-true immediately instead of converging. Not built;
   decided unnecessary once 75=75=75 reconciled, but the approach is sound
   if an older backfill is ever wanted.
4. **Tablets** currently classify as WIRELESS unless the device name says
   iPad/tablet — cosmetic vs the DD's TABLET category; totals unaffected.
5. The standalone `sp_order_log` manual entry and the relay tabs stay as
   the debug path; retire if unused after the thread swap beds in.

## 10. Conversation timeline (for continuity)

* **9/10** — Read the RingCentral automation (`rc_contact_sync`) and the
  B2B Metrics activation overview; probed SaraPlus Sales Order History
  (found all status columns on the grid; statuses verified against Tableau
  DTR on all 9 orders of 9/3); proved the native CSV export carries the
  whole office/week in one file.
* **9/12** — Rebuilt both deliverables from SaraPlus (order-level first: 34
  vs 75 discrepancy traced to per-order vs per-line counting); Carlos ruled
  per-unit counting; per-line statuses found on the customer card, then the
  Wireless panel + its export; DD pulled as ground truth; per-line
  activation dates proven absent from SaraPlus → the flip tracker built,
  seeded, and shipped.
* **9/14** — The 75-vs-"132" gap forensically resolved (DD Base vs Add On
  rows — no missing sales; all three sources reconcile at 75). Carlos:
  replace the Tableau versions. `b2b_metrics/capture.py` swapped to
  SaraPlus-first for Carlos with Tableau fallback (+ the totals KeyError
  fix for all offices). This README written.
