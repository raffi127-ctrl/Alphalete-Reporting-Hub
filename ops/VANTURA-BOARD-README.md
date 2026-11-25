# Vantura Master Sales Board — How It All Works

_Reference for making changes safely. Written 2026-09-05 after the 9/3–9/5
sessions. Sheet id `1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY`. Keep this
updated whenever the layout or automations change._

---

## The four tabs and what they are

| Tab | What it is | Who writes it |
|---|---|---|
| **NDS Sales Board** | the AT&T program's reps (campaign label **NDS** since 2026-10-03; was "Sales Board" / B2B): one live week, rep day cells + totals + analytics; owns the gold week cell B2 | Slack fill, order-log fill, managers, the bound script |
| **BOX Sales Board** | BOX reps (new 2026-10-02, cloned from the main board: same geometry, CF, filter, validations; B2 = `='NDS Sales Board'!$B$2`) | same writers, routed by campaign |
| **Verizon Sales Board** | Verizon reps (was "D2D Sales Board" until 2026-10-03; dynamic + WeekData-linked since 2026-10-02, same geometry as the others; B2 follows the NDS board) | same writers, routed by campaign |
| **BOX Stations** | BOX car rides / stations / rep list / mark-off (the old "D2D Stations" tab, rebuilt 2026-10-02) | Managers; formulas read BOX Sales Board + Roll Call |
| **Roll Call** | Attendance + roster history (statuses, trainers, terminations) | Managers, the bound script, Slack fill (Here marks) |
| **Stations** | Daily ops: AT&T **NDS** section on top (rows 4-27) + **VERIZON section in the lower block (rows 28-49, since 2026-10-02)**; Q2 week label; hidden helpers R:Y | Managers; formulas read NDS Sales Board / Verizon Sales Board + Roll Call |
| **Daily Update** | Recruiting pipeline log (renamed from "New DU" 9/5); **col M "Week Ending" = ARRAYFORMULA in M1 (9/26) — never type in M** | Lucy 8:45pm fill (append-only, columns by HEADER), Sunday status reconcile, managers |

Support tabs: `WeekData` (board archive, key `Rep|WE`), `RollCallData`
(attendance archive), `Lucy At&t Data` / `Lucy Box Data` (order-log feeds),
`Name Aliases` (old-name → real-name bridges), `Commission` + `Rates`
(payroll), hidden helpers.

## Who talks to whom

```
#alphalete-gp-sales ──(Slack fill, 4-9pm+5am, raise-only)──▶ Sales Board day cells
Tableau order logs ──▶ Lucy At&t/Box Data tabs ──(morning ladder)──▶ Sales Board
      (B2B raise-only 5:02-6:45 · BOX AUTHORITATIVE 7:15-9:30, reposts "corrected" image)

Sales Board day-cell edit ──(bound script onEdit)──▶ Roll Call attendance
      number→Here · X→Off · T→Terminated+terminateWeek (T rest of week, both tabs)
Roll Call attendance edit ──(script)──▶ Sales Board marks (Off→X, T→T, Here→0-if-empty)
Trainer / campaign / rep-name edits sync BOTH DIRECTIONS via the script.

Stations MARK OFF handles PASTES too (9/19): a multi-cell paste into K has
   no per-cell edit value, so the handler re-reads both K zones and syncs
   every name (X on board today, Off on roll today). Managers paste the
   whole off list - that path silently did nothing before.
Stations MARK OFF pick ──(offSyncOnEdit, 9/16)──▶ board today = X + roll today = "Off"
   ...and the OFF is fully LINKED both ways now (Carlos 9/16): un-picking the K cell
   restores the board day cell to its INDEX formula and blanks the roll "Off";
   clearing roll "Off" or removing board "X" clears the other two surfaces incl.
   the K mark-off cell (which kills the strikethrough). offSyncOnEdit lives in
   RollWeek.gs, runs from the vzOnEdit installable trigger (hooked 9/16 - line 27
   of Verizon.gs). The OLD board<->roll off-sync in Code.gs wrote a DEAD hidden
   list (col 91) and the K column had NO handler at all. Script writes don't fire
   triggers, so the 4am K self-clear does NOT un-mark yesterday's board/roll.
Stations formulas ◀── board roster (rep list, by Leadership level) + roll call (new starts, auto-off)
OFF boxes ──(conditional formatting via INDIRECT)──▶ strike-through on Sales Board + Roll Call

Roll Call H1 ("View wk") ──(rollWeekView, 9/17)──▶ G:L attendance columns
   H1 is a REAL week switcher now: pick a week, see that week's archived marks
   (RollCallData); pick the live week (board B2) and the live marks come back.
   Leaving the live week SNAPSHOTS the live literals to RollCallData first, so
   switching can never lose marks. Monday flip guards against a browsed H1:
   closing week = WeekData J3, view restored before archiving. While a PAST
   week is showing, G:L edits belong to that view - switch to the live week
   before marking attendance. H1 is TEXT-formatted (9.20 stays 9.20).

Daily Update ──(script menu "Add New Starts to Roll Call")──▶ Roll Call rows
Roll Call truth ──(Lucy, Sundays 7pm)──▶ Daily Update statuses → "Not Active"
Monday week roll: board → WeekData archive, day cells reset, week label flips (board B2 + Stations Q2)
  — fires Lucy 2 launchd **Monday 08:20am CT** (com.alphalete.vantura-week-roll-mon; moved
    earlier from 11:30 on 2026-09-14). Boxed in the 08:05-08:30 gap: after the production
    post's last 08:05 retry, before car-rides-cleanup takes Stations at 08:30. Truly-earlier
    would need the roll to gate on the production post, not race the clock. Time knob =
    StartCalendarInterval in the plist; redeploy = push main + `lucy rerun update` +
    `lucy rerun install_vantura_week_roll_agent`.
```

## Layout law (things that MUST NOT move)

- **Roll Call columns A–O are frozen**: A week, B status, C campaign, D rep
  name, E 2nd rounder, F trainer, G:L Mon–Sat, M date gone, N days lasted,
  O reason. The bound script hardcodes these positions. Extra columns go
  AFTER O only (Leadership lives at P as a formula).
- **Sales Board**: header r4, reps r5+, B name, C This Wk, D Last Wk, E:K
  Mon–Sun, L campaign, M trainer, N field status, O team, P leadership,
  AE start date. Day-cell vocab: number = sales, 0 = worked no sale,
  X = off, T = terminated, F = floater.
- **Stations**: ride rows = leaders − 2 per campaign; ALL content must end
  at or above **row 52** (the script writes "MONDAY LINEUP" at fixed A53
  daily — rows 53+ are hidden to bury it). Week label at **R2** (week_roll
  writes it; Q2 until the 2026-11-02 Notes column). **Column B is NOTES
  (free text, Carlos 11/2)** — never a name source, never autocompleted,
  grouped with A. Any layout change must re-anchor: `car_rides` BOXES
  ranges, the cross-off CF INDIRECT strings (only the Verizon board's rule
  still has one), CF ranges, the script's column constants and
  `stationsHelperGuard` canon, week_roll's `STATIONS_WE`, frames.
- **Tab names are load-bearing**: "Daily Update", "NDS Sales Board",
  "BOX Sales Board", "Verizon Sales Board", "Roll Call", "Stations",
  "BOX Stations", the Lucy* data tabs. Automations and the script's KEEP
  whitelist reference them literally (renamed 2026-10-03 — see that section
  for the full rename checklist).

## The bound Apps Script ("Untitled project")

Carlos-owned, `Code.gs` (~220KB, menus Alphalete + payroll webapp) +
`Payroll.gs`. It is the live sync engine: onEdit marks, terminations,
trainer/name propagation, add-person dialogs, Start New Week, tenure,
name-clash checks, the Commission ACTIVE/NOT-ACTIVE panel builder.

- It **hardcodes sheet geometry** (constants at the top). Sheet layout must
  match the script, not the other way around — realign the SHEET when in
  doubt (that's how the 9/4 T-splash was fixed).
- Its old Stations painters/autocomplete point at dead ranges — they are
  no-op'd in effect by the sheet's own CF; don't re-enable.
- `cleanupTabs` (menu) deletes any tab not on its KEEP whitelist. Leaders
  Retention, Sheet25 and (until its strings are updated) "Daily Update"
  are unprotected. **Never run it casually.**
- OPEN ITEM: 5 strings inside it still say "New DU" — until fixed, the
  "Add New Starts to Roll Call" menu errors, and its error message wrongly
  says to rename the tab back. **Never rename the tab back.**
- Files in the project: `Code.gs` (the engine), `Payroll.gs`, and
  `Verizon.gs` (the D2D auto-move, added 9/7 — see the D2D section).
- **How to edit the bound script (works, proven 9/7):** open the editor as
  the owner (CarlosHidalgo349) in real Chrome at
  `script.google.com/home/projects/<id>/edit`. Do NOT type code in — Monaco
  auto-closes brackets and doubles them. Instead put the code on the macOS
  clipboard with `pbcopy < file.gs` (it's the same machine), click the file,
  Cmd+A, Cmd+V, then Save with the toolbar disk icon (Cmd+S is often blocked
  by the auto-mode classifier, the toolbar click isn't). The Apps Script API
  (script.googleapis.com) is NOT usable: the only OAuth client on file lives
  in a GCP project this account can't access, and the classifier blocks the
  in-page javascript_tool. em-dashes get mangled by pbcopy — keep pasted code
  ASCII.
- RESOLVED 2026-09-08: the 5 "New DU" strings in Code.gs were changed to
  "Daily Update" via the editor's Find & Replace (Cmd+F → expand to Replace →
  Replace All, then toolbar Save). This was `addNewStartsToRollCall()`'s
  `getSheetByName("New DU")` (line ~2405), its error message, and the KEEP
  whitelist entry. The "Add New Starts to Roll Call" menu now finds the tab,
  and cleanupTabs now protects "Daily Update". Never rename the tab back.

## Stations layout — CURRENT (restructured 2026-09-09; Notes column added 2026-11-02)

Per campaign section: **A Territory Status, B NOTES (free text, 2026-11-02),
C:F car rides (Territory Leader, Rep #1-3)**, STATIONS below in the same
columns, REP LIST H:J, **MARK OFF at L** (single column, right beside the
rep list). Column J is **"In Training / New Starts"**: board reps with
Leadership "In Training" first, then ONE blank row, then the week's Roll
Call new starts (from hidden helpers X5/Y5). New starts inherit all rep-list
coloring and are pickable in MARK OFF and the name type-ahead automatically.
(Before 11/2 everything from B rightwards sat one column to the LEFT:
rides B:F, rep list G:I, MARK OFF K, helpers R–Y, week label Q2 — read old
notes below with that shift in mind.)

Hidden helper columns (S–Z, all load-bearing — NEVER clear or unhide-and-edit):

| Col | What |
|---|---|
| S5 | NDS mark-off dropdown source = TOCOL(H6:J24) |
| T5 | Verizon mark-off dropdown source = TOCOL(H31:J49) |
| U5 | TERMINATED names (live-week roll T/Terminated + board P=Terminated) — drives red+strike CF everywhere |
| V5/W5 | name type-ahead sources (NDS/Verizon) = UNIQUE(TOCOL(H:J)) |
| X5/Y5 | NEW STARTS (NDS/Verizon) roll-call filters — feed col J's second block + car-ride green CF |
| Z5 | union of V/W (runner dropdowns) |

**THE TYPE-AHEAD RECIPE — DO NOT BREAK (Carlos: "the way it works now is
great, lock it in").** Typing part of a name in any car-ride/station cell or
MARK OFF cell pops matching full names. That behavior requires ALL of:
1. data validation `ONE_OF_RANGE` pointing at a **single-column** helper
   (S/T for MARK OFF, V/W for name cells — one column left of that before 11/2);
2. the helper being **blank-free and contiguous** (that's what
   `TOCOL(...,1)` guarantees — a plain multi-column or gappy range KILLS the
   suggestions);
3. `showCustomUi: true` (turning it off leaves validation but no dropdown);
4. `strict: false` (so free-hand names still get accepted, warning only).
Past regressions came from repointing a dropdown at a range with blanks or
multiple columns. If suggestions ever stop: check the helper column spills,
then the four properties above.

**Cleanup law (learned 9/9):** when wiping a zone, clear values, formats,
validations, AND `note` fields — notes survive format wipes and leave black
corner triangles. And keep validation / CF / script-clear RANGES in lockstep
(L5:L18 + L30:L43 everywhere since 11/2; K before) or first-row picks silently do nothing.
R2 (Q2 before 11/2) is the week label the Monday roll writes — never "clean" it.

Cross-off / off flow: pick a name in MARK OFF (K) → CF strikes them red on
rides/stations, gray on the rep list, and strike-through on the Sales Board
and Roll Call (their CF uses INDIRECT to Stations `$K$6:$K$18` and
`$K$31:$K$43` — moved L→K 9/9, M/L both dead; the daily 4am reset clears the
K ranges). Cols L and M are EMPTY in rows 1-56 but the meeting boxes use
them below row 70 — never "clean up" L/M full-height. BOX rep-list header
G29:I29 is merged/shaded brown #B45309 like the section headers; K4 header
blue #1D4ED8 (ATT), K29 brown (BOX).
MARK OFF picks **self-clear every morning ~4am**: `resetOffList` (Code.gs,
daily trigger) clears `L6:L18` and `L31:L43` along with its un-strike sweep
(added 9/9).

**MEETING PREP BOXES (rows 70-108, added 9/9):** two in-sheet versions of
the old printed Word docs, SIDE BY SIDE — **MONDAY LEADERS MEETING at
A70:G108** and **MONDAY SALES TOTALS & GOALS / CIRCLE UP (the Atmo morning
meeting) at I70:O108** (H is the gap column). Their section rows are
deliberately aligned (row heights are shared across a row): bands at r70 /
78 / 86 / 93 serve both boxes, so DON'T re-height those rows for one box
without checking the other. Print either via select-range → File → Print →
"Selected cells".

**Runner pickers (added 9/9):** each Leaders-box band (title r70,
Recognition r78, Competition r86, Announcements r93, Meeting r101) has a
dropdown SLOT built into the right end of each band (merged F:G, lighter
navy #35597D, white bold text) — pick or type-ahead ANY active rep (both
campaigns) to mark who's running that section. Band structure: text merged
A:E (centered), picker slot F:G. Carlos rejected both a far-right white cell
and a mid-band white cell — the slot must stay NAVY-toned so the band reads
as one piece.
Source = hidden helper `Y5` (= UNIQUE TOCOL of U5+V5, i.e. rep lists + new
starts). Same locked type-ahead recipe as everything else. Re-merging a
band across A:G kills its picker.

**MONDAY LEADERS MEETING box detail:** an in-sheet version of
the old printed Word doc — navy bands (title / Recognition / Competition /
Announcements / Meeting), underlined write-in fields, prefilled standards
(NO ZEROS, 12, 3 a day). Managers type into it; nothing automated writes
there. The dead lineup-zone recolor calls (rows 55-142) were removed from
`recolorCarNewStarts` the same day so the daily pass can't strip the box's
formatting. To print just the box: select B70:H108 → File → Print →
"Selected cells".

Retired 9/9 (removed on purpose, don't resurrect): the K new-starts lists,
the auto OFF-TODAY lists, the `colorStationRunnerRows` and
`_recolorChecklists` daily painters (their zones Y:CM were cleared junk),
and all content right of the helpers / below row 56. Q2 still holds the week
label (week_roll writes it — untouched).

## 2026-09-09 session changelog (what changed + what broke)

- Week roll recovered by hand-running the module (Lucy 2 was down Monday);
  8 stale WeekData rows fixed first — the roll's stop-before-flip caught it.
- Field Status confirmed self-advancing (5:33am dailyFieldStatus; counts
  from FIRST Roll Call week, not col AE).
- Stations: MARK OFF consolidated to K (L/M dead), first-row K5/K30 pickers,
  BOX REP LIST header shaded, terminated/new-start/wk-2 CF (T5/W5/X5
  helpers), name type-ahead everywhere, junk zones purged (Y:CM, rows
  57-150, stray validations at r109+), banners trimmed to K, r17 station
  header repainted blue daily by the script, meeting prep boxes built at
  A70:G108 + I70:O108, D2D Stations brought to full parity.
- Apps Script edits: New DU→Daily Update (menu fixed), renameJELineup call
  removed, runner/checklist painters removed, dead lineup recolors removed,
  un-strike widened to A4:R56, self-clears for all MARK OFF columns.
- **NEAR-MISS (browser editor discipline):** a replace-field click that
  landed in the CODE spliced replacement text into resetOffList (line
  ~1094). Caught by reading the post-edit screenshot; repaired by selecting
  the whole line via the LINE-NUMBER GUTTER and pasting the corrected line
  (paste never triggers Monaco auto-close). Rules: screenshot-verify the
  find/replace field has focus BEFORE typing; after every editor edit,
  re-read the touched line in the screenshot; a successful save only proves
  the file PARSES, not that the edit landed where intended.

## Monday week flip — BOTH sides now automated (9/14)

The Monday flip is TWO systems; both are now on timers:

1. **Board roll** — Python `week_roll` on Lucy 2, launchd Mon **08:20** CT.
   Board-only by design: archive to WeekData, Last Wk, day-cell formulas,
   gold cell + Stations Q2.
2. **Roll Call week-start** — bound-script `rollCallNewWeek()` (RollWeek.gs),
   Apps Script time triggers Mon **9am + 11am** (second is catch-up; function
   is idempotent — exits unless board B2 has moved past roll H1). Does what
   the startNewWeek MENU did on the roll side, headless (no getUi):
   terminateGone, snapshot attendance to RollCallData, clear marks, reset
   history formulas, **H1 = new week as TEXT (setNumberFormat("@") first —
   plain setValue turned 9.20 into 9.2, the trailing-zero trap)**,
   _rcdAddWeek, **promote prior-week survivors** (no-T rows -> Active +
   inserted on the board as In Training at the top of their campaign group),
   trainer dropdown, recolors, dailyFieldStatus.

Learned the hard way on 9/14 (first automated Monday):
9/14 afternoon follow-ups (now encoded in RollWeek.gs):
- **Order matters**: remove-terminated and promote-survivors run BEFORE the
  attendance clear (both judge "terminated last week" by the closing week's
  T marks; clearing first made 6 terminated new starts look like survivors).
- **_tMatch is alive-first**: a rehired rep has an old Terminated roll row AND
  a live Active row - the term-first order deleted Jayden Willingham (restored
  by hand: BOX / Level 2 / Last Wk from his WeekData 9.13 row / X for his Off).
- Something scrambled the hidden helper formulas (S5 held T5's, V5 held the
  new-starts filter, W5 held X5's) - BOX type-ahead died and every BOX name
  cell showed the red invalid-triangle. Rebuilt from the recipe; if red
  triangles ever appear across a section, CHECK THE HELPER FORMULAS FIRST
  (labels stay put, formulas are what shift).


- The Python roll left the 9.13 new starts (Michelle Flores + 3) stranded:
  current-week helpers stopped matching them and nothing promoted them.
  `applyRolloverFix` / `fixRollover_` in Code.gs is the MANUAL version of the
  survivor promotion (its `PREVWK` is hardcoded — now "9.13"; edit before use).
- `boardLastRep` (and any board row INSERT) throws "not supported on a range
  with a filtered out row" if someone left the board's basic FILTER on with
  hidden rows. Clear the filter first (API clearBasicFilter);
  restoreBoardFilters puts it back.
- Editor RUN clicks get swallowed by the function-dropdown overlay: a
  1-second "Execution completed" on a function that does real work means the
  WRONG function ran. Always: Escape, click neutral code, screenshot-verify
  the toolbar label, THEN Run — and verify the effect (triggers list, sheet
  state), never the log alone.

## Hand-added new starts (9/15) - the self-healing normalizer

Managers sometimes insert new-start rows at the TOP of the Roll Call by hand.
Those rows inherit the HEADER's paint (orange #C55A11 / navy #1F3764, bold)
and a typed week like 9.20 parses to the NUMBER 9.2 - which silently hides
the reps from the Stations new-start filters (col A no longer matches board
B2). Happened again 9/15 (10 rows + a stray painted empty row; Ricardo Ortiz
missed entirely and added by hand).

Fixed for good, three layers:
1. Roll Call A3:A2000 is TEXT-formatted (typed 9.20 stays text in existing
   rows; hand-INSERTED rows still inherit the header's format, hence #2).
2. `rollDailyNormalize()` (RollWeek.gs): any top-region data row wearing the
   header colors is reformatted from the first clean data row below, and any
   numeric week equal to the board's current week is rewritten as TEXT. Runs
   DAILY at ~6:45am - hooked into `checkNameClashes()` (Code.gs line ~23),
   which already had a daily trigger - and inside the Monday flip chain.
   (A dedicated trigger install kept failing: the editor's function DROPDOWN
   gets stuck as a ghost overlay and swallows Run clicks - piggybacking on an
   existing trigger via Find&Replace avoids the dropdown entirely. If the
   dropdown ghosts: switch files, click into code, retry; NEVER trust a
   1-second "Execution completed" from a heavy function.)
3. `installRollNormalizeTrigger` exists in RollWeek.gs as an alternative if
   the checkNameClashes hook is ever removed.

## 2026-09-18 MIGRATION: Roll Call Leadership at column C

Roll Call columns SHIFTED (+1 from old C): A week, B status, **C Leadership
(new - grouped, dropdown, 2-way synced with board P)**, D campaign, E name,
F 2nd rounder, G trainer, **H:M Mon-Sat**, N date gone, O days lasted,
P reason. The week-view cell moved H1 -> **I1**.

Everything that reads the roll by position was updated IN THE SAME WINDOW:
- Code.gs (R_* constants + ~25 literal sites), Verizon.gs (VZ_RCAMP=4),
  RollWeek.gs v8, Payroll.gs (4 positional blocks).
- Lucy: vantura_du_status, vantura_contacts_sync, vantura_board_audit
  (fallback dict; header-resolution self-adapts), payroll_review, team_tree,
  roster_sync (commit "Leadership column inserted at C").
- Stations W5/X5 + D2D S5 INDIRECT formulas (direct refs auto-shifted).
Leadership sync: edit roll C -> board P instantly; edit board P -> roll C
instantly (offSyncOnEdit branches); rollDailyNormalize bulk-mirrors board->
roll every morning (covers API/Shikamaru-driven changes, which fire no
triggers). Attendance history formulas now key $E & $I$1.

MONDAY FLIP (same date): plist 05:15, WRAPPER polls the sales_boards run
manifest and rolls the moment the production post has DELIVERED (08:20 hard
fallback); week_roll then pokes the payroll web app `?action=rollcallflip`
(deployment Version 7) so rollCallNewWeek() runs in the same breath - board
and Roll Call flip TOGETHER. 9am/11am triggers remain as backstops.

OFF-TODAY GRAY (Carlos liked the accidental version): rule #2 on BOTH tabs -
whole row gray-italic when today's mark is X (board) / Off (roll). Mark-off
strike stays #1 and wins. Board day-cell X-gray and roll Off-chip were the
old partial behavior.

Board Campaign dropdown now includes JE + Verizon (was missing both - nobody
could PICK Verizon on the board).

## 2026-09-18 (evening): menu slimmed, CHIP dropdowns, helper guard

**Alphalete menu** is now just: Add > (This Week's New Starts to Roll Call /
New Starts to Car Rides / a New Team) + Reactivate Rep. Removed at Carlos's
request (all automated or Claude-handled now): Start New Week, New Starts
(bulk), One to Roll Call, Sales Rep, Week-1 Start, every Fix item, Realign /
Health Check. Reactivate Rep audited post-migration: fully constant-driven,
works on the new layout.

**THE AUTOFILL TRUTH (why "type Joe -> Joelle" kept breaking):** the magic
depends on the dropdowns' DISPLAY STYLE being **Chip**. Every time
validations were recreated via script/API (showCustomUi) they silently came
back as ARROW style - suggestions still pop, but Enter commits the literal
text instead of picking the suggestion. Restored Chip style by hand on all
Stations dropdown rules (rides, stations, both MARK OFFs, runner cells) via
Data > Data validation > rule > Advanced options > Display style: Chip.
**RULE: never recreate these validations via API - edit formulas only.**
stationsHelperGuard() (RollWeek.gs, runs in the 6:45am normalizer) re-asserts
the canonical R5/S5/U5/V5/W5/X5/Y5 helper formulas daily if they drift, and
deliberately never touches validations.

## 2026-09-19: week-flip DRESS REHEARSAL — two Monday-killers caught (v13)

Carlos asked for a full rehearsal of Monday 9/21 before it happens: copy the
whole sheet, force the flip on the copy, verify everything. Procedure that
works (took 3 rounds):
- Drive-copy the sheet ("TEST n — … (safe to delete)"). The bound script
  copies WITH it (new script id; NOT exportable via Drive by that id — verify
  code by eye in its editor; prod's project IS exportable).
- Board side: monkeypatch the module — `week_roll.SHEET_ID = <copy id>` and
  `week_roll.dt.date = FakeDate` (today() -> next Monday) — then
  `main(["--apply","--force"])`. A plain --force can NOT roll "away" from the
  week that holds today (guard returns audit_rolled) — the FakeDate is the
  only way. Its rollcallflip poke hits the PROD webapp and no-ops ("already
  on <wk>") — harmless.
- Roll side: open the COPY's Apps Script, Run rollCallNewWeek; first run
  demands auth — the popup opens OUTSIDE controlled tabs: grab its URL via
  AppleScript (Chrome tab enumeration), open it in a controlled tab,
  Advanced > Go to project (unsafe) > Select all > Continue. Then Run again
  (~2-3 min).
- Verify with scratchpad vz_copyverify.py (I1 text, RCD rows, formulas keyed
  $I$1, no Terminated on board, survivors promoted, roll C = In Training,
  Stations Q2 + helper spills, B2/E5).

**Catch #1 — manager FILTERS shred the flip (fixed in RollWeek v12).**
Prod had basic filters on Sales Board AND Roll Call (managers filter
mid-week; 9/14 just happened to be filter-free). With a filter active, row
insert/delete THROW and even plain range writes SKIP filter-hidden rows —
and every step is try/catch-wrapped, so the flip "completes" while silently
losing: 0 survivors promoted, terminated left on the board, attendance
formulas only in visible rows. rollCallNewWeek now REMOVES both filters
first thing; removeTerminatedNow does the same for the board.
restoreBoardFilters (called inside the promote step) rebuilds BOTH filters
pristine — criteria-less, hides nothing — so managers keep their filter UI
and the later clear/reset steps are unaffected.

**Catch #2 — WeekData J3 is a FLOAT and 9.20 became "9.2" (fixed in v13).**
week_roll writes the WeekData J week-list numerically, so the closing week
read as "9.2" — rollCallNewWeek trusted it over roll I1, then snapshot and
promote hunted for col-A week "9.2" and matched NOTHING (silent no-op; the
9/14 flip only worked because 9.13 survives float round-trip — 9.20 was the
first trailing-zero week the coupling ever faced; 12.20 and 1.10 recur).
Fix: derive the closing-week label from **K3's DATE** (can't lose a zero):
`kd=getRange("K3").getValue(); if(kd&&kd.getMonth) prevWeek=(kd.getMonth()+1)+"."+kd.getDate()`.

**Catch #3 — _promoteWeekSurvivors still read the PRE-migration columns.**
name was d[i][3] (old D) — post-migration that's the CAMPAIGN; it would have
promoted rows named "B2B"/"BOX" if it ever got that far. Now d[i][R_NAME-1],
days R_DAY0-based. (Lesson: the 9/17 migration sweep updated camp/trainer/day
indexes in that function but missed name — grep RollWeek for raw `d[i][` when
columns move.)

Round-3 result on the copy, ALL GREEN: board B2/Q2 -> 9.27 TEXT, 42 archived,
This Wk zeros, attendance formulas 36/36 keyed $I$1, RCD 9.20 snapshot,
terminated removed (incl. mid-week Ts), **all 9 week-1 survivors promoted** —
board rows at top of their campaign block with trainer carried, Last Wk 0,
In Training in P, recruit-end 9/20/2026 for B2B (blank for BOX), day
formulas, roll B -> Active + roll C -> In Training, campaign totals shifted
intact (123/71/194), numbering 1..49, filters back on pristine.
RollWeek.gs is now **v13 (495 lines)** in PROD. Copies 1-2 trashed; copy 3
("TEST 3 — Vantura Week Flip Dry Run (safe to delete)") left for inspection.

## 2026-09-21: real Monday flip broke — STALE WEBAPP DEPLOYMENT (v14 + redeploy)

The first live Monday after all the dry-run work broke anyway, and the reason
is important: **the Monday roll-call flip runs through the web-app DEPLOYMENT,
not HEAD.** week_roll (board, Python) rolled fine at ~5:15, then poked
`?action=rollcallflip`. That webapp was still **Version 7 (Sep 18)** — the
pre-v12 code with the filter bug — because pasting v13/v14 into the editor only
updates HEAD. So the flip ran the OLD code: promoted nobody, left 2 terminated
on the board, installed attendance formulas only in filter-visible rows. The
9am/11am HEAD triggers could NOT self-heal: the broken flip had already set
roll I1 = 9.27, so the guard (`oldWeek===newWeek`) no-ops them. Symptom Carlos
saw: last week's new starts missing from the Stations rep list (they were never
promoted onto the board, and the Stations "In Training" columns are FILTERs off
the board's P column — no board row, no Stations entry).

**RULE (now the #1 deploy gotcha): after ANY RollWeek/Payroll paste, REDEPLOY
the webapp — Deploy > Manage deployments > edit (pencil) > Version: New version
> Deploy. Same URL. HEAD-only changes do NOT reach the Monday poke.** The stored
URL in `vantura-payroll-webapp.json` is unchanged across redeploys.

Recovery (v14 `recoverFlip0921()`, a one-shot; ran 8:43-8:45am): filters off →
delete board rows whose OWN P(16)=="Terminated" (unambiguous; leaves rehires
like Jayden, who is Level 2 on the board but has only old Terminated roll rows,
alone — roll-status matching would wrongly delete him) → `_promoteWeekSurvivors`
→ reinstall attendance formulas on every roll row → renumber/restore filters/
recolor. Then redeployed webapp to **Version 8**.

**Permanent hardening in v14:** `_promoteWeekSurvivors` now skips
status=="Terminated" rows, not only day-T-marked ones. A partial flip clears the
protective T marks before recovery runs, which would otherwise promote a
terminated rep (Diego Andres Urdaneta, Dayana Paola Paz had cleared marks).

**INSERT-SHIFT on cross-sheet refs (bit us during recovery):** promoting 9 reps
inserted board rows, and Google auto-shifted the STATIONS rep-list FILTERs from
`'Sales Board'!$B$5:$B$60` to `$B$11:$B$67` (and W5/X5 MATCH `$B$5:$B$64` to
`$B$11:$B$71`) — so the 6 B2B survivors at board rows 5-10 fell outside the
range and vanished from Stations even though they were on the board. The
board's OWN stat ranges are self-healed by `reanchorBoardStatRanges`, but
cross-sheet refs are NOT. Fix = reset G6/H6/I6/G31/H31/I31 to `$5:$60` and
W5/X5 to `$B$5:$B$64`. **Watch this after any board row insert/delete: grep
Stations formulas for `'Sales Board'!$B$1` (shifted anchors).**

Jayden Willingham anomaly to flag: he's active on the board (Level 2, 23rd Wk,
B2B) but has NO active roll row — only old Terminated rows (9.6, 4.26). That
makes him a standing target for terminated-removal every flip. Worth giving him
a live Active roll row so the alive-first guard protects him.

## 2026-09-25/26: NoShow ≡ Off, deployed through the Apps Script API

Carlos: "no show should do the same thing as someone being marked off." Three token
swaps, no logic change: Code.gs attMap treats `noshow`/`no show` as the `off` class
(Stations cross-off + board X), `_rlk.tryLock(10000)` (was 0 → today-column edits
silently skipped recolorRepList when another run held the lock), RollWeek v15
un-off (`_wasOff`/`_nowOff` include NoShow, so clearing a NoShow un-X's the board
like clearing an Off). Attendance map is now: Here/Late→0, Off/NoShow→X, T→T.

**Deploy path that finally works (the 4,070-line Code.gs never persisted from the
browser editor):** Apps Script API `GET/PUT https://script.googleapis.com/v1/projects/
1mK8wCgQevh5sSWJ1z-FDxd0TZcxfy2OxE7NhUTrQkx5b4W7ngw6H2bq5/content` with all 5 files
(`{name,type:SERVER_JS|JSON,source}`), token `~/.config/recruiting-report/
script-oauth-token.json` (scope script.projects), header `X-Goog-User-Project:
swift-icon-472718-s0` (the API is enabled in Carlos's "My Maps Project"; the OAuth
client lives in rafael-crm which he can't administer), and the user toggle at
script.google.com/home/usersettings ON. The API syntax-checks and REJECTS bad code
("Missing catch or finally", "Unexpected end of input") — inline `//` comments on
compact single-line statements comment out the trailing braces; use comment-free
token swaps. PUT = HEAD only: the Monday poke still calls the VERSIONED webapp
(Version 8, v14 flip code — unchanged by v15, so Monday is fine); any future
RollWeek flip change still needs Deploy → Manage deployments → New version.

## 2026-09-26: Daily Update "Week Ending" column at M (+ Lucy readers now header-resolved)

**What:** Carlos asked for a "Week Ending" column right of "2nd round Interview Date"
(L). Inserted column M via the API (insertDimension, inheritFromBefore) and put ONE
formula in the header cell **M1**:

```
=ARRAYFORMULA({"Week Ending"; IF(L2:L="",, IF(ISNUMBER(L2:L), L2:L-WEEKDAY(L2:L,2)+7,
  IFERROR(DATEVALUE(TRIM(L2:L))-WEEKDAY(DATEVALUE(TRIM(L2:L)),2)+7,)))})
```

= the Sunday of the Mon–Sun week that holds L (same rule as the board weeks and
Leaders Retention AB). Number format m/d on M2:M. Verified against Python for all
2,702 dated rows (0 mismatches, every value a Sunday); 'n/a' / blank L → blank M.
Visible layout is now Status | Campaign | Name | 2nd round date | **Week Ending** |
Orientation Date | Job Ad | Classroom Retention (N..R and V..AA stay hidden).

**Why the HEADER cell holds the formula:** the tab carries a manager basic filter
with 14 sort keys. Sorting moves row 2, so an M2-anchored ARRAYFORMULA would walk
away or #REF!; M1 sits outside the sorted rows and M is a pure function of L in
the same row, so any sort/filter keeps it consistent. RULES: never type into column
M (a typed value blocks the spill → M1 shows #REF! "would overwrite data in Mnnn";
delete the typed cell); never retype the M1 header (that deletes the formula → the
whole column goes blank; paste the formula above back into M1).

**Why the ISNUMBER branch:** `TRIM(date-cell)` returns the DISPLAYED "6/18" and
`DATEVALUE("6/18")` assumes the CURRENT year → every 2025 interview date landed on a
2026 Sunday (74 rows wrong on the first cut). **Leaders Retention AA
(`DATEVALUE(TRIM('Daily Update'!L2:L5998))`) has this exact pre-existing bug** — its
2025 rows read as 2026 — FIXED 9/26 at Carlos's request: AA2 now `IF(ISNUMBER(L), L, DATEVALUE(TRIM(L)))` (74 rows moved to their real 2025 dates; report body unchanged for the selected week). Also latent: Lucy's fill
writes L as RAW text "9/24" (no year), so in January 2027 December's text dates
will resolve to 2027 in BOTH formulas until the fill writes real dates.

**What shifted (every item verified by script, pre vs post):** old M..Z → N..AA; the
basic filter range A:V→A:W with all 14 sort keys and 7 filter columns shifted and
'Not Active' still hidden; filter view "final" widened; hidden-column set shifted (M
visible); data validations moved with their columns (M has none); frozen A:I
unchanged; Leaders Retention ARRAYFORMULAs auto-shifted (L stays L; N→O, O→P, P→Q,
Q→R, R→S, T→U; A stays) with identical values; Apps Script addNewStartsToRollCall
resolves NAME/ORI/CR/2R by header (2R now O, Orientation S, CR U) — no script change.

**Lucy modules that WOULD have broken (positional readers) — fixed on main
(83083932) and pulled on Lucy 2 BEFORE the insert:** daily_update_fill (the `I:S`
positional append block, T reads, `A2:T6000` + row[13/17/19]), team_tree (`A1:R4000`
+ row[13]/row[17]), vantura_contacts_sync (`DU_2ND=13, DU_ORIENT=17`). New
`automations/recruiting_report/du_layout.py` → `resolve(header_row)` maps status /
campaign / name / email / phone / date2 / first / second / show / offered / bob /
orient / ad / cr / week_ending by header text (classic-position fallback) and serves
the master (with Week Ending) AND the 11 owner boards (classic layout, different
wording: "2nd rounder", "job ad / source"). The fill now writes ONE CELL PER FIELD —
never an I:S block, because a blank positional write over M would wipe the formula.
Proven identical on both layouts before and after the insert: 74 contacts targets
(same digest), 10 status flips, Justin Wood +0 / 31→Active / 4 flips, team_tree 26
scheduled. vantura_du_status (header-resolved) and vantura_board_audit (A/I only)
were already safe; att_order_log only lists the tab name.

**Format trap, again — and the 9/19 "fix" is DANGEROUS.** repeatCell on M2:M
silently skipped the filter-hidden 'Not Active' rows (162 text-date rows kept a
text format → showed raw serials). I applied the 9/19 recipe (clearBasicFilter →
repeatCell → setBasicFilter(saved)) — and **setBasicFilter with the saved
`sortSpecs` RE-SORTED the whole tab** (14 stale sort keys the managers had set long
ago). Worse, a filter sort only moves the FILTER RANGE (A:W); the 4 hidden checkbox
columns X..AA (Digi Docs / Email Forwarded / Headshot / Quizzes, ~3,760 cells) sit
OUTSIDE it and stayed put → misaligned with their people. Recovered with File →
Version history → **Restore** "Today 4:15 PM" (the only later edit was my own
batch; Sales Board / Roll Call / Stations / WeekData verified identical before and
after; Leaders Retention AA2:AI6 back to the morning baseline; Daily Update L2 back
to 45826). RULES: (1) never `setBasicFilter` with `sortSpecs` — strip them, or
don't touch the filter; (2) to format filter-hidden rows use **`updateCells`** (one
RowData per row) — it honors hidden rows, repeatCell/copyPaste do not; (3) the
manager filter's range (A:W) excludes X..AA, so even a manager sorting through the
filter UI misaligns those four checkbox columns — extending the filter to A:AA
— DONE 9/26 at Carlos's request: filter set to A:AA via setBasicFilter with filterSpecs only (sortSpecs dropped; rows verified unmoved).

**What breaks when you change X:** insert/delete a Daily Update column → Lucy readers
survive (header-resolved) and Sheets shifts the Leaders Retention refs itself.
RENAME a header ("Orientation Date"→"Start Date") → du_layout falls back to the
classic position for that key = silently the wrong column; keep the header words
(name / 2nd round … date / 1st round / 2nd round(er) / show / offered / bob /
orientation / job ad / classroom|retention / week ending). Owner boards: adding a
Week Ending column there is optional — the resolver already tolerates it.

## 2026-09-28: Monday check — what recurred, what didn't (and 3 fixes)

Carlos asked to re-check this Monday against the earlier Monday failures.
**Flip itself: clean.** week_roll 5:15am exit 0, board B2 = "10.4" (text),
Stations Q2 10.4, roll I1 10.4, WeekData/RollCallData "Name|9.27" archived,
7 survivors promoted to In Training at the top of their campaign groups, day
formulas in every rep row, no Terminated rows left, both basic filters
restored criteria-less, no header paint on the roll's top rows, no numeric
week labels. 11 of the 12 removals were legit (T marks + Terminated roll).

**Recurred #1 — Jayden Willingham deleted AGAIN (the 9/14 bug).** He sold 11
last week and had no T, but his only Roll Call rows were old "Terminated" ones
(9.6 and 4.26), so the flip's terminated-removal matched him. Nobody had given
him a live row after the 9/21 warning. FIX: board row re-inserted at row 23
(Level 2 / 24th Wk / Last Wk 11 / day formulas / # renumbered; campaign B2B —
Carlos corrected my BOX guess, her BOX trainees notwithstanding) and roll
row 71 set to Active + B2B (it was Terminated + B2B; RollCallData shows that
row was Active through 9.13 and got terminated in the 9.20 week). Trainer (M)
and team label (O) are BLANK — could not recover them (the version viewer
only shows changed rows; the copy-version popup is blocked in the pane; the
team-tree PNG is too big to read through Slack). Carlos to fill in. RULE: a
rehired rep needs an Active roll row BEFORE Monday or the flip removes them.

**Recurred #2 — Stations "In Training / New Starts" (AT&T) list was DEAD.**
Someone typed "yariel Martin Caban" into I6 (the FILTER anchor) and the rest
of the list (I7:I13) was a pasted static copy — it still listed a terminated
rep and three who are now Entry Level, and would never have shown this week's
new starts (the 9/21 symptom, one week later). FIX: I6 formula restored
(B2B mirror of I31: In Training from board P + the W5 new-start pool), static
cells cleared, and all six list formulas (G/H/I 6 and 31) re-anchored to
'Sales Board'!$B$5:$B$60 — they had drifted to $B$5:$B$55 and I31 to
$B$8:$B$55 after the flip's deletes/inserts (they drift EVERY Monday; the
9/21 note stands).

**Reported by Carlos — Gary's campaign change on the Roll Call didn't reach
the board/Stations.** The 9/17 two-way sync only covered Leadership (roll C
<-> board P). FIX: RollWeek v16/v17 — the roll<->board mirrors were rewritten
(_mirrorFind / _mirrorRollToBoard / _mirrorBoardToRoll): Leadership (roll C <->
board P) AND Campaign (roll D col 4 <-> board L = B_CAMP), dispatched from
offSyncOnEdit for single edits and for pasted/filled blocks (every row of the
edited range, up to 200), names matched exact -> Name Aliases tab -> unique
first+last token; board->roll writes the NEWEST roll row. Stations lists follow
board L. Pushed via the Apps Script API (HEAD; onEdit runs HEAD, no redeploy).
Live-tested both ways: roll D66 BOX -> board L18 + Stations (Gary), and board
L39 BOX -> roll D50 (Kyara, accidental click under a filtered view — proved the
board side). Carlos's own edits made BEFORE the push (Gary, Kyara) had to be
mirrored by hand; Nico's roll row was stale (BOX) and set to B2B per Carlos.
Jayden is B2B (Carlos), not BOX. LIMIT: script/API writes fire no trigger.
TRAP while testing: with a manager filter on the board, the pane's row->pixel
mapping is off by hidden rows — verify the Name Box, or edit via the API.

**Stations dropdown look (Carlos: rows 41+ differ from rows <=40).** The data
validation RULES are identical in the API (ONE_OF_RANGE on $V$5:$V$60,
showCustomUi) — the difference is the UI-only *Display style*: B31:E40 =
Arrow, B41:E41,A44:E56 = Chip (and on the AT&T side A18:A27,B26:E27 = Chip vs
B6:E15,B18:E25 = Arrow). Set both Chip rules to Arrow via Data > Data
validation > rule > Advanced options (the API cannot read or set this). This
REVERSES the 9/18 "chip-ify everything" note: Carlos now wants Arrow.

**Roll-call marks -> board (Carlos caught one that never landed).** Audit at
10:31: all 5 Off/NoShow people had their board X and Stations strike; 27
people marked Here had EMPTY board Monday cells; by 10:45 the 0s were there
(a later paste/sweep filled them). The single-cell Here->0 / Off->X / T->T
write is Code.gs's SIMPLE onEdit (`_writeBoardZeroIfEmpty` / `writeBoard`),
best-effort under rapid marking (each run also does a full recolor behind a
10s lock). Pasted blocks were already covered by the installable
vzOnEdit -> offSyncOnEdit -> rollAttendanceSweep. FIX (RollWeek v18): the
installable path now runs `rollAttendanceSweep()` on every SINGLE-cell roll
day edit too (idempotent, fills empty board cells only; un-off still restores
the day formula first). Audit script: compare roll H..M marks vs board E..J
(Here/Late->0, Off/NoShow->X, T->T) and the Stations strike state.

**Lucy 2 weekend/Monday logs (first runs on the header-resolved Daily Update
code):** team-tree 6:00am both days fine ("26 scheduled orientations", same
as the dry run), vantura-contacts-sync 9:30pm ran, vantura-du-status Sunday
7pm ran. The 8:45pm daily_update_fill card's log name did not match
"daily-update-fill"/"library" in logtail — find the card runner's log file
name before assuming it ran.

## 2026-09-29: Verizon day — "why was Jayden terminated?" (she wasn't) + blank rows

Carlos relabeled ten reps **Verizon** on the Roll Call (Will, Nico, Gary, Luis
Valenciano, Kyara, Jayden, Yariel, Giovanni, Richard, Gavin + four new starts).
His own Verizon auto-move (Verizon.gs, 9/7) moved each row off the Sales Board
onto the **D2D Sales Board** — so "not on the Sales Board / Stations" for a
Verizon rep is BY DESIGN: Verizon reps live on the D2D tabs (D2D Stations lists
filter the D2D board). Jayden = D2D row 14, Level 2, LW 11.

**Manual adds/moves today (all mirrored from what Verizon.gs does):** Diego
Chacon reactivated (roll Active/Verizon, D2D In Training 1st Wk); Thais Alvarez
Aragon new start (roll r3 "10.4"/New Start/Verizon + D2D); Edgar Camunez and
Hamid Asim revived as B2B Level 1 (roll + main board), then moved to Verizon =
D2D rows 21-22 (Hamid had NO roll row left — history only in WeekData 4.12-5.10;
made one). Edgar's roll->Verizon flip did NOT auto-move him (cause unknown — the
mirror wrote board L, the move never ran; no toast reported) — moved by hand.

**Blank rows on the Sales Board (Carlos's screenshot):** `vzClear_` blanks the
vacated row on purpose (keeps C's =SUM and the row) — fine for one move, ugly
for ten. Deleted the 12 blank rep rows via the API (deleteDimension works even
under the managers' BOX-only basic filter), renumbered A; Stations anchors
shrank to $5:$51 and still cover every rep. **Verizon.gs v2:** `vzLeave_` —
leaving the MAIN board now DELETES the row (fallback: blank it if the delete is
refused under a filter); leaving D2D still blanks (fixed 5..34 grid);
`vzFreeRow_` on a compact main board INSERTS a row above the "AT&T (B2B)" totals
(formats from the row above, C =SUM, # continued) instead of "move held".
Rows shift constantly now (roll rows too — managers insert new starts at the
top) — never cache a row number across calls; re-find by name.

## 2026-10-01: "Late - C" added to the Roll Call Mon-Sat dropdowns

Added through the Data validation sidebar (three rule blocks: H3:M500,
H501:M614, H615:M1164 — the UI route keeps the chip display style; an API
rewrite would downgrade them to Arrow), yellow chip, plus a CF rule TEXT_EQ
"Late - C" with Late's yellow (ffeb9c) on the same ranges. Script: any mark
that STARTS with "late" counts as present — Code.gs onEdit writes the board 0
and removes the rep from the off list; RollWeek's rollAttendanceSweep writes 0
too (`indexOf("late")===0` in both). The lists had never contained a plain
"Late" option (only the CF rule); current options: Here / Off / STF / NoShow /
T / Floater / Late - C.

## 2026-10-02: THREE BOARDS — B2B / BOX / Verizon, and the Stations swap

Carlos: "Box, B2B & Verizon each have their own sales board now. Verizon & B2B
share the stations tab, BOX gets its own — swap Verizon and BOX. Do whatever you
need to not break things." Done the same night, rehearsed first on a Drive copy
(`BACKUP - Vantura Master Sales Board 10-2-26 (pre 3-board split) — rehearsal
copy`, id 1iB0ZgquP_Rvg-xFIiNpClX708of1MrzRWwnUeJXE61g — also the pre-change
backup; safe to delete later).

**Boards (identical geometry, header r4, reps r5+, A # / B rep / C =SUM / D Last
Wk / E:K Mon..Sun WeekData lookups / L campaign / M trainer / N tenure / O team
/ P leadership / AE start; rep block ends at the first stat label row):**
- `Sales Board` = B2B only. Name kept on purpose: it is load-bearing in the KEEP
  list, every Lucy module, the Hub links and the week roll. Stat labels
  "AT&T (B2B)" / "TOTAL"; the BOX total row, BOX % rows, BOX headcount row and
  BOX teams sub-block were removed (the ALL rows now equal the B2B rows).
- `BOX Sales Board` = BOX only. Made with sheets.copyTo of Sales Board (keeps
  CF/validations/filter/merges/hidden cols), non-BOX rows deleted, stat labels
  "BOX" / "TOTAL", % block + Headcount + Teams box rewritten for BOX,
  `B2` = `='Sales Board'!$B$2` so the Monday roll flips it.
- `D2D Sales Board` = Verizon. Converted from the fixed 30-row grid to the
  dynamic model: empty rows deleted, day cells E:K are now the same WeekData
  INDEX/MATCH formulas as the other boards (this week's typed values were first
  archived into WeekData as `Name|10.4` rows so nothing showed blank), cross-off
  CF re-pointed to `'Stations'!$K$30:$K$43`.
- WeekData keys stay `Rep|WE` (board-agnostic). The gold week cell is ONLY
  `Sales Board!B2`; the other two B2 cells are formulas — never write them.

**Stations swap:** the main tab's lower section (rows 28-49) is now VERIZON:
A28 red band "VERIZON (D2D)", labels row 30 (Territory Status | Territory
Leader | Rep #2-4), car rides 31-38 (Verizon kept its territory-status column
A — the CF colors for need-new-T/good/etc. already covered A30:A41), stations
block r42-48 with one combined label row ("Station 1 (Intro)"...), rep lists
G31:I49 FILTER `'D2D Sales Board'` + "Verizon", mark-off K30:K43 (dropdowns
re-asserted from S5 — the clear dropped them), helper X5 = Verizon new starts
excluding `'D2D Sales Board'!$B$5:$B$64`, T5 extended to all three boards'
P="Terminated", the 2nd-Wk yellow CF re-pointed to the D2D board, AT&T lists
re-anchored to `$B$5:$B$60` (the BOX row deletions had shrunk them to $32).
`D2D Stations` was RENAMED `BOX Stations` (gid 1984019054 unchanged) and
rebuilt with BOX's layout: title rows 2-4, labels row 5, car rides 6-15, stations
block 17-24 (Closing/Rebuttals labels), rep lists G6:I25 FILTER `'BOX Sales
Board'` + "BOX", mark-off K5:K18, helpers R5 (TOCOL G6:I25) / S5 (BOX new starts
excluding the BOX board), dropdowns ONE_OF_RANGE `$R$5:$R$40` on rides /
stations / mark-off, 16 CF rules remapped from the old D2D shapes (terminated
red via INDIRECT to main `'Stations'!$T$5:$T$60`, dup-red, off strike, placement
colors, white catch-alls), formats + column widths copied from the main tab.

**Bound script v20 (API-pushed; webapp redeployed as Version 12 on Oct 2 9:48pm
— the same deployment ID the Monday poke calls):** constants `BOX_BOARD`,
`VZ_BOARD`, `BOX_STN`, `BOARDS`; helpers `boardForCamp` / `campForBoard` /
`stnForCamp` / `boardSheets()` / `_isStatLabel` / `findRepOnBoards(name)`.
`boardLastRep` stops at any stat label (not just "AT&T(B2B)") and counts
Verizon rows. Multi-board: `writeBoard`, `_writeBoardZeroIfEmpty`, onEdit's board
branch (`BOARDS.indexOf(name)`), rename propagation, `unterminateRep`,
`restoreBoardFilters`, `dailyFieldStatus` + `progressTrainingStatus`,
`refreshTerminatedLead`, `fillMissingThisWeekFormulas`, `recolorRepList` /
`recolorCarNewStarts` (both stations tabs; bands [[6,25],[29,40]] main,
[[6,25]] BOX; off/terminated sets from every board; TERM_COL only on main),
`assignNewStartsToCarRides` (B2B → Stations 6-25, Verizon → Stations 29-40, BOX
→ BOX Stations 4-15), `resetOffList` clears BOX Stations K5:K18, KEEP whitelist
+4 tabs. RollWeek: offSyncOnEdit gates on both stations tabs + all boards; K
mark-off zones per tab; `offBoard`/`unK`/mirrors/`rollAttendanceSweep`/daily
leadership mirror go through `findRepOnBoards` / `boardSheets()`;
`stationsHelperGuard` canon = Verizon X5 + BOX Stations R5/S5; the Monday flip
removes terminated + reinstalls formulas + restores filters PER BOARD and
promotes each survivor onto `boardForCamp(roll D)`. Verizon.gs v3 = generic
campaign move between any two boards (board L or roll D edit → copy row, insert
above the target's totals, DELETE the source row; roll Verizon with no board row
still adds to the Verizon board as a new start; B2B/BOX new starts wait for the
Monday promotion). ALSO FIXED: Code.gs onEdit wrote a board campaign change
into roll col 3 = Leadership (stale since the 9/17 column insert) — now col 4.

**Lucy side:** commit `a64a49a0` (merged to main as `045dcdfe`, pulled on Lucy 2
2026-10-02 ~10:15pm; 122 tests green, dry-runs on the rehearsal copy)
(`automations/vantura_boards.py` shared resolver; sales_boards + week_roll,
vantura_slack_sales, vantura_orderlog_sales, vantura_board_audit, team_tree,
vantura_revenue_board, promo/payroll helpers, daily_update_fill, car_rides,
order-log protected-tab lists). Each writer routes by campaign → tab; week_roll
archives/resets all three boards; the Stations Q2 label and the webapp poke are
unchanged.

**Verify after any future change:** `scratchpad/check_boards.py <sheet id>`
(this session) — tabs, per-board rep/campaign/stat-label/formula/#/filter
checks, WeekData rows, Stations + BOX Stations formulas/helpers/lists/dropdowns/
CF, roll-vs-board campaign consistency. Known cosmetic: the API renumber of col
A had to be re-run once per board (last row kept its old number).

**What breaks when you change X (new):** rename any of the three board tabs or
"BOX Stations" → the script constants, Lucy `BOARD_TABS`, Stations FILTERs and
CF INDIRECT strings all break at once. Add a 4th campaign → `boardForCamp` /
`stnForCamp` / `BOARDS` / Lucy `BOARD_TABS` / stat-label set. Rows inserted on
BOX Sales Board or D2D Sales Board shift the BOX Stations / Stations-lower
FILTER anchors exactly like the main board always did ($5:$60 canon).

## 2026-10-03: NDS RENAME — "Sales Board" → "NDS Sales Board", "D2D Sales Board" → "Verizon Sales Board", campaign B2B → NDS

Carlos: "Instead of Door-to-Door Sales Board, call the tab Verizon Sales Board.
Instead of B2B it's now NDS — the name of the program we're switching to. Flip
every active and orientation-scheduled rep to NDS, add NDS as a campaign
everywhere B2B shows (stations, roll call), AT&T B2B → AT&T NDS on the board.
Through all the scripts, all the formulas, everything — make sure the tab names
get changed correctly so nothing gets screwed up." Done 10/3 morning (scratchpad
`rename_nds.py`, verified by `check_boards.py` ALL GREEN + `scan_leftovers.py`).

**Sheet**
- Tab renames: `Sales Board` → **NDS Sales Board** (gid 1898586497, still owns
  the gold week cell B2), `D2D Sales Board` → **Verizon Sales Board** (gid
  1620149423). BOX Sales Board / Stations / BOX Stations unchanged. Sheets
  auto-updates DIRECT refs on a rename; everything else was rewritten by hand:
  INDIRECT strings (Stations cross-off/2nd-Wk CF, BOX Stations CF — the
  copyTo clone had carried `'Sales Board'`), the helper-guard formulas, every
  script literal, Lucy's tab map.
- Campaign label **NDS**: board L on all 16 main-board reps, Roll Call D on the
  17 live rows (Active / New Start), Daily Update F on Active + Orientation
  Scheduled (+ Gavin Natividad, Showed to Classroom 9/22). History keeps the
  old words ON PURPOSE: 316 Terminated roll rows say B2B, 862 Not-Active DU
  rows say "B2B ATT" — do not mass-replace them (filters, retention math).
- Labels: "AT&T (B2B)" → **"AT&T NDS"** (board stat row 21, K-box campaign
  rows, Stations A3 band, campaign/headcount boxes, "All AT&T NDS Reps").
  Header text row 2 of the NDS board says "AT&T NDS (one app per sale)".
- Dropdowns (all ONE_OF_LIST, Arrow style — the campaign chips never had
  colors so nothing was lost): Roll Call D3:D1164 = NDS/BOX/Verizon/JE/Base/B2B
  (set with `updateCells` because `setDataValidation` SKIPS filter-hidden rows
  — the managers' filter showed 6 of 498 rows and the first attempt only hit
  those); NDS board L = NDS/BOX/Verizon/B2B/Manager, BOX board L =
  BOX/NDS/Verizon/Base/JE/B2B (L18 had a stray old list — fixed), Verizon L =
  Verizon/NDS/BOX; Daily Update F has NDS; Stations ride/mark-off lists have
  NDS. `ensureRollCallValidation` (runs at every flip) rebuilds the roll list
  from the script — change it THERE too.
- CF: Roll Call got a TEXT_EQ "NDS" light-blue rule (clone of the B2B rule
  #14: C3:D21, Q3:Q1141, C23:D1141) so NDS cells paint like B2B did. Deleted
  one inert orphan rule on Stations (I8:I11, INDIRECT to the dead 'D2D
  Stations' tab → #REF, never fired). Verizon board C1 title cell set to
  "Verizon Sales Board". The 48/49/50 literals left in the stat rows' # cells
  (NDS r21-22, BOX r24-25) cleared.
- Still saying B2B, by design: P&L 2026 line labels, RAW/Commission product
  codes ("B2B-ATT-SBS", "B2B Roadtrip Bonus"), Report an Issue notes, the
  hidden `Lucy At&t Order Log` A1 title, old roll/DU rows. Slack channel names
  (#a-players-b2b) were not asked about and are untouched.

**Bound script v21 → v22 (API PUT to HEAD; webapp = Version 13, 10/3 10:06am)**
- Constants: `BOARD="NDS Sales Board"`, `VZ_BOARD="Verizon Sales Board"`,
  `NDS="NDS"`, `isNDS(c)` (NDS or B2B), `campForBoard` → "NDS",
  `_isStatLabel` accepts "AT&T NDS" and "AT&T (B2B)".
- Every `getSheetByName("Sales Board")` (23 sites) → `getSheetByName(BOARD)`;
  every `'Sales Board'!` formula string → `'NDS Sales Board'!` (re-anchor regex,
  stat-range reanchor, RollWeek `ns()` week/exclusion refs, helper guards W5
  / X5 / BOX Stations S5).
- Lists/maps: roll D list, campaign-box labels, teams box ("AT&T NDS" / NDS),
  headcount formulas (`$L="NDS"`, roll `$D="NDS"`), placeSection("NDS"),
  polishStations bands/colors, new-start campaign mapper defaults to NDS,
  promote/fixRollover AE date via isNDS.
- v22 (after the rename): Add-person dialog offers NDS/BOX/Verizon/JE/Base
  (was B2B/BOX/JE/Base); `_submitAddPersonCore` defaults to NDS and folds a
  typed "B2B"; **`_addBoardRowIfNew` now routes to `boardForCamp(camp)` — it
  always wrote the main board before, a latent 3-board bug**; legacy
  `startNewWeek` snapshot keys/label code know NDS. v22 touched no flip code,
  so no webapp redeploy was needed for it.
- Verizon.gs v4 = v3 (campaign moves between any two boards; unchanged).

**Lucy 2 (main `02f7a62a`, deployed 10/3 ~10:25am)**
- `automations/vantura_boards.py` is the one layout module: `BOARD_TABS =
  {NDS, BOX, Verizon}`, `MAIN_CAMPAIGN="NDS"`, `LEGACY_CAMPAIGNS={"B2B":"NDS"}`
  + `canon_campaign()`, `SUBTOTAL_LABELS["NDS"]="AT&T NDS"` (STAT_LABELS still
  parses "at&t (b2b)" so the 10/2 backup reads), `board_ws()` opens the new
  title and falls back to the old one (`LEGACY_TABS`) so a code/sheet rename
  order mix-up can't strand a run.
- Routed through it: sales_boards (render/zeros/run/week_roll),
  vantura_slack_sales (run/alert/roster_sync — `campaign_rows("B2B")` still
  finds NDS rows), vantura_orderlog_sales, vantura_board_audit, team_tree
  (titled "AT&T NDS"), vantura_payout_estimate, b2b_metrics/rep_boards,
  vantura_revenue_board (these three indexed `BOARD_TABS["B2B"]` and would
  have KeyError'd), promo_checkin (NDS group), daily_update_fill,
  vantura_contacts_sync (B2B/B2B ATT → NDS), att/box order-log PROTECTED_TABS.
  149 tests green; dry-runs on the rehearsal copy matched prod shapes.

**Rename checklist (if a tab or the campaign word ever changes again)**
1. Sheet: rename tab → fix INDIRECT strings (Stations CF ×2 sections, BOX
   Stations CF, Roll Call CF), helper guards W5/X5/S5, board title cells,
   dropdown lists, campaign values, stat labels.
2. Script: constants at the top of Code.gs + the literals (grep
   `Sales Board'!`, `getSheetByName("`), `_isStatLabel`, `isNDS`, the
   roll list in `ensureRollCallValidation`, KEEP whitelist; push via API;
   redeploy the webapp only if flip code changed.
3. Lucy: `vantura_boards.BOARD_TABS` / `LEGACY_TABS` / `LEGACY_CAMPAIGNS` /
   `SUBTOTAL_LABELS`; run the module tests; `lucy update` + `git_status`.
4. Verify: `check_boards.py <sheet id>` ALL GREEN, `scan_leftovers.py` shows
   only the by-design leftovers, next morning's 4am audit + 5am fills clean.

## 2026-10-07: BOX Stations new-start / 2nd-week colors (missing CF rules)

Carlos: "box stations new starts and week 2s aren't being colored the way they
are supposed to be." Cause: the ride-row colors are NOT the script painter's
doing in practice. `_recolorCarNewStartsOn` paints static green/yellow/red/pink
backgrounds on both Stations tabs, but every Stations tab also carries `=TRUE`
→ white conditional-format rules over the ride rows (and stations/mark-off
blocks), and CF beats a static background. On the main Stations the green
(new-start pool W5/X5) and yellow (board N = "2nd Wk") CF rules sit BEFORE the
white rules, so they win; BOX Stations (built 10/2 from the D2D layout) never
got those two rules, so its ride rows stayed white. Fix: two CF rules on
BOX Stations B6:E15 at index 12/13 (ahead of the white rules):
`=AND(B6<>"",COUNTIF($S$5:$S$40,B6)>0)` → #b7e1cd and
`=AND(B6<>"",COUNTIFS(INDIRECT("'BOX Sales Board'!$B$5:$B$50"),B6,INDIRECT("'BOX Sales Board'!$N$5:$N$50"),"2nd Wk")>0)` → #ffe599.
Rule ORDER is the mechanism: terminated/mark-off strike rules first, then
green/yellow, then the white defaults last. Anything that rebuilds a Stations
tab's CF list must keep that order (`_recolorRepListOn` only drops rules on the
rep-list columns G:I, so these survive it).

## 2026-10-05: the first Monday on the three boards — the roll refused the flip (and the recovery)

At 5:16am `week_roll` archived 35 reps, found 18 'Name|10.4' rows ALREADY in
WeekData (written by the 10/2 split, mid-week, so stale: Verizon blanks, BOX
missing Fri-Sun), skipped them as "already archived", reset every day cell to
the INDEX formula — which now rendered the stale rows — and the readback
refused the flip (exit 3). Nothing was lost (snapshot on Lucy 2:
`output/sales_boards/week_roll_10.4_to_10.11_2026-10-05.json`), but the board
sat on 10.4 all morning, so today's attendance marks (Off → X) landed on LAST
week's Monday for five BOX reps, and the 6:45 sweep typed 0/X into the blanks.

Recovery (scratchpad `recover_roll_prep.py`): restored the five BOX Monday
cells from the archive, rewrote the 18 stale WeekData rows from the board (+
Adrian Leon's row from the log's "was" line), dry-ran until "0 to update",
then ran `week_roll --apply` from the laptop (clean checkout of main, the
webapp json copied in) at 8:58am: 53 rows verified, flip + roll-call poke OK.
After the flip: Stations/BOX Stations list anchors had shifted ($B$6:$B$60 /
$B$5:$B$56 — the promotion inserts) → re-anchored (ALL column refs of a
formula together, or FILTER sizes disagree and the list goes blank); the flip
removed Jayden / Diego Chacon / Edgar Camunez from the Verizon board because
their only roll rows said Terminated → restored (rows inserted before the last
rep so the SUMIFS ranges grow), roll rows set Active.

**Root cause of the rehire loop (found 10/7):** the 4am audit's store signal
("latest RollCallData week says Terminated and has closed → flip the roll row")
re-terminated those three every morning after a human set them Active, because
the Monday flip had snapshotted their Terminated status into 'Name|10.4'. The
same thing undid the 9/29 revivals the morning after. Fixes shipped 10/7:

- Lucy `week_roll` (main 5889190e): existing archive rows are compared and
  UPDATED when they differ; the archive is verified against the board BEFORE
  any board cell is reset. `plan_archive` / `archive_mismatches` are unit-tested.
- Lucy `vantura_board_audit` (same commit): store signal 1b is held for a rep
  with a live board row and no 'T' on it ("rehire, store row ignored").
- Script RollWeek v22 (HEAD + webapp **Version 14**, 10/7 12:42pm):
  `stationsHelperGuard` now also pins the nine rep-list formulas' board refs to
  $5:$60 (daily + inside the flip); `_ensureBoardRepsOnRoll` gives any board
  rep with no live roll row an Active row (skips Terminated-with-Date-Gone, a
  'T' this week, stat labels; max 10/run; matches through `_mirrorFind` = exact
  → Name Aliases → unique first+last). Runs at the top of the flip (before the
  terminated sweep) and in rollDailyNormalize. `previewBoardRepsOnRoll` (editor)
  logs what it would add — "nothing to add" on 10/7.
- RollCallData: the three 10.4 rows' Status set to Active by hand (the store
  is what the audit reads).

**Also 10/7 (Carlos's eyes on the board):** Verizon board "% On Board" row was
raw decimals with no colour → percent format + the three threshold rules
(≥70% #b7e1cd, 40-70% #34a853, <40% #e06666) copied from the NDS board; Roll
Call got a TEXT_EQ "Verizon" campaign fill (#f4cccc — NDS is #cfe2f3, BOX
#d9ead3, JE #fce5cd, Base #d9d2e9); column A: leftover 51-64 numbers cleared
below the rep block on NDS + BOX, NDS renumbered 1..15 after a hand-deleted
row; the redundant "All Reps / ALL — …" rows under the NDS "% on the Board"
block removed (Carlos: keep only the AT&T NDS rows), note moved up, the %
colour rules trimmed to row 27.

**Trap (10/7):** I tried wrapping the nine list formulas' board refs in
INDIRECT so inserts can't shift them; a `\"` in my replacement text broke all
nine formulas for ~3 minutes (lists blank). Reverted to direct refs; the
script guard is the fix. If INDIRECT is ever retried: write the formula text
exactly, no escaping, and test on ONE cell first.

## 2026-10-07 (pm): "why does the T not go all the way across for Kyara"

The Roll Call has Mon–Sat columns only. A termination marked ON THE ROLL by
paste/fill (multi-cell edit → RollWeek `offSyncOnEdit` → `rollAttendanceSweep`)
reached the board through the sweep's 6-day map, so Sunday (col K) stayed a
formula/blank while Wed–Sat read T. (A single-cell T on the roll already calls
`terminateWeek`, which fills the board Mon..Sun.) RollWeek **v23**: `_sweepOn`
reads the board 7 wide and carries a roll T through Sunday on the board.
RollWeek **v24** (Carlos: "go on until Sunday when you put T — our 3 sales
boards should function basically the same"): `_carryTThroughSunday(board)`
runs in `rollAttendanceSweep` for every board — the first T in a rep's week
fills the empty cells after it through Sunday, whatever the entry path
(typed, pasted, roll-synced) and whatever the roll status. Web app Version 16.
Kyara's K12 set to T by hand; a scan of all three boards found no other row
with a gap after its first T. Roll Call Verizon chip is now the board's dark
red (#b00000, white bold) — the #f4cccc light red read like the Terminated
pink next to it; all 518 campaign cells normalised to bold Arial 10 centered.

## 2026-10-08: Verizon joins the morning post (and the Slack fill)

Carlos: "We need to create a Verizon metrics thread that gets posted every
morning just like the B2B metrics thread" and "update this board based off
what they post on Slack and post in the morning at the same time the other
threads are posted."

**Morning thread (Lucy `sales_boards`, branch verizon-metrics-thread cbe10fa4
→ main):** program "Verizon" renders off the Verizon Sales Board tab like
B2B/BOX ((a) weekly, (b) highrollers) and posts `:satellite_antenna: *Verizon
Sales Board <WE>*` into a NEW daily parent `*Verizon Metrics MM/DD/YYYY*` in
#alphalete-gp-sales + #a-players-b2b. sales_boards is the only creator of that
parent: read-only lookup (today's history, oldest matching parent) → opener
creates one only if none exists; state in
`output/sales_boards/verizon_thread_state.json` (separate from the B2B
thread_state so the metrics runner's 10-key retention is untouched). Zero
Streaks still read NDS + BOX only (`ZEROS_PROGRAMS`; add "Verizon" there if
Carlos wants Verizon reps in the streak images). Same 5:10 ladder, no plist
change, `--program Verizon` and `--dry-run` work. 31+5+4 new tests.

**Slack fill (Lucy `vantura_slack_sales`, branch verizon-slack-fill b2a1293f
→ main 10/8):** third `Campaign("Verizon")` in parse.py — a sale post is
Verizon iff its text contains the word "verizon" (tally lines excluded);
sales per post = the `NL #n` / `n NL` items, a Verizon post with no NL item
counts 1 and is flagged; image-only posts count nothing and are logged
("post with no text/count from <rep> … board number kept"). Raise-only like
the others, office tally `Verizon - N/goal` reconciled, unknown posters
reported never written (Alexis Alejo, a new start, shows as "NOT A Verizon
REP ON THE BOARD"). Same plist (4-9pm + 5am). Name map additions: Yariel
caban → Yariel Martin Caban, Gary Vanwhitaker → Gary Van Whitaker, Thais →
Thais Alvarez Aragon, gavin natividaf → Gavin Dimitri Natividad, Jayden Luna
→ Jayden Willingham, William Bautista → Will Bautista, Luis Adan Valenciano
→ Luis Valenciano; Edgar's old "Edgar" (Base) alias retired. Replay of
10/6-10/7 history matched the board and the office tally exactly (18, 16).
KNOWN GAP (pre-existing, not changed): the B2B rule still EXCLUDES posts
containing "d2d" (a Base-era marker) and every AT&T post now reads "D2D
AT&T", so the Slack fill counts 0 AT&T sales — the NDS board gets its
numbers from managers / the order-log ladder. Dropping that exclusion is a
one-regex decision for Carlos. Two BOX posters were unnamed on main (Alexa
Marie Munoz U0C3CG64482, Annett Michell Climaco U0BTFSN2BU7) → added 10/8.

**Verizon posts, as the reps write them (10/7 samples):** "VERIZON D2D /
D2D Verizon / VERIZON (D2D) / D2D (Verizon)" + "Wrap text sent / Auto Pay on"
+ shout-outs + the lines sold as `NL #1 … NL #n` (or `1 NL, 2 NL`); `CX1` =
customer marker (not a sale), `BYOD` = line attribute. The office tally line
is `Verizon - 16/15`. "D2D" alone is the AT&T program (NDS reps post "D2D
AT&T"), never Verizon. Edgar's image-only post = nothing to count.

## 2026-10-22: totals not adding up on all three boards + "On the Board" row

Carlos: "the NDS sales board total isn't adding up properly … for verizon
sales board it's also not adding up" + "on the % on the board can you add a
row that shows how many people got on the board."

**Cause:** every subtotal / TOTAL / % block / Headcount / Teams formula is a
fixed row range, and two things drift them: Monday promotion inserts at row 5
push the START down (BOX had `$11:$22`, Verizon `$8:$22`), and mid-week
campaign moves (Verizon.gs `vzFreeRow_` inserts ABOVE the totals label, at the
range boundary) never grow the END (NDS `$5:$16` with reps to row 18). The
healer `reanchorBoardStatRanges` only looked at the NDS board and only fixed
ranges whose END still equalled the last rep — so once both ends drifted it
did nothing. Seen 10/22: NDS 49 vs 52, BOX 6 vs 9, Verizon 58 vs 69.

**Fix (Code.gs v23 / Verizon.gs v5 / RollWeek v25, webapp Version 17):**
`reanchorBoardStatRanges` loops `boardSheets()`, and re-anchors any range in
the stat area (rows from the subtotal label down, cols A:AZ) whose START sits
inside the rep block to `firstRep..lastRep` — sheet-qualified ranges are left
alone unless they name that board (a `'Roll Call'!$E$5:$E$300` is not a rep
range). It now runs after every campaign move (end of `vzOnEdit`), daily in
`rollDailyNormalize`, and at the flip as before. Run it by hand from the
editor any time a total looks short.

**% on the Board block (all three boards, rebuilt via API):** rows under the
header are now All <campaign> Reps / Reps Worked / Rolled a Zero / **On the
Board** (new: reps with a sale > 0 that day = Worked − Rolled a Zero) / % On
Board / the footnote. The BOX board's redundant "All Reps / ALL — …" rows were
removed like NDS's on 10/7. The three % colour rules point at the new % row.
Formulas are unqualified `$L$5:$L$<last>` style so the healer maintains them.

## 2026-10-23: "Headcount by Campaign" box removed from all three boards

Carlos: "why is the total head count different on the % on the board and the
headcount by campaign box … we don't have different campaigns so let's just
remove [it]." The two numbers measure different things: the % block's "All
<campaign> Reps" is PER DAY — reps with any mark in that day's cell (a sale,
0, X or T), floaters (F) and blanks excluded — while the box's Total Head
Count was the ROSTER by leadership level (Leaders + Entry Level + In
Training, Term? flag excluded on NDS/BOX, not on Verizon). Box cleared
(values + formats) at NDS K22:P23, BOX K26:P27, Verizon K29:P30. The Teams —
Current Week box below it stays; `refreshTeamsBox` finds it by its own
"total head count" header and already skipped the headcount box, so nothing
in the script breaks. The menu one-offs `addHeadcountNewStarts` /
`excludeTerminatedHeadcount` now throw "Headcount header not found" — they
are legacy and unused.

## 2026-10-23: NDS board filled from Carlos's NDS SaraPlus (Lucy `vantura_nds_sara`)

Carlos: "use sara plus but look at the way that lucy uses sara plus for the
order log to make sure you include the correct sales. upgrades, tablets, and
wearables shouldn't get added" … "we just started selling under my NDS
SaraPlus this Monday [10/19]" … "that works. go ahead and fill now."

Why: the Tableau ATTTRACKER-B2B order log (`att_order_log` → "Lucy At&t
Data") stopped carrying the reps' sales when they moved to the NDS SaraPlus
account, so the 9:30 order-log fill had nothing to add and the Slack fill
counts 0 AT&T (the "D2D" exclusion); managers were typing the NDS board.

How it works (branch vantura-nds-sara → main c1d58668, Lucy 2, launchd
`com.alphalete.vantura-nds-sara` 16:00–21:00 hourly + 05:00, plus `rerun
vantura_nds_sara [--probe|--dry] [--date YYYY-MM-DD]`):
- Source = the office agent's relay. Carlos's office Mac mini runs
  `icd_alerts` against his NDS SaraPlus and relays every rep's day totals to
  the 'ICD Relay' tab of the Lucy Access App workbook (one row per office per
  day, updated in place). The run takes the latest row for the office whose
  enrolment campaign is `nds`; no row = HOLD (exit 75, "the office mini may
  be off"); wrong week / no day column = hold.
- Units per rep = Int + NL + Air, where (relay.py `_nds_lines`) NL = New Lines
  + Port Lines − Tablets − Wearables, Int = internet sales − upgrades − AIA,
  Air = Internet Air. Int Up (upgrades + upgrade lines), tablets, wearables and
  DTV are shown in the log but never added. `UNIT_KEYS` in run.py is the knob.
- Writes are AUTHORITATIVE (sara.plan_overwrite): a matched rep's day cell is
  SET to the SaraPlus number, up or down; a board rep absent from SaraPlus is
  left as-is and flagged; a SaraPlus rep with no board row is flagged, never
  written (Nico Murrugarra sells but has no NDS row). Hand-typed markers
  (T/X/F/non-numeric) are kept unless SaraPlus shows sales; 0 units writes a
  blank. Before 10am the run closes YESTERDAY, after it TODAY.
- Names: SaraPlus is UPPERCASE; `match_rep` (exact → first+last token) after
  ALIASES (NICHOLAS SMEDRA → Nick Smedra, NICOLAS MURRUGARRA → Nico Murrugarra)
  and the order-log first-name map.
- Lucy 2 Hub card auto-created; failures show as the card pill only (no Slack
  alert), like the order-log fill. The 5am close-out needs the mini's 2am
  catch-up relay; if the mini slept, `rerun vantura_nds_sara --date <day>`.
- The laptop's Google token cannot open the relay workbook (403) — probe and
  fill only run on Lucy 2. The queue's `logtail` returns ~4 lines per call,
  so verify a fill by diffing the NDS board (scratchpad
  nds_before_sara_fill.json holds the 10/23 pre-fill snapshot).
- The Slack fill still writes NDS raise-only (0 today because of the "D2D"
  rule) and the order-log fill still runs at 9:30; SaraPlus overrides both at
  its next pass.

## Issues we actually hit (the lookout list)

1. **Board names must match the order log** (exact or first+last token).
   Mismatch = sales in no total AND the authoritative BOX pass wipes
   hand-fixes every run (Gary "Whitetaker II" / "Jayden Luna", 9/3). The
   order log is the naming authority; bridge history in Name Aliases.
   Unmatched log reps now alert #claudecorrections.
2. **Inserting a Roll Call column mass-terminated people** (9/4): the
   script read campaign as the rep name, so one typed T ran terminateWeek
   for a whole campaign. Fixed by moving the new column to P. Never insert
   into A–O.
3. **"MONDAY LINEUP" — RETIRED 2026-09-08.** It used to be re-stamped daily
   by `renameJELineup()` at fixed rows (53,66,79,92,105,118,131), the header
   of a dead Mon–Sun "JE Lineup" section (rows 53–143) that carried NO data —
   just drifted, duplicated labels. Removed the `renameJELineup()` CALL from
   `recolorCarNewStarts` (line ~2969) so it never writes again, and cleared
   the 13 stale labels. Rows 53+ are now free for the BOX section to grow into
   (the old "keep content ≤ r52" constraint is lifted). The `renameJELineup`
   function still exists but is uncalled; the lineup `recolor(55,64)…(133,142)`
   calls still run harmlessly on empty rows (remove them if BOX expands there).
   **Stations header highlight:** `recolor()` paints only cols B:F and CLEARS
   any B:F cell without a rep name — which wiped manual coloring on the BOX
   header rows (30, 43) while col A survived. Fixed by having
   `recolorCarNewStarts` repaint `A30:E30` and `A43:E43` amber (#FEF3C7) right
   after the recolor calls, so it's maintained, not fought. (ATT car header r5
   sits above the recolor range so it was always fine; ATT station header r17
   is still half-cleared — same one-line fix if wanted.)
4. **Conditional formatting ALWAYS overrides script painting.** The CF
   stack's bottom "=TRUE → white" rules were masking every color
   `recolorCarNewStarts` painted (terminated red, new-start green, week-2
   yellow) — a T'd rep looked normal on Stations (Ivan, 9/9). Fixed at the CF
   level: hidden helper `T5` lists terminated names (live-week Roll Call
   T/Terminated + board P="Terminated"); top-priority red+strike rules cover
   every name surface (rides, stations, rep lists, new-starts, both
   campaigns); car rides also carry CF green (name in the K new-starts list)
   and yellow (board Field Status "2nd Wk") just above the whites. The
   script's painting still runs underneath, harmlessly. **Also 9/9: name
   type-ahead.** Native autocomplete dies on any blank cell above (why BOX
   never suggested and C13 wouldn't fill) — every ride/station name cell now
   has a ONE_OF_RANGE dropdown (helpers `U5` ATT / `V5` BOX = rep list + new
   starts; warning-only, free text allowed). Hidden helper cols: R–V.
5. **Conditional-formatting traps** (each one burned us):
   - A multi-range rule's relative anchor drifts → blanks light up. Use
     one rule per range, anchored at that range's top-left.
   - `addConditionalFormatRule` WITHOUT an index inserts at the TOP.
     Catch-all white rules must sit at the BOTTOM (pass explicit index).
   - Rules carry `backgroundColorStyle` which OVERRIDES `backgroundColor`
     — set both or the color silently doesn't change.
   - COUNTIF ranges inside CF formulas go stale after row inserts/deletes
     — re-verify every rule after any layout change.
   - Cross-sheet CF works only via `INDIRECT("...")` — and those strings
     do NOT auto-shift when rows/columns move; update them by hand.
5. **Formula traps**: USER_ENTERED coerces "8.30"→8.3 (week labels are
   TEXT, write RAW); COUNTA counts a formula's "" (use `COUNTIF(rng,"?*")`
   for header counts); XMATCH doesn't arrayify inside SORT/FILTER (use
   nested IF rank keys); TODAY() follows the spreadsheet timezone
   (America/Chicago — verified).
6. **Validation traps**: an inserted column inherits its neighbor's
   dropdown validation (red-corner storm on the Leadership column);
   hardcoded ONE_OF_LIST name dropdowns go stale after renames (Trainer
   col now uses ONE_OF_RANGE against the live board roster); dropdown
   type-ahead needs a single-column, blank-free source range.
7. **Commission "active" panel** is pasted values built by Code.gs — the
   payroll webapp's `action=refresh` does NOT rebuild it. Its roster wants
   a RECENT Active roll-call row; stale Roll Call = "not active" ghosts
   (Jayden). Keep Roll Call current-week rows for active reps.
8. **Daily Update statuses were maintained by nobody** — the 8:45pm fill
   only appends. The Sunday 7pm reconcile (`vantura_du_status`) now flips
   Active/Orientation-Scheduled rows to "Not Active" when the person's
   NEWEST roll-call row is Terminated/T-marked. Most-recent-row rule on
   purpose (old Terminated rows must not beat current Active ones).
9. **BOX board counts can legally drop**: order log is truth; a Slack
   count lowers when the log lacks the contract (late entry, failed TPV).
   Check `Lucy Box Data` before calling it a bug.
10. **The board filter goes stale** when humans append rep rows —
    `ensure_board_shape()` (runs on every live fill pass) re-extends it,
    which CLEARS active filter criteria; re-pick the campaign after.
11. **Ops hygiene**: the laptop's repo clone drifts (fetch before
    reasoning); build deploys in a git worktree; verify Lucy 2 deploys by
    logtail, never success messages; other sessions push constantly.

## Quick diagnostics

- Board vs tracker mismatch → `lucy logtail vantura-orderlog-sales`, look
  for "IN THE LOG BUT ON NO <camp> ROW".
- Weird T's appearing → check who's missing from the Sales Board roster
  and what the script's constants expect vs the actual columns.
- Colors not updating on Stations → dump the CF stack; whites must be at
  the bottom, ranges must match current geometry.
- DU status wrong → `lucy rerun vantura_du_status` (dry preview).
- Anything script-side → full local copy of Code.gs lives at
  `~/Downloads/vantura_codegs.txt` (from 9/4; re-export before editing).


## D2D (Verizon) tabs — added 2026-09-06 (HISTORICAL: this tab is "Verizon Sales Board" since 2026-10-03 and fully automated since 2026-10-02 — the "still not wired" list at the end is obsolete)

Two new single-campaign tabs, built as sheet-side clones of the main pair:

- **"D2D Sales Board"** — 30 rep rows (r5-34), Verizon-red theme,
  same columns/day-cell vocabulary as the main board. Week picker B2 is a
  FORMULA following 'Sales Board'!B2, so the Monday roll flips it
  automatically. Verizon totals r35 + TOTAL r36; single-campaign "% on the
  Board" block r38-42; Headcount r38-39 and Teams r41-45 boxes on the right
  (team names are typed into K42-45 and the formulas fill in). Campaign
  dropdown = Verizon only; Leadership dropdown matches the main board.
- **"D2D Stations"** — one section: CAR RIDES (A:E, 8 rows),
  STATIONS below (Station 1-4, r17-26), leveled REP LIST G:I with live
  counts, NEW STARTS K (from the shared Roll Call, campaign "Verizon"),
  OFF-TODAY auto list L + MARK OFF dropdowns M. Same legend colors, dup-red,
  off-red, cross-off strikes (on the D2D board and the shared Roll Call).

**Verizon onboarding path (9/10, E2E-verified):** Roll Call campaign
dropdown and Daily Update campaign dropdown both include **Verizon**. Three
ways a Verizon rep reaches the D2D tabs — all tested: (1) a human sets Roll
Call campaign C to Verizon → the `vzOnEdit` trigger adds/moves them to the
D2D Sales Board instantly (trainer, 1st Wk, In Training) and the D2D
Stations rep list/type-ahead pick them up; (2) the **Add New Starts to Roll
Call** menu now maps DU campaign "Verizon"→ roll "Verizon" (it used to
default everything unknown to B2B!) and calls `vzFromRoll_` itself for those
rows, because script-written rows never fire triggers; (3) the manual
`lucy rerun vantura_roster_sync` reconcile. New-starts helpers (`W5`/`X5`
main, `S5` D2D) exclude anyone already on their board, so a rep never shows
twice in the In Training / New Starts column.

**D2D Stations parity (9/9):** restructured to match the main Stations tab —
col I = "In Training / New Starts" (board in-training + one blank row + roll
Verizon new starts via hidden helper `S5`); single **MARK OFF at K**
(dropdowns K5:K17, source `R5` rep-list helper; old K new-starts list and L
auto-off REMOVED, M dead); name type-ahead dropdowns on all ride/station
cells (same locked recipe); terminated red+strike CF on every name surface
via INDIRECT to the main Stations' `T5` helper; the D2D board's cross-off CF
repointed to `'D2D Stations'!$K$5:$K$17`; the 4am `resetOffList` also clears
D2D `K5:K17`. Hidden helpers on D2D: R (mark-off/name source), S (new
starts).

Roll Call is SHARED: its campaign dropdown now includes "Verizon"; Verizon
hires get normal Roll Call rows and the D2D new-starts list picks them up.

**Campaign moves are AUTOMATED — NATIVE in the bound script (9/6-9/7):**
A file `Verizon.gs` in the bound project + an installable `onEdit` trigger
(`vzOnEdit`, visible in the script's Triggers list) move a rep the moment
their campaign is set to Verizon — Code.gs itself is untouched. No Lucy.

- Main-board rep set to **Verizon** → row moves to the D2D board (carries
  last-wk, day cells, trainer, field status, team, leadership; the source
  row is blanked, C `=SUM` restored, Roll Call campaign synced).
- D2D rep flipped **off** Verizon → moves back to the first empty main row.
- Roll Call campaign set to Verizon → if the rep is on the main board they
  move to D2D; if on no board they're added to D2D (trainer, "1st Wk",
  In Training).
- Terminated rows skipped; no duplicates; a FULL target board shows a toast
  ("… is full - move held") and leaves everything in place.
- **Handles multi-cell PASTE too.** `vzOnEdit` is range-based on purpose: an
  installable onEdit DOES fire on a paste/fill/drag, it just gives no
  per-cell value, so the handler reads the campaign column straight from the
  edited range and processes every affected row. Pasting a column of
  "Verizon" moves every rep.
- Reinstall after any script change: pick `vzInstall` in the editor's
  function menu and Run. Disable: delete the `vzOnEdit` trigger.
- Day cells are carried as VALUES (not the main board's INDEX formulas), so a
  moved rep's empty day cells become literal blanks until the Monday roll
  resets them — harmless (sales are values and survive; SUM is unaffected).

**Lucy roster_sync = RETIRED (9/7).** `roster_sync.py` and the standalone
`com.alphalete.vantura-roster-sync` agent were the pre-native mechanism; the
agent is booted out (`disable_vantura_roster_sync_agent`) and the in-fill-pass
hooks removed, because the script now covers every case including paste.
`lucy rerun vantura_roster_sync` is kept only as a MANUAL full-scan reconcile
if the boards ever drift.

**Still not wired (by design, for now):** the bound Apps Script ignores these
tabs (no T-termination sync, no trainer/name propagation — those only run on
"Sales Board"/"Roll Call"/"Stations"); no Slack/order-log fill exists for
Verizon yet (day cells are typed by managers); the Monday week roll does NOT
archive/clear the D2D board (clear day cells manually on Monday until an
automation is built); P&L/commissions separate, later. The script's
cleanupTabs whitelist does NOT protect the two new tabs — one more reason
never to run that menu item.

## 10/24 — NDS fill from SaraPlus: where the passcode actually goes

**State:** the `vantura_nds_sara` fill is deployed on Lucy 2 (launchd 4–9pm hourly + 5am) but
has NOT written anything yet. Every login as the NDS dealer (alphaletegp@gmail.com) hits
SaraPlus's "new location or browser" passcode wall, and the code never reaches the inbox the
login watches.

**What was established 10/24 (read off the live picker from the laptop, no code requested):**
- The picker offers a mobile number (XXX-XXX-6610) or an email dropdown whose two entries both
  show as `alph...@gmail.com` — the login's own alphaletegp@gmail.com. So the code goes to
  alphaletegp's OWN inbox.
- The B2B dealer login (carhi1816) is different: its picker says `Carl...@gmail.com`, the code lands
  in Carlos's personal Gmail and a filter there forwards it to alphaletereporting@gmail.com. That is
  the forward `rc_contact_sync.verify_code` relies on, and it is the ONLY SaraPlus forward that exists.
- The reporting inbox has had 0 "Gmail Forwarding Confirmation" mails and 0 SaraPlus codes addressed
  to alphaletegp in 14 days → no alphaletegp → alphaletereporting forward is set up or confirmed.
  nds_metrics' NDS order-history pull has been dying on the same wall since 10/22 ("nds-dealer pull
  blocked (CodeNotFound)" → b2batt fallback).

**Code now in main (3442bc99):**
- `rc_contact_sync.sara.login(..., code_inbox=(address, app-password file))` threads an alternate
  inbox into `verify_code.wait_for_code(inbox=)`; default unchanged.
- `vantura_nds_sara.config.code_inbox()` = alphaletegp's inbox when
  `~/.config/recruiting-report/gmail-app-password-alphaletegp` exists on the machine, else the
  reporting inbox. Both the board fill and nds_metrics' pull use it. `--preflight` prints the choice.
- `rerun vantura_nds_sara --passcode-mail` lists sent / to / arrived-here (forward delay) of recent
  SaraPlus passcode mails in the inbox being read; `--mail-query "<gmail search>"` does the same for
  any search (headers only, never bodies or codes).
- mini_control `_CRED_FILES["gmail-app-password-alphaletegp"]` so the file can travel:
  `lucy push_cred_file gmail-app-password-alphaletegp "Lucy 2"`.

**What unblocks it (Carlos, on the alphaletegp Google account — either one):**
1. App password (robust): Google Account → Security → 2-Step Verification → App passwords → create;
   save it on the laptop as `~/.config/recruiting-report/gmail-app-password-alphaletegp` (chmod 600);
   push with the command above. Then `rerun vantura_nds_sara --probe --source sara --date <d>`.
2. Forward (what was asked for on 10/23): Gmail → Settings → Forwarding → add
   alphaletereporting@gmail.com → Google mails a confirmation to alphaletereporting (read it with
   `rerun vantura_nds_sara --mail-query "from:forwarding-noreply@google.com newer_than:2d"`) →
   confirm → filter `from:security.info@saraplus.com` → forward. Check alphaletegp's Spam for
   SaraPlus mail (Gmail never forwards spam-foldered mail).

**Traps:** the first login attempt uses nds_metrics' profile (`automations/uploaded/
.saraplus_nds_profile`) and waits up to 420s, then the module's own profile waits again — a
`lucy rerun` (10-min cap) can time out before the second attempt; once a code arrives in ~5s this
is moot. Every attempt mails fresh codes to alphaletegp, so expect a pile of "SARA Plus Passcode"
mails there. Lucy 2's logtail shows ~1–8 lines per call and cuts lines at ~200 chars — grep for a
distinctive word, and put the number you need early in the log line.

## 10/26 — a campaign move (BOX → NDS) left Nathaly Benitez on no board

Roll Call col D changes move a rep's board row through Verizon.gs (`vzOnEdit` → `vzFromRoll_` →
`vzMoveRow_`: copy to the target board, then delete the source row). Carlos moved several reps
BOX → NDS this morning; all landed except Nathaly, who ended up on no board at all, so the Stations
REP LIST (built from 'NDS Sales Board' B/L/P) lost her. The script's execution log is not readable
with the laptop token (needs the script.processes scope), so the failing step is unknown.

Fixed by hand (Sheets API): a row inserted INSIDE the NDS rep block (before the last rep, so every
`$5:$N` stat range grew on its own — no reanchor needed) with #, name, `=SUM(E:K)`, Last Wk (her
WeekData 10.25 total), the seven INDEX-into-WeekData day formulas, L NDS, M trainer (roll col G),
N "19th Wk" (`(WE − roll week)/7 + 1`), P Level 1, AQ term flag; renumbered. Annett Michell Climaco
had a leftover BOX row carrying L = NDS (she was already on NDS, so the move only re-labelled the
source row) — deleted, BOX renumbered 1–11. Verified: Stations Leaders list now shows her (13).

## 10/26 — board audit + cleanup (Carlos: "check everything works, clean up")

Found and fixed by hand (Sheets API, USER_ENTERED):
- **BOX TOTAL row** C/D were `=SUM(#REF!)` (the BOX board has no campaign label row; something deleted the
  row they summed). Now `=SUM($C$5:$C$15)` / `=SUM($D$5:$D$15)`.
- **Subtotal "Last Wk"** on NDS (`D24`) and Verizon (`D30`) were typed numbers (73 / 119) among formulas.
  Now `=SUMIFS(D$5:D$<last>,$L$5:$L$<last>,"<camp>")` like the other columns.
- **% block literals** (earlier today): NDS "All Reps" Thu/Fri and "Reps Worked" Fri were typed numbers →
  formulas restored. Watch for this: any typed number in rows 27-31 (NDS) / 19-23 (BOX) / 34-38 (Verizon)
  freezes that day.
- **AQ "Term?" flag** was missing on NDS r23 (a row moved in by the campaign move), BOX r5-r9 (this
  morning's promotions) and ALL 25 Verizon rows (the Verizon board never had the column at all; header
  added). `vzMoveRow_` and `_promoteWeekSurvivors` do not write AQ — the daily `fillMissing…` should, but
  did not here.
- **Verizon numbering** had a gap at 21 (a row moved out) → renumbered 1-25.
- **Verizon Teams box** (K36:Q40) had blank team labels, so all rows summed the same reps → K37 Bautista,
  K38 Akatsuki, K39 Unaccounted For (`$O=""` pattern), K40:Q40 cleared. NDS K33 header renamed to
  "Teams — Current Week" to match; the leftover **BOX sub-box on the NDS board** (K38:Q39) cleared.
- **Stations!T5** (the hidden terminated-names helper that feeds the car-ride dropdown) had drifted to
  `'Roll Call'!$75:$531` and board starts $8/$10/$15 → re-anchored to `'Roll Call'!$3:$1046` and `$5:$60`
  on every board. It is NOT one of the nine lists `stationsHelperGuard` pins, so it will drift again on
  the next row insert/delete above it — add it to the guard in RollWeek.gs (TODO).
- **Stale T marks on the Verizon board**: Alexis Alejo (all week), Giovanni Monreal (all week, roll says
  Here Monday), Ndifreke Ikotidem (Tue-Sun), Yariel Martin Caban (Tue-Sun), Cesar Ramos (Sunday) showed
  T with no T on their Roll Call rows (all Active). Day formulas restored for those cells. The Roll Call is
  the record of terminations; mark T there and the board follows.
- Nathaly Benitez re-added to NDS (see 10/26 above); Annett's leftover BOX row removed.

Left for Carlos (judgment calls, not changed):
- BOX: Michelle Flores, Kandice Michelle Flores, Rebeca Juarez have **T on all six Roll Call days this
  week but status Active**. The Monday flip deletes board rows with a T day-mark, so either set the status
  to Terminated (with Date Gone) or clear the T's.
- Hamid Asim: Roll Call Active / Verizon / Level 1 (week 10.4) but no board row since WE 10.11.
- Trainer disagreements: Nick Smedra (board Sebastian Avellaneda, roll himself); Yariel Martin Caban
  (board Gary Van Whitaker, roll Jayden Willingham). Blank trainers on both board and roll: Brianna
  Belen Contreras, Jorge Hernandez, Carmen Julia Laguna, Anna Laura Gomez, Cesar Ramos, Jair Ortero.
- New starts of WE 11.1 (Valerie Marquez, Elisa Diaz-Garcia, Marco Antonio Hernandez, Ja'nevaeh Renee
  Winkley, Maria Guadalupe Gonzalez Robledo) are on the roll only — by design until Monday's promotion.
- **Stations Verizon lists (G31/H31) showed #REF!** since before today: stale typed names sat under the
  list heads (H32:H39, G40:G41), so the FILTER arrays could not spill. Writing "" over them through the
  values API was NOT enough (the cells still counted as occupied); `values:clear` on G32:H49 fixed it.
  Rule: never type or paste into the REP LIST columns G:I on either Stations tab; to unblock a #REF!
  list, clear (not blank) the cells beneath it.

## 10/27 — Teams box: campaign row totals, one style, every board (Code.gs v24)

Carlos: "row 34 should add everything up" + "the coloring changed". `refreshTeamsBox()` (Code.gs)
regenerates the K:Q "Teams — Current Week" box on every edit of a Team (O) or Campaign (L) cell, so a
hand tidy never lasted. Rewritten (pushed via the Apps Script API, Code.gs v24):
- Runs on EVERY board (`refreshTeamsBox(sheet)` for the edited board from onEdit; no argument = all
  three from the daily routines). The old one only ever touched the NDS board, which is why the Verizon
  box was static and had no Term? column.
- The campaign band row (AT&T NDS / BOX / Verizon) now carries the campaign TOTALS (Apps, Head Count,
  Leaders, Entry Level, In Training, Sales Avg) — same SUMPRODUCT formulas without the team factor.
- Team rows: white, normal weight, sorted; Unaccounted For italic. No alternating bold. Band colors:
  NDS #cfe2f3, BOX #d9ead3, Verizon #f4cccc. Black borders, centered.
- Only the board's own campaign is listed (the stray BOX section on the NDS board is gone for good).
- Still (re)writes the hidden Term? column (AQ) for every rep row — reps flagged T are excluded from
  every count (that is why BOX "Liv" shows 0 while Rebeca Juarez is marked T).
The same shape was written to the sheet directly on 10/27 so it shows now; the script keeps it.

## 10/27 — Stations "Territory Status" colors ignore spaces/case now

"good " (trailing space, phone autocomplete) did not turn green: the five status rules on A6:A15 /
A31:A41 were exact-text matches. They are now `=LOWER(TRIM(A6))="good"` etc. (Need New T /
Extension Needed = yellow #ffea99; New T Given / T Extended / Good = green #b7e0b7). Any typed status
still has to be one of those five words to color.

## 10/27 — "Last Week" row replaces the duplicate TOTAL row; stray formatting cleared

Carlos: "row 25 isn't needed. swap it for 'last week' … how many sales we did the week prior on that day".
- NDS r25 / Verizon r31 / BOX r17 are now **Last Week** (grey band, italic): C = last week's total,
  D = the week it refers to ("WE 10.25"), E:K = that weekday's sales a week earlier, summed over the
  board's CURRENT reps (same basis as the Last Wk column): 
  `=SUM(ARRAYFORMULA(IFERROR(VALUE(VLOOKUP($B$5:$B$<last>&"|"&MID($D<row>,4,10),WeekData!$A$2:$H$5000,<2..8>,FALSE)),0)))`.
  The `$B$5:$B$<last>` range is re-anchored by the script like every other stat range. D's label comes
  from B2 (`DATE(...)-7`), so it follows the Monday flip by itself.
- BOX r16 was its only totals row, labelled TOTAL; relabelled **BOX** so the three boards read the same
  (subtotal row, then Last Week).
- Readers updated so "Last Week" ends the rep/totals block like TOTAL did: vantura_boards.STAT_LABELS,
  sales_boards/render.py (`TOTALS_BOTTOMS`), sales_boards/run.py by_name scan, week_roll campaigns
  scan (so the roll never writes a 'Last Wk' literal onto that row); Apps Script `_isStatLabel`
  accepts LASTWEEK. Deployed (main 88b61055, Lucy 2 on it; script pushed).
- Stray formatting outside the block cleared: Verizon Q1:Q3 color + Q5:Q29 borders, NDS Q5:Q19 borders +
  R5:R15 blue + R17:U17 borders, BOX Q5:Q15 borders + R5:R10 blue. Hidden data columns AE/AO (dates
  the script uses) were left alone. BOX's light-blue banner across K1:Q3 left as is.
- "L6 has a dropdown": every Campaign cell (L) on every board carries the same NDS/BOX/Verizon dropdown
  (the campaign move relies on it); nothing unique about L6. Stations has no L-column dropdown.
- 10/27 later: C of the Last Week row left blank (D24 already shows last week's total). Dropdowns are
  now uniform: Campaign (L) / Team (O) / Leadership (P) on every rep row of every board and on NO row
  below the block (the stray arrows in L26, L42… came from validations inherited by inserted rows).
  One solid border grid over A5:P<last>; column Q boxes above the Teams box cleared. Internal columns
  AE (script's AE date), AO and AQ (Term?) hidden on all three boards (Verizon had them visible); AQ
  shows 0/1 instead of 1899 dates. Lowercase day marks (x) uppercased — a lowercase x renders in a
  visibly different size and is what "the font is different" usually is. Verizon E27 font family
  normalised to the column (no explicit family, size 12, #141414).
- "Last Week" Saturday reads 0 for NDS because the archived board (WeekData, taken Monday 4am by the
  roll) had no Saturday sales typed in — the NDS SaraPlus fill is still blocked on the login code and
  the Slack fill writes 0 for NDS. Backfilling WeekData rows for WE 10.25 fixes the row retroactively.

## 10/27 — NDS Slack fill was writing 0 for everyone: the "D2D" exclusion

Last week's NDS Saturday read 0 on the Last Week row. Cause: the Slack fill's AT&T/NDS rule
(vantura_slack_sales/parse.py, campaign "B2B") excluded any post containing "d2d" — a rule from when
Verizon posts without a Verizon header leaked into AT&T. Every NDS rep now heads their post
"D2D AT&T" / "AT&T D2D", so the fill counted 0 for the whole board every day and only hand-typed numbers
survived (Mon–Fri last week); nobody typed Saturday. Fixed in main 6610f481: "d2d" is no longer
excluded (Verizon posts still go to Verizon via their override; a Verizon rep's bare "D2D" post cannot
land on the NDS board because the fill only writes names that have an NDS board row). test_parse 97/97.
Saturday 10/24 is being backfilled into WeekData ("Rep|10.25", col G) from the posts. The SaraPlus fill
(blocked on the login code) remains the better source once it works.

## 10/29 — "NDS Order Log" tab (daily customer status log) + BOX log cancelled

Carlos: "get an update on all of these customers every single day in a tab called NDS Order Log".
- **What it is**: one flat, filterable table on the Vantura Master Sales Board, one row per crew
  wireless LINE from the NDS dealer's Wireless Resolution feed (alphaletegp) — the same lines the
  NDS Metrics thread's order-log workbook carries ("All Reps"). Columns: Week Ending (Mon–Sun Sunday),
  Rep, Customer, Order Date, DSI #, Wireless Order #, BAN, Line, Type, Device, Plan, Line Status,
  Ship Date, Delivered, Port Status, Last Updated, Notes. Rows coloured by Line Status (Active green,
  disconnected/cancelled red, in flight yellow). Header filter, frozen header, IDs stored as text.
- **When**: every morning inside the NDS Metrics run (`nds_metrics --post`, Lucy 2, after 6:30, right
  after the `nds_wireless_pull` card at 6:10 caches the feed). A tab problem never sinks the thread.
  By hand: `lucy rerun nds_metrics --tab` (tab only, no pull, no post).
- **Merge rules** (`automations/nds_metrics/order_log_tab.py`): the feed covers 31 days, the tab keeps
  60 by Order Date. A line is kept when the feed forgets it, replaced when it is still there, aged out
  past 60 days. Last Updated restamps only when Line Status / dates / type / device / plan change.
  **Notes is Carlos's column** and is carried by line key through every rewrite. Key =
  (Wireless Order #, Line), else (DSI #, Line), else (Customer, Order Date, Line).
- **No feed today** (the 6:10 pull failed — e.g. the SaraPlus passcode wall): the tab is left as it was
  and the run logs "no wireless feed cached". Nothing is ever blanked.
- **BOX Sales Log / Lucy Box Order Log**: cancelled completely 10/29 (Carlos). The Lucy 2 agent was
  already unloaded 10/28; today the `box-readme-daily-update` task and the three Box Notes email
  sweeps (`box-notes-email-sweep`, `box-notes-sweep-730`, `box-notes-sweep-800`) were deleted. The
  two tabs stay on the workbook as frozen records; the code stays in the repo.
- 10/29 later: tab centered, columns auto-fit (Rep/Customer 190px, Notes 220px), new **"Being worked on"**
  column (Yes/No dropdown) after Notes — carried by line key like Notes. Rows the parser calls lines
  but that have no line number (a "Resolve Order" header misread as a line) are skipped and purged.
  Port Status values like "6P" are SaraPlus's own port-status codes; on Port lines the Device column
  currently shows the ported phone number (feed parser columns swapped — parser work in progress).

## 2026-11-02 — attendance marks that "came back", Ruby, the Stations NOTES column, Friday's new starts

**"I keep removing people's attendance status on the NDS board and it keeps bringing back what I removed."**
Root cause, proven from the data: the roll's SATURDAY column (M) held literal Off/Here marks typed this
morning (the 11.1 archive had Saturday blank), the board's Saturday cells (J) mirrored them as X/0, and
`rollAttendanceSweep` — which runs on EVERY single-cell roll attendance edit through the installable
`offSyncOnEdit` — copies every roll literal back into any EMPTY board cell. Clearing the board cell is
supposed to clear the roll mark too, but that mirror lives in the SIMPLE `onEdit` (best-effort, skipped
under load, and it only ever sees the top-left cell of a multi-cell delete), so for ten reps the roll
literal survived and the next leader mark put the X back. Fixed two ways:
- Data: Saturday on the NDS board (15 reps) and on the roll (10 live rows + Ruby) put back to the
  WeekData / RollCallData formulas. Monday's 0s for Nick/Andrew/Jacob/Aaron were left — those are the
  leaders' live "Here" marks (the 0 presence marker Carlos asked for 7/21). Eric (x all week), Sebastian
  and Carlos (F) untouched, per Carlos.
- Code (RollWeek.gs, HEAD only — the Monday webapp pin is unaffected): `offSyncOnEdit` now mirrors EVERY
  emptied board day cell of the edited range to the roll (`_clearRollMark`: live rows only, literals
  only, a history formula is left alone). A board clear now sticks, single or multi-cell.
- Who typed the Saturday marks is not visible through the API; right-click a cell > Show edit history if
  it matters.

**Ruby Flores marked T but still "active" on Stations.** Her board row had T across the week but
Leadership (P26) still said Level 1 and her roll row's week is 8.9, so neither half of the TERMINATED
helper caught her (board P ≠ Terminated; roll week ≠ live week). The T-typed path normally sets P via
`terminateWeek → markLeadTerminated`; it did not run for her (the 5am `refreshTerminatedLead` would have
caught it tomorrow). Set P26 = Terminated (note `prevlead:Level 1`, what the script writes): she left the
Leaders list (13 now) and is in the terminated helper (red+strike wherever she is placed). Monday's flip
removes the row.

**Stations NOTES column at B (Carlos: "a column grouped with column A, mainly for the car rides, call it
Notes").** Inserted at B on the main Stations tab (API insert, everything from the old B shifts one
column right: rides C:F, rep list H:J, MARK OFF L, helpers S:Z, week label R2). B is free text (wrap,
left-aligned, no validation), header "Notes" in rows 5 and 30, 170px. Column B ALONE is a collapsible
column group and the +/- toggle sits above column A (sheet property `columnGroupControlAfter` = false,
i.e. "before the group"; Carlos's follow-up 11/2: "the grouping should only bring in and out column B, it
should be above column A" — the first cut grouped A:B with the toggle after the group, above C). The
toggle position is a per-sheet setting: adding another column group on Stations inherits "before".
What had to move with it (all done 11/2, verified live):
- Sheet: direct refs shifted themselves (helper formulas, rep-list FILTERs, dropdown ranges incl. chip
  style, every Stations CF rule). The ONE cross-tab INDIRECT left anywhere — Verizon Sales Board CF rule
  0, `'Stations'!$K$30:$K$43` — re-pointed to `$L$30:$L$43`. (NDS board / Roll Call CF no longer use
  INDIRECT to Stations.)
- Script (Code.gs + RollWeek.gs, pushed via the Apps Script API): `OFF_COL` 91→92, `TERM_COL` 48→49;
  `onEdit` recolor zones, `_recolorRepListOn`, `_strikeStations`, `_recolorChecklists`,
  `_recolorCarNewStartsOn`, `recolorOneBandRepList`, `stnBandRecolor`, `stnAutocomplete` (column B is
  explicitly never autocompleted), `assignNewStartsToCarRides`, `resetOffList` (L5:L18 / L30:L43),
  `checkNameClashes` diag cells; `offSyncOnEdit` MARK OFF column = L on the main tab (K on a BOX Stations
  tab if it ever comes back); `stationsHelperGuard` canon now S5/T5/V5/W5/X5/Y5/Z5 with H:J lists.
  Legacy one-time builders (`fixStationDropdownSources`, `colorStationRunners`, `addNewStartsToCarRides`,
  `fillBaseCarRides`, `boxAudit`, `addDuplicateHighlight`) still carry old letters — do not run them.
- Lucy (main, abbdf931): `car_rides` BOXES att range A5:F14 (columns found by header, so the Notes
  column is skipped); `sales_boards/week_roll.py` `STATIONS_WE = "R2"` (next Monday's flip writes R2).
  `vantura_board_audit` locates Stations cells by formula content — nothing to change.
- Observed while here: the **BOX Sales Board and BOX Stations tabs are gone** (BOX retired 10/28). The
  `car_rides` job opened "BOX Stations" by name and died before doing the AT&T half — now a missing tab
  skips that campaign. The Car Rides Report tab's last entry is 2026-09-29, so that job has not been
  delivering for a month either way — worth a look.

**Friday's new starts → Stations "New Starts".** The Stations list fills itself from Roll Call rows with
week = board B2, Status "New Start", campaign NDS/Verizon, Date Gone blank, not on the board (helpers
X5/Y5). Kaleigh Jolie Stephenson + Isadora Bazan Puga were added through the menu this morning and
show. The Daily Update tab cannot say who starts Friday (it never updates a start date once a row
exists) and the laptop's AppStream login is timed out, so a new one-office reader was built:
`lucy rerun appstream_new_starts --office 11580 --start 2026-11-02 --end 2026-11-08 --tab "New Starts
11580"` (main, c1b312ae) — Total New Starts Scheduled / New Starts Showed Up / Brought on Board Booked
per day, dropped on that control-workbook tab. Result 11/2: NOBODY booked for Friday; 13 booked for today's
orientation + Ann Ali for Sat 11/7. Added the 8 whose Daily Update status was confirmed (Hired Today /
Confirmed Classroom) as 11.8 New Start roll rows via the API (format + validation copied from the row below,
like `_addRollRowIfNew`): NDS Angela Rizo, Roxanna Martinez, Viridiana Cura, Stefany Zaldivar, Zayra
Finlinson; Verizon Jaime Castillo Ii, Sara Ronderos, Axel Soto. Left out (NA Classroom / Declined): Victoria
Limon, Dayna Sifuentes, Melanie Espinoza, Roseanna Jurado, Richard Moye. A no-show needs a T on the roll
before Monday 8:20 or the flip promotes them onto the board as In Training.

## 2026-11-03: how the NDS numbers really arrive + the Revenue Board's missing reps

**Carlos asked "what's your process for getting the sales numbers on the NDS Sales Board".** What the
logs show (Hub Activity + `logtail vantura-nds-sara source`):
- The 4–9pm hourly + 5am `vantura_nds_sara` passes all run clean, BUT the relay leg is never used: the
  office Mac mini relays Carlos's office as enrolment `carlos-b2batt (b2b_att)`, and the fill only
  accepts an office enrolled as campaign `nds` (`no carlos* office enrolled as 'nds' relayed for this
  day -- relayed: carlos-b2batt (b2b_att)`). So EVERY pass falls back to `source: direct SaraPlus read`
  from Lucy 2 (creds `~/.config/recruiting-report/saraplus-creds-nds.json`, alphaletegp). That read has
  been passing the passcode wall since at least 10/30 (the 10/24 blocker is moot for the fill; the
  office mini's own wall is a separate thing, see LOCAL-OFFICE-SALES-CALLOUTS-README 11-02).
- 5am 11/3: `0 cell(s) would change` for Monday 11/2 (board already = SaraPlus from the evening
  passes). The Slack fill said the same (`B2B Monday 11/2 — 0 cell(s) would change`).
- The order-log morning ladder still runs 5:02–9:30 but "Lucy At&t Data" has 3 rows since the move to
  NDS SaraPlus (10/19) — it contributes nothing for NDS.
- `[incident] vantura_nds_sara: delivery still unverified` in every log = an OPEN corrections ticket
  that can't self-close because `verify` isn't wired for the card; cosmetic, a ✅ on the thread post
  closes it.
- To re-enable the relay leg (cheaper, no SaraPlus login from Lucy 2): enrol the office mini's
  `carlos-b2batt` key as campaign `nds` in icd_alerts, or add an `nds` enrolment. Not done 11/3.

**NDS Revenue Board showed two reps (Carlos: "that makes no sense").** `nds_metrics` prices the
board off the Tableau NDS-SN ORDERLOG (owner CARLOS HIDALGO, Mon..today window), then filters the
lines through `total_knocks.guests.GUEST_REPS` — the hand-kept 9/25 fiber-era roster (16 names + Carlos).
Everyone who joined the NDS board after that (Annett, Elisa, Nathaly, Brianna, Esmeralda, Cinthya,
Yahir, Eric, Valerie, Jorge Hernandez, Ruby) was dropped as "non-crew on his owner" — and the same
filter sits under EVERY crew-based section of the NDS Metrics thread (% On Board, Order Log, Activation
boards, Pending, Churn ...). Fix (main d94d28e0): `nds_metrics.run.crew_names()` = static roster +
Carlos + every rep in column B of the live 'NDS Sales Board' (via vantura_slack_sales.board_grid /
campaign_rows), de-duplicated, static-only fallback when the sheet can't be read; `load_crew` now logs
the dropped names (`non-crew on his owner (dropped): name=n, ...`). The Tableau line itself still has
to exist: OOF orders reach the NDS-SN log through the call center, so a Tuesday-morning board covers
Monday only and lags late-entered orders. Lookout for the OTHER sections: a rep on the board under a
spelling Tableau doesn't use (first token must match) still drops — read the dropped-names line in
`logtail orch-<date>-nds_metrics non-crew`.
**12 vs 10 on Monday 11/2 (Carlos: "its showing 12 sales on the sales board but we did 10").** SaraPlus
had 10: Annett 3, Elisa 4 (NL 1-3 + Internet Air), Jose Manuel Pimentel 1, Fernando 2. The other 2 were
Eduardo Alvarez's 8:24pm post ("D2D AT&T ... NL 1 / NL 2 BYOD"), which the SLACK fill raised onto the
board at the 9pm pass; the SaraPlus pass one second later logged `! Eduardo Alvarez has 2 on the board
but isn't in Sara — LEFT as-is` (Megan's rule: a board rep absent from Sara is never touched). So the two
fills disagreed and the board kept the higher one. Fixes 11/3:
- `vantura_slack_sales.run.SARA_OWNED = ("B2B",)` + `slack_fill_campaigns()` (main 2d55eef0): the Slack
  fill still reads and counts NDS posts in its log but NEVER writes the NDS board; Verizon still fills
  from Slack. The NDS board = SaraPlus and nothing else. Trade-off accepted: if the SaraPlus login breaks,
  the NDS board stays empty until the next pass that logs in (the 4pm HOLD alert says so).
- E12 (Eduardo, Monday) cleared by hand → NDS Monday 10, Current Week 10.
- Still true: a rep absent from Sara is left as-is, so a HAND-typed number stays until someone clears it.
Diagnose a mismatch: `logtail vantura-nds-sara SUMMARY 2` (per-rep units from Sara, truncated at ~200
chars — use `logtail vantura-nds-sara <REP-UPPERCASE> 2` for one rep's `Int n + NL n  Up n Air n DTV n`
line and the `!` flags).

**11/4 — Roll Call "Off" marks not showing on Stations (Carlos).** Root cause: the Stations MARK OFF box
is two-way — manual dropdown picks in the TOP half (L6:L11 NDS / L31:L36 Verizon) and a TODAY()-keyed
auto-list formula at **L12** (NDS) / **L37** (Verizon) that lists every Active / New Start rep whose
Roll Call mark for today's weekday is "Off". The 4am `resetOffList` cleared the WHOLE box (L5:L18 /
L30:L43 — before 11/2: K5:K18 / K30:K43), so the auto-list formulas were wiped and the box stayed empty.
Fixed 11/4 (Apps Script API PUT, HEAD = live for triggers): `resetOffList` clears only L6:L11 / L31:L36;
`stationsHelperGuard` (6:45am `rollDailyNormalize`) re-seats L12 / L37 ONLY when the cell is empty;
formulas re-written by hand 11/4:
`=IFERROR(FILTER('Roll Call'!$E$3:$E$1500, ('Roll Call'!$B$3:$B$1500="Active")+('Roll Call'!$B$3:$B$1500="New Start"), ('Roll Call'!$D$3:$D$1500="NDS")+('Roll Call'!$D$3:$D$1500="B2B"), INDEX('Roll Call'!$H$3:$M$1500,0,WEEKDAY(TODAY(),2))="Off"),"")`
(Verizon: campaign "Verizon"). No week filter on purpose: Roll Call col A is the rep's START week, and
H:M always hold the CURRENT week's marks. Lookouts: the list spills down from L12 (more than 7 Off =
rows past L18); the mark must be exactly "Off" (NoShow/Floater don't list); a Roll Call column insert
shifts these direct refs by itself but the guard's canonical copy must then be updated too.

**Board vs SaraPlus audit (11/3–11/4, `rerun vantura_nds_sara --probe --date <d>` per day, logs via
`logdump`):** WE 11.1 matched rep-for-rep every day — Mon 11, Tue 13, Wed 13, Thu 23, Fri 28, Sat 17
(=105) — and Mon 11/2 = 10 once Eduardo's Slack-only 2 was removed. The only "off" day was Sara's own
over-count (Cinthya Tue 11/3). Method note: the SUMMARY line truncates names to 22 chars (Diego Javier
Del Pozo…, Nathaly Elizabeth Moli…) — compare on the per-rep `-> Board Name =` lines, not the summary.

**11/4 — SaraPlus itself over-counted (Cinthya Tue 11/3: Sara 8 NL, real 4).** The board copies Sara
exactly, so a Sara mistake lands on the board; `rerun vantura_nds_sara --date 2026-11-03` at 8:58 found
Sara STILL at 8 ("board already matches SaraPlus"), so F16 was set to 4 by hand (Carlos). A hand-set
number on a PAST day sticks: the passes only read today (4–9pm) and yesterday (5am); only a hand
`--date` rerun re-reads an older day, and that would put Sara's number back if Sara is still wrong.
When Sara is corrected later, the rerun is safe. Standing rule: Carlos's word beats Sara on the board.

**Revenue Board rule (Carlos 11/3, main a92df54f): "if you ever see a sale from someone not on the list
you still want to add it for the revenue board."** `load_crew` keeps every line on his owner on
`cols.owner_lines`; `build_revenue_board` prices those (no crew filter at all) and logs
`revenue board: +N rep(s) off the roster, kept: ...`. A crew filter that matches nobody now falls back to
all owner lines instead of raising. Re-post of one section = `rerun nds_metrics --prune revenue_board
--only revenue_board --post --force` (prune deletes the old reply from today's thread first).

## 2026-11-05 — Revenue Board "$6,153" vs the direct deposit "$6,311" (WE 11.1)
Carlos: the NDS activation-revenue table said last week (10.25–10.31) posted $6,153; his DD shows NDS Wireless $6,311. Both are right — they measure different things. Reconciled line by line (RAW tab WE 11.1 block, campaign `NDS Wireless`, ties to $6,311 exactly; SaraPlus orders behind the board dumped with `lucy rerun nds_metrics_probe --soh-dump` → control sheet 'DD Probe' tab; per-line truth from the 'NDS Order Log' tab).

**Bridge:** board $6,153 → minus 13 lines SaraPlus calls activated but the NDS portal still shows Shipped/Delivered (−$2,381) → minus 3 lines activated after the deposit cut, Marvin Stone L2 / Kenny Nguyen L4 / Cardinal's new line (−$451) → minus Dania Marisol Amaya, disconnected (−$188) → minus Noe Mendez paid at the in-footprint rate $193 not $213 (−$20) = **$3,113 paid for the board's orders** → plus Subba Rao's 10/31 line the board files under Cancelled because a sister line disconnected (+$213) → plus Jose Guevara, SaraPlus active 10/23 so the board had it the week before (+$193) → plus Sunday 11/1 activations the board shows under THIS WEEK (+$1,278: Georgeatte Mcdonald 2, Subba Rao 2, Sri Krishna Majety 2) → plus Internet Air activations the board can't see (+$369 = 3 × $123) → plus Smedra's Tier Volume Bonus (+$840) → plus add-ons (+$305) = **$6,311**.

**Why, structurally (lookouts):**
1. The board prices EVERY line of an order on the day SaraPlus stamps the order's `Wireless Active Date`; AT&T pays per LINE as each one actually activates (phones still Shipped/Delivered pay nothing yet). That alone was $2,381 of the week.
2. The deposit's week runs Mon–Sun (WE 11.1 paid activations 10/26–11/1); the board's weeks are Sun–Sat Tableau weeks. Sunday activations always land one board-week later.
3. The alphaletegp SaraPlus export has no Internet Air column and no IF/OOF flag: Air activations ($93 + $30 ABP = $123) never show on the board, and in-footprint ports pay $193 (the DD marks them `IF`), the board assumes $213 OOF.
4. Tier Volume Bonus and add-ons (Unlimited Extra $10 / Premium $15 / Protect $15+$10) exist only in the DD — the board's subtitle already says add-ons are out.
5. Chargeback watch: Subba Rao Maddela L1 disconnected 11/5 after all three lines were paid in WE 11.1.
Possible fixes, NOT built (Carlos's call): price per line from the NDS Order Log statuses instead of per order; add Air from the SaraPlus AIA count; read IF/OOF from the Tableau NDS-SN order log. Owner boards untouched; nothing on the Vantura board was written.

## 2026-11-06 — NDS Activation Revenue now priced per LINE (+ Internet Air), Mon–Sun weeks
Carlos, after the $6,153-vs-$6,311 bridge: "yes you should price each individual line and add internet air." Built as `automations/nds_metrics/line_revenue.py` (main f77614a6); `build_activation_revenue` in nds_metrics/run.py is now a thin wrapper around it. Same PNG, same thread section ("NDS Activation Revenue Overview"), same `[nds] act-rev <label>: posted / open / cancelled` log grammar.

**How it works now**
- **Lines + statuses** come from the NDS Wireless Resolution Report (the per-line SaraPlus feed `nds_wireless_pull` caches at 06:10 Mon–Sat as `output/nds_metrics/nds_wireless_<date>.html`), read with `nds_metrics.wireless_pull.parse` — the same parser the 'NDS Order Log' tab uses. NOT `sp_order_log.wireless_lines.parse_wireless_xls`: that one returned nothing for the grid-scrape days (10/31, 11/4–11/6) and hung SPM orders' lines on the previous DSI order.
- **A line's activation day** = sp_order_log's activation ledger (`~/.config/recruiting-report/sp_line_activations.json` on Lucy 2, keyed by phone number): the first cached feed that shows the line Active. Every run replays ALL cached feeds oldest→newest into it (idempotent — a stamp never moves), so the board doesn't care which order-log path ran that morning. A live flip is dated **two days before** the feed that first shows it (`LIVE_FLIP_LAG_DAYS = 2`: SaraPlus runs a day behind AT&T, the 06:10 pull another), never earlier than the order's own SOH active date. A line already Active on the earliest feed takes the order's SOH active date (src `order`), or its order date if the SOH has none (src `orderdate`).
- **Price per line** (sow_rates.json, base comp, OOF): port $213, BYOD port $188 (the feed's device cell says "BYOD"; if it doesn't, the SOH's BYOD Line Count marks that many unshipped ports), new line $25, upgrade $30, tablet $25; the plan's Unlimited Extra $10 / Premium $15 rides on an active line. **Internet Air** $93 (+$30 when the order's ABP = Y) from the SOH's Internet Package/Status/Install Date, dated by install date. Still deposit-only: Tier Volume Bonus, Protect, the in-footprint $193 rate.
- **Weeks are Mon–Sun** like the deposit ("LAST WEEK (WE 11.1: 10.26 - 11.1)"). Cancelled $ = a dead line in the week it died (first feed showing it dead, −2 days; else the SOH cancel date); a line paid in an earlier week stays posted there too (the chargeback warning); same-week activate-and-die = cancelled only. Still Open $ = not yet active and not dead, any week. An order the feed doesn't carry is priced the old way (order level) and counted in the log.
- **Calibration / audit:** `lucy rerun nds_metrics_probe --line-calib` replays the feeds, prices every line, lays them against the latest deposit week on the RAW tab, and writes three sections to the control sheet's 'DD Probe' tab: the deposit join (verdict per paid line), the per-line status TIMELINE across feed days, and every board line. Log lines `CALIB …`, `TIMELINE …`, `[calib] verdicts: …`. Re-post of the section alone: `rerun nds_metrics --prune activation_revenue --only activation_revenue --post --force`.

**Lookouts**
1. No feed on Sunday (the pull runs Mon–Sat); Saturday/Sunday activations show on Monday/Tuesday. On Mon–Wed mornings "last week" is still catching up; it is complete by the Wednesday deposit.
2. If the lag drifts (SaraPlus faster or slower than a day), the probe's TIMELINE section shows it: compare each line's first Active feed day with the deposit's activation date. Change `LIVE_FLIP_LAG_DAYS`, nothing else.
3. The feed's first cached day (10/29) is the ledger's horizon: lines already Active then are dated by the SOH order date, which is exact only for the order's first line.
4. The sp_line_activations.json file is shared with the B2B sp_order_log path (keys are phone numbers; an added `first_dead` field is harmless there). Deleting it just makes the next run replay the caches.
5. NDS_SINCE (10/20) floors the SOH: Jose Guevara's 10/19 order was paid as NDS Wireless in WE 11.1 but is off every board. Not changed (affects every crew board) — Carlos's call.
6. The feed cell names are confusing: `wireless_pull.parse` stores the phone number as `device`, the device type as `line_number`, the model as `line_phone`; `line_revenue.parse_feed` renames them (tn / device_type / device). The tab's "Device" column is the phone number for the same reason.
Calibration result (WE 11.1 deposit, 27 paid lines, probe run 11/6 10:21): 21 exact to the day, 2 off by one day (Zechariah Lucy, Noe Mendez — same week), 3 Internet Air matched by count, 1 outside the board (Jose Guevara, order 10/19 < NDS_SINCE). Board last week = $5,283 (21 wireless lines $4,649 incl. Cardinal's $25 new line the deposit hasn't paid yet, add-ons $265, Air $369) vs deposit $6,311: the gap is the Tier Volume Bonus $840, Guevara $208, Protect $40, and $5 net of IF/Cardinal — all deposit-only by design. With the old per-order board the same week read $6,153 with $2,381 of unshipped phones in it and the Sunday lines in the wrong week.

### 2026-11-06, later — rep tier bonus on the board, Protect after the 11/3 notice, NDS start = 10/19
Carlos: "protect add ons should be on sara plus somewhere look again. Tiers you can calculate. Check my email…"
- **Rep tier bonus — now on the board** (main 3c309e74). The rule is Sean Balderrama's 10/19 reply "Re: NDS - Commission Grid": *weekly lines are paid a tiered bonus based on ORDER count within a given week, paid upon line activation* — <4 orders $0, 4 → $30, 5–6 → $50, 7–8 → $75, 9+ → $110 per activated line. Decoded against the deposits: the week is the **Sun–Sat SALE week** of the order (not the activation week), an order counts when it has at least one port line (Jacob's upgrade-only order didn't count; Air-only doesn't), and Sean's "Double Tier Bonus — <date>" emails make that day's sales count twice (10/8, 10/9, 10/10, 10/12, 10/31 so far — `sow_rates.json rep_tier.double_days`, append each new one). Reproduces every Tier Volume Bonus row on WE 10.25 and WE 11.1: Smedra 4 orders in 10/19–10/25 (incl. Guevara 10/19) → $30 on Fernando/Guevara; 6 orders 10/26–10/31 + the 10/31 double = 7 → $75 on Luis/Maricio/William/Amada; Andrew 4 → $30. DNQ (0–30 churn > 7% at 20+ activations, or activation rate < 60% at 20+ sales) is NOT modeled — Smart Circle's "Tiered Bonus DNQ" Tableau view (NDS-SN RES-ATT-OOF workbook) shows who was disqualified. The bonus rides each activated port line's posted $ in its activation week; the log line says `rep tier bonus $X last / $Y this on N line(s)`.
- **NDS_SINCE moved 10/20 → 10/19.** Guevara's 10/19 order was paid as NDS Wireless and is the 4th order of Smedra's tier week; every crew board now starts 10/19.
- **Protect Advantage.** Smart Circle's 11/3 email "Device Protection (PA) - Bonus Removal Effective 11/3" (Sean Balderrama): the $10 (PA1) / $25 (PA4) BONUS is gone for sales from 11/3; the base stays — 1 line $25 → **$15**, 4 lines $75 → **$50**. So Protect is still paid. It is NOT in anything SaraPlus gives us: the SOH export (97 columns, none for features), the Wireless Resolution Report (plan only), or the customer card (per-line Line Number / Status / Phone / Type / Fulfillment — no features; checked on the 11/5 TNC Probe dump). Until a SaraPlus surface with features is found, Protect stays deposit-only; `sow_rates.json addons` carries the new $15/$50.
- Expected read for WE 11.1 after this change: board ≈ $6,351 vs deposit $6,311 — the $40 gap = two in-footprint lines paid at $193 (Noe Mendez, Jose Guevara; the board prices OOF $213), Cardinal's $25 new line the deposit hasn't paid, minus Sravanthi Solasa's $25 Protect. Confirmed by the 12:09 calibration run: board WE 11.1 = **$6,351** (25 active lines $4,592 + add-ons $250 + tier $840 + Subba Rao's 3 paid-then-disconnected lines $669); the tier total equals the deposit's $840 to the dollar (Smedra 3 × $30 + 10 × $75); 21 of 24 paid lines exact to the day, 3 off by one day in the same week (Zechariah Lucy, Noe Mendez, Jose Guevara), 3 Air matched. Posted into the 11/6 NDS Metrics thread at 12:10.

### 2026-11-06, evening — in-footprint off the order log, double-tier days off Sean's emails (main 371e6c5a)
Carlos: "on the order log you can see if its in foot print. i want the majority checked on sara but for the in foot print thing youll probably need to look at the order log. Double tiers you can see off of my email and then you'll know sales from that date are double tiers."
- **In-footprint.** The Tableau NDS-SN order log (the CSV `nds_metrics.pull` already fetches every morning; columns incl. `IF/OOF`, `spe.TN`, `Wireless Installment Plan`, `Auto Bill Pay`, `Rep Tier Bonus Status`) is joined to each SaraPlus feed line by phone number (`line_revenue.if_numbers`); an IF number prices port $193 / BYOD $168, everything else stays OOF $213 / $188. A number the order log has not seen yet prices OOF until it shows up. Log line `[nds] order log IF/OOF: OOF=…, IF=…; N in-footprint number(s)`.
- **Double-tier days.** `nds_metrics/double_tier.py` searches Carlos's inbox (carloshidalgo349; Raf's raffi127 file is the fallback where it exists) for sender sbalderrama@thesmartcircle.com, subject "Double Tier", since 10/1; the M/D in the subject is the double day (the email says "tomorrow, 10/31" or "today, 10/9"). Days are cached in `output/nds_metrics/double_tier_days.json` and unioned with the seed list in sow_rates.json, so an inbox outage never forgets one. Refreshed on every board run; `rerun nds_metrics_probe --double-days` prints the list. Lookout: if Carlos ever rotates that app password, re-push the file (the inbox manager on the mini breaks at the same time, so you'll know).
- Still deposit-only: Protect Advantage (no SaraPlus surface shows it) and the tier DNQ rule. 12:34 calibration: Noe Mendez and Jose Guevara now price $193 (IF off the order log; vocab IF/OOF), and WE 11.1 reads **$6,311 = the deposit to the dollar** (28 lines $5,191 + add-ons $280 + tier $840 — Cardinal's unpaid $25 new line and Sravanthi's unseen $25 Protect cancel out). Posted into the thread 12:34. Double-tier reader verified 12:59: it reads CARLOS's inbox (carloshidalgo349 — the mini's inbox manager already held that Gmail app password; it was moved to Lucy 2 with `push_cred_file gmail-app-password-carloshidalgo349 "Lucy 2"`, a key added to mini_control's whitelist, main 7665d921) and found Sean's 5 emails: 10/8, 10/9, 10/10, 10/12, 10/31. Raf's file is the fallback on a box that has it. Lookout: a NEW push_cred_file key only works after `restart_poller` on the receiving box — the running poller keeps the old whitelist in memory (first push failed 'unknown file-key', second landed after the restart).

### 2026-11-06, night — Protect Advantage found on the SaraPlus GRID and priced (main 71dce217)
Carlos: "can you see when the protect is attached on sara plus or in the order log". Word-searched "protect" through today's three caches (`rerun nds_metrics_probe --find protect`): the Tableau NDS order log has NO protection field (it does carry `Rep Tier Bonus Status` = Smart Circle's own 0/30/50/75/110/DNQ per line, and `Wireless Installment Plan` with "Next36 w/ Next Up"); the SaraPlus CSV export has none (97 columns); the wireless report has none. The T&C probe's header dump of the on-screen **Sales Order History grid** (142 columns) has them: `[107] Protection Plans Sold`, `[133] Protection Plan`, `[134] Plan Status` — per ORDER, the grid shows columns the export omits.
- **Build:** `nds_metrics.run._grid_protect` pages through that grid right after the CSV export in the same browser session (nds_tnc_check's `_read_grid_raw` / `_next_page`) and writes `output/nds_metrics/nds_protect_<date>.json` ({order id: sold, plan, status, wireless status, active date, rep, customer}). A grid problem never sinks the export (own try). `line_revenue.load_protect` reads today's sidecar (else the newest) and `compute` prices each plan with the order's FIRST activated line — $25 (PA1) / $75 (PA4) for sales through 11/2, $15 / $50 from 11/3 (`sow_rates.json protect_rates`, the 11/3 bonus-removal notice) — posted/cancelled/open like a line. `rerun nds_metrics_probe --protect` prints the sidecar's orders with plans; the log line carries `protect N plan(s) $X last / $Y this`.
- Lookouts: the sidecar is only refreshed by a real SaraPlus pull (once a day, or `rerun nds_metrics --repull …`); the PA4-vs-PA1 split keys on a "4"/"four" in the plan text; "Plan Status" is not yet used (a cancelled plan still prices until its order dies). First live read 14:03: 3 orders with a plan in the 31-day window (Gustavo Arbolde/Smedra 10/21 open, Jean Carlos Tello Salazar/Yahir 10/21 → 10/23, Sri Krishna Vinay Majety/Yahir 10/23 → 11/1 = the deposit's 'Sravanthi Solasa' $15+$10 row, same order DSI281145813). The grid's 'Protection Plan' cell was BLANK on all three (only 'Protection Plans Sold' = 1), so every plan prices as PA1 until a PA4 ever shows a plan name — watch the deposit for a $50/$75 Protect row. WE 11.1 now reads $6,336 vs the deposit's $6,311: the whole gap is Christopher Cardinal's $25 new line (SaraPlus dates it 10/31, the deposit hasn't paid it yet). Posted into the 11/6 NDS Metrics thread at 14:04.

### 2026-11-06, night — new section "NDS Activation Rate by Week Ending" (main 30178f82)
Carlos: "activation rate by the week ending and i want look at the last 5 weeks … off all sales made on X WE date how many have activated / whats the activation rate for that WE … show each WE since ive been on NDS." `automations/nds_metrics/activation_by_week.py`, section id `activation_by_week`, posts daily in the NDS Metrics thread right after "Activation Rate by Rep".
- (Restyled the same evening, main e1ab14a0, Carlos: "looks like the other activation reports … every morning we get a screenshot": now drawn with `b2b_metrics.rep_boards.render_table_png` exactly like "NDS Activation Rate by Rep" — Crew Total row then a row per rep, a COLUMN per week ending with its sales count in the header (* = in progress), each cell `(activated/sold)` + rate on the same Green/Yellow/Red bands (vantura_churn.fill.BANDS, 0–30 scale for weeks ≤ 30 days old, 31–60 after). The paragraph below describes the counting; the first PIL table layout is gone. Later the same evening (main 2a4c9a4f, Carlos: "right under Crew Totals … show the cancel rate and then how many are pending"): two more crew rows under the activation row — "Crew Total — cancel rate" (cancelled-before-activating ÷ sold, coloured like the Churn Rates board: green < 4%, yellow < 6%, red) and "Crew Total — lines still pending" ("n of sold", grey); rep rows stay activation-only. `--dm U…,U…` now sends one group DM of the board.)
- One row per Mon–Sun week ending (WE Sunday, the deposit's week) since NDS_SINCE, the last 5, oldest first, the week in progress marked. Columns: Sales (wireless orders by ORDER date; Air-only orders excluded), Lines (every line of those orders off the wireless report, cancelled included; an order the report lacks counts its SOH line count), Activated (Active now, or was Active before it died — the Tableau board's rule), Pending, Cancelled, Act. Rate = Activated ÷ Lines (red under 60% = Smart Circle's tier-bonus DNQ line, which only applies at 20+ sales), Sales w/ activation (orders with ≥1 activated line). TOTAL row.
- Numbers only: `rerun nds_metrics_probe --week-rates` (log lines `[nds] act-week WE m/d: …`). Re-post: `rerun nds_metrics --prune activation_by_week --only activation_by_week --force`.
- Lookouts: rates for a young week read low by design (lines ship/port over 1–2 weeks; the feed lags AT&T by ~2 days); the rule counts churned-after lines as activated (churn has its own board); an order that disappears from the 31-day SOH window drops out of its week (the window is the SOH pull's, not the board's).

### 2026-11-07 — two Tableau screenshots every morning + the pending breakdown (main fc6933bc)
Carlos: the NDS workbook's "Order Rep Tiered Ranking" filtered to his owner ("we used to post this … when we were doing B2B … every morning in the NDS metrics thread, post this screenshot"), and the workbook's "Top 100 Reps View" showing the top 50.
- `automations/nds_metrics/tableau_shots.py`, sections `rep_tiers` ("NDS Rep Tiered Ranking (this week)") and `top_reps` ("NDS Top 50 Reps") right after `activation_by_week`. Views: `NDS-SNRES-ATT-OOFWorkbook/OrderTieredBonus-RepRanking?Owner%20Name=Carlos%20Hidalgo` (the view's own Time Frame default is This Week; member spelled "Carlos Hidalgo") and `…/Top100RepsView` (its default week = the last complete sales week). Capture = `tableau_screenshots.capture.capture_page` (Tableau Download → Image, full canvas) inside the shared `tableau_session`, like the B2B `order_tiered_bonus` capture.
- Crops: the tiered ranking canvas carries a page of white space under a short table → `crop_to_table` cuts at the last pixel row whose dark pixels span > 50% of the width (the table's bottom border; the "Last Server Update" footer box is narrower). The Top 100 list runs 106 rows → `crop_rows(png, 50)` finds the horizontal grid lines, takes the modal gap (64 px) as the data-row pitch and cuts at the line closing row 50. A blank board (`metrics_shot._looks_blank`) raises, so an unknown owner member skips the section instead of posting white.
- Hand runs: `rerun nds_metrics --only rep_tiers,top_reps` (posts into today's thread; add `--prune rep_tiers,top_reps … --force` to replace). First look at any Tableau view without wiring: `rerun b2b_churn_preview --url <view url>` → base64 in the control sheet's 'B2B Shot' tab → decode on the mini (scratchpad decode_shot.py pattern: join column A, base64-decode).
- Lookouts: a Tableau URL filter value that matches no member blanks EVERY filter on the view (memory: Tableau URL filters) — if Carlos's owner member is ever renamed, the section raises "blank" and the log says so; the Top-50 crop depends on the row pitch staying uniform — a taller multi-line row would shift the cut by a row.
- **Pending breakdown (Carlos: "why are lines pending?")** from the 11/6 calibration: WE 10/25 36 of 92 pending = 34 Delivered-never-activated + 1 Shipped + 1 Pending; WE 11/1 61 of 103 = 44 Shipped, 11 Delivered, 2 Porting Issue, 1 Pending Valid Payment, 3 blank; WE 11/8 (in progress) 56 of 65 = 20 Shipped, 20 Pending Shipment, 5 BYOD, 4 Delivered, 2 Pending Valid Payment, 1 Backordered, 4 blank. The 34 delivered-and-sitting phones from WE 10/25 are the actionable ones (the Delivered-message text job already chases them).

### 2026-11-07 — Verizon Sales Board off the office ROSTER post (red drops) (main 92b2e896)
Carlos: "for Verizon, the way they post their sales on Slack now is they'll put their name (either their first name or their last name), and they'll put the red teardrop emoji. However many teardrops there are is how many apps they got. Can you go back and update the sales board based off of those red teardrops?"
- Since 11/5 the office posts ONE running list all evening (Samantha, Isaac, Jacob, Andrew, Jayden, Gary, Eduardo, Esmeralda, Thais, Edgar, Diego Chacon, Carlos, Diego Borres, William, Nicholas, Nico, Jose Pimentel all re-post it): `Verizon D2D 🔥🔥📈‼️` then `CHACON 🩸🩸🩸🩸`, `SAMANTHA 🩸`, … (Verizon apps), then `Jacob 📱📱📱` … (AT&T sales, phones), then `48/50 🔥🔥` (office total vs goal). The API text carries the shortcodes `:drop_of_blood:` / `:calling:` (unicode handled too).
- `vantura_slack_sales/parse.py`: `roster_lines()` / `is_roster()`; a roster post is NEVER the poster's own sale (before this, "the word Verizon = 1 sale for the author" would have credited every re-poster); `tally()` for Verizon keys by the NAME on the line, day count = the MAX drops over the day's lists (snapshots, not units); a roster posted before 10am is yesterday's final list (Andrew 11/6 08:09 = Thursday's). Phones are ignored (the NDS board is SaraPlus-owned, Slack never writes it).
- `run.py match_rep`: a lone first/last name resolves to the ONE Verizon row whose first or last token equals it ("CHACON" → Diego Chacon, "BAUTISTA"/"Will" → Will Bautista, "THAIS" → via the alias); two rows sharing the token = unmatched, reported in the log ("NOT A Verizon REP ON THE BOARD"), never guessed. The fill stays raise-only.
- Backfill: `rerun vantura_slack_sales --week` (base_args carry `--fill --yes`) = Mon..yesterday of the week the board shows; past weeks are rolled off the live board (WeekData) and are NOT touched by this. Hand run for one day: `rerun vantura_slack_sales --date YYYY-MM-DD`.
- Lookouts: a new rep whose roster name matches no row (or two rows) shows in the log as unmatched — fix the board row name, not the parser; a line with BOTH drops and phones counts the drops only; "N/50" totals are ignored. First backfill 11/7 09:17 (`--week`, Mon 11/2–Fri 11/6): Mon already agreed (6/6); 17 cells raised — Tue Jair Otero 0→6, Jose Ramos 1→2, Thais 1→2; Wed Diego Chacon 2→6, Edgar 1→4, Isaac Nambo 1→3, Jair 0→5, Marco Antonio Hernandez 2→4, Thais 1→2; Thu Edgar 1→3, Gary 2→6, Jair 0→1, Thais 1→2; Fri Diego Chacon 1→4, Gary 1→2, Jayden 1→4, Thais 1→2. UNMATCHED (reported, not written): Samantha / Samantha Ruiz (2–4 apps a day, no Verizon row), BAUTISTA (two Bautista rows — Will and Richard — so the bare last name is ambiguous; 'Will' lines do land), Nick (6 on Wed; neither 'Nico Murrugarra' nor 'Nicholas Esmerado Macias' starts with 'nick'), Gio / Giovanni Monreal (no row), JACOB (2 on Thu, no Verizon row), and 'Jair Otero' full-name posts miss the board row spelled 'Jair Ortero' (the bare 'Jair' lines match it). Board-row fixes are Carlos's call.
- **Roll Call column Q cleared (11/7, Carlos: "I don't know why there's that random stuff there").** Q19:Q400 held a headerless leftover formula `=IF(OR($E19="",$A19&""<>'NDS Sales Board'!$B$2&""),"",IFERROR(VLOOKUP($E19,'NDS Sales Board'!$B$15:$P$19,15,FALSE),IF($B19="New Start","In Training","")))` — a lookup into a five-row slice of the NDS Sales Board that showed "In Training" on the current week's new starts and blank elsewhere. No formula on any tab and no Lucy code or bound-script function reads or writes Roll Call!Q (checked all 38 tabs' formulas, the repo, and the 11/4 Code.gs/RollWeek.gs/Verizon.gs copies), so Q3:Q400 was cleared by values:batchClear (formats untouched; backup in the session scratchpad rollcall_Q_backup.json). If it ever reappears, a human pasted it.

### 2026-11-07 — Verizon Sales Board corrected from CREDICO's Sales Verification + column Q "Approved" (main 3d299f03)
Carlos (on Megan's HVA Verizon Wireless Sales Tracker): "megan had lucy make this. look through the hub to see how she pulled these numbers. however she got the numbers i want lucy to fill out our verizon salesboard with those numbers. i liked the approved column so to the right of last weeks number add in this approved number that lucy/megan are grabbing".
- **Where Megan's numbers come from.** `automations/verizon_office` (Nico's office, key `nicolas` = Credico "High Value Acquisitions, Inc."): Credico emails `Sales Verification - Verizon Wireless - High Value Acquisitions, Inc. - YYYYMMDD.xlsx` from vzreports@credicousa.com ~10:45am CT, redirected by Nico's Outlook rule into the Hub inbox (alphaletereporting@). `run.fetch` pulls it over IMAP (`email_ingest.fetch_by_globs`, matched by file name + subject); `parse.read_sales_verification` reads 'Sales by Week' (blocks "Week Ending <Saturday>", one row per rep: Sun..Sat VALID LINES, Valid Lines, Valid Sales, 'Appr. %' = lines with an approval date ÷ lines) and 'Overview' (per week '% Appr.'). The file covers sales through YESTERDAY; Credico weeks are Sun–Sat.
- **New module `automations/vantura_verizon_credico/run.py`** (LaunchAgent `com.alphalete.vantura-verizon-credico` on Lucy 2, daily 11:10 + 12:40 CT; registry ids `vantura_verizon_credico` / `install_vantura_verizon_credico_agent`). Reads the 'Verizon Sales Board' tab by header (vantura_boards.columns), places Credico's days by DATE inside the week the gold WE cell shows (B2 "11.8" = Mon 11/2–Sun 11/8), and:
  - sets each matched rep's day cell to Credico's valid-lines count for every covered day — AUTHORITATIVE like the BOX order-log pass (lowering included, log note "LOWERED to Credico — Slack overcount"); a hand-typed marker (T/X/F) stays unless Credico shows lines; a blank stays blank on 0; a board rep Credico does not list is left alone and named in the log ("days left alone") — a name mismatch never zeroes anyone.
  - writes **column Q "Approved"** (header on row 4; first free column right of Leadership Status): each rep's 'Appr. %' for the Credico week whose Saturday falls inside the board's week, and the crew's '% Appr.' on the "Verizon" totals row (row 23). A rep with no Credico row this week gets Q cleared; on Monday before Credico has a block for the new week, Q is cleared and refilled from Tuesday. Written as "85%" (USER_ENTERED → a real percent).
  - NOT inserted between Last Wk and Monday: the day columns, the Monday week-roll script, the Slack fill and the Stations/Roll Call readers all key on E:P; moving them is a coordinated layout change (offered to Carlos separately).
- **Names.** Credico uses the SSO legal name. Match = same first name after the order-log aliases (william→will, nicholas→nick, nicolas→nico, jeffrey→jeff) and tokens a subset either way or same last name; else a near-identical last name (Jair Otero ↔ board "Jair Ortero"); else Credico's first name as a MIDDLE name on the board with the same last name (Samantha Ruiz ↔ "Brandy Samantha Ahumada Ruiz"); "Last, First" handled; apostrophes ignored (Ja'nevaeh). Two candidates = unmatched, reported ("matches no Verizon board row — not written"), never guessed.
- **Screenshots after the write (main 76d3e9dd):** the daily card carries `--repost` — after ≥1 cell is written, the pass runs `sales_boards --program Verizon --post --corrected`, i.e. yesterday's Verizon day board (sorted high→low) and the week ranking land in the day's Verizon Metrics thread with '(corrected)' captions beside the 5:10 replies (sales_boards dedupes by caption, so a second pass the same day posts nothing). Carlos, review DM 11/7 12:44: "then the screen shot sent out like these below. One for yesterday sales sorted highest to lowest and one screenshot for the week sorted highest to lowest" — "these" = the NDS day/week boards sales_boards already posts. A failed re-post exits 2 → the agent's Slack alert.
- **Hand runs:** `lucy rerun vantura_verizon_credico --plan` (read-only, prints every cell it would change; `--plan` overrides the `--fill --yes --repost` a rerun carries); `… --sv FILE.xlsx` reads a local file; `logtail vantura-verizon-credico "" 40` shows the last pass. Stale guard: a newest file older than 3 days writes nothing.
- **Interplay with the Slack roster fill** (`vantura_slack_sales`, evenings + 5am, raise-only from the red drops): Slack is the live ticker for TODAY; at 11:10 the next day Credico overwrites yesterday with the valid count. Saturday's and Sunday's corrections (Credico's Sunday/Monday files) land on Sunday/Monday morning — Monday's 11:10 pass runs AFTER the 8:20 week roll, so Sunday is never corrected on the live board (it rolls into WeekData as Slack left it). `rerun vantura_slack_sales --week` re-raises Slack counts over Credico's lowered cells — run it only before 11:10 or accept the re-raise.
- **Where the file comes from, in order** (main 62360187): (1) the Hub inbox, Credico as sender — the Outlook REDIRECT rule from Nico's Credico mailbox (workflows/verizon-icd-onboarding.md §2); (2) Carlos's inbox (carloshidalgo349, any sender — a forward from Nico or a Credico CC; his app password is on Lucy 2 for the double-tier reader), matched by file name. **STATUS 11/7 13:03:** the first plan run found NOTHING in either inbox for the last 10 days — Nico's redirect is not live yet (Megan's `verizon_daily_nicolas` card is OFF for the same reason; her review sample came from `output/_verizon_inventory/outlook/` on her laptop). Until the redirect (or a daily forward to Carlos) exists, every pass logs `SKIP -- no ... Sales Verification` and exits 0 (no Slack alert), and the Slack roster numbers stand. The day the file starts arriving, the agent fills the board with no further change. Coordination: Carlos told Megan's Lucy the same thing in the review group DM (C0CFN3SBFCM, 11/7 12:44: "pull the numbers and add into our verizon sales board ... Im having claude make a section for the approved %") — the fill lives HERE (Lucy 2); her side owns the screenshots (yesterday + week, sorted high→low) in the Verizon Metrics thread.
- **Lookouts:** (1) Credico's email not arriving = Nico's Outlook redirect rule or the Hub inbox password — the log says "SKIP -- no ... Sales Verification in the Hub inbox or Carlos's inbox" and the Slack numbers simply stand; (2) a new rep on the board under a nickname Credico doesn't carry shows as unmatched in the log — rename the board row (or add an alias in the module), never hand-edit the parser; (3) column Q is now Lucy's — anything typed there is overwritten daily; (4) a changed Credico column label ('Appr. %' / '% Appr.') makes Approved read 0% — `parse.py` raises on the structural columns but not on these two.

### 2026-11-08 — Verizon reps renamed to their CREDICO names, Giovanni on the board, room nicknames wired, Approved column styled (main 04a7e9ef)
Carlos: "Samantha Ruiz is Brandy … whatever her credit code [Credico] name is, go ahead and make that change on the sales board, the daily update, and the roll call so that everything matches … Same with Geo … Nick is Nicholas Esmerado Macias. For Jair, make his name whatever the legal name is, or whatever the credit code name is, and make that change for the daily update and the roll call so everything matches." Approved column: "make the change wherever it's easiest and there's less moving parts, but still looks good."
- **Credico spellings** came from Megan's HVA Sales Tracker image (review DM C0CFN3SBFCM) and `resources/verizon_review/order_log.xlsx` (per-rep tabs = Credico's Sales Agent Names): Jair Hernandez Otero, Brandy Ahumada Ruiz, Giovanni Monreal, Nicholas Esmerado Macias, William Bautista, Marco Antonio Hernandez Rojas, Isaac Salomon Nambo, Thais Alvarez Aragon, Gary Van Whitaker, Edgar Camunez, Diego Chacon, Jayden Willingham, Jose Ramos.
- **Renamed (same person, every live copy):** `Jair Ortero` → **Jair Hernandez Otero** — Verizon Sales Board B9, Roll Call E535, Daily Update row 1193 (his old "Jair Hernandez" B2B row, Not Active/B2B ATT → **Active/VERIZON**; he never had a Verizon DU row), Stations car-ride cell B34 (was typed "Jair Otero"), WeekData keys 10.18/10.25/11.1, RollCallData keys 10.18/10.25/11.1. `Brandy Samantha Ahumada Ruiz` → **Brandy Ahumada Ruiz** — board B15, Roll Call E545, Daily Update I6, Stations C36, WeekData 11.1, RollCallData 10.25/11.1. Archive keys were renamed so "Last Wk" (D) and the Sat/Sun WeekData lookups keep resolving. **Name Aliases** tab got 4 rows (Jair Ortero / Jair Otero → Jair Hernandez Otero; Brandy Samantha Ahumada Ruiz / Samantha Ruiz → Brandy Ahumada Ruiz) so payroll/DU-status readers bridge the old spellings. His April–May 2026 "Jair Otero|…" WeekData keys (earlier B2B stint) were left as they were.
- **Giovanni Monreal** (Credico spelling already matched; he is Credico's #10 this week and the trainer of Nicholas and Jose Ramos) had NO live row anywhere: Roll Call 548 said Terminated 6.28, Daily Update 1064 Not Active. Both flipped to **Active** (the Sunday 7pm du_status job flips a DU row back to Not Active when the Roll Call says gone — so the Roll Call had to move too) and a board row was INSERTED at row 22 (above Nico; the totals SUMIFS grew to $5:$23 by inserting inside the range): # 19, name, C `=SUM(E22:K22)`, Mon–Sun = the WeekData INDEX formulas the other rows use, L Verizon, P Level 1, Trainer/Field Status/Team blank for the office to fill.
- **Room nicknames → rows** (`vantura_slack_sales.NAME_ALIASES`): samantha / samantha ruiz / brandy → Brandy Ahumada Ruiz; gio → Giovanni Monreal; nick → Nicholas Esmerado Macias; **bautista → Will Bautista** (Carlos did not answer this one — he misread my "bare 'Bautista'" as a name — but every 'BAUTISTA' roster line so far equals William's Credico lines (Thu 11/5 = 6) and Richard has none; flagged to him). `match_rep` also resolves a lone token to the ONE row carrying it as a MIDDLE name ("JACOB" → Jaime Jacob Castillo once he has a row); a first/last-name carrier still wins, two carriers = unmatched. Tests: `vantura_slack_sales/test_match_rep.py`.
- **"Jacob" (Carlos: "where are you getting the name Jacob from?")**: Jacob Castillo (Slack U0CE3QF1G4V, jacobcastillojjc@) posted "VERIZON (D2D) JACOB 🩸🩸 2/50" himself Thu 11/5 15:40, Nico replied "First of many", and every roster list that evening carried "JACOB 🩸🩸". He is **Jaime Jacob Castillo**, Roll Call row 18 New Start WE 11.8 (trainer Giovanni), Daily Update 2639 "Showed to Classroom"/VERIZON — not on the board yet. Credico's board through Thu 11/5 has no Castillo row while Giovanni shows exactly 2 on Thu → his two apps were written under Gio's code. No board row added; the normal new-start promotion handles him.
- **Approved column (Q)** stays in Q (fewest moving parts): header "Approved" written on row 4 with P's format copied, Q5:Q24 formatted like P (centered, `0%`), width 130 like P. The Credico pass fills it the day Nico's Outlook redirect (or a forward to Carlos) delivers the file.
- Lookouts: (1) a hand-typed "Jair Ortero"/"Samantha" anywhere new (Stations rides, Roll Call 2nd-rounder/trainer columns) no longer matches the board — type the Credico name; (2) Gio's board row has blank Field Status/Trainer — the Monday roll may fill or the office types them; if the Monday flip ever removes his row, check Roll Call 548 is still Active; (3) the Monday 8:20 roll archives THIS week under the new names, so next week's "Last Wk" is right automatically.

## 2026-11-09 — NDS CHURN tab (the LUCY CHURN report for Carlos's NDS code)

- **What:** tab `NDS CHURN` (sheet 220381511), unhidden, after 'NDS Order Log'. A duplicate of the hidden B2B `LUCY CHURN` tab, so `automations/vantura_churn/fill.py` writes it unchanged: B5:B7 = activation bases (Wireless/Air/Internet), hidden helper block P2:AE41 (one row per disconnected account, FILTER at A16 drives the visible rolloff list, SUMIF at C5:C7), notes lookup at P99+, per-rep activation list at AG15. Written daily by `automations/nds_churn/run.py` on Lucy 2 (card `nds_churn`, 06:00, before the NDS Metrics thread).
- **Differences from LUCY CHURN:** column J = `Line · IF/OOF` (was CRU/IRU; the NDS ORDERLOG export has no disconnect reason); H4:N12 = the NDS SOW churn tiers (Port Non-BYOD / Port BYOD, $ per line at the Churn Notice's 90-day tier, live 0-30 band marked "◀ now"); A13:N14 merged = status line. No captain decelerator. No 'NDS Activations' tab (Carlos 11/9: the NDS Order Log tab is the per-order view).
- **Counting:** 0-30 day by activation (`spe.dtr Posted Date`), distinct `spe.Name`; **wireless = port PHONE lines only** (`spe.TN Type` == port and not a tablet/wearable by `spe.Wireless Type` or device name) — Smart Circle's CHURNRATES view counts the same way (16/126 on 11/9, exact; upgrades, tablet/wearable lines and untyped lines are named on the status line as not counted). Reconcile gate: the view's per-rep sum (office_metrics.nds_churn ChurnALlExp sliced to Carlos) must equal ours (today's or yesterday's window) or nothing is written.
- **Traps:** never add another tab with 'activation' in its title to this board (`fill.activations_worksheet` falls back to it when the hidden B2B 'Activations' tab is missing). The tier charts and status line are rewritten every run — edit `nds_churn/comp.py` (NOTICE), not the cells. A16/C5 formulas are the helper-block contract (`fill.helper_bounds`); don't insert columns left of P or rows above 16. `#N/A` in A16 just means no disconnect for the selected product.

## 2026-11-09 — Roll Call carried last week's marks into the new week

- **Symptom (Carlos, Monday ~noon):** Roll Call Tue–Sat already "marked" for the new week, the boards showing X on Tue–Sun, and the red invalid-data triangle on the week cell (Roll Call I1 = "11.15").
- **What the data said:** the Monday flip itself ran (board B2 = 11.15, Last Wk filled, RollCallData has an 11.8 archive of 50 rows). But the live H:M grid held exactly the 11.8 archive's marks (48 of 54 marked rows identical; the 6 others were today's manager edits), and the RollCallData **11.15 seed rows were a copy of the 11.8 marks** (44/50 identical). That is the fingerprint of the "View wk" switcher: someone viewed 11.8 and came back to 11.15 — the archive marks ended up in the live week. The X marks on the boards were the roll→board Off echo of those stale marks. The red triangle: I1 is TEXT "11.15" while `_rcdAddWeek` appended the week to RollCallData!I as a NUMBER (11.15) — ONE_OF_RANGE sees no match (and "9.20" had become 9.2 twice, "8.30" 8.3); fixed in Code.gs the same afternoon. Also 11/9: the Roll Call basic filter ended at column O — Reason Lost (P) was outside the sort/filter; range set to A:P (`setBasicFilter`, same sort + Terminated-hidden criteria).
- **Fix applied (Sheets API, cell-level; pre-state saved at scratchpad `vantura_prefix_backup_2026-11-09.json` + `rollcall_backup_2026-11-09.json`):** cleared 227 Roll Call Tue–Sat cells that merely repeated the 11.8 archive (cells that differed — today's edits: Eduardo Tue Off, Carlos Tue/Wed Off, Jorge Thu/Fri Off — were left); re-seeded the 50 RollCallData|11.15 rows with the corrected live grid; put the WeekData INDEX day formula back on 32 board X cells (Tue–Sun) whose roll cell no longer says Off (5 X kept where it still does); rewrote RollCallData!I2:I19 as TEXT in the archive keys' own spelling (one "9.20", "8.3" kept as the keys spell it). **Monday (H) was left alone** — it is a mix of today's real marks and stale ones nobody re-checked; Carlos to say whether today's roll was taken.
- **ROOT CAUSE (read from the bound script via the Apps Script API, 11/9 afternoon):** `rollCallNewWeek` ends with `resetRollAttendanceFormulas()` — every live H:M cell becomes `=IFERROR(INDEX(RollCallData!B$2:B$5000,MATCH($E&"|"&$I$1,…)),"")`, a lookup keyed on the week in I1 (it reads blank because the new week has no archive rows yet). Then a manager picked a past week in I1 ("View wk"). The installable onEdit fires AFTER the cell changed, so when `rollWeekView` did its "leaving the live week → snapshotRollAttendance(live)" the formulas already displayed LAST week's marks — and it archived them as the live week (`RollCallData|11.15` = the 11.8 marks, 50 rows, with current statuses; the few literal cells the managers had typed — Carlos, Jorge, Angela — rode along, which is why those survived). Switching back rendered `RollCallData|11.15` over the grid as literals: last week everywhere, today's edits kept. Carlos's account ("blank for everyone, we started filling in, then it filled in all of last week") fits exactly. **Fix pushed to HEAD (Code.gs, Apps Script API PUT):** `snapshotRollAttendance` now reads `getFormulas()` and treats a formula cell as blank (a formula is never a manager's mark); `_rcdAddWeek` writes the week label as TEXT (`setNumberFormat("@")`) so I1's dropdown stops flagging the live week. Triggers run HEAD, so both are live for the next pick; the webapp deployment (week_roll's `rollcallflip` poke) is untouched.
- **Traps:** (0) the live grid after a flip is FORMULAS, not blanks — anything that snapshots the roll must ignore formula cells (now done). (1) don't browse "View wk" to a past week on Monday before the day's roll is settled — the switcher can lay the archive over the live week; if that happens again, the tell is RollCallData|<live week> rows carrying full-week marks on a Monday. (2) a sort on the Roll Call (filter sortSpecs by Campaign) moves rows between two API reads — ALWAYS resolve a row by name right before writing it (a positional write 11/9 landed on Esmeralda/Cinthya for a minute; reverted by name). (3) The roll→board Off echo is on-edit only: API clears on the roll do NOT un-X the board — restore the day formulas by hand (`week_roll.day_formulas` shape).


### 2026-11-10 — Teams box head-count exclusions (NDS Sales Board)
Carlos: Carlos Hidalgo, Jorge Hernandez and Eric Forsythe are not counted under Total Head Count / Leaders / Entry Level / In Training / Sales Avg by Rep; their sales still count in Apps. How: hidden col AR "No HC?" (`=IF(COUNTIF($AT$5:$AT$12,$B5)>0,1,0)`) fed by the hidden list AT4 "Not in Head Count" (AT5:AT12 — add a board-spelled name there to exclude someone else). D43:G48 multiply by `($AR$5:$AR$30=0)` next to the Term? factor `($AQ$5:$AQ$30=0)`; C (Apps) doesn't; H = ROUND(C/D,1). The script's `reanchorBoardStatRanges` and the audit's `_fix_stats_ranges` only re-anchor rows, so the range survives. Counting rule: Head Count = every named, non-terminated NDS row (1st-week reps included); Leaders = Level 1/Level 2/Mastermind; Entry Level = "Entry Level"; In Training = "In Training" and Field Status ≠ "1st Wk". Also restored the AQ5:AQ11 Term? formulas that had gone blank. Verizon board untouched.

## 2026-11-11: Stations rows 60+ — WEEKLY MEETING PLAN (Mon–Sat)

Carlos: "delete everything in the Stations tab under rows 60 and below; make a
table for Monday–Saturday with a column for who, time and the room." The 9/9
boxes ("9 AM TRAININGS" A60:C63, "MONDAY LEADERS MEETING" + "SALES TOTALS &
GOALS / CIRCLE UP" A70:Q107 — merges, navy bands, runner dropdowns, 8-px
spacer rows) are GONE (values backed up in the session scratchpad).

**Layout (A:E, rows 60–146):** r60 title band `WEEKLY MEETING PLAN — MONDAY TO
SATURDAY`, r61 the assignment instruction, then six 14-row blocks — MONDAY r63,
TUESDAY r77, WEDNESDAY r91, THURSDAY r105, FRIDAY r119, SATURDAY r133. Each
block: day band, header `ITEM | WHO | TIME | ROOM | TOPIC / NOTES`, 11 item
rows (ATT Leaders Meeting, VZ Leaders Meeting, ATT Day 1, VZ Day 1, ATT Day 2,
VZ Day 2, Lesson, Circle Up, ATT Announcements, VZ Announcements, Impact), one
spacer. WHO cells carry a people dropdown fed by the hidden active-reps helper
(`=Stations!$Z$5:$Z$80`, warning-only, so a pair or "None" still saves with the
small red corner); ROOM / TOPIC are free text. Everything is centered with
black grid lines; TIME cells are formatted `h:mm am/pm`.
Only Wednesday was prefilled, from Carlos's message.

**What depends on it:**
- `vantura_board_audit` (4am) stops its unknown-rep name scan at the row whose
  col A starts with "WEEKLY MEETING PLAN". Rename that title and every room
  name in the plan ("Atmo Conference Room") comes back as a typo'd rep.
- Nothing writes rows 57+: `resetOffList` sweeps A4:R56, car_rides reads
  A5:F14 + the Verizon block, nds_oof's no-dispo range is C6:F15. The hidden
  helpers S:Z spill downward (Z reaches ~r56 today) — keep the plan inside A:R
  so a longer roster never collides with it.
- `daily_plan_text` (8am Mon–Sat text to NEW A Players) still sends the static
  Wednesday template from its config; it does NOT read this table yet.

## 2026-11-11: "Add > New Starts to Car Rides" fixed (Code.gs `assignNewStartsToCarRides`)

Carlos clicked the menu for the 11.15 new starts and nothing was added. Read the
function through the Apps Script API; three causes, all fixed and pushed (HEAD is
what the menu runs, no redeploy needed):

1. **The NDS "section" was rows 6-25** — the car rides AND the Stations block
   under them (that geometry dates from before 9/3, when the rides alone filled
   6-25). Anyone typed anywhere in those rows counted as "already placed", so
   Anairt and Christopher, sitting in the Day 1 / 10:30 station column (F20/F21),
   were skipped. Now `placeSection("NDS","NDS",6,14)` — the ride rows only
   (same rows Lucy `car_rides` reads, A5:F14, and the ride CF zones).
2. **Verizon section was 29-40** — row 29 is the "CAR RIDES" title row and, with
   C29:F29 empty, it was the first "blank" row a new trainer's ride would have
   been written to. Now `placeSection('Verizon','Verizon',31,40)` (rides 31-38 +
   the "New T" / blank spare rows 39-40).
3. **New starts with no Trainer on the Roll Call vanished silently** (the 9/15
   gotcha). They are still not placed — there is no trainer to put them under —
   but the alert now ends with `No Trainer on the Roll Call (fill col G, then run
   this again): NDS: <name>`. Yoangel Delgado Rodriguez was the case this week.

Also: the ride grid read is now 4 wide (Leader + Rep #1-3 = C:F; the old 5-wide
read reached the spacer column G and `REPS=[2,3,4,5]` could park a 4th rep
there), and the `getDataValidations`/`setDataValidations` round-trip is gone
(`setValues` keeps validations; re-setting them is exactly what turns the Chip
dropdowns into Arrow style — see "THE AUTOFILL TRUTH" above).

No blank ride row left in 6-14 → a trainer without a ride row is reported as
"Bumped / no spot" instead of being written into the gap or the Stations rows.
`placeStore` (unused) got the same return shape. Before/after copies of Code.gs
sit in the 11/11 session scratchpad (`Code.gs.before-*/after-*.js`).

Follow-up (same day): the "No Trainer" line names only new starts who are NOT
already sitting in a ride row (hand-placed people are not a problem), so Yoangel,
whom Carlos placed under Fernando by hand, stops showing up in it.

## 2026-11-15 — NDS CHURN: the rolloff list is now THREE TABLES (wireless non-BYOD / BYODs / Air)

- **What (Carlos):** "The NDS customer churn. Let's make into tables one for wireless no BYODs, BYODs, & airs." A15:N holds three stacked tables — `ALL WIRELESS (non-BYOD)`, `BYODs`, `AIR` — each a band row ("<disc> of <act> disconnected = <pct>", the box row's own numbers), the 14-column header row, one row per disconnecting account soonest to fall off first (or "no disconnects in the last 30 days"), then a blank row. Columns unchanged except E = that table's own "<box row> % After Rolloff"; D stays "All Orders % After Rolloff". Internet has no table (the old All Orders list left it out too). Main d580cf0e; `automations/nds_churn/compute.py` (`rolloff_groups`, `class_tables`, `pct_after`) + `sheet.py` (`write_class_tables`, `write_rep_list`, `ensure_recent_highlight`, `ensure_borders`, `report_range`, `migrate_filter_list`).
- **Mechanics changed — the 11/09 "Traps" above no longer apply to THIS tab:** the tables are plain values written every run (formats first, then clear A15:N98, then values). The FILTER at A16, the B3 "Filter:" dropdown and the hidden helper block P:AE are retired (`migrate_filter_list` cleared them once; the columns stay hidden and empty). `vantura_churn/fill.py`'s helper machinery (`helper_bounds`, `update_churn_tab`, `update_activation_rates`, `repair_viewing_dropdown`, `hide_helper_columns`) does not run on NDS CHURN any more — the rep list is written by `nds_churn.sheet.write_rep_list` (column = the "Rep Name" header on row 15, default AG; rows from the shared `fill.activation_list_rows`, office total first), the rose "new disconnect" rule covers A16:N98 (`$J16`), borders go on each table (header..last row) + the rep list, and the thread picture is framed by `sheet.report_range` (A1:AH<max of tables / rep list>) — `nds_metrics.build_customer_churn` calls `shot.render(ws, out, report_range)`. LUCY CHURN / Churn - Atef keep the FILTER machinery exactly as before.
- **What breaks if you change it:** adding a column = `LIST_HEADERS` + `LIST_COL_PX` + compute's `T_*` offsets + the number-format column indexes in `table_format_requests` together; the tables start at row 15 (`TABLES_FIRST_ROW`, shared with the rep list) and may not pass row 98 (`TABLES_LAST_ROW`, raises); `tables_last_row` reads column A, so a row with a blank A would shorten the picture; renaming "Disconnect Date" breaks the rose rule's column lookup. Hand run: `rerun nds_churn --dm U046G04P5LG`.

## 2026-11-15 — NDS Order Log: nothing ages off; Not saveable marks drive the activation board

- **No more 60-day drop.** The tab used to drop a line 60 days after its Order Date (`order_log_tab.DAYS_KEPT = 60`). Carlos 11/15: "we shouldn't be removing anything past 60 days, and we should be checking if anything past 60 days ever gets disconnected." Now `DAYS_KEPT = None`: every line stays. Nothing had been dropped yet (oldest line 10/19). Put a number back to restore the age-off.
- **Known limit:** the SaraPlus wireless feed behind the tab is pulled with a 31-day window by order date (`nds_wireless_pull --days`, default 31). A line older than that keeps the status it last had. To watch disconnects past 31/60 days, widen `--days` (10-day sub-windows, one SaraPlus report request each) or read the disconnect off Tableau. Not done yet — Carlos's call.
- **Not saveable → the activation board.** On the SaraPlus "NDS — Activation Rate by Week Ending" board, lines marked **Not saveable** in the tab's *Being worked on* column (W on 11/15; readers resolve by header) leave "Crew Total — lines still pending" and get their own row "Crew Total — not saveable". Activated/cancelled lines never move, so activation rate and cancel rate are unchanged. `order_log_tab.not_saveable_marks()` reads the live tab (DSI # + Line, phone number); `activation_by_week.aggregate(marks=…)` does the counting; an order the feed has forgotten (past the window) still counts its marked lines by DSI #. Tableau twin untouched. Tab unreadable → the row stays blank and the log says so.
- **What breaks if you change it:** renaming the "Not saveable" dropdown value (`order_log_tab.NOT_SAVEABLE`) without the marks reader; marking a line that already activated or cancelled does nothing (by design); a line with blank DSI # AND blank Phone # can't be matched. Verify a run with `logtail nds_metrics "act-week" 14`.

## 2026-11-15 — NDS Revenue Board: tier chip, lines activated ($), rate + churn cards, apps breakdown, sales per rep (main 5d3829bb; apps + deposit pricing c94b6fc8)

Carlos, after seeing the Verizon Revenue Board: "I like how the Verizon one shows what tier they're on right next to the rep's week total. I like the way that it checkmarks some things, and it shows the rep how many lines they have activated this week." Plus: the activated $ in parentheses, the activation rate for the last 4 weeks and the 0–30 day wireless churn (no Airs/BYODs/tablets/watches) top right, the port lines next to the order count, and a sales-per-rep number on the reps card. Previewed by DM; the 06:30 NDS Metrics thread and the two text chains carry it from 11/16.

**What the board shows now** (`automations/nds_metrics/revenue_extras.py`, wired in `run.build_revenue_board` under `FLAGS["tier_columns"]`):
- **TIER chip** right after WEEK TOTAL: T1 = 4 orders, T2 = 5–6, T3 = 7–8, T4 = 9+ orders with a port line this Sun–Sat tier week (the same count as the "N orders" badge and the tier columns); "—" below 4. Colours come from the renderer's tier chips. No bonus math behind it — the week total is still base comp.
- **Name cell** (stacked, same night): first name on one line, the rest under it; the badge "5 orders · 23 apps" (orders = the Sun–Sat tier count, double-tier days counted twice, as before; apps = port phone lines + BYODs + Internet Airs sold this Mon–Sun week — tablets, watches, upgrades and new-number lines are not apps); then two lines of what sold: "19 new phones · 4 BYOD · 0 Air" and "0 Next Up · 4 Premium · 17 Extra · 2 Value" — the payout variables Carlos named. BYOD = the Wireless Installment Plan says BYOD, else (plan still Pending) the NDS CHURN tab's device rule (a bare model code is the customer's own phone). Next Up = the installment plan says 'w/ Next Up' — it reads Pending until the line activates, so the count fills in over the week. Plan = the Package column (Premium / Extra / Value).
- **LINES ACTIVATED this week ($ activated)**: first right-side column. Wireless lines that went Active this Mon–Sun week on SaraPlus's wireless report (line_revenue's activation ledger — the Activation Revenue Overview's "this week" rule), with that rep's this-week posted $ in parentheses (lines + add-ons + tier bonus + Air + Protect, the same number the Activation Revenue Overview posts). SaraPlus rep names are matched to the Tableau names by first-name-anchored word subsequence (middle names free).
- **Cards top right**: ACTIVATION RATE BY WEEK-ENDING = the SaraPlus "Activation Rate by Week Ending" board's rate for the last four WE Sundays (activated ÷ lines sold, oldest first; the current week is included and reads low until its lines activate). 0–30 DAY CHURN · WIRELESS NON-BYOD = the NDS CHURN tab's "All Wireless" box row (nds_churn `product_box`): non-BYOD phone lines activated in the last 30 days that have disconnected — Air, BYOD, tablets, watches and upgrades are out. Read off the day's Tableau order-log csv (`output/nds_metrics/nds_orderlog_<date>.csv`).
- **REPS ON THE BOARD**: "19 · 7.1 sales per rep (134 apps this week)" — this week's apps ÷ the reps listed (renderer hook `extra["reps_extra"]`, shared with the Verizon board). The first version counted orders (40) and Carlos called it "100% wrong — we did 130-something": his sales are apps.
- **OFFICE TOTAL row**: the same badge and two lines with the office sums ("38 orders · 134 apps", "92 new phones · 39 BYOD · 3 Air", "1 Next Up · 43 Premium · 71 Extra · 17 Value" on 11/15) — renderer `office["rep_badge"]` / `office["rep_tags"]`.
- **Pricing fixed with it** (`revenue_extras.board_line_price`): each sold line now prices like the deposit — port $213 ($193 in-footprint, the IF/OOF column), BYOD port $188 ($168 IF), Internet Air $93 (+$30 with auto bill pay), tablet/wearable $25, new-number line $25. Before, every port priced $213 (BYOD was read off the Package column, which never says BYOD) and Air and wearables $25 as "new lines", so the 11/15 week total moved from $28,028 to about $27k.
- Footer note rewritten (tier legend + lines-activated rule + the tier-column legend).

**Best-effort rule**: each extra is computed on its own; a source that can't be read leaves its column/card blank and logs `[nds] revenue board: NOTE ...` — the board itself never waits on it.

**Verify**: `logtail nds_metrics "revenue board" 12` → "lines activated this week N line(s) / $X across R rep(s)", "activation rate card WE m/d p% ...", "churn card D of A non-BYOD phone lines disconnected (0-30)", "N order(s) Mon-today on his owner, R rep(s) on the board". Preview: `rerun nds_metrics --only revenue_board --dm U046G04P5LG`. Re-post a day's copy: `--prune revenue_board --only revenue_board --post` (no --force).

**Round 3 the same night — the Verizon board's look (main 8fac7731; Carlos: "Make those changes with our version equivalent")**: names back on one line (the stacked cell was judged too small on the Verizon board); the breakdown is a WHAT SOLD column on the far right, with the office's lines in that column on the OFFICE TOTAL row; reps + sales/rep sit inside the OFFICE WEEK TOTAL card ("$26,987 · 19 reps · 7.1 sales / rep (134 apps)") and the separate reps card is gone; ACTIVATION RATE BY WEEK-ENDING is one coloured box per week (green 75%+, yellow 65%+, red under — the Activation Rate by Rep's bands); the 0–30 day churn % is coloured by the NDS SOW non-BYOD chart (T4/T3 green ≤ 4.85%, T2 yellow to 7.50%, T1 red from 7.51%); a fourth card, APP MIX THIS WEEK, shows BYOD / Air / Premium / Extra / Next Up as a share of the week's apps. Kept different from Verizon on purpose: Mon–Sun weeks (Verizon Sun–Sat) and no DNQ rule. The Verizon board got the "($ activated)" parentheses on its LINES ACTIVATED column in the same commit (Carlos: "tell Verizon ... and just go ahead and add it into their automation"); `rerun verizon_revenue_preview` DMs it.

**Round 4, the header (Carlos: "get rid of the NDS leaders and the stuff under it ... call the top portion the NDS Revenue Sales Board ... make it blue, add in the AT&T logo up there, and center it")**: the board now opens with an AT&T-blue band — globe + "AT&T" top-left (an inline SVG drawn in `revenue_extras.ATT_LOGO`; swap in the official file by inlining it there), "NDS Revenue Sales Board" centred, the week's dates top-right — and has NO footer: the "NDS LEADERS" label, the legend note and "N reps on the board" are gone. Minutes later Carlos moved the mark into the title and recoloured it: the band is BLACK, the wording AT&T blue, and the centred title reads "AT&T [globe] NDS Revenue Sales Board" with nothing top-left (`revenue_extras.BRAND`, renderer brand hook with its new `fg` colour). It rides the renderer's `brand` hook that the Verizon board uses; the B2B/BOX boards keep the dark header and footer.

**Tableau export trap found the same night**: the mini's pull of the NDS-SN order log carried a new column, "Order date to Install Date Days", and the board's order-date lookup (`cols.need("order date", "sp.order date")`) substring-matched it first — an empty column, so every line was skipped and the board would have been blank. `Cols.find` now takes the tightest matching header ("sp.Order Date (copy)"); `test_cols_find.py` pins the live header. Lucy 2's own pull had not grown the column yet; if a view ever gains a field whose name contains a lookup word, this is the place to look.

**What breaks when you change X**:
- Rename the SaraPlus rep names or the Tableau "Rep" column format → LINES ACTIVATED shows 0 for the unmatched reps (the log's "across R rep(s)" count drops). `revenue_extras.match_rep` is the join.
- Move the Tableau csv or change `LOOKBACK_DAYS` → the churn card reads a different window (it wants ≥ 30 days of activations in the file).
- `activation_by_week.aggregate` / `line_revenue.replay` signature changes → the rate card or the lines column go blank with a NOTE; the board still posts.
- The renderer (`vantura_revenue_board/run.py`) keys: `tier_chip`, `reps_extra`, `cards`, `headers` — B2B/BOX boards pass none of them and render as before; the Verizon board passes `cards`/`reps_extra`/`no_next`.

## 2026-11-17 — NDS CHURN: Pending is a column in the top-left box (main cfef1490)

- **What (Carlos):** "For the table at the top left the pending orders should be another column not another row. The order of the columns should be disconnected - activations - pending." The box is now one row per product — All Orders / All Wireless / BYODs / Air / Internet — under `Product | Disconnects | Activations | Pending | Churn % | 0-30 Day Activation Rate | 31-60 Day Activation Rate`, A4:G9. It was eight rows in A5:F12 with a "… Pending" row under the first three products. Air and Internet show their pending count too, so the column adds up to All Orders. Same numbers as before (`compute.product_box`, `compute.box_activation_rates`); only the layout moved. Churn % = Disconnects ÷ Activations (`=IFERROR(B5/C5,"")`).
- **The tier charts moved one column right.** The seventh box column took the blank column G that used to separate the box from the charts, so the charts now sit in I4:N10 with H as the blank column: Non-BYOD in I:K, BYOD in L:N. The BYOD chart's separate `OOF $` / `INFP $` columns became one `OOF / INFP $` (e.g. `$203 / $183`), the way the Non-BYOD chart always showed them. Rows 10–12 under the box and 11–12 under the charts are blank.
- **Mechanics changed:** rows 4–12 of A:N ("the top block") are written by ONE atomic batch every run — `sheet.write_top_block(ws, box, rates, ts)`: `top_block_cells` builds every cell's value + format, `top_block_requests` unmerges whatever sits in the block, writes all 9×14 cells with `updateCells` (fields `userEnteredValue,userEnteredFormat`, so nothing of an older layout survives), merges the two chart titles (I4:K5, L4:N5) and moves the two Churn % gradient rules onto the Churn % column (wireless ramp E5:E7, Air ramp E8 — `churn_colour_requests`). `write_product_box`, `write_box_rates`, `write_tier_tables`, `_unmerge_box_rates` and `_retarget_churn_colours` are gone, and so is the copy-the-first-row formatting they relied on.
- **What breaks if you change it:** anything typed or formatted by hand in A4:N12 is wiped on the next run (the block is fully code-defined). A new box column = `BOX_HEADERS` + the `BOX_*` column indexes; the box may not pass column G or the charts lose their blank column (`TIER_COL0 = BOX_W + 1`, and the module asserts the charts end on N). A new product row = `BOX_ROWS` (the box has room down to row 12; the status line starts on 13). The colour rules are found by a cell each has always covered (`_WIRELESS_RAMP_AT` / `_AIR_RAMP_AT`) — if the Churn % column moves again, add its new cell there or the rules stay behind. `--setup` on the live tab no longer touches rows 4–12 or re-applies the LUCY CHURN theme (the theme paints four-column chart titles and would spill past N). Tests: `automations/nds_churn/test_top_block.py`.
- **Not changed:** the three rolloff tables, the rep list, the status line text, the counting rules, the reconcile gate, the thread section (`customer_churn` shoots the tab as before, so the thread and the texted copy carry the new box from the next morning's run).

## 2026-11-18 — Teams box: new teams show up on their own, ranked by Apps; Secondary Status (Floater) column on the NDS board

Carlos, four asks in forty minutes: "on the NDS sales board i added in new team names but theyre not populating on the teams board" → "i need a column for a secondary status ... so that i could have some people listed as floaters and i don't want them counting towards the total head count, leaders, entry level, in training and sales average. we can add it right next to leadership status" → "bautista shouldnt be part of the teams board ... sort by most apps to lowest" → "do something to make it easier to look at".

**What was wrong.** The Teams — Current Week box (NDS `B42:H…`, Verizon `B35:H…`) was rebuilt only by the simple `onEdit` on a Team (O) / Campaign (L) cell. The NDS box had not been rebuilt since 11/10: it still listed Akatsuki / Bautista / Cynthia / Generational while column O held eight other teams. `onEdit` never sees a team renamed inside the dropdown rule or a value written by a script or the API, and it fails silently (empty `catch`) for anyone who cannot write column B — the box's labels sit in column B, which is protected ("Rep names — add people ONLY via Alphalete menu > Add", 4 editors), and the rebuild's first write is B42. Which of these it was this time is not known.

**How the box works now (Code.gs + RollWeek.gs, pushed through the Apps Script API, HEAD; final push 11/18 12:02, eight in all).**
- **Team names are rank formulas.** Each name cell is `=IFERROR(INDEX(LET(tms,UNIQUE(FILTER(O,(L=camp)*(O<>"")*(B<>""))),aps,MAP(tms,LAMBDA(tm,SUMPRODUCT(…Apps…))),SORT(tms,aps,FALSE,tms,TRUE)),k),"")` — the k-th team by Apps, most first, ties by name. The order, and a renamed team, follow the board live with no script. The stat formulas point at `$B<row>`, so a whole row re-sorts together. The script only decides HOW MANY rows there are.
- **`_teamsBoxStale(board)`** (one read of the tab's top-left corner, 200 rows × 20 columns — reading the whole data range made the first hourly check take 30 s, stamp `2026-11-18 12:01:14 check=30008ms`): are the teams on the board the names in the box, and does the box still end with "Unaccounted For"? **`teamsBoxSync()`** rebuilds the boards that fail that test. Nothing is written when they pass.
- **Who calls it:** `onEdit` on a Team/Campaign cell (asks `_teamsBoxStale` first — an ordinary team change costs one read, not a rebuild); the every-minute `processAddQueue` trigger once an hour, on the hour; the daily `rollDailyNormalize` (it runs inside the `checkNameClashes` trigger, ~6:45am). `recolorRepList(e)` carries the same hook but NO trigger calls it (see the trigger list below).
- **`_refreshTeamsBoxOn(board)`** writes the whole box with ONE `setValues` (labels + formulas), plus the Term? column and, only when the number of rows changed, two format copies and a clear. It keeps the box's own look: team rows take the formats of the first two existing team rows in turn (the banding), the last row takes the old "Unaccounted For" row's. The plain script style is only used on a box with no rows.
- **Head-count exclusions are in the generator:** Head Count / Leaders / Entry Level / In Training carry `*($AR$5:$AR$N=0)` when row 4 has a "No HC?" header (the 11/10 hidden "Not in Head Count" list) and `*($Q$5:$Q$N<>"Floater")` when it has a "Secondary Status" header. Apps does not, so their sales still count; Sales Avg by Rep = Apps ÷ Head Count follows.
- **Heartbeat:** every timed run stamps spreadsheet developer metadata (document-visible, nothing on any tab): `teamsBoxSyncAt` = `yyyy-MM-dd HH:mm:ss check=<ms>ms rebuilt=<n>` (Central time, how long the check took, how many boxes it rebuilt) and `teamsBoxSyncLog` = the last 30 of those, newest first. Sheets API `developerMetadata:search` with either key answers "is the timed check alive" and "how slow is the workbook for a script". The trigger fires at :42 past the minute, so a stamp at 12:00:55 means the workbook took ~13 s to answer. Seen 11:32:22 and 11:41:15 on 11/18 (earlier ten-minute versions).

**Secondary Status column (NDS Sales Board only).** Column Q — empty, already inside the board's grid and filter (`B4:Q30`) — is "Secondary Status": header like P4, cells like P's, a "Floater" dropdown on the rep rows (not strict; made by the API, so it is an arrow dropdown, not a chip). No column was inserted, nothing moved. A Floater is left out of Total Head Count, Leaders, Entry Level, In Training and the Sales Avg denominator; their sales still count in Apps. New rep rows get the dropdown and an empty cell on their own (the add / promote code copies row 5 through AE and then clears O:Q). The Verizon board has no such column (its Q is "Approved").

**The look (NDS box), applied through the Sheets API and kept by the script:** total row bold on #DDEBF7, team rows banded white / #EEF3F9, Apps bold, "Unaccounted For" italic grey, Sales Avg one decimal. No heavy line under the total row on purpose — a row's borders travel with its format when it is copied down.

**What went wrong on the way (11/18 10:52–11:38), so it is not repeated.**
- The first versions rebuilt the box cell by cell (~90 `setFormula` calls) on EVERY Team edit. Carlos was re-assigning teams at that moment; this workbook answers a script slowly when busy (a `processAddQueue` run that does nothing took 10–38 s, and still ~9 s an hour later with nobody editing; freezing the rank formulas to plain text for four minutes did not change that, so they are not the cause — why the workbook is that slow is an open question, handed off as its own task), so those rebuilds ran into the 30 seconds a simple `onEdit` gets — eight "Timed Out" `onEdit` runs between 11:27 and 11:37, and every other trigger slowed down with them. Fixed at 11:38: `onEdit` asks `_teamsBoxStale` first, and a rebuild is one `setValues`.
- I had hooked the timed check onto `recolorRepList` and waited for it: that trigger does not exist. **Read the Triggers page before relying on a trigger.**

**The project's triggers on 11/18 (script.google.com → the project → Triggers; all owned by Carlos):** `processAddQueue` (time, every minute), `resetOffList` (daily ~4:20am), `refreshTerminatedLead` (~5am), `dailyFieldStatus` (~5:30am), `checkNameClashes` (~6:45am, calls `rollDailyNormalize`), `rollCallNewWeek` ×2 (Mondays), and two spreadsheet on-edit triggers, `vzOnEdit` and `onWeekPick`. There is no `recolorRepList` and no `rollDailyNormalize` trigger. The Triggers and Executions pages (function, start, duration, Completed / Timed Out) are readable in Carlos's Chrome signed in as him; the API token (`script.projects`) can push and read source but cannot run a function or read that log.

**What breaks if you change it.**
- Any `onEdit` work must fit in 30 seconds on a slow workbook: batch writes (`setValues`), and ask a cheap question before doing anything. Time-driven work is rationed per day: keep the hourly check to a couple of reads.
- Rename the headers "Secondary Status", "No HC?", "Term?", "Total Head Count", "Apps", or the value "Floater" → the generator or the exclusion stops matching (they are matched by text).
- A hand-typed team name or number inside the box is overwritten on the next rebuild; hand formatting survives as long as the box keeps a team row and its Unaccounted For row.
- Until a rebuild, an ADDED team pushes the lowest-ranked one out of the box (the rows stop adding up to the total row — that is the tell), and a REMOVED team leaves a blank row above Unaccounted For. `onEdit` fixes both at once when the editor can write column B; otherwise the hourly check does.
- The local dry run (macOS `jsc` with a mocked sheet) stores a formula's text as the cell's value, so after a simulated rebuild it calls the box stale. Real Sheets returns the computed names.
- Patcher, the new function text, the script before and after, and both boxes as they were: `~/.config/recruiting-report/backups/` (`patch_teams_box_gas_2026-11-18.py`, `teams_tail_2026-11-18.js`, `vantura_script_before_2026-11-18.json`, `vantura_script_after_2026-11-18.json`, `teams_box_backup_*_2026-11-18.json`).

### 11/18 evening — floaters in the "% on the Board" table; on-the-spot for every editor

- **"% on the Board" (NDS only):** Carlos: "Floaters also shouldn't be counted on the percentage on the board table unless they get a sale." All Reps and Reps Worked (rows 35-36, C:H over day columns E:J) carry `*(($Q$5:$Q$N<>"Floater")+($Q$5:$Q$N="Floater")*ISNUMBER(day)*(day>0))`; % On Board's subtraction of new-rep zeros carries `*($Q$5:$Q$N<>"Floater")` so a floater's zero is not taken out twice; Rolled a Zero and On the Board are unchanged; the footnote says "Floaters (Secondary Status) count only on a day they sell." Effect that night: All Reps 24 → 22 (two floaters carrying X marks). Keep the six day columns on the same formula shape — `sales_board_fixer.check_day_rows` resets an odd day to the majority. The morning "NDS % On Board" picture is a shot of the block (it stops above the footnote) and follows by itself. Before-state: `~/.config/recruiting-report/backups/pct_block_before_floaters_2026-11-18.json`.
- **On the spot for every editor (script push #9, 19:01):** `vzOnEdit` — the installable on-edit trigger, which runs as Carlos whoever is typing and has no 30-second cap — calls `_teamsBoxAfterEdit(e)` in a `finally`: when the edit touched the Team or Campaign column of a board, `teamsBoxSync()` runs under a script lock (`_teamsBoxLocked`, 15 s). The simple `onEdit` asks through the same lock, so only the first of the two rebuilds. The hourly check stays as a backstop for values written by a script or the API.
- **Sorting:** the rank formulas re-sort the box the instant a sale or a team changes. No timer is involved.
- **Heartbeat that afternoon** (`teamsBoxSyncLog`): the hourly check ran every hour from 12:00 to 19:00; `check=` 4.3-13.8 s once it read only the corner (30 s before). A script run costing 5-15 s is normal for this workbook, and the triggers were still running at 7pm.

## 2026-11-19 — Daily Update tab re-layout (done in another chat, audited here)

Carlos asked a different Claude chat (on the laptop) for this, then asked this one to "check and make sure nothing was broken and everything was done right". That chat changed the sheet and pushed a docstring note (`c392528b`); it did not know this README exists (it looked for a Google Doc).

**The layout now (28 columns, A:AB, frozen through Name = J):**
`A Status | [B Secondary Status, C Notes, D Day 0 - in Office Start Date, E Day 0 Attendance] | F Campaign | [G Day Zero Date, H 1st Paycheck, I Training Bonus] | J Name | [K Email, L Phone #, M Job Ad] | N 2nd round Interview Date | [O 1st Round, P 2nd round, Q 2nd show/no show, R Offered, S BOB Status] | T Orientation Date | U Week Ending | V Classroom Retention | [W BGC/Saraplus Logins … AB Headshot]`. Brackets = a collapsed column group; its + sits on the column to its LEFT (Status, Campaign, Name, 2nd round Interview Date, Classroom Retention).

- **What moved:** Job Ad (was T) into the Name group, right of Phone; Week Ending (was M) to the left of Classroom Retention; the five columns 1st Round … BOB Status grouped under the 2nd-round date; a NEW column G "Day Zero Date".
- **Day Zero Date (G)** is a header array formula: `={"Day Zero Date";MAP($T$2:$T,LAMBDA(od,IF(LEN(od)=0,,IFERROR(WORKDAY(od,1),""))))}` — the next business day after Orientation Date (Mon → Tue, Fri → Mon). Never type in column G: one typed value blocks the whole column. The other chat had capped it at row 4000 (the tab was at row 3,136 and grows ~17 rows a day); made open-ended here.
- **Week Ending (U)** kept its header array formula; it now reads the 2nd-round date from column N. Same rule as before: never type in it.
- **Verified:** 3,124 named rows, no error cells; Day Zero = next business day on all 1,079 rows with an orientation date; Week Ending = that week's Sunday on all 3,093 rows with a 2nd-round date; filter, filter view, sort history, dropdowns and the frozen columns followed their columns. The only other tab with formulas into this one is `Leaders Retention` (helper block AA2:AI2) — Sheets re-pointed them and they read correctly. The bound script's "Add New Starts to Roll Call" finds Name / Orientation / Classroom Retention / "2nd round" by header and uses Status = column A and Campaign = column F by position, both unmoved.
- **Broken by the move, fixed here (main `89c11456`):** `vantura_board_audit._load_activity` read the name at `r[8]` (column I). With Name now in J it keyed every rep's Daily Update status by the Training Bonus column, so the audit said "Daily Update says nothing" for everyone and `ROLL CALL STALE` could not fire. It now uses `du_layout.resolve` like every other reader (`daily_update_fill`, `vantura_du_status`, `vantura_contacts_sync`, `nico_roster_check`, `rc_contact_sync.wrapup`, `team_tree` — all by header already).
- **Left for Carlos to decide:** the tab already had a hand-typed "Day 0 - in Office Start Date" (column D, hidden in the first group). On the 558 rows that have both, the formula agrees on 460 and differs on 98: holidays (Memorial Day 5/25 and Labor Day 9/7 — the formula says Monday, the VA typed Tuesday), people who started a day late, and a few typos. `WORKDAY` takes a holiday list if he wants them skipped.
- **Known limit, not new:** Orientation Date and most 2nd-round dates are TEXT with no year ("8/31"). Sheets reads them as this year, so rows from 2025 get this year's weekday, and every weekday-based value (Day Zero, Week Ending) will re-read itself on January 1.
- **What breaks if you change it:** any reader that indexes this tab by position. Use `recruiting_report/du_layout.resolve(header_row)`; a new column anywhere left of a reader's column shifts it.

## 2026-11-19 — Holidays tab; Day Zero skips major holidays

- Carlos: "Major holidays yes." New tab **Holidays** (right after Daily Update; columns Date / Holiday / note), 18 rows: New Year's Day, Memorial Day, Independence Day (observed), Labor Day, Thanksgiving, Christmas (observed) for 2025, 2026 and 2027. Add a row to skip another day (the day after Thanksgiving is NOT on it). The Daily Update's G1 formula is now `={"Day Zero Date";MAP($T$2:$T,LAMBDA(od,IF(LEN(od)=0,,IFERROR(WORKDAY(od,1,Holidays!$A$2:$A$200),""))))}` — 200 rows of the list are read, so the list may grow to row 200.
- Verified on all 1,079 rows with an orientation date: 33 rows moved (Memorial Day 14, Labor Day 15, the day after Thanksgiving 4 — those four are 2025 rows read as 2026, see the no-year note above). Agreement with the hand-typed "Day 0 - in Office Start Date" (col D) went from 460/558 to 478/558; the remaining 80 are late starts and typos.
- **What breaks if you change it:** renaming or deleting the Holidays tab makes every Day Zero `#REF!` (the IFERROR then shows blank); a text value in Holidays!A is ignored by WORKDAY; the bound script's `cleanupTabs` menu item (never run) would delete this tab along with every other tab not on its stale KEEP list.

## 2026-11-19 — WEEK 1–4 + TERMINATED block under the Teams box (NDS Sales Board, from B56)

Carlos: "tables that show the week 1s ... week 1 starts on day 0 ... week 2s ... Monday through Saturday roll call and their attendance ... mirror what's over on the roll call sheet ... a week 3 table ... who did the second round and who is the designated trainer." Then, on the first version (three fixed 12-row tables): "I wanted to look more the way that the roll call looks ... the line, the wording, and the dropdown options ... add in the attendance for the prior week ... a note section that shows what days it is that they showed up ... a lot of extra rows that just aren't needed, so it needs to constantly be adjusting to however many new certs there are."

- **What it is now:** ONE formula in **B56** that spills the whole block — WEEK 1 title row (`WEEK 1 · 11/16 – 11/22 · 5 reps`), the header row, one row per rep, a blank row, WEEK 2 …, WEEK 3 …, WEEK 4, then a TERMINATED table — so it is exactly as tall as the people in it (rows 56–93 on 11/19; it may use rows down to 220). Later the same evening Carlos asked for four weeks, for people to disappear the week after they are terminated, and for the 2nd Rounder column to become lifetime sales. No footnote: the title text has to fit in column B (the spilled cells beside it hold "" and block overflow), so everything in column B is kept short. Columns B:N: Roll Call (the Roll Call's spelling of the name) | Status | Day 0 | Mon | Tue | Wed | Thu | Fri | Sat | Date Gone | Prior Weeks | Total Sales | Trainer. Wording and colours are the Roll Call's: navy header, orange Status header, Arial 10 centred, status chips (New Start #BDD7EE, Active #C6EFCE, Terminated #F4B0B0, Inactive #D9D9D9), mark colours (Here #C6EFCE, Off #D9D9D9, STF / Late #FFEB9C, NoShow #FFC7CE, T #F4CCCC, Terminated #F4B0B0, CR #DDEBF7, Not Here #FCE4D6) — all conditional formats over B56:N220, keyed on the text in column B for the title / header / note rows. Columns L (235 px), M (200 px) and N (160 px) were widened for the note and the names.
- **Who is in which table:** Daily Update rows with Campaign = NDS, Classroom Retention = "Showed To CR" and Day Zero Date inside the week — WEEK 1 = the Mon–Sun board week in B2, WEEK 2 = the week before, WEEK 3 = two weeks before, WEEK 4 = three weeks before. Someone let go stays listed (Terminated, Date Gone) through the week they were let go and disappears from the next week on — Roll Call status Terminated AND Date Gone before the current week's Monday (a Terminated row with no Date Gone keeps showing); orientation no-shows never appear. The count in each title is the rows shown, after that drop. A week with nobody shows one line "no week N reps".
- **Prior Weeks:** WEEK 2 rows say `Wk 1: Mon Tue Wed Thu Fri Sat` — the days that rep was Here / Late / STF / CR in the archived week (RollCallData key `<Roll Call name>|<WE m.d>`); WEEK 3 rows carry two lines (Wk 2 then Wk 1), WEEK 4 three (joined with CHAR(10), column L wraps); "none" = a week they never showed, "no roll call" = no archived row. WEEK 1 shows "—".
- **Total Sales (column M):** `5 orders · 28 apps` — everything the rep has sold under their own login since they started, off the **NDS Order Log** tab (every wireless line since 10/19, nothing ages off): apps = lines of Type Port or New whose Line Status is not Cancelled and whose Device is not a tablet / watch / hotspot (the Sales Board's own unit rule: no upgrades, tablets, wearables); orders = distinct CUSTOMERS among those lines (Carlos 11/19: "the order count is how many customers, and then the apps is how many lines the order had") — keyed by BAN, or by the customer name when a line has no BAN yet; two accounts on the board carry two orders each, so this is one less than the order-number count for those reps. Internet Air lines are not on that tab, so an Air does not count here. Rep names on the Order Log are SaraPlus full names ("Stefany Michelle Zaldivar Justiniano", "Nicholas Paul Smedra"), so the match is: the Order Log name starts with the Roll Call first name AND contains the Roll Call last name as a word ("Nick" matches "Nicholas …", both "Yahir Lopez" and "Yahir Uriel Lopez" count for Yahir). The Order Log columns are found by header (Rep, Wireless Order #, Type, Line Status, Device), so that tab's columns may move.
- **TERMINATED · last 4 weeks (the fifth table; Carlos: "anyone that has been labeled terminated in the last 4 weeks ... just their name, the trainer, total orders they've done, and days lasted"):** every Roll Call row with Status = Terminated, Campaign = NDS and a Date Gone inside the four board weeks (we−27 … we) AND proof they were around in those weeks — a mark on their live Roll Call row, an NDS row on the Daily Update (the label exists only since 10/3/2026), or marks archived in RollCallData for one of the three previous weeks (`rcdHas`) — newest first, one row per person (two Roll Call rows with the same first + last name — "Zayra Estephany Finlinson" / "Zayra Finlinson" — show once). Columns B:E only (Carlos: "it doesn't need all the columns for Monday through Saturday"): B Roll Call | C Days Lasted | D Total Orders | E Trainer; F:N of those rows are spilled "" with no format, so the table reads as four columns. Its navy band and header stop at E because the two navy rules carry a column test (`=AND(LEFT($B56,10)="TERMINATED",COLUMN(B56)<=5)` and `=AND($B56="Roll Call",OR($C56<>"Days Lasted",COLUMN(B56)<=5))`), its borders are 4 wide (script and apply script: a title starting TERMINATED → width 4; the stored extent marks it `80-93:4`), C:E wrap (the two-line headers, and a long trainer name wraps in E's 88 px). Total Orders is written as TEXT because column D carries the week tables' m/d date format — a number 2 would show as 1/1. Days Lasted = the Roll Call's own number (its script: Date Gone − the cohort's week-ending date, blank when negative) and, when that is blank, Date Gone − Day 0 off the Daily Update, whole days, never below 0. Total Orders = the same customer count as Total Sales. Trainer = the Roll Call's, else the board's Trainer column if the rep still has a board row — blank when neither has one (most terminated rows: the Roll Call clears it). Title regex in the script and the apply script: `^(WEEK \d|TERMINATED)`.
- **Borders:** a spill cannot carry borders, so the bound script's `weekTablesTidy()` draws the thin grey grid around each table's current rows and clears the rest — after any edit to a board, the Roll Call or the Daily Update (`_weekTablesAfterEdit`, hooked into `vzOnEdit`, under the script lock) and hourly from `processAddQueue`. It keeps the block's extent in developer metadata `weekTablesExtent` and writes nothing while that is unchanged. Pushed 11/19 17:50 (push #11).
- **The formula** is built by `week_block.py` (`~/.config/recruiting-report/backups/`); `week_block_apply.py` re-applies it, draws today's borders and stamps the extent. Shape: outer LET (board week off `$B$2`, the `key` lambda = first + last name token, the Roll Call columns, the Daily Update columns, RollCallData, a `showed(name, weekEndingDate)` lambda, a `sales(name)` lambda, a `tbl(k)` lambda that builds one table: mask → FILTER → XMATCH into the Roll Call (newest row first) → `pick(column)` → `keep` (the termination rule) → FILTER → SORT by Day 0 then name) → `{tbl(1);blank;tbl(2);blank;tbl(3);blank;tbl(4);blank;term}`.
- **Formula rules learned the hard way (same evening, five rounds of #ERROR! / #NAME?):** (1) a LET name must not look like a cell reference — `d0`, `rnd0`, `rnd2`, `r2`, `r0` (column RND / R, row n) are parse errors — and must not be a function name (`sec`, `rows`, `days`); (2) LET names are CASE-INSENSITIVE: `rk` and `rK`, `rNm` and `rnm` collide and the whole formula is `#NAME?`; (3) a column range used inside a LET value is evaluated in scalar context (implicit intersection), so a whole-column mask must be wrapped in `ARRAYFORMULA(...)` or it is 0 everywhere; (4) IFERROR hides none of these — test without it, in scratch cells far to the right (AX110+), then clear; (5) Daily Update dates carry no year, so a date window must also filter on something only current rows have (Campaign = NDS, a label that exists since 10/3/2026) or 2025 rows with the same month/day appear; (6) `COUNTUNIQUE(FILTER(...))` with no match is 1, not an error — the #N/A counts as one unique value — so guard with the count first; (7) a Date Gone written by the script is a date-TIME, so subtract `INT()`s or days come out as 0.4257; (8) when splicing a new LET name into a builder string, check the comma on BOTH sides — a dropped comma is a bare `#ERROR!` with no hint.
- **Guards in the bound script:** `reanchorBoardStatRanges` stops its read-and-write-back above the first "WEEK n" title in column B (writing spilled cells back as values would freeze them and break the spill; push #10); the Teams box's empty-box fallback clears only its own rows. The Teams box has room for 11 teams (rows 44–54) before it reaches B56.
- **What breaks if you change it:** typing anything in B57:N220 breaks the spill (#REF! in B56) — delete the typed value to restore; the Roll Call is read BY POSITION (B status, E name, G trainer, H:M Mon–Sat, N Date Gone) and the Daily Update too (F, G, J, P, V) — inserting a column left of those shifts them, then rebuild from `week_block.py`; the title must keep starting with "WEEK " (the script's tidy routine and the re-anchor guard key on it; a row starting "Note:" is left outside the borders if one is ever added); RollCallData keys must stay `<name>|<m.d>`; moving the block means changing `WEEK_TOP` in the script and the 56s in `week_block.py` together.

### 11/19 night — last year's people re-added as this year's new starts (found from the Terminated table)

- Carlos: "Some of those were here forever ago and terminated forever ago." Two of the twelve were from 2025: **Austin Palacio** (on the board Dec 2025 – Jan 2026 per WeekData; Daily Update row "B2B ATT", orientation 11/13) and **Robert Polanco** (Daily Update "B2B ATT", orientation 11/06, no sales, no attendance). Both sat on this year's Roll Call (row 15, WE 11.22, Terminated 11/16; row 489, WE 11.15, Terminated 11/9) with campaign NDS. The other ten were checked against RollCallData, WeekData and the Daily Update and are right (Ruby Flores started in August but worked through 10/29 and was terminated 11/2).
- **Cause:** the bound script's menu "Add New Starts to Roll Call" (`addNewStartsToRollCall`) picks Daily Update rows by orientation month/day (`_mdNorm`) — the dates have no year, so a 2025 row with the same date and "Showed To CR" matched, and "B2B ATT" maps to NDS. **Fix (push #14, 19:02):** it now skips Daily Update rows whose Status is "Not Active" (every 2025 row is). Someone from this year who quit before the menu ran is skipped too; the week tables still list them from the Daily Update with "not on Roll Call".
- **Table rule:** see "proof they were around" above — Austin and Robert no longer show.
- **The two Roll Call rows:** Carlos: "Not deleted but they should be where every other terminated person is at." Robert's row was already in the Roll Call's big Terminated block (rows 20–490, left by the last sort on Status); Austin's row (15, up with this week's new starts) was moved there with `moveDimension`, right after Robert's — now rows 488 (Robert) and 489 (Austin). Their Week Ending (11.15 / 11.22) and Date Gone (11/9 / 11/16/2026) are still the values stamped by the bad re-add.
- The same no-year matching exists in Lucy's `daily_update_fill.rollcall_sync` (±14 days by month/day), but that one is owner-boards only (`NO_ROLLCALL_SYNC` keeps the Vantura master on the manual menu).

## 2026-11-19 — The Daily Update's dates carry their year

Carlos: "Add the year if that makes things easier." It did: every no-year bug of the day (last year's people re-added as new starts, Day Zero and holidays read in the wrong year, the Terminated table's ghosts) came from 'm/d' dates.

- **Orientation Date (T)** was plain TEXT 'm/d' on 1,067 rows (12 were real dates). Each got its year from the row's own evidence, by vote: the 2nd-round date (a real date on 2,931 rows; orientation 0–21 days after it), the hand-typed "Day 0 - in Office Start Date" (orientation 0–10 days before it) and the 1st Paycheck (7–35 days after it). A year typo in one field is outvoted (Maya Ramirez's 2nd round reads 12/26/2026; Alan Garcia's Day 0 reads 1/2/2025). Result: 1,025 → 2026, 42 → 2025 (Austin Palacio 11/13/2025, Robert Polanco 11/6/2025, Kenyatta Walker, Rajiv Yalamanchili …); 3 rows with no other date took the latest past date (Hayden Bright 9/28, Jacqueline Varela 7/1, Jorge Loya 8/23 → 2026). Checked against the hand-typed Day 0 on 547 rows: 531 within 0–10 days. Written as real dates (RAW serials), after checking no row had moved; the original values are in `~/.config/recruiting-report/backups/daily_update_orientation_before_years_2026-11-19.json` (by row, with the names); the script is `du_years.py` there.
- **Formats:** Orientation Date, 2nd round Interview Date and Day Zero Date show `m/d/yyyy`. Orientation's TEXT format is gone, so an orientation typed as "11/20" now becomes 11/20/2026 by itself. The 162 2nd-round dates that are still 'm/d' TEXT (written by the nightly fill; 160 have nothing to date them by) were left as they are.
- **Effects checked:** Day Zero recomputed — 49 rows now land in 2025 and use 2025 holidays; Week Ending already worked off real 2nd-round dates; the NDS Sales Board WEEK block and Leaders Retention compute with no errors (Leaders Retention's AG helper, `TRIM(T)&""`, now holds the date serial as text for dated rows — its formulas only test it for non-empty, so the counts are unchanged); the 20 "Orientation Scheduled" rows are all real 2026 orientations.
- **New rows keep the year:** `daily_update_fill` (main `2e60c78a`) writes the master's 2nd-round and orientation dates as `m/d/yyyy` with USER_ENTERED (real dates); an AppStream orientation without a year takes the year that puts it on or after the interview; the status step honours a written year — all behind `YEAR_DATES = {"Carlos Hidalgo"}`. The owner boards are byte-for-byte unchanged ('m/d' text, RAW, same parsing). Tests: `automations/daily_update_fill/test_dates.py`.
- **The Roll Call menu:** `addNewStartsToRollCall` now builds the target with its year (the one nearest this week's Monday) and skips an orientation date more than 3 days from it (push #15); with the "Not Active" guard from earlier, last year's same-date rows can't match.
- **What breaks if you change it:** typing an orientation date with a leading apostrophe or turning the column back to TEXT format brings back no-year text; the week block and the menu then fall back to the campaign / Not Active guards. A reader that parses 'm/d' with this year still works (the year is ignored) — `vantura_du_status`, `rc_contact_sync`, `team_tree` (honours the year), `vantura_contacts_sync` (shows the text).

## 2026-11-19 — the same WEEK 1–4 + TERMINATED block on the Verizon Sales Board (from B50)

Carlos: "Now let's go ahead and add this to the Verizon sales board so Daddy Nico is happy."

- **Where:** one spilled formula in **B50** of the Verizon Sales Board (the tab was extended to 225 rows so the block has room; it may use rows down to 214). Title/header bands are red `#B00000` instead of navy; everything else looks and behaves like the NDS block.
- **Same formula, five swaps** (`week_block_vz.py` runs `week_block.py`'s builder and swaps): Daily Update Campaign `"VERIZON"` (NDS block: `"NDS"`), Roll Call Campaign `"Verizon"`, sales off the **Verizon Order Log** (no BAN there, so an order = a distinct Customer; apps = its lines by the same unit rule), and the board's name/campaign ranges `'Verizon Sales Board'!$B$5:$B$33` / `$M$5:$M$33`.
- **Trap found building it:** the board ranges first ran to `$B$200`, which includes B50 itself — a spill that reads its own anchor is a circular `#REF!`. Keep any board range above row 50.
- **Borders:** the bound script's `weekTablesTidy()` now walks a list, `WEEK_BLOCKS = [{NDS Sales Board, top 56, key weekTablesExtent}, {Verizon Sales Board, top 50, key weekTablesExtentVZ}]` (push #16), on the same triggers as before (after an edit to a board / the Roll Call / the Daily Update, and hourly from `processAddQueue`).
- **11/19 check:** WEEK 1 6 reps, WEEK 2 1, WEEK 3 1, WEEK 4 1, TERMINATED 22 — every terminated name has Date Gone in the four weeks and attendance there, no errors.
- **Rebuild:** `python3 week_block_vz.py` (re-applies the formula; `--setup` also adds rows, formats, conditional formatting). Copies of both builders: `~/.config/recruiting-report/backups/`.

### 11/19 late — terminated people sit at the bottom of their week's table (both boards)

- Carlos: "once someone is terminated, they're always at the bottom of the roll call list for the week that they're on? Angela should be under Stefany."
- Each WEEK table now sorts by **gone first-key** (`goneFlag` in `TBL` = Status "Terminated" OR a Date Gone on the Roll Call), then Day 0, then name. Re-applied to the NDS block (B56) and the Verizon block (B50) with `week_block_apply.py` / `week_block_vz.py`; no errors. Formulas before the change: `~/.config/recruiting-report/backups/week_blocks_before_term_sort_2026-11-19.json`.
- A Date Gone counts as gone even when the Status still says New Start/Active (Susana Hernandez on 11/19 had T Thu–Sat and Date Gone 11/19 but Status New Start).

### 11/19 late — a T mark does NOT change the Roll Call status (Susana Hernandez)

- What a T does today: typing T in a Roll Call day cell (or on a board day cell) runs `markGone` — it stamps **Date Gone** (with the time) and Days Lasted, nothing else. The Status column becomes "Terminated" only when someone picks it by hand, or at the weekly cleanup (`terminateGoneRollCall`, which terminates every row that has a Date Gone).
- So a rep T'd mid-week keeps "New Start"/"Active" until the next weekly flip. Carlos: "Susana's status still shows as 'new start,' but she should be marked as 'terminated.'" Fixed by hand: Roll Call row 10 (Verizon, WE 11.22) Status → Terminated (backup `rollcall_susana_before_2026-11-19.json`); she now shows Terminated in Verizon WEEK 1 and in the TERMINATED table (2 days, 0 orders).
- Not changed: making T flip the status right away (asked Carlos 11/19). Careful if you do — the Roll Call `onEdit` returns early for any row whose Status isn't Active/New Start, so flipping the status INSIDE `markGone` would stop that same edit's T from reaching the board.

### Why someone isn't on the week tables (Brianna, 11/19)

- The four week tables go by **Day 0**: WEEK 1 = Day 0 in this board week (Mon–Sun), WEEK 2 the week before, and so on to WEEK 4. Someone whose Day 0 is **five** weeks back is past WEEK 4 and drops off them.
- **Brianna Belen Contreras** (NDS): Day 0 **10/19** = week 5 this week. Elisa Diaz-Garcia's Day 0 is **10/27**, one week later, so Elisa is WEEK 4. Brianna, terminated 11/18, shows as the first row of the TERMINATED table (26 days lasted, 2 orders, trainer Nick Smedra).

## 2026-11-19 — Week-table texts to NEW A Players, Mon–Fri: WEEK 1 at 10:45, WEEK 1–4 at 11:30 (AT&T + Verizon)

Carlos: "every day at 10:45 a.m., Monday through Friday, I want a screenshot like this of the week ones. The screenshot should end at whatever the current day is ... sent on the A Players text chain." His sample was B56:H62 on Thursday — the title row to the last rep, Roll Call across to Thu. Then: "the week one screenshot at 10:45, you'll do it both for AT&T and Verizon. And then at 11:30 a.m., I want the screenshot of week 1, week 2, week 3, and week 4 for both AT&T and Verizon."

- **Code:** `automations/week_one_text/` (main `53cc817e`, `1fcb11a6`, `2ff5a76c`). Two shots × two boards = four texts a day, each its own text (`AT&T Week 1s — Friday 11/20`, `Verizon Week 1s — …`, `AT&T Weeks 1–4 — …`, `Verizon Weeks 1–4 — …`, then the picture). AT&T = the NDS Sales Board.
  - **week1 (10:45):** the WEEK 1 table, title row to last rep, Roll Call across to TODAY's day column (Mon → E … Fri → I).
  - **weeks (11:30):** WEEK 1's title down to WEEK 4's last rep, full width through Trainer (Date Gone, Prior Weeks, Total Sales included); never the TERMINATED table.
- **Found by label, not row number:** each table = a column-B title (`WEEK n · …` / `TERMINATED · …`) with the `Roll Call` header under it, reps down to a blank or the next title; the day column by its header (`Thu`). Pictures come off the live tabs (same PDF export as the Teams box).
- **Timers (launchd on Lucy 2, Mon–Fri):** `com.alphalete.week-one-text` 10:45 + 10:55 retry (`deploy/week_one_text.sh --send`) and `com.alphalete.week-tables-text` 11:30 + 11:40 retry (`… --shot weeks --send`); installed with `rerun install_week_one_text_agent` / `rerun install_week_tables_text_agent`. Each board texts **once per day per shot** (state `~/.config/recruiting-report/week_one_text_state.json`, under a lock), so a retry only fills in what's missing. NOT Report Library cards — Lucy 2's card scheduler only watches (see the Lucy 2 ops README).
- **Chat:** NEW A Players for all four: `TEXT_ROUTES` keys `("NDS WEEK 1","nds_week_one")`, `("VZ WEEK 1","vz_week_one")`, `("NDS WEEKS 1-4","nds_weeks")`, `("VZ WEEKS 1-4","vz_weeks")`, through the local text outbox like every other picture text (`restart_poller` after changing a route).
- **When a board sends nothing:** nobody in the shot (logged); or WEEK 1's dates don't cover today — the week cell **B2** was left on an old week (Verizon's B2 is `='NDS Sales Board'!$B$2`, so it moves with the NDS board). That board FAILS on purpose rather than text a stale week; the other board still sends. Put B2 back on the current week and send by hand.
- **Monday:** the boards flip to the new week at 08:20 (week_roll) and the Roll Call at 9:00 (+11:00 catch-up), so 10:45 sees the new week; WEEK 1 is then whoever has Day 0 on Monday.
- **Hand commands:** `rerun week_one_text` (dry run of the 10:45 shot, both boards) · `--shot weeks` (the 11:30 one) · `--shot all` (both) · `--board nds|verizon` · `--send` (queue; once per day per board per shot) · `--send --force` (again) · `--shot all --dm U046G04P5LG` (Slack DM preview to Carlos from Lucy, texts nothing). Log: `logtail week-one-text-<YYYY-MM-DD>` on Lucy 2.
- **On request — the TERMINATED tables** (main `af046d5c`): `rerun week_one_text --shot terminated --send` texts each board's TERMINATED table (B:E, last 4 weeks) to NEW A Players as `AT&T Terminated, last 4 weeks — <day>` / `Verizon …`; routes `NDS TERMINATED` / `VZ TERMINATED`; no timer. First sent 11/19 ~10:28pm together with both Weeks 1–4 pictures (Carlos: "just because I want them to see it").
- **What breaks it:** renaming the `WEEK n` / `TERMINATED` titles or the `Roll Call` / day headers, or moving the block out of columns B:N. A new column between B and the day columns is fine (found by header).

## 2026-11-19 — 2nd rounds + new starts report, AT&T vs Verizon (`automations/second_round_report`, main `3c8353e1`)

Carlos: "how many total second round interviews we've had so far this week, how many were conducted by AT&T, how many we offered the job to, and how many accepted ... Verizon, same thing ... both of our closing percentages ... cross-reference this with what's on applicant stream retention details." Then the last 4 weeks with new starts scheduled / showed.

- **Reads the Daily Update by header**: `2nd round Interview Date`, `2nd round` (the interviewer), `2nd show/no show`, `Offered`, `BOB Status`, `Orientation Date`, `Classroom Retention`, `Campaign`, `Name`. Conducted = Showed; accepted = BOB; closing % = accepted ÷ conducted; new start scheduled = orientation date in the period, showed = Showed To CR.
- **Team = who did the 2nd round**, matched to the NDS (AT&T) / Verizon Sales Board rep rows (last name + first name or nickname; suffixes like II ignored); "?" or no interviewer → the candidate's Campaign.
- **AppStream check**: the funnel board's hourly `Daily Log` (recruiting dashboard `111Bmxx1…`) for office 11580 — AppStream Retention Details' per-day 2nd showed / offered / brought on board / new starts scheduled / showed — compared day by day; the picture names each day that differs and the Daily Update rows behind it (e.g. offers marked N that AppStream counts).
- **Run (Lucy 2, on request)**: `rerun second_round_report --through 2026-11-18 --dm U046G04P5LG` (this week), `--view weeks --weeks 4 …`, `--note-to U1,U2 --send-note` (the offers note as one group DM from Lucy). Picture only without `--dm`.
- **What breaks it**: renaming those Daily Update headers; a 2nd-round interviewer who isn't on either board falls back to the candidate's campaign (logged as "interviewers not on a board").
- **11/19 late — by leader + AppStream "Done By 2nd" + the cards text** (main `7b21d765`, `eaaf06a4`, `97d9608a`): `--view leaders` = the same numbers per 2nd-round leader (new starts credited to the leader who did their 2nd round). `--appstream-pull` (or `--view leaders --pull`) reads AppStream's per-person detail lists for office 11580 (2nd rounds, showed, offered, brought on board, new starts; with Done By 1st/2nd, email, phone) into the control sheet's **2R AppStream Pull** tab; the by-leader picture then shows, per leader, how AppStream's Done By 2nd compares. **Carlos's rule:** AppStream saying *Carlos Hidalgo* where the Daily Update names someone else is intentional — the Daily Update wins and it's counted as "Carlos", not a mismatch. `--cards-only --text` texts just the Office / AT&T / Verizon cards to NEW A Players (route `2ND ROUNDS`). One-shot launchd timers for Fri 11/20: `second-round-leaders-1120` (6:30, pull + DM Carlos) and `second-round-cards-1120` (9:00, cards to A Players); both act only on 11/20 and should be removed after (`rerun install_second_round_*_agent --remove`). AppStream login: the pull uses the funnel board's unattended form login in its own profile (`.appstream_profile_2r`); at midnight 11/19 AppStream itself was down (Cloudflare 525).
- **11/20 — daily by-leader text, no notes box** (main `7ae730a5`): Carlos, on the AppStream notes box under the by-leader tables: "Remove this bottom section. Send daily in the morning on the Aplayers and leaders text chain" / "On the A Players you can send now. Leaders you can send at 9am". The picture is now the AT&T + Verizon leader tables only (the done-by detail — who AppStream names instead, who is on one list only — stays in the run log). Lucy 2 launchd `com.alphalete.second-round-leaders-daily`, Mon–Sat 9:00 (9:20 retry): `--view leaders --weeks 4 --through yesterday --pull --text` → NEW A Players + ATT B2B Leaders, once per chain per day (`--to aplayers|leaders` for one chain; state `~/.config/recruiting-report/second_round_text_state.json`). The window is the last 4 Mon–Sun weeks through yesterday (the current week partial). The **2R AppStream Pull** tab now records the window it covers (Pulled From / Pulled Through); a failed pull or a pull for another window leaves the AppStream column off instead of showing "not found". The 11/20 6:30 pull worked in under 4 minutes: of 122 2nd rounds AppStream had the same leader on 96, Carlos Hidalgo on 16, blank on 2 and a different leader on 8 — all 8 say Nico Murrugarra where the Daily Update has Edgar Camunez, Jair Otero or Diego Chacon. The 6:30 one-shot was removed. **Same day, main `d3e46aac`:** the Daily Update is typed by hand (its fill was retired 11/3), and at 7:35 Thursday 11/19 had 0 rows against AppStream's 11, so the first A Players picture said "through Thu 11/19" with Wednesday's numbers. `--through yesterday` now stops at the latest day whose showed 2nd rounds are at most one short of AppStream's (funnel Daily Log `2nd Showed`) and logs "<day> is not on the Daily Update yet"; the once-a-day text key stays on the day asked, so a later fill never sends a second picture. **Then (main `091e5812`):** Carlos: "Remove the app stream done by column on the far right / Without the bottom box and the column to the right" — the picture is the Daily Update numbers only (no AppStream column, no notes box), and the daily timer no longer walks AppStream (`--pull` still logs the done-by check on a hand run).


## 2026-11-20 — car-ride new starts lost their green (the WEEK tables read as "on the board")

Carlos: "something happened with the car ride new starts. they're not green anymore".
- **Cause:** the Stations new-start filters X5 (NDS) / Y5 (Verizon) list Roll Call rows for the board week with Status "New Start", no Date Gone, and NOT on the board — "on the board" was `MATCH(name, '<board>'!$B$5:$B$64, 0)`. Since 11/19 the WEEK 1–4 tables (B56 NDS, B50 Verizon) list this week's new starts by name in column B inside that range, so every new start read as already on the board: X5/Y5 empty → no car-ride green (CF `COUNTIF($X$5:$X$40,C6)` → #b7e1cd), no New Starts under column J, and the new starts dropped out of the name type-ahead (V5/W5) and MARK OFF lists (S5/T5).
- **Fix (sheet):** X5/Y5 now stop the board range above the first "WEEK " title: `'<board>'!$B$5:INDEX('<board>'!$B$5:$B$220,IFERROR(MATCH("WEEK *",'<board>'!$B$5:$B$220,0)-1,60))` (no WEEK title = rows 5–64 as before). Verified: X = Hung Quoc Nguyen, John Anthony Escobedo, Rocco Dichiara; Y = Eric Murillo, Eric Dylan Reese, Robert Lee Nichols; D6/D7/D9/D34 green again. Before-formulas in the scratchpad `stations_X5Y5_before_2026-11-20.json`.
- **Fix (script, API PUT to HEAD):** one builder `_newStartsFilterFormula(camp, board)` (RollWeek) used by `stationsHelperGuard`'s `ns()` (6:45am) and by a new `newStartHelpersCheck()`, which the every-minute `processAddQueue` trigger runs once an hour on the hour (next to `teamsBoxSync` / `weekTablesTidy`). WHY the hourly check: the Monday flip poke (`?action=rollcallflip`) runs the webapp's older saved VERSION, whose guard still writes the rows 5–64 formula; the 9am/11am Monday triggers exit early ("already on"), so without it Monday would stay un-green until Tuesday 6:45. Worst case now: ~8:20 → 9:00 on Mondays. Bumping the webapp version (Deploy → Manage deployments → New version; the API token has no deployments scope) would close that gap. Backups: `~/.config/recruiting-report/backups/vantura_script_before_2026-11-20.json` / `_after_`.
- **Also fixed (column J, Stations J6/J31):** when a board has NO In Training reps but has new starts, the old `IFERROR(VSTACK(SORT(FILTER(...)),...),TOCOL(...))` listed the first new start twice (IFERROR swaps the #N/A element for the fallback's first value — Verizon showed "Eric Murillo" twice, count 4 for 3 people). Now `LET(itr,…,nst,…,hasi,COUNTIFS(…)>0,hasn,COUNTIF(nst,"?*")>0, IF(hasi, IF(hasn, VSTACK(SORT(itr),"",TOCOL(nst,1)), SORT(itr)), IF(hasn, TOCOL(nst,1), "")))`. Board refs stay `$5:$60` so the guard's rep-list pin still applies.
- **What breaks if you change it:** a WEEK table title that no longer starts with "WEEK " (the filters fall back to rows 5–64 and the green goes again); moving a WEEK block above row 64 without a WEEK title; editing X5/Y5 by hand (the hourly check and the 6:45 guard put `_newStartsFilterFormula`'s version back — change the builder instead). Checked while here: `week_roll` stops its rep rows at the first totals label (never reaches the WEEK tables), and the Roll Call has no junk rows from them.


## 2026-11-24 — car-ride new starts not green again: the WEEK tables were FROZEN by the Monday flip, and the block's Roll Call range had DRIFTED

Carlos: "why arent new starts green on the car rides".
- **Chain:** Stations X5/Y5 (the new-start filters that drive the car-ride green, column J's second block, type-ahead, MARK OFF) list Roll Call new starts NOT on the board; "on the board" = `B5 : <row above the first "WEEK " title>`. The title is the spill anchor: NDS B56, Verizon B51. On 11/24 both showed `#REF!` ("Array result was not expanded because it would overwrite data in B57/B52"). Everything under the anchors (NDS B57:N90, Verizon B52:N83) was LITERAL text: the old spill, saved as values. With no title, the first "WEEK " found was WEEK 2 (row 62 / 55). So this week's WEEK 1 names counted as "on the board" and Robert Anthony Mitchell / Brysen Kade Mathes (NDS) and Tommy Earl Burk (Verizon) dropped out of X5/Y5.
- **Why it froze:** the Monday flip (`?action=rollcallflip`; it ran 6:26–6:30am on 11/23 — the roll goes as soon as the production post has delivered, 8:20 is only the fallback) runs the webapp's OLD saved version. Checked 11/24 evening: the newest SAVED script version is 19 (11/4), before the 11/19 guard, so whichever saved version the webapp points at lacks it (the token gets 403 on deployments.list, so the exact number is not readable). v19's `reanchorBoardStatRanges` writes 60 rows x 52 columns back from the first totals label (NDS row 31 -> row 90, where the frozen NDS rows ended). It writes only when it finds a drifted range, which a Monday promotion insert causes. That version's read-and-write-back (`reanchorBoardStatRanges`; HEAD has the push #10 guard) wrote the spilled rows back as values. The frozen rows read "WEEK 2 · 11/16 – 11/22" and "11/23 … not on Roll Call", so the freeze was Monday 11/23 around the flip. **Expect it again on any Monday the flip has a drifted range to fix, until the webapp deployment is bumped** (Deploy → Manage deployments → New version, needs the editor UI) or a self-repair goes into the hourly tick. Stale "nothing typed" check: the anchor is `#REF!` and the cells below are literals.
- **Fix (11/24 ~12:35, sheet only, values API):** (1) backup `~/.config/recruiting-report/backups/vantura_week_blocks_frozen_2026-11-24.json` (every literal), (2) `values:batchClear` NDS `B57:N90` + Verizon `B52:N83` (the spill area under each anchor, values only), (3) Stations `J16:J17` cleared (two names typed under J6 while the list was empty, they blocked the J6 spill = `#REF!`), (4) Day 0 column format `m/d` re-applied on NDS `D57:D220` and Verizon `D52:D214` (rows that held the frozen text had lost it and showed serials like 46350). Car rides D6/D9 green again; X5 = 8 names, Y5 = 9.
- **Second bug found the same minute:** every WEEK 1 row said "not on Roll Call". The block reads `'Roll Call'!$E$3:$E` (and B/D/G/H:O) but Google had slid the start to **row 22**, because new starts are inserted at the top of the Roll Call (rows 3-20 this week): the new starts above row 22 were never searched. **Fixed in both formulas: all 12 Roll Call refs are now `INDIRECT("'Roll Call'!$E$3:$E")`** so inserted rows can't move them (same trick as X5/Y5). Tested in scratch cells first (spilled clean, then cleared), then written to B56 / B51. Formula backup `vantura_week_formulas_2026-11-24.json` (old + new). Builder `week_block.py` (backups copy + scratchpad copy) updated the same way; `week_block_vz.py` swaps off it unchanged.
- **Also seen, left alone:** Stations `L12` (auto "off today" list) is `#REF!` because names are typed under it in L13:L17 (it errored before this fix); `U5` (terminated source) reads the Roll Call from row 63, `L12` from row 23 (the same row drift). U5 isn't in the 6:45 guard's canon.
- **What breaks it again:** the Monday flip on the old webapp version (freeze), typing anything inside B57:N220 / B52:N214, or someone editing the Roll Call refs back to plain `$3` (inserted rows drift them). To repair by hand: clear the literals under the anchor, then check `B56`/`B51` show "WEEK 1 ·".
