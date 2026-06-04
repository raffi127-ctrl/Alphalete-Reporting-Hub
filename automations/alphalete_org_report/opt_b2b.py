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
PP_ROW = 42   # canonical Personal Production row

# All B2B ICDs on the Alphalete Org sheet: (ICD name, sheet tab). Carlos is the
# head — his full B2B OPT block fills here too (Megan 2026-06-03), not just
# Valeria's. The crosstab views carry every ICD, so we download once and extract
# per ICD.
B2B_ICDS = [
    ("Valeria Tristan", "Valeria Tristan - B2B"),
    ("Carlos Hidalgo",  "Carlos Hidalgo -B2B"),
]

# Personal Production = the per-rep 'B2BLASTWEEK' view (REPEXPANDED filtered to
# the finished week — Megan 2026-06-03; 'this week and last' combined the two,
# so a last-week-only view is what's separable). PP per ICD = the rep row where
# REP == the ICD's own name (their own sales), formatted '3 NI / 2 NL'.
B2B_PP_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/"
              "B2BATTSalesMetrics/5dc77806-1536-4a20-9c98-54545f786715/B2BLASTWEEK")
B2B_PP_SHEET = "Sales.Quality Metrics"


def _parse_b2b_pp(path) -> dict:
    """Per-rep B2BLASTWEEK crosstab → {rep-name-lower: {column: value}}."""
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    rows = _read_tab_csv(path)
    if not rows or len(rows) < 2:
        return {}
    headers = [(h or "").strip() for h in rows[0]]
    rep_i = next((i for i, h in enumerate(headers)
                  if h.lower() == "rep"), 1)
    by_rep: dict = {}
    for r in rows[1:]:
        if len(r) <= rep_i:
            continue
        rep = (r[rep_i] or "").strip()
        if not rep or rep.lower() == "total":
            continue
        by_rep.setdefault(rep.lower(),
                          {h: (r[i] if i < len(r) else "")
                           for i, h in enumerate(headers)})
    return by_rep


def _b2b_pp_for(icd: str, by_rep: dict, fallback: str = "") -> str:
    """The ICD's OWN personal production: the rep row where REP == ICD name
    (with as_owner + first/last fallbacks). '-' when no self-row (the ICD runs
    a team but didn't personally sell), matching the manual-entry convention."""
    cands = [icd]
    if fallback and fallback.lower() != icd.lower():
        cands.append(fallback)
    rec = next((by_rep[c.lower()] for c in cands if c.lower() in by_rep), None)
    if rec is None:
        parts = icd.lower().split()
        if len(parts) >= 2:
            rec = next((v for k, v in by_rep.items()
                        if k.startswith(parts[0]) and k.endswith(parts[-1])), None)
    return cb._format_carlos_pp(rec) if rec else "-"


def _b2b_fallback_names(tab: str = B2B_TAB) -> List[str]:
    """Alternate names for an ICD from the Alphalete Org mapping (Tableau may
    spell the legal name differently than the tab)."""
    import json
    p = (Path(__file__).resolve().parent.parent / "recruiting_report"
         / "office-mapping-alphalete-org.json")
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    for c in data.get("confirmed", []):
        if c.get("sheet_tab") == tab:
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


def collect_b2b_views(page, logfn=print) -> dict:
    """Download + parse all B2B views + DD + Personal-Production ONCE (the
    crosstabs carry every ICD). Returns the parsed data for per-ICD extraction:
      {'views': {key: (by_owner, grand, view)}, 'dd': parsed_dd, 'pp': by_rep}."""
    views: dict = {}
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
            views[view.key] = (by_owner, grand, view)
            logfn(f"OPT B2B: {view.key}: {len(by_owner)} owner(s)")
        except Exception as e:
            logfn(f"OPT B2B: ✗ {view.key}: {type(e).__name__}: {str(e)[:120]}")

    dd_parsed: dict = {}
    try:
        dd_out = OUTPUT_DIR / "opt_b2b_dd.csv"
        download_crosstab_patchright(ORG_DD_URL, ORG_DD_SHEET, dd_out,
                                     verbose=False, page=page)
        dd_parsed = parse_direct_deposit(dd_out)
    except Exception as e:
        logfn(f"OPT B2B: ✗ dd: {type(e).__name__}: {str(e)[:120]}")

    pp_by_rep: dict = {}
    try:
        pp_out = OUTPUT_DIR / "opt_b2b_personal_production.csv"
        download_crosstab_patchright(B2B_PP_URL, B2B_PP_SHEET, pp_out,
                                     verbose=False, page=page)
        pp_by_rep = _parse_b2b_pp(pp_out)
        logfn(f"OPT B2B: personal production: {len(pp_by_rep)} rep(s)")
    except Exception as e:
        logfn(f"OPT B2B: ✗ personal production: {type(e).__name__}: {str(e)[:120]}")

    return {"views": views, "dd": dd_parsed, "pp": pp_by_rep}


def values_for_b2b_icd(icd: str, tab: str, parsed: dict, logfn=print) -> dict:
    """Extract one ICD's {canonical_row: value} from the once-parsed data —
    every view, DD, and Personal Production (row 42) — then apply_computed."""
    fallback = _b2b_fallback_names(tab)
    fb = fallback[0] if fallback else ""
    values: dict = {}
    for key, (by_owner, grand, view) in parsed["views"].items():
        values.update(cb.values_for_icd(icd, by_owner, grand, view,
                                        fallback_names=fallback))
    dd_v = match_dd_owner(parsed["dd"], icd)
    if dd_v is not None:
        values[DD_ROW] = f"${dd_v:,.2f}"
    values[PP_ROW] = _b2b_pp_for(icd, parsed["pp"], fb)
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
    # Build the per-tab remap: canonical row -> this ICD's actual row, by label.
    remap = {}
    for canon, label in cb.ROW_TO_LABEL.items():
        r = cb.metric_row_for_tab(col_b, label)
        if r is not None:
            remap[canon] = r
    # Personal Production (row 42) isn't in ROW_TO_LABEL — look it up by label.
    pp_r = cb.metric_row_for_tab(col_b, "Personal Production")
    if pp_r is not None:
        remap[PP_ROW] = pp_r
    return cb.write_icd_values(ws, values, target_col, dry_run=dry_run,
                               row_remap=remap)


def run_b2b_opt(dry_run: bool = False, logfn=print) -> dict:
    """Pull the B2B views ONCE + fill every B2B ICD's tab on the Alphalete Org
    sheet (Valeria + Carlos — the head). Each ICD's full OPT block, incl. PP."""
    week_label = _week_col_label()
    logfn(f"OPT B2B: target week = {week_label!r}")
    try:
        with tableau_session(verbose=False) as page:
            parsed = collect_b2b_views(page, logfn)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:140]}"
        logfn(f"OPT B2B: ✗ session: {msg}")
        return {"filled": [], "skipped": [], "errors": [msg]}

    client = rfill._client()
    sh = rfill.open_by_key(ALPHALETE_ORG_SHEET_ID, client)
    filled, skipped = [], []
    for icd, tab in B2B_ICDS:
        values = values_for_b2b_icd(icd, tab, parsed, logfn)
        logfn(f"OPT B2B: collected {len(values)} metric(s) for {icd}")
        try:
            ws = rfill._retry(sh.worksheet, tab)
        except Exception as e:
            logfn(f"OPT B2B: ✗ {tab}: {type(e).__name__}: {str(e)[:120]}")
            skipped.append(tab)
            continue
        for ln in fill_b2b_tab(ws, values, week_label, dry_run, logfn):
            logfn(f"OPT B2B: {ln}")
            if ln.lstrip().startswith(("[OK", "[DRY-RUN")):
                filled.append(tab)
    return {"filled": filled, "skipped": skipped, "errors": []}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = run_b2b_opt(dry_run=args.dry_run)
    print(f"\nFilled: {len(result['filled'])}; Errors: {len(result['errors'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")
