# Alphalete ORG Sales Board — build recipe (from walkthrough video 1)

Tab: `Alphalete ORG Sales Board` (practice on `Copy of Alphalete ORG Sales Board`).
Week runs **Mon–Sun** (Frontier & Verizon: Sun–Sat). Filled **day by day** — each
day adds that weekday's numbers; a new week starts by **clearing** the prior data.
Backlog: "Org Sales Board" (In Progress / Megan). Daily runner = Eve.

## NEW-WEEK ROLLOVER — do this FIRST, before clearing/filling
Every chart with the comparison block + total columns must "shift" history over
by one before the new week is filled:
- **Comparison block (below the ICD rows):** This week's Totals → Last Week →
  Prior Week → 2 Weeks Prior → 3 Weeks Prior (oldest drops off).
- **Per-ICD total columns (right side):** Running Week Totals → Last Week's
  Totals → Previous Week's Totals (oldest drops off).
- Capture the **values before clearing** (running totals are live formulas that
  would zero out), and shift the per-ICD totals **by ICD name** (not by row
  position), since rows get re-sorted.
- Then: clear this week's day cells + running total, then fill day by day.
- Applies to ALL charts on the tab that have these blocks/columns.

## FORMULA-DRIVEN summaries — DO NOT clear or hardcode
These auto-derive from the daily sections; just keep the formulas intact + verify:
- **Product Summary (rows 3–14):** each product type's day cell = its daily
  section's **Totals row** (Retail NL `=C85`, Fiber `=C103`, Retail JE `=C114`,
  NDS `=C133`, B2B `=C148`, BOX `=C160`, Retail Internet `=C182`, Frontier
  `=C170`). Grand Total = `=SUM(C5:C11)+SUM(C13)`. Labels in col B also auto-pull
  (`=A80`, …).
- **RAF ORG – vs Prior/4-wk (rows 16–22):** `Sales This Week =C14`,
  `vs Prior =(C18-C21)/C21`, `vs 4-wk =(C18-C22)/C22`,
  `Last Week =C86+C104+C115+C134+C149+C171+C183+C161`, `4-Wk Avg =AVERAGE(...)`
  over the sections' Last/Prior/2/3-week history rows.
- ⚠ EARLIER MISTAKE: a "clear Product Summary" step was built + blanked these on
  the sandbox; restored from the real tab. The new-week reset is **not** here —
  it's the **daily section fill areas** + the section-history shift.

## Fill rules (all sections)
- The **sheet's ICD list drives the rows** — fill a value for every listed ICD.
- An ICD with **no data** in the pull → enter **0** (never leave blank). e.g.
  Ronald Dawson absent from the pull = 0 for that day.
- Cross-check each section: the filled day total should match the source's total.
- **Running Week Totals** column = a live **SUM formula** over that ICD's
  Mon–Sun cells — calculated, never hardcoded. (Only Last Week's / Previous
  Week's Totals are static values, captured during the rollover.)

## Sections + their data sources

| Section | Source | Metric / notes |
|---|---|---|
| **Retail NL** | Tableau purpose-built view **"Retail NL Org Sales Board"** (Dropship V_2 / SARA PLUS SALES SUMMARY BY DAY): `.../DropshipV_2/SARAPLUSSALESSUMMARYBYDAY/2eaaea0a-8456-44d9-8852-edd8034e4ee7/RetailNLOrgSalesBoard` | **Wireless Lines** per owner/day = **new lines only**. Set date=this week; view is pre-scoped to the Retail NL ICDs + Wireless Type=Phone. **TN Type must EXCLUDE "upgrade"** (upgrades don't count) — verify the purpose-built view already does, else un-click upgrade. Cross-check: day total matches. |
| **Retail Internet** (bottom, rows ~177–186) | **SAME pull as Retail NL** (one SARA PLUS pass) | read the **Internet** metric row (vs Wireless Lines for Retail NL); same 3 ICDs. Note a static-looking **"Org Head"** column on the right (Carlos/Raf) — confirm manual vs derived. |
| **ATT Fiber Team** (rows 92–107) | Tableau purpose-built view **"Fiber Team no voice"** (ATT Tracker 2.1 D2D V2 / PRODUCT SALES SUMMARY 4WK): `.../ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/ae3a6f98-e68f-4c83-9620-50ea60d6c61a/FiberTeamnovoice` | per-ICD **Total** per weekday = AIR+New Internet+Upgrade Internet+Video+Wireless (**Voice excluded** — view pre-drops it; verify Product Type = all-except-Voice). Date filter = **Sale Date Week Ending** dropdown (not a min/max range). Owners = the Fiber list on the sheet. |
| **Retail JE** (rows 107–114) | **manually-sent screenshot** | **"Closed Won"** per Regional Office (SCI_TX_CinthyaReyes 26, SCI_TX_DavidMartinez 9, SCI_TX_TJGoodwin 1). NOT pullable — **hand-keyed**. ICDs: David Martinez, TJ Goodwin, Cinthya Reyes, Magdalena Alfaro. ⚠ The automation must still **freeze/save Retail JE's totals into the leaderboard during the Monday rollover** (don't skip the manual section) so its weekly numbers persist. |
| **ATT NDS Team** | **NDS Product Sales Summary** (different workbook — NDS campaign) | filter **Wireless** products (wireless = NDS new lines) |
| **B2B** | Tableau **V2V page** workbook | per owner/day |
| **BOX** | **Box daily tracker** | per owner/day |
| **Frontier** | **emailed Verizon PDF** ("Taylor Sales Frontier Events") | look up person (e.g. Abel) → Monday sales. PDF parse — cf. existing Frontier OPT report |

## ALPHALETE ORG leaderboard (rows 24+) — auto-derives from the daily sections
Don't pull this separately — it references the daily sections we fill:
- Per-ICD cell in a WE column = `=SUMIF($B$<sec_names>, B<row>, $J$<sec_run_totals>)`
  — pulls that ICD's **Running Week Total (col J)** from its daily section, by name.
- Group **TOTALS** = `SUM` of the group's ICD rows.
- **ALL TOTALS** (r25) = `SUM` of all campaign TOTALS rows
  (`=SUM(C30+C41+C45+C57+C65+C70+C73+C78)`).
- **Newest WE column = live formulas; all older WE columns = frozen static values.**

Weekly rollover for this section:
1. **Freeze** the just-finished newest column: convert its formulas → the actual
   (verified) numbers, so it stays put when the sections roll next week.
2. **Insert a new WE column** on the left (new WE date) carrying the SUMIF/SUM
   formulas + the ALL TOTALS formula — auto-pulls the fresh week as it fills.
3. Double-check the numbers vs the sections.

## Captainships (lower section)
Each captainship filled from a product-sales-summary workbook filtered by the
**Captain Bonus Team** filter:
- Raf's (D2D Product Sales Summary, all products), Carlos's (B2B tracker),
  Evelis's, Wayne's (fiber), Starr's (fiber), Aaron's (fiber), Khalil's (NDS),
  Colton's (NDS).
- Movers: people leave/join captainships (e.g. "All In" removed from Raf's);
  new people inserted in the middle; nicknames vs full names (Tony Chavez = Jose
  Antonio Chavez, Trail Mitchell = Lamar Mitchell) → **ICD aliases**.

## Sorting (after fill)
- Sort each chart by the **weekly running total** (col J for leaderboard, col C
  for the day tables), **highest → lowest**.
- ALWAYS select from **outside the box** (incl. the name/label column) so each
  ICD's whole row of days moves together — never sort just the numbers.
- Box / Frontier groups already tend to be in order; verify anyway.

## Plus
- A separate **Country Sales Board** chart + a refresh step (shift current week
  to the prior column, insert a new week column carefully — select only the exact
  cells, special-paste values, then zero out the new week).

## Name matching ⚠
- Owner names in Tableau carry a `[company, inc.]` suffix — strip it.
- Org-board row names differ from Tableau (e.g. **Akib Chowdhury** = Tableau
  **BOAKTEAR CHOWDHURY**). The ICD Aliases tab has "Akib"/"Boaktear Choudhury"
  but spelling ("Choudhury" vs "Chowdhury") + the board's own label ("Akib
  Chowdhury") mean we need an org-board owner→row map (or fixed aliases) per ICD.

## Build phasing (proposed)
1. ✅ Clear Product Summary (done — `clear_product_summary`).
2. **Retail NL** via SARA PLUS (have the source + filters) — first working pull.
3. Retail Internet (same view).
4. ATT Fiber / NDS / B2B / BOX (each its own Tableau workbook).
5. Frontier (email PDF) + Retail JE (manual/upload).
6. Captainships + sorting + Country board + week-rollover.
