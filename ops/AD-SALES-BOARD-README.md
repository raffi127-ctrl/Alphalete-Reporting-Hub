# Ad Sales Board — how it works, and what breaks when you change it

_Master reference for the Ad Sales Board on the Alphalete Recruiting Dashboard.
Auto-updated daily at 7pm by the scheduled task `ad-sales-board-readme-daily`
(new changes, new gotchas, new tab behavior). Built 2026-08-26 → 2026-09-03;
this file exists because nearly every change below broke something non-obvious,
and next time we should know in advance._

Companions: `LUCY2-OPERATIONS-README.md` (queue/deploy machinery),
`RECRUITING-DASHBOARD-README.md` (the whole workbook),
`automations/ad_sales_board/README.md` in the repo (code-facing).

---

## 1. What it is

One visible tab, **Ad Sales Board**, on the Alphalete Recruiting Dashboard
(`111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`), fed by hidden **Ad Sales
Data**. It answers: *per ad, per day, how many applicant emails did we
receive — and how does that stack week over week?*

- **One stacked scroll** — every Mon→Sun week of 2026 for the picked manager,
  newest first. No week dropdown. Each block opens with a blue **WEEK ENDING
  m/d** band, closes with a grey **TOTAL** row.
- Grid: `# | Account | City | AD | Pull | Mon..Sun | To Call List`. Day cells
  = emails **received** that day. Pull = the week's received total (from the
  weekly report). To Call List = the source report's weekly sent-to-call-list
  count.
- Pickers: **B1 manager**, **D1 Org/Captainship**. Everything centered, bold
  11pt; Account+City+AD carry one **color per account**, held down the whole
  scroll (14 tints, assigned by first appearance, newest week first).
- Amber row = call-list names that matched no ad. Blank day cell = "never
  read" — **never** confused with 0 = "read, nobody came".

## 2. Where the numbers come from

| Piece | Source | How |
|---|---|---|
| Weekly Pull, To Call List, ad rows | AppStream Source Report p=702, one 7-day pull per office | same fetch/parse as the monthly Source Report - Indeed (variant merge, junk filter, city rule, `CITY_AGNOSTIC` for Carlos/Jamis) |
| Day cells (received/day) | p=702 pulled as ONE-DAY windows | each morning pulls **yesterday**; `--day mm-dd-yyyy` backfills; a day is only final once it's over, so **today is always blank until tomorrow's 7:50 run** |
| Names (data col J, not displayed) | old tracker's Call List tab (applicant_tracker import, 6:45am Lucy 1) | org offices only; Saturdays never imported upstream |

Data tab layout: rows live in **A..S plus AC..AI** (AC..AI = received/day).
**T..AB are helper columns (manager/week lists, rosters, dropdown feed) — a row
write must NEVER touch them** (see §4, the collision that taught us).

## 3. Schedule & operations

- **Every 2 hours, 7:50am–9:50pm** (launchd `com.alphalete.ad-sales-board` on
  Lucy 2). Refreshes current + previous week + pulls yesterday's day counts +
  heals any short week in the last 14 days. Overnight it's silent on purpose.
- The wrapper **self-updates from GitHub main** at each tick (60s alarm — §4).
- Backfills/repairs go through the **Mini Control - Lucy 2 queue**:
  `rerun ad_sales_board --office <id> --anchor <wk>` / `--day <d>` /
  `--allow-shrink` / `--heal-days N` / `--reset`.
- **Standing rule (Carlos, 9/1): never drive ApplicantStream from two
  automations at once.** applicant_push walks offices 7am–10pm on the same
  session — heavy backfills wait for the **10:05pm quiet window** (pattern: a
  held queue row + a local deadman script that flips it to `queued` at 22:05).
  A one-click task chip exists for the real fix (a shared AppStream lock).
- Layout rebuild: `build_tab.py --force-view` (laptop) — never touches data
  rows. Data semantics changes: `run.py` + push to main + queue `update`.

## 4. THE CHANGE LOG — what we changed, what it broke, what to watch for

Every entry: the change → what broke → the guard that now exists. **Read this
before making a similar change.**

### Week definition (Wed→Tue changed to Mon→Sun, 8/26)
- Week **labels are the join key** across runs. Changing anchor day or label
  format orphans every stored row: old weeks stay forever (freeze rule keeps
  unmatched pairs) and the picker fills with dead labels.
- **Playbook:** any week re-definition = `run.py --reset` + full-year re-pull.
  Done once; cost a full night. Don't do it casually.

### The received-per-day grid (8/27–8/28) — four incidents in a row
1. **Helper-column collision.** First cut stored day counts in T..Z — right on
   top of W/X/Y/Z (manager list, rosters, dropdown feed). Symptoms: roster
   text inside day cells, manager dropdown dead. Fix: day grid moved to
   AC..AI; row writes are TWO ranges (A..S and AC..AI) skipping T..AB.
   **Watch for:** any new data column must dodge T..AB, and check
   `grep -n "AA\|AB\|W2" build_tab.py run.py` before adding one.
2. **Empty-but-valid reports.** AppStream sometimes answers a one-day report
   as a valid table with NO rows — indistinguishable from "nobody applied",
   exits 0. ~1 office-day in 30. Fix: re-submit an empty day once; still-empty
   stays **blank, never 0**; the **heal pass** re-pulls missing days of any
   week whose days don't sum to its weekly total (identity makes it converge).
3. **Join drift.** A 1-day window merges fewer title variants than a 7-day
   one, so the same posting can carry a different base role → counts silently
   dropped (Carlos's April weeks landed ~25%). Fix: fuzzy join — exact
   (inbox+base+city), else sole-ad-on-inbox, else closest title ≥0.5 Jaccard;
   below that it refuses and **names the unmatched inbox|title in the log**.
4. **Clear-before-reapply.** Re-pulling a day left its old value on the ad it
   used to credit while the new value landed elsewhere → double count (weeks
   swung from under to over). Fix: every slot a run re-reads is cleared across
   the week's ads before applying; empty days deliberately not cleared.

### Wrong-office contamination (8/31–9/1) — the big one
- The AppStream session is **shared**; applicant_push switches the selected
  office every few minutes. A report submitted mid-switch renders a perfectly
  valid page **for the wrong office**. Carlos's board nearly got Atef's
  numbers; only the shrink guard stopped the write.
- Fix: every pull checks the **owner name on the page** against the roster
  spelling for the requested office and raises loudly on mismatch (token
  overlap, because spellings drift: "CARLOS HIDALGO", "Muhammad UI/Ul Haque").
- **Watch for:** any NEW report that pulls AppStream needs this same check —
  the page always looks valid. And data written **before** 8/31 can still hold
  contaminated values (Jackie's Aug 17/24 did): symptom is one manager's week
  total suspiciously equal to another's.

### The shrink guard, and its two lessons (8/29–9/3)
- **Guard:** emails only accumulate, so a fresh weekly pull SMALLER than the
  stored total is a short/contaminated pull → rejected, stored week kept
  (`--allow-shrink` overrides).
- **Lesson 1 — churn tolerance:** AppStream history drifts DOWN a few emails
  (server-side spam/dup removal). A 1077→1072 pull is churn, not a short
  pull; rejecting it froze a bad week. Now only >2% AND >10 emails rejects.
- **Lesson 2 — the guard can defend corrupted data:** when the STORED value is
  contamination-inflated, the guard rejects the *correct* smaller pull. If a
  week refuses to fix itself, read the run's "SHORT PULLS REJECTED" lines —
  if the pulled number matches the manager's pre-incident history, it's the
  truth: re-run that office with `--allow-shrink`.
- **Also:** rejected weeks silently skip the end-of-run reconciliation table —
  a run can print "reconciles" while a rejected week sits wrong. Check the
  REJECTED lines, not just the reconcile line.

### Queue behavior (8/27, bit us twice more since)
- `poll_once` **snapshots the queue at pass start**. Flipping a row to "hold"
  mid-pass does nothing — the poller runs it anyway and overwrites the cell.
  Holds only work against rows a FUTURE pass reads. A long serial pass blocks
  everything behind it for hours. (Fix chip exists: re-read Status per row.)
- Queue reruns of appstream-type reports fire `chrome_guard.close_stray_chrome()`
  at start — it SIGTERMs any Chrome without the automation marker, including
  the push walks' CDP Chrome. Backfill bursts = repeated push-browser kills.
- Only ONE ad_sales_board can run at a time (both the wrapper pgrep guard and
  mini_control's own guard). A batch of queued rows behind a running one fails
  instantly with "ALREADY running" — that's fine (nothing pulled); re-queue.

### Scheduler / wrapper (9/3)
- The wrapper's self-update `git pull` had no timeout; one hung pull ate the
  7:50 and 9:50 ticks **before the log line**, so the schedule died with no
  trace (Wednesday went unfilled until a manual run). Fix: `perl alarm 60`
  around the pull (macOS has no `timeout`). **Watch for:** "no log file at
  all" = the wrapper died before logging — check for hung wrappers and
  reinstall the agent (`rerun install_ad_sales_board_agent`), don't stare at
  run.py.
- Remediation that works remotely: queue `rerun ad_sales_board` (fills the
  gap), then `rerun install_ad_sales_board_agent` (bootout+bootstrap kills
  hung wrappers), then verify the NEXT tick wrote
  `output/logs/ad_sales_board_YYYYMMDD.log` — never trust "reinstalled ✓".

### Sheets API flakiness (9/1, 9/3)
- Transient read-timeouts AND transient 404s come in bursts; the preflight
  probe retries 3× 20s apart but a bad enough burst still kills queued rows
  with exit 3 ("cannot write the workbook") — **that message usually means
  network, not permissions**. Nothing was pulled; plain re-queue.
- 60 writes/min/user; USER_ENTERED coerces ("July 2026"→date) — this module
  writes RAW everywhere on purpose.

### The laptop cannot reach AppStream (9/1, proven)
- Since AppStream's 8/20 release: saved sessions die, the login form has an
  interactive human check, and even a fresh ownerville SSO handoff is rejected
  server-side. **Every automated path from the laptop is dead.** Backfills run
  on Lucy 2 (warm rcaptain session) or after a one-time human login:
  `PYTHONPATH=. .venv/bin/python -m automations.shared.tableau_patchright --appstream-login`.
- Related fix that stays: rqst tokens can contain **underscores** as well as
  hyphens (TOKRE); a truncated token reads as "Your login is timed out".

### Still open
- **Monthly Source Report - Indeed undercounts**: real applications arriving
  as "[Action required] New application for …" are junk-filtered there (this
  board unwraps them; hundreds per full run). Fixing the monthly parser moves
  its numbers UP — Carlos's call, not yet made.
- Captainship-only offices (11) have Pull but no names (no Call List feed);
  Saturdays missing upstream for everyone.
- Fleet history: org is complete (all 17); the 11 captainship-only offices
  still have ~16 empty weeks each before May 25 — overnight batch on request.

## 5. How to verify (never trust "done")

- Every run prints a **reconciliation**: each finished week's day cells must
  sum to its weekly Pull. Read it with
  `logtail ad_sales_board <pattern> N` — plus the "SHORT PULLS REJECTED" and
  "[recv] … dropped=" lines.
- Sheet-side spot check: pick a manager, a finished week — days across should
  equal Pull. 26–29 of 29 offices reconcile exactly on a healthy day; a WHOLE
  day blank across every ad = a failed day pull (heal fixes within 14 days);
  a week that won't converge = shrink-guard/contamination (§4).
- The three invariants that catch everything: **days sum to the week · a week
  never shrinks (beyond churn) · blank ≠ zero.** Every real data bug so far
  tripped at least one of them.

---

## Change journal (auto-appended; newest first)

- **2026-09-03** — Morning ticks dead (hung self-update git pull, no log);
  manual fill restored Wednesday fleet-wide by 11:00, agent reinstalled, 60s
  alarm added to wrapper, 11:50 tick verified live. 4 overnight rows lost to
  Sheets 404 burst (Isaiah/Kash/Roshan backfills + Cody fix) — re-staged for
  22:05. Per-ad/per-day week-pace report built for Raf (artifact).
- **2026-09-02** — Org backfill: Aya/Cody/Cyrus daytime (Carlos approved
  overlap), 10 org offices + Jackie contamination fix overnight. Jackie's
  Aug 17/24 confirmed contaminated (stored=Carlos's totals); fixed via
  --allow-shrink. Churn tolerance added to shrink guard.
- **2026-09-01** — Wrong-office contamination discovered and guarded; shrink
  guard caught it; probe retry added; four-office backfill (Carlos, Rafael,
  Jackie, Khalil) completed; no-overlap-with-pushes rule established.
- **2026-08-31** — Laptop AppStream access proven dead (human-check + SSO
  rejection); TOKRE underscore fix; all backfills moved to Lucy 2.
- **2026-08-28/29** — Received-per-day shipped (AC..AI after the T..Z
  collision), fuzzy join, clear-on-repull, empty-day retry, heal pass,
  reconciliation report. Account color-coding; full-row tint tried and pulled
  back to Account+City+AD.
- **2026-08-27** — Stacked scroll replaces week dropdown; Mon→Sun weeks
  (full-year --reset re-pull); Account/City moved left of AD; queue
  stale-snapshot hold flaw found.
- **2026-08-26** — Board born: weekly view, sales-board dress, day-by-day
  names, 2-hourly schedule, full-2026 backfill.
