# Focus Report Campaign Metrics — System README

_Last updated: 2026-09-30 by Claude. This file is the source of truth
for the per-campaign sales-metrics block on the org Focus Report. Read it fully
before changing ANYTHING in this system — the second half is a playbook of what
typically breaks when you make a change, learned the hard way on 8/23.
Auto-updated daily at 7 PM CT by the scheduled task
`focus-report-readme-daily-update`. Companion docs:
RECRUITING-DASHBOARD-README.md (the whole workbook), CAPTAINSHIP-MASTER-README.md
(the captainship fleet this mirrors), LUCY2-OPERATIONS-README.md (deploys/queue)._

---

## 1. What this is

The **Focus Report** tab of the **Alphalete Recruiting Dashboard**
(`111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`) shows, below the recruiting
funnel (rows 4–27), a **campaign zone** in rows **30–73**: per-campaign sales
metrics for the people in Carlos's Tuesday "Carlos/Raf's One on Ones". Pick a
manager in A1 and the block redraws for THEIR campaign — different rows,
labels, and bands per campaign. Color key sits below at row 76.

Built 8/23 (proposal artifact:
https://claude.ai/code/artifact/d8c7024e-40b9-4ff5-8df3-154869d34500).

**Who gets what** (map lives in `automations/org_campaign_metrics/layout.py`):

| Manager | Campaign | Block source |
|---|---|---|
| Carlos Hidalgo + every captainship owner with a sales board (Atef, Jamis, Jackie, Justin, Joshua, Dhyey, Jeff, Kinsey, George, Joey, Vincent, Sabrina) | `b2b_att` | COMPUTED from ATTTRACKER-B2B ORDERLOG (one export, all owners tallied at once) + ACTIVATIONRATES/CHURNRATES crosstabs. Until 9/7 the owners were MT-tab copies off the Captainship Dashboard — that workbook is IN THE DRIVE TRASH and retired as a source. |
| Ryan McSpadden, Roshan Amin | `box` | B2BBOXEnergyTracker views + the BOX order log |
| Khalil Mansour, Maxamad-Amin Aden | `nds` | NDS-SN (RES-ATT-OOF) workbook views |
| MJ Malhas, Akib Chowdhury | `limbo` | manual TEAM rows only (Head Count / Leaders / People in Training) |

MJ + Akib are **CAMPAIGN_ONLY** picker entries (`funnel_board/roster.py`) —
on the Focus Report picker but NOT in the org: their funnel rows read zero
**by design**, they have no AppStream office being pulled and no Goals row.

## 2. Architecture (why it survives the hourly wipe)

The core constraint: **`funnel_board/build.py` wipes and redraws the ENTIRE
Focus Report tab every hour** (4am + :05 past every hour, on Lucy 2). Nothing
hand-placed on the tab survives 60 minutes. So the zone is split into two
layers:

1. **Rendering (code, redrawn hourly)** — build.py draws a *generic* 44-row
   zone: every cell is an INDEX/MATCH formula keyed on the A1 picker. Labels,
   band headers, values, goals — ALL lookups. Band colors paint via
   conditional-format rules keyed on a hidden helper column (one col past the
   last week block) that resolves each row's "kind". Styling: everything
   centered, data bold, hard row rules, thick black week separators —
   deliberately matched to the captainship block (Carlos, 8/23).
2. **Data (the hidden `Campaign Log` tab, NEVER wiped)** — build.py only
   *ensures it exists*; it is not one of the five owned tabs. Columns:
   - `A:B` manager → campaign map
   - `D:H` layout: key `campaign|slot`, kind, label (what each row SAYS)
   - `J:N` values: key `manager|weekISO|slot`, value as **display TEXT**
   - `P:R` goals: key `manager|slot`, value as text

**Values are TEXT on purpose** ("288", "6.4", "79%"): one slot is a count for
BOX and a rate for NDS, and a Sheets cell holds only ONE number format. The
grading CF compares `VALUE()` of the text against the goal. Weeks are Mon–Sun
keyed by the **Sunday ISO date** (matches the funnel's WK columns; row 2 holds
the date serials the formulas `TEXT(...,"yyyy-mm-dd")` against).

**Slot kinds**: `hdr` (ink super-band) · `band0-4` (TEAM/PRODUCTION/PRODUCT
MIX/QUALITY/NATIONAL, funnel stage palette) · `m` (automated) · `mm` (manual)
· `mg` (manual + goal + graded — Head Count) · `g` (auto + goal + graded —
weekly units, Sales per Rep). Goals live in violet cells; grading = green
≥95% of goal / yellow 90–95% / red <90%, colored-number style.

**Adding/changing a campaign's rows is a DATA change, not a build.py change**:
edit `layout.py`, run the stamper once (it rewrites the layout section), done.
build.py never needs to know. Zone capacity is `N_SLOTS = 44` rows.

## 3. The moving parts

| Piece | Where | Runs |
|---|---|---|
| Zone renderer | `automations/funnel_board/build.py` (`campaign_zone()`, `CAMP_Z0`) | inside every funnel_board rebuild (hourly, Lucy 2) |
| Layout + campaign map | `automations/org_campaign_metrics/layout.py` | imported by build.py AND the stamper |
| Store writer | `automations/org_campaign_metrics/sheet.py` (RAW upserts, merge-by-key, never deletes) | called by stamper/backfills |
| Daily stamper | `automations/org_campaign_metrics/run.py` (`--write`; dry by default) | Lucy 2 Report-Library card `org_campaign_metrics`, **daily 8:30 AM CT** |
| Pullers | `pull_b2b.py` (computed for all 13 b2b managers), `pull_box.py`, `pull_nds.py` | inside the stamper |
| History backfills (one-shot) | `backfill_carlos_b2b.py`, `backfill_box.py`, `backfill_nds.py` | manual, done 8/23 |
| Two-way edit sync | Apps Script "Goal Sync" bound to the workbook (source mirror: `automations/funnel_board/appsscript/goal_sync.gs`) | onEdit, human edits only |

**Why 8:30 AM**: after the Box Tableau extract lands (~7–8am). (The old
second reason — waiting for `captainship_boards` to fill `MT · Atef` at
6:30 — died with the MT copy on 9/7.)

**Typing on the sheet**: manual ✎ TEAM numbers go in the **WK column**; violet
goal cells in column B. The Goal Sync script catches the edit, writes it into
Campaign Log, and restores the formula — so typed numbers survive the hourly
wipe. Day cells are NOT tracked (v1 is weekly); typing there gets reverted
with a toast. Automated rows revert with a "this row is automated" toast.

**Goal semantics** (since 9/7, every campaign the same): goals are
**seed-only** — SPR goal seeds from the campaign's national average (newest
week), weekly-units goal seeds from HeadCount-goal × national SPR, and after
that the stamper never overwrites — typed goals live forever. (b2b goals
used to be stamped from the MT tabs; those copies are retired.)

**History**: production metrics are backfilled to WE 1/04 (Max Aden from WE
3/08 — his true first week on the NDS tracker, verified absent before that).
Ranks, acceptance/churn/drop rates CANNOT be backfilled anywhere — the
trackers compute them live and keep no archive. They accrue weekly from 8/23
forward via the stamper.

## 4. Deploy + test workflow

- Deploy: commit on the laptop → `git push origin HEAD:main` **and**
  `HEAD:resume-pushing-v2` (push BOTH — different Lucy checkouts have tracked
  each at different times) → queue `update` on Lucy 2 ("Mini Control -
  Lucy 2" tab of `1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw`) → the next
  hourly rebuild picks it up, or run build yourself (below).
- **Test on a copy first, always**: Drive-copy the workbook, then run
  build.py against it — `FUNNEL_SSID=<copy-id>` env plus a FUNNEL_DATA
  payload reconstructed from the copy's own Daily Log (harness pattern:
  scratchpad `rebuild_test.py` from 8/23; run.py's history loader is the
  recipe). The stamper takes `ORG_CAMPAIGN_SSID=<copy-id>`.
- Forcing a live redraw without waiting for the hour: same harness pointed at
  the live id — it re-renders from the existing Daily Log in ~2 min, no
  AppStream scrape. Safe because the loader reads the FULL log first (see
  §6, the 8/20 lesson).
- Manual stamper run: `python -m automations.org_campaign_metrics.run --write`
  (add `--only b2b|box|nds`, `--skip-tableau`). Dry run prints every tuple.

## 5. ⚠️ CHANGE PLAYBOOK — what typically breaks, and what to check

This is the section to re-read before ANY change. Each entry: the change →
what breaks → what we did / what to look for.

**Changing the recruiting funnel's length (adding/removing METRICS rows in
build.py)** → moves the zone off row 30, but the installed Goal Sync script
HARDCODES `CAMP_Z0 = 30` — typed goals would silently land on the WRONG
Campaign Log slots. build.py prints a loud `!! CAMPAIGN ZONE MOVED` warning
(it deliberately does NOT die — see next entry). Fix layout.py `ZONE_START`
AND re-install the updated goal_sync.gs together.

**Making build.py fail after the wipe** → the wipe (`updateCells fields:*` on
all five tabs) runs EARLY; any exception after it leaves the whole dashboard
BLANK until the next successful run. That's why the zone-moved check is a
warning, not a SystemExit. Never add a hard failure between the wipe and the
value flush. Related, the 8/20 pre-history lesson: a run that can't READ the
existing Daily Log must refuse to run, or it replaces months of history with
one day (run.py already guards this — don't weaken it).

**Renaming labels — anywhere** → almost everything in this system matches by
LABEL, not position:
- MT · Atef col-A labels → `pull_b2b._MT_TO_OURS`. Incident 8/23: the MT tab
  says "New Internet **Sales**" while the map had "New Internet" — six
  product-mix rows silently skipped (the puller logs
  `labels not found on MT tab (layout drift?)` — WATCH for that line).
- layout.py labels → pullers key on `slots_by_label()`; rename a label in
  layout.py and every puller that references the old string silently stops
  stamping that row. Grep the module for the old label before renaming.
- Focus-row labels on the Carlos 1on1s / captainship sheets are matched by
  label too (house-wide convention). Renames are how reports die quietly.

**Editing Campaign Log by hand / with USER_ENTERED** → values MUST stay text.
`valueInputOption=USER_ENTERED` coerces "79%" → 0.79 and "8.23"-style strings
→ dates, and then every zone lookup returns numbers the TEXT-formatted cells
render wrong and `VALUE()` grading half-works. All code writes RAW. If you
must hand-fix a value, prefix nothing, just make sure the cell format on
Campaign Log stays `@`/text (the Apps Script sets `setNumberFormat('@')`
before writing for exactly this reason).

**Two writers on Campaign Log at once** → upserts are read-merge-rewrite of
the whole J:N block; concurrent writers lose rows. The stamper (8:30am),
backfills, and the Apps Script all write it. Run backfills OUTSIDE the 8:30am
window; a lost typed-goal is recoverable by retyping, a lost backfill week by
re-running the backfill (they're idempotent).

**Tableau view changes (SmartCircle republishes constantly)**:
- **CHURNRATES (B2B)**: the BASE view auto-restores a broken team-filtered
  custom view that excludes most owners — always pull the **ALLTEAMCHURN**
  custom view URL (in pull_b2b). Same class of bug killed opt_phase_carlos
  on 6/01.
- **Multi-row crosstabs**: ACTIVATIONRATES/"Activation Office" and
  CHURNRATES/"ICD Churn" carry 3 rows per ICD with an UNNAMED subrow column.
  Incident 8/23: naive first-row matching grabbed 'Activated SPE/SP' (a
  count) as Carlos's churn → **375.0%** on the dashboard. Match the subrow
  ('Activation %' / 'Churn Rate'), never the first owner row.
- **BoxSalesMetrics**: its saved week filter LAGS (found pinned 8 weeks stale)
  — every pull must pin `?Sale Date Weekending=<ISO>` in the URL.
- **Box ORDERLOG**: the saved Contract ID quick filter re-pins itself to a
  stale snapshot; box_order_log's window hook force-releases it and forces a
  70-day date window at pull time. Screenshots/other consumers that skip the
  hook show truncated data.
- **NDS ORDERLOG**: saved Start/End dates drift (found pinned 5 weeks back) —
  always pass `?Start Date=&End Date=&Search Date Range=Order Date`.
- **NDS "Sales Week" filter is NOT URL-pinnable** (field name ≠ caption; ISO,
  M/D/YY and the fiber-style caption are all silently ignored). backfill_nds
  drives the filter in the UI and verifies every export against the
  crosstab's own week-ending banner — several stale mid-flight exports were
  caught only by that check. Copy that pattern for any week-driven NDS pull.
- **Worksheet renames**: crosstab pulls name the worksheet ("Sales Metrics",
  "ICD Churn", "Metrics Call Last week data (Internet)"…). A Tableau rename
  takes the report down for a day — the pullers log which sheet they asked
  for; check that first when a pull dies.
- **Date rows read FORMATTED can lose the year** ("8/23") — MT week headers
  are read as serials (UNFORMATTED) for exactly this reason.
- **Extract timing**: the Box extract lands ~7–8am CT; numbers pulled before
  that are yesterday's. NDS/D2D1 tracker lags ~a day on "today".

**Changing rosters** → org vs captainship vs CAMPAIGN_ONLY all live in
`funnel_board/roster.py` and are load-bearing in different views. Adding
someone to ORG puts them on EVERY org view (board, matrix, goals). Adding to
CAMPAIGN_ONLY puts them ONLY on the Focus Report picker (funnel rows read
zero — expected). Spelling must match the picker/Daily Log exactly — see the
name-variant table in each puller (e.g. Tableau says "ROSHAN AHMAD
[Sapphire Marketing]" / "MAXAMAD ADEN…"; picker says "Roshan Amin" /
"Maxamad-Amin Aden").

**Apps Script edits** → the installed copy in the workbook's bound "Goal
Sync" project is what runs, NOT the repo mirror — change both or they drift.
Install via Extensions → Apps Script, paste over Code.gs (clipboard trap:
use `LANG=en_US.UTF-8 pbcopy` or non-ASCII glyphs mangle — the '·' bug from
the captainship install). The onEdit is a SIMPLE trigger: fires for human/UI
edits only, never for API writes (that's why the stamper's writes don't loop).

**"Manual rows are blank" reports** → check whether they were ever typed
before debugging. Atef's Head Count/Leaders/People-in-Training render blank
because they're blank on MT · Atef too — nobody has typed them anywhere.
Blank-manual ≠ broken sync.

**Lucy 2 queue behavior** → single-threaded: a long queued job (e.g. an
8-chunk backfill) blocks EVERYTHING behind it, including hourly texting jobs
(bit us 8/26 — 7pm texts sat behind an ad_sales_board backfill until ~9pm).
Queue long backfills at night, or run them from the laptop directly.

**Scheduling anything time-critical on card_scheduler** → DON'T. Same
single-threaded problem, worse: a card only starts inside its
[time, time+20min grace] window, so any long-running earlier card that
swallows the window means the card silently never runs — no error, no
alert, data just stops (this took the stamper down 9/15–9/30 behind the
hours-long 7:50am ad_sales_board run). Time-critical daily jobs get a
STANDALONE LaunchAgent (pattern: `deploy/org_campaign_metrics.sh` +
`com.alphalete.org-campaign-metrics.plist` + an `install_<x>_agent`
registry entry, installed via `lucy rerun`); keep the card as a manual Run
button with its schedule stripped. Also: registering a card in the Report
Library is NOT enough — card_scheduler only fires ids that exist in the
day-orchestrator registry (schedule_config.json). Both, or it never runs.

**Long backfill chains** → one process per backfill. A second
tableau_session inside the same interpreter dies (TargetClosedError /
asyncio re-mint failure — 9/30). Chain separate `python -m` runs; never
loop backfills inside one script. And only ONE Campaign Log writer at a
time — upserts are read-merge-rewrite and concurrent writers lose rows.

**Deploy landed?** → never trust "push worked". Lucy 2's checkout must
actually pull (queue `update`, check the row result), or the next hourly
rebuild redraws the zone with OLD code and quietly reverts styling/geometry.
After any build.py deploy, verify one zone cell's format or the legend row
position on the live tab.

## 6. Verification checklist after ANY change

1. Rebuild the TEST copy; flip the picker through Carlos, Atef, Roshan,
   Khalil, MJ, and one UNMAPPED manager (zone must render fully / partially /
   empty respectively).
2. Check one graded row's chips against its goal by hand (VALUE math).
3. Type a number into a manual WK cell and a violet goal on the TEST copy →
   confirm it lands in Campaign Log and the formula restores. (On live, the
   next hourly wipe is the real test that typed data survives.)
4. Run the stamper `--only <campaign>` dry and read the tuple printout —
   watch for `labels not found` / `no ... column` / `pull failed` lines.
5. After deploy: confirm Lucy 2's `update` row says done, then after the next
   :05 rebuild confirm the zone still carries your change.

## 7. Incident / adjustment log

- **2026-08-23** — Initial build. Architecture chosen specifically because the
  hourly wipe destroyed anything placed on the tab directly (first design
  reality; everything data-driven since).
- **2026-08-23** — MT label drift: "New Internet" vs "New Internet Sales" et
  al.; six b2b product rows skipped until the map carried both spellings.
- **2026-08-23** — Carlos churn showed **375.0%**: naive crosstab parse took
  the 'Activated SPE/SP' count row instead of the 'Churn Rate' subrow. Fixed
  with subrow-aware matching + switched to the ALLTEAMCHURN custom view.
- **2026-08-23** — Zone-moved guard demoted from SystemExit to loud warning:
  dying after the wipe would blank the whole dashboard.
- **2026-08-23** — Round-2 restyle after Carlos review: everything centered,
  data bolded, harder rules, screenshot placeholder bands added to b2b;
  full-history backfills run (BOX agent stalled on the session lock; finished
  by hand — 34 wks all owners, Max from 3/08).
- **2026-08-23** — MT date-header row reads "8/23" (no year) under
  FORMATTED_VALUE → week detection rewritten to read row-2 serials.
- **2026-08-26** — Lucy 2 queue congestion: an 8-chunk ad_sales_board backfill
  queued at 6:49pm held the 7pm text_dispositions jobs ~2h (single-threaded
  poller). Lesson recorded above: schedule long backfills off-hours.
- **2026-09-07** — Captainship Dashboard found IN THE DRIVE TRASH (30-day
  fuse to permanent deletion) while the stamper still MT-copied it daily —
  trashed Sheets keep answering the API, so nothing errored. Carlos's call:
  the org Focus Report is the captainship's home now. b2b blocks flipped
  from MT-copy to COMPUTED (`pull_b2b.collect_computed`: one current-week
  ORDERLOG export tallied for all 13 managers at once + the activation/churn
  crosstabs read once for everyone — activation + churn now refresh daily
  for the owners, which the MT copy never did). Manual TEAM rows + goals no
  longer emitted at all: typed on the org sheet, Goal Sync owns them. The
  two NATIONAL rows froze at their last stamped values (follow-up: wire a
  tracker source). Campaign Log history untouched (upserts never delete).
  `captainship_boards` STILL writes the trashed workbook's MT tabs + the 11
  owner boards every morning — retiring that is the agreed next step, done
  deliberately, not in this change.
- **2026-09-07 (later)** — **Counting rule changed (Carlos): only what the
  D2D1 tracker counts is a sale** — NEW INTERNET + WIRELESS + AIR/AWB
  (`captainship_boards.config.COUNTED_PRODUCTS`). VOICE / TABLET-WEARABLE /
  VIDEO / UPGRADE INTERNET units in the ORDERLOG no longer count toward
  Total Apps, Sales per Rep, seller headcount, or rank — on the org computed
  blocks AND the captainship boards' parser (day cells, WeekData, Here
  marks: a tablet-only day no longer credits the rep). VoIP Line Count still
  sums from every row. Campaign Log history WE 1/04–9/06 re-stamped under
  the new rule (`backfill_counted_rule.py`; sales-count slots only — the
  CRU/ABP/BYOD % history, activation/churn, nationals, TEAM rows and goals
  were left as stored). Board WeekData HISTORY was NOT recomputed — boards
  count the new way from 9/8 forward.
- **2026-09-30** — **The daily stamper had silently never been on a working
  schedule.** Carlos reported missing prior weeks; the Campaign Log stopped
  at WE 9/20 for everyone. Two stacked causes: (1) the 8:30am Report-Library
  card's id wasn't in the day-orchestrator registry until 9/14, so
  card_scheduler never fired it — every stamp 8/23→9/14 was actually manual;
  (2) after registration it STILL never fired, because card_scheduler is
  single-threaded and the 7:50am ad_sales_board card now runs for HOURS
  (9/30: 7:50am→2:04pm), so the 8:30 slot's 20-minute grace window expired
  every morning. WE 9/21–9/27 was lost. FIX: standalone LaunchAgent
  `com.alphalete.org-campaign-metrics` (daily 8:30am CT,
  `deploy/org_campaign_metrics.sh` --write, Slack alert on failure,
  installed via `lucy rerun install_org_campaign_metrics_agent`); the card
  survives as a manual Run button only (schedule stripped — captainship
  precedent). Data repaired the same day: WE 9/27 b2b restamped for all 14
  owners from a fresh ORDERLOG window pull; Nicolas Lujan's history
  backfilled (his first order-log week is genuinely WE 8/30); BOX/NDS missed
  weeks re-pulled. The rolling quality rates (activation/churn/acceptance)
  for the lost week are unrecoverable as always — they accrue live only.
- **2026-09-30** — KNOWN GAP (accepted): WE 9/27's secondary BOX slots
  (rep counts, ELE/Gas, kWh) and NDS AIR split are blank — the mini's
  Tableau crosstab downloads currently die at Download.save_as (fresh
  process, warm session — laptop-specific; Lucy 2's identical pulls work).
  Core production for 9/27 IS there (b2b full, BOX/NDS sales + SPR). To
  close the gap: registry-register the backfill scripts and run them via
  `lucy rerun` on Lucy 2.
- **2026-09-30** — Sequential backfills in ONE process crash after the first:
  the second `tableau_session` in the same interpreter dies
  (TargetClosedError / "Playwright Sync API inside asyncio loop" on the
  re-mint). Run each backfill as its OWN process — a shell chain of separate
  `python -m` invocations is fine; sharing one interpreter is not.

## 8. Still open / future wiring

- **Screenshot bands** (b2b blocks): placeholders only. Real wiring needs
  per-manager hosted PNGs (b2b_metrics `sales_metrics` images) + an
  `=IMAGE(INDEX(...))` lookup rendered by build.py — static images can't live
  on a picker-driven tab.
- Day cells in the zone are empty by design (weekly v1); the order logs could
  feed them later.
- BOX "Reps in DNQ tier / 1 sale away" and Khalil's NDS captain volume-tier
  row were scoped out of v1 — data-only additions when wanted.
- TEST copy `1aq6A9NXkajZlJoF2jHA7JYOaQ8TJ9GmfebDKyqQpSjk` still in Drive —
  trash after Carlos confirms, or keep as the standing test bed.
