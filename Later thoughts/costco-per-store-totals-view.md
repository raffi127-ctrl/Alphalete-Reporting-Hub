# Costco per-store wireless-line totals — Tableau view needed

**Status 2026-05-26: per-Costco-store fill is DISABLED** in
`automations/alphalete_org_report/opt_retail.py` (gated behind
`_COSTCO_FILL_ENABLED = False`). Megan fills the cells manually until
the Tableau-side change below is in.

## Why disabled

The fill writes the WK Total for each Costco store on the Akib/MJ
shared tab (`Boaktear Chowdhury (Akib/MJ) - Retail`) for stores like
`Costco #669`, `Costco BC #655`, etc.

Current data source: the `AkibMJSummary` custom view on the
`RETAILSALESSUMMARYBYCLUB` dashboard returns long-format rows like
`(Costco #669, WK Total, 0)`. The "WK Total" measure is **the current
calendar week's running total** — on a Mon/Tue run, the new week has
barely started so every store reads 0. Even with `Min Date`/`Max Date`
URL params, the saved view's date filter locks and the measure stays
"this week so far."

Megan confirmed the wrong-source diagnosis: the correct numbers (e.g.
store #669 = 52 NL for the week ending 5/24) appear in the
**SARA PLUS SALES SUMMARY / AkibMJSummary** custom view's Summary row
when `Club #` is filtered to one store at a time. But:

- The HTTP CSV endpoint of that view only serves the National Summary
  primary worksheet — one aggregated row across all stores, not per-store.
- Setting `Club #` via URL param doesn't filter — Tableau ignores it.
- Looping per-store via UI automation (driving the Club# filter widget)
  would work but is ~60s per run and brittle to Tableau UI changes.

## What to ask the data team

Add a new worksheet on the SARA PLUS SALES SUMMARY dashboard (or save
it as part of AkibMJSummary) with:

- **Rows**: `Club #` (so each Costco store gets its own row,
  auto-includes new stores as they appear)
- **Columns**: `Measure Names` filtered to `New/Port Lines`
- **Marks** = `Measure Values`
- Filters preserved: Owner & Office = Akib + MJ, Retailer = Costco,
  date filter via URL `Min Date` / `Max Date`

Result: scraping that worksheet's CSV gives one row per Costco store
with the correct WK Total New/Port Lines for the selected week. ~1s
HTTP fetch, no UI automation needed.

## How to re-enable

1. Edit `automations/alphalete_org_report/opt_retail.py`:
   - Set `_COSTCO_FILL_ENABLED = True`
   - Point `_RETAIL_BY_CLUB_BASE_URL` (or its replacement) at the new
     worksheet's CSV endpoint
   - If the per-store table's CSV schema differs from the existing
     `parse_retail_by_club` long-format expectation, update that
     parser too
2. Verify on Marcellus first per the preview-rollout rule (or the
   first Costco-relevant rep if Marcellus has no Costco rows).
3. Confirm with Megan: open the live view in Tableau, eyeball expected
   numbers (e.g. #669 = X NL for last completed week), run the script,
   compare to what landed in the sheet.

## Metrics to fill (per Megan 2026-05-26)

- Total Store Count (Retail block)
- Costco #669
- Costco #376
- Costco #683
- Costco #1173
- Costco BC #655
- Costco #1735 (3/5)

(Plus any new clubs that show up.)
