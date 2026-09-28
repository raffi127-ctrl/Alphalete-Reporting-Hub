# Local Office 1on1s — report spec

Source: Raf's Loom, 2026-09-27 —
https://www.loom.com/share/a197dcc15c944fa4bf853f49378f76ff
(tagged to Megan, cc Eve)

> "The most tedious task is just getting the data, which is why I'm so
> hit-and-miss about doing it with the reps. What I would like is for it
> just to automate it, and all of it being connected to the sales board."

This is the **local office** 1on1 sheet — Raf's own office. It is NOT
[[project_org_1on1s_report]] (the "Alphalete Org 1on1s - Focus Report"
tab, which is per-ICD and PP-driven). Different sheet, different grain:
here a box is **one rep**.

---

## Shape

**Tabs: one per team.** Alphaletes, Se7en Sins, Ceaseless, Hashiras,
Mindset Engine. Raf: "it would delete these" — the existing per-person
tabs get cleared out and replaced by five team tabs.

**Inside a tab: one box per rep** (Hayden, Thomas, IBK, Zoe, …), stacked.

**Only leaders get a box.** Raf: "it only has to do it for leaders. So if
they're an entry-level, it doesn't have to." Same test
`gap_alerts/leaders.py` already uses — sales-board `Leadership Status`
above Entry Level on the ladder (In Training → Entry Level → Level 1 →
Level 2 → Mastermind), terminated excluded via `terminated_reps.board`.

**Two box templates.** Raf keeps these two and deletes the rest:
1. **Rep template** — the average rep who is a leader but has no team of
   their own yet.
2. **Team-leader template** — a rep "running their own team", i.e. they
   have a team NAME. Same rep fields, plus the team block at the bottom.

**Schedule: Sunday morning, data as of Sunday morning. Then again
Monday morning** — "because sometimes the reps do sales on Sunday."
Same tabs, same boxes, overwritten. Not a second post/sheet.

---

## Field → source map

Everything below is by-label lookup, never a fixed row/column
([[feedback_no_hardcoded_columns]]). Grain is one rep per box.

### Rep fields (both templates)

| Field | Source | Already built? |
|---|---|---|
| Knocking data | Weekly Knock Dispositions per-rep rows — Mon–Fri Total Knocks, Mon–Fri Total Leads Knocked, Mon–Fri Avg Doors/Day, Sat Avg Doors/Day, Mon–Sat Avg Knocks/Hr, Mon–Sat % Talk To's per Knocks | **Yes** — `automations/weekly_knock_dispositions/board.py`. Raf: "comes from the knocking report that gets sent out." |
| Sales | The office sales board, per-rep row | **Yes** — `automations/icd_sales_board/board_read.py` (Raf's "Alphalete SALES BOARD 2025", `Sales Board WE m.d` tabs, rep block ends at `TOTALS`) |
| 2nd Rounds Conducted | Recruiting funnel — AppStream p=783 "Retention - Details (new)" | Partly — see **Gap 1** |
| Job Offered | same | Partly — Gap 1 |
| 2nd Rounds Closed (a NUMBER — Raf corrected this live: "so that should be a number") | same | Partly — Gap 1 |
| % 2nd Round Close | formula off the two above | formula |
| BOB | same | Partly — Gap 1 |
| New Starts Scheduled / New Starts Shown | same | Partly — Gap 1 |
| **These six are MONTHLY, not weekly.** Raf: "This is monthly, so it doesn't have to be weekly… when I was filling it out manually, it would be for the month. What are they at?" | | |
| Trained This Week | Sales board — reps whose `Trainer` cell names this rep, filed to the week | Reader exists (`sales_board_mind_map` walks the Trainer chain); the weekly count is new |
| Retained (= not terminated) | Sales board termination, all three markings | **Yes** — `terminated_reps.board`. Raf: "that would come off of the fact that the rep is not terminated yet on the sales board." |
| Gross Paycheck | `Got Paid` out of the P&Ls | Partly — see **Gap 2** |

Raf on one block: *"This stuff right here would just be us."* — a set of
cells stays manual/leadership-entered. Which ones is in **Question 3**.

### Team block (team-leader template only)

| Field | Source | Notes |
|---|---|---|
| Team Structure — All | Trainer chain off the sales board, first-gen count + whole-team count | `sales_board_mind_map` already prints exactly this as "Name 2/5" (2 first gens, 5 in the whole team). Raf: "it's got team structure all, which is what that means is entry levels." |
| Team Structure — with Leaders | same chain, leaders only | same source, filtered by `Leadership Status` |
| Active Reps | team size, **week ones excluded** | Raf: "I would not count a week one an active rep." Week is on the board (colour + "WK1 New Start" rank) |
| # Leaders | `Leadership Status` above Entry Level, in their downline | `gap_alerts/leaders.py` test |
| New Starts that started | board New Starts / Classroom block | |
| How many are alive | of those, not terminated | `terminated_reps.board` |
| New Start Retention | formula (alive ÷ started) | formula |
| Team totals — "what did they all do" | sum of the rep rows in their downline | Raf: "this would be formulas, I believe" |

Note the upline rule: a rep's team comes from their **Trainer chain**,
not their own `Team` cell — "their trainer is their upline" (Megan,
2026-09-20, in `sales_board_mind_map`). The five team names are the
roots. That module's tree is the thing to reuse for every structural
number here, rather than re-deriving the chain.

---

## Gaps (real work, not unknowns)

**Gap 1 — the funnel numbers are not per-rep today.**
`automations/funnel_board/` pulls all eleven funnel metrics from
AppStream p=783, but per **office/manager** — and `fetch.py` explicitly
skips the per-recruiter breakdown (`tr.adminRow`). The per-person rows
exist in the page; `automations/recruiter_stats/` already reads a
per-admin cut of a sibling report. So the pull is a known change, not a
new capability. **Open:** whether field leaders (Hayden, Thomas, IBK,
Zoe) appear as recruiters/admins in that breakdown at all — see
Question 2.

**Gap 2 — only one P&L is wired.**
`automations/reps_gross_paycheck/pnl.py` reads per-rep `Got Paid` out of
`Raf PNL 2026` (in "All in One Local Office - Raf") and already handles
the traps: sub-rosters below row ~389 (AYA, CY - Rafs DD, CY - Cy's DD,
Zach, Rashad), people on two rows, and the 3-wide
`Brought In | Got Paid | Profit/Loss` week blocks found by header.
Raf wants all three searched: "there's a couple different PLs here, so
it would have to search the three PLs, and then it would just grab got
paid." Repo also knows `B2B PNL`, `Fiber PNL`, `JE PNL`, and
`Copy of Carlos PNL 2026` — but those three are program blocks on the
Focus Report tab, office-level, no per-rep `Got Paid`. So the three
rep-level P&Ls have to be named. See Question 3.

**Gap 3 — the fill itself.** New module, per the house pattern: sandbox
copy of the sheet + `--dry-run` until the output is confirmed; preview
on ONE box first (Raf's own default preview rep) before the other four
tabs get touched.

---

## Blockers

1. **The spreadsheet URL.** The template layout — which rows carry which
   label, in what order, in each of the two box templates — can only be
   read off the sheet. [[feedback_ask_for_the_url]]
2. **Do the field leaders show up in AppStream's per-recruiter
   breakdown on p=783?** If 2nd rounds are logged under the office
   admin who booked them rather than the leader who conducted them,
   Gap 1 needs a different source (or those six cells stay manual).
3. **Which three P&Ls, and are the other two per-rep with a `Got Paid`
   column?** Raf said "search the three PLs" while pointing at the
   screen; only `Raf PNL 2026` is a known per-rep one.
4. **"We can just delete all of these"** — the existing per-person tabs.
   Deleting tabs someone filled in is exactly the thing this repo does
   not do without a confirm, and they get backed up to `output/` first.
   Needs an explicit go from Raf, not just the Loom aside.

## Not blockers (decided)

- Five tabs, named for the five teams; boxes only for leaders.
- Sunday AM fill + Monday AM re-fill, same cells.
- Monthly grain for the six funnel fields, weekly for everything else.
- Week ones are not active reps.
- Structure numbers come from the Trainer chain, via the mind-map tree.

---

# As-built layout (read off the sheet, 2026-09-27)

Workbook: **"1on1's - Local Office - Rafs"**
`1KhCZ4fzIbXh9LKWeHMfvfswcHdlXEa14IK5KsmRgwZM`

## Geometry — same shape as the Focus Report

    col A   section label ('1. Sales', '2. Recruiting', ..., "Owner 1on1's")
    col B   metric label  ('New INT', 'Total Apps', 'Gross Paycheck last week?')
    col C+  one column per week-ending, header 'WE m/d'

So rows are found by their col-B label and weeks by their date header —
`fill.find_sunday_columns` and by-label row lookup apply unchanged
([[feedback_no_hardcoded_columns]]).

**A box** starts on a row whose col A is `Rep Name?`; the rep's name is in
col B of that same row, and the box repeats the week-header row. Boxes are
stacked ~28 rows apart but NOT on a fixed pitch (Alphaletes: r1, 44, 72,
97, 125, 153) — walk for the `Rep Name?` marker, never step by a constant.

## The tabs that exist

| Tab | Boxes | Named reps |
|---|---|---|
| `Template - Fiber` | 3 | template |
| `A-player - Template` | 2 (+2 `Owner 1on1's` blocks) | template |
| `Alphaletes` | 6 | Hayden, Thomas Crenshaw, Ibukunolowa Ogunolola (IBK), Zoria, Ana Griffin |
| `Se7en Sins` | 12 | Lakeaih Gregory, Heiddy Ochoa, Alyssa Moreno, Anthony Marchetti, Justin Avila, Cooper Childers, Alexis Streit, Ivette Henson, Anthony Coca, Kenneth Guzman, Nima Aweida |
| `Ceaseless` | 14 | Willie, Chloe Johnson, Raphael Luzes, Jordan Ruiz, bo scarbrough, William Canas, Jessie Gomez, lemsy Vazquez (+6 blank) |
| `Hashiras` | 8 | Ben K, pranish, Rhea, Elijah, Andres (+2 blank) |
| `Mindset Engine` | 10 | Andrew Sanborn, Adriannah Reyes, Ian Rodriguez, Bill Hirwa, Jordan Castillo, Samajai Hoy, Alexis Streit (+3 blank) |
| `Velocity` | 7 | Zoria, Sydney, Thomas, Miguel, IBK (+2 blank) |
| `Safiya` | 10 | Safiya, Tadana (+8 blank) |
| `Thomas` | — | per-person leftover |
| `Edgar ` (trailing space) | 3 | Ibukunolowa Ogunolola (IBK) |

**The five team tabs Raf named already exist and are already hand-filled**
through WE 8/30. So this is a FILL of existing boxes, not a build of new
tabs. Blank boxes are pre-made slots — a new rep reuses one rather than
getting rows inserted.

## Box variants — four, not two

1. **Full rep box** — `Template - Fiber` r1-42. The only place the
   **knocking block** exists (r2-14 — note it carries NO section number
   in col A; the numbered sections start at `1. Sales` on r15): Mon-Fri Total Knocks · Mon-Fri AVG
   Doors/Day · Mon-Fri Total Talk To's · Monday % Talk To's per Knocks ·
   Mon-Fri avg Talk To's Day · Mon-Sat Total Apps · AVG Talk To's per App ·
   Mon-Fri AVG First Knock · Mon-Fri AVG Last Knock · Sat Avg Doors/Day ·
   Sat First Knock · Sat Last Knock · Sat avg Talk To's Day.
   Also the **expanded recruiting block** (r23-29): 2nd rds Conducted ·
   Job Offered · 2nd rds closed · BOB % / 2nd rd closing · New Starts
   Scheduled · New Starts Showed · New starts Retention %.
2. **Short rep box** — `Template - Fiber` r46-70. No knocking block;
   recruiting condensed to 4 rows.
3. **A-player box** — `A-player - Template` r1-41, adds `Team Structure -
   All` / `Team Structure - Leaders` and the `Owner 1on1's` team block
   (r26-40): Active Reps · Leaders · New Starts started · New Starts
   alive? · New Start Retention · New INTS · Upgrades · DTV's · Wireless
   Lines · Total Apps · App AVG per rep · New INT AVG per rep · New INT
   Goal · Wireless Goal · App Goal.
4. **Energy variant** — `A-player - Template` r44+, sales block is
   `Energy Sales` / `Energy Sales Goal` instead of INT/Upgrades/DTV/
   Wireless.

**Every live box today is variant 2 or 3 — none carries the knocking
block.** Raf's "just this knocking data, just filling it out there for
the rep" therefore means adding those 13 rows to the live boxes.

**Live boxes use the CONDENSED recruiting form**, and it is a *ratio in
one cell*: Hayden WE 8/30 → `2nd Closing numbers = 3/8`, `2nd Closing % =
38%`, `New Starts showed / Schedule = 0/1`, `New starts Retention % = 0%`.
The transcript's seven separate rows are variant 1's expanded form, which
Raf was editing live ("I just kind of edit this… so that should be a
number").

## Labels drift between boxes — match loosely

Real examples inside one tab: Hayden has `New INT Goal` / `Wireless Goal`
/ `Total App Goal`; Thomas has one `New / App Goal`; IBK has `New INT
Goal` / `Wireless Goal` / `New / App Goal`. `Dress Code 1 out of 3` on
some boxes, `1 out of 5` on others. IBK alone carries a `Team Structure`
row. So the row matcher has to be fold-and-contains, and a label it
cannot place is SKIPPED and reported, never written to a guessed row.

## Manual rows — confirmed, do not fill

Raf's *"this stuff right here would just be us"* is section **4. Culture
/ Atmo / HTP** in full (Listening to X book? · Dress Code · Last week
Punctuality? · Atmo Engagement · Slack / Chat Engagement · Networking?),
plus `What are we going to do better?`, `Money Saved?`, and `Goal / Focus
for the week`. Leave every one of those alone.

`BreakEven` looked automatable — col C of `Raf PNL 2026` is literally
headed `Breakeven` — but it is **empty for all 446 named reps across all
three P&Ls**. It stays MANUAL. Only `Gross Paycheck last week?` comes
from these tabs. (Measured 2026-09-27.)

## Week-header traps (found, must be handled)

The header is NOT uniform across tabs:

    Alphaletes / Ceaseless / Mindset Engine / Velocity / Safiya
        WE 8/02 … WE 8/30        — stops at 8/30, four weeks stale
    Se7en Sins
        WE 8/02 … WE 8/30 | 'WE  9/4' (DOUBLE space) | '9/13'
    Hashiras
        WE 8/02 … WE 8/30 | '09/06' | '9/13' | '9/20' | '9/27'
    Template - Fiber
        WE 8/02 … WE 8/30 | '08/06'   — AUGUST 6th, sitting after 8/30

Three separate problems:
1. **Two headers are wrong, in two different ways.** `WE  9/4` on Se7en
   Sins is a FRIDAY (the week ending is 9/6). `08/06` on
   `Template - Fiber` is AUGUST 6th sitting after `WE 8/30` — it means
   9/6 too. A parser that trusts the header files both weeks wrong, and
   `08/06` would land four weeks BEHIND where it belongs. Headers that
   do not resolve to a Sunday in sequence get flagged, never accepted.
2. **Three spellings of the same thing** — `WE 8/02`, `09/06`, `9/13`.
   Zero-padded, unpadded, prefixed, unprefixed.
3. **Most tabs are missing September columns entirely** and need them
   appended before anything can be written.

## Reps on two teams — has to resolve to one

- `Alexis Streit` — Se7en Sins r214 **and** Mindset Engine r188
- `Zoria`, `Thomas`, `IBK` — Alphaletes **and** Velocity
- `IBK` again on the `Edgar ` tab

The Trainer chain on the sales board decides ("their trainer is their
upline"); a rep resolving to two tabs is a data error to report, not
something to fill twice.

## Name matching

Sheet spellings are informal and often first-name-only — `Hayden`,
`Zoria`, `Ben K`, `pranish`, `Rhea`, `Elijah`, `Andres`, `Sydney`,
`Miguel`, `bo scarbrough`, `lemsy Vazquez`. And where the sheet says
`Ibukunolowa Ogunolola (IBK)` the sales board says
`Ibukunoluwa Olapade Ogunlola`. `weekly_knock_dispositions/teams.py`
already has the three-pass unique-hit matcher for exactly this; a
first-name-only box that matches two reps must be reported, not guessed
([[feedback_alias_list]]).

## Decided — by the Loom, not by us

1. **The templates win over the live tabs.** 0:43 — *"we can just delete
   if you guys want all of these. Because they're kind of whatever, and I
   think these templates make the most sense."* Where a live box and a
   template disagree on the row set, the template is right.

2. **Recruiting = the EXPANDED seven rows** (`Template - Fiber` r23-29).
   1:42, read off the screen in order: *"Second rounds conducted, job
   offered, second round close, percent second round close, second rounds
   closed… BOB and second round closing number, new starts scheduled
   shown."* The live condensed four (`2nd Closing numbers = 3/8`) is the
   old form and gets migrated.
   **His one edit** (corrected off Megan's screenshot of the tab,
   2026-09-27): *"I just kind of edit this. So that should be a number."*
   points at **r25 `2nd rds close`**, which holds `8/11` — a RATIO. It
   becomes a count. r26 `BOB % / 2nd rd closing` holds `72%` and stays a
   percent; its label already says so.

   This is why three rows are BLANK in Raf's own template: `2nd rds
   Conducted` (r23), `Job Offered` (r24) and `New Starts Scheduled`
   (r27). The ratio cells were carrying both halves — `2nd rds close`
   = `8/11` is closed-over-conducted, `New Starts Showed` = `4/10` is
   showed-over-scheduled. Split those into real counts and the blank
   rows fill themselves; the ratios stop existing. That IS the edit.

3. **Two templates, and which one a rep gets.** 0:53 — *"two different
   templates: one for your average rep, and then two once a rep is…
   running their own team, which I call a player… you can think about it
   once they have their own team name."* So:
   - **average rep** (a leader with no team of their own) → the rep box,
     WITH the 13 knocking rows
   - **A-player** (has their own team name) → the A-player box, no
     knocking rows, plus the `Owner 1on1's` team block
   "Fiber" in `Template - Fiber` is just Raf's program; the knocking rows
   in it are plain per-rep knocking data, not Fiber-specific.

4. **Five tabs, and the rest are deleted.** 3:13 — *"I would like to have
   a tab per team, so it would be Alphaletes, Se7en Sins, Ceaseless,
   Hashiras, and Mindset Engine. It would delete these."* So `Velocity`,
   `Safiya`, `Thomas` and `Edgar ` all go. That also clears the
   Zoria / Thomas / IBK duplicates, which were Alphaletes-vs-Velocity.
   Still back each one up to `output/` first, and still get the go in
   writing — deleting a tab someone filled in is the one thing this repo
   does not do on an aside ([[feedback_dont_touch_user_data]]).

5. **Team Structure - All includes entry levels.** 3:33 — *"it's got team
   structure all, which is what that means is entry levels. And then it's
   got team structure with leaders, which I think Megan is distinguished
   on the mind map."* He is pointing at `sales_board_mind_map`'s "Name
   2/5"; reuse that tree.

6. **Boxes only for leaders.** 3:22 — *"Hayden, Thomas, IBK, Zoe, and it
   only has to do it for leaders. So if they're an entry-level, it
   doesn't have to do it."*

7. **A week one is not an active rep.** 3:42 — *"how many active reps? I
   would not count a week one an active rep."*

## The recruiting numbers already exist — no AppStream pull needed

Megan, 2026-09-27, pointed at
`1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4` gid `71919177` —
workbook **"All in One Local Office - Raf"**, tab **`2nd rds %'s`**.

It carries all seven recruiting metrics **per leader, monthly, with the
team name**, already maintained by hand. That is exactly the grain Raf
asked for (*"This is monthly, so it doesn't have to be weekly"*), so
**Gap 1 is closed and `funnel_board`/AppStream p=783 is not needed for
this report.**

Layout: a two-row header (r2 labels, r3 sub-labels), then one row per
leader.

    A  Team Name          F  BOB # / Accepted
    B  Leader Name        G  BOB %
    C  2nd rds conducted  H  New Start Scheduled
    D  Job offered        I  New starts showed
    E  Job Offered %      J  NS Showed %

### Mapping to the template's r23-29

| Template row | Source column | Note |
|---|---|---|
| r23 `2nd rds Conducted` | `2nd rds conducted` | |
| r24 `Job Offered` | `Job offered` | |
| r25 `2nd rds close` | `BOB # / Accepted` | **this is the "should be a number" row** — `8/11` was BOB# over Job offered |
| r26 `BOB % / 2nd rd closing` | `BOB %` | stays a percent |
| r27 `New Starts Scheduled` | `New Start Scheduled` | |
| r28 `New Starts Showed` | `New starts showed` | `4/10` was showed over scheduled |
| r29 `New starts Retention %` | `NS Showed %` | **label mismatch — flag** |

Two things to raise with Raf rather than paper over:
- r29 is labelled **Retention %** but the only matching source is
  **NS Showed %** (Hayden's `4/10` → `40%` confirms it). Show rate and
  retention are not the same thing. Either the template is mislabelled
  or retention comes from somewhere else.
- `Job Offered %` (col E) has no row in the template at all.

### THE TRAP: month blocks are sorted independently

Seven months sit side by side, each with its **own** Leader Name column
and its **own** sort order:

    September  A-J    (the only block with Team Name)
    August     N-U        July  W-AD      June  AF-AM
    May        AO-AV      April AX-BE     March BG-BN

On the row where col B says `Hayden Wilson`, the other blocks say
`Hayden Wilson` (Aug), `Jessie Gomez` (Jul), `Jordan Castillo` (Jun),
`John Sims` (May), `Samajai Hoy` (Apr), `Jorge Serrano` (Mar).

**Reading across a row silently attributes other people's numbers.**
Every month must be looked up by name inside that block's own Leader
Name column. The blocks also differ in width — September has
`Job Offered %`, the older ones do not — so columns come from the
two-row header per block, never from an offset.

### It also answers three other things

1. **Team assignment per leader**, in col A — an independent, maintained
   source, and simpler than deriving it from the sales-board Trainer
   chain. It uses `Terminated` and `Extra` as pseudo-teams.
2. **Full proper names**, which bridge the informal box labels:
   `Hayden`→Hayden Wilson, `Ben K`→Benjamin Kushpit, `pranish`→Pranish
   Shrestha, `Rhea`→rhea mckee, `Elijah`→Elijah Rodriguez,
   `Andres`→Andres Mejia, `Zoria`→Zoria Johnson, `Sydney`→Sydney Agnew,
   `IBK`→Ibukunoluwa Ogunlola.
3. **No `Velocity` team exists** in the list, and `Safiya Mahmoud` is
   filed under Alphaletes — confirming those tabs are leftovers.

### Conflicts this surfaces

- **`Heiddy Ochoa` — CONFIRMED TERMINATED** (Megan, 2026-09-27: "Heiddy
  Ochoa - is T"). The `T` is the sales board's own termination marker.
  Her live box on `Se7en Sins` is stale.
- **`Alexis Streit` — TERMINATED** (Megan, 2026-09-27, correcting an
  earlier "brand new and not a leader"). She has boxes on BOTH
  `Se7en Sins` and `Mindset Engine`; both are stale and neither gets
  filled.

  Logged in the master `Terminated Reps` tab at **WE 8/23/2026**.
  **She does not appear in `2nd rds %'s` at all** — not even under its
  `Terminated` pseudo-team, where Heiddy Ochoa and Alfredo Lopez are
  filed. So that tab is NOT a complete termination list.

## The three P&Ls — named and confirmed

Same workbook. `Raf PNL 2026` (gid 1300001293),
`MJ-Alphaletes PNL 2026` (325879371), `OG-Alphaletes PNL 2026`
(1122999014). Ignore `TEST pnl Raf`.

All three are **byte-identical in layout** — verified r1-2:

    A Current Employee Y/N | B Team | C Breakeven | D Leader
    E First Name | F Last Name | then WE m/d blocks of
    Brought In | Got Paid | Profit/Loss

So `reps_gross_paycheck/pnl.py` reads all three with **no parser
change** — point it at three tabs and merge. This closes Gap 2.

### They are a HANDOFF, not three places to search

MJ and OG hold **3 named reps each**, and they overlap Raf PNL on
exactly the people this report is about:

| Rep | Raf PNL 2026 | the sub-P&L |
|---|---|---|
| Hayden Wilson | 8/30 `$800`, then **blank all September** | OG: 9/6 `$800` · 9/13 `$1,460` · 9/20 `$750` |
| Thomas Crenshaw | 8/30 `$1,200`, then **blank** | OG: 9/6 `$1,200` · 9/13 `$1,200` · 9/20 `$1,443` |
| Ana Griffin | 8/30 `$800`, then **blank** | MJ: 9/6 `$2,475` · 9/13 `$1,965` · 9/20 `$2,030` |

Raf PNL stops at **WE 8/30** for these people; the sub-P&Ls take over
from **WE 9/6**. The one shared week, 8/30, **agrees in both** — so the
overlap is a clean handoff, not a conflict.

**This is the bug Raf was describing.** Reading only `Raf PNL 2026` —
which is what `reps_gross_paycheck` does today — returns blank for
Hayden, Thomas and Ana for all of September. Three of the four leaders
he named by name in the Loom. Hence *"it would have to search the three
PLs."*

Merge rule: per rep per week, take whichever P&L carries a value; if two
do and they disagree, report it and write neither — `pnl.py` already
behaves exactly this way for duplicate rows within a tab.

### Two more signals in these tabs

- **`Leader` (col D) is a Y/N flag** — `Y` on Amjad, Ana, Hayden and
  Thomas; blank on Valery Galindo and Tayah Johnson. A third independent
  read on "is this person a leader", alongside the sales board's
  `Leadership Status` and the `2nd rds %'s` roster.
- **`Team` (col B) says `Alphaletes`** for all six, so MJ and OG are
  splits *within* Alphaletes, not separate teams. Consistent with Raf's
  five.

**Correction to an earlier note in this spec: `BreakEven` is MANUAL.**
Measured across all three tabs — **0 of 446 named reps have col C
filled.** The column exists and is completely empty. An earlier note
here claimed it was automatable off `Raf PNL 2026`; that was wrong.
Hayden's `$700`/`$925` are typed by hand and stay that way.

`Leader` (col D), by contrast, IS populated: `Y` on 94 of 440 in
`Raf PNL 2026`, 2 of 3 in each sub-P&L.

## Boxes that should not exist

Two reasons a live box should not be filled:

- **Terminated** — `Heiddy Ochoa` (Se7en Sins) and `Alexis Streit`
  (Se7en Sins AND Mindset Engine). Both confirmed by Megan 2026-09-27.
- **Not a leader** — the roster is leaders only; a box below that rank
  is premature, not a gap to fill.

Neither is deleted by the run. A box the sheet has but the roster does
not is listed as "no box should exist here" and its cells are left
alone.

Three of the ~45 live boxes were stale on the day this spec was written.
That is the normal rate, not an anomaly — the check runs every time.

## Terminated reps: never fill, never silently delete

Heiddy Ochoa is the first case, and there will be more every week. The
rule:

**The master list is the `Terminated Reps` tab** (Megan, 2026-09-27:
"we have a master termination list that you should reference") — gid
`835099438`, same workbook as the P&Ls. 2,688 rows, one per departure
since 2024: `Rep Name | Lead Rep | # Days Worked | Termination Date WE |
Ownerville | Slack Deact | Notes | Year`. Already read by
`reps_gross_paycheck/terminated_log.py`; reuse it, do not re-parse.

It confirms both live cases — **Alexis Streit WE 8/23/2026**, **Heiddy
Ochoa WE 8/28/2026** — i.e. both left BEFORE WE 8/30, the last week
their boxes were filled by hand.

**Correction to an earlier line in this spec:** the sales board is NOT
the sole authority. Neither source is complete, and
`terminated_log.py` documents exactly why:

- **The log catches what the board misses.** Checked 2026-08-07: the
  log knew about ELEVEN reps who still had tabs and whose board row
  never got a `Termination Date`.
- **The log cannot stand alone.** It is append-only and nobody removes a
  row when someone comes BACK. `Tadana Manyangadze` is in it TWICE —
  5/29/2026 and 8/25/2026 — and between those dates she posts 27 second
  rounds in the July block of `2nd rds %'s`. `Alexis Gaitan` shows the
  same double-entry pattern. A log-only rule writes off live reps.

**So: a log row counts only when the rep is ALSO absent from the newest
sales board. Presence on the board outranks any historical departure.**
That is exactly `reps_gross_paycheck/plan.py:gone` — reuse it rather
than writing a fourth terminated check.

The board half still goes through `terminated_reps.board`, the only
reader that knows all three ways the board marks it (a filled
`Termination Date`, a bare `T` in a day block, `Terminated` in the New
Starts box). Reading one of the three missed 15 of 15 people one week
([[automations/gap_alerts/leaders.py]]).

**`2nd rds %'s` col A is a hint only, never a check** — it files Heiddy
and Alfredo Lopez under a `Terminated` pseudo-team but omits Alexis
Streit entirely.
- **The stale box is REPORTED, not deleted.** The run lists it as
  "terminated, box should be removed" and leaves the cells alone. A rep
  leaving is not the shut-down-office case, which is the only standing
  exception to [[feedback_dont_touch_user_data]]. A human removes it, or
  Raf gives a blanket go and it gets backed up to `output/` first.

## Still genuinely open

1. **`New starts Retention %` (r29) vs the source's `NS Showed %`** —
   mislabelled template, or a different number Raf wants?
2. **Written go on the four tab deletions** (`Velocity`, `Safiya`,
   `Thomas`, `Edgar `) — back up to `output/` first.
