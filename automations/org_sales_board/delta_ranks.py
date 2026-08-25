"""Rank numbers (col A) for the DELTA boxes at the bottom of the Org Sales Board.

The 'Total this week / Last week / Delta' box of every captainship is the only
per-rep table on the board that was never numbered. Five of them carry 1..N in
col A (Raf x2, Carlos, Eveliz, Wayne's NEW INTERNET) and the rest do not, so the
same captain's two boxes disagree with each other — Wayne's NEW INTERNET box is
numbered and his ALL UNITS box right below it is not (Eve, 2026-08-25).

Two jobs, done per box and independent of each other:

  1. NUMBER the rep rows 1..N in col A.
  2. CLOSE the header and footer bars over that new gutter, so the box reads as
     one table and not as a band with a number column hanging off its left edge
     (Eve, 2026-08-25: "los encabezados y los pies tienen que quedar fluidos").

Both COPY EACH BOX'S OWN FORMAT rather than stamping one house style: the title
bar is a different colour per box (#FF6D01 on Wayne's first, #BD6422 on his
second) and every one keeps whatever it has. Col A of a bar takes its col-B
neighbour's format verbatim; the rank cells take col B's font, centered, with no
fill and only the top/bottom rules — exactly what the already-numbered boxes
look like.

THE BAR: MOVE THE LABEL, THEN MERGE. A mergeCells over a col B that still holds
its label leaves that text in the grid, hidden under the merge but still read by
every col-B parser on this board — so the label is written into col A and col B
cleared BEFORE the merge, which is why values go out in their own batch first.
Three shapes exist and all three end up the same: already merged across A:B
(nothing to do), merged across col B only and two rows tall (that merge is
dropped and re-made one column wider), or not merged at all.

WHAT READS THESE LABELS. Moving a title from col B to col A is only safe because
both readers were taught to look in either column: `cap_insert._delta_captain`
(which decides whose box this is — it was already blind to Raf's, Carlos' and
Eveliz' boxes, whose titles have lived in col A all along) and
`rollover.check_delta_totals_lastweek`'s report label.

RENUMBERING AFTERWARDS IS ALREADY HANDLED. `new_owners/cap_insert.tables_for`
decides a table is ranked by looking at col A of its first row, so once these
carry a number an insert renumbers them like any other table. `roster_remove`
had delta tables pinned to ranked=False and now derives it the same way.

A box whose col A holds a manual marker instead of a rank (RAF SPECIAL TEAM's
'*') is left alone and reported — those asterisks are somebody's notes.

    python -m automations.org_sales_board.delta_ranks              # dry-run
    python -m automations.org_sales_board.delta_ranks --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB      # noqa: E402
from automations.org_sales_board import rollover as ro                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_SHEET_ID_CACHE: Dict[str, int] = {}

# A trailing SUMMARY line, not a rep. `find_delta_tables` stops at a blank col B
# or a 'Captainship' label, which covers most boxes — but TRANG'S ORG closes with
# 'Total Org' and RAF SPECIAL TEAM with 'TOTAL' / 'Raf Org' / 'Carlos Org', and
# those rows would otherwise take a rank number of their own.
DELTA_SUMMARY_RE = re.compile(r"^(total|totals|grand total|captainship)\b|\borg$", re.I)


def _cell(grid, r1: int, c1: int) -> str:
    """1-based, like rollover's own helper."""
    r, c = r1 - 1, c1 - 1
    return (grid[r][c] if r < len(grid) and c < len(grid[r]) else "").strip()


def _title(grid, header_row: int) -> str:
    """The box's name, wherever it sits: the numbered boxes label themselves in
    col A, the un-numbered ones in col B."""
    parts = []
    for r in (header_row - 1, header_row):
        for c in (1, 2):
            v = _cell(grid, r, c)
            if v and v.lower() not in ("total for week", "total this week"):
                parts.append(v)
    return " / ".join(parts) if parts else f"row {header_row}"


def _rank_format(bfmt: dict) -> dict:
    """The gutter style, taken from the box's own col-B cell: same font, no
    fill, centered, only the horizontal rules. Mirrors what col A looks like in
    the boxes that are already numbered."""
    out = {"horizontalAlignment": "CENTER"}
    if "verticalAlignment" in bfmt:
        out["verticalAlignment"] = bfmt["verticalAlignment"]
    tf = dict(bfmt.get("textFormat") or {})
    tf.pop("bold", None)
    if tf:
        out["textFormat"] = tf
    borders = bfmt.get("borders") or {}
    edge = borders.get("bottom") or borders.get("top") or {"style": "SOLID",
                                                           "width": 1}
    out["borders"] = {"top": dict(edge), "bottom": dict(edge)}
    return out


def _merged_cols_ab(merges, row1: int) -> bool:
    """Does a merge cover col A or B on this row? Painting into a merged cell
    would move the band, so those rows are left alone."""
    r = row1 - 1
    return any(m.get("startRowIndex", 0) <= r < m.get("endRowIndex", 0)
               and m.get("startColumnIndex", 0) < 2
               for m in merges)


def _one_cell(row1: int, fmt: dict) -> dict:
    return {"updateCells": {
        "range": {"sheetId": _SHEET_ID_CACHE["id"],
                  "startRowIndex": row1 - 1, "endRowIndex": row1,
                  "startColumnIndex": 0, "endColumnIndex": 1},
        "rows": [{"values": [{"userEnteredFormat": fmt}]}],
        "fields": "userEnteredFormat"}}


def _ab_range(first_row: int, last_row: int) -> dict:
    return {"sheetId": _SHEET_ID_CACHE["id"],
            "startRowIndex": first_row - 1, "endRowIndex": last_row,
            "startColumnIndex": 0, "endColumnIndex": 2}


def _merge_ab(first_row: int, last_row: int) -> dict:
    return {"mergeCells": {"mergeType": "MERGE_ALL",
                           "range": _ab_range(first_row, last_row)}}


def _merges_at(merges, row1: int) -> list:
    """Merges touching col A or B on this row."""
    r = row1 - 1
    return [m for m in merges
            if m.get("startRowIndex", 0) <= r < m.get("endRowIndex", 0)
            and m.get("startColumnIndex", 0) < 2]


def _covers_ab(m) -> bool:
    return m.get("startColumnIndex", 0) == 0 and m.get("endColumnIndex", 0) >= 2


def _bar(grid, formulas, fmts, merges, bar: List[int]):
    """Turn one header/footer line into a single bar across A:B — the shape the
    numbered boxes already have. Returns (values, requests, note).

    Three shapes exist on the board today. Already merged over A:B (Raf, Carlos,
    Wayne's first box, Starr): nothing to do. Merged over col B only, usually
    two rows tall (Khalil, Colten, Jairo, Raf Special, Trang, Luis, Atef): the
    B-merge is dropped and re-made one column wider. Not merged at all (Wayne's
    second box, Chan, Tony, Sahil, and every 'Captainship' totals line): the
    label moves A<-B and the pair is merged.

    The label MOVES rather than the merge simply swallowing col B: a mergeCells
    over a col-B that still holds text leaves that text in the grid, hidden
    under the merge but still read by every col-B parser on this board."""
    ms = [m for r in bar for m in _merges_at(merges, r)]
    if ms and all(any(_covers_ab(m) for m in _merges_at(merges, r)) for r in bar):
        return [], [], ""                       # already one bar across A:B
    values, requests = [], []
    for m in {(m["startRowIndex"], m["endRowIndex"],
               m.get("startColumnIndex", 0), m["endColumnIndex"]): m
              for m in ms}.values():
        requests.append({"unmergeCells": {"range": m}})
    src = next((r for r in bar if _cell(grid, r, 2)), None)
    if src is not None:
        label = _cell(grid, src, 2)
        if str(formulas_at(formulas, src, 2)).startswith("="):
            return [], [], f"col B de f{src} es una fórmula, no la muevo"
        if _cell(grid, src, 1):
            return [], [], f"col A de f{src} ya tiene texto, no piso nada"
        values.append({"range": f"A{src}:B{src}", "values": [[label, ""]]})
    fmt_src = fmts.get((src if src is not None else bar[0], 2))
    for r in bar:
        f = fmts.get((r, 2)) or fmt_src
        if f is not None:
            requests.append(_one_cell(r, f))
    requests.append(_merge_ab(bar[0], bar[-1]))
    return values, requests, ""


def _rep_rows(grid, t) -> List[int]:
    """The REP rows of a delta box — `find_delta_tables`' data rows with the
    trailing summary lines dropped."""
    rows = list(t["data_rows"])
    while rows and DELTA_SUMMARY_RE.search(_cell(grid, rows[-1], 2)):
        rows.pop()
    return rows


def _band_rows(grid, t, rows: List[int]) -> List[int]:
    """The rows that have to read as ONE bar across A:B — the two title rows
    above the header, and every summary line that closes the box. Most boxes
    close with a single 'Captainship' row; TRANG'S ORG closes with 'Total Org'
    and RAF SPECIAL TEAM with three ('TOTAL', 'Raf Org', 'Carlos Org'). A
    closing line is one that still carries a 'Total this week' value in col C."""
    band = [t["header_row"] - 1, t["header_row"]]
    r = (rows[-1] if rows else t["header_row"]) + 1
    while _cell(grid, r, 3) and r <= len(grid):
        band.append(r)
        r += 1
    return band


def plan(grid, formulas, fmts: Dict[Tuple[int, int], dict],
         merges) -> Tuple[list, list, list]:
    """(value updates, format requests, notes) for every delta box.

    Two independent jobs per box, so one can be skipped without losing the
    other: NUMBER the rep rows, and close the header/footer bars over the new
    gutter (col A painted like its col-B neighbour, the label moved A←B, then
    A:B merged — the shape the already-numbered boxes have)."""
    values: List[dict] = []
    requests: List[dict] = []
    notes: List[str] = []
    for t in ro.find_delta_tables(grid):
        rows = _rep_rows(grid, t)
        if not rows:
            continue
        name = _title(grid, t["header_row"])
        have = [_cell(grid, r, 1) for r in rows]
        done = []

        # --- 1. the rank gutter -------------------------------------------
        odd = sorted({v for v in have if v and not v.isdigit()})
        blocked = [r for r in rows if _merged_cols_ab(merges, r)]
        if have == [str(i + 1) for i in range(len(rows))]:
            done.append("números ya puestos")
        elif odd:
            notes.append(f"  SALTEO  {name} (f{rows[0]}-{rows[-1]}) — col A "
                         f"tiene marcas a mano: {odd}")
        elif rows != list(range(rows[0], rows[0] + len(rows))):
            notes.append(f"  SALTEO  {name} — filas de reps no contiguas")
        elif blocked:
            notes.append(f"  SALTEO  {name} — A:B combinadas en {blocked}")
        else:
            values.append({"range": f"A{rows[0]}:A{rows[-1]}",
                           "values": [[i + 1] for i in range(len(rows))]})
            for r in rows:
                requests.append(_one_cell(r, _rank_format(fmts.get((r, 2)) or {})))
            done.append(f"1..{len(rows)} en f{rows[0]}-{rows[-1]}")

        # --- 2. the header / footer bars ----------------------------------
        # The two title rows are ONE bar when only one of them is labelled (a
        # two-row-tall title), two bars when each carries its own line
        # ("<name>'s Captainship" over "ALL UNITS").
        head = [t["header_row"] - 1, t["header_row"]]
        titled = [r for r in head if _cell(grid, r, 2) or _cell(grid, r, 1)]
        bars = ([[r] for r in head] if len(titled) > 1 else [head])
        bars += [[r] for r in _band_rows(grid, t, rows)[2:]]
        made = []
        for bar in bars:
            v, rq, why = _bar(grid, formulas, fmts, merges, bar)
            if why:
                notes.append(f"  SALTEO  {name} banda f{bar[0]} — {why}")
                continue
            values += v
            requests += rq
            if rq:
                made.append(bar[0] if len(bar) == 1 else f"{bar[0]}-{bar[-1]}")
        if made:
            done.append(f"banda A:B en {made}")

        touched = bool(made) or (bool(done) and done[0] != "números ya puestos")
        notes.append(f"  {'arreglo' if touched else 'ok     '} {name} — "
                     + ("; ".join(done) if done else "nada que hacer"))
    return values, requests, notes


def formulas_at(formulas, r1: int, c1: int):
    r, c = r1 - 1, c1 - 1
    return formulas[r][c] if r < len(formulas) and c < len(formulas[r]) else ""


def read_formats(sh, tab: str, first: int, last: int):
    """userEnteredFormat for A:B over the delta section, plus the tab's merges,
    in one metadata call."""
    res = _retry(sh.fetch_sheet_metadata, {
        "includeGridData": True,
        "ranges": [f"'{tab}'!A{first}:B{last}"],
        "fields": ("sheets(properties(sheetId),merges,"
                   "data(startRow,startColumn,rowData(values(userEnteredFormat))))")})
    s = res["sheets"][0]
    _SHEET_ID_CACHE["id"] = s["properties"]["sheetId"]
    d = (s.get("data") or [{}])[0]
    sr, sc = d.get("startRow", 0), d.get("startColumn", 0)
    out = {}
    for i, row in enumerate(d.get("rowData") or []):
        for j, v in enumerate(row.get("values") or []):
            f = v.get("userEnteredFormat")
            if f is not None:
                out[(sr + i + 1, sc + j + 1)] = f
    return out, s.get("merges") or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="numera los delta boxes del board")
    ap.add_argument("--apply", action="store_true",
                    help="escribir (por defecto: dry-run)")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    args = ap.parse_args(argv)

    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(args.tab)
    grid = _retry(ws.get_all_values)
    tables = ro.find_delta_tables(grid)
    if not tables:
        print("no hay tablas delta en la pestaña")
        return 1
    first = min(t["header_row"] for t in tables) - 1
    last = max((t["data_rows"] or [t["header_row"]])[-1] for t in tables) + 4
    fmts, merges = read_formats(sh, args.tab, first, last)
    # A label is only safe to move A<-B if it is TEXT. Nothing on these bars is
    # a formula today, but a '=' in col B would move as a string and the bar
    # would show the formula instead of its result.
    formulas = _retry(lambda: ws.get_all_values(value_render_option="FORMULA"))

    values, requests, notes = plan(grid, formulas, fmts, merges)
    print(f"=== delta ranks · {args.tab} "
          f"({'LIVE' if args.apply else 'DRY-RUN'}) ===")
    for n in notes:
        print(n)
    print(f"  -> {len(values)} escritura(s) de valores, {len(requests)} "
          f"pedido(s) de formato/merge")
    if not values and not requests:
        return 0
    if not args.apply:
        print("  (dry-run — corré con --apply para escribir)")
        return 0
    # Values FIRST, merges after: a mergeCells over a col-B that still holds the
    # label would hide it under the merge instead of showing it, and every
    # col-B parser on this board would keep reading it from down there.
    if values:
        _retry(sh.values_batch_update, {
            "valueInputOption": "USER_ENTERED",
            "data": [{"range": f"'{args.tab}'!{v['range']}", "values": v["values"]}
                     for v in values]})
    if requests:
        _retry(sh.batch_update, {"requests": requests})
    print("  listo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
