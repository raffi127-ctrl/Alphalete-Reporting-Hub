# Carlos 1on1s — Focus Report OPT/Metrics source map

Where every row in the Carlos sheet's OPT + financial sections comes from.
The recruiting-pull section (rows 2-20) is already wired via the shared
`recruiting_report` module with `CAPTAINSHIP=Carlos` (Phase A, shipped
2026-05-20). This doc covers the OPT block (rows 26-50) and financial
block (rows 52-58).

Sheet: https://docs.google.com/spreadsheets/d/1KLF8diMJ8pwIQWW9IqN7CL288t1l9VGUKxzBcMl8Of4/

## Source key

- **Tableau (auto-scrape)** — pulled from the listed view + column
- **Manual entry** — humans fill it; automation MUST NOT overwrite
- **Formula** — the cell holds an `=...` formula; automation MUST NOT
  overwrite (would clobber the formula)
- **Computed** — Python does the math in the runner before writing the
  resulting VALUE (no formula written)
- **Emailed Excel** — the existing `financial_report` module's pull

## OPT block — rows 26-50

| Row | Sheet label                          | Source                                                                                                            |
|----:|--------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| 26  | (section header "OPT")               | —                                                                                                                 |
| 27  | Headcount                            | **Manual entry**                                                                                                  |
| 28  | Leaders                              | **Manual entry**                                                                                                  |
| 29  | Active Headcount on Tableau          | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · column **Rep Count**                                                  |
| 30  | New starts in classroom              | **Manual entry**                                                                                                  |
| 31  | New Starts by EOW                    | **Manual entry**                                                                                                  |
| 32  | New Start Retention (OPT-block)      | **Formula** — depends on row 30/31; leave alone                                                                   |
| 33  | New Internets                        | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · column **New intrnt**                                                 |
| 34  | Voice Sales                          | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · column **voice count**                                                |
| 35  | Wireless                             | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · column **wrls sales**                                                 |
| 36  | New Lines                            | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · column **AIR/AWB Sales**                                              |
| 37  | Total Apps                           | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · column **totals** (already sum of 33+34+35+36)                        |
| 38  | AVG Apps Per Active Headcount        | **Computed**: row 37 / row 29 (Python writes the value, NOT the formula)                                          |
| 39  | AVG New INT Sales                    | **Computed**: row 33 / row 29 (Python writes the value, NOT the formula)                                          |
| 40  | National AVG Apps                    | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · **bottom totals row** column **Sales / Rep** — single value, same on all 32 Carlos tabs |
| 41  | Scorecard Ranking                    | Tableau · `ATTTRACKER-B2B / D2D1-PAGERV3` · column **rank**                                                       |
| 42  | Personal Production                  | **TBD — Eve confirming.** Likely the same Raf-pipeline view: `ATTTRACKER2_1-D2D / PRODUCTSALESSUMMARY4WK` filtered on each Carlos ICD's rep name. Update this row once Eve confirms. |
| 43  | 0-30 Day Cancel Rate                 | Tableau · `ATTTRACKER-B2B / B2BCancelRates` · column **6 Week average**                                           |
| 44  | Activation / Approval %              | Tableau · `ATTTRACKER-B2B / ACTIVATIONRATES` · column **31-60 Days**                                              |
| 45  | 0-30 Day Churn                       | Tableau · `ATTTRACKER-B2B / CHURNRATES` · column **0-30 Day Churn**                                               |
| 46  | 30 Day Churn                         | Tableau · `ATTTRACKER-B2B / CHURNRATES` · column **30 Day Churn**                                                 |
| 47  | 60 Day Churn                         | Tableau · `ATTTRACKER-B2B / CHURNRATES` · column **60 Day Churn**                                                 |
| 48  | 90 Day Churn                         | Tableau · `ATTTRACKER-B2B / CHURNRATES` · column **90 Day Churn**                                                 |
| 49  | 120 Day churn                        | Tableau · `ATTTRACKER-B2B / CHURNRATES` · column **120 Day churn**                                                |
| 50  | Penetration Rate                     | Tableau · `ATTTRACKER-B2B / MARKETPERFORMANCEZIPLEVEL` · column **Actual Pen %**                                  |
| 51  | Direct Deposit                       | Tableau · `DirectDepositICDVIEWVersion2_0 / PROGRAMSUMMARY` · column **Grand Total to ICD**                       |

## Financial block — rows 52-58

| Row | Sheet label             | Source                                                                                                 |
|----:|-------------------------|--------------------------------------------------------------------------------------------------------|
| 52  | Total Funds Available   | **Emailed Excel** — existing `financial_report` module. Needs Carlos's sheet added to its output list. |
| 53  | Owners Payroll          | (same)                                                                                                 |
| 54  | Operating %             | (same)                                                                                                 |
| 55  | Indeed                  | (same)                                                                                                 |
| 56  | Total Expenses          | (same)                                                                                                 |
| 57  | Owners Withdrawal       | (same)                                                                                                 |
| 58  | Profit/Loss             | (same)                                                                                                 |

## Tableau views referenced (unique URLs)

| Workbook / view                                   | Used for rows | URL |
|---------------------------------------------------|---------------|-----|
| `ATTTRACKER-B2B / D2D1-PAGERV3`                   | 29, 33-37, 40, 41 | https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/D2D1-PAGERV3 |
| `ATTTRACKER-B2B / B2BCancelRates`                 | 43            | https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/B2BCancelRates |
| `ATTTRACKER-B2B / ACTIVATIONRATES`                | 44            | https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/ACTIVATIONRATES |
| `ATTTRACKER-B2B / CHURNRATES`                     | 45-49         | https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/CHURNRATES |
| `ATTTRACKER-B2B / MARKETPERFORMANCEZIPLEVEL`      | 50            | https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/MARKETPERFORMANCEZIPLEVEL |
| `DirectDepositICDVIEWVersion2_0 / PROGRAMSUMMARY` | 51            | https://us-east-1.online.tableau.com/#/site/sci/views/DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY |
| `ATTTRACKER2_1-D2D / PRODUCTSALESSUMMARY4WK` (?)  | 42 (TBD)      | https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK |
