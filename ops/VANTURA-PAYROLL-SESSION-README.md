# Vantura Payroll — Session Handoff README
Written 2026-10-20 from the long payroll chat (Aug→Oct 2026), updated 2026-10-22. Read this first when picking up payroll work in a new chat.

## 1. The weekly payroll, in order
Board: **Vantura Master Sales Board** `1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY`.

1. **Wednesday ~11am CT** — Lucy 2 runs `vantura_payroll` automatically: pulls Carlos's Tableau DD ("ICD dd Detail"), appends the week to RAW, sets Commission!B1, writes P&L formulas, refreshes, DMs Carlos the kickoff + checks (tie-out, spares, ORG sweep note).
2. **Week numbers**: `m.d` of the week-ending Sunday with trailing zeros dropped (WE 10/4 → `10.4`). RAW col A carries it; never pre-add a week's rows before the Wednesday load — `_load_raw` RESUMEs (skips the whole load) if the label already exists.
3. **Carlos sends batches in chat** (bonuses / no-pay / set-totals / NPAs). Enter them as Adjustments rows: `Week | Rep (board spelling!) | Bonus/REMOVEALL/NPA | Amount | Label`. "Set total to N" = Bonus of N − current paid (label was "Transition bonus" the week he asked for that). Names MUST match the Commission spelling or the row orphans.
4. **Refresh** after every change: `GET <webapp>?action=refresh` (~40s). URL in gitignored `~/recruiting-report/vantura-payroll-webapp.json`. Then verify the rep's line on Commission AND the P&L tie-out (Carlos Total DD / Payroll must equal Commission TOTAL to the penny).
5. **Standing transfers — check every week until told otherwise**:
   - Everything **Nico Murrugarra → Jayden Willingham** (move RAW col B rows, then recompute Jayden's Level-2 = 5% of his brought; the auto Level-2 row skips him when he had $0 at load time — add/update it by hand).
   - Customers **Tomas Ramos / Noemi Avila / Cecilia Theresa Ramos → Edgar Camunez** (Tomas + Cecilia already moved 10/8; **Noemi Avila still pending** — move her lines when they post).
6. **Lock**: Thursday ~11am CT Apps Script trigger. It has NOT been stamping F1 (known since 9/24). As of 10/18 the lock is self-diagnosing: each run writes "lock ran …" or "LOCK ERROR …" to **Commission!H1** — check H1 Thursday and fix from the error text.
7. **Panels rules**: never list Carlos or Nico in no-revenue panels; first-2-week reps excluded; Lead Disposition never pays.

## 2. P&L mechanics (fixed this session — don't re-break)
- Engine tab "Copy of Carlos PNL 2026": roster rows 3→(dynamic bottom), `z EXTRA` spare rows self-replenish (gas **v11**, confirmed live 10/8). Sync wipes each week's stamp cells before restamping (no more departed-rep ghosts).
- **Auto-added reps get NO campaign in col C** → they fall out of "Carlos Total DD" until C is filled (B2B/BOX/Base). Fill it by hand when a new rep lands.
- run.py anchors are label-driven since 10/1 (`_pnl_rep_last`, rev rows = dd_b2b+31). Full history: memory files `vantura-pnl-selfheal`, `raf-dd-access`.
- Webapp deployment: version pinned; Apps Script triggers run HEAD (that's how the lock patch shipped without redeploy). Headless deploy: Apps Script API PUT (token `~/.config/recruiting-report/script-oauth-token.json`, scope `script.projects` only — cannot touch deployments; repointing the webapp needs the editor UI).

## 3. Probe flags built into `automations/vantura_payroll/run.py`
All run via the Lucy 2 queue (`rerun vantura_payroll --<flag>`), all read-only, long output lands in control-sheet tabs (queue Result cells truncate):
- `--dd-diff` → fresh personal DD vs loaded RAW week ('DD Diff' tab).
- `--raf-test` / `--raf-list` / `--owner-probe` → ORG DD views, per-rep/owner sums ('DD Probe' tab).
- `--fiber-probe` → org-wide D2D ORDERLOG (SalesBoardOriginal): the 16 reps' fiber orders, statuses, pay flags ('DD Probe' + 'Fiber Order Log' + 'DD Reps' tabs).
- `--rafdd-probe` → Raf's PROGRAM SUMMARY downline grid, per-corp deposits per processed week.
- **ORG DD sweep** runs inside every Wednesday load: pulls DDDETAILORG, appends the 16 NDS reps' lines found under non-Carlos owners (dedupes on rep+sale date+customer+amount; can't double-pay). **Carlos extended it 10/28: keep sweeping through WE 11/1 and WE 11/8** — turn it off after the Wed 11/11 run (empty `RAF_DD_REPS` or remove the `_load_raf_extra` call).

## 4. The Raf fiber money — where it stands (OPEN)
Carlos's crew sells fiber/wireless ports under Raf's office (11479, "Alphalete Marketing Inc", owner Rafael Hidalgo). Findings, all verified in Tableau:
- **143 order-log lines since 9/28** for 10 reps (Andrew 25, Jacob 24, Eduardo 23, Smedra 22, Aaron 19, Jose Manuel 9, Sebastian 8, Bazan 7, Diego 5, Jorge 1). **55 lines "Already Paid"** on the 10/3 and 10/10 deposit dates, 35 "Eligible for Pay", rest pending/cancel/disconnect.
- **None of those lines are in Carlos's DD or Commission** (customer-level cross-check). The "NDS Wireless" money on his Commission is from different (business) customers.
- The money paid **office-side under Raf**. His per-line deposit detail is login-locked (like Carlos's own DD Detail); the ICD views, org detail, downline grid, and period pulls have all been exhausted — only corp-level totals are visible.
- **Settle-up path**: Raf exports his weekly commissions file (same family as Nico's Verizon export) for the 10/3 + 10/10 weeks → reconcile line-by-line against the order log (order #s included) → per-rep invoice.
- Christian Perez, Gavin Natividad, Danniel Alvarenga: **zero orders anywhere** — likely selling under other rep numbers; ask.
- Deliverable: **Fiber Order Log** (Google Sheet, color-coded, standalone): `https://docs.google.com/spreadsheets/d/1xgqZARUQ1ltfF2yp6KOuKEpb5GlzkyF80R0o39qOO14` — green = paid (+DD date), blue = eligible, red = cancel/disconnect, cols M/N = not-in-your-DD flags.

## 5. Other deliverables from this chat
- **High Value (Verizon) commission pack** from Nico's deposit export, standalone: Google Doc `https://docs.google.com/document/d/1GnKixvlYeIl-tr7D7lKJMGtqKErtYp2gx8CjWwwnRmw` + a .docx in ~/Downloads. Deposit $4,071.67 reconciled; commission shown at standard 40% (rates unconfirmed for the Verizon crew). To redo: parse `CommissionDetail` sheet of the `~High Value~Commissions.xlsx` export; rep lines = CommissionGroup "Commissions"; mirror the board's 9-column itemized look (black header, Arial 10, per-line commission).
- **Esmeralda tie-out page** (why Revenue-by-Status ≠ deposit): `https://claude.ai/artifact/BkLs8VppaLt8PPQ41K62SR`.
- **Box Revenue-by-Status fixes** (live): buckets by accepted-by-supplier date (was already so); Core vs Ancillary gate = usage ≥10k (BF-tier rule was disproven by Tara); volume bonus = $75 × Core count. Ties to deposits within ~$25–200/rep; residual = SCI's own usage numbers. Deal-level truth only comes from the DD; DD-feedback loop (price funded deals from the deposit) was proposed, not built.

## 5b. UPDATE 10/21–22 — Raf's personal DD now arrives as a CSV (and how to load it)
Raf now exports his own DD filtered to Carlos's reps: `ICD_dd_Detail_filtered.csv` (UTF-16, tab-separated, same columns as the ICD crosstab). WE 10.18: 61 lines / $6,397 across 9 reps, all loaded and tied to the penny (Commission TOTAL = P&L Total DD = $26,410).

**Load procedure (the part that matters):**
1. Parse with `encoding='utf-16'`, delimiter tab; rep lines have `REP.Full Name`; skip the Grand Total row.
2. **Dedupe** against the week's RAW block on (rep, sale date, customer, amount) — the Wednesday ORG sweep can't see Raf's office, so overlap is normally 0, but check.
3. **Name map to board spellings**: Diego Del Pozo Borres → `Diego Javier Del Pozo Borres`, Jacob Ortega → `Jacob Isaiah Ortega` (Name Aliases tab has these). Everyone else matches.
4. **INSERT the rows INSIDE the week's RAW block** (insertDimension before the block's last row) — the P&L formulas use bounded ranges (`RAW!$X$start:$X$end`) and only auto-expand if you insert inside. Appending after the block breaks the tie-out.
5. Write A:H and J:N as two calls (NEVER col I), USER_ENTERED. Campaign comes in as `RES-ATT`.
6. Webapp refresh, then verify per-rep Commission lines and the tie-out.

Known quirk: `RES-ATT` has no bucket in the P&L's "Revenue by Campaign" diagnostic block, so its B2B row looks low. The real totals (Carlos Total DD etc.) are right — offered Carlos a Fiber line there, no answer yet.

## 5c. NEW weekly job — Nico's High Value (Verizon) commissions
Every week Carlos sends `YYYY-MM-DD~High Value~Commissions.xlsx` (Nico's deposit export). Build a Commission tab on the **Verizon Reporting and Sales** sheet (`1DOITkoe7FUBPTPMeiN9yviXF90EMI6bE28xqB100emE`) styled exactly like the Vantura Commission tab.

- **Script**: `~/hv-commissions/build_hv.py` — run `cd ~/recruiting-report && PYTHONPATH=. .venv/bin/python ~/hv-commissions/build_hv.py <xlsx> '<tab name>' <week>`. It parses CommissionDetail (header row 2), flips "Last, First" names, groups per rep, writes rep block + per-rep itemized sections + Brought In/PNL boxes, applies the full Vantura styling (gold week cell, green Profit/Loss col, border grids, centered, black per-rep headers, boxed sections).
- **Rates (CONFIRMED by Carlos 10/21)**: William Bautista 60%, Diego Chacon 50%, Jayden Willingham 45% (Level-2 +5%), everyone else 40%. They live in `RATES` in the script.
- **PNL** on the tab: deposit − payroll − 12% tax. Office-level lines (kicker top-ups, wire fees) = "Office / High Value Adjustments," no payout.
- Tabs so far: "Commission" (WE 10.24: deposit $14,663.35, payroll $6,301, PNL $7,606.23) and "Commission 10.17" (deposit $3,761.67, PNL $2,067.11). Convention: keep one tab per week; current week's can be named just "Commission" — rename it to "Commission <wk>" when the next week lands.
- The 10/19 Word/Google-doc pack for WE 10.17 used flat 40% — the sheet tab supersedes it (Jayden +$25, Diego +$44).

## 5d. Working from a non-Mac device + 10/22 gotchas
State as of Thu 10/22 ~10:45am CT: WE 10.18 has the 61 Raf fiber lines PLUS 5 training bonuses (Anna Gomez, Amelia Jimenez, Zitlaly Valadez, Juanita Hernandez $400 each; Yahir Uriel Lopez $400 + $275 shadow pay — entered via Adjustments by the phone/web chat). Verified: Commission TOTAL $26,410.00 brought / $14,251.85 paid / $10,447.93 PNL = P&L to the penny.

- **A non-Mac chat can do everything on the board except the webapp refresh** — the URL is a secret in a gitignored file on the Mac (`~/recruiting-report/vantura-payroll-webapp.json`). Never paste it into a chat. The no-Mac fallback: Carlos re-picks the week in Commission!B1 (a human edit fires onWeekPick → full rebuild, ~40s). API writes to B1 do nothing.
- **Stale-merge trap (bit us 10/22):** when the rep block grows, the TOTAL row can land on a leftover merged banner cell (A:C merges from the old "ACTIVE REPS" layout). Symptom: TOTAL row has D (Profit/Loss) but B/C blank, and API writes to B/C report success and vanish. Fix: unmerge any A:C merge in the rep-block zone (rows 3–33), then the rebuild writes land. The script's own breakApart only cleans BELOW totalRow+3, so it never removes these.
- **ACTIVE REPS - NO REVENUE panel was blank since 10/3 (found 10/28):** Payroll.gs `_commissionExtras` + the leaders block still read `getSheetByName('Sales Board')` — dead after the NDS rename — so NOBODY was ever listed. Fixed in HEAD 10/28 (reads NDS + BOX boards, Verizon-campaign reps excluded like JE). RESOLVED same day: webapp redeployed to **Version 18** (done via Carlos's Chrome with his OK — version created by API, repoint clicked in the editor UI; the script-oauth token can't touch deployments). ALSO NEW in v18 (Carlos 10/28): active no-revenue reps are **auto-added to the Commission rep block at $0 brought / $0 commission** every rebuild (`_activeNoRevNames` in Payroll.gs — same roll-call+board logic as the panel; Verizon/JE reps and owners excluded), and the ACTIVE REPS - NO REVENUE box stays. Block order is alphabetical (the manager filter's sort), not commission-desc.
- **Bonus-only new reps** (no DD revenue, only an Adjustment) get auto-added to the engine with a BLANK campaign col C and their payout silently drops out of the P&L (payroll reads low by exactly their bonus). Fill col C (B2B for NDS reps / BOX / Base) and refresh. Yahir = B2B, filled 10/22.

## 5e. NDS + Fiber sections on the P&L (added 10/28, corrected same day)
The Revenue-by-Campaign block has TWO new sections: **NDS** (rev_title+20, per-row `NDS Wireless` only) and **Fiber** (rev_title+26, per-row `RES-ATT`). They are SEPARATE programs on Tableau's PROGRAM SUMMARY — the first cut lumped them and Carlos caught it against his own summary (NDS 10.25 = $3,718, matching exactly). **Paid Out on both = line-level RAW col I** (their reps are tagged B2B in engine col C, so the rep-tag SUMIF the other sections use would read $0). To check against Tableau: `download_program_summary(we_sunday=<deposit Sunday+7>)` in `automations/recruiting_report/opt_phase.py` runs fine from the laptop and returns per-owner per-program dollars. Written weekly by `_repoint_pnl` (main `9ec7fb6e`, pulled on Lucy 2) and mirrored onto P&L 2026 (`clean_pnl.CAMPAIGNS` += NDS). Weeks 10.11/10.18/10.25 backfilled by hand. The Commission "Brought In" box (P2:Q8) also shows all five buckets now.

## 6. Open items for the next session
1. **Thursday**: check Commission!H1 for the lock's self-diagnosis; fix whatever error it reports. Lock schedule is back to normal Thu 11am (the one-day 6pm gate was removed).
2. **Wednesday**: confirm late fiber-adjacent lines; run the standing transfers; fill campaign col C for any auto-added P&L reps. (10.18 checked 10/21: no Nico rows, no Noemi Avila, no Jayden revenue — nothing to transfer.)
3. **After WE 11/8** (Wed 11/11 run): shut off the ORG DD sweep — Carlos extended it two weeks on 10/28.
4. **Raf back-pay settle-up**: he can now export his DD (see 5b) — still need the **10/3 + 10/10** weeks' exports to reconcile the 55 already-paid fiber lines against the Fiber Order Log.
5. **Noemi Avila → Edgar** when she posts.
6. **Nico weekly**: build the High Value Commission tab when the export lands (see 5c — rates are confirmed now).

## 7. How to work with Carlos (style)
Short messages, plain language, result first, phone-screen length. He pushes back when something smells wrong — he's usually right; re-verify against raw data instead of defending. Numbers must reconcile to the penny before saying "done."
