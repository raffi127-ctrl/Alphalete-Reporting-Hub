"""Financial Bulletin — Rafael's old 'Financials Report' workbook, rebuilt live
in the Alphalete Org workbook (Rafael, Slack 2026-10-18: "recreate that report
and have the data live in the org spreadsheet").

The numbers are NOT pulled again: the financial report already writes every
owner's weekly Total Funds Available / Owners Payroll / Owners Withdrawal /
Operating % into the financial section of their Focus Report tab. This reads
those sections back across the four focus workbooks and lays them out the way
Rafael's bulletin did — one block per metric, owners down, weeks across — plus
what he asked for on top of it: an average column per owner, a per-owner
average row for every week, and a summary table up top with each owner's
average money saved / pay / withdrawal and operating %.

  Money saved          = 'Total Funds Available' (the bulletin's first block)
  Owners pay           = 'Owners Payroll'
  Withdrawal/dividend  = 'Owners Withdrawal'
  Operating %          = 'Operating %'

Averages skip blank weeks (an owner whose book didn't come in that week is not
a $0 week). Only the tab this script creates is ever written.

Runs on its own as the last step of the Financial Pull (financial_report.run),
right after the ICD tabs are filled — so it is always as fresh as they are.
It went straight to production (Eve 2026-10-20: a new report, no tab to
protect; changes get made on the live tab).

Usage:
  python -m automations.financial_bulletin.run            # the real tab
  python -m automations.financial_bulletin.run --dry-run  # print, no writes
  python -m automations.financial_bulletin.run --sandbox  # a SANDBOX copy
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill as rfill
from automations.financial_report import fill as ffill
from automations.financial_report import run as frun
from automations.alphalete_org_report.opt_nds import ALPHALETE_ORG_SHEET_ID

LIVE_TAB = "Financial Bulletin"
SANDBOX_TAB = "Financial Bulletin SANDBOX"
WEEKS_SHOWN = 8

# (row label on the focus tab, heading on the bulletin, kind)
METRICS: List[Tuple[str, str, str]] = [
    ("Total Funds Available", "MONEY SAVED (Total Funds Available)", "money"),
    ("Owners Payroll", "OWNERS PAY (Owners Payroll)", "money"),
    ("Owners Withdrawal", "OWNERS WITHDRAWAL / DIVIDEND", "money"),
    ("Operating %", "OPERATING %", "pct"),
]


def _num(v) -> Optional[float]:
    """A sheet cell as a number: '$1,234.50' / '(500)' / '-3%' / '45.2%'.
    Percent cells come back as 45.2 (points), money as dollars. Blank or text
    ('CLOSED', 'Not Found In Email') → None."""
    s = str(v or "").strip()
    if not s or "not found" in s.lower():
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[,$%()\s]", "", s)
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _pct(v) -> Optional[float]:
    """Operating % in points. Most tabs show '52.3%'; the NDS tabs hold the
    bare fraction (0.523, no % format) — same number, other scale. A 0 is the
    tab's IFERROR fallback (no revenue that week), not a real 0% week."""
    x = _num(v)
    if x is None or x == 0:
        return None
    if "%" not in str(v) and abs(x) <= 1.5:
        x *= 100
    return x


def _merge_duplicates(owners: Dict[str, dict]) -> Dict[str, dict]:
    """One person under two spellings (an NDS tab spelled like the tracker,
    'Maxamad Aden' / 'Atef Choudhury', next to their ATT tab) is ONE owner:
    the ICD Aliases sheet decides the name when it knows both; otherwise two
    owners whose money-saved weeks are identical (4+ matching weeks, same
    book feeding both tabs) collapse into the first spelling."""
    try:
        from automations.focus_office_att import aliases as _al
        raw = _al.load_aliases()
        canon = lambda n: _al.alias_to_canonical(n, raw)  # noqa: E731
    except Exception:  # noqa: BLE001 — no alias sheet → names as-is
        canon = lambda n: n  # noqa: E731
    out: Dict[str, dict] = {}
    for name in sorted(owners, key=str.lower):
        m = owners[name]
        key = canon(name)
        if key not in out:
            tfa = m.get("Total Funds Available", {})
            for other, om in out.items():
                otfa = om.get("Total Funds Available", {})
                common = [d for d in tfa if d in otfa]
                if len(common) >= 4 and all(tfa[d] == otfa[d] for d in common):
                    key = other
                    break
        dst = out.setdefault(key, {})
        for label, series in m.items():
            s = dst.setdefault(label, {})
            for d, x in series.items():
                s.setdefault(d, x)
    return out


def _avg(xs: List[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def read_owners() -> Tuple[Dict[str, Dict[str, Dict[dt.date, float]]], Dict[str, str]]:
    """{owner: {metric label: {week: value}}} from every visible ICD tab's
    financial section, plus {owner: 'workbook › tab'} of where it came from.
    An owner with a tab in two workbooks (ATT + NDS) is one owner: the first
    tab seen with a value for a week wins that week — both were filled from
    the same source."""
    client = rfill._client()
    owners: Dict[str, Dict[str, Dict[dt.date, float]]] = {}
    source: Dict[str, str] = {}
    for book, sid in ffill.OUTPUT_SHEETS.items():
        sh = rfill.open_by_key(sid, client)
        hidden = frun._hidden_tab_titles(sh)
        tabs = [w.title for w in rfill._retry(sh.worksheets)
                if not frun._is_non_icd_tab(w.title) and w.title not in hidden
                and not re.search(r"template|\btest\b|sandbox", w.title, re.I)]
        resp = rfill._retry(lambda: sh.values_batch_get(
            [f"'{t}'!A1:EZ300" for t in tabs]))
        for tab, vr in zip(tabs, resp.get("valueRanges", [])):
            grid = vr.get("values", [])
            if not grid:
                continue
            date_cols = ffill._date_columns(grid[0])
            col_b = [(r[1] if len(r) > 1 else "") for r in grid]
            tfa = ffill._norm("Total Funds Available")
            anchors = [j for j, v in enumerate(col_b) if ffill._norm(v).startswith(tfa)]
            if not anchors or not date_cols:
                continue
            a = anchors[0]
            section = {ffill._norm(col_b[j]): grid[j]
                       for j in range(a, min(a + ffill._SECTION_SPAN, len(grid)))
                       if col_b[j].strip()}
            owner = ffill._tab_to_name(tab)
            got = owners.setdefault(owner, {})
            for label, _h, kind in METRICS:
                row = section.get(ffill._norm(label))
                if row is None:
                    continue
                series = got.setdefault(label, {})
                read = _pct if kind == "pct" else _num
                for d, c in date_cols.items():
                    x = read(row[c]) if c < len(row) else None
                    if x is not None and d not in series:
                        series[d] = x
                        source.setdefault(owner, f"{book} › {tab}")
    owners = _merge_duplicates({o: m for o, m in owners.items() if any(m.values())})
    return owners, source


def pick_weeks(owners, n: int = WEEKS_SHOWN, today: Optional[dt.date] = None) -> List[dt.date]:
    """The last `n` week columns, ending at the latest week that has a Total
    Funds Available value for at least a quarter of the owners (one early
    owner shouldn't open a week everybody else is still blank in)."""
    today = today or dt.date.today()
    counts: Dict[dt.date, int] = {}
    for m in owners.values():
        for d in m.get("Total Funds Available", {}):
            if d <= today + dt.timedelta(days=8):
                counts[d] = counts.get(d, 0) + 1
    floor = max(1, len(owners) // 4)
    full = [d for d, k in counts.items() if k >= floor]
    if not full:
        return []
    last = max(full)
    return [last - dt.timedelta(weeks=i) for i in range(n - 1, -1, -1)]


def build_grid(owners, weeks: List[dt.date]) -> Tuple[List[list], List[tuple]]:
    """The bulletin as rows of values, plus (row index, ncols, style, metric
    index) marks for the formatter. The metric index picks the block's color
    (None = the navy summary)."""
    # Owners with nothing in these weeks (no source yet, closed) stay off.
    names = sorted((o for o, m in owners.items()
                    if any(s.get(d) is not None for s in m.values() for d in weeks)),
                   key=lambda s: s.lower())
    wk_lbl = [d.strftime("%m/%d/%y") for d in weeks]
    rows: List[list] = []
    marks: List[tuple] = []

    def add(row, style=None, sec=None):
        if style:
            marks.append((len(rows), len(row), style, sec))
        rows.append(row)

    def series_avg(o, label):
        s = owners[o].get(label, {})
        return _avg([s.get(d) for d in weeks])

    add([f"FINANCIAL BULLETIN — {len(names)} owners · last {len(weeks)} weeks "
         f"(WE {wk_lbl[0]} – {wk_lbl[-1]})"], "title")
    add([f"Updated {dt.date.today():%m/%d/%y}. Numbers come from each owner's "
         f"Focus Report tab (financial section). Averages skip weeks with no data."],
        "subtitle")
    add([])

    # Summary: one row per owner, Rafael's four columns.
    add(["OWNER AVERAGES"], "section")
    head = ["OWNER"] + [f"AVG {h.split(' (')[0]}" if k == "money" else "AVG OPERATING %"
                        for _l, h, k in METRICS] + ["WEEKS WITH DATA"]
    add(head, "summary_head")
    for i, o in enumerate(names):
        n = sum(1 for d in weeks
                if owners[o].get("Total Funds Available", {}).get(d) is not None)
        add([o] + [series_avg(o, l) for l, _h, _k in METRICS] + [n],
            "summary_odd" if i % 2 else "summary")
    add(["ALL OWNERS AVERAGE"]
        + [_avg([series_avg(o, l) for o in names]) for l, _h, _k in METRICS]
        + [""], "summary_avg")
    add([])

    # One block per metric, like the old bulletin.
    for sec, (label, heading, kind) in enumerate(METRICS):
        add([heading] + [""] * (len(weeks) + 1), "section", sec)
        add(["OWNER"] + wk_lbl + [f"{len(weeks)}-WK AVERAGE"], "head", sec)
        for i, o in enumerate(names):
            s = owners[o].get(label, {})
            vals = [s.get(d) for d in weeks]
            add([o] + vals + [_avg(vals)], "row_odd" if i % 2 else "row", sec)
        per_week = [[owners[o].get(label, {}).get(d) for o in names] for d in weeks]
        if kind == "money":
            add(["TOTAL"] + [sum(x for x in col if x is not None) if any(
                x is not None for x in col) else None for col in per_week] + [""],
                "total", sec)
        add(["AVERAGE PER OWNER"] + [_avg(col) for col in per_week]
            + [_avg([_avg([owners[o].get(label, {}).get(d) for d in weeks]) for o in names])],
            "total", sec)
        add([])
    rows = [[("" if v is None else v) for v in r] for r in rows]
    return rows, marks


def _rgb(hex_):
    h = hex_.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


NAVY = ("#1F3A5F", "#DCE4EF", "#F3F6FA")
# Per block: (bar, header/total tint, zebra tint) — the same order as METRICS.
PALETTE = [
    ("#2E7D32", "#C8E6C9", "#F1F8F1"),   # money saved — green
    ("#1565C0", "#BBDEFB", "#F0F7FD"),   # owners pay — blue
    ("#E65100", "#FFE0B2", "#FFF7EE"),   # withdrawal / dividend — orange
    ("#6A1B9A", "#E1BEE7", "#F8F1FA"),   # operating % — purple
]


def _fmt_requests(ws_id: int, marks, ncols: int, nrows: int) -> List[dict]:
    def rng(r, c0=0, c1=None):
        return {"sheetId": ws_id, "startRowIndex": r, "endRowIndex": r + 1,
                "startColumnIndex": c0, "endColumnIndex": c1 or ncols}

    def paint(r, c0, c1, fmt):
        reqs.append({"repeatCell": {"range": rng(r, c0, c1),
                                    "cell": {"userEnteredFormat": fmt},
                                    "fields": "userEnteredFormat(" + ",".join(fmt) + ")"}})

    money = {"type": "CURRENCY", "pattern": "$#,##0;[Red]-$#,##0"}
    pct = {"type": "NUMBER", "pattern": "0.0\"%\";[Red]-0.0\"%\""}
    white = _rgb("#FFFFFF")
    line = {"style": "SOLID", "color": _rgb("#D0D7E2")}
    kinds = [k for _l, _h, k in METRICS]
    reqs: List[dict] = [
        {"unmergeCells": {"range": {"sheetId": ws_id}}},
        {"repeatCell": {"range": {"sheetId": ws_id}, "cell": {"userEnteredFormat": {}},
                        "fields": "userEnteredFormat"}},
        {"updateSheetProperties": {"properties": {"sheetId": ws_id, "gridProperties": {
            "frozenColumnCount": 1, "hideGridlines": True}},
            "fields": "gridProperties(frozenColumnCount,hideGridlines)"}},
        {"updateDimensionProperties": {"range": {"sheetId": ws_id, "dimension": "COLUMNS",
                                                 "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 240}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": ws_id, "dimension": "COLUMNS",
                                                 "startIndex": 1, "endIndex": ncols},
                                       "properties": {"pixelSize": 115}, "fields": "pixelSize"}},
    ]
    for r, n, style, sec in marks:
        dark, mid, light = (PALETTE[sec] if sec is not None else NAVY)
        num = (pct if sec is not None and kinds[sec] == "pct" else money)
        if style == "title":
            paint(r, 0, ncols, {"backgroundColor": _rgb(NAVY[0]),
                                "verticalAlignment": "MIDDLE",
                                "textFormat": {"bold": True, "fontSize": 16,
                                               "foregroundColor": white}})
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": ws_id, "dimension": "ROWS", "startIndex": r, "endIndex": r + 1},
                "properties": {"pixelSize": 40}, "fields": "pixelSize"}})
        elif style == "subtitle":
            paint(r, 0, 1, {"textFormat": {"italic": True,
                                           "foregroundColor": _rgb("#5F6B7A")}})
        elif style == "section":
            width = n if sec is not None else 6
            paint(r, 0, width, {"backgroundColor": _rgb(dark), "verticalAlignment": "MIDDLE",
                                "textFormat": {"bold": True, "fontSize": 12,
                                               "foregroundColor": white}})
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": ws_id, "dimension": "ROWS", "startIndex": r, "endIndex": r + 1},
                "properties": {"pixelSize": 30}, "fields": "pixelSize"}})
        elif style == "summary_head":
            paint(r, 0, n, {"backgroundColor": _rgb(NAVY[1]), "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                            "textFormat": {"bold": True, "foregroundColor": _rgb(NAVY[0])}})
            # Each average column wears its block's color, so the summary
            # reads as a key for the blocks below.
            for i, (pdark, _m, _l) in enumerate(PALETTE):
                paint(r, 1 + i, 2 + i, {"backgroundColor": _rgb(pdark),
                                        "textFormat": {"bold": True, "foregroundColor": white}})
        elif style == "head":
            paint(r, 0, n, {"backgroundColor": _rgb(mid), "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True, "foregroundColor": _rgb(dark)}})
        elif style in ("summary", "summary_odd", "row", "row_odd"):
            bg = _rgb(light) if style.endswith("odd") else white
            paint(r, 0, n, {"backgroundColor": bg,
                            "borders": {"bottom": line}})
            if style.startswith("summary"):
                for i, (pdark, _m, plight) in enumerate(PALETTE):
                    paint(r, 1 + i, 2 + i, {"numberFormat": pct if kinds[i] == "pct" else money,
                                            "backgroundColor": _rgb(plight) if style.endswith("odd") else white})
                paint(r, 5, 6, {"horizontalAlignment": "CENTER"})
            else:
                paint(r, 1, n, {"numberFormat": num})
                # the average column: bold on the block's tint
                paint(r, n - 1, n, {"backgroundColor": _rgb(mid), "textFormat": {"bold": True}})
        elif style in ("total", "summary_avg"):
            paint(r, 0, n, {"backgroundColor": _rgb(mid), "textFormat": {
                "bold": True, "foregroundColor": _rgb(dark)},
                "borders": {"top": {"style": "SOLID_MEDIUM", "color": _rgb(dark)}}})
            if style == "summary_avg":
                for i in range(len(METRICS)):
                    paint(r, 1 + i, 2 + i, {"numberFormat": pct if kinds[i] == "pct" else money})
            else:
                paint(r, 1, n, {"numberFormat": num})
    return reqs


def write(rows, marks, tab: str) -> str:
    """Rewrite `tab` in the Org workbook — a tab this script owns. Creates it
    on first run; never touches any other tab."""
    sh = rfill.open_by_key(ALPHALETE_ORG_SHEET_ID, rfill._client())
    ncols = max(len(r) for r in rows)
    nrows = len(rows)
    try:
        ws = sh.worksheet(tab)
    except Exception:
        ws = rfill._retry(sh.add_worksheet, title=tab, rows=nrows + 20, cols=ncols + 2)
    if ws.row_count < nrows or ws.col_count < ncols:
        rfill._retry(ws.resize, rows=max(ws.row_count, nrows + 20), cols=max(ws.col_count, ncols + 2))
    rfill._retry(ws.clear)
    rfill._retry(ws.update, range_name="A1", values=rows, value_input_option="RAW")
    rfill._retry(sh.batch_update, {"requests": _fmt_requests(ws.id, marks, ncols, nrows)})
    return f"https://docs.google.com/spreadsheets/d/{ALPHALETE_ORG_SHEET_ID}/edit#gid={ws.id}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--sandbox", action="store_true",
                    help=f"write '{SANDBOX_TAB}' instead of the real '{LIVE_TAB}' tab")
    ap.add_argument("--weeks", type=int, default=WEEKS_SHOWN)
    a = ap.parse_args(argv)
    a.live = not a.sandbox
    owners, source = read_owners()
    weeks = pick_weeks(owners, a.weeks)
    if not weeks:
        print("financial bulletin: no week has financial data — nothing to build")
        return 1
    rows, marks = build_grid(owners, weeks)
    print(f"financial bulletin: {len(owners)} owners, weeks {weeks[0]} → {weeks[-1]}")
    if a.dry_run:
        for r in rows[:len(owners) + 6]:
            print("  ", r)
        return 0
    url = write(rows, marks, LIVE_TAB if a.live else SANDBOX_TAB)
    print(f"financial bulletin: wrote {'LIVE' if a.live else 'SANDBOX'} tab → {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
