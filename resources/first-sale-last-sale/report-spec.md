# First Sale / Last Sale + Production Breakdown — report spec

The final section of the focus report. Its **own report run** (like the
financial report) because it depends on an emailed Excel the user uploads
first. Sources: Eve's walkthrough video + Megan's files/links (2026-05-18).

## Destination
- **ATT Program - Focus Report** (Megan confirmed). Run **Mondays**.
- The section sits on each ICD tab as **two stacked tables**:

**Table 1 — First Sale / Last Sale** (header `WE <date>`)
| Week Avg | First Sale Avg Office | Last Sale Avg Office | Order Count |

Rows: `Week Avg`, then `Sunday … Saturday`. ← from the emailed Excel.

**Table 2 — Production breakdown by rep** (header `WE <date>`)
| Rep | Product Type (Broken Out) | Monday … Sunday | Product Total |

Rows: a `Total` row, then one row per rep, sorted by Product Total
descending. ← from the PRODUCT SALES SUMMARY Tableau view.

⚠️ The two tables can be on **different weeks** — in the live sheet Table 1
showed `WE 5.10` while Table 2 showed `WE 5.17` (first/last sale lags).

## Source 1 — emailed Excel (uploaded as preflight)
- e.g. `B2B.D2D First Last Sale WE 5.17.2026.xlsx`.
- **3 sheets, one per channel:** `B2B Firs.Last Sale`,
  `RES IF First.Last Sale`, `RES OOF First.Last Sale`.
- Columns A-G: Channel | Captains | Owner Name | Week Avg (period label) |
  First Sale Avg Office | Last Sale Avg Office | Order Count.
- Per **Owner Name**: a block of up to 8 rows — `Week Avg` + each day that
  had sales. Times are real time values; Order Count is an integer.
- → for an ICD tab, find that owner across the 3 sheets and copy their block
  into Table 1.

## Source 2 — PRODUCT SALES SUMMARY (Tableau, auto-pulled)
- View "PRODUCT SALES SUMMARY", AUTOMATION PULL custom view:
  https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/1ea6a190-e1a9-4f68-a71d-3ebf08ec7498/AUTOMATIONPULL-NICHURNVIEW
- Same workbook as OPT Source view 3 (PRODUCT SALES SUMMARY 4WK).
- Gives per-rep, per-day counts broken out by product → fills Table 2.

## Per-owner variation
- Most owners: **New Internet** breakout only.
- Some owners (e.g. Hasani): **New Internet AND Wireless** breakout.
- A few owners have a special chart tracking specific reps under a senior's
  office; deleted once that rep launches their own office.
- → the fill keys off whatever Product Type rows already exist on each tab —
  never hardcoded.

## Open questions (Megan)
- **Week offset:** the emailed file is `WE 5.17` but the live Table 1 showed
  `WE 5.10` — does first/last sale lag the production table by a week? Which
  week does the WE 5.17 file fill?
- **Channel:** how is an ICD assigned to B2B / RES IF / RES OOF — from the
  tab, or just search all 3 sheets by owner name?
- **Production view:** confirm the AUTOMATION PULL view exposes per-rep,
  per-day, per-product counts, and how to scope to one office's reps.
