# Retired: First Sale / Last Sale report

**Retired 2026-07-06** (Megan: "no longer needed"). This folder is the saved
copy so it can be rebuilt later if needed. Git history also retains everything.

## What it was
Weekly report that parsed the emailed **B2B.D2D First Last Sale WE ….xlsx**
(Smart Circle — cdeliscu@thesmartcircle.com, Mondays ~8:50am–1:11pm CT) and
filled the First Sale / Last Sale times + Order Count table (1 week behind) on
every ICD tab. Ran on its own **Monday 2:00pm CST** launchd job on the mac mini
(`com.alphalete.first-last-sale-mon`), NOT the 4am orchestrator.

## What's saved here
- `automations_first_last_sale/` — the whole module (run.py, parse.py, fill.py,
  email_source.py, __init__.py)
- `deploy/` — the launchd plist + wrapper .sh
- `resources/` — the report spec + Hub-card snippet

## How to restore
1. `cp -R "Later thoughts/retired-first-last-sale/automations_first_last_sale" automations/first_last_sale`
2. `cp "Later thoughts/retired-first-last-sale/deploy/"* deploy/`
3. Re-add the Hub card to `automations/dashboard.py` (id `first-last-sale`,
   category 🎯 Recruiting) — see `resources/HUB-CARD-SNIPPET.md`.
4. Re-add the `first_last_sale` report entry + `install_fls_agent` installer to
   `automations/day_orchestrator/schedule_config.json`.
5. Re-add the `"first_last_sale": "first-last-sale"` line to `hub_publish.py`
   `_HUB_CARD` and the `library_assignments.json` entry.
6. Reinstall the mini job: `lucy update` then `lucy rerun install_fls_agent`.

## What removed it (so restore is complete)
Retirement commit unwired the card + scheduler + mapping and added a generic
`automations/day_orchestrator/uninstall_agent.py` + a one-shot
`uninstall_fls_agent` registry entry. The mini's 2pm job was stopped with
`lucy update` + `lucy rerun uninstall_fls_agent` (bootout + plist delete).
