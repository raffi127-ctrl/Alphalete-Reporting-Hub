> **CANCELLED 2026-10-29** — Carlos: "cancel that automation completely". Agent unloaded 10/28; the README daily task and the Box Notes email sweeps were deleted 10/29. The tabs are frozen records.

> **RETIRED 2026-10-28** — Carlos: "the whole thing can go". The LaunchAgent `com.alphalete.box-order-log` was unloaded on Lucy 2 (`rerun remove_box_order_log_agent`); nothing below runs any more. Restore with `rerun install_box_order_log_agent`. The Vantura 'Lucy Box Order Log' tab is frozen as of 10-28. Other owners' email runs (box-order-log-owners / per-office) are unaffected.

# BOX Order Log — how it all works
_Started 2026-09-05 from the El Meson / TPV-memory session. Auto-updated daily
at 7pm by scheduled task `box-readme-daily-update`. Companion to
`LUCY2-OPERATIONS-README.md` (queue protocol / deploy flow) and
`VANTURA-BOARD-README.md` (the board this report writes into)._

## 1. The one-paragraph model

Every morning Lucy 2 pulls Carlos's **BoxOrderLog** Tableau view
(`B2BBOXEnergyTracker → BoxOrderLog → CarlosOrderLog`), collapses the raw
status-transition rows into one row per sale, and delivers to three places:
the **"Lucy Box Order Log"** tab on the Vantura Master Sales Board (a rolling
6-week merged log), a **Slack thread** in #alphalete-gp-sales + #a-players-b2b
(workbook, payout image, pending image, tier board), and an **xlsx archive**
on disk. Code lives in `~/recruiting-report/automations/box_order_log/`
(repo `raffi127-ctrl/Alphalete-Reporting-Hub`); it runs ONLY on Lucy 2 —
the pull needs Carlos's Tableau session, and the Slack replies must come from
Lucy's token.

## 2. Schedule and delivery rules

- **LaunchAgent** `com.alphalete.box-order-log` on Lucy 2: **7:00am and 8:30am
  CST, daily incl. weekends** (Carlos's exact ask, 7/18). Wrapper:
  `deploy/box_order_log.sh`.
- **Exactly one Slack post per day.** The wrapper writes a dated marker
  (`output/logs/.box-order-log-posted-<date>`) only after a successful post;
  8:30 sees it and refreshes the sheet only. If 7:00 dies, no marker → 8:30
  posts. Never two. Since 8/17 the module ALSO enforces this itself
  (`day_marker.py`) because `lucy rerun --post` walks straight past the
  wrapper's check — that double-post actually happened on 8/17.
- **Freshness gate**: the 7:00 pass runs `--require-fresh`; if the extract
  hasn't reached the latest completed day it exits 3 (no post, no marker) and
  8:30 is the fail-open floor. A 7:03 post therefore PROVES the source was
  fresh — useful when someone suspects staleness (checked exactly this way
  9/5).
- If the **8:30** pass also fails, `section_drop_alert` posts to
  #claudecorrections-and-requests. A 7:00 failure alone is silent by design.
- **Thread naming**: since 9/5 the parent is short — "**Box Metrics — <date>**",
  title-only; the section list is the first reply (Carlos: "I don't like how
  long that message is"). Finders (`sales_boards.box_thread_ts`,
  `backfill_tier.find_parent`) accept the old "BOX Order Log — <date>" title
  as fallback. **When editing thread code, keep both titles findable.**

## 3. The status pipeline (clean.py) — what counts as a sale

Raw export = one row per STATUS TRANSITION, keyed **Contract ID + Account Id**
(Contract ID alone is NOT unique — one contract can span multiple meters).

Gates, in order:
1. **Draft** (`JUNK_STATUSES`) — tablet-quote noise, dropped. The junk filter
   is `Draft`, NOT `Complete Sales = 0` — the latter once dropped 16 real
   deals sitting in Verification.
2. **Collapse** — group by key; surfaced status = highest `LEVEL_PRIORITY`;
   full history kept (feeds "Secondary Status").
3. **Dead levels** — `Verification/TPV Failed` and `Rejected QC` drop, UNLESS
   the deal ever said TPV Passed (see rule below).
4. **TPV gate** — a deal is a sale once it reached TPV or beyond
   (`SALE_LEVELS`). Carlos 7/22: "TPV completed and forward is a sale, but it
   could go to cancelled by broker at any point." Exemptions: `Incomplete`
   (Megan keeps it), sub-status "Rejected By Supplier" alone (Carlos 8/27: if
   the supplier rejected it, it got there).

**The 8/28 rulings (Carlos):**
- **"If it ever said TPV passed, it should never get removed from the order
  log unless we're past the date range."** Implemented as `TPV_PROVEN_LEVELS`
  (= SALE_LEVELS minus "Requires TPV Review" — review still owed ≠ passed).
  Applied BOTH in `clean.collapse` and in the sheet's merge purge — fixing
  only one is not enough, the other deletes it on the way through.
- **Sales weeks are Monday–Sunday.** `--rep-day` uses Mon–Sun. ⚠️ OPEN: the
  log's own `week_ending()` is still Sun–Sat (inherited from Raf's Fiber log,
  never confirmed with Carlos) — so is `payout.py`'s pay week (documented as
  deliberate in `shared/report_week.py`). Changing them relabels historical
  weeks and shifts payout buckets — needs its own ruling. Practical impact:
  Sunday sales (~0.6%) bucket into the following week.

## 4. THE TPV MEMORY — why it exists (the El Meson story)

**Tableau ERASES history.** El Meson Doña Tere (ctr 278285): showed
Verification/TPV Passed on 8/14–8/19; by 8/23 the export carried only
`Draft` + `Cancelled by Broker` — the TPV row was gone. The history-reading
gate then saw "cancelled before TPV" and dropped a real sale. 24 sales were
lost this way at the time of the fix; the flattening also hits deals whose
only surviving row is `TPV Failed`.

Two memories now back the gate (unioned, in `run.py`):
- **The sheet** (`sheet.tpv_seen_keys` / `tpv_proven_keys`) — reads Status +
  Secondary Status off "Lucy Box Data". Only remembers ~6 weeks, and the OLD
  purge used to delete failed-after-passing rows, erasing its own evidence.
- **The crosstab ledger** (`tpv_ledger.py` → `output/box_tpv_ledger.json` on
  Lucy 2) — every run since 7/18 archives its raw pull as
  `output/box_order_log_<date>.csv`, nothing deletes them; the ledger walks
  that archive and records every key EVER seen at TPV+ (with dates,
  `tpv_proven` latches). It only GROWS (rebuild unions; atomic tmp-rename
  write). Nothing regenerates it if lost — it is evidence, not derived state.

Rescued deals surface at their CURRENT status (El Meson returns as the cancel
it is, not a phantom TPV Passed) — which also heals the sheet's stale rows.
Fail-open: an unreachable sheet/ledger = old behaviour, announced in the log
("TPV memory empty — rescues are off"), never a dead report.

Diagnostics (`lucy rerun box_tpv_ledger …`): `--build` refresh; `--erased
[--to-tab]` = deals vouched for that today's export no longer shows (tab
"Box TPV Erased" on the queue sheet); `--dead-check [--to-tab]` = for every
deal surfacing TPV Failed/Rejected QC, does the ledger prove a pass? (tab
"Box TPV Dead Check"). Run 8/28: 0 proven / 6 review-only / 34 never-seen —
the immunity rule keeping zero was CORRECT, not broken.

## 5. The Google Sheet (sheet.py)

- Board id `1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY`; tabs
  **"Lucy Box Order Log"** (view) + hidden **"Lucy Box Data"**. Only these two
  are ever written (`PROTECTED_TABS` guard).
- **MERGE, never overwrite**: the Tableau view is a rolling ~44-day window, so
  rows age out of the SOURCE before the report — a sale missing from today's
  pull is KEPT; one in both is replaced (fresh pull is authoritative);
  >6 weeks ages out; carried rows are re-tested against current rules
  (with TPV-passed immunity since 8/28).
- Merge key is digits-only (`_norm_id`) — Sheets number-formats "267770" into
  "267,770", which once duplicated every row. ID columns are pinned to TEXT
  format on each write for the same reason.
- View tab: week dropdown (B2) + per-rep COUNTIFS summary + FILTER spill.
  Spacer rows carry the week in col A and Filter Week (col O) so the color
  rule can paint them as divider bars — merge skips them by empty key.
  The write preserves whichever week the dropdown has picked.
- Week label on this tab is the SATURDAY (Sun–Sat legacy — see §3 open item).

## 6. The Slack artifacts

| Artifact | Module | Notes |
|---|---|---|
| Workbook (one tab per rep) | `xlsx.py` | FULL pull, not the 6-week window |
| Payout image (2 week tables) | `payout.py` + `png.py` | Pay week = when the supplier ACCEPTED, not when sold — deliberately different from the log's sale-date week. Sun–Sat. |
| Pending orders image | `pending.py` + `pending_png.py` | One model, two surfaces (also the workbook tab) — logic split out 8/25 so they can't disagree. Yellow (Ready For Booking) excluded from the image. |
| Tier board | `tier_bonus.py` | Screenshot of Tableau "Box Tier Bonus - Rep Level", sliced to the owner via URL |

Related handles: `box_order_log_repost` (re-post today's workbook into the
existing thread — never a second thread), `box_order_log_tier_backfill` (add
the tier board after the fact), `box_order_log_roshan` / `_abel` /
`_per_office` (per-owner runs via `run_owner.py`/`per_office.py` — these run
on the MINI: Carlos's Lucy 2 session is self-scoped and only sees his rows).

## 7. Counting subtleties that keep coming up

- **Log week = SALE date; payout week = ACCEPTED date.** Mixing them once
  showed "41 sales" in a 29-sale week. Never merge the two.
- **Multi-meter deals**: one row per meter. G Tech Precision (8/25): 2
  contracts × 4 meters = 8 rows for one business — Sandy's day read 8. A
  day's "sales" can legitimately be counted as rows / distinct contracts /
  distinct businesses; say which. (Open question for Carlos.)
- **Same business ≠ same sale**: businesses re-sign under new contract IDs
  (El rios bodyshop ×3). The KEY is Contract ID + Account Id.
- **Vantura Revenue Board Week Total ≠ sum of day cells — by design**: the
  Tiered Volume bonus is weekly and rides only in the total
  (`vantura_revenue_board/run.py`). Carlos asked why on 9/5; a Bonus column
  is the suggested fix (not yet built).
- `--rep-day [--tpv-only] [--to-tab]` prints a rep × day grid (Mon–Sun, sale
  date) without writing anything.

**DD reconciliation (proven 9/13):** the revenue board's LAST WEEK (Mon-Sun,
TX Grid before the 9/7 sales cutover / New Comp after, volume bonus included)
matches the week's DD to ~99% — Kandice reconciled line-for-line. The small
remainder is the DD's "random disposition" line, which is NOT counted toward
reps (Carlos 9/13) — do not chase it as a bug, and do not "fix" the board to
absorb it.

## 8. When you change something, THESE break (lookout list)

1. **Anything touching the sale gates** → run the module tests
   (`PYTHONPATH=. python -m unittest automations.box_order_log.test_tpv_memory
   test_pending_and_submitted test_window_filters` — 50+ tests). The gates
   feed COMMISSION artifacts; a silent filter is worse than no report.
2. **A gate change must be applied twice** — collapse AND the sheet merge
   purge re-test carried rows. Fixing one side loses the row on the other
   (exactly how the old purge erased the sheet's own TPV evidence).
3. **Sheets coercion**: write RAW/pinned-TEXT or IDs grow thousands
   separators and the merge key breaks (dup-everything, 7/18). USER_ENTERED
   coerces "July 2026"→serial, "8.30"→8.3.
4. **The Tableau view's saved filters DRIFT** (`window.py`): Start/End Date
   pinned to a 2-day window (8/1); Contract ID/Account Id pinned to a frozen
   44k-checkbox include-list (8/7 — export stuck at 7/30 for 8 days); the
   filter re-rendered as a collapsed dropdown reading "Multiple values"
   (8/17 — probes saw "no filter", cost days: hidden ≠ removed). Every pull
   now releases filters then widens dates, in that order. If a whole day/rep
   vanishes, suspect THIS before the gates. `(All)` only flips via
   focus+Space, not clicks.
5. **An empty-but-valid AppStream/Tableau export exits 0** — headers, no
   rows, indistinguishable from "nobody applied". Guard with an arithmetic
   identity (ad_sales_board's day-counts-vs-week-total is the model) or a
   freshness probe; never trust exit 0 alone.
6. **Don't kill the shared CDP Chrome** — box_order_log shares it with
   att_order_log and captainship_boards (orchestrator order 10001 exists
   because of this). `source_type: local` jobs skip chrome_guard; use it for
   read-only handles.
7. **Retries/reposts must be idempotent** — dated markers (`day_marker.py`),
   caption-marker dedupe (`repost_workbook`), "already in thread" checks
   (`backfill_tier`). Any new sender needs the same or 8/17 repeats.
8. **`lucy rerun` appends the registered `base_args`** (`--sheet --xlsx`) —
   a "dry" rerun still WRITES. Use `--no-sheet` (added 8/28) for a real-data
   dry run, or `--inspect <text>` (read-only raw-row dump, returns before any
   write).
9. **Queue Result cell truncates ~450 chars keeping the TAIL** — long output
   goes to a queue-sheet tab ("Box TPV Erased", "Box TPV Dead Check",
   "Box Rep Day") and gets read from the mini. Make the last printed line the
   one that matters.
10. **schedule_config.json: edit as TEXT, never re-dump the JSON** — a
    json.dumps rewrite reformatted ~400 unrelated lines; an unmerged copy of
    this exact file killed Lucy 2's whole 4am orchestrator on 8/27. Insert
    surgically, verify with a semantic diff (parse old vs new, compare
    reports keys).
11. **Deploy = `git push origin HEAD:main`** from the mini (working branch
    is `split-boards`; plain `git push origin main` pushes the stale local
    main and is rejected). Lucy 2 tracks MAIN since ~8/28 — the old
    "resume-pushing-v2" rule is dead; that branch has diverged and its
    non-ff rejection is harmless. Verify a deploy by logtail, never by
    "Already up to date" (which can mean "already pulled" OR "tracking
    branch didn't move" — check `git_status` HEAD).
12. **Long-running queue jobs block everything** — the poller is
    single-threaded; a 34-week funnel backfill held box jobs for ~2h on 8/28.
    Queue behind it and wait; re-queueing just lengthens the line.
13. **Thread-title changes break finders** — repost/backfill/sales_boards all
    locate today's thread by parent title. The 9/5 rename kept the old title
    as a fallback; do the same for any future rename.
14. **Run `date` before any "today/yesterday/this week" reasoning** — these
    sessions span days (this one crossed 8/28 → 9/5 twice); a stale clock
    produced a wrong-week rep grid.

## 9. Open items

- Sun–Sat vs Mon–Sun week for the log's `week_ending()` + payout (§3) —
  awaiting Carlos's call on scope (log only / log+payout / +AT&T log).
- Multi-meter counting rule (per meter vs per contract vs per business) —
  G Tech makes rep counts ambiguous.
- 6 "Requires TPV Review → failed" deals (I&M Auto, Numix, G Tech ×4, 8/25–26)
  excluded from immunity; one-line change if Carlos rules they count.
- Bonus column on the Vantura Revenue Board so Week Total visibly sums.
- Whether "Incomplete" should count as TPV evidence (2 of the 35 erased-list
  deals rest on it; Megan's rule says yes, weaker than the other 33).
