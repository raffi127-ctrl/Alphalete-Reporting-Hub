# Alphalete Org 1on1s — per-campaign OPT data sources

The Alphalete Org sheet has rep tabs grouped by campaign (NDS / B2B / BOX /
Retail / JE / Frontier). Each campaign uses its OWN Tableau view/workbook —
unlike Raf's or Carlos's reports which each have a single all-reps view.

Source: Eve's video walkthroughs (logged here as she shares each one).

---

## NDS (D2D) — partially mapped (Megan, 2026-05-20)
**Tableau URL:** https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1
**Workbook:** `NDS-SNRES-ATT-OOFWorkbook`
**View / worksheet:** `NDSDailyTracker`

Reps (visible):
- Isaiah Revelle, Colten Wright, Drew Tepper, Jairo Ruiz, Khalil Mansour,
  Maxamed Aden

These reps are NOT in Raf's existing "AUTOMATION PULL ICD" Tableau view, so
Raf's `opt_phase.py` pipeline can't fill them. The view above is the
NDS-scoped equivalent.

**Metric mapping (confirmed so far):**
| Sheet metric | Tableau column | Per-rep or shared |
|---|---|---|
| Active Selling Heads | Rep Count | Per-rep |
| Scorecard Ranking | Ranking | Per-rep |
| National AVG for sales | New/Port per Rep (total avg) | **Shared across all NDS tabs** |

**Manual / formula entries (per Megan, not automated):**
- Headcount, Leaders, New starts in classroom, New Starts by EOW (all manual)
- New Start Retention (formula on the manual cells)

**Second NDS view — DropshipV_2 / SARAPLUSSALESSUMMARY (Megan, 2026-05-20):**
**URL:** https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/SARAPLUSSALESSUMMARY

| Sheet metric | Tableau source |
|---|---|
| Personal Production | ICD name row (only present if the ICD has sales logged) |
| New Lines | New/Port Lines total |

~~Same view also drives the Rep Breakdown chart~~ — **corrected (Megan, 2026-05-20):** the Rep Breakdown chart at the bottom of each NDS tab actually comes from a DIFFERENT view: `NDS-SNRES-ATT-OOFWorkbook / ProductSalesSummaryRep / REPEXPANDED` (custom view, iid=2).

**Rep Breakdown chart — NDS:**
- **URL:** https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/b86d7862-bfc7-4966-a0a4-7803432a6444/REPEXPANDED?:iid=2
- **Filter:** Wireless only (every rep row shows `WIRELESS` in the "Product Type (Broken Out)" column)
- **Header on sheet:** `WE M.D` (e.g. "WE 5.17")
- **Columns:** Rep | Product Type (Broken Out) | Mon | Tue | Wed | Thu | Fri | Sat | Sun | Product Total
- **Reps sorted by Product Total desc.** Top row = daily totals + grand total.
- **Same format already established on Raf's report** (Hasani Lynch tab → "Production Breakdown" pattern). Reuse `automations/production_breakdown/run.py` if compatible, or clone the formatting routine.

**Third NDS view — NDSWeeklyMetricsRep / THISWEEK (Megan, 2026-05-20):**
**URL:** https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/NDSWeeklyMetricsRep/2a63e621-b4cb-423f-9a46-75e56abca9a3/THISWEEK?:iid=1
*(Same workbook NDS-SNRES-ATT-OOFWorkbook; different view; "THISWEEK" is a saved custom view that scopes to the current week. Need a LASTWEEK / equivalent for the just-completed-week target.)*

| Sheet metric | Tableau column | Per-rep or shared |
|---|---|---|
| 0-30 Day Cancel Rate 4wk avg | Cancel Fraud Review % | **Total % for office (shared across NDS tabs)** |

**Fourth NDS view — DropshipV_2 / ACTIVATIONRATES (Megan, 2026-05-20):**
**URL:** https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/ACTIVATIONRATES?:iid=1

| Sheet metric | Tableau column |
|---|---|
| Activation % by Week | 60+ Days (% value) |

**Fifth NDS view — NDS-SNRES-ATT-OOFWorkbook / CHURNRATES / THISWEEK (Megan, 2026-05-20):**
**URL:** https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/c289786d-e0d4-4de7-825a-264c21e133c1/THISWEEK?:iid=1
*(Same workbook as NDSDailyTracker + NDSWeeklyMetricsRep; THISWEEK is a saved custom view.)*

| Sheet metric | Tableau column |
|---|---|
| 0-30 Day Churn | (column name matches our label exactly) |
| 60 Day Churn | (matches) |
| 90 Day Churn | (matches) |

**Sixth NDS view — NDS-SNRES-ATT-OOFWorkbook / LeadPenetrationOverview / THISWEEK (Megan, 2026-05-20):**
**URL:** https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/LeadPenetrationOverview/a15a85ac-e0c8-423d-ba85-6be048203b0b/THISWEEK?:iid=1

| Sheet metric | Tableau column |
|---|---|
| Total Leads | Lead Count — **sum across all rows assigned to that ICD** (per-rep aggregation) |

**Seventh NDS view — DropshipV_2 / SARAPLUSSALESSUMMARY iid=2 (Megan, 2026-05-20):**
**URL:** https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/SARAPLUSSALESSUMMARY?:iid=2
*(Same workbook DropshipV_2 used for Personal Production + New Lines; iid=2 picks a different worksheet within the view.)*

Both are COMPUTED metrics (ratios), per office. Numerator + denominator come from this view's office totals:

| Sheet metric | Formula |
|---|---|
| Next Up % | (office "Next Up" count) / (office "New/Port Lines" count) — percent |
| Extra/Premium % | (office "Premium/Elite" + "Extra") / (office "New/Port Lines") — percent |

**Direct Deposit — shared across ALL programs (Megan, 2026-05-20):**
**URL:** https://us-east-1.online.tableau.com/#/site/sci/views/DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY/15c897de-6162-469b-9ef7-1735d235f2a8/DOWNLINEVIEW?:iid=1
*(Same workbook + DOWNLINEVIEW custom view used for Carlos's DD scrape. Note: prior Carlos run only saw 3 ICDs from this view due to permission scoping — may need access broadened, or "No Access" marker for unscoped ICDs.)*

| Sheet metric | Tableau column |
|---|---|
| Direct Deposit | Grand Total to ICD (per-ICD value) |

This applies to **every campaign** (NDS / B2B / BOX / Retail / JE / Frontier).

**AVG Apps Per Active Headcount — computed metric (Megan, 2026-05-20):**

| Sheet metric | Formula |
|---|---|
| AVG Apps Per Active Headcount | `New Lines / Active Selling Heads` (look both values up by their label cells — DO NOT hardcode row positions per [[feedback_no_hardcoded_columns]]) |

**All NDS metrics now mapped.** Pipeline can be built once the week-scoping decision is locked in.

**⚠ Week scoping warning (Megan):** "we are mid week on this data pull so
we need to ensure we're collecting the correct data / entering in the
correct place". The NDS Daily Tracker view shows current-day values; the
runner needs to scope to the just-completed week's WE Sunday (e.g. Mon 5/25
→ fill column 5/17, not in-progress 5/24).

---

## B2B — pending
Megan to share walkthrough / Tableau URL.

Reps (visible): Valeria Tristan

Per Lizette Ruiz's tab structure (hidden but inspected), B2B uses Carlos-style
metrics: New Internets, Voice Sales, Wireless, New Lines, Total Apps,
Penetration Rate, AVG New INT Sales — distinct from D2D's "Active Selling
Heads / AVG Apps Per Active Headcount" framing.

---

## BOX (Box Energy) — partially mapped (Eve, 2026-05-20)
**Tableau workbook:** `V2P box energy`
**Worksheet:** `V2P box energy daily tracker`
**URL:** *(pending — Megan to share)*

Reps (visible): Ryan Mcspadden, Roshan Amin Ahmad, Benjamin Burden

**Metric mapping** (sheet row label → tracker source):

| Sheet metric | Source | Per-rep or shared |
|---|---|---|
| Active Selling Heads / rep count | Tracker → rep count column | Per-rep (e.g. Ryan = 14) |
| Total customers / New Lines | Tracker → "22"-style cell | Per-rep |
| National AVG for sales | Tracker → orange row (avg across all reps) | **Shared across all 3 BOX reps** |
| National AVG kilowatts | Tracker → kilowatts row | **Shared across all 3** |
| Accepted average | Tracker → accepted average column | Per-rep (e.g. Ryan = 55) |
| Direct Deposit | Tracker → DD column | Per-rep |

Notes:
- Workbook recently changed — values used to be formula-driven, now are
  direct entries Eve types in. Automation will replace the manual type.
- Ryan has 2 financial summaries (Colorado + Texas) — covered by the separate
  financial pull video, not the OPT box video.

---

## Retail — pending
Megan to share walkthrough / Tableau URL.

Reps (visible): Boaktear Chowdhury (Akib/MJ), Ronald Dawson

---

## JE (Just Energy) — Tableau-based (Eve walkthrough 2026-05-24)
Reps (visible): Cinthya Reyes (only rep for now)

**Workbook:** "Just Energy Sales, Staffing & Productivity" (Eve types "JE"
in Tableau search → opens this workbook). Filter: ICD name = Cinthya;
Week Ending = default latest (correct).
**URL: still needed** — Eve didn't paste it; ask for the workbook + the
"track by rep" conversion view URLs.

Fillable from Tableau:
- **Sales by store** — per-store sale counts (sum across the week's days),
  + Total Store Count + Headcount (people per store, summed). Example
  week: stores 6265=9, 8248=1, etc.; store count 3, ~6 people. (New
  stores appear week to week — handle dynamically like Retail Costco.)
- **Conversion** — a SEPARATE "track by rep" view, filtered to Cinthya
  (filter auto-selects a few reps; remove + reselect her). It's the
  **4-week average** — Eve selects 5 week-endings in the picker so the
  latest (incomplete) week-ending doesn't dilute it, leaving 4 complete
  weeks. (Same "select 5 to get 4" trick the NDS Cancel 4wk-avg uses.)

NOT from Tableau (email / manual):
- **Financials / Direct Deposit** — Program Summary email
- **Personal Production** — not visible in JE Tableau (leave blank)

---

## Frontier (Frontier Internet) — EMAIL/PDF only, NO Tableau (Eve 2026-05-24)
Reps (visible): Abel Draper (Ben) (only rep for now)

**There is no Tableau for Frontier.** Everything comes from email + PDFs,
so automating it needs Gmail + PDF parsing — a different toolchain than
the Tableau scrape pattern. Sources:
- **"Frontier Events Daily Sales Scorecard"** email — two attached PDFs:
  - *Events by Store* PDF → per-store sales + headcount (e.g. store
    2144 = 6 sales / 3 heads; 2299 = 4 sales / 2 heads). Sum heads
    across stores for Total Headcount.
  - *Metrics* PDF → JIG (100% / 123.1), ABB (100%), etc. — the green
    figures are 4-week averages.
- **Direct Deposit** — from the weekly bulletin (Eve copies Abel's
  latest deposit). Not in the scorecard email.
- **Approval / Consult / Pending** — a DIFFERENT email (scorecard/quality);
  inconsistent, pull from the latest. Approval e.g. 85.7%.

Automation approach (future): Gmail search for the scorecard email →
download PDFs → parse tables. Heavier lift; sequence after JE.
