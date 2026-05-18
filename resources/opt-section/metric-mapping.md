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

---

## Still to map

OPT rows not yet covered: Headcount, Leaders, New starts in classroom,
New Starts by EOW, New Start Retention, Green Leads. Plus the rest of the
Metric Goals + Wireless sections. Awaiting Megan's mapping.
