"""When the NDS workbook fails, the board reads NDS from Sara Plus instead.

The NDS workbook stays the source on every run. This only runs after it fails
(Eve 2026-11-05, the day a permission error on one of its data sources took the
workbook down). The next run that gets the workbook goes back to it on its own,
and overwrites what came from here.

Source: Dropship Workbook V_2 -> SARA PLUS SALES SUMMARY BY DAY -> Original view
-> 'Sara Plus Sales ICD (by day)'. Checked against the board for 11/2 and 11/3:
23 of 26 owner-days equal, the other 3 are one higher in Sara.

Any run that uses it leaves a note for the day's email, so nobody reads these
numbers as the regular ones.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import quote

# Original view: without it Tableau can open a saved view filtered to a couple
# of owners.
VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/"
            "SARAPLUSSALESSUMMARYBYDAY?:original_view=yes")
WIRELESS = "wireless lines"
# The NDS program 'Total' on the captainship boxes (board 11/3: Colten 25+2+1=28).
TOTAL_MEASURES = (WIRELESS, "aia", "internet")
NOTE_FILE = "nds_source_note.txt"
NOTE_TEXT = ("Note: today's NDS numbers come from an alternate source (SaraPlus) "
             "because the NDS Tableau workbook is unavailable. They will be "
             "updated as soon as possible.")

_cache: Dict[Tuple[dt.date, str], dict] = {}


def _sum_measures(measures: dict, wanted) -> dict:
    total: dict = {}
    for name, days in measures.items():
        if name.strip().lower() in wanted:
            for day, n in days.items():
                total[day] = total.get(day, 0) + n
    return total


def program_shape(parsed: dict) -> dict:
    """{owner: {measure: {day: n}}} -> what the NDS captainship pull gives."""
    out = {}
    for owner, measures in parsed.items():
        total = _sum_measures(measures, TOTAL_MEASURES)
        if total:
            out[owner] = {"Total": total}
    return out


def section_shape(parsed: dict, metric: str = "Wireless") -> dict:
    """{owner: {measure: {day: n}}} -> what the ATT NDS Team section pull gives."""
    out = {}
    for owner, measures in parsed.items():
        lines = _sum_measures(measures, (WIRELESS,))
        if lines:
            out[owner] = {metric: lines}
    return out


def pull(page, today: dt.date, out_dir, logfn=print) -> dict:
    """Download once per run and return {owner: {measure: {day: n}}}."""
    from automations.org_sales_board import sara_pull, week as _wk
    from automations.shared.tableau_patchright import download_crosstab_patchright
    key = (today, str(out_dir))
    if key in _cache:
        return _cache[key]
    lo, hi = _wk.reporting_monday(today), _wk.reporting_sunday(today)
    url = (f"{VIEW_URL}&{quote('Min Date')}={lo.isoformat()}"
           f"&{quote('Max Date')}={hi.isoformat()}")
    out = Path(out_dir) / "org_sales_board_nds_from_sara.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    logfn(f"  ⚠ NDS workbook failed: reading NDS from Sara Plus by day, "
          f"{lo.isoformat()}..{hi.isoformat()}")
    download_crosstab_patchright(url, sara_pull.RETAIL_CROSSTAB_SHEET, out,
                                 page=page, verbose=False)
    parsed = sara_pull.parse_sara_crosstab_byday(out, today=today)
    if not parsed:
        raise RuntimeError("Sara by day came back with no owners")
    _cache[key] = parsed
    return parsed


def _note_path(run_day: dt.date) -> Path:
    from automations.org_sales_board.screenshot_email import out_dir_for
    return out_dir_for(run_day) / NOTE_FILE


def mark_used(run_day: dt.date) -> None:
    """The day's email carries the note. Never stops the board."""
    try:
        p = _note_path(run_day)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(NOTE_TEXT, encoding="utf-8")
    except OSError as e:
        print(f"  ⚠ couldn't leave the NDS note for the email: {e}", flush=True)


def clear(run_day: dt.date) -> None:
    """The workbook answered in a later run: the note no longer applies."""
    try:
        _note_path(run_day).unlink()
    except OSError:
        pass


def note_for(run_day: dt.date) -> Optional[str]:
    try:
        return _note_path(run_day).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
