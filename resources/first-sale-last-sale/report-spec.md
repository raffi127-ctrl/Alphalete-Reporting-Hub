# First Sale / Last Sale + Production Breakdown — report spec

The final section of the focus report. Its **own report run** (like the
financial report) because it depends on an emailed Excel the user uploads
first. Sources: Eve's walkthrough video + Megan's files/links (2026-05-18).

## Destination
- **ATT Program - Focus Report**. Run **Mondays**.
- The section sits on each ICD tab as **two stacked tables**:

## Which report fills which table (Megan, 2026-05-19)
The two tables have different sources, so split them between two report runs:

- **Table 1 (First Sale / Last Sale)** — fills from the emailed `.xlsx`.
  Stays in this dedicated **"First Sale / Last Sale" upload report**
  (one-table report; user uploads the file as preflight).
- **Table 2 (Production breakdown by rep)** — fills from the
  **PRODUCT SALES SUMMARY** Tableau view. Built into the existing
  **ATT Program - Focus Report (Raf)** OPT run — no upload needed; just
  another Tableau crosstab download on the same run.

Each report = one source pattern (upload vs. Tableau), no mixing.

## Two stacked tables — visual

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

## Week-offset rule (Megan, 2026-05-19)
**Table 1 (first/last sale) is always 1 week behind the report's current
week.** When the report is on WE 5/17, this table fills the **WE 5/10**
column. The header `WE <date>` in the section must be **re-set each run** to
the table's actual week — not left static. The emailed Excel's sheet is named
to match (`B2B.D2D First Last Sale WE 5.10.2026`), so the sheet-name date IS
the week the data fills.

Table 2 (production) stays on the report's current week — no offset.

## Filename pattern of the uploaded .xlsx
The user (Megan / Eve) uploads the emailed Excel as a preflight. **The
filename carries the week**, e.g. `B2B.D2D First Last Sale WE 5.10.2026.xlsx`
(period-separated date, year included). The fill **parses the filename** to
learn the target week — don't trust the upload's modified date.

Inside that file are the 3 channel tabs (`B2B Firs.Last Sale`,
`RES IF First.Last Sale`, `RES OOF First.Last Sale`) — those are the data
sources for Table 1.

## Channel assignment (Megan, 2026-05-19)
**Each ICD is in only 1 channel.** No per-ICD mapping doc needed — the fill
searches the owner's name across all 3 channel tabs; whichever tab has their
block IS their channel. (If an owner ever appears in 2 tabs, surface that as
an error rather than silently merging.)

## Open questions (Megan)
- **Production view:** confirm the AUTOMATION PULL view exposes per-rep,
  per-day, per-product counts, and how to scope to one office's reps.
