# Fiber Lead Performance — per-ICD totals view

**STATUS 2026-06-10: largely DONE / nothing to switch to right now.**

The runtime win this note was about is **already live**: Raf's Focus Report
Fiber pull switched to a single Crosstab download on 2026-05-22
(`download_fiber` → `_download_fiber_bulk` in
`automations/recruiting_report/opt_phase.py`). It downloads the
`AUTOMATIONPULL-NICHURNVIEW` custom view once and groups per owner — replacing
the old ~25-min per-ICD `Program Overview` loop (kept only as a fallback). So
the "one request instead of N" goal is met.

The remaining idea was to switch from the zip-level
`Office New Fiber Lead Penetration By Zip` sheet (~1,800 rows, grouped per
owner via Tableau "Fixed" aggregates) to a cleaner **per-ICD totals**
worksheet (one row per ICD, no grouping). But enumerating the view's Crosstab
dialog on 2026-06-10 shows only **3 sheets** — there is NO such per-ICD totals
worksheet:

  - `Office New Fiber Lead Penetration By Zip`  (current bulk source)
  - `Program Overview`  (per-ICD box; the legacy per-ICD scrape)
  - `Title`

So there's nothing to switch to. The current bulk path works and is fast.

**To pick this up (only if the zip-level grouping ever gets fragile):** add a
per-ICD totals worksheet to the FiberLeadPerformance dashboard in Tableau
(rows = Owner; the per-owner penetration / lead-count / fiber-sales rollup with
the AUTOMATIONPULL-NICHURNVIEW filter), then point `FIBER_BULK_CROSSTAB_SHEET`
at it and simplify the parser to read one row per owner. Same pattern as the
Costco per-store ask — needs the Tableau-side worksheet first.

Original note (Megan 2026-05-22): the dashboard "now exposes a per-ICD totals
worksheet in the Crosstab download dialog" — not borne out by the 2026-06-10
enumeration; the dialog only has the 3 sheets above.
