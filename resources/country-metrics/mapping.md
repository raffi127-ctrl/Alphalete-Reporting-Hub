# Country Metrics — Tableau → Google Sheet mapping

Build spec for `automations/country_metrics`. Fills the **Country Metrics** tab
of the ATT Program - Focus Report (real Sheet
`1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE`). Data is pulled by automating
Tableau's **Download → Crosstab (CSV)** via the unattended patchright session
(`opt_phase.download_crosstab`).

---

## Tab layout

One stacked block per section, each with the same ~17 metric rows. Section
header in **column A**; weekly **WE-Sunday** date headers in **row 1** (and
repeated in each section's header row). The target week's column is found by
matching its date in row 1 — never by a fixed index.

| Section (col A) | Meaning |
|---|---|
| COUNTRY | Whole-company total (Tableau "Grand Total") |
| RAF / STARR / ARON / PAT / WAYNE | Captainships (Tableau "<Name>'s Team") |
| SAM | Captainship added 2026-05-28 (cloned from WAYNE; header pink `#E91E63`) |

**Labels live in column A** here (not B, unlike the per-ICD ATT template).

---

## Sources

| Source | View / sheet | Notes |
|---|---|---|
| **Metrics** | `ATTTRACKER2_1-D2D/Metrics`, crosstab sheet **"Metrics Call Last week data (Internet)"** | Grouped by `Captain's Bonus Teams` (Grand Total + one `… \| Total` row per team). **Filter `Week's Metrics` MUST be `Last Week`** (URL param `?Week's Metrics=Last Week`) — we fill one week behind. Also supplies the owner→team roster. |
| **PRODUCT SALES SUMMARY 4WK** | `.../PRODUCTSALESSUMMARY4WK/3a00519d-…/ALLREPS`, week-filtered via `Sale Date Week Ending (mon-sun)=<WE Sunday>` | sheet **"Product Sales Summary by ORG"** = COUNTRY product totals; sheet **"Sales By ICD (Weekly View)"** = per-owner products + per-owner weekly total. |
| **Order Log** | `.../ORDERLOG/117748c0-…/ALLREPS`, `Start/End Date` params | ONLY to add each owner's **AIR** orders to the >=100 threshold (PRODUCT SALES omits AIR + VOICE). |

---

## Row → source mapping

Written for **all 7 sections** (COUNTRY = Grand Total row; others = team `Total` row):

| Sheet row (col A) | Source column |
|---|---|
| Rolling 4 weeks | Metrics `Rolling 4 Weeks` |
| 30-60 Day Activation Rates | Metrics `30-60 day New Internet activation rate` |
| 0-30 Day New Internet Churn Rates | Metrics `0-30 day new internet churn rate` (the **churn** col, not "cancel rate") |
| New Internet ABP Mix (%) | Metrics `New Internet ABP Mix % (Metrics)` |
| New Internet 1gig+ Mix % | Metrics `New Internet 1Gig+ Mix% (Metrics)` |
| Jep New Internet Count (4 wk) | Metrics `Jep New Internet Count (4 wk)` |
| % of sales scheduled 6+ days out | Metrics `% of sales scheduled 6+ days out (4 wks)` |
| New Internet Count | PRODUCT SALES — `NEW INTERNET` (COUNTRY: by-ORG; teams: by-ICD summed via roster) |
| Upgrade Internet Count | PRODUCT SALES — `UPGRADE INTERNET` |
| Video Sales | PRODUCT SALES — `VIDEO` |
| Wireless | PRODUCT SALES — `WIRELESS` |

Written for **captainships + SAM only** (COUNTRY rolls up by formula):

| Sheet row | Source |
|---|---|
| Total Owners in Captainship | count of the team's owners present in PRODUCT SALES by-ICD |
| Owners Over 100 | count of those owners whose weekly units (4 PRODUCT SALES products **+ AIR** orders) >= 100 |

---

## Never written (Sheet formulas / intentional blanks)

- **AT&T AIR** — left blank (Eve, 2026-05-28). AIR exists only in the Order Log; not broken out in PRODUCT SALES.
- **VOICE** — no row; not counted anywhere.
- **Sales (ALL)** — Sheet formula `=sum(<products>)`.
- **AVG Units per Owner** — Sheet formula `=IFERROR(SalesAll/TotalOwners,0)`.
- **% of Owners over 100** — Sheet formula `=IFERROR(OwnersOver100/TotalOwners,0)`.
- **COUNTRY** Total Owners / Owners Over 100 — Sheet formulas summing the captainships (incl. SAM).

The fill reads the target column with FORMULA render and **skips any cell that
holds a formula**, as a hard guard on top of the above.

---

## Cadence + behavior

- **Runs Thursdays**, filling the most-recently-finished week (WE Sunday). The
  column is located by its row-1 date, so consecutive Thursdays advance to the
  **next** column on their own; re-running the same week **overwrites** that
  column (idempotent), never duplicates.
- A new week's column **inherits the prior week's formatting** (borders, bold,
  number formats) via a `PASTE_FORMAT` copy from the column to its left.
- **Name mismatches → ICD Aliases sheet.** e.g. `Patrick Thompson` (PRODUCT
  SALES) → `Pat Thompson` (Metrics roster). Resolved via
  `focus_office_att.aliases`.

---

## Run

```
python -m automations.country_metrics.run                  # most-recent WE Sunday
python -m automations.country_metrics.run --week 2026-05-24
python -m automations.country_metrics.run --skip-download   # reuse cached crosstab CSVs
```

`setup_sam.py` is a one-time helper that adds the SAM section (clone a
captainship block + recolor header + extend COUNTRY's owner-sum formulas).
