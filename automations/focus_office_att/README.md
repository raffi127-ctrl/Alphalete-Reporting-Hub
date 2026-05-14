# Focus Office: Sales Org -ATT Program

Per-rep daily breakdown report. One tab per owner (ICD); each tab fills in the rep-level metrics that A-players currently pull by hand for coaching.

## What it does

For every owner listed (one tab per owner in the Sheet), pulls each rep's metrics for the current week:

| Source | Data |
|--------|------|
| Office Access → Time Tracker | First Knock, Last Knock, # of Gaps, Total Gap Time |
| Office Access → Disposition by Rep | Total Leads Knocked, Talk To's (calc), Presentations (calc) |
| Tableau → Product Sales Summary | New INT, Upgrades, DTV (their "Video"), New Lines (their "Wireless") |

**Talk To's** = Not Interested (Talk-to bucket) + Not Interested (Presentation bucket) + Comeback + Sale
**Presentations** = Not Interested (Presentation bucket) + Sale
**Weekly Total** = sum of Mon–Sun for each metric

## Destination Sheet

`Focus Office - Sales Org / ATT Program`
ID: `1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY`

- `Template` tab — master format (do not modify)
- One tab per owner, named with the owner's full name (e.g. `Cody Cannon`)

## Build status

- [x] Phase 1: scaffold + auto-create tabs (one per owner) using Template format
- [x] Phase 1.5: structural fix (Tue-Sun match Mon's 11 metrics), formatting, conditional colors, auto-updating date formulas, bold outer border, propagated to all 30 owner tabs
- [ ] Phase 2: Office Access scraper (Time Tracker + Disposition by Rep)
- [ ] Phase 3: Tableau scraper (Product Sales Summary)
- [ ] Phase 4: Wire into dashboard with mapping prompt for new owner tabs

## How new owners are added (Phase 2+ requirement)

The owner list lives in the Sheet itself — every tab whose name isn't
"Template" is treated as an owner. When Megan manually adds a new tab
(e.g. "Joe Smith") to onboard a new owner:

1. Next time the report runs, the script scans tab names and finds
   "Joe Smith" with no saved Office Access owner-ID mapping.
2. The dashboard pops a prompt: "Map 'Joe Smith' to an Office Access
   owner" with fuzzy-match suggestions from the all-owners list.
3. Once Megan confirms the mapping, it's saved to
   `output/focus_office_owner_mappings.json` and never asked again.
4. The script then pulls Joe Smith's rep data and fills his tab.

Same pattern as the daily-focus ICD mapping prompt — see
`_render_daily_focus_mapping_prompt` in dashboard.py for reference.

## Run

```bash
# Phase 1: ensure each owner has a tab (idempotent, skips existing)
.venv/bin/python -m automations.focus_office_att.setup_tabs
```
