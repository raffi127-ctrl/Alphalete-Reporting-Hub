"""Production Breakdown by Rep — fills the combined Production Breakdown
chart on each ICD tab. Combined-design (Raf 2026-05-19): one chart per tab,
with mixed reps (sold NI + WIRELESS) shown as 2 ptype rows with the Rep
name and combined Product Total merged vertically across the pair.

Uses the same PRODUCT SALES SUMMARY 4WK crosstab the OPT phase already
downloads (output/opt_personal_production.csv) — runs as a step of the
OPT phase, not as its own report."""
