# automations/harvest — harvest-once Tableau cache

**Status: proven; cutover built but DEFAULT-OFF.** The live 4am path is
byte-for-byte unchanged until `HARVEST_MODE=on`. Implements the full design in
`output/harvest-architecture-design.md`; flip procedure in
`output/harvest-cutover-plan.md`.

## Why it can't affect the 4am run (until you flip it)
- The churn `pull.py` guards import `automations.harvest.adapter` **only when
  `HARVEST_MODE=on`**. With no env var the guard is a single dict lookup that
  short-circuits — no import, no behaviour change, identical to before.
- `day_orchestrator/*`, `schedule_config.json`, LaunchAgents, plists: no
  references (the one exception is the OFF-scheduler `install_harvest_proof_agent`
  / `harvest_proof` entries, which only drive the standalone 1pm shadow proof).
- Cache reads fail SAFE: miss / stale / any error → live scrape. The cache can
  only replace a pull with byte-identical data or defer to live; it can never
  serve stale data (loader hard-fails) or break a report.

Verify the default path is untouched:
```
HARVEST_MODE unset → grep the guards: each is `if os.environ.get("HARVEST_MODE"
,"off")... == "on":` — false by default, so the live download runs unchanged.
```

## Modules
| file | role |
|------|------|
| `needs.py` | `DataNeed` + `cache_key` + the churn-cluster registry; `scheduled_data_needs(date)` unions today's scheduled tableau reports. Browser-free. |
| `harvester.py` | pulls each unique need once over ONE login → dated cache + `manifest.json` (pull_ts, target_date, row_count, sha256, ready_probe); prunes the rolling window. |
| `readiness.py` | probe each unique source once, sticky-READY (reuses the orchestrator's `_csv_covers_date`). |
| `loader.py` | `load_harvest(need, date)` / `load_harvest_rows` with the **hard-fail** staleness/provenance guard. |
| `compute.py` | bounded `ThreadPoolExecutor` compute pool with a per-spreadsheet lock (Phase-2 model; inert). |
| `proof.py` | Stage (c): harvest once, then parse twice (live control vs cache treatment), diff cell-for-cell. |
| `adapter.py` | **Cutover seam.** `try_cache_view(view_url, sheet, out)` — serves cache when `HARVEST_MODE=on`, else None (→ live). Fail-safe. |
| `run.py` | **Harvest-prime entrypoint.** `python -m automations.harvest.run` pulls today's churn views once → cache (runs first at cutover). |
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

## Phase-2 — org-wide-pull-and-slice (`org_wide=True`, ALL PROGRAMS PROVEN)
`orgwide.py` + `proof_orgwide.py`. Pull ONE org-wide view per program and slice
per office in Python instead of N per-office pulls. The hazard the design flagged —
a naive collapse inherits the org-wide total, not the office's — is handled by
**recomputing** each office's total row from its sliced reps. Two slicer shapes:
`slice_owner` (B2B/NDS, owner-keyed rows), `slice_d2d` (D2D NI/Wireless per office,
sliced by the `ICD Owner Name (rep)` column), and `slice_d2d_team` (D2D
captainship — slices a team's owners then AGGREGATES reps up to owner level).
Proven 2026-07-12 across EVERY current churn destination tab (3 B2B + 3 NDS
captainships, 3 D2D local offices ×NI/WL, 6 D2D captainship teams): **19 offices,
~4,330 cells, 0 mismatches** vs per-view pulls. `slice_d2d_team` filters by the
`Captain's Bonus Teams` column (the SFDC team filter) — owner-only aggregation
over-counts owners with cross-team reps.
Views: `ALLTEAMCHURN` (B2B), `INTAllTeams`, `WirelessAllTeams`, `NDSAllTeamsChurn`.
See `output/harvest-proof-orgwide-2026-07-12.md`.

**Two correctness lessons (caught by this proof):** (1) owner-keyed slices MUST
match the full `NAME\n[office]` identity, not bare name — the same person can
appear under two offices in an org-wide view (a bare-name slice merged two "Kyle
Campas"). (2) captainship-team slices MUST filter by the `Captain's Bonus Teams`
column, not just owner — an owner's reps can span teams, so owner-only
aggregation over-counts (William Sassenberg: 165 on-team vs 194 all).
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
