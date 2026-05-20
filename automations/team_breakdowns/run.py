"""Team Breakdowns driver — iterates ICD tabs, fills the 'Next Promotion'
sections. Reads the OPT phase's PRODUCT SALES SUMMARY crosstab.

Auto-detects tabs with the section, so adding/removing the section on a
tab is a template-side change with no code update needed."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from automations.recruiting_report import fill as rfill
from automations.recruiting_report import opt_phase
from . import fill as tbfill


NON_ICD_TAB_TITLES = {
    "1on1's", "ATT owners list", "Copy of Country Sales Board ",
    "Copy of Country Stats", "Country Metrics", "Country Metrics pilot",
    "Country Sales Board", "Country Sales Board (backup copy)",
    "Country Stats", "Focus Office - Sales", "Hub Activity",
    "OLD-Daily Focus Report", "Rafs", "Recruiting", "Template 1",
    "Template Fiber",
}


def run_team_breakdowns(crosstab_path: Path = opt_phase.PRODUCT_SALES_PATH,
                        logfn=print) -> dict:
    """Fill the Next Promotion section on every ICD tab that has one.

    Auto-detects sections — only tabs with the 'Next Promotion' + matching
    'Total Units' rows get touched. Idempotent."""
    crosstab_path = Path(crosstab_path)
    if not crosstab_path.exists():
        logfn(f"TB: no crosstab at {crosstab_path} — skip")
        return {"filled": 0}
    by_norm, by_fl = tbfill.parse_crosstab_per_rep(crosstab_path)
    we = opt_phase._most_recent_sunday()
    logfn(f"TB: crosstab {len(by_norm)} reps (+{len(by_fl)} first-last); WE = {we}")

    sh = rfill.open_sheet()
    tabs = [w.title for w in sh.worksheets()
            if w.title not in NON_ICD_TAB_TITLES and not w.title.startswith("_")]

    filled = 0
    unmatched_all = {}
    for tab in tabs:
        try:
            ws = rfill._retry(sh.worksheet, tab)
            res = tbfill.fill_for_tab(ws, we, by_norm, by_fl)
            if res["status"] == "OK":
                filled += 1
                msg = (f"  [OK] {tab}: {res['n_sections']} section(s), "
                       f"{res['cells']} cells")
                if res["unmatched"]:
                    unmatched_all[tab] = res["unmatched"]
                    msg += f"  (unmatched: {res['unmatched']})"
                logfn(msg)
        except Exception as e:
            logfn(f"  [ERR] {tab}: {type(e).__name__}: {e}")

    logfn(f"TB summary: {filled} tabs filled")
    if unmatched_all:
        logfn("TB: reps marked 'Unmatched Name - Check Spelling' (no history on tab):")
        for t, names in unmatched_all.items():
            for n in names:
                logfn(f"   {t}: {n!r}")
    return {"filled": filled, "unmatched": unmatched_all}


if __name__ == "__main__":
    run_team_breakdowns()
