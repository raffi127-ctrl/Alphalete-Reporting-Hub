# Recruiting Stack README — how it all works, and what breaks when you change it

Canonical copy: `docs/RECRUITING-STACK-README.md` in the Alphalete-Reporting-Hub repo
(Desktop READMEs have vanished before — the repo copy is the one that survives).
Auto-updated daily at 7:00 PM by a scheduled Claude task (see bottom).

Last full rewrite: 2026-09-06 (Carlos asked for a single reference: how everything
works + what typically breaks after a change, so the next change starts here).

---

## 1. The map

| Piece | Where |
| --- | --- |
| The workbook | **Alphalete Recruiting Dashboard**, Sheets id `111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA` |
| The code | this repo (`raffi127-ctrl/Alphalete-Reporting-Hub`), checkout `~/recruiting-report` on the mini |
| The runner | **Lucy 2** (MacBook). No SSH — driven only via the Google-Sheet queue (`1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw`, tab "Mini Control - Lucy 2") |
| Bound Apps Script | "Goal Sync" project on the workbook — goal two-way mirror, Ad Plan format mirror (`adPlanMirror_`), campaign-zone logic |
| The website | "Alphalete Recruiting Hub" Apps Script web app (standalone project, Carlos's account) serving 8 tabs read-only; allowlist in its Code.gs |
| Logins | **Megan's Lucy Login Standard is authoritative.** AppStream = `Lucy Reports` everywhere + `Lucy Resume Pushing` (resume pusher only, Lucy 2). OwnerVille: Lucy 2 = Carlos, Lucy 1/3 = Raf. Cloudflare clears itself with the 30s pre-submit waits — nothing "needs a human". Check both logins with `lucy login_check --machine "Lucy 2"`. |

## 2. The visible tabs and what feeds them

| Tab | Fed by | When |
| --- | --- | --- |
| Recruiting Dashboard | `funnel_board` (AppStream Retention pulls, 28 offices) + AD BUDGET box ferried by `tracker_mirror` | 1:00 AM chain + 1:00 PM chain |
| Goals | hand-edited + two-way mirror with Focus Report goal column (Apps Script "Goal Sync") | on edit |
| Focus Report | `funnel_board` build (recruiting funnel) + `org_campaign_metrics` (campaign/sales blocks, rows 30–73 via hidden 'Campaign Log') | 1 AM / 1 PM; campaign stamper separate |
| Source Report - Indeed | `indeed_source_report` — AppStream p=702 source report per office, current month | 1 AM + 1 PM chains |
| Ad Plan | ONE tab mirroring per-manager hidden tabs (17 live IMPORTRANGE from personal trackers + 4 via the old workbook chain); B1 picker + `adPlanMirror_` re-dresses formats on flip | live (IMPORTRANGE) |
| Ad Sales Board | `ad_sales_board` — stacked Mon→Sun weeks, names per ad per DAY from one-day p=702 pulls | daily in the chains |
| Manager Matrix | funnel_board build (every manager × week, metric picker B1) | with funnel_board |
| City Zip Code Research | hand/one-off research + hidden 'City Zip Data' | manual |
| Sales Board / Roll Call / Stations / Daily Update / Leaders Retention | migrated captainship views; `captainship_boards` 6:30 AM fill, `daily_update_fill` 8:45 PM, week stamp written daily by captainship_boards (RAW, see §4) | daily |

Hidden load-bearing tabs: per-manager first-name tabs (Ad Plan sources), `Indeed Ad Data`,
`Ad Sales Data`, `Campaign Log`, `Daily Log`, `WE`, `City Zip Data`, `Mirror Config`,
`SRC WD`/`SRC RCD`, `0Config`. **Do not delete or "clean up" hidden tabs** — most
formulas on the visible tabs point into them.

## 3. The schedule (all times Lucy 2 local, CST)

- **1:00 AM** — `recruiting_chain.sh full`: funnel_board → indeed_source_report → ad_sales_board (sequential; ~40–45 min total)
- **1:00 PM** — `recruiting_chain.sh refresh`: indeed_source_report → ad_sales_board (~35 min)
- **4:00 AM** — day orchestrator batch (captainship + everything else registered on the scheduler)
- **6:30 AM** — captainship_boards (owner sales boards fill)
- **7:00 AM (mornings)** — b2b_metrics per office; item #6 Customer Churn posts the new-comp rendered image for carlos + atef (falls back to plain screenshot on any error)
- **7:50 AM** — ad sales board Slack post
- **8:45 PM** — daily_update_fill (Vantura Daily Update pass)
- **Resume pusher** — q5-10min, 8 AM–10 PM, skips Saturday, skips hour 13 (the 1 PM chain window)
- **7:00 PM** — README auto-update (scheduled Claude task on the mini; this file)

Deploy flow (never skip the verify): edit on the mini → commit → `git pull --rebase`
→ push `HEAD:main` (Lucy 2 tracks **main**) → queue `update` → queue `rerun <id>` →
**verify by reading the log** (`logtail`), never by a success message.

## 4. THE GOTCHA LIST — what typically breaks when you change things

These are all real incidents. Before any change, scan this list for the row that
matches what you're about to touch.

### Writing values to Sheets
- **USER_ENTERED coerces.** "July 2026" becomes a date serial, "8.30" becomes 8.3 —
  this silently killed the Source Report pickers and emptied the migrated Sales Board
  week view. Fix pattern: TEXT ("@") format on the cell + write RAW + dual-match
  formulas that accept both the string and the coerced form. Any new picker cell
  gets this treatment from day one.
- **Reading with FORMATTED_VALUE returns strings** — arithmetic downstream dies or
  goes $0 (the Recruiting Dashboard AD BUDGET box). Always read with
  `UNFORMATTED_VALUE` when numbers will be computed.
- **60 writes/min/user quota** — batch writes; a per-cell loop will stall the run.
- **Sheets "Table" objects block spill formulas and survive value clears** — if a
  spill shows #REF after someone "made it a table", you need `deleteTable`, not a
  bigger clear.
- **Filter criteria stick.** Adding criteria to a basic filter hides rows for
  EVERYONE and persists; sorting via filter menu breaks spill formulas (#REF).
  Clear criteria, keep the filter buttons. This has bitten the Ad Plan tab twice.

### Renaming / moving / restructuring tabs
- Renaming a tab is safe for formulas ON the workbook (references follow), but
  **anything external addressing the tab by name breaks**: Lucy jobs with hardcoded
  tab strings, IMPORTRANGEs from other books, the web app's PAGES list, Apps Script
  constants. Grep the repo for the old tab name before renaming.
- **copyTo across workbooks breaks references (#REF).** The working migration
  pattern: dump formulas first, copy, recreate referenced tabs, re-plant formulas
  verbatim.
- **IMPORTRANGE authorizes per destination FILE** — every new destination↔source
  pair needs one human "Allow access" click. A migrated/duplicated tab shows #REF
  until that click happens.
- **Row/column inserts shift ranges used by jobs.** The funnel/board builders write
  to fixed anchors; moving blocks around (like Goals rows 46–54) requires updating
  build.py anchors in the same change.

### Apps Script (Goal Sync project + web app)
- **onEdit triggers fire only on HUMAN edits** — API/job writes never trigger the
  goal mirror or adPlanMirror. Don't build logic that assumes a Lucy write will
  fire a trigger.
- **The editor saves silently fail**: verify "Saved to Drive" in the header before
  closing, or the old code keeps running (lost an edit this way once). Dismiss the
  "signed in as" popup first — it eats clicks.
- **monaco applyEdits targets the visible editor's model** — when editing via
  automation, resolve models by `uri.path` extension (`.js` vs `.json`); we once
  overwrote Code.gs with the manifest because "file_1.js" WAS Code.gs.
- Web app: raw REST to sheets.googleapis.com gets **403** (default GCP project) —
  use the Advanced Sheets Service. Every code change needs Deploy → Manage
  deployments → edit → **New version** to reach the /exec URL. Adding a user =
  ALLOWED array + new version.
- Very large tabs don't render as web pages — Ad Sales Board is capped at 240 rows
  (700 rendered blank).

### The queue / deploying to Lucy 2
- Lucy 2 tracks **main**; push `HEAD:main` from the mini's working branch. The old
  resume-pushing-v2 push rejection is harmless — ignore it.
- `rerun <id> -- --flag` FAILS through raw queue rows — the `--` is a lucy-CLI
  convention only. Args string: `indeed_source_report --office 11580`.
- The poller is single-threaded: a long job blocks every queued row behind it.
- A check run right after `update` may have executed on the OLD code (two lanes) —
  wait for the update row to finish before the verify row.
- The queue tab has a finite grid — extend (+3000 rows) when appends start failing.
- `diag` only knows 4 hardcoded agents; **verify by log, never by diag or by a
  "loaded/success" message**.
- Scratchpad on the mini wipes between days — durable helpers belong in the repo,
  not /tmp scratch.

### schedule_config.json / registry
- **Never `json.dump` the whole config with different formatting** — it rewrites
  9,400 lines and buries your one-entry diff. Load, mutate, dump with `indent=2`
  exactly, and check `git diff --stat` shows only your entry.
- New off-scheduler report = entry with `on_scheduler: false` + `machine` +
  `command`; test with `rerun <id>` before trusting any schedule.
- Retired agents are `.disabled` plists, not deletions — re-enable via the
  matching `install_<x>_agent` handle.

### Data-loss patterns
- **Daily Log has been wiped twice.** Version history may show it intact hours
  earlier; recovery that worked was a batched multi-week re-scrape, not sheet
  restore (the "Make a copy" dialog resists automation). Treat any build change
  that touches Daily Log as high-risk; check row count before/after.
- **Ad Sales Board day-cell history cannot be re-derived** — received-per-day
  values are carried-over rewrites keyed by inbox+base(+city); once a day is gone
  it's gone. Never "rebuild from scratch" that tab's history.
- **Workout sheet rule (general Carlos rule): never repaste full ranges over
  logged data — cell-level edits only.**
- Edit scripts that assert AFTER writing lose earlier edits silently when the
  assert throws — write-per-edit or single-purpose scripts.

### Jobs / pulls
- AppStream p=702 per-office schemas differ; office ids: Carlos 11580, Atef 23467
  (see indeed_source_report/offices.py for the rest — two "Joshua Murphy" offices
  exist, 21770 is the right one).
- Tableau: URL week filters don't apply to B2BATTSalesMetrics — drive the dropdown.
  Stale sessions heal headed with the 30s waits; CSV export needs timeout=240s.
- captainship_boards breaks when a NEW captain's board isn't shared with
  raffi127@gmail.com — first thing to check when one board stops filling.
- The 503-with-no-retry pattern (org_campaign_metrics ensure_tab) silently killed
  a week of campaign stamps — any new Sheets GET in a long job needs retry.
- One office failing must never kill a multi-office run (existing loops already
  try/except per office — keep that shape in new code).

## 5. Adjustments made BECAUSE a change broke something (the history)

- **Tab rename → "Source Report - Indeed"** (from Indeed Ad Performance): safe for
  formulas, but pickers had already been killed by date-coercion — the rename change
  bundled the TEXT-format + RAW + dual-match fix. Lesson: renames ride along fine;
  coercion was the real bug.
- **Pickers moved to column C** (B hidden): required re-pointing the validation and
  the formulas that read the picker — moving a picker means grepping for its A1
  address in build code, not just dragging the cell.
- **Ad budget box $0** after tracker_mirror change → FORMATTED_VALUE reads; fixed to
  UNFORMATTED + re-ferry.
- **Captainship views merged into the org book** → every IMPORTRANGE pair needed a
  fresh Allow click; week picker died to "8.30"→8.3 coercion → TEXT+RAW+daily stamp
  added to captainship_boards so the view heals itself every morning.
- **Goals rows moved (46–54)** → funnel build anchors updated in the same commit or
  the next build would have rewritten the old layout.
- **Ad Plan v3**: tab-switcher rejected → in-place mirror; then leftover Table
  object + stuck filter criteria made it "empty" twice → deleteTable + clear
  criteria; then row-2 filter added — criteria must stay clear, buttons only.
- **Two-account AppStream refactor (Sep 2, Raf's side)** broke resume pushing for
  Carlos + Atef: the new `Lucy Resume Pushing` session was never validly minted on
  Lucy 2 and the whoami check can FALSE-FAIL on scoped accounts. Real test/seed:
  `rerun applicant_push --dry-run` (real-Chrome path). Passwords come from
  Carlos/Megan only.
- **1am/1pm chain reschedule** → resume pusher gained the hour-13 skip so it never
  collides with the heavy AppStream pulls; funnel_board removed from the 4am batch
  (weekdays: []) so it doesn't double-run.
- **[Action required] wrapper emails** were being dropped as noise → unwrapped and
  counted since 8/27 (monthly undercount before that).
- **Carlos full-month window (2026-09-05)**: his office (11580) pulls Sept 1→30
  every run via FULL_MONTH_MANAGERS in indeed_source_report/run.py; everyone else
  stays 1st→today. If his numbers ever look inflated vs others, check this first.

## 6. Standing rules

- Vantura Master Sales Board is NEVER part of fleet/captainship changes unless
  Carlos names it explicitly.
- Never enter Carlos's passwords anywhere; credential installs go through the
  SECRET queue actions and the values come from Carlos/Megan.
- `ownerville-creds.json` is gitignored and never committed (repo is public).
- Sends/deletes are irreversible: `--dry-run` / `--limit 1` first, log-verified.
- Errors go to #claudecorrections-and-requests, never office channels.
- If code and Megan's Lucy Login Standard disagree, the standard wins — update the
  code (and login_check.py + test_login_policy.py with it).

## 7. Change log (auto-appended daily at 7 PM)

- **2026-09-06** — README created (Carlos). Covers state through today: web app
  live (8 pages, Carlos-only allowlist), Carlos full-month source window live,
  new-comp churn image live for carlos+atef mornings, resume-pusher outage being
  worked by peer sessions (login seed on Lucy 2).
