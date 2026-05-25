"""B2B OPT fill for the Alphalete Org sheet — the 'Valeria Tristan - B2B' tab.

Megan 2026-05-24: "it's the same mapping from Carlos's report — duplicate it
onto this report." It IS the same metric set (confirmed by label diff: 62
shared labels), just at different ROW positions on Valeria's tab. So this
module REUSES Carlos's B2B engine (automations.recruiting_report.
opt_phase_carlos) wholesale — its VIEWS, ROW_TO_LABEL, values_for_icd,
apply_computed and write_icd_values — and only:

  1. downloads each ATTTRACKER-B2B view via the automated patchright path
     (Carlos's module uses manual CDP Chrome at :9222), and
  2. maps every metric to Valeria's row BY LABEL (never by Carlos's hardcoded
     row number) via metric_row_for_tab + a per-tab row_remap.

Metrics filled (canonical row → label, from ROW_TO_LABEL):
  Active Headcount on Tableau, New Internets, Voice Sales, Wireless, New
  Lines, Total Apps*, AVG Apps Per Active Headcount*, AVG New INT Sales*,
  National AVG Apps, Scorecard Ranking, 0-30 Day Cancel Rate, Activation/
  Approval %, the five churn rows, Penetration Rate, Direct Deposit.
  (* = computed in Python by apply_computed.)

Direct Deposit comes from the shared Program Summary workbook (same source
+ parser as JE). Personal Production (canonical row 42) is NOT filled here
— Carlos pulls it from a special REPEXPANDED per-rep view; left manual for
now (consistent with BOX/Frontier).
"""

import datetime as dt
import re
from pathlib import Path
from typing import List, Optional

import gspread

from automations.recruiting_report import fill as rfill
from automations.recruiting_report import opt_phase_carlos as cb
from automations.recruiting_report.opt_phase import drive_crosstab_dialog
from automations.alphalete_org_report.opt_nds import (
    ALPHALETE_ORG_SHEET_ID, OUTPUT_DIR, ORG_DD_URL, ORG_DD_SHEET,
    parse_direct_deposit, match_dd_owner, _norm_owner, _current_target_week_end)
from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)


B2B_TAB = "Valeria Tristan - B2B"
B2B_ICD = "Valeria Tristan"
DD_ROW = 51   # canonical Direct Deposit row in ROW_TO_LABEL


def _b2b_fallback_names() -> List[str]:
    """Alternate names for Valeria from the Alphalete Org mapping (Tableau may
    spell the legal name differently than the tab)."""
    import json
    p = (Path(__file__).resolve().parent.parent / "recruiting_report"
         / "office-mapping-alphalete-org.json")
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    for c in data.get("confirmed", []):
        if c.get("sheet_tab") == B2B_TAB:
            return [n for n in (c.get("as_owner"),) if n]
    return []


def _week_col_label(today: Optional[dt.date] = None) -> str:
    # Same target as the rest of the Alphalete Org OPT (most recent Sunday
    # on-or-before today) so B2B fills the current week's column (5/24), not
    # the prior finalized one (5/17).
    d = _current_target_week_end(today)
    return f"{d.month}/{d.day}/{d.year % 100}"


def _download_view(page, view: "cb.ViewConfig", out: Path, logfn=print) -> bool:
    """Download a crosstab view via patchright. view.sheet_thumbnail_match is a
    SUBSTRING (Tableau appends a dedup counter like '(3)'), so enumerate the
    dialog's worksheets, find the one that contains it, then download that
    exact name. Returns True on success."""
    substr = view.sheet_thumbnail_match
    try:
        drive_crosstab_dialog(page, view.url, "__enumerate__", out, verbose=False)
        return False   # shouldn't reach — enumerate always raises
    except RuntimeError as e:
        m = re.search(r":\s*(\[.*\])\.", str(e))
        avail = []
        if m:
            import ast
            try:
                avail = ast.literal_eval(m.group(1))
            except Exception:
                avail = []
        target = next((s for s in avail if substr.lower() in s.lower()), None)
        if target is None:
            logfn(f"OPT B2B: ✗ {view.key}: no worksheet matching {substr!r} "
                  f"in {avail}")
            return False
        drive_crosstab_dialog(page, view.url, target, out, verbose=False)
        return True


def collect_b2b_values(page, logfn=print) -> dict:
    """Run every crosstab/aggregator B2B view + DD for Valeria; return
    {canonical_row: value} (after apply_computed)."""
    fallback = _b2b_fallback_names()
    values: dict = {}
    # The crosstab + aggregator views (everything except DD + personal prod).
    for view in cb.VIEWS:
        if view.key in ("dd", "personal_production"):
            continue
        out = OUTPUT_DIR / f"opt_b2b_{view.key}.csv"
        try:
            if not _download_view(page, view, out, logfn):
                continue
            _hdr, by_owner, grand = cb._parse_view_csv(
                out, key_column=view.key_column, key_clean=view.key_clean,
                subrow_column=view.subrow_column, subrow_value=view.subrow_value,
                keep_all_rows=bool(view.aggregator))
            vals = cb.values_for_icd(B2B_ICD, by_owner, grand, view,
                                     fallback_names=fallback)
            logfn(f"OPT B2B: {view.key}: {len(vals)} metric(s)")
            values.update(vals)
        except Exception as e:
            logfn(f"OPT B2B: ✗ {view.key}: {type(e).__name__}: {str(e)[:120]}")

    # Direct Deposit — org-wide DD view (same source every campaign uses;
    # Megan 2026-05-25).
    try:
        dd_out = OUTPUT_DIR / "opt_b2b_dd.csv"
        download_crosstab_patchright(ORG_DD_URL, ORG_DD_SHEET, dd_out,
                                     verbose=False, page=page)
        dd_v = match_dd_owner(parse_direct_deposit(dd_out), B2B_ICD)
        if dd_v is not None:
            values[DD_ROW] = f"${dd_v:,.2f}"
            logfn(f"OPT B2B: dd: ${dd_v:,.2f}")
    except Exception as e:
        logfn(f"OPT B2B: ✗ dd: {type(e).__name__}: {str(e)[:120]}")

    return cb.apply_computed(values)


def fill_b2b_tab(ws: gspread.Worksheet, values: dict, week_label: str,
                 dry_run: bool = False, logfn=print) -> List[str]:
    """Write {canonical_row: value} to Valeria's tab, mapping each canonical
    row to her actual row BY LABEL (ROW_TO_LABEL → metric_row_for_tab)."""
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-b2b] {ws.title}: empty tab"]
    header = grid[0]
    target_col = next((i + 1 for i, h in enumerate(header)
                       if (h or "").strip() == week_label), None)
    if target_col is None:
        return [f"[skip-b2b] {ws.title}: no column for week {week_label}"]
    col_b = [(r[1] if len(r) > 1 else "") for r in grid]
    # Build the per-tab remap: canonical row -> Valeria's actual row, by label.
    remap = {}
    for canon, label in cb.ROW_TO_LABEL.items():
        r = cb.metric_row_for_tab(col_b, label)
        if r is not None:
            remap[canon] = r
    return cb.write_icd_values(ws, values, target_col, dry_run=dry_run,
                               row_remap=remap)


def run_b2b_opt(dry_run: bool = False, logfn=print) -> dict:
    """Pull the B2B views for Valeria + fill her tab on the Alphalete Org sheet."""
    week_label = _week_col_label()
    logfn(f"OPT B2B: target week = {week_label!r}")
    try:
        with tableau_session(verbose=False) as page:
            values = collect_b2b_values(page, logfn)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:140]}"
        logfn(f"OPT B2B: ✗ session: {msg}")
        return {"filled": [], "skipped": [], "errors": [msg]}

    logfn(f"OPT B2B: collected {len(values)} metric(s) for {B2B_ICD}")
    client = rfill._client()
    sh = rfill.open_by_key(ALPHALETE_ORG_SHEET_ID, client)
    ws = rfill._retry(sh.worksheet, B2B_TAB)
    filled = []
    for ln in fill_b2b_tab(ws, values, week_label, dry_run, logfn):
        logfn(f"OPT B2B: {ln}")
        if ln.lstrip().startswith(("[OK", "[DRY-RUN")):
            filled.append(B2B_TAB)
    return {"filled": filled, "skipped": [], "errors": []}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = run_b2b_opt(dry_run=args.dry_run)
    print(f"\nFilled: {len(result['filled'])}; Errors: {len(result['errors'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")
