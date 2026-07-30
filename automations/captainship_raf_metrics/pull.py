"""Slice the Metrics crosstab down to Raf's Team, one slot per box.

ONE download feeds all five boxes (see boxes.py for the full source path). The
crosstab is the same file captainship_activation_rate / captainship_abp_6days
pull, so this module reuses their reader and their owner-subtotal rule rather
than re-implementing either:

  * `_read_crosstab` — the UTF-16 tab-delimited encoding dance.
  * the 'Rep Name' == 'Total' filter — the view breaks each ICD owner down by
    individual rep, and without that filter the LAST rep's number silently
    lands in the owner's cell.

Returns, per box key:

    {"office_total": {box_key: {"pct": "79.2%", "units": "3178"}},
     "reps": {"Rafael Hidalgo": {box_key: {"pct": ..., "units": ...}}}}

Percentages stay STRINGS exactly as Tableau printed them so USER_ENTERED turns
'79.2%' into 0.792 in the sheet's PERCENT-formatted cell. Units are digits only
(commas stripped) so they land as real numbers under the '#,##0' format.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional

from automations.captainship_activation_rate.pull import (
    VIEW_URL, WORKSHEET, TEAM_COL, OWNER_COL, REP_COL, TOTAL_ROW,
    _read_crosstab, _dl,
)
from automations.captainship_churn import pull as _cs   # _smart_title
from automations.captainship_raf_metrics import boxes as B

CSV_NAME = "captainship_raf_metrics.csv"

_PCT_RE = re.compile(r"^-?[\d,.]+%$")

# One download per PROCESS — every box reads the same view.
_METRICS_CSV: Optional[Path] = None


def fetch(out_path: Optional[Path] = None, verbose: bool = False,
          page=None) -> Path:
    """Download the Metrics crosstab (all teams). Cached per process."""
    global _METRICS_CSV
    out_path = out_path or (Path(tempfile.gettempdir()) / CSV_NAME)
    if _METRICS_CSV is not None and _METRICS_CSV.exists():
        return _METRICS_CSV
    _dl(VIEW_URL, WORKSHEET, out_path, verbose=verbose, page=page)
    _METRICS_CSV = out_path
    return out_path


def _pct(cell: str) -> str:
    """Keep a percentage as Tableau printed it ('79.2%'); anything that isn't
    one (blank, '-', 'Null') becomes ''."""
    v = (cell or "").strip()
    return v if _PCT_RE.match(v) else ""


def _pct_float(cell: str) -> Optional[float]:
    v = _pct(cell)
    if not v:
        return None
    try:
        return float(v.rstrip("%").replace(",", ""))
    except ValueError:
        return None


def _invert(cell: str) -> str:
    """100% - the activation rate. Blank stays blank (no data is not 100%)."""
    v = _pct_float(cell)
    return "" if v is None else f"{round(100.0 - v, 1)}%"


def _count(cell: str) -> str:
    """'1,290' -> '1290'. Anything that isn't a plain count becomes ''."""
    s = (cell or "").strip().replace(",", "")
    return s if re.fullmatch(r"-?\d+(?:\.\d+)?", s) else ""


def parse(csv_path: Path, team_value: str = B.TEAM) -> dict:
    """Read every box's slot for one captainship out of the crosstab."""
    rows = _read_crosstab(csv_path)
    if not rows:
        raise RuntimeError(f"Empty / unreadable crosstab: {csv_path}")

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    team_i = header.index(TEAM_COL)
    owner_i = header.index(OWNER_COL)
    rep_i = header.index(REP_COL) if REP_COL in header else None

    wanted = {c for b in B.BOXES
              for c in (b.pct_col, b.units_col) if c}
    missing = sorted(c for c in wanted if c not in header)
    if missing:
        # A renamed / removed source column must be LOUD. Filling half the tab
        # silently is the failure mode this codebase keeps paying for.
        raise RuntimeError(
            "The Metrics crosstab is missing column(s) "
            + ", ".join(repr(m) for m in missing)
            + ". The Tableau view changed — update "
              "automations/captainship_raf_metrics/boxes.py (the same rename "
              "breaks captainship_activation_rate and country_metrics).")
    col_i = {c: header.index(c) for c in wanted}

    office_total: dict = {}
    reps: dict = {}
    matched = 0

    for r in rows[1:]:
        if len(r) <= max(col_i.values()):
            continue
        if (r[team_i] or "").strip() != team_value:
            continue
        # Owner SUBTOTAL rows only — the per-rep detail rows underneath belong
        # to nobody on these tabs.
        if rep_i is not None and (r[rep_i] or "").strip() != TOTAL_ROW:
            continue
        owner = (r[owner_i] or "").strip()
        matched += 1
        is_total = owner == TOTAL_ROW
        target = (office_total if is_total
                  else reps.setdefault(_cs._smart_title(owner), {}))

        for box in B.BOXES:
            raw = r[col_i[box.pct_col]] if box.pct_col else ""
            pct = _invert(raw) if box.invert else _pct(raw)
            units = _count(r[col_i[box.units_col]]) if box.units_col else ""
            if pct or units:
                slot = target.setdefault(box.key, {})
                slot["pct"] = pct
                slot["units"] = units

    if not matched:
        teams = sorted({(r[team_i] or "").strip()
                        for r in rows[1:] if len(r) > team_i})
        raise RuntimeError(
            f"No rows for {TEAM_COL} == {team_value!r} in {csv_path.name}. "
            f"Teams present: {teams}. The team was renamed in SFDC — update "
            f"boxes.TEAM.")

    return {"office_total": office_total, "reps": reps}


def for_tab(parsed: dict, tab: str) -> dict:
    """Re-key one tab's slice from the GLOBAL box slug ('cancel-0-30') to the
    key that tab's own find_boxes returns ('0-30').

    The two namespaces are deliberately different: the slug has to be unique
    across all three tabs (it is the email's cid slot), while the sheet key only
    has to be unique within its tab. This is the one place they meet."""
    keymap = {b.key: b.box for b in B.for_tab(tab)}
    def _slice(per_box: dict) -> dict:
        return {keymap[k]: v for k, v in per_box.items() if k in keymap}
    return {
        "office_total": _slice(parsed.get("office_total", {})),
        "reps": {name: _slice(per_box)
                 for name, per_box in parsed.get("reps", {}).items()},
    }
