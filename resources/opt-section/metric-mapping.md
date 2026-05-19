# OPT + Metric-Goals — Tableau → Google Sheet mapping

The build spec for the OPT-section automation. Accumulated from Megan as we
map each Tableau view. Data is pulled by automating Tableau's
**Download → Crosstab (CSV)** (the numbers render on a canvas — not DOM).

---

## Source view: "AUTOMATION PULL"

- Workbook: **ATT TRACKER 2.1 - D2D**
- View: **D2D 1-PAGER V4**, sheet **"AUTOMATION PULL"**
- URL: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/D2D1-PAGERV4/05356558-3732-4a96-af9d-99ee56f98138/AUTOMATIONPULL
- One row per ICD; columns are the metrics below.

### Google Sheet — OFFICE GOALS / OPT section (section 2)

| Sheet row label | Tableau column header | Notes |
|---|---|---|
| Active Headcount on Tableau | `Rep Count` | |
| New Internets | `New Internet` | |
| Upgrades | `Upgrd Internet` | |
| DTV | `Video Sales` | |
| New Lines | `Wrlss Lines New/Port` | |
| % of Wireless Rep Count | `% wireless rep count` | |
| Scorecard Ranking | `Ranking` (header truncated as "Ra…") — rank by office production | |
| Total Apps | — | **Formula:** New Internets + Upgrades + DTV + New Lines |
| AVG Apps Per Active Headcount | — | **Formula:** Total Apps ÷ Active Headcount on Tableau |
| National AVG Apps | total/average of the `Sales Per Rep Avg` column | same value for every ICD |

**Formula rule (Megan):** formula rows must NOT be hardcoded to fixed row
numbers — look up the component rows by their column-B label each run, so it
still works if the template's row order ever changes.

**National numbers (Megan):** National AVG Apps and National New INT AVG are
country-wide totals — the SAME value is written to every ICD tab, not a
per-ICD number. Pulled from Tableau's total/average row.

### Google Sheet — METRIC GOALS section (section 3)

| Sheet row label | Tableau column header |
|---|---|
| 1 GIG% | `New int 1 gig + mix %` |

---

## Confirmed — test download (2026-05-17)

- In the AUTOMATION PULL view's **Download → Crosstab** dialog, the sheet to
  pick is **"ICD Summary - ATT (V2)"** (current week; "(LW)" = last week).
- Downloaded file: **UTF-16, tab-delimited**, one row per ICD.
- ICD name column: **"ICD Owner Name"** — values are ALL CAPS.
- National/total row: **"Grand Total"** — its `Sales Per Rep Avg` cell is the
  National AVG Apps value.
- Columns present: ICD Owner Name, Ranking, Rep Count, Sales Per Rep Avg,
  % Wireless rep count, New Internet, Upgrd Internet, Video Sales,
  Wrlss Lines New/Port, New Internet ABP Mix %, Tech Install %,
  New Internet 1Gig+ Mix%, % of Orders After 7:30PM.

## Fill rules

- **Raf Hidalgo's tab** has an extra section other tabs don't — find the
  "OPT" section anchor in column B and scope the label lookup within it;
  never assume fixed row numbers.
- **Never delete existing data** — the fill only writes OPT metric cells.
- Preview on the **Marcellus Butler** tab first, before rolling out to all.

---

## Source view 2 — AUTOMATION PULL (Internet Only)

- View: **D2D 1-PAGER V2 (Internet Only)**, sheet "D2D PAGE 1 THIS WEEK
  (Internet Only)".
- URL: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/D2D1-PAGERV2InternetOnly/9a35d92c-65c1-4d12-ba6c-ebc381e1d00c/AUTOMATIONPULL
- Same pattern as the ATT view — Download → Crosstab → the INT ICD-summary
  sheet.

OFFICE GOALS / OPT section:

| Sheet row label | Tableau column | Notes |
|---|---|---|
| AVG New INT Per Active Headcount | `New Int Per Rep Average` | per-ICD |
| National New INT AVG | total/avg of `New Int Sales Per Rep Avg` column | national — same value every tab |

## Source view 3 — PRODUCT SALES SUMMARY 4WK

- URL: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK
- Different pull pattern — NOT a one-shot crosstab:
  - Must select the correct **week ending** first.
  - In the **rep filter**, search the ICD's name (their personal production).
  - Sheet row **"Personal Production"** holds a text value like
    `1 NI / 1 DTV / 1 Wireless / 1 UG` (NI = new internet, DTV = video,
    UG = upgrade). One value per ICD.
- The Focus Office ATT report already pulls from this view
  (`step7_download_tableau.py`) — reuse that machinery.

## Source view 4 — Metrics

- URL: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/Metrics
- Sheet "Metrics". The **"Week's Metrics" filter must be set to "this week"**.
- Crosstab columns (per JD's old `_Internet_Metrics` import):

| Sheet row label (Office Metrics section) | Tableau column |
|---|---|
| 6+ days out scheduled | `% of sales scheduled 6+ days out (4 wks)` |
| 0-30 Day Cancel Rate | `0-30 day new internet cancel rate` |
| 30-60 activation rate % | `30-60 day new internet activation rate` |

(Megan describes the 6+ days value as a hover tooltip on the "Install
Scheduled 6+ Days New Internet Count (4 wk)" column — but the crosstab
download exposes it directly as the `% of sales scheduled 6+ days out`
column. Confirm on the first pull.)

## Source view 5 — Captain's Bonus  ✅ BUILT

- Custom view: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/CaptainsBonus/96f8a0ef-a1fc-48c8-9669-e39cdffa4d7e/AUTOMATIONPULL-CAPTAINS
- The Crosstab dialog has **no single sheet** — data is split into one
  **"CB Appr + Churn (<captain>)"** sheet per captainship team. All five
  (Aron, Pat, Raf, Starr, Wayne) are downloaded and merged into one ICD lookup.
- Each sheet's columns: `Captain's Bonus Teams v2`, `ICD Owner Name`,
  `60 Day New Internet Churn Rate`, `Rolling 4 Weeks`.

| Sheet row label (Office Metrics section) | Source |
|---|---|
| Activation /Approval % | `Rolling 4 Weeks` column |
| 30-60 Day Cancel Rate | computed: 100% − Activation/Approval % |

- **Date handling — confirmed 2026-05-18:** the view has a "Weekending"
  *parameter* (a dropdown, a new date added weekly). It is NOT URL-overridable
  (`?Weekending=` is ignored). BUT the "CB Appr + Churn" sheets are a **rolling
  4-week metric** — verified identical at week 5/2 vs 5/16 — so they are
  always current on their own. **No date override is needed.** (The
  "CB Activations" sheets DO follow the parameter, but we don't pull those.)

## Source view 6 — CHURN

- URL: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/CHURN
- Crosstab sheet: **"ICD Churn"** (the ICD BREAKOUT — not the national average).
- The "Churn View" filter must be **New Internet** (the view currently
  defaults to Wireless — its dialog shows "ICD Churn (Wireless)").
- All values are % on the Google Sheet (Office Metrics section):

| Sheet row label | Tableau column |
|---|---|
| 0-30 Day Churn | `0-30 Day Churn` |
| 30 Day Churn | `30 Day Churn` |
| 60 Day Churn | `60 Day Churn` |
| 90 day Churn | `90 day Churn` |

## Filter-setting note

The ATT / INT / Product Sales pulls are clean because they point at
**"AUTOMATION PULL" custom views** Megan saved with filters pre-set. The
Metrics / CHURN / Captain's Bonus views are base views — their filters
aren't locked. Cleanest fix: save an AUTOMATION PULL custom view of each
with the correct filter, then the report pulls them with zero filter code.

## Source view 7 — Fiber Lead Performance  ⏸ BLOCKED — needs a Tableau-side per-office sheet

- Base view: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/FiberLeadPerformance
- Custom view: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/FiberLeadPerformance/a79fd021-3606-4aa2-bf55-bc3856cdac99/AUTOMATIONPULL-NICHURNVIEW
- Per-ICD numbers live on the **"Office New Fiber Lead Penetration By Zip"**
  worksheet: set the **"Owner Name"** filter to an ICD, and the **Grand Total**
  row gives that ICD's Lead Count / Expected Fiber Sales (copy) / Total Sales /
  Assigned Fiber Lead Penetration.

| Sheet row label (Office Metrics section) | Source (Grand Total row) |
|---|---|
| Penetration Rate | `Assigned Fiber Lead Penetration` |
| Total Leads | `Lead Count` |
| Expected Fiber Sales (120 days, 17wks) | `Expected Fiber Sales (copy)` |
| Expected Fiber Sales Weekly | computed: Expected Fiber Sales ÷ 17 |

**⚠️ BLOCKED — all automated paths exhausted (2026-05-18):**
- **Crosstab export:** the "Office New Fiber Lead Penetration By Zip" sheet's
  Download button stays disabled (too many marks). Dead.
- **Dashboard scrape:** the table is canvas-rendered — not in the page DOM.
- **Download → Data** (the View Data window — works for Program Summary):
  here it's disabled until a worksheet is clicked; once activated, the whole
  by-zip sheet's View Data is **9,225 rows** (≈1,819 zips × ~5 measures) — far
  too big to scroll-scrape. The View Data window's own "Download" button
  (`download-data-Button`) is **non-functional via automation** — clicking it
  produces no file, no event, no dialog.
- The "Penetration View" dropdown options are `Office Penetration by Zip`,
  `Days Since Last Sale`, `Market Expectations` — **no per-office option**.
- Per-ICD filtering works (one ICD → ~30-50 zips → small View Data) but is
  ~52 separate pulls ≈ 50 min/run — too slow.

Root cause: every Fiber worksheet is **per-zip**; there's no per-ICD summary
sheet (Program Summary worked because its data is naturally ~64 per-ICD rows).

**Recommended fix (Tableau-side):** ask whoever owns the *Fiber Lead
Performance* workbook to add a **per-office (one row per ICD) summary
worksheet** with Penetration Rate / Total Leads / Expected Fiber Sales — or an
AUTOMATION PULL custom view of it. That sheet would crosstab-export or
View-Data cleanly and wires in minutes. Until then Fiber Lead is the one
OPT row group that can't be auto-pulled.

## Source view 8 — Program Summary (Direct Deposit)

- Workbook: **Direct Deposit ICD VIEW Version 2.0**, view PROGRAM SUMMARY.
- Custom view (filter "downline or captain" = Captain): https://us-east-1.online.tableau.com/#/site/sci/views/DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY/639b7ff1-d2ed-49ae-a85d-b96a0787a1e9/CAPTAINVIEW
- Direct Deposit ← the Grand Total value, assigned to the ICD.

## Source view 9 — Wireless Metrics (Metrics workbook)

- Custom view: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/Metrics/23910d52-35aa-4b2d-95f5-8d96649a7b0d/AP-WIRELESSMETRICS
- Filters baked in: "Metrics view" = Wireless metrics, "weeks metrics" = This week.
- Writes the **Wireless Metrics** section (a separate section anchor).

| Sheet row label | Tableau column |
|---|---|
| BYOD Lines | `BYOD Lines (Metrics)` |
| BYOD % | `BYOD Line % (Metrics)` |
| New Lines | `New Lines (Metrics)` |
| New Lines % | `New Line % (Metrics)` |
| Approval % (Rolling 4 weeks) | `Approval % (Rolling 4 Weeks)` |
| 30-60 Activation Rate | `30-60 Activation Rate` |
| 0-30 day cancel Rate | `0-30 day wireless cancel rate` |
| 0-30 day Wireless Cancels | `0-30 day wireless cancels` |
| Extra / Preimum Plan % Metrics | `Extra/Premium Plan % (Metrics)` |
| Next up % | `Next Up % (Metrics)` |
| **Insurance %** | ⚠️ source TBD — Raf to confirm where to pull it from; ask to add later |

## Source view 10 — Wireless Churn (CHURN workbook)

- Custom view: https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/CHURN/e4e438a7-c289-4128-a89a-8b5beec41baa/AP-WIRELESSCHURN
- Filter baked in: "Churn view" = Wireless churn view.
- Writes the **Wireless Metrics** section's churn rows (distinct from the
  Office-Metrics churn rows): 0-30 / 30 / 60 / 90 Day Churn ← the ICD Churn
  crosstab's `0-30 Day Churn` / `30 Day Churn` / `60 Day Churn` /
  `90 Day Churn` columns (parse like the New-Internet CHURN view).

---

## Still to map

**Leave alone — the automation must NOT write these** (Megan, 2026-05-18):
- *Manual rows* — filled live in the 1-on-1 report review with the ICD and
  Raf: **Headcount, Leaders, New starts in classroom, New Starts by EOW.**
- *Sheet formula* — **New Start Retention** is a Google Sheets formula
  (New starts in classroom vs New Starts by EOW); leave the cell intact.

**Still awaiting a data source** (Megan to map): **Green Leads**, plus any
other still-blank rows in the Metric Goals / Wireless sections — incl.
**Insurance %** (Raf to confirm its source).

**Next group to build — financial / P&L section** (Megan queued 2026-05-18,
source TBD): Total Funds Available, Owners Payroll, Total Expenses, Indeed,
Owners Withdrawal, Profit/Loss, Operating %. Source not yet given — likely
ownerville's Office P&L page, a Tableau view, or sheet formulas; confirm
which per row.
