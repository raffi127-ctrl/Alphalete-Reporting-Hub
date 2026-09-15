"""Production Breakdown driver — iterates every ICD tab on the ATT
Program - Focus Report and runs the per-tab fill. Reads the OPT phase's
already-downloaded PRODUCT SALES SUMMARY crosstab (no extra download)."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from automations.recruiting_report import fill as rfill
from automations.recruiting_report import opt_phase
from automations.focus_office_att import aliases as _aliases
from . import fill as pbfill


NON_ICD_TAB_TITLES = {
    "1on1's", "ATT owners list", "Copy of Country Sales Board ",
    "Copy of Country Stats", "Country Metrics", "Country Metrics pilot",
    "Country Sales Board", "Country Sales Board (backup copy)",
    "Country Stats", "Focus Office - Sales", "Hub Activity",
    "OLD-Daily Focus Report", "Rafs", "Recruiting", "Template 1",
    "Template Fiber",
}


def tabs_to_process(titles: List[str], only: Optional[str] = None) -> List[str]:
    """The ICD tabs a run touches — every one, or just `only`. Pure.

    `only` exists for a NEW tab (Nuri Burgos, 2026-09-14): filling one chart
    must not rebuild the other ~80 tabs' charts behind it."""
    tabs = [t for t in titles
            if t not in NON_ICD_TAB_TITLES and not t.startswith("_")]
    if only:
        tabs = [t for t in tabs if t.strip().lower() == only.strip().lower()]
    return tabs


def run_production_breakdown(crosstab_path: Path = opt_phase.PRODUCT_SALES_PATH,
                              logfn=print, only: Optional[str] = None) -> dict:
    """Fill the Production Breakdown chart on every ICD tab (or just `only`).
    Idempotent — safe to re-run; rep block rebuilds from scratch each run.

    Reads the PRODUCT SALES SUMMARY crosstab (downloaded by the OPT phase's
    download_crosstab call). Uses Hasani Lynch's chart as the formatting
    source — must be Megan-formatted before running.
    """
    crosstab_path = Path(crosstab_path)
    if not crosstab_path.exists():
        logfn(f"PB: no crosstab at {crosstab_path} — skip")
        return {"filled": 0, "skipped": 0}
    parsed = pbfill.parse_crosstab(crosstab_path)
    aliases_map = _aliases.load_aliases()
    we_sunday = opt_phase._most_recent_sunday()
    logfn(f"PB: crosstab has {len(parsed)} owners; OPT week = {we_sunday}")

    sh = rfill.open_sheet()
    src_ws = rfill._retry(sh.worksheet, pbfill.SRC_TAB)
    src_grid = rfill._retry(src_ws.get_all_values)
    src_anchors = pbfill.find_charts(src_grid)
    if not src_anchors:
        logfn(f"PB: format source '{pbfill.SRC_TAB}' has no Production "
              f"Breakdown chart — skip whole rollout")
        return {"filled": 0, "skipped": 0, "errored": 0}
    src_chart = pbfill.chart_layout(src_grid, *src_anchors[0])
    src_sid = src_ws._properties["sheetId"]

    tabs = tabs_to_process([w.title for w in sh.worksheets()], only)
    if only and not tabs:
        logfn(f"PB: no ICD tab named {only!r} — nothing to do")
        return {"filled": 0, "skipped": 0, "errored": 0}

    counts = {"OK": 0, "NO_CHART": 0, "NO_DATA": 0,
              "EXPECTED_NO_SECTION": 0, "ERR": 0}
    for tab in tabs:
        try:
            ws = rfill._retry(sh.worksheet, tab)
            res = pbfill.fill_for_tab(sh, ws, parsed, aliases_map,
                                       src_chart, src_sid, we_sunday)
            status = res["status"]
            counts[status] = counts.get(status, 0) + 1
            if status == "OK":
                ex = f", -{res['extra_deleted']}" if res['extra_deleted'] else ""
                ch2 = " (chart2 deleted)" if res['chart2_deleted'] else ""
                logfn(f"  [OK] {tab}: {res['n_rows']} rows "
                      f"({res['n_reps']} reps, {res['n_mixed']} mixed){ex}{ch2}")
            elif status == "EXPECTED_NO_SECTION":
                logfn(f"  [EXPECTED] {tab}: no PB chart (Megan-confirmed)")
            elif status == "NO_CHART":
                logfn(f"  [NO CHART] {tab}")
            elif status == "NO_DATA":
                logfn(f"  [NO DATA] {tab}")
        except Exception as e:
            counts["ERR"] += 1
            logfn(f"  [ERR] {tab}: {type(e).__name__}: {e}")

    logfn(f"PB summary: {counts}")
    return {"filled": counts.get("OK", 0),
            "skipped": counts.get("NO_CHART", 0) + counts.get("NO_DATA", 0)
                       + counts.get("EXPECTED_NO_SECTION", 0),
            "errored": counts.get("ERR", 0)}


if __name__ == "__main__":
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — Windows console, best effort
        pass
    ap = argparse.ArgumentParser(description="Fill the Production Breakdown "
                                             "chart(s) from the latest PRODUCT "
                                             "SALES crosstab on this machine.")
    ap.add_argument("--only", help="just this Sheet tab (e.g. a new ICD)")
    args = ap.parse_args()
    res = run_production_breakdown(only=args.only)
    sys.exit(1 if res.get("errored") else 0)
