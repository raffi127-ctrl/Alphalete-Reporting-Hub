"""Vantura "P&L 2026" — the clean, week-by-week P&L tab (Carlos, 2026-07-30).

The working tab ('Copy of Carlos PNL 2026') stays as-is: it is the calculation
engine, 3 columns per week, with the messy per-campaign DD/payroll/NPA stack in
rows 190-217. This module renders a READ-ONLY presentation of it — ONE column
per week, the Revenue-by-Campaign shape Carlos likes (Revenue Brought In / Paid
Out / Payroll Tax / Profit / Profit Margin %) applied to the TOTAL and to each
campaign, plus an active-reps revenue table underneath.

Every cell is a LIVE formula pointing at the working tab, so the numbers move
the moment the engine moves (an adjustment + Refresh shows up here instantly).
The Wednesday payroll run calls build() again to pick up the new week and
re-resolve row positions, which drift as the roster grows.

  .venv/bin/python -m automations.vantura_payroll.clean_pnl            # build
  .venv/bin/python -m automations.vantura_payroll.clean_pnl --dry-run  # preview

Rep filter (Carlos's rule): a rep shows only if they brought in revenue in
either of the last two populated weeks. Two quiet weeks and they drop off —
leader or not, the tab only ever shows who is currently producing.
"""
from __future__ import annotations

import argparse
import sys

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
SRC_TAB = "Copy of Carlos PNL 2026"
DST_TAB = "P&L 2026"

# Working-tab geometry. Rows are found BY LABEL (they shift whenever roster rows
# are inserted); only the labels themselves are constants.
SUMMARY_LABELS = {
    "total_dd": "Carlos Total DD",         # = the 3 campaign DDs; excludes captain
    "total_payroll": "Carlos Total Payroll",
    "total_tax": "Total Payroll Tax",
    "total_pnl": "TOTAL PNL",
    "captain": "Captain",
}
REV_TITLE = "Revenue by Campaign"
CAMPAIGNS = ("B2B", "BOX", "Base")
REP_FIRST = 3          # working-tab roster rows; last is found by scanning
ACTIVE_LOOKBACK = 2    # weeks of no revenue before a rep drops off

_HDR_BG = {"red": 0.52156866, "green": 0.1254902, "blue": 0.047058824}
_SEC_BG = {"red": 0.85, "green": 0.85, "blue": 0.85}
_MONEY = {"type": "CURRENCY", "pattern": '"$"#,##0.00'}
_PCT = {"type": "PERCENT", "pattern": "0.0%"}


def _log(m):
    print(m, flush=True)


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _find(seq, label, after=0, wanted=1):
    """Row of the nth `label` in seq [(row, text)] strictly after `after`."""
    n = 0
    for row, text in seq:
        if row > after and text == label:
            n += 1
            if n == wanted:
                return row
    return None


def read_source(sh, log=_log) -> dict:
    """Map every WE block on the working tab -> its columns and label rows."""
    src = sh.worksheet(SRC_TAB)
    grid = src.get_all_values()
    row1 = grid[0] if grid else []
    weeks = []
    for i, h in enumerate(row1, start=1):
        if str(h).strip().startswith("WE "):
            weeks.append((i, str(h).strip()))
    if not weeks:
        raise RuntimeError(f"no 'WE m/d' headers in row 1 of {SRC_TAB!r}")

    # last roster row = last row with a first name in col D above the summary
    last_rep = REP_FIRST
    for r in range(REP_FIRST, min(len(grid), 400)):
        row = grid[r - 1] if r - 1 < len(grid) else []
        first = (row[3].strip() if len(row) > 3 else "")
        if first:
            last_rep = r

    blocks = {}
    for c, hdr in weeks:
        labels = src.get(f"{col_letter(c + 1)}{last_rep + 1}:"
                         f"{col_letter(c + 1)}{last_rep + 110}")
        seq = [(last_rep + 1 + i, (r[0] if r else "").strip())
               for i, r in enumerate(labels)]
        b = {"bro": col_letter(c), "paid": col_letter(c + 1),
             "prof": col_letter(c + 2), "header": hdr}
        for key, lab in SUMMARY_LABELS.items():
            b[key] = _find(seq, lab)
        rev = _find(seq, REV_TITLE)
        b["rev_title"] = rev
        if rev:
            prev = rev
            for camp in CAMPAIGNS:
                b[camp] = _find(seq, camp, after=prev)
                prev = b[camp] or prev
        blocks[hdr] = b
    live = [h for h, b in blocks.items() if b.get("rev_title")]
    log(f"source: {len(weeks)} week blocks, roster rows {REP_FIRST}-{last_rep}, "
        f"{len(live)} with a Revenue-by-Campaign block")
    return {"src": src, "grid": grid, "weeks": weeks, "blocks": blocks,
            "live": live, "last_rep": last_rep}


def _rep_rows(info) -> list:
    """[(row, 'First Last')] for every named roster row on the working tab."""
    out = []
    for r in range(REP_FIRST, info["last_rep"] + 1):
        row = info["grid"][r - 1] if r - 1 < len(info["grid"]) else []
        first = (row[3].strip() if len(row) > 3 else "")
        last = (row[4].strip() if len(row) > 4 else "")
        if first:
            out.append((r, f"{first} {last}".strip()))
    return out


def _money(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("(", "-")
                     .replace(")", "").strip() or 0)
    except ValueError:
        return 0.0


def active_reps(info, log=_log) -> list:
    """Carlos's rule: keep a rep only if they brought in revenue in either of
    the last two populated weeks. Leaders are not exempt."""
    recent = info["live"][-ACTIVE_LOOKBACK:]
    cols = [info["blocks"][h]["bro"] for h in recent]
    idx = [sum((ord(ch) - 64) * 26 ** i
               for i, ch in enumerate(reversed(c))) for c in cols]
    keep = []
    for row, name in _rep_rows(info):
        g = info["grid"][row - 1] if row - 1 < len(info["grid"]) else []
        if any(_money(g[i - 1]) > 0 for i in idx if i - 1 < len(g)):
            keep.append((row, name))
    log(f"active reps: {len(keep)} (revenue in {recent})")
    return keep


def build(*, write: bool = True, log=_log) -> dict:
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    info = read_source(sh, log=log)
    # Only weeks that have actually been run. A blank column per un-started week
    # would push the live ones off-screen; the Wednesday rebuild adds each new
    # week as it lands.
    order = info["live"]
    reps = active_reps(info, log=log)

    q = f"'{SRC_TAB}'!"
    rows: list[list] = []
    fmt: list[tuple] = []          # (row_index0, kind)

    def add(label, per_week=None, kind=None, bold=False):
        r = [label]
        for hdr in order:
            r.append(per_week(info["blocks"][hdr]) if per_week else "")
        rows.append(r)
        fmt.append((len(rows) - 1, kind, bold))

    def ref(b, row):
        return f"={q}{b['prof']}{row}" if row else ""

    def margin(b, num_row, den_row):
        if not (num_row and den_row):
            return ""
        return (f"=IFERROR(IF({q}{b['prof']}{den_row}=0,\"\","
                f"{q}{b['prof']}{num_row}/{q}{b['prof']}{den_row}),\"\")")

    add("VANTURA — P&L 2026", kind="title", bold=True)
    add("")
    add("TOTAL", kind="section", bold=True)
    add("Revenue Brought In (no captainship)", lambda b: ref(b, b["total_dd"]), "money")
    add("Captainship Bonus", lambda b: ref(b, b["captain"]), "money")
    # A week with no Captain's Bonus line has no captain row at all — fall back
    # to the plain DD rather than blanking the whole row.
    add("Total DD (with captainship)",
        lambda b: ("" if not b["total_dd"] else
                   f"={q}{b['prof']}{b['total_dd']}+{q}{b['prof']}{b['captain']}"
                   if b["captain"] else f"={q}{b['prof']}{b['total_dd']}"), "money")
    add("Paid Out", lambda b: ref(b, b["total_payroll"]), "money")
    add("Payroll Tax", lambda b: ref(b, b["total_tax"]), "money")
    add("Total Gross Profit", lambda b: ref(b, b["total_pnl"]), "money", bold=True)
    add("Profit Margin %", lambda b: margin(b, b["total_pnl"], b["total_dd"]), "pct")
    add("")

    for camp in CAMPAIGNS:
        add(camp, kind="section", bold=True)
        add("Revenue Brought In",
            lambda b, c=camp: ref(b, b[c] + 1 if b.get(c) else None), "money")
        add("Paid Out",
            lambda b, c=camp: ref(b, b[c] + 2 if b.get(c) else None), "money")
        add("Payroll Tax",
            lambda b, c=camp: ref(b, b[c] + 3 if b.get(c) else None), "money")
        add("Profit",
            lambda b, c=camp: ref(b, b[c] + 4 if b.get(c) else None), "money", bold=True)
        add("Profit Margin %",
            lambda b, c=camp: margin(b, b[c] + 4 if b.get(c) else None,
                                     b[c] + 1 if b.get(c) else None), "pct")
        add("")

    add("REVENUE BROUGHT IN BY REP  (active only — 2 quiet weeks drops off)",
        kind="section", bold=True)
    for rep_row, name in reps:
        rows.append([name] + [f"={q}{info['blocks'][h]['bro']}{rep_row}"
                              for h in order])
        fmt.append((len(rows) - 1, "money", False))

    n_rows, n_cols = len(rows), len(order) + 1
    log(f"clean P&L: {n_rows} rows x {n_cols} cols "
        f"({len(reps)} active reps, {len(order)} weeks)")
    if not write:
        for r in rows[:14]:
            log("   " + " | ".join(str(x)[:34] for x in r[:3]))
        return {"rows": n_rows, "cols": n_cols, "reps": len(reps), "written": False}

    try:
        dst = sh.worksheet(DST_TAB)
        dst.clear()
    except Exception:  # noqa: BLE001 — first build creates it
        dst = sh.add_worksheet(title=DST_TAB, rows=max(n_rows + 40, 200),
                               cols=max(n_cols + 4, 60))
    if dst.row_count < n_rows + 5:
        dst.add_rows(n_rows + 5 - dst.row_count)
    if dst.col_count < n_cols + 2:
        dst.add_cols(n_cols + 2 - dst.col_count)

    header = [""] + order
    dst.update(values=[header] + rows, range_name=f"A1:{col_letter(n_cols)}{n_rows + 1}",
               value_input_option="USER_ENTERED")

    sid = dst.id

    def rng(r0, r1, c0, c1):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}
    reqs = [
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenRowCount": 1,
                                               "frozenColumnCount": 1}},
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
        {"repeatCell": {"range": rng(0, 1, 0, n_cols), "cell": {"userEnteredFormat": {
            "backgroundColor": _HDR_BG, "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True, "foregroundColor": {
                "red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
        {"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 300}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": n_cols},
            "properties": {"pixelSize": 108}, "fields": "pixelSize"}},
    ]
    for i, kind, bold in fmt:
        r = i + 1  # +1 for the header row
        if kind in ("title", "section"):
            reqs.append({"repeatCell": {"range": rng(r, r + 1, 0, n_cols),
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _HDR_BG if kind == "title" else _SEC_BG,
                    "textFormat": {"bold": True, "foregroundColor": (
                        {"red": 1, "green": 1, "blue": 1} if kind == "title"
                        else {"red": 0, "green": 0, "blue": 0})}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
        elif kind in ("money", "pct"):
            reqs.append({"repeatCell": {"range": rng(r, r + 1, 1, n_cols),
                "cell": {"userEnteredFormat": {
                    "numberFormat": _MONEY if kind == "money" else _PCT,
                    "horizontalAlignment": "CENTER",
                    "textFormat": {"bold": bold}}},
                "fields": "userEnteredFormat(numberFormat,horizontalAlignment,textFormat)"}})
    sh.batch_update({"requests": reqs})
    log(f"wrote {DST_TAB!r} (gid {sid})")
    return {"rows": n_rows, "cols": n_cols, "reps": len(reps),
            "weeks": len(order), "gid": sid, "written": True}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    out = build(write=not a.dry_run)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
