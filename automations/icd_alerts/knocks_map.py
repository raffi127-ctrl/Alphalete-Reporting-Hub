"""Re-key an ICD's relayed rows into the vocabulary the knocks board is drawn in.

WHAT THIS IS NOT: a schema. The board renderer decides which board to draw by
looking at which KEYS a row has -- a wireless office has no Talk-To split, an
Energy Wells office has VL and Presentation, a B2B office has neither -- so
flattening every office onto one fixed set of fields would hand
`knocks_shape()` the wrong answer and draw a plausible-looking board with every
disposition blank. Only the columns the office's own grid actually had come
through, which is exactly what makes the routing work.

THE CANONICAL NAMES ARE THE LIVE HEADERS. `total_knocks.pull._resolve_columns`
matches `idx.get(_norm(col))` -- there is no alias table anywhere, because the
Sheet's column names were taken from the page in the first place. So this is
mostly a re-spelling: the agent relayed normalised header text, and this puts
back the exact canonical casing the renderer indexes by.

Total Talk To is CALCULATED, never scraped -- the same five buckets
total_knocks sums, and for the same reason: no office's page carries it.
"""
from __future__ import annotations

import re
from typing import Dict, List

from automations.total_knocks import pull as TP


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _int(v) -> int:
    try:
        return int(float(re.sub(r"[^\d.\-]", "", str(v)) or 0))
    except (TypeError, ValueError):
        return 0


# Every column the renderers know about, in every shape. Built from the pull
# module so a column added there reaches ICD offices without a second edit.
def _known_columns() -> List[str]:
    seen, out = set(), []
    for name in dir(TP):
        if not name.startswith("COL_"):
            continue
        value = getattr(TP, name)
        if isinstance(value, str) and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _gaps_count(value) -> int:
    """'3 gaps' -> 3. The endpoint has returned both a count and a phrase."""
    m = re.search(r"(\d+)", str(value or ""))
    return int(m.group(1)) if m else 0


def gaps_by_id(tracker: List[Dict]) -> Dict[str, Dict]:
    """{badge id: {Gaps, Total Gaps (min)}} from the Time Tracker rows."""
    out = {}
    for row in tracker or []:
        rid = str((row or {}).get("id", "")).strip()
        if not rid or rid == "0":
            continue
        out[rid] = {TP.COL_GAPS: _gaps_count(row.get("gaps")),
                    TP.COL_TOTAL_GAPS: _int(row.get("totalGapMinutes"))}
    return out


def to_rows(raw: List[Dict[str, str]],
            tracker: "List[Dict] | None" = None) -> List[Dict]:
    """Relayed rows -> rows the board renderer can draw.

    Rows with no Rep are dropped: DataTables renders a 'no data available'
    row, and a totals line is not a person.
    """
    canonical = _known_columns()
    by_id = gaps_by_id(tracker)
    out = []
    for row in raw or []:
        row = {_norm(k): v for k, v in (row or {}).items()}
        rep = (row.get(_norm(TP.COL_REP)) or "").strip()
        if not rep or rep.lower() in ("total", "totals"):
            continue

        rec = {}
        for col in canonical:
            key = _norm(col)
            if key not in row:
                continue                      # absent here means absent THERE
            value = row[key]
            rec[col] = (_int(value) if col in TP.COUNT_COLUMNS
                        else (value or "").strip())

        rec[TP.COL_REP] = rep
        # Calculated, exactly as the pull does it: Talk To - Not Interested +
        # Presentation - Not Interested + Come Back + Sale + Do Not Knock.
        #
        # ONLY FOR AN OFFICE THAT HAS THE TALK-TO SPLIT. A wireless grid has
        # Come Back but none of the rest, so summing "the parts that happen to
        # be here" would publish a Total Talk To that is simply wrong -- and
        # wrong in the believable direction, which is the kind nobody catches
        # from the board.
        if TP.COL_TALK_TO_NI in rec:
            rec[TP.COL_TOTAL_TALK_TO] = sum(
                _int(rec.get(p, 0)) for p in TP.TALK_TO_PARTS)

        # Gaps ride in from the Time Tracker, matched on badge id. A rep with
        # no tracker row keeps them BLANK rather than 0 -- "did not clock in"
        # and "stood still for zero minutes" are different facts, and the
        # board draws them differently.
        merged = by_id.get(str(rec.get(TP.COL_ID, "")).strip())
        if merged:
            rec.update(merged)
        out.append(rec)
    return out


def shape_of(rows: List[Dict]) -> str:
    """Which board these rows will be drawn as. Empty rows -> ''. """
    if not rows:
        return ""
    from automations.total_knocks.render import knocks_shape
    return knocks_shape(rows)
