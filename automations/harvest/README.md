# automations/harvest — harvest-once Tableau cache (SHADOW-ONLY)

**Status: inert. Nothing on the live 4am path imports this package.**
It exists to be proven, not to run in production yet. Implements Stage (b)+(c)
of `output/harvest-architecture-design.md` (design approved).

## Why it can't affect the 4am run
- No existing report `run.py` / `pull.py` imports `automations.harvest`.
- No `day_orchestrator/*` module imports it.
- No `schedule_config.json` entry, no LaunchAgent, no plist references it.
- The proof (`proof.py`) runs in a throwaway process and calls only report
  **pull + parse** (pure functions: crosstab → dict). It never fills a Sheet,
  never posts Slack, and cannot reach the live 4am subprocesses.

Verify at any time:
```
grep -rl "automations.harvest" automations --include=*.py | grep -v automations/harvest/
```
(should print nothing).

## Modules
| file | role |
|------|------|
| `needs.py` | `DataNeed` + `cache_key` + the churn-cluster registry; `scheduled_data_needs(date)` unions today's scheduled tableau reports. Browser-free. |
| `harvester.py` | pulls each unique need once over ONE login → dated cache + `manifest.json` (pull_ts, target_date, row_count, sha256, ready_probe); prunes the rolling window. |
| `readiness.py` | probe each unique source once, sticky-READY (reuses the orchestrator's `_csv_covers_date`). |
| `loader.py` | `load_harvest(need, date)` / `load_harvest_rows` with the **hard-fail** staleness/provenance guard. |
| `compute.py` | bounded `ThreadPoolExecutor` compute pool with a per-spreadsheet lock (Phase-2 model; inert). |
| `proof.py` | Stage (c): harvest once, then parse twice (live control vs cache treatment), diff cell-for-cell. |
| `config.py` | knobs: `CACHE_ROOT`, `RETENTION_DAYS` (default 3), `COMPUTE_MAX_WORKERS`. |

## Cache layout & retention
```
output/harvest/<YYYY-MM-DD>/
    <cache_key>.tsv     raw crosstab, BYTE-IDENTICAL to a live pull
    manifest.json       provenance per key
```
Rolling **3-day** window (config knob `RETENTION_DAYS`, or `harvest(..., retention_days=N)`).
Pruned at the START of each harvest; never deletes today's folder, a future
folder, or a mid-write folder (`.writing` sentinel). Doubles as a re-run buffer —
a failed report rebuilds off cache within the window without re-scraping.
Footprint: ~19 crosstabs/day × ~200 KB ≈ 4 MB/day → ~12 MB at 3 days.

## The cache key (why filters, not just the view)
`sha256(normalized_view_url + crosstab_sheet + canonical_filters + pull_mode)`.
The churn cluster is 100% `saved_view` mode (each owner/week is a distinct view
GUID, so `filters` is empty and the URL carries identity), but the key includes
filters + pull_mode so a future date-param or `pre_export` report can never be
silently served another week's rows.

## Run the proof
```
python -m automations.harvest.proof            # 5-need structural cover
python -m automations.harvest.proof --full     # all 19 pulls
```
Requires live Tableau access. Exit 0 iff every payload is identical cell-for-cell.

## Phase-2 — org-wide-pull-and-slice (`org_wide=True`, B2B PROVEN)
`orgwide.py` + `proof_orgwide.py`. Pull ONE `ALLTEAMCHURN` view and slice per
captainship in Python instead of N per-captain pulls. The hazard the design
flagged — a naive collapse inherits the org-wide Grand Total, not the office's —
is handled by **recomputing** each office's Grand-Total row from its sliced reps.
Proven for B2B (2026-07-12): 3 offices, 477 cells (rep + recomputed Grand Total),
0 mismatches vs the per-view pulls. See `output/harvest-proof-orgwide-2026-07-12.md`.
```
python -m automations.harvest.proof_orgwide              # harvest + diff
python -m automations.harvest.proof_orgwide --no-harvest # re-diff from cache
```
**Membership** sources the same way `org_sales_board/captainship.py` already does
in production — the destination tab's rep-row names (roster) matched by
name+aliases, with an org-wide fallback; `slice_b2b` flags drift via
`_missing_members`. So membership is a solved, proven pattern, not a new risk.

**Blocker to extend the org-wide collapse beyond B2B:** it needs an all-teams
(team=All) *churn* custom view per workbook, and only `ALLTEAMCHURN` (B2B)
exists today. To apply the lever to the reports that actually scale with office
count, Megan must save all-teams churn views (like `ALLTEAMCHURN`, 2026-06-01)
for: D2D NI/Wireless churn + D2D fiber churn (`ATTTRACKER2_1-D2D/CHURN`) and NDS
churn (`NDS-SNRES-ATT-OOFWorkbook/CHURNRATES`). Until then those stay on per-view
pulls — still deduped + single-login + cached under Phase-1, just not collapsed.
Each new org-wide view then needs its own `proof_orgwide`-style diff (Fiber/NDS
office rows are `Grand Total` / `Office/Organization Average` with different
metric labels — the recompute must be re-verified per workbook).
