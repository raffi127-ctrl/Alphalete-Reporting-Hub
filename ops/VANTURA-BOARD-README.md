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
  daily — rows 53+ are hidden to bury it). Week label at **Q2** (week_roll
  writes it). Any layout change must re-anchor: `car_rides` BOXES ranges,
  the cross-off CF INDIRECT strings on Sales Board + Roll Call, CF ranges,
  frames.
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

## Stations layout — CURRENT (restructured 2026-09-09)

Per campaign section: CAR RIDES (A:E), STATIONS below (A:E), REP LIST G:I,
**MARK OFF at K** (single column, right beside the rep list — the old K "NEW STARTS" list and the old
L "OFF — TODAY (auto)" list are GONE). Column I is now
**"In Training / New Starts"**: board reps with Leadership "In Training"
first, then ONE blank row, then the week's Roll Call new starts (from hidden
helpers W5/X5). New starts inherit all rep-list coloring and are pickable in
MARK OFF and the name type-ahead automatically.

Hidden helper columns (R–X, all load-bearing — NEVER clear or unhide-and-edit):

| Col | What |
|---|---|
| R5 | ATT mark-off dropdown source = TOCOL(G6:I24) |
| S5 | BOX mark-off dropdown source = TOCOL(G31:I49) |
| T5 | TERMINATED names (live-week roll T/Terminated + board P=Terminated) — drives red+strike CF everywhere |
| U5/V5 | name type-ahead sources (ATT/BOX) = UNIQUE(TOCOL(G:I)) |
| W5/X5 | NEW STARTS (ATT/BOX) roll-call filters — feed col I's second block + car-ride green CF |

**THE TYPE-AHEAD RECIPE — DO NOT BREAK (Carlos: "the way it works now is
great, lock it in").** Typing part of a name in any car-ride/station cell or
MARK OFF cell pops matching full names. That behavior requires ALL of:
1. data validation `ONE_OF_RANGE` pointing at a **single-column** helper
   (R/S for MARK OFF, U/V for name cells);
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
(K5:K18 + K30:K43 everywhere) or first-row picks silently do nothing.
Q2 ("9.13") is the week label the Monday roll writes — never "clean" it.

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
