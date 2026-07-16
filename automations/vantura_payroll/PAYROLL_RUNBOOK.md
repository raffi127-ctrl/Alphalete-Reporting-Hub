# Vantura Weekly Payroll — runbook (Claude Code edition)

Carlos's spec for the weekly commission/payroll process, as given 2026-07-15.
`run.py` automates the deterministic half of this. NOTE vs §3: on Lucy 2 the
Tableau pull is NOT manual — `run.py` downloads the ICD dd Detail crosstab
itself over the real-Chrome CDP route (Lucy 2's warm ownerville/Tableau
session); §3's manual pull only applies to machines without that session.

Big idea: the entire payroll system is ONE Google Sheet plus the Apps Script
bound to it. Nothing here clicks a browser for the board itself. Everything is
driven two ways:

1. Google Sheets API — read/write cells, formulas, and the RAW/Adjustments
   tabs directly.
2. The bound Apps Script functions (the "Payroll menu" logic) — triggered
   headlessly via a deployed Web App URL (recommended) or the Apps Script API
   `scripts.run`.

This is the same logic as the browser "Payroll menu," just invoked from code.
It also avoids the Google "trying to connect" freezes that plague the UI.

---

## 0. Identifiers (constants)

- `SPREADSHEET_ID = 1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY`
- `SCRIPT_ID = 1mK8wCgQevh5sSWJ1z-FDxd0TZcxfy2OxE7NhUTrQkx5b4W7ngw6H2bq5`
- Board URL: https://docs.google.com/spreadsheets/d/1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY/edit
- Google account: the payroll account (Carlos's gmail) — must have EDIT rights.
- Tab gids: Commission = 1751272760, Copy of Carlos PNL 2026 = 1765991474,
  RAW = 1425857248.
- Hidden data tabs: RAW, Adjustments, Rates, Name Aliases, NoRevPay.

---

## 1. One-time setup (for the headless refresh/lock/print)

Enable APIs in a Google Cloud project tied to the payroll account: Sheets API,
Apps Script API (also toggle on at script.google.com/home/usersettings), Drive
API and Docs API (for the PDF pack).

Auth: an OAuth Desktop client -> credentials.json + one interactive flow to
cache a token with scopes: spreadsheets, script.projects,
script.external_request, drive, documents. (Or gcloud ADC.)

Tooling:

    npm i -g @google/clasp
    pip install google-api-python-client google-auth google-auth-oauthlib openpyxl
    clasp login
    clasp clone 1mK8wCgQevh5sSWJ1z-FDxd0TZcxfy2OxE7NhUTrQkx5b4W7ngw6H2bq5

Add API-safe wrappers (the existing menu functions call getUi()/ui.alert,
which throw headless). After clasp clone, READ Payroll.gs to confirm the real
signatures, then append (adapt names to what you find) and `clasp push`:

    // --- API-safe entry points (added for Claude Code / headless runs) ---
    function apiRefresh(){ _rebuildCore(); try{ syncCarlosPNL(false); }catch(e){} return 'refreshed'; }
    function apiSyncOnly(){ syncCarlosPNL(false); return 'synced'; }
    function apiLock(){ lockCommissionWeek(); return 'locked'; }
    function apiUnlock(){ unlockCommissionWeek(); return 'unlocked'; }
    // printCommissionPack builds a Doc->PDF; make it RETURN the URL:
    function apiPrint(){ return printCommissionPack(); }

    // Web App entry so a simple GET can trigger these:
    function doGet(e){
      var a=(e && e.parameter && e.parameter.action)||'';
      var out;
      if(a==='refresh') out=apiRefresh();
      else if(a==='sync') out=apiSyncOnly();
      else if(a==='lock') out=apiLock();
      else if(a==='unlock') out=apiUnlock();
      else if(a==='print') out=apiPrint();
      else out='unknown action';
      return ContentService.createTextOutput(JSON.stringify({ok:true,action:a,result:out}))
        .setMimeType(ContentService.MimeType.JSON);
    }

Deploy as a Web App ("Execute as: me", "Who has access: only me") and save the
/exec URL where `run.py` reads it: `vantura-payroll-webapp.json` at the repo
root (gitignored) as {"webapp_url": "..."} or env `VANTURA_WEBAPP_URL`. Test:

    curl -L "$WEBAPP_URL?action=refresh"

Alternative that needs NO wrappers: the refresh already runs on a Thursday
11am CT cloud trigger, and the P&L auto-syncs at the end of _rebuildCore. The
wrappers are for on-demand runs.

---

## 2. What lives where (data model)

- `Commission!B1` = week-ending selector (e.g. 7.12). Set this first.
- `RAW` (hidden): A Week Ending | B Rep | C Sale Date | D Act Date |
  E Description | F Desc Detail | G Customer | H Total $ to ICD (brought) |
  I Commission (arrayformula) | J campaign (optional). Each week's rows append
  below the previous week (WE 7.5 = rows 845-1234, 390 rows).
- `Adjustments` (hidden): Week | Rep | Type | Amount | Label. Type in
  {Bonus, NPA, RemoveAll, RemoveLine}. Write here for a bonus/NPA, then refresh.
- `Rates` (hidden): A rep | B base | C override | D effective(=IF(C,C,B)) |
  E note; G2:G = "No-Pay This Week" list (names zeroed even with sales).
- `Name Aliases` (hidden): A other/board name | B real paid name | C note.
- `Copy of Carlos PNL 2026`: per-week 3-column blocks (WE 7.5 = CF brought /
  CG paid / CH profit). Campaign profit blocks + "Carlos Total DD" live here.

Apps Script functions already in Payroll.gs: rebuildCommissionSheets (UI),
_rebuildCore (no UI — the real work), syncCarlosPNL(dryRun),
printCommissionPack, lockCommissionWeek/unlockCommissionWeek,
_appendAdj(week,rep,type,amt,label), _readAdj, _injectAdjReps (fuzzy
name-matching), _commissionExtras, _canon/_nmMatch (name matching + aliases).

---

## 3. What stays manual

- On a machine WITHOUT a seeded Tableau session: the pull (workbook "Direct
  Deposit ICD VIEW" -> view "DD DETAIL" -> Download -> Crosstab -> Excel). On
  Lucy 2 this is automated (see header note).
- Deciding bonuses / no-pay / rate overrides — Carlos supplies the amounts;
  they get written to the Adjustments/Rates tabs.

---

## 4. The weekly run

Inputs: the ICD dd Detail export (auto-pulled on Lucy 2) and the week-ending
(computed; e.g. 7.12).

1. Read the export with openpyxl. Columns of interest (0-based):
   REP.Full Name = 3, cl.Campaign__c = 5, cl.Description = 14,
   cl.Description Detail = 15, cl.Customer Name = 21, Total $ to ICD = 31.
   First data row = grand-total row -> SKIP it. Next rows = line items.
2. Append to RAW: find RAW's last row, write the new week's rows after it.
   A=week, B=rep, C=sale date, D=act date, E=description, F=desc detail,
   G=customer, H=Total $ to ICD. Leave I (arrayformula; if it doesn't extend,
   copy the I formula down). Record the new row range — needed in step 6.
3. Set the week: `Commission!B1`.
4. Refresh: apiRefresh (Web App GET or scripts.run). Rebuilds the Commission
   tab and syncs the P&L. Read the Commission summary back to sanity-check.
5. Adjustments (as Carlos requests): append rows to Adjustments
   (Week | Rep | Type | Amount | Label); no-pay names -> Rates!G. Refresh
   again. Truly different names -> add a Name Aliases row.
6. Per-campaign profit formulas for the new week's P&L column (only the
   Captain's bonus excluded from gross). Pattern — replace the RAW row range
   and the block column (for 7.5: cells CH157/CH164/CH171 and CH184):
   - BOX profit = SUMPRODUCT(inBOX * RAW!H) - SUMPRODUCT(inBOX * RAW!I)*1.12,
     inBOX = (E="BF 1")+(E="BF 2")+(E="Term Length Bonus")+(E="kWH Bonus").
   - Base profit = same with inBase = (E="Energy Enrollment")+(E="RES Pilot
     Program - Weekly Guarantee")+(E="Lead Disposition Bonus")+(E="")
     (blank desc = BasePowerRES $200 lines).
   - B2B profit = SUMPRODUCT((1-NB)*RAW!H) - SUMPRODUCT((1-NB)*RAW!I)*1.12,
     NB = inBOX + inBase + ISNUMBER(SEARCH("Captain",E)).
   - Carlos DD add-back = SUMIF($C3:$C152,"B2B",<brought col>) +
     SUMIF(RAW!E,"B2B Roadtrip Bonus",RAW!H) + SUMIF(RAW!E,"MCOE Bonus",RAW!H)
     (stripped from rep rows but must count in gross).
   Campaign map: Base = Energy Enrollment / RES Pilot / Lead Disposition /
   blank BasePowerRES; BOX = BF 1 / BF 2 / Term Length / kWH; B2B = everything
   else (AT&T/CRU/IRU + MCOE + Next Up + Roadtrip + Tiered/Rep Volume);
   Captain = excluded.
7. Verify (read-only):
   - Orphan payouts: no rep paid with $0 brought that isn't on the Commission
     tab (SUMIFS(paidCol, $C$3:$C$152,"B2B", broughtCol, 0) should be 0).
   - Reconciliation: the three campaign TOTALs should sum to gross (Carlos DD
     - payroll x 1.12). Manual bonuses raise payroll un-tagged — expected.
8. Print pack: apiPrint -> PDF/Doc URL for Carlos.
9. Lock: apiLock (or the automatic Thursday 11am CT lock).

---

## 5. Gotchas / rules

- Only the Captain's bonus is excluded from gross. Roadtrip, MCOE, and
  everything else count.
- Campaign-profit formulas are per-week — re-point RAW ranges + P&L column
  each week (step 6).
- Bonus name-matching is fuzzy; genuinely different names need a Name Aliases
  row.
- clasp push can clobber concurrent edits — always clasp pull right before
  editing. Two script files (Code.gs ~339k = Sales Board; Payroll.gs ~59k =
  payroll). ONLY touch Payroll.gs.
- Menu functions use getUi() — never call rebuildCommissionSheets /
  printCommissionPack directly headless; use the api* wrappers.
- Don't run refresh twice quickly — it queues; wait for one to finish.
- RAW col I is an arrayformula keyed off Rates; if a new week's I cells are
  blank, extend the formula rather than hand-writing values.
- The full click-by-click browser version lives in
  Vantura_Weekly_Payroll_Runbook.md (Carlos's Downloads).
