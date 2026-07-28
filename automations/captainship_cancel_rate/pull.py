"""Tableau pull for the Captainship Cancel Rate report.

SOURCE (one crosstab, one download, all 5 captains):
  workbook   ATT TRACKER 2_1 - D2D
  view       Metrics
             https://us-east-1.online.tableau.com/#/site/sci/views/
             ATTTRACKER2_1-D2D/Metrics
  worksheet  "Metrics Call Last week data (Internet)"
  filter     none applied by us — the view's own default state is what the
             link shows. The crosstab already comes fully EXPANDED (the '+'
             on the dashboard), i.e. one row per
             Captain's Bonus Teams -> ICD Owner Name (rep) -> Rep Name.

ROWS WE READ (the tabs list ICD OWNERS, not individual reps):
  col 0  "Captain's Bonus Teams"       -> "Wayne's Team" / "Starr's Team" / ...
  col 1  "ICD Owner Name (rep)"        -> the owner ('Total' = the whole team)
  col 2  "Rep Name"                    -> we keep ONLY 'Total' (the owner roll-up)

COLUMNS WE READ:
  "0-30 day New Internet cancel rate"        -> the 0-30 section, verbatim.
  "30-60 day New Internet activation rate"   -> the 30-60 section, INVERTED:
        30-60 cancel rate = 100% - 30-60 activation rate
     because the workbook carries no 30-60 cancel-rate column. A blank
     activation rate stays BLANK (not 100%) — no data is not a 100% cancel.

  NOTE: there is also a "0-30 day new internet churn rate" column right
  next to the cancel rate. It is a DIFFERENT metric and is NOT what this
  report fills (churn is automations.captainship_churn). Match on the exact
  header text.
"""
from __future__ import annotations

import csv
import re
import tempfile
from pathlib import Path
from typing import Optional

from automations.recruiting_report import opt_phase
from automations.focus_office_att import aliases as _aliases

METRICS_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "ATTTRACKER2_1-D2D/Metrics")
METRICS_SHEET = "Metrics Call Last week data (Internet)"

COL_TEAM = "Captain's Bonus Teams"
COL_OWNER = "ICD Owner Name (rep)"
COL_REP = "Rep Name"
COL_CANCEL_030 = "0-30 day New Internet cancel rate"
COL_ACT_3060 = "30-60 day New Internet activation rate"

# Canonical period keys — must match fill.SECTION_LABELS.
P_030 = "0-30"
P_3060 = "30-60"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def _read_crosstab(path: Path) -> list[list[str]]:
    """Tableau crosstab CSVs are UTF-16, tab-delimited."""
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = list(csv.reader(f, delimiter="\t"))
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            continue
    return []


def _col_index(header: list[str], wanted: str) -> Optional[int]:
    w = wanted.strip().lower()
    for i, h in enumerate(header):
        if (h or "").lstrip("﻿").strip().lower() == w:
            return i
    return None


def _pct_to_float(raw: str) -> Optional[float]:
    """'84.3%' -> 84.3 ; '' / '-' / junk -> None."""
    s = (raw or "").strip().replace(",", "")
    if not s or s in {"-", "%"}:
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*%?", s)
    return float(m.group(1)) if m else None


def _invert(raw: str) -> str:
    """30-60 cancel rate = 100% - 30-60 activation rate. Blank stays blank."""
    v = _pct_to_float(raw)
    if v is None:
        return ""
    return f"{round(100.0 - v, 1)}%"


def _display_name(tableau_name: str, alias_raw: dict) -> str:
    """Tableau shouts owner names ('ALEX TURZYNSKI'). Resolve through the ICD
    Aliases sheet first — a hit already carries the exact Sheet-tab spelling
    ('JC Gerard Pascual' -> 'JC Pascual'), so don't re-case it. A miss gets
    title-cased, which is the spelling these tabs use."""
    canonical = _aliases.alias_to_canonical(tableau_name, alias_raw)
    if canonical != tableau_name:
        return canonical          # alias/canonical hit — already spelled right
    return tableau_name.title()


def fetch(out_path: Optional[Path] = None, *, page=None,
          verbose: bool = False) -> Path:
    """Download the Metrics crosstab. `page` = an open tableau_session page."""
    out = out_path or (Path(tempfile.gettempdir()) / "captainship_cancel_rate.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    opt_phase.download_crosstab(METRICS_URL, METRICS_SHEET, out,
                                verbose=verbose, page=page)
    return out


def parse(path: Path, alias_raw: Optional[dict] = None) -> dict:
    """Parse the crosstab into:

        {"teams": {"Wayne's Team": {"avg":  {"0-30": "7.7%", "30-60": "15.7%"},
                                    "reps": {"Wayne Rude": {"0-30": ..., ...}}}},
         "missing_cols": [...],
         "teams_seen": [...]}

    Only owner-level rows (Rep Name == 'Total') are kept — the tabs list ICD
    owners. Values are kept as '12.3%' STRINGS so USER_ENTERED writes land as
    real percents in the Sheet (and the tabs' conditional formatting fires).
    """
    if alias_raw is None:
        try:
            alias_raw = _aliases.load_aliases()
        except Exception:
            alias_raw = {}

    rows = _read_crosstab(path)
    if not rows:
        raise RuntimeError(f"Empty / unreadable crosstab: {path}")

    header = rows[0]
    idx = {
        "team": _col_index(header, COL_TEAM),
        "owner": _col_index(header, COL_OWNER),
        "rep": _col_index(header, COL_REP),
        P_030: _col_index(header, COL_CANCEL_030),
        "act3060": _col_index(header, COL_ACT_3060),
    }
    wanted = {"team": COL_TEAM, "owner": COL_OWNER, "rep": COL_REP,
              P_030: COL_CANCEL_030, "act3060": COL_ACT_3060}
    missing = [wanted[k] for k, v in idx.items() if v is None]
    if missing:
        # A renamed/removed source column must be LOUD — silently filling half
        # the tab is the failure mode we never want (the DD 1-row scrape).
        raise RuntimeError(
            "The Metrics crosstab is missing these column(s): "
            + ", ".join(repr(m) for m in missing)
            + ". The Tableau view changed — update pull.py's column constants.")

    teams: dict = {}
    for r in rows[1:]:
        if len(r) <= max(idx.values()):
            continue
        team = (r[idx["team"]] or "").strip()
        owner = (r[idx["owner"]] or "").strip()
        rep = (r[idx["rep"]] or "").strip()
        if not team or rep != "Total":
            continue          # per-rep detail rows — the tabs are owner-level
        slot = {
            P_030: (r[idx[P_030]] or "").strip(),
            P_3060: _invert(r[idx["act3060"]]),
        }
        bucket = teams.setdefault(team, {"avg": {}, "reps": {}})
        if owner == "Total":
            bucket["avg"] = slot
        elif owner:
            bucket["reps"][_display_name(owner, alias_raw)] = slot

    return {"teams": teams, "missing_cols": [], "teams_seen": sorted(teams)}


def for_team(parsed: dict, team: str) -> dict:
    """One captain's slice: {"avg": {...}, "reps": {name: {...}}}."""
    return parsed.get("teams", {}).get(team, {"avg": {}, "reps": {}})
