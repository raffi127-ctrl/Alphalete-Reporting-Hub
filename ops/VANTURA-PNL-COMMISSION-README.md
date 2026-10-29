# Vantura P&L + Commission — How It All Works

_Companion to `VANTURA-BOARD-README.md` (that one covers Sales Board / Roll
Call / Stations / Daily Update). This one covers the **money** side: RAW,
Rates, Adjustments, Commission, the working P&L and `P&L 2026`._

_Written 2026-09-06. Sheet id `1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY`.
**Read the "Lookout list" before changing anything.** Updated nightly at 7pm
by `vantura_readme_update` — see the last section._

---

## The chain

```
Tableau "ICD dd Detail" crosstab (Direct Deposit ICD VIEW → DD DETAIL, Owner: Carlos)
        │  Wed 11:00 CT, Lucy 2, automations/vantura_payroll/run.py
        ▼
RAW          one row per paid line · col A = week number · col I = ARRAYFORMULA
        │
        ├── Rates       (per-rep %, no-pay list)     ─┐ feed col I
        ▼                                             │
Commission   B1 picks week · rep block + itemized block are STATIC
        ▲    rebuilt by Payroll.gs _rebuildCore (webapp ?action=refresh)
        │
Adjustments  your weekly judgement (bonuses / no-pay / set-total)
        │
        ▼
Copy of Carlos PNL 2026    the engine — 3 cols per week × 53 weeks
        │
        ▼
P&L 2026     read-only presentation, 1 col per week, all live formulas
```

## Tabs

| Tab | What it is | Who writes it |
|---|---|---|
| **RAW** | the ledger; every paid line, all weeks | `run.py` weekly (A:H, J:N). **Never col I** |
| **Rates** | per-rep rate; col G = no-pay list | you, by hand |
| **Adjustments** | weekly bonuses / no-pay / top-ups | you (via Claude), append-only |
| **Commission** | the rep-facing sheet you print | Payroll.gs `_rebuildCore` |
| **Copy of Carlos PNL 2026** | calculation engine | `run.py` formulas + `syncCarlosPNL` |
| **P&L 2026** | clean presentation | `clean_pnl.build()` |
| **NoRevPay** | log of pay with no revenue | by hand (last entries 6.21 — may be abandoned) |
| **Commission Calculator** | Base energy bonus tiers (12–15 → $200, 16+ → $300) | static |
| **Name Aliases** | board-name → paid-name bridge | by hand |

## RAW columns

| Col | Field | Notes |
|---|---|---|
| A | Week Ending | **number**, `8.3` = WE 8/30. Aug 3 was a Monday so month.day never collides in 2026 |
| B | Rep Name | **blank = the captain's bonus row** — that's how it's identified |
| C–D | Sale / Activation Date | serial numbers |
| E | Description | **bare token since 8/2** ("WIRELESS", "OOF", "BF 1") or blank. Do not build new logic on this |
| F | Description Detail | **always empty since 8/2** |
| G | Customer Name | |
| H | Total $ to ICD | the money |
| **I** | **Commission** | **ARRAYFORMULA at I2 — see below** |
| J | Campaign | `B2B-ATT-SBS` / `B2B-BOX-Energy` / `RES-BASE POWER-Energy` / `NDS Wireless`. **The reliable field** |
| K | Product | carries the real payout name since 8/2 |
| L | Commission Type | Base / Add On / Campaign / Special / Return / Exclusive (added 8/27) |
| M | Category | WIRELESS / ELE / Volume Bonus / **Lead Disposition Bonus** / Captain's Bonus … (added 8/27) |
| N | Tier | "Tier 2", "Tier 3-4", blank (added 8/27) |

### `RAW!I2` — the commission cascade

One spilling ARRAYFORMULA covering the whole column, evaluated top to bottom:

1. `H` blank → `""`
2. rep name in **`Rates!G`** (no-pay list) → `0`
3. **C, D, E, F, G all blank** → `0` ← the junk guard
4. `IRU AIR`, or `- OOF`/`- IF` with blank Detail → `0`
5. tier payout → **100% of H**, but only `"Tier Volume"` in K **AND** `J = "B2B-ATT-SBS"`
6. otherwise → `H × VLOOKUP(rep, Rates!A:D, 4)`, default `0.4`

## Commission tab

- `B1` picks the week — and since 9/6 it **auto-rebuilds**: an installable
  `onWeekPick` edit trigger (Payroll.gs, 6-min budget) calls `_rebuildCore()`
  when a HUMAN edits B1. Table redraws in ~10–40s; a "P&L synced" popup may
  appear at the end. API/script writes to B1 do NOT fire it (Sheets triggers
  ignore API edits) — the Wednesday run still refreshes via the web app.
- The rep block (`A3:E…`) and itemized block (`G:O`, 9 cols, Product after
  Description) are **static** — they repopulate only when `_rebuildCore` runs
  (via the B1 trigger, the menu, or the web app).
- `P3:Q6` = Brought In by campaign, live `SUMIFS` on `B1`.
- Sub-tables below the TOTAL row: `ACTIVE REPS - NO REVENUE` /
  `REVENUE - NOT ACTIVE`, then `FIRST & SECOND WEEK PAYCHECKS` (reuses col A
  names — **scanners must stop at TOTAL**).
- The "active" panel is built by **Code.gs**, not the payroll webapp, and needs
  a recent *Active* Roll Call row or reps show as ghosts.

## The P&L

**Working tab** (`Copy of Carlos PNL 2026`): 53 week-blocks, 3 columns each
(brought / paid / profit), roster rows **3–171**, week header `WE m/d` in row 1.

| Rows | What |
|---|---|
| 173–192 | per-campaign Total Loss / Total Profit / TOTAL / Average Rep Paycheck |
| 198–201 | Carlos Total DD / Total Payroll / Payroll Tax / TOTAL PNL |
| 203–225 | per-campaign DD / Payroll / Tax / NPA / PNL / Margin % |
| 227–229 | Captain / Total Transfers / Total on Tableau |
| 236–254 | Revenue by Campaign (B2B@238, BOX@244, Base@250) |

**Two revenue measures coexist and are not meant to tie:**
- rows 203/211/219 (`Carlos DD …`) assign a rep's *whole* revenue to their one
  campaign tag in col C;
- rows 239/245/251 (Revenue by Campaign) split **per row** on `Campaign__c`.

`Total DD` = Tableau total − captain's bonus. Payroll tax = 12%.

**Paid Out comes from the rep block, never `RAW!I`** — RAW never sees
Adjustments, so a RAW-sourced Paid Out understates payroll by every bonus.

Anchors are found **by label, never row number**, because roster inserts shift
everything below.

## Adjustments protocol

`Week | Rep | Type | Amount | Label`

| Type | Effect |
|---|---|
| `Bonus` | adds Amount (negative works — chargebacks, withholding) |
| `REMOVEALL` | zeroes the rep for that week (Amount blank) |
| `REMOVELINE` | drops one line |

Label conventions actually in use: `Training bonus one`, `Training bonus one and
two`, `Second training bonus`, `Shadow pay`, `Set total to N dollars`,
`No pay week N.N`.

**"Set total to N"** = write `N − current base commission` as a Bonus. Check the
base on the Commission tab *first*.

Rep name must match the **paid** name (RAW / Commission), not the board name.
Known: `Rodolfo Bazan` (not Baza), `Rebeca Juarez` (one c), `Ashley Tapia`,
`Maritza Viviana Huerta`, `Juliet Ortega`.

## The automation

- **Lucy 2, Wednesday 11:00 CT**, launchd `com.alphalete.vantura-payroll-wed`,
  `--live` since 7/15. Pulls Tableau over CDP → loads RAW → sets B1 → re-points
  P&L formulas → webapp refresh → read-only checks → DMs Carlos.
- It does **not** do bonuses, printing, or locking. Board auto-locks Thu ~11am.
- `--enrich-cols` backfills L:N for an already-loaded week (content-identity
  matched).
- **Level-2 bonuses are automated** (9/6): `LEVEL2_REPS` in `run.py` maps
  promoted reps to their extra %-of-revenue; the Wednesday run appends one
  labeled Adjustments row per rep per week (idempotent, skips no-revenue
  weeks, a failure never blocks payroll). Promotions NEVER touch the Rates
  tab — see Lookout 7/5. Current: Jayden Willingham 5%.
- Webapp `?action=refresh` = `_rebuildCore` + `syncCarlosPNL`. URL in gitignored
  `vantura-payroll-webapp.json`. ~40s.
- **Deploy = push to `main` AND the `resume-pushing-v2` branch Lucy 2 tracks.**
  Verify by `logtail`, never by a success message.
- **Payroll.gs got its first non-clasp edit 9/6** (via Chrome + the script
  editor): `onWeekPick` + `installWeekPickTrigger` appended at the end.
  Installable triggers run HEAD, so no web-app redeploy was needed for it —
  but `?action=refresh` still runs the PINNED deployment (v4); any change to
  the api*/doGet path still needs Manage deployments → New version.

---

## Lookout list — things that actually broke

1. **Never write a literal into RAW col I.** It is one spilling ARRAYFORMULA;
   a value anywhere in the column kills every commission on the sheet. That is
   why the loader writes `A:H` and `J:N` as two separate calls.
2. **The 8/2 Tableau format change broke everything keyed on Description.**
   `Description` became a bare token or blank, `Description Detail` went
   permanently empty, and the real payout name moved to a new `Product` column.
   Everything downstream that read Description started lying silently.
   Casualties, each found separately:
   - tier bonus underpaid 4 weeks (WE 8.16 alone: 73 rows / 14 reps / **$3,232**);
   - `Term Length Bonus` + `kWH Bonus` vanished from Description into Category;
   - Lead Disposition lines arrived with *every* text field blank;
   - the Commission `Q3:Q6` box read Base as **$46,414 against a true $400**
     (fixed 9/3 — see 6).
   **Rule: build on `Campaign` (J) / `Category` (M), never Description.**
3. **"Blank Description = Base" is dead** (removed 9/3). It was safe only while
   Base was the one thing Tableau left blank. `BASE_DESCS` / `BASE_BLANK_AMOUNT`
   in `run.py` are dead constants — the P&L moved to Campaign in July.
4. **Lead Disposition is permanent no-pay** and is *supposed* to show $0. It is
   16-ish rows/week (one per BOX rep) that since 8/2 arrive completely blank —
   rep name + amount + campaign and nothing else. They pay $0 only because the
   junk guard (rule 3 of the cascade) happens to catch them. **If you ever
   loosen that guard, they start paying.** They are correctly identifiable now
   via `Category = "Lead Disposition Bonus"`.
5. **`Commission!B1` used to silently lie** — it relabeled the tab without
   rebuilding the table, so one week's numbers sat under another week's label.
   FIXED 9/6 with the `onWeekPick` installable trigger (see Commission tab
   section). Residual traps: (a) the trigger fires on human edits only — a
   script that sets B1 must also call refresh; (b) `_rebuildCore` includes
   `syncCarlosPNL`, so switching to an OLD week re-stamps that week's frozen
   P&L per-rep columns from a fresh recompute — identical numbers unless Rates
   or aliases changed since, in which case the closed week gets restated
   silently; (c) it pops a "P&L synced" dialog that steals keyboard focus.
6. **`P3:Q6` was rewritten 9/3** onto Campaign. Before: B2B $20,166 / BOX
   $15,295 / **Base $46,414** / total $81,875 (which silently included the
   $25,794 captain's bonus, because the `"*Captain*"` subtraction matched a
   description that no longer exists). After: $23,635 / $32,467 / $400 /
   $56,502, matching the P&L. **`_rebuildCore` has wiped `P1:Q6` before —
   re-check it after any refresh.**
7. **Rate changes in `Rates` are retroactive** (and the Rates tab has NO
   history — one cell per rep). Permanent promotions therefore run as auto
   Level-2 bonus rows (see The automation), never as Rates edits. Col I is
   live over all weeks, so
   editing a rate restates every closed week (Jayden 40→45% = **+$2,098** across
   11 weeks, only $151 of it current). For one week only, use an Adjustments
   row — precedent: the 8.9 `Rate 37.5 percent this week only` row.
8. **Tableau row order is not stable between pulls.** Positional alignment of an
   export against RAW is wrong by construction — `--enrich-cols` matches on
   content identity (rep + amount + campaign + product + customer) and blanks
   what it can't match, failing loud past 2%.
9. **The DD export you get depends on the Tableau session.** The laptop pulled
   *Rafael's* 364-row slice while Lucy 2 pulled Carlos's 623-row one. Run
   payroll pulls on Lucy 2.
10. **Late Smart Circle posts.** Rows can appear *after* the Wednesday pull
    (WE 7.26: 10 rows / $6,000 missed). Diff row counts against a fresh export
    before finalizing.
11. **Roster inserts shift the P&L summary blocks.** `_locate_block` finds
    anchors by label and survives it, but `PNL_REP_LAST` / `REV_TITLE_ROW` /
    `REV_CAMPAIGNS` in `run.py` must move by the same amount. Rows past ~165 are
    **not** free space — they're the per-campaign summary block.
12. **The webapp pins a version.** After editing Payroll.gs you must
    Manage deployments → New version, or `?action=refresh` keeps running the old
    code (this silently ran pre-Product code for weeks; now v4).
13. **A repeating refund.** Hamid Asim's −$420.60 (customer Aashish Aman,
    `Category = Customer Refund`) has re-posted **every week since 8.9** —
    $672.96 clawed back over three weeks for what looks like one refund.
    **Unresolved.** Zeroed for 8.30 only.
14. **Duplicate-looking rows are often legitimate** — a 2-line wireless port
    gives identical rows for one customer, same day (Caleb, WE 8/30). Check the
    customer + product before calling it a bug.
15. **Bonus-only reps exist.** Reps with $0 (or no) DD revenue still get paid
    via Adjustments and land in `REVENUE - NOT ACTIVE`. Fernando Salazar and
    Jose Cepeda had *zero* RAW rows on WE 8/30 and were paid $300 each.
16. **Ops:** the laptop repo clone drifts (fetch first); other people push to
    `main` constantly (rebase, retry); the `resume-pushing-v2` merge conflicts on
    funnel-board files — cherry-pick your commit instead of resolving blind.

## Blocked / open

- **Apps Script API is disabled** on OAuth project `964848123914`, so Payroll.gs
  cannot be read or pushed programmatically. Enable at
  `console.developers.google.com/apis/api/script.googleapis.com/overview?project=964848123914`.
  Blocked behind it: putting Commission Type / Category / Product / Description /
  Tier on the rep's wrap, and dropping Lead Disposition rows from rep sheets.
  (`~/Downloads/vantura_codegs.txt` is the *board* Code.gs, not Payroll.gs.)
- **Jayden's 45%** — undecided: Adjustments row (+$150.75, this week) vs Rates
  edit (+$2,098.35, restates 10 closed weeks).
- **Hamid's repeating refund** (13 above) — root cause not investigated.
- **Base @ $150/sale** is an Adjustments patch, not a rule. It is re-entered by
  hand each week and reverts to 40/50% if forgotten. Baking it into `I2` would
  restate 8.2–8.16.

## Quick diagnostics

- Commission looks like the wrong week → check `B1` vs the data, then refresh.
- Every commission is 0/blank → someone wrote a literal into RAW col I.
- A payout category looks wrong → check `Category` (M) and `Campaign` (J), not
  Description.
- Payroll job status → `lucy logtail vantura-payroll-wed-*` (scheduled) or
  `rerun-*-vantura_payroll.log` (manual). Never trust a queue "done".
- Base/BOX/B2B totals disagree between Commission and P&L → the two measures in
  "The P&L" above are different by design; compare like with like.
