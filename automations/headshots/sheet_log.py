"""Tick the "Headshot Photo" box on the week's D2D OBCL tab, and tint it green.

Megan 2026-08-24: once a headshot actually lands on the rep's OwnerVille
profile, mark them off on the recruiting team's own sheet — "checkmark the
box and make it green", the same shape blueink_docs already uses for its
"Blue Ink" column on these tabs.

Three things about these tabs the lookup has to survive (all learned by the
Blue Ink report first):

1. **A new tab every week** — "D2D OBCL 8.24", "D2D OBCL 8.31", … We resolve
   by DATE, never by position, and never use the rolling undated "D2D OBCL"
   tab (it stacks every week ever).
2. **A tab can hold several sections** — a date row, a header row, people,
   then a blank row and ANOTHER date + header row for the late adds. Every
   section is parsed, so a late add can't be silently missed.
3. **Columns move** — everything is found by its header LABEL, per section.

Names are matched with the same typo tolerance as the OwnerVille lookup, and
with the same refusal to guess: two near-equal candidates mean nobody gets
marked (marking the wrong person would tell the admins a rep is done when
they aren't).

    # who would be marked, writes nothing:
    python -m automations.headshots.sheet_log --name "Hayden Wilson" --dry-run

    # tick + tint:
    python -m automations.headshots.sheet_log --name "Hayden Wilson"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

from automations.shared import obcl_charts

# Same workbook the Blue Ink report and bg_check_sync write to.
SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
DATED_TAB_PREFIX = "D2D OBCL"

COL_FIRST = "Name"
COL_LAST = "Last Name"
COL_HEADSHOT = "Headshot Photo"

# Google Sheets' "light green 3" (#D9EAD3) — the tint already used by hand on
# these tabs, so an automated mark looks like a manual one.
LIGHT_GREEN = {"red": 0xD9 / 255, "green": 0xEA / 255, "blue": 0xD3 / 255}

_TAB_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\s*$")


class SheetLogError(RuntimeError):
    pass


def _client():
    from automations.recruiting_report.fill import _client as c
    return c()


def tab_date(title: str, today: dt.date | None = None) -> dt.date | None:
    """'D2D OBCL 8.24' -> date(2026, 8, 24). None if it isn't a dated tab."""
    if not title.strip().lower().startswith(DATED_TAB_PREFIX.lower()):
        return None
    m = _TAB_DATE.search(title)
    if not m:
        return None
    today = today or dt.date.today()
    month, day = int(m.group(1)), int(m.group(2))
    year = int(m.group(3) or 0)
    if year and year < 100:
        year += 2000
    if not year:
        # No year on the tab: assume the nearest sensible one.
        year = today.year
        try:
            cand = dt.date(year, month, day)
        except ValueError:
            return None
        if (cand - today).days > 180:      # e.g. "12.29" seen in January
            year -= 1
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def find_week_tab(sh, today: dt.date | None = None):
    """The dated OBCL tab for the current week — the newest one dated on or
    before today. (Raf's team creates the tab on/just before the Monday.)"""
    today = today or dt.date.today()
    dated = []
    for ws in sh.worksheets():
        d = tab_date(ws.title, today)
        if d:
            dated.append((d, ws))
    if not dated:
        raise SheetLogError(
            f"no dated {DATED_TAB_PREFIX!r} tab in the workbook")
    past = [(d, w) for d, w in dated if d <= today]
    chosen = max(past or dated, key=lambda t: t[0])
    return chosen[1], chosen[0]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def sections(values: list[list[str]]) -> list[dict]:
    """Every CHART on the tab: its header row, its people, its label->column map.

    Delegates to automations.shared.obcl_charts, which both this and the Blue
    Ink report use. It had its own copy of this until 2026-08-24 and was
    missing two rules the Blue Ink reader had already learned the hard way:
    a chart ENDS at a blank row (else 25 stray name rows below the chart read
    as people), and a chart opened by a DATE row with no header of its own
    still counts (else Monday's pasted-in second chart vanishes).

    Keys are kept as they were -- header_row / end_row, both 1-indexed, with
    end_row EXCLUSIVE as find_person's range() expects.
    """
    charts = obcl_charts.find_charts(values, first_label=COL_FIRST,
                                     last_label=COL_LAST)
    out = []
    for c in charts:
        out.append({
            # A chart with no header of its own has header_row None; report the
            # row before its first person so range(header_row, end_row) still
            # walks exactly its people.
            "header_row": (c["header_row"] if c["header_row"]
                           else c["start_row"] - 1),
            "end_row": c["end_row"],       # exclusive for range(), see below
            "cols": c["cols"],
        })
    return out


def _name_key_of(s: str) -> str:
    from automations.headshots.ov_upload import _name_key
    return _name_key(s or "")


def find_person(values: list[list[str]], name: str, *, verbose: bool = True):
    """(row, headshot_col, matched_name) for `name`, or (None, None, reason).

    Typo-tolerant, and refuses to choose between near-equal candidates."""
    from automations.headshots.ov_upload import (_MIN_MARGIN, _MIN_SCORE,
                                                 _name_score)
    cands = []
    for sec in sections(values):
        cols = sec["cols"]
        c_first, c_last = cols.get(COL_FIRST), cols.get(COL_LAST)
        c_head = cols.get(COL_HEADSHOT)
        if not (c_first and c_last):
            continue
        for r in range(sec["header_row"], sec["end_row"]):
            row = values[r] if r < len(values) else []
            first = _norm(row[c_first - 1]) if len(row) >= c_first else ""
            last = _norm(row[c_last - 1]) if len(row) >= c_last else ""
            full = f"{first} {last}".strip()
            if not full or first == COL_FIRST:
                continue
            cands.append((_name_score(name, full), r + 1, c_head, full))
    if not cands:
        return None, None, "no people found on the tab"
    cands.sort(reverse=True)
    best, row, c_head, got = cands[0]
    runner = cands[1][0] if len(cands) > 1 else 0.0
    runner_name = cands[1][3] if len(cands) > 1 else ""
    if best < _MIN_SCORE:
        return None, None, f"no row matches (closest {got!r} at {best:.2f})"
    # Two rows carrying the SAME name is a duplicate (a person listed in two
    # sections of the tab), not an ambiguity — mark the topmost and move on.
    # Only DIFFERENT near-twin names are a real "don't guess" (Ana Gonzalez
    # vs Ana Griffin).
    same = _name_key_of(got) == _name_key_of(runner_name)
    if not same and best - runner < _MIN_MARGIN:
        return None, None, (f"ambiguous — {got!r} ({best:.2f}) vs "
                            f"{runner_name!r} ({runner:.2f})")
    if not c_head:
        return None, None, f"no {COL_HEADSHOT!r} column in {got!r}'s section"
    if verbose and best < 1.0:
        print(f"    sheet: matched {name!r} -> {got!r} ({best:.2f})")
    return row, c_head, got


def mark(ws, row: int, col: int, *, dry_run: bool = False) -> None:
    """Tick the checkbox and tint the cell green — ONE batched request.

    Only this cell is touched; a per-cell loop would burn the write quota and
    429 the next report as well as this one."""
    if dry_run:
        return
    ws.spreadsheet.batch_update({"requests": [{
        "repeatCell": {
            "range": {"sheetId": ws.id,
                      "startRowIndex": row - 1, "endRowIndex": row,
                      "startColumnIndex": col - 1, "endColumnIndex": col},
            "cell": {"userEnteredValue": {"boolValue": True},
                     "userEnteredFormat": {"backgroundColor": LIGHT_GREEN}},
            "fields": ("userEnteredValue,"
                       "userEnteredFormat.backgroundColor"),
        }
    }]})


def log_upload(name: str, *, dry_run: bool = False,
               verbose: bool = True) -> dict:
    """Mark `name`'s Headshot Photo cell on this week's OBCL tab."""
    sh = _client().open_by_key(SHEET_ID)
    ws, when = find_week_tab(sh)
    values = ws.get_values("A1:CM400")
    row, col, got = find_person(values, name, verbose=verbose)
    if row is None:
        return {"status": "not_marked", "name": name, "tab": ws.title,
                "reason": got}
    cur = ""
    if row - 1 < len(values) and col - 1 < len(values[row - 1]):
        cur = _norm(values[row - 1][col - 1]).upper()
    if cur == "TRUE":
        return {"status": "already_marked", "name": name, "tab": ws.title,
                "row": row, "matched_as": got}
    mark(ws, row, col, dry_run=dry_run)
    return {"status": "would_mark" if dry_run else "marked", "name": name,
            "tab": ws.title, "row": row, "matched_as": got}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Tick the Headshot Photo box on the week's OBCL tab.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    res = log_upload(args.name, dry_run=args.dry_run)
    print(res)
    return 0 if res["status"] in ("marked", "would_mark",
                                  "already_marked") else 1


if __name__ == "__main__":
    sys.exit(main())
