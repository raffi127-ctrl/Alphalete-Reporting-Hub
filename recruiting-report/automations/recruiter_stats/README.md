# Recruiter Stats

Per-admin weekly funnel boxes on the **Alphalete Recruiting Dashboard**
(`111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA`) for Carlos's three offices:
Carlos Hidalgo (11580), Atef Choudhury (23467), Rafael Hidalgo (11280).

Built 2026-09-05/06 for Carlos. Manual-only so far — "if I like it, we'll
probably make it an automation."

## What the user sees

One visible tab, **"Recruiter Stats"**:

- **B1 office dropdown** (data validation): pick an office, the whole tab
  swaps. The dropdown works because the visible tab holds no data — cell A2
  is one spilled formula, `=INDIRECT("'RS Data - "&$B$1&"'!A1:<lastcol><rows>")`,
  mirroring a hidden per-office storage tab (`RS Data - Carlos Hidalgo`, etc.).
- **One box per admin**, stacked down the left: title row (blue), header row
  (grey), one row per week NEWEST FIRST, then a **YTD TOTAL** row (grey).
  Weeks are labeled by their **starting Sunday** (Carlos calls that "week
  ending"). Boxes are sorted by **most recent activity first**, ties by year
  booked — so current people are always near the top.
- **OFFICE TOTAL block** to the right of the individual boxes (one gap
  column): the same columns for the whole office, every week of the year,
  so any person-week can be compared against the office number for that week.
- **Columns** (both blocks): Week | Interviews Booked | Retention Call List |
  Total First Interviews | 1st Showed Up | 1st Retention | Booking Ratio |
  Total Calls Made | one column per call type (No Answer, LM1, LM2, LM3,
  Removed — whatever sections the report actually carries).

### Derived numbers

- **Retention Call List** (per person) = person's Interviews Booked ÷ the
  office's *Sent to Call List* for that week. AppStream only reports Sent to
  Call List office-wide, so this is the agreed per-person approximation.
- **1st Retention** = 1st Showed Up ÷ Total First Interviews.
- **Total Calls Made** = LM1 + LM2 + LM3 (the no-answer statuses) — Carlos's
  definition of calls made.
- **Booking Ratio** = calls per interview booked, rendered `5:1` style
  (one decimal under 10:1). `-` means calls but zero bookings that week.
- Empty weeks are DROPPED from a person's box (Carlos 2026-09-05: no numbers,
  no row). A week with only call activity still counts as active.

### Color logic — lives in conditional formatting, NOT in the fill

All coloring is CF **custom formulas on the visible tab** so it follows the
dropdown live (a static fill would color the wrong cells the moment the
office changes). Per block, keyed on the block's own label column:

- Grey: label = `Week` or `YTD TOTAL`. Blue+bold: title rows (label filled,
  next 5 cells blank).
- Grading (columns B–F equivalents only): the row directly under a `Week`
  header (= that person's newest week) vs `AVERAGE` of the 4 cells below it
  (their own prior 4 active weeks — never a cross-person baseline):
  GREEN at/above, YELLOW within 5% below, RED more than 5% below.

## How it runs

The module runs **wholly on Lucy 2** (this dashboard's other writers already
run there; the laptop/mini have no live AppStream session). Deploy/run via
the queue — see `docs/operating-lucy2.md`:

```
git push origin HEAD:main          # from the laptop the local branch is split-boards
# queue on "Mini Control - Lucy 2": update, then rerun recruiter_stats
```

- `lucy rerun recruiter_stats` — full pull (~7–10 min: AppStream p=701
  Retention Details, admin breakdown ON, every Sun–Sat week of the current
  year × 3 offices) + tab build.
- `... --no-pull` — rebuild the tabs from the cached
  `output/recruiter_stats_raw.json` (seconds; use for layout-only changes).
- `... --dry-run` — pull + print rosters, write nothing.

Registered in `automations/day_orchestrator/schedule_config.json` as
`recruiter_stats` (manual-only, machine "Lucy 2", 60-min timeout).

Scrape internals are borrowed from `recruiter_retention/run.py`
(`_admin_on`, `_rqst`, `tr.adminRow` parsing) and
`recruiting_report/fetch_office.py` (`_switch_office`, `_set_week_and_submit`).

## Things that broke and what we did (read before changing anything)

1. **Google 403 on write (2026-09-05).** Lucy 2's personal Sheets OAuth token
   can OPEN this dashboard but 403s on any edit (`add_worksheet`). The module
   writes with the **applicant_tracker service account** via
   `funnel_board.auth` (service-account-first, OAuth fallback) — the same fix
   funnel_board needed from Lucy 1 on 2026-08-10. *Lookout:* any new code that
   writes this dashboard must use that auth path, not
   `recruiting_report.fill._client()`.
2. **"Starting Open Applicants" leaked into the call breakdown (2026-09-06).**
   Breakdown columns are picked by regex (`CALL_PAT`) over section labels; the
   word "open" matched the *Starting Open Applicants* inventory section.
   Now `open` only matches as a whole label. *Lookout:* when widening
   `CALL_PAT`, check the storage-tab header afterward for sections that
   pattern-matched but aren't call types.
3. **The raw cache only contains what the scraper kept.** Originally only 6
   sections were cached (`KEEP` filter); adding the call columns forced a
   FULL re-pull because the cache had no LM sections. The parser now keeps
   EVERY section, so future column additions should rebuild from cache with
   `--no-pull`. *Lookout:* a cache written before 2026-09-06 lacks the call
   sections — when in doubt, full re-pull.
4. **Section labels carry suffixes.** Lookups go through `_sec()` (exact
   match, then prefix match) — matching labels exactly breaks on some weeks.
5. **CF formulas are keyed per block.** Rules lock on the block's label
   column (`$A` for individuals, the office block's own letter on the right).
   Adding another block (or moving one) requires emitting its own rule set in
   `_cf_rules` — the `$A`-locked rules silently do nothing for a block that
   isn't at column A.
6. **The INDIRECT spill must stay unobstructed.** The mirror formula spills
   from A2 over `total_cols × max_rows`. Anything written inside that
   rectangle on the visible tab turns the whole tab into one `#REF!`. The
   footer note is written BELOW `end_row + 2` for that reason; keep it there.
   Changing the column count changes the range string — it is computed from
   `total_cols`, don't hard-code it.
7. **Number formats are positional.** The two percent columns are C/F
   *relative to each block's start*; the breakdown columns shift with
   whatever sections exist. If column meaning changes, revisit the numfmt
   requests AND the CF grading range (grading covers only the five core
   metric columns of each block).
8. **Storage is written RAW.** Week labels like `8/30` must stay text
   (USER_ENTERED would turn them into dates); numbers are written as real
   JSON numbers, percents as decimals (0.4211) formatted by the visible tab.
9. **Queue realities.** ~2-min latency per command; the poller is
   single-threaded (a long job ahead of you blocks yours); verify by
   `logtail rerun-...-recruiter_stats.log`, never by the "done" status alone.
   Other sessions share the queue — row numbers move.
10. **Don't collide with the dashboard's other writers.** funnel_board
    (Recruiting Dashboard / Focus Report / Daily Log / Goals), ad_sales_board
    (Ad Sales Data + lists), indeed_source_report, tracker_mirror (disabled).
    This module owns exactly: "Recruiter Stats" + "RS Data - *". Keep it that
    way.

## Change log

- 2026-09-05: initial build — dropdown tab + hidden storage tabs + CF
  grading (36a397b2); service-account write fix (9bd4b819); drop empty week
  rows (b2bc0512); recency-first box sort (f6f98409).
- 2026-09-06: Booking Ratio / Total Calls Made / call-type breakdown columns,
  scraper keeps all sections, call-only weeks count as activity (cd2f0f1f);
  OFFICE TOTAL block with per-block CF/formats (8cecd55f); drop
  "Starting Open Applicants" from the breakdown (2b0913d6).
