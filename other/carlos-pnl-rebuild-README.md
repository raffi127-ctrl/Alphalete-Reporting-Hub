# Business & Personal P&L (Weekly) — rebuild guide

This package lets another Claude rebuild Carlos Hidalgo's automated P&L Google Sheet for a different
owner, **pixel-for-pixel**: same tabs, same colors, same fonts, same centering, same headers, same
formulas, same automation. It was produced by reading the live workbook through the Sheets API on
2026-10-21, so everything here is what is actually on the sheet, not a description from memory.

```
Carlos PNL README/
├── README.md                     ← this file (read all of it first)
├── spec/
│   ├── 00_summary.json           ← tab list (order, sizes, freezes, tab colors)
│   ├── 00_Dashboard.json … 15_Balances.json
│   │                             ← EXACT per-tab dump: every cell's value/formula + format (hex colors,
│   │                                font, size, bold, alignment, number format, borders), column widths,
│   │                                row heights, merges, conditional-format rules, data validation,
│   │                                basic filter, charts
│   ├── apply_spec.py             ← rebuilds the whole workbook from those JSON files into a NEW sheet
│   │                                (tested: the rebuilt copy was byte-identical on every sampled cell)
│   ├── dump_pnl_spec.py          ← the script that produced the JSON (re-run against any sheet)
│   └── make_tables.py            ← turns the JSON into the readable tables below
├── tables/                       ← one markdown file per tab: every cell with its formula and format
├── code/
│   ├── automations/carlos_finance/categorize.py      ← bank-transaction rules engine
│   ├── automations/carlos_finance/tiller_sync.py     ← Tiller → Ledger daily sync + calendar roll
│   ├── automations/carlos_payroll_pull/run.py        ← Apex payroll export (Thursdays)
│   ├── automations/carlos_security_ledger/run.py     ← Tableau security ledger + captain bonus + weekly override + balances
│   ├── deploy/*.sh                                   ← the three wrapper scripts the schedulers call
│   ├── launchagents/*.plist                          ← macOS launchd schedules
│   └── schedule_config_excerpt.json                  ← the Lucy 2 orchestrator entries
```

**The fastest exact rebuild is: run `spec/apply_spec.py`, then swap in the new owner's details
(section 9).** Everything else in this README explains what you are rebuilding so you can adapt it
correctly.

---

## 1. What the sheet is

One Google Sheet, 16 tabs. Three automated feeds land raw data on "data tabs"; every number the
owner looks at is a formula over those tabs. Nothing is typed by hand except two cells on the
`Raf Loan` tab.

| Feed | Lands on tab(s) | How often |
|---|---|---|
| **Tiller** bank feed (10 bank/card accounts, read from Tiller's own Google Sheet) | `Ledger`, plus `Balances` (account balances) | daily |
| **Tableau** (Smart Circle / SCI): NetSuite Security Ledger, DD Detail (captain's bonus), ORG Override Summary | `Security Ledger`, `Captain Bonus (Tableau)`, `Override Weekly (Tableau)` | daily |
| **Apex** payroll (apex.herbjoyent.com) CSV export | `Payroll (Apex)`, `Apex Net Pay Detail` | Thursdays 1 pm |

Design rules the owner insisted on (keep them):

1. **Every number must trace to a bank statement or the Tableau security ledger.** No estimates.
2. Weeks run **Sunday–Saturday**; a week is identified by its **Saturday** ("Week Ending"). Months are
   text `YYYY-MM`.
3. **Newest period on the left.** Column C is the week in progress, column D the latest full week,
   column B is year-to-date.
4. **Captainship bonus and standard overrides are separate income lines.** They never count toward
   Direct Deposit or the operating %.
5. **Security (the SCI security balance) is treated as one of the owner's accounts.** Overrides are
   income when SCI credits them to Security; wires from Security to checking are transfers, not income.
6. Personal and business are kept apart; a business expense on a personal card (or vice versa) is
   **flagged**, shown on `Review`, and still counted on the correct side.
7. Short labels, little wording, colored boxed sections, centered numbers.

---

## 2. Global look & feel (apply to every tab)

| Thing | Value |
|---|---|
| Font everywhere | **Inter** (set `fontFamily: "Inter"` on every formatted cell; the specs carry it per cell) |
| Body text | 10 pt, color default black `#1F2933` on the Dashboard tables |
| Secondary / note text | 9 pt italic, `#727A84` (P&L tabs) or `#6B7280` (Dashboard) |
| Section header bands (P&L tabs) | white bold 10 pt on a solid color: navy `#11213F`, green `#1C6B47`, amber `#B77214`, teal `#19667F`, dark green `#287F5B`, red `#9E2D2D`, slate `#596072`, grey `#8C939E` |
| Column header row (P&L tabs, row 4) | bg `#11213F`, white bold 10 pt, centered; week dates formatted `mmm d` |
| Input rows under a band | light tint of the band color (see §4) |
| Subtotal rows | bg `#EDF2F7`, bold |
| Total rows | bg `#DBE5EF`, bold |
| Headline rows (GROSS PROFIT, CLOSING BALANCE, NET PROFIT…) | bg `#E0F4E5`, bold 11 pt |
| Negative headline turns red | conditional format `NUMBER_LESS 0` → bg `#FCE5E5` on rows GROSS PROFIT, CLOSING BALANCE, NET PROFIT OR LOSS, NET PROFIT (earned), NET CASH MOVEMENT (columns B..AS) |
| Money format on P&L tabs | accounting, no cents: `_($* #,##0_);[Red]_($* (#,##0);_($* "-"_);_(@_)` |
| Money format on data tabs | accounting with cents: `_($* #,##0.00_);[Red]_($* (#,##0.00);_($* "-"_);_(@_)` |
| Money on the Dashboard | plain, centered: `$#,##0;[Red]-$#,##0;"–"` (tables) and `$#,##0;-$#,##0` (tiles) |
| Percent | `0.0%` |
| Dates on data tabs | `mmm d, yyyy` |
| Alternating row shading on P&L tabs | every second data row has bg `#F6F7F9` in the week columns |
| Gridlines | hidden on Dashboard, Business Weekly, Business Monthly, Personal Weekly, Review, Raf Loan, Balances; shown on data tabs |
| Tab colors | Dashboard & Tableau/Apex data tabs amber `#F2A533`; Business Weekly/Monthly navy `#112140`; Personal Weekly & Balances green `#338C59`; Review red `#D85933`; Ledger/Rules/Accounts/Sources grey `#727A84`; Raf Loan purple `#8C4CB2` |

Exact tab order, sizes, freezes and colors are in `spec/00_summary.json`.

---

## 3. Dashboard (tab 0) — what the owner opens

63 rows × 60 cols, first 5 rows frozen, gridlines hidden, **page background deep navy `#042C53`**
(every cell outside the tiles/tables, columns A→BH, is navy). Column widths: A=170, B=110, C…I=140,
rest 100. Helper columns P:Q:R are hidden (they feed the chart).

### Header (rows 1–5)
- **A1:H1** merged: `Carlos — Weekly Dashboard` — white, bold, 20 pt, centered, row height 46.
- **A2:H2** merged: subtitle, italic 10 pt `#B5D4F4`, centered.
- **A3:H3** merged: `=E4` (the "data through" line) italic 9 pt `#B5D4F4`, centered. (E4 holds the
  real formula and is colored navy-on-navy so it's invisible.)
- **A4** `Week ending (Saturday) — defaults to this week` bold 10 pt `#B5D4F4`, right-aligned.
- **B4 = the week picker.** Value `='Business Weekly'!C4` (the in-progress week). Data validation
  `ONE_OF_RANGE ='Business Weekly'!$C$4:$AS$4` with dropdown UI. Format: bg `#FFF7D6`, 12 pt,
  centered, date `mmm d, yyyy`, **thick amber frame** `SOLID_THICK #EF9F27` on all four sides.
  Every tile and table below reads `$B$4`.
- **C4** `=TEXT(B4-6,"ddd mmm d")&" – "&TEXT(B4,"ddd mmm d, yyyy")` white 10 pt.
- **E4** `="Data through →  Bank: "&TEXT(MAX(Ledger!A:A),"mmm d")&"   ·   Security ledger: "&TEXT(DATEVALUE('Security Ledger'!O1),"mmm d")&"   ·   Apex payroll: period ending "&TEXT(MAX('Payroll (Apex)'!B:B),"mmm d")&"   ·   Captain bonus: DD week "&TEXT(MAX('Captain Bonus (Tableau)'!A:A),"mmm d")`
- Row 5 (`Prior week`, `=B4-7`) is kept but hidden by navy text on navy, height 6.

### The tile grid (rows 7–19)
Four rows of four tiles. Each tile = two merged cells wide (A:B, C:D, E:F, G:H), label row + value
row. Spacer rows 7, 11, 14, 17 are 4 px; row 10 is 2 px; row 6 is 8 px.

| Row pair | Label row (26 px) | Value row (48 px) | Group color: fill / label text / value text / frame |
|---|---|---|---|
| 8–9 | Business checking · Personal checking + savings · Security at SCI · TOTAL CASH AVAILABLE | balances | blue `#E6F1FB` / `#185FA5` / `#0C447C` / `SOLID_THICK #378ADD` |
| 12–13 | Total credit card debt · Spending this week (no payroll) · Indeed this week · N charges · TOTAL FUNDS AVAILABLE | | amber `#FAEEDA` / `#854F0B` / `#633806` / `SOLID_THICK #EF9F27` |
| 15–16 | Direct deposit this week · Captainship bonus · Gross profit · operating % · Net profit | | green `#EAF3DE` / `#3B6D11` / `#27500A` / `SOLID_THICK #639922` |
| 18–19 | Override earned last week · Override waiting to be paid · Last override payment · Next payment expected | | purple `#EEEDFE` / `#534AB7` / `#3C3489` / `SOLID_THICK #7F77DD` |

Tile formatting: label = bold 11 pt, centered, vertical **BOTTOM**; value = bold **22 pt**, centered,
vertical **TOP**, number format `$#,##0;-$#,##0` (E16 is text, E13 is `$#,##0;-$#,##0`). Each tile has
its thick colored frame on all four sides; adjacent tiles share the line, which gives the "box grid".

Conditional formats on the tiles (custom formulas, applied to the label+value pair):
- every tile: `=AND(ISNUMBER($X$<valuerow>),$X$<valuerow><0)` → bg `#FCEBEB`, text `#791F1F` (whole tile turns red when negative)
- G12:H13 and G15:H16 (Total funds available, Net profit): `…>=0` → bg `#EAF3DE`, text `#27500A` (turns green when positive)

Tile formulas (all in `tables/00_Dashboard.md`; the pattern is):
```
Business Weekly lookup:
=INDEX('Business Weekly'!$A$1:$AAC$300,(MATCH("<row label>",'Business Weekly'!$A$6:$A$300,0)+5),MATCH($B$4,'Business Weekly'!$4:$4,0))
Balances lookup:
=INDEX(Balances!$C:$C,MATCH("<account name>",Balances!$A:$A,0))
```
- A9 business checking · C9 personal checking + two savings (three lookups added) · E9 `Business Security (SCI)` · G9 `TOTAL CASH`
- A13 `TOTAL CARDS OWED` · C13 `=-<TOTAL EXPENSES> + SUMIFS(Ledger G, week=$B$4, category "Commissions & Wages (ADP)") + SUMIFS(… "Payroll Taxes (ADP)")` (spending without payroll) · E12 label `="Indeed this week  ·  "&COUNTIFS(Ledger!$H:$H,"Recruiting - Indeed",Ledger!$B:$B,$B$4)&" charges"`, E13 `=-<Recruiting - Indeed>` · G13 `TOTAL FUNDS AVAILABLE`
- A16 `Direct Deposit` · C16 `Captainship Bonus` · E16 `=TEXT(<GROSS PROFIT>,"$#,##0;-$#,##0")&"  ·  "&TEXT(<Operating %>,"0.0%")` · G16 `NET PROFIT (earned)`
- A19 last week's standard override from `Override Weekly (Tableau)` (`SUMIFS` on the MAX week) shown as `$8,167  ·  wk 9/27`
- C19 override waiting to be paid = sum of `Override Weekly (Tableau)` rows whose `Period 2026-N` number is **greater than the last period SCI posted** to the Security Ledger (`REGEXEXTRACT` of `P9-2026` / `P09 2026` from the latest `Override - Standard` explanation)
- E19 last standard-override lump posted to Security: amount and date · G19 `="about "&TEXT(<that date>+28,"mmm d")` (SCI posts the lump every 4 weeks)

### Lower boxes (white "cards" on the navy page)
All four share: title band bold 12 pt on the group's pale color, grey column-header row bg `#F6F7F9`
bold, every number **centered**, row labels bold, full grid `SOLID #9AA5B1`, outer frame
`SOLID_THICK #85B7EB`, heavier line `SOLID_MEDIUM #5F6B7A` under the title and under the header row,
total rows bg `#F6F7F9` bold.

- **A22:D29 NEEDS A LOOK** (band amber `#FAEEDA` / `#633806`): Item · This week · All time. Rows:
  Business expenses paid from personal accounts, Personal spending on business cards (SUMIFS on
  `Ledger!J` flag), Transactions with no category (COUNTIFS `Uncategorized`), NPAs paid through
  payroll, Zelle & checks to people (Business Weekly lookups), note row 29.
- **E22:H30 SECURITY ACCOUNT — THIS WEEK** (band purple `#EEEDFE` / `#3C3489`): Opening balance,
  Standard overrides and bonuses credited, Moved to checking, Paid to other ICDs, Fees & deductions,
  Closing balance (bold, bg `#F6F7F9`), Overrides earned YTD, Moved to checking YTD — all lookups
  into Business Weekly's Security block (values in column G).
- **A33:D44 YEAR-END RUN RATE** (band blue `#E6F1FB` / `#0C447C`): C34 `=INT((DATE(2026,12,26)-$B$4)/7)`
  weeks left, C35 `=COUNTIFS('Business Weekly'!$4:$4,">="&DATE(2026,1,1),'Business Weekly'!$4:$4,"<="&$B$4)`
  weeks so far; header row 36 `Year to date | At YTD pace | At last-8-week pace`; rows 37–42 Gross
  profit, Net profit earned, Net profit or loss bank, Captainship bonus, Rep commissions, NPAs:
  B = `SUMPRODUCT` of the Business Weekly row across weeks ≤ $B$4, C = `B+B/$C$35*$C$34`,
  D = `B+AVERAGE(OFFSET(<row>, last 8 weeks))*$C$34`; rows 43–44 Total funds available / Net position
  (after Raf) bold. Conditional format: B37:D44 `NUMBER_LESS 0` → red text `#9E2D2D`.
- **A47:I57 LAST 8 WEEKS (year to date on top)** (band green `#EAF3DE` / `#27500A`): header row 48
  `Week ending | Direct deposit | Rep commissions | Gross profit | Operating % | Captainship | Net profit (earned) | Net profit / loss (bank) | Funds available`;
  row 49 `2026 YEAR TO DATE` reads Business Weekly column B; rows 50–57 `=$B$4-7*7 … -7*0` with
  `IFERROR(INDEX(… MATCH($A50, 'Business Weekly'!$4:$4,0)),0)` lookups; E = `=IF(B=0,"",D/B)`;
  rows 49 and 57 bold on `#F6F7F9`, even rows shaded `#F6F7F9`.
- Hidden helpers **P48:R56**: `Week ending | Gross profit | Operating %` with `=A50`, `=D50`,
  `=IF(E50="",0,E50)` … (navy background).
- **Chart** anchored at row 60 (0-based rowIndex 59), 900×320 px: COMBO, title
  `Gross profit (bars) and operating % (line), last 8 weeks`, domain P48:P56, series Q (COLUMN,
  left axis, navy `#112140`) and R (LINE, right axis, green `#1C6B47`), legend bottom,
  `hiddenDimensionStrategy: SHOW_ALL` (required — the helper columns are hidden), title font Inter 12 bold.
  Full chart JSON is in `spec/00_Dashboard.json`.

---

## 4. Business Weekly (tab 1) — the P&L engine

131 rows × 63 cols. Frozen 4 rows + 2 columns. Widths: A=270, B=110, C→BC=92. Rows: 1=34 px,
4=30, section bands=26, spacer rows (10, 22, 30, 39, 55, 108, 111, 121)=10.

- **A1** `Business P&L — Weekly` bold 18 pt `#11213F`. **A2** note 9 pt `#727A84`.
- **Row 3**: C3 `="In progress"`, D3 `="Latest full week: "&TEXT(D4-6,"mmm d")&" – "&TEXT(D4,"mmm d")`,
  E3… `=TEXT(E4-6,"mmm d")&" – "&TEXT(E4,"mmm d")` — 9 pt grey centered.
- **Row 4** (navy band, white bold, centered): A4 `Category`, B4 `YTD 2026`, C4 = Saturday serial of
  the current week, D4 = C4−7, E4 = D4−7 … (dates, `mmm d`). Column D (latest full week) has a
  `SOLID_MEDIUM #11213F` left+right border down the whole column and a top border on D5 — the
  "latest full week" box.
- **Column B (YTD)** on every numeric row: `=SUMPRODUCT((YEAR(C$4:AS$4)=2026)*N(+C6:AS6))` (bg `#EDF2F7`).
  Ratio rows use `=IFERROR(B8/B6,"")`.
- **Columns C…** hold the per-week formulas; **every week column is identical to column C with the
  column letter shifted** (the sync script copies column C to make a new week). The full list of
  rows with exact column-C formulas is in `tables/01_Business_Weekly.md`; the structure:

| Row | Label | Band / fill | Column-C formula (summary) |
|---|---|---|---|
| 5 | DIRECT DEPOSIT | band navy `#11213F` | |
| 6 | Direct Deposit | `#EFF2F9` | `SUMIFS(Ledger amount, category "Sales Deposits (SCI)", week) − SUMIFS('Captain Bonus (Tableau)'!C, B=week)` |
| 7 | Sales rep commissions | | `IF(no Apex row for week, SUMIFS(Ledger "Commissions & Wages (ADP)"), −SUMIFS('Payroll (Apex)'!F sales-rep gross))` |
| 8 | **GROSS PROFIT** | `#E0F4E5` bold 11 | `=C6+C7` |
| 9 | Operating % | italic grey, `0.0%` | `=IF(C6=0,"",C8/C6)` |
| 11 | OTHER INCOME | band green `#1C6B47` | |
| 12 | Captainship Bonus | `#EDF7EF` | `SUMIFS('Captain Bonus (Tableau)'!C, B=week)` |
| 13 | Security Account | | Security Ledger credits that week: kinds `Override*` + `Bonus*` + `Other credit*` + `Transfer in*` (col H = week ending) |
| 14–15 | ␣␣Standard override (incl. special & Credico) / ␣␣Bonuses & other credits | 9 pt grey italic, labels indented 6 spaces | the two halves of row 13 |
| 16 | Misc Income | | Ledger categories Profit Sharing & JV Income + Rent Reimbursement + Cash & Check Deposits + Other Business Income |
| 17–20 | ␣␣Profit sharing… / ␣␣Rent reimbursement… / ␣␣Cash & check deposits / ␣␣Other | 9 pt grey | one category each |
| 21 | TOTAL OTHER INCOME | `#DBE5EF` bold | `=C12+C13+C16` |
| 23 | SECURITY ACCOUNT | band amber `#B77214` | |
| 24 | Opening balance | `#FCF4E5` | running balance (`'Security Ledger'!F`) at the last row dated ≤ week−7 |
| 25 | Standard overrides and bonuses | | same as row 13 |
| 26 | Moved to checking | | kind `Payout*` |
| 27 | Paid to other ICDs | | kind `Transfer out*` |
| 28 | Fees & deductions | | kinds `Fee*` + `Deduction*` + `Other debit*` |
| 29 | **CLOSING BALANCE** | `#E0F4E5` bold 11 | running balance at the last row dated ≤ week |
| 31 | BANK VIEW | band teal `#19667F` | |
| 32 | SCI deposits (gross) | `#EAF4F9` | Ledger "Sales Deposits (SCI)" |
| 33 | From Security to checking | | Ledger "Transfer from Security to checking" |
| 34 | Other cash in | | Misc income categories + Loan from Raf (received) + Loans & Capital In (other) |
| 35 | GROSS REVENUE | `#DBE5EF` bold | `=C32+C33+C34` |
| 36 | TOTAL EXPENSES | `#DBE5EF` bold | every negative Ledger row on the 5 business accounts except "Transfer / Card Payment", **plus** flagged business-on-personal rows, **minus** flagged personal-on-business rows |
| 37 | **NET PROFIT OR LOSS** | `#E0F4E5` bold 11 | `=C35+C36` |
| 38 | ␣Difference vs earned net profit | | `=C37-C109` |
| 40 | FUNDS BY ACCOUNT (balance at end of week) | band dark green `#287F5B` | |
| 41–45 | each cash account | `#E5F7EA` | `=Balances!$C$n − SUMIFS(Ledger amount, account, date > week)` (Security row = ledger running balance) |
| 46 | TOTAL CASH | `#B7E5C6` bold | sum |
| 47–52 | each card | `#FCEAEA` | `=-(Balances!$C$n + SUMIFS(…date > week))` |
| 53 | TOTAL CARDS OWED | `#F4C6C6` bold | sum |
| 54 | TOTAL FUNDS AVAILABLE | `#287F5B` white bold 12 | `=C46+C53` |
| 56 | OPERATING EXPENSES | band red `#9E2D2D` | |
| 57 | Admin & owner payroll | `#FCEFEF` | −(Apex owner gross D + admin gross E) when an Apex row exists |
| 58 | NPAs | | −(Apex K+L+M) + N |
| 59–82 | ␣␣<person name> ×24 | 9 pt grey | per-person NPA from `Apex Net Pay Detail` (G additions − H deductions, kind "Reimbursement / extra") |
| 83 | Payroll taxes / fees | | ADP bank debits − everything Apex accounts for (+ Payroll Fees) |
| 84 | Zelle & checks to people | | Ledger "Contractor & Bonus Pay" |
| 85 | Payroll subtotal | `#EDF2F7` bold | `=C57+C58+C83+C84` |
| 86–88 | Recruiting - Indeed / - ARS / - Other | | `=SUMIFS(Ledger!$G:$G,Ledger!$H:$H,$A86,Ledger!$B:$B,C$4)` (label-driven) |
| 89 | Recruiting subtotal | subtotal | |
| 90–96 | Rent & Facilities, Phone & Internet, Software & Subscriptions, Office Supplies & Equipment, Hub Accounting & Consulting, Management Fees (Other Offices), Paid to other ICDs from Security | | label-driven SUMIFS; row 96 from Security Ledger `Transfer out*` |
| 97 | Office subtotal | | |
| 98–100 | Meals & Team Events, Travel, Meals & Travel subtotal | | |
| 101–105 | Bank Fees & Interest, Business Taxes (IRS), Business Insurance, Security fees, Financial subtotal | | |
| 106 | Other Business Expense | | |
| 107 | TOTAL OPERATING EXPENSES | `#DBE5EF` bold | `=C85+C89+C97+C100+C105+C106` |
| 109 | **NET PROFIT (earned)** | `#E0F4E5` bold 11 | `=C8+C21+C107` |
| 110 | Net margin | italic grey | `=IF(C6+C21=0,"",C109/(C6+C21))` |
| 112 | BELOW THE LINE | band slate `#596072` | |
| 113–119 | Owner Draw / Withdrawal, Loan from Raf (received), Loan Repayment to Raf, Loans & Capital In (other), Loan Payments (Idea 247), Owner draws through payroll (`−'Payroll (Apex)'!J`), Overrides still in Security (change in running balance) | `#F2F2F4` | |
| 120 | **NET CASH MOVEMENT** | `#E0F4E5` bold 11 | `=C109+C113+…+C119` |
| 122 | MEMO | band grey `#8C939E` | |
| 123–131 | ␣Security → checking (bank side), ␣Overrides credited to Security, ␣Paid out of Security (ledger), ␣Apex gross payroll on file, ␣ADP cash paid (wages + taxes), ␣Business spend from personal accounts, ␣Personal spend on business accounts, ␣Uncategorized, ␣Transactions (count) | `#F4F4F4` | |

Conditional formats: rows 8, 29, 37, 109, 120 columns B:AS `NUMBER_LESS 0` → bg `#FCE5E5`.

**Business Monthly (tab 2)** is the same layout with month keys: C4 `="2026-10"`, D4 `="2026-09"` …;
row 3 `=TEXT(DATE(LEFT(C4,4),RIGHT(C4,2),1),"mmmm yyyy")`; YTD column B
`=SUMPRODUCT((LEFT(C$4:P$4,4)="2026")*N(+C6:P6))`; Ledger lookups use `Ledger!$C:$C` (Month) instead
of `$B:$B`; Security Ledger lookups use `'Security Ledger'!$I:$I` (Month); balances use
`EOMONTH(DATE(LEFT(C$4,4),RIGHT(C$4,2),1),0)`; Apex and Captain lookups use
`SUMPRODUCT((TEXT(<date col>,"yyyy-mm")=C$4)*N(+<amount col>))`. All in `tables/02_Business_Monthly.md`.

**Personal Weekly (tab 3)**: same header style; rows 5 INCOME (band green), 6 Paycheck, 7 Other
Personal Income, 8 TOTAL INCOME; 10 SPENDING (band red), 11–23 the 13 personal categories, 24 TOTAL
SPENDING, 26 NET (income − spending), 28 MEMO (band grey), 29–31 memo lines. Every category row is
label-driven: `=SUMIFS(Ledger!$G:$G,Ledger!$H:$H,$A6,Ledger!$B:$B,C$4)`.

---

## 5. Data tabs (what the automations write)

Header row on every data tab: bg `#11213F`, white bold; frozen row 1; basic filter on Ledger,
Security Ledger, Apex Net Pay Detail.

| Tab | Columns | Written by |
|---|---|---|
| **Ledger** | A Date · B Week Ending (Saturday) · C Month `YYYY-MM` · D Account (sheet name) · E Side (Business/Personal/Transfer/Review) · F Description · G Amount (income +, spending −) · H Category · I Group · J Flag · K Txn ID (Tiller) · L Full Description | `tiller_sync.py` — newest first, one row per bank transaction since 2025-01-01. H has data validation `=Rules!$A$2:$A$60` (dropdown). Conditional formats on J: `Needs category` → `#DBE5EF`; contains `BUSINESS account` → `#FCE5E5`; contains `PERSONAL account` → `#FFF2CC`. Widths A95 B95 C70 D200 E80 F300 G100 H210 I130 J250 K250 L300. |
| **Security Ledger** | A Date · B Explanation · C Kind · D Campaign · E Amount · F Running balance · G Document · H Week ending (Sat) · I Month · J Pulled · L1 `Security balance (SFDC Total Balance)` M1 = balance (bg `#E0F4E5` bold) N1 `as of` O1 = date; L3:L4 a "How this tab works" note | `carlos_security_ledger.run` — rewritten newest-first every run |
| **Captain Bonus (Tableau)** | A DD week (Sun) · B Lands in P&L week ending (Sat) = A+6 · C Captain's Bonus (header bg `#E0F4E5`, values bold on `#E0F4E5`) · D DD total to ICD (Tableau) · E Live Tableau check (current week) · F Source · G Pulled · H `=SUMIFS(Ledger!$G:$G,Ledger!$H:$H,"Sales Deposits (SCI)",Ledger!$B:$B,B2)` · I `=IF(OR(D2="",H2=0),"",D2-H2)` · J `=IF(I2="","no bank deposit yet",IF(ABS(I2)<=25,"✓ bank matches Tableau","check"))`; conditional format J contains `check` → `#FFF2CC` | same job (`write_captain_table`) |
| **Override Weekly (Tableau)** | A Week (Sun) · B P&L week ending (Sat) · C Period (`Period 2026-10`) · D Standard override `$#,##0.00` · E Pulled · F Source | same job (`write_overrides`); one row per (week, period) |
| **Payroll (Apex)** | A Period start · B Period end (Sun) · C Paid in week ending (Sat) · D Owner gross · E Office Admins gross · F Sales Reps gross · G Company gross · H Rep share `0.0%` · I Source file · J Owner net-pay additions: DRAWS · K Owner net-pay additions: other · L Admin net-pay additions · M Rep net-pay additions · N Net pay deductions · P1 "How this tab works" note | `carlos_payroll_pull.run` (`upsert_row`, keyed on period end) |
| **Apex Net Pay Detail** | A Period start · B Period end · C Paid in week ending · D Section (Owner / Office Admins / Sales Reps) · E Name · F Gross pay · G Net pay addition · H Net pay deduction · I Comment · J Kind (`Owner draw` when section Owner and comment matches `draw|distribution|dividend`, else `Reimbursement / extra`) | same job (`upsert_people`) |
| **Balances** (tab 15, gridlines hidden, widths A300 B90 C140 D30 E60, column E hidden) | A Account · B Type · C Balance · E Acct # (hidden key). Rows 2–6 cash accounts (bg `#E5F7EA`), 7 TOTAL CASH `=SUM(C2:C6)` (`#B7E5C6` bold), 8–13 cards (`#FCEAEA`), 14 TOTAL CARDS OWED `=SUM(C8:C13)` (`#F4C6C6` bold), 15 TOTAL FUNDS AVAILABLE `=C7-C14` (`#287F5B` white bold), 16 Loan from Raf `='Raf Loan'!B9` (`#FFF2CC`), 17 NET POSITION (funds available − Raf loan) `=C15-C16` (`#11213F` white bold). C6 `='Security Ledger'!M1`. Conditional format C15, C17 `NUMBER_LESS 0` → `#FCE5E5`. | `update_balances` copies Tiller's `Accounts!Last Balance` into C keyed on E |
| **Accounts** | A Account # · B Name in this sheet · C Institution · D Type · E Side · F Last balance (Tiller) · G Last update — one row per linked account + the Security row (`F='Security Ledger'!M1`) | reference, filled once |
| **Rules** | A Category · B Group · C Side · D Shows on (rows 2–48 = the category table) · F # · G Pattern (regex) · H Category · I Only on accounts · J Amount test (rows 2–…= the ordered rule list) | reference copy of `categorize.py` |
| **Sources** | A P&L line · B Source system · C Exact path · D How it is verified | documentation of where every line comes from |
| **Review** (frozen 5 rows, gridlines hidden) | A1 title; A4 band `#FFF2CC` "BUSINESS EXPENSES PAID FROM A PERSONAL ACCOUNT…"; A5:G5 header; A6 `=IFERROR(SORT(FILTER({Ledger!A:A,Ledger!B:B,Ledger!D:D,Ledger!F:F,Ledger!G:G,Ledger!H:H,Ledger!J:J},Ledger!J:J="Business expense on PERSONAL account"),1,FALSE),"none")`; I1 band `#FCE5E5` "PERSONAL SPENDING CHARGED TO A BUSINESS ACCOUNT…", I2:O2 header, I3 the same FILTER for the other flag. (Uncategorized rows are counted on the Dashboard; the Ledger filter finds them.) | formulas only |
| **Raf Loan** (gridlines hidden) | B4 balance owed (typed, `#FFF2CC`), B5 as-of date (typed); B7 repaid since `=-SUMIFS(Ledger G, cat "Loan Repayment to Raf", date > B5)`; B8 borrowed since; **B9 BALANCE OWED TODAY `=B4-B7+B8`** (`#E0F4E5` bold); B11 usual weekly repayment `=IFERROR(MODE(FILTER(-Ledger!$G:$G,Ledger!$H:$H="Loan Repayment to Raf")),0)`; B12 weeks to pay off; B13 paid off around; rows 16+ monthly history (`="2026-09"` … with SUMIFS per month) and F16 detail FILTER | two typed cells |

---

## 6. How the numbers are produced (the rules the code implements)

### 6.1 Bank transactions → Ledger (`categorize.py` + `tiller_sync.py`)
- Tiller refreshes its own Google Sheet from the banks daily (`Transactions` and `Accounts` tabs).
- `tiller_sync` reads Tiller `Transactions`, keeps rows dated ≥ 2025-01-01, and **adds only rows whose
  Tiller Transaction ID is not on the Ledger yet**. Existing rows keep whatever Category is on the
  sheet (manual edits are never overwritten); Group / Side / Flag are recomputed from the Category
  for every row so a manual change flows through.
- Category = **first matching regex** over `UPPER(full description | description)` in the ordered
  rule list (`categorize.R`); optional account filter and amount test (`POS`/`NEG`). Tiller's own
  "Transfer" tag is ignored. No match → `Uncategorized` (flag `Needs category`).
- Category → (Group, Side) from `CATEGORIES`. Side `B`/`L` = business, `P` = personal, `X` =
  transfer (excluded everywhere), `?` = review. Flag = `Business expense on PERSONAL account` or
  `Personal expense on BUSINESS account` when the category's side ≠ the account's side.
- **Smart Circle split**: Smart Circle pays sales once a week. For each Sun–Sat week on the business
  checking account, the **largest** positive SCI ACH stays `Sales Deposits (SCI)`; every other SCI
  deposit / Fedwire that week becomes `Transfer from Security to checking` (it is a Security payout).
  SCI debits (−$290 background checks) are `Recruiting - Other`.
- Week Ending = the Saturday of the transaction's Sun–Sat week (`week_end`). Month = `YYYY-MM`.
- **Calendar roll**: when a new week starts, `roll_calendar` inserts a new column at C on
  `Business Weekly` and `Personal Weekly` (copy of the old C incl. formats, then C4 `=D4+7`, row-3
  labels, moves the "latest full week" border to D), adds a month column on `Business Monthly`
  (C4 `="YYYY-MM"`), and resets `Dashboard!B4` to `='Business Weekly'!C4`.
- All Sheets calls go through a retry wrapper (429 / 5xx with backoff).

### 6.2 Security ledger, captain bonus, weekly override, balances (`carlos_security_ledger/run.py`)
- Tableau view **Overrides ICD View → NETSUITE SECURITY LEDGER SFDC**, crosstab sheets
  `Transaction Details` (keep rows whose owner column contains the owner's name, drop the `Total`
  row) and `SFDC Total Balance` (the owner's balance → `Security Ledger!M1`).
- `classify(explanation, amount)` → Kind: `Override - Credico` (text contains "credico"),
  `Override - Special`, `Override - Standard` ("standard override" / "std or"), `Fee` (wire/ACH fee),
  `Payout to bank` ("security payment", "sec draw", wire+payment), `Transfer out (to other ICD / account)`
  / `Transfer in` ("security transfer", "autho ", "sec dep", "balance transfe", by sign), `Bonus`
  ("bonus", "r&r"), `Deduction` ("burn", "chargeback", "deduct"), else `Other credit` / `Other debit`.
  Campaign = text after `Override - …`. Tableau text has double spaces — collapse whitespace first.
- Captain's bonus: Tableau **Direct Deposit (ICD VIEW) Version 2.0 → DD DETAIL** (owner's login, sheet
  `ICD dd Detail`) or **DD DETAIL ORG** (Hub login, sheet `ORG DD Detail`, filter owner name). Rows
  whose description matches `captain'?s?\s*bonus` per `cl.DD Week`; that view only shows the current
  DD week, so history comes from the Hub workbook's weekly captures (`Org Overrides Ongoing Report` →
  section `CAPTAIN/SPECIAL OVERRIDES ONLY` → owner row → next row `Captain Override`; DD totals from
  `Org DDs Ongoing Report`). A DD week labelled Sunday lands in the P&L week ending Saturday = +6 days.
- Weekly standard override: Tableau **Overrides ICD View → ORG OVERRIDE SUMMARY** with URL filter
  `?Period=Period 2026-N` (year-prefixed form only), crosstab sheet `ORG Override Summary`; sum every
  campaign row under the owner's name per week column; a week near a month edge sits in two periods —
  keep both rows, formulas sum them. Pulls periods N, N−1, N+1 each day (first run N−2 too), saving
  after each period (one Tableau sign-in for all of them, ~13 min total on the Hub machine).
- Balances: copy Tiller `Accounts` → `Last Balance` into `Balances!C` keyed by account number in the
  hidden column E (normalize leading zeros: 0573 ↔ 573).

### 6.3 Apex payroll (`carlos_payroll_pull/run.py`)
- Real Chrome launched with a **persistent** profile (`~/Library/Application Support/carlos_payroll_pull/chrome_profile`,
  CDP port 9248) that the owner signed into once. **The code never types credentials.** If the login
  form appears the job exits 2 with a message asking the owner to sign in.
- Apex forces a "set up 2FA" interstitial on every full page load — ignore it: navigate in-app by
  JS-clicking `a[href="/payrolls"]`, viewport 1600×1000, dismiss the modal, collapse the sidebar.
- Pay-period dropdown is a Kendo widget (`span.k-dropdown[aria-owns$="_listbox"]`, items via
  `[id="<aria-owns>"] li`); index 0 is the week in progress, index 1 the newest completed period.
  Click **Export** → `Payroll_<period-end>.csv`. Never click "Save & Recalculate" or "Submit Payroll".
- Parse sections `Owner`, `Office Admins`, `Sales Reps` (gross per section, per-person Net Pay
  Addition / Deduction + Comments); owner additions whose comment matches `draw|distribution|dividend`
  are draws (column J), the rest "other" (K). Upsert into `Payroll (Apex)` keyed on period end and
  `Apex Net Pay Detail` keyed on (period end, name). A period paid Mon–Sun lands in the P&L week
  ending the following Saturday (= period end + 6).

---

## 7. Schedules (reproduce the same cadence)

| Job | Where it runs | When | Command |
|---|---|---|---|
| Tiller → Ledger | Hub machine ("Lucy 2") via the day orchestrator **and** the owner's Mac (launchd) as backup | daily 05:00 (orchestrator); 06:30 + 13:30 (Mac) | `python -m automations.carlos_finance.tiller_sync` |
| Security ledger + captain bonus + weekly override + balances | Hub machine (has a shared Tableau session) | daily not before 05:30 | `python -m automations.carlos_security_ledger.run --via hub` |
| Apex payroll | owner's own Mac (needs the owner's Apex login in Chrome) | Thursdays 13:00 | `python -m automations.carlos_payroll_pull.run` |

- launchd plists are in `code/launchagents/`; they call `code/deploy/*.sh`, which `cd` into
  `~/recruiting-report` (a clean clone of the Hub repo). **Do not run scheduled jobs from `~/Desktop`**
  — macOS privacy controls block launchd from reading Desktop and the job silently fails.
- Orchestrator entries (`schedule_config_excerpt.json`): `carlos_security_ledger` (`base_args ["--via","hub"]`,
  `not_before 05:30`) and `carlos_tiller_sync` (`not_before 05:00`).
- Every job supports `--dry-run`. The Apex job also takes `--period YYYY-MM-DD` and `--backfill N`;
  the security job takes `--from-files` and `--via chrome|hub`.
- Dependencies: the two Tableau/Apex jobs import helpers from the Hub repo
  (`automations.shared.tableau_patchright.download_crosstab_patchright`,
  `automations.override_bulletin.pulls.read_crosstab/_with_filter/_num_locale/_WK_HDR`,
  `automations.recruiting_report.opt_phase.drive_crosstab_dialog`, `automations.vantura_churn.cdp_pull`).
  Outside that repo you need equivalents: a Tableau Cloud sign-in + "Download → Crosstab" driver
  (patchright/Playwright) and a UTF-16 TSV crosstab reader.
- Python 3.9 venv; packages: google-api-python-client, google-auth, google-auth-oauthlib, patchright.
- Google auth: a user OAuth token for the owner's own Google account with scope
  `https://www.googleapis.com/auth/spreadsheets` (`~/.config/recruiting-report/oauth-token.json`).
  The Hub machine's Google identity must be **shared on the P&L sheet (Editor) and on the Tiller
  sheet (Viewer)** or it gets 403.

---

## 8. Build order (if you are not using apply_spec.py)

1. Create the spreadsheet (locale `en_US`, time zone `America/Chicago`). Create all 16 tabs first, in
   the order of `00_summary.json`, so cross-tab formulas resolve.
2. Data tabs first (`Ledger`, `Security Ledger`, `Captain Bonus (Tableau)`, `Override Weekly (Tableau)`,
   `Payroll (Apex)`, `Apex Net Pay Detail`, `Balances`, `Accounts`, `Rules`, `Sources`, `Raf Loan`):
   headers, widths, formats, filters, validations from `tables/*.md`.
3. `Business Weekly`: column A labels and formats, row 4 dates (C4 = this Saturday, then −7 each
   column, 40+ columns), column B YTD formulas, column C formulas from `tables/01_Business_Weekly.md`,
   then copy C across all week columns. Add the five conditional formats and the column-D border box.
4. `Business Monthly` and `Personal Weekly` the same way.
5. `Review`, then `Dashboard` (navy fill A1:BH63 first, then tiles, tables, hidden helpers, chart,
   conditional formats, B4 validation, frozen rows 5).
6. Run `tiller_sync` once (it backfills the Ledger from Tiller history), then the security job
   (`--via hub` or `--via chrome`), then the Apex job with `--backfill 8`.
7. Verify: no cell starting with `#` on Dashboard / Business Weekly / Balances; Dashboard tiles show
   numbers; `Captain Bonus (Tableau)!J` says `✓ bank matches Tableau` for past weeks; Business Weekly
   row 38 (bank vs earned difference) is small and explainable; `Review` lists flagged rows.

`spec/apply_spec.py` does steps 1–5 in about two minutes (`--token` = the OAuth token JSON). It was
tested on 2026-10-21: it rebuilt all 16 tabs into a new spreadsheet with zero formula errors and
identical formats on every cell checked.

---

## 9. What to change for a different owner (checklist)

Search-and-replace these; everything else carries over unchanged.

1. **Accounts** — `categorize.ACCOUNTS` (last-4 → sheet name, side B/P), `BIZ`, `PERS`; the same names
   on `Balances!A2:A13` + `E2:E13`, `Accounts`, Business Weekly rows 41–52 (one row per account, add
   or delete rows and fix the TOTAL formulas), the `TOTAL EXPENSES` formula (one `SUMIFS` per business
   account), Dashboard C9 (which accounts are "personal checking + savings"), `tiller_sync.BIZ_CHK`.
2. **Tiller sheet ID** (`CARLOS_TILLER_SHEET_ID` / `tiller_sync.TILLER`, `carlos_security_ledger.TILLER_ID`)
   and **P&L sheet ID** (`CARLOS_PNL_SHEET_ID`, `PNL`, `PNL_SHEET_ID`).
3. **Owner name** used to filter Tableau rows: `carlos_security_ledger.OWNER = "carlos hidalgo"`
   (lower-case, matched as a substring of the "ICD Owner Name and OFFICE NAME" column and of the
   ORG Override Summary owner column).
4. **Merchant rules** — the regex list in `categorize.py` (and its copy on the `Rules` tab) is
   Carlos's merchants: his landlords (`CCINORTHHWY360`…), his consultants, his loan counterparties
   (`ALPHALETE MARKET.*ACH` = loan from Raf, `ALPHALETEMARKETING(INC|ORGACCT)` = management fee to
   Maud), SCI descriptors (`WF SCILL|SMARTCIRCLE INTL|SMART CIRCLE`), ADP descriptors. Review every
   rule against the new owner's bank descriptions; the SCI and ADP ones usually transfer as-is.
5. **People** — Business Weekly rows 59–82 are one row per person who received NPAs (name must match
   the Apex export exactly). Generate them from the new owner's `Apex Net Pay Detail` names.
6. **Loan tab** — rename `Raf Loan` / "Loan from Raf" if the owner has a different lender or delete
   the tab, `Balances!C16`, `NET POSITION`, Dashboard B44:D44 and the two `Loan …` categories.
7. **Year** — formulas hard-code 2026 in `YEAR(C$4:AS$4)=2026`, `LEFT(C$4:P$4,4)="2026"`,
   `DATE(2026,12,26)`, `DATE(2026,1,1)`, the `YTD 2026` / `2026 YEAR TO DATE` labels, and the Raf Loan
   month list. Replace at the turn of the year.
8. **Titles** — `Carlos — Weekly Dashboard` (Dashboard A1), spreadsheet title, Security Ledger note,
   Sources tab text.
9. **Apex** — the owner signs into apex.herbjoyent.com once in the dedicated Chrome profile; the
   section names (`Owner`, `Office Admins`, `Sales Reps`) are Apex's and should be identical.
10. **Tableau access** — the owner's own login sees `DD DETAIL` (ICD view) and the security ledger;
    `DD DETAIL ORG` and `ORG OVERRIDE SUMMARY` need an org-level login (the Hub's). Pick `--via chrome`
    (copy of the owner's everyday Chrome profile, read-only) or `--via hub`.

---

## 10. Gotchas we hit (so you don't)

- Hidden helper columns feeding a chart require `hiddenDimensionStrategy: SHOW_ALL` or the chart
  shows "Add a series".
- A label that starts with `+` is parsed as a formula → `#ERROR!`. Don't start labels with `+`.
- `MATCH("Direct Deposit", 'Business Weekly'!$A$6:$A$300)` starts at row 6 on purpose: the section
  band `DIRECT DEPOSIT` in row 5 would collide with the line `Direct Deposit` (MATCH is case-insensitive).
- Account numbers with a leading zero (0573, 0021, 0253) come back as 573/21/253 from Tiller or the
  sheet — normalize before keying.
- Tiller "Transfer" tags are wrong often enough that the rules engine defines transfers itself.
- Apex: a `/tmp` Chrome profile gets wiped by macOS → the login is lost. Keep it under
  `~/Library/Application Support/…`.
- Tableau crosstabs are UTF-16 tab-separated; "Wire security  payment" has two spaces.
- Hub orchestrator runs several Sheets-heavy jobs back to back → 429s; retry with backoff.
- Lucy's rerun cap is 45 minutes; one Tableau sign-in per period took ~4 min each — share one session.
- Dashboard freshness formula must use whole-column ranges (`MAX(Ledger!A:A)`), otherwise inserting
  rows shifts it.
- `roll_calendar` must keep `Dashboard!B4` as the formula `='Business Weekly'!C4`, not a value,
  or the Dashboard stops following the current week.

---

## 11. Reference IDs (Carlos's instance — replace for the new owner)

- P&L sheet: `1ngQtKRNeuGV_FDBp-d9boZmxp6cO3T4IKa7k2NdiLq0`
- Tiller sheet: `1D2mjKSRNCM3fleq8e7uJyRuIotVqMfEW6baC7DV9fAE`
- Hub workbook with weekly Tableau captures (captain bonus history): `1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E`
- Tableau views: `OverridesICDView/NETSUITESECURITYLEDGERSFDC`, `OverridesICDView/ORGOVERRIDESUMMARY`,
  `DirectDepositICDVIEWVersion2_0/DDDETAIL`, `DirectDepositICDVIEWVersion2_0/DDDETAILORG`
  (site `us-east-1.online.tableau.com/#/site/sci/views/…`)
- Apex: `https://apex.herbjoyent.com` → Payroll → Payroll Entry → Export
- A rebuilt-from-spec test copy (no data, formulas only) exists at
  `https://docs.google.com/spreadsheets/d/1nlpdFHmYejEaLifns38-pSm1gNCxCGsZTVAboWolfZw` — safe to delete.
