# Alphalete Reporting Hub

How this repo's automations work, and — just as important — **what breaks when
you change things**, so the next change starts from what the last one taught
us. A scheduled job updates this file daily at 7pm (see [Maintenance](#maintenance)).

Deep operational detail lives in [docs/operating-lucy2.md](docs/operating-lucy2.md);
this README is the map and the scar tissue.

---

## The system in one page

- **Three machines.** The **Mac mini** (Carlos's, `/Users/carloshidalgo/recruiting-report`)
  is dev/control: git push rights, Google auth, warm Tableau/AppStream sessions.
  **Lucy 2** (MacBook, `Lucys-MacBook-Neo`) runs the B2B/Vantura automations.
  **Lucy 1** (`Lucys-Mac-mini`) runs the Tableau Country Trackers and captainship
  captures. Machines are reachable ONLY through the Google-Sheet command queues
  (tabs "Mini Control - Lucy 2" and "Mini Control" on sheet
  `1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw`) — no SSH.
- **Code travels via GitHub** (`raffi127-ctrl/Alphalete-Reporting-Hub`): edit on
  the mini → push `main` → queue `update` on each machine. All machines track
  `main` (since 2026-09-05; the old resume-pushing-v2 double-push is dead).
- **The day runs from the 4am orchestrator** (`automations/day_orchestrator/`,
  config in `schedule_config.json`). Failures page
  **#claudecorrections-and-requests** in real time as their own threads.
- **Verify by log, never by success messages**: `lucy logtail <name>` /
  `daystate` / `git_status` through the queue. The Hub Activity tab logs every
  run from every machine — the fastest cross-machine "what failed today".
- **Everything irreversible is gated** behind `--dry-run` / `--limit 1` and a
  human checkmark where a send goes to real people.

## The report ecosystem (major groups)

- **Vantura Master Sales Board** (`1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY`):
  filled by `rep_sales_fill` (4:00) + `vantura_orderlog_sales` (all morning),
  audited by `vantura_board_audit` (4:01, see Roll Call below), rolled onto the
  new week Mondays 11:30 by `sales_boards.week_roll`. `sales_boards` posts the
  board images into the day's threads from 5:10.
- **B2B Metrics threads** (`b2b_metrics.runner`): one thread per office
  (carlos / atef / jamis / sabrina), ~10 screenshot sections captured from
  Tableau/Sheets and posted as replies. Carlos's thread has extras (short
  parent, by-rep boards) — see `B2BOffice` flags in `b2b_metrics/offices.py`.
- **Box Metrics thread** (`box_order_log`, 7:00) — renamed from "BOX Order Log"
  2026-09-05.
- **Tableau Country Trackers** (`tableau_screenshots`, Lucy 1) — the 4:31
  multi-channel board post; freshness-gated on the extract.
- **Org Sales Board side** (mini): `org_sales_board`, `all_campaigns_board`,
  review-gated emails, captainship fills.

## Roll Call & terminations (how it's SUPPOSED to work)

A rep marked **T** stays visible all week (so weekly losses are countable) and
flips to **Terminated on Roll Call col B only when the new week starts**. The
sheet's own week-roll script used to do that flip; it died around the time the
Captainship board was created, and nobody noticed until 16 T'd-but-Active rows
piled up (2026-09-05). The flip now lives in `vantura_board_audit`:

- Signal 1: a clean `T` run on the **Sales Board** day cells → close same-day.
- Signal 1b: the **RollCallData store** (`Name|W.k` keys, per-week Status) says
  Terminated AND that labeled week has CLOSED → flip col B + fill an empty
  Date Gone from the first T day. A newer non-Terminated week (rehire) wins.
- Signal 2: a past Date Gone on an Active row.
- Never more than `MAX_AUTO_CLOSE` (25) rows per run — a bigger pile means a
  shifted column, not a mass quitting.

---

## THE CHANGE PLAYBOOK — what breaks when you change things

Every entry below is a real incident. When you make a similar change, check the
listed blast radius BEFORE shipping.

### Changing anything in Tableau (views, fields, members)

- **A restructured workbook silently blanks captures** — it does not error.
  When CHURNRATES was rebuilt (~2026-09-03), the per-product saved views kept
  "working" but rendered empty images for three days. The blank-render guard
  caught it; the cause was found only by capturing the view raw.
  **Rule: never rely on a view's SAVED filter state — name every filter member
  explicitly in the URL.**
- **Tableau URL filter rules (all proven the hard way, 2026-09-05):**
  - Percent-encoding parens/slashes in the *param name or value* makes the
    filter select NOTHING. Copy the raw-paren style of existing working URLs
    (`?Product%20Type%20(Broken%20Out)=AIR/AWB,...`).
  - A value that matches **no member** of the field doesn't get ignored — it
    resets **every filter on the view to None** and the whole board renders
    blank.
  - Member spellings change in restructures (Owner & Office members lost their
    embedded `\r` in the 9/03 rebuild). The dropdown itself is ground truth —
    `b2b_churn_preview --owner X` logs every member.
  - **Owner & Office URL slicing is DEAD on CHURNRATES** since the restructure
    (every encoding tested). The capture drives the dropdown instead
    (`capture.drive_owner`): content-detected box (ids are empty), keyboard-only
    toggles, and dismissal must be a real mouse click at the **iframe origin**
    — Escape and page-coordinate clicks leave the menu overlay up and the next
    Download→Image click times out behind it.
- **A field caption is part of the filter name** ("Sale Date Week Ending
  (mon-sun)" — dropping the suffix is an inert no-op). Some views need the
  DOM-probed internal field name (`WEEK_FIELD_OOB`).
- **Crosstab exports follow their worksheet's design, not the dashboard.** The
  rep churn sheet has no product column; rep×product needed one download per
  product member. Filtered exports also change spelling (`Grand Total` rep
  becomes `rep.Full Name=Grand Total`/`Rep=Total`) and export counts as
  decimals ("2.0").

### Renaming a Slack thread / changing its parent message

- **Other automations FIND threads by their title text.** Renaming
  "BOX Order Log" → "Box Metrics" required updating `sales_boards.box_thread_ts`,
  `backfill_tier.find_parent`, and keeping the OLD title as a fallback so a
  thread posted pre-deploy is still found. `tableau_screenshots` keeps a
  `_LEGACY_TITLE_PREFIX` for the same reason. **Grep for the title string
  before renaming anything.**
- **Parents get EDITED later** (late-note refreshes, UPDATED tags, tier
  backfill). A short (title-only) parent means those edits must target the
  contents reply instead — see `_update_contents_reply` (trackers) and the
  short-parent guard in `backfill_tier`.
- The parent's section list is a **completeness contract** (`expected_items`):
  the header, the capture list, and the missed-section reconciliation must come
  from the same source or they drift.

### Adding/removing/reordering thread sections (b2b_metrics)

- Sections are `ITEMS` + per-office `skip_views`/flags; a plans file
  (`thread_plans.json`) can override per office. Per-office extras (Carlos's
  `churn_by_rep`) must be filtered in `expected_items` or every other office
  reports it MISSED forever.
- `--only` runs MERGE into the day's manifest — they speak only for what they
  ran (2026-08-25/28 incidents).
- A section that has never had data for an office must not page
  (`has_ever_posted` discriminates new-office-blank from broken-blank).

### Google Sheets changes

- **Anything written into a spill column breaks the spill** — the anchor shows
  `#REF!` ("Array result was not expanded…"), which reads like a broken formula
  but isn't. Even a written `''` (empty STRING) blocks it — a true fix needs
  `batch_clear`, not writing blanks (Stations!L31, 2026-09-05: two hand-typed
  names at L35:L36). The Sheets API's `errorValue.message` names the blocking
  cell — read it before guessing.
- **Fixed formula ranges drift when rows are inserted** (menu adds insert at
  row 5). The audit's STATS-RANGE DRIFT finding exists for this; run
  Alphalete > Realign after roster edits.
- **Tab renames break readers**: "New DU" → "Daily Update" (2026-09) needed a
  code change; the audit fails soft on a missing tab but loses that signal.
- **Week labels are TEXT on purpose**: a numeric 8.30 becomes 8.3 and breaks
  every WeekData key + the sales_boards gate (2026-08-24). Write week cells
  with RAW + string.
- **Sections that publish a day behind** must be in
  `org_sales_board.data_gate.LAGGING_SECTIONS`, or the morning gate holds on a
  structurally blank column forever (BOX, 2026-08-12→25).

### Deploy / infrastructure

- Push `main` only; queue `update` per machine; **`restart_poller` after
  changing `mini_control.py`** (new actions don't exist until the poller
  restarts); `restart_hub` after `dashboard.py`.
- **A dirty tree on a runner blocks every `update`** — deploy wrappers are
  committed 755 so `install_agent` chmods can't dirty them.
- The queue is **one serial worker** — a 22-minute rerun blocks every read
  behind it; the read lane (`install_mini_control_read_agent`) exists for that.
- `diag` cannot confirm an agent is loaded (4 hardcoded names). Read the log.
- Browser reports: one Chrome per report, serialized on the CDP-9246 lock —
  an unlocked user kills another report's pull mid-flight (2026-08-14).
- The orchestrator treats INCOMPLETE as terminal for `after`/`depends_on` —
  gate data-dependent fills in READINESS (`data_sources`), not exit codes, or
  a partial board upstream writes a day of zeros downstream (2026-09-01).

---

## Sheets & tabs (Vantura Master Sales Board)

| Tab | Role |
|---|---|
| Sales Board | The live week: rep rows per campaign, day cells (T = terminated that day), gold week cell (TEXT) |
| WeekData | Archived weeks; keys `<REP>\|<W.k>` — why week labels must keep trailing zeros |
| Roll Call | New starts & roll: col B Status, col D name, cols G-L week view over RollCallData, col M Date Gone |
| RollCallData | The per-week attendance/status STORE (`Name\|W.k` keys) — ground truth the audit's week-close flip reads |
| Stations | Territory/station assignment; L31 = auto OFF-TODAY spill (never type in it); S2 rewritten by the Monday roll |
| Daily Update | Recruiting funnel statuses (renamed from "New DU") — NOT a termination source (it parks 97% of rows as "Not Active") |
| RAW | The sales feed (one row per sale component) — campaign totals SUMIFS over Sales Board rows, so a rep without a board row is invisible in totals even with RAW rows |
| LUCY CHURN / Lucy * Churn / Lucy *Order Log / Lucy * Data | Automation-written blocks feeding the metrics threads |
| Name Aliases | Board↔roll spelling bridge — extend it rather than "fixing" a name in place |
| Report an Issue | The audit's findings ledger (deduped) |

Control sheet (`1eJ3-…MABTAw`): the two Mini Control queue tabs, Hub Activity
(every run, every machine), B2B Diag / B2B Shot / B2B Shot AR (probe output +
base64 screenshot channels), RP/Vantura equivalents.

## Maintenance

- **This README is updated daily at 7pm** by a scheduled Claude job on the
  mini: it reviews the day's git log, day_state/Hub Activity, and
  #claudecorrections incidents, then appends to the change log below and to
  the playbook when a new failure mode was learned, and pushes to `main`.
  Keep entries dated and terse; the playbook is for the NEXT person mid-change.

## Change log

- **2026-09-05** — Big day; most of the playbook above was earned here:
  consolidated CHURNRATES board (per-product saved views retired after the
  9/03 Tableau restructure blanked them); Owner & Office slicing moved to
  dropdown-driving; Roll Call week-close auto-flip added to the board audit
  (+17-row backfill); short title-only thread parents for Carlos's channels;
  "BOX Order Log" thread renamed "Box Metrics"; new Churn-by-Rep (per product)
  and rebuilt Activation-by-Rep (0-30 + 31-60, banded per
  `vantura_churn.fill.BANDS`) sections on Carlos's B2B Metrics thread;
  Stations!L31 spill unblocked; Lucy 2 confirmed tracking `main`
  (resume-pushing-v2 retired); docs/operating-lucy2.md updated to match.
