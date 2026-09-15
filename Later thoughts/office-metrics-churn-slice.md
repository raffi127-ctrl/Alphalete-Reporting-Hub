# Office-metrics churn slice — a HARVEST change, NOT a standalone build

**Corrected 2026-07-14 (was mis-scoped earlier the same day).** Goal: make the
per-office `churn` metric cost flat as offices grow — pull the all-teams churn
view ONCE and slice each office out, instead of a churn pull per office.

## KEY FACT (why this is NOT a standalone build)
The metrics churn is ALREADY in the harvest system:
- `automations.churn.run` pulls via `new_internet_churn` / `wireless_churn`, and
  BOTH already have the `HARVEST_MODE` cache seam (`adapter.try_cache_view`).
- `harvest/needs.py` `REPORT_NEEDS` already lists `rashad_metrics` + `aya_metrics`
  — but mapped to the PER-OFFICE views (`NEED_NI_RASHAD`=INTRashad, `NEED_NI_AYA`
  =INTAya), which are NOT `org_wide=True`. So today the cutover would just CACHE
  the per-office view (≈zero cross-office win, since only one report pulls it).

So building a parallel slice in the metrics code would DUPLICATE + COLLIDE with
harvest. Don't.

## The actual change (small, in harvest, do it WITH that effort post-soak)
Repoint `rashad_metrics` / `aya_metrics` needs in `harvest/needs.py` from the
per-office views to a SLICE of the all-teams views (`NEED_D2D_NI_ALLTEAM`
INTAllTeams 907184c5…, `NEED_D2D_WL_ALLTEAM` WirelessAllTeams 66b10d0a…, both
confirmed working 2026-07-14). The slice machinery (`orgwide.py` `slice_d2d`) is
already proven cell-for-cell for D2D local offices. Then a `proof_orgwide`-style
diff for Rashad's + Aya's specific offices before flipping `HARVEST_MODE=on`.

## Scope / value (modest — don't rush)
- Churn is 1 of 4 per-office metrics. ongoing_cancel (cancel-rates) + ABP have NO
  all-teams view; knocks is ownerville. Those stay per-office regardless.
- Until this lands, adding a metrics office needs 4 cloned views (churn NI, churn
  WL, ongoing_cancel, ABP). After it lands, new offices need only 2 (ongoing_cancel
  + ABP) — churn comes from the shared all-teams slice.
- Steps 1 (config table + wrong-channel guard) + 2 (org-wide crosstab dedup) are
  DONE + proven live (4am 2026-07-15: all 8 metrics posted clean, both offices).

See [[project_office_metrics]]. Gate: harvest cutover soak (green shadow proofs
daily) → canary → rollout, then repoint the two metric needs.
