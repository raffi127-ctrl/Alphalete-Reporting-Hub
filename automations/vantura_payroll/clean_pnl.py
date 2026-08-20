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
_WHITE = {"red": 1, "green": 1, "blue": 1}
_INK = {"red": 0.13, "green": 0.13, "blue": 0.13}
_BAND = {"red": 0.965, "green": 0.965, "blue": 0.965}
# Semantic colours, matching the house style on the working tab:
# blue = revenue coming in, red = money going out, green = what we keep.
_TONE = {"in": {"red": 0.067, "green": 0.333, "blue": 0.8},
         "out": {"red": 0.7, "green": 0.0, "blue": 0.0},
         "profit": {"red": 0.094, "green": 0.502, "blue": 0.22}}
_BORDER = {"style": "SOLID", "width": 1,
           "color": {"red": 0.6, "green": 0.6, "blue": 0.6}}
_THICK = {"style": "SOLID_MEDIUM", "width": 2,
          "color": {"red": 0.35, "green": 0.35, "blue": 0.35}}
# Each block gets its own accent so the eye can jump straight to a campaign.
_ACCENT = {
    "TOTAL": _HDR_BG,
    "B2B": {"red": 0.11, "green": 0.28, "blue": 0.53},
    "BOX": {"red": 0.08, "green": 0.40, "blue": 0.40},
    "Base": {"red": 0.55, "green": 0.40, "blue": 0.05},
}
_REPS_BG = {"red": 0.30, "green": 0.30, "blue": 0.30}
_FONT = "Calibri"


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
            "live": live, "last_rep": last_rep,
            "order": [h for _, h in weeks]}


def _cell(grid, row, col_letter_str):
    c = sum((ord(ch) - 64) * 26 ** i
            for i, ch in enumerate(reversed(col_letter_str)))
    r = grid[row - 1] if row - 1 < len(grid) else []
    return r[c - 1] if c - 1 < len(r) else ""


def _week_has_data(info, hdr) -> bool:
    """A week counts as run once its Total DD / payroll is set OR any rep row
    carries revenue. Keeps un-started columns out of the clean tab."""
    b = info["blocks"][hdr]
    g = info["grid"]
    for key in ("total_dd", "total_payroll"):
        if b.get(key) and _money(_cell(g, b[key], b["prof"])):
            return True
    for row in range(REP_FIRST, info["last_rep"] + 1):
        if _money(_cell(g, row, b["bro"])):
            return True
    return False


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
    # Every week that has ANY data — the whole year to date, not just the weeks
    # with a Revenue-by-Campaign block (that block only starts at WE 6/21, so
    # earlier weeks show the TOTAL box and the rep table with blank campaigns).
    # Un-started weeks are skipped so they don't push the live ones off-screen.
    order = [h for h in info["order"] if _week_has_data(info, h)]
    reps = active_reps(info, log=log)

    q = f"'{SRC_TAB}'!"
    rows: list[list] = []
    fmt: list[dict] = []

    def add(label, per_week=None, kind=None, bold=False, tone=None):
        r = [label]
        for hdr in order:
            r.append(per_week(info["blocks"][hdr]) if per_week else "")
        rows.append(r)
        fmt.append({"i": len(rows) - 1, "kind": kind, "bold": bold, "tone": tone})

    def ref(b, row):
        return f"={q}{b['prof']}{row}" if row else ""

    def margin(b, num_row, den_row):
        if not (num_row and den_row):
            return ""
        return (f"=IFERROR(IF({q}{b['prof']}{den_row}=0,\"\","
                f"{q}{b['prof']}{num_row}/{q}{b['prof']}{den_row}),\"\")")

    add("VANTURA \u2014 P&L 2026", kind="title", bold=True)
    add("")
    add("TOTAL", kind="section", bold=True)
    add("Revenue Brought In (no captainship)", lambda b: ref(b, b["total_dd"]),
        "money", tone="in")
    add("Captainship Bonus", lambda b: ref(b, b["captain"]), "money", tone="in")
    # A week with no Captain's Bonus line has no captain row at all \u2014 fall back
    # to the plain DD rather than blanking the whole row.
    add("Total DD (with captainship)",
        lambda b: ("" if not b["total_dd"] else
                   f"={q}{b['prof']}{b['total_dd']}+{q}{b['prof']}{b['captain']}"
                   if b["captain"] else f"={q}{b['prof']}{b['total_dd']}"),
        "money", bold=True, tone="in")
    add("Paid Out", lambda b: ref(b, b["total_payroll"]), "money", tone="out")
    add("Payroll Tax", lambda b: ref(b, b["total_tax"]), "money", tone="out")
    # The captain's bonus is revenue the office keeps — no rep is paid on it — so
    # it belongs in gross profit and in the margin denominator. The working tab's
    # TOTAL PNL deliberately excludes it, so we add it back here (Carlos, 2026-08-06).
    def _gross(b):
        if not b["total_pnl"]:
            return ""
        base = f"{q}{b['prof']}{b['total_pnl']}"
        return f"={base}+{q}{b['prof']}{b['captain']}" if b["captain"] else f"={base}"

    def _gross_margin(b):
        if not (b["total_pnl"] and b["total_dd"]):
            return ""
        num = f"{q}{b['prof']}{b['total_pnl']}"
        den = f"{q}{b['prof']}{b['total_dd']}"
        if b["captain"]:
            cap = f"{q}{b['prof']}{b['captain']}"
            num, den = f"({num}+{cap})", f"({den}+{cap})"
        return f'=IFERROR(IF({den}=0,"",{num}/{den}),"")'

    # Profit BEFORE the captain's bonus is added back — this is the figure
    # the Commission tab's TOTAL Profit/Loss shows, so Carlos can tie the two
    # together directly (Carlos, 2026-08-20).
    add("Total Gross Profit (no captainship)",
        lambda b: ref(b, b["total_pnl"]), "money", bold=True, tone="profit")
    add("Total Gross Profit (incl. captainship)", _gross, "money",
        bold=True, tone="profit")
    add("Profit Margin %", _gross_margin, "pct", bold=True, tone="profit")
    add("")

    for camp in CAMPAIGNS:
        add(camp, kind="section", bold=True)
        add("Revenue Brought In",
            lambda b, c=camp: ref(b, b[c] + 1 if b.get(c) else None),
            "money", tone="in")
        add("Paid Out",
            lambda b, c=camp: ref(b, b[c] + 2 if b.get(c) else None),
            "money", tone="out")
        add("Payroll Tax",
            lambda b, c=camp: ref(b, b[c] + 3 if b.get(c) else None),
            "money", tone="out")
        add("Profit",
            lambda b, c=camp: ref(b, b[c] + 4 if b.get(c) else None),
            "money", bold=True, tone="profit")
        add("Profit Margin %",
            lambda b, c=camp: margin(b, b[c] + 4 if b.get(c) else None,
                                     b[c] + 1 if b.get(c) else None),
            "pct", bold=True, tone="profit")
        add("")

    add("REVENUE BY REP \u2014 ACTIVE ONLY",
        kind="section", bold=True)
    for n, (rep_row, name) in enumerate(reps):
        rows.append([name] + [f"={q}{info['blocks'][h]['bro']}{rep_row}"
                              for h in order])
        fmt.append({"i": len(rows) - 1, "kind": "money", "bold": False,
                    "tone": "in", "band": n % 2 == 1})

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
    for f in fmt:
        r, kind, bold, tone = f["i"] + 1, f["kind"], f["bold"], f.get("tone")
        if kind in ("title", "section"):
            label = rows[f["i"]][0]
            bg = (_HDR_BG if kind == "title"
                  else _ACCENT.get(label.split()[0] if label else "", _REPS_BG))
            reqs.append({"repeatCell": {"range": rng(r, r + 1, 0, n_cols),
                "cell": {"userEnteredFormat": {
                    "backgroundColor": bg,
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {"bold": True, "fontSize": 12 if kind == "title" else 11,
                                   "fontFamily": _FONT, "foregroundColor": _WHITE}}},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                          "verticalAlignment,textFormat)"}})
        elif kind in ("money", "pct"):
            cell = {"numberFormat": _MONEY if kind == "money" else _PCT,
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {"bold": bold, "fontFamily": _FONT,
                                   "foregroundColor": _TONE.get(tone, _INK)}}
            if f.get("band"):
                cell["backgroundColor"] = _BAND
            reqs.append({"repeatCell": {"range": rng(r, r + 1, 1, n_cols),
                "cell": {"userEnteredFormat": cell},
                "fields": "userEnteredFormat(numberFormat,horizontalAlignment,"
                          "verticalAlignment,textFormat"
                          + (",backgroundColor" if f.get("band") else "") + ")"}})
            lbl = {"textFormat": {"bold": bold, "foregroundColor": _INK,
                                  "fontFamily": _FONT},
                   "horizontalAlignment": "CENTER",
                   "verticalAlignment": "MIDDLE"}
            if f.get("band"):
                lbl["backgroundColor"] = _BAND
            reqs.append({"repeatCell": {"range": rng(r, r + 1, 0, 1),
                "cell": {"userEnteredFormat": lbl},
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,"
                          "verticalAlignment"
                          + (",backgroundColor" if f.get("band") else "") + ")"}})
    # Boxed borders around each section, and a highlight on the newest week.
    for f in fmt:
        if f["kind"] == "section":
            r = f["i"] + 1
            reqs.append({"updateBorders": {"range": rng(r, r + 1, 0, n_cols),
                "top": _BORDER, "bottom": _BORDER}})
    reqs.append({"repeatCell": {
        "range": rng(1, n_rows + 1, n_cols - 1, n_cols),
        "cell": {"userEnteredFormat": {"borders": {
            "left": _BORDER, "right": _BORDER}}},
        "fields": "userEnteredFormat.borders"}})

    # No mergeCells across the title: column A is frozen and Sheets refuses to
    # merge frozen with non-frozen columns. The full-width band reads fine.
    reqs.append({"updateBorders": {"range": rng(0, 1, 0, n_cols),
                                   "bottom": _THICK}})
    reqs.append({"updateDimensionProperties": {"range": {
        "sheetId": sid, "dimension": "ROWS", "startIndex": 0,
        "endIndex": n_rows + 1}, "properties": {"pixelSize": 23},
        "fields": "pixelSize"}})
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
