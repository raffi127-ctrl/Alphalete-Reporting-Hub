"""Daily 1st rd Recruiter % — daily Hub report (Eve).

Per recruiter, an 8-row scorecard block repeated down the 'Daily 1st rd
Recruiter %' tab, alphabetized. Each block has two cards side by side:
  • LEFT  = current week, filled Mon -> today (days after today stay blank)
  • RIGHT = last week, full Mon-Fri
Rows per block: name banner / day headers + dates / then four metric rows:
  1st Rounds Booked        <- AppStream 'Interviews Booked'
  First Rounds Scheduled   <- AppStream 'Total First Interviews'
  First Rounds Showed      <- AppStream 'First Interviews Showed Up'
  1st Round Retention %    = Showed / Scheduled   (color-coded, Raf)

Source: AppStream p=701 admin breakdown (Raf's office) — already per-day, so
we read Mon-Fri straight across (7-array index 1..5; index 0 = Sunday).
Recruiter universe = anyone with any Booked/Scheduled/Showed this week OR last
week; last-week-only recruiters still appear (this week shows 0s).

  python -m automations.recruiter_retention.daily --dry-run
  python -m automations.recruiter_retention.daily --limit 2     # preview first N
  python -m automations.recruiter_retention.daily               # live, all
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.recruiter_retention import run as wk

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# The shared pull captures Booked too (the weekly report ignores it).
wk.SECTIONS.setdefault("interviews booked", "B")

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "Daily 1st rd Recruiter %"

BLOCK_H = 8                      # content rows per recruiter block
SPACER = 1                       # blank white row between blocks
STRIDE = BLOCK_H + SPACER        # rows from one block's top to the next
NAME_ROW, DATE_ROW = 1, 4        # 1-indexed rows WITHIN a block
MET_ROW = {"B": 5, "Sch": 6, "SU": 7}
PCT_ROW = 8
# 1-indexed columns. Left card (current week) / right card (last week).
L_NAME, L_DAYS, L_TOTAL = 3, [4, 5, 6, 7, 8], 9        # C / D-H / I
R_NAME, R_DAYS, R_TOTAL = 13, [14, 15, 16, 17, 18], 19  # M / N-R / S
PCT_LABEL = "1st Round Retention %"   # col C marker used to count blocks

CF_GREEN, CF_GREY, CF_RED = wk.CF_GREEN, wk.CF_GREY, wk.CF_RED
HEADER_BG = {"red": 0.71, "green": 0.69, "blue": 0.90}  # day+date header band (periwinkle)


def _col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _ord(n: int) -> str:
    """1 -> '1st', 24 -> '24th' — date headers read as dates, not counts."""
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _mon_fri(arr):
    """7-array (Sun..Sat) -> [Mon, Tue, Wed, Thu, Fri] (indices 1..5)."""
    a = arr or [0] * 7
    return [a[i] if i < len(a) else 0 for i in range(1, 6)]


def _has_any(rec: dict) -> bool:
    return any(sum(rec.get(k, [0] * 7)) for k in ("B", "Sch", "SU"))


def _weeks(today: dt.date):
    this_mon = today - dt.timedelta(days=today.weekday())   # Monday=0
    cur_sun = this_mon - dt.timedelta(days=1)               # Sun-Sat week start
    last_sun = cur_sun - dt.timedelta(days=7)
    return this_mon, cur_sun, last_sun


def _frac(su, sch):
    # No scheduled = no data -> show 0% but UNcolored. Writing it as the text
    # "0%" (not the number 0.0) means the numeric color rule skips it. A real
    # 0% (scheduled but none showed) returns 0.0 (a number) -> flagged red.
    return round(su / sch, 4) if sch else "0%"


def _block_count(ws) -> int:
    """How many recruiter blocks already exist (count of the % label in col C)."""
    colC = ws.col_values(L_NAME)
    return sum(1 for v in colC if v.strip() == PCT_LABEL)


def _card_rows(rec_cur, rec_last, this_mon, today):
    """Return the per-card filled values for one recruiter.

    Each card -> dict with metric -> {'days': [5 vals or ''], 'total': val}.
    Current-week days after `today` are '' (blank); past/today filled.
    """
    def card(rec, monday, future_aware):
        out = {}
        dates = [monday + dt.timedelta(days=i) for i in range(5)]
        bydays = {m: _mon_fri(rec.get(m, [0] * 7)) for m in ("B", "Sch", "SU")}
        # which day columns are fillable
        fill = [(not future_aware) or (d <= today) for d in dates]
        for m in ("B", "Sch", "SU"):
            days = [bydays[m][i] if fill[i] else "" for i in range(5)]
            total = sum(bydays[m][i] for i in range(5) if fill[i])
            out[m] = {"days": days, "total": total}
        # retention % per day + total
        pct_days = []
        for i in range(5):
            if not fill[i]:
                pct_days.append("")
            else:
                pct_days.append(_frac(bydays["SU"][i], bydays["Sch"][i]))
        sch_t = sum(bydays["Sch"][i] for i in range(5) if fill[i])
        su_t = sum(bydays["SU"][i] for i in range(5) if fill[i])
        out["pct"] = {"days": pct_days, "total": _frac(su_t, sch_t)}
        out["dates"] = [_ord(d.day) for d in dates]
        return out

    cur = card(rec_cur, this_mon, future_aware=True)
    last = card(rec_last, this_mon - dt.timedelta(days=7), future_aware=False)
    return cur, last


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recruiter_retention.daily")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pull + compute + print; no sheet writes.")
    ap.add_argument("--date", default=None, help="Override today (YYYY-MM-DD).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Fill only the first N recruiters (preview).")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    this_mon, cur_sun, last_sun = _weeks(today)
    print(f"=== Daily 1st rd Recruiter % — {today} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    print(f"  this week Mon-Fri: {this_mon} .. {this_mon + dt.timedelta(days=4)} "
          f"(fill Mon->today={today})")
    print(f"  AppStream weeks (Sun): current={cur_sun}  last={last_sun}")

    data = wk.pull_as_weeks([cur_sun, last_sun], verbose=True)
    cur_w, last_w = data.get(cur_sun, {}), data.get(last_sun, {})

    names = sorted(
        {n for n, d in cur_w.items() if _has_any(d)}
        | {n for n, d in last_w.items() if _has_any(d)},
        key=str.lower,
    )
    if args.limit:
        names = names[: args.limit]
    print(f"\n  {len(names)} recruiter(s): {names}")

    cards = []
    for n in names:
        cur, last = _card_rows(cur_w.get(n, {}), last_w.get(n, {}), this_mon, today)
        cards.append((n, cur, last))
        if args.dry_run:
            c, l = cur, last
            print(f"\n  {n}")
            print(f"    THIS  Booked {c['B']['days']} = {c['B']['total']} | "
                  f"Sch {c['Sch']['days']} = {c['Sch']['total']} | "
                  f"SU {c['SU']['days']} = {c['SU']['total']} | "
                  f"% {c['pct']['days']} = {c['pct']['total']}")
            print(f"    LAST  Booked {l['B']['days']} = {l['B']['total']} | "
                  f"Sch {l['Sch']['days']} = {l['Sch']['total']} | "
                  f"SU {l['SU']['days']} = {l['SU']['total']} | "
                  f"% {l['pct']['days']} = {l['pct']['total']}")

    if args.dry_run:
        print("\n(dry-run — no sheet writes)")
        return 0

    _write(cards, this_mon, today)
    print(f"\n=== done ===")
    return 0


def _zero_card(this_mon, today):
    """A zeroed card (counts 0, % '0%') — for recycled/hidden recruiters."""
    def card(monday, future_aware):
        dates = [monday + dt.timedelta(days=i) for i in range(5)]
        fill = [(not future_aware) or (d <= today) for d in dates]
        out = {m: {"days": [0 if fill[i] else "" for i in range(5)], "total": 0}
               for m in ("B", "Sch", "SU")}
        out["pct"] = {"days": ["0%" if fill[i] else "" for i in range(5)], "total": "0%"}
        out["dates"] = [_ord(d.day) for d in dates]
        return out
    return card(this_mon, True), card(this_mon - dt.timedelta(days=7), False)


GOAL_COLS = {1: "A", 2: "B", 11: "K", 12: "L"}   # manual goal columns to preserve
TEMPLATE_NAME = "RECRUITER NAME"

# Low-performer chart (right of the data): last week's recruiters at <=50%
# retention, with a streak count of consecutive weeks on the list.
CHART_NAME_C, CHART_PCT_C, CHART_CNT_C = 21, 22, 23   # cols U / V / W
CHART_ROW0, CHART_MAX = 4, 60                          # first list row / clear extent


def _chart_state(ws):
    """Existing chart contents -> {name: weeks_count}, plus the last-counted
    reference week (kept as an invisible note on U1 so daily re-runs within a
    week don't re-increment)."""
    counts = {}
    for row in ws.get(f"U{CHART_ROW0}:W{CHART_MAX}"):
        if row and row[0].strip():
            c = str(row[2]).strip() if len(row) >= 3 else ""
            counts[row[0].strip()] = int(c) if c.isdigit() else 0
    marker = None
    try:
        meta = ws.spreadsheet.fetch_sheet_metadata({
            "ranges": [f"'{TAB}'!U1"],
            "fields": "sheets(data(rowData(values(note))))"})
        note = meta["sheets"][0]["data"][0]["rowData"][0]["values"][0].get("note", "")
        if "counted_week=" in note:
            marker = note.split("counted_week=")[-1].strip()
    except Exception:
        pass
    return counts, marker


def _write(active_cards, this_mon, today):
    sh = wk.open_by_key(SHEET_ID) if hasattr(wk, "open_by_key") else None
    if sh is None:
        from automations.recruiting_report.fill import open_by_key
        sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB)
    sid = ws.id

    # ---- snapshot existing blocks: recruiter names + their manual goals ----
    # (goals live in cols A/B left + K/L right, on the metric rows 5-8).
    existing = _block_count(ws)
    tops = [1 + i * STRIDE for i in range(existing)]
    end = (tops[-1] + BLOCK_H) if tops else 0
    grid = ws.get(f"A1:S{end}") if end else []

    def cell(r, c):                                  # 1-indexed
        return grid[r-1][c-1] if (r-1 < len(grid) and c-1 < len(grid[r-1])) else ""

    existing_names, goals_by_name = [], {}
    for T in tops:
        nm = cell(T, L_NAME).strip()
        existing_names.append(nm)
        if nm and nm.upper() != TEMPLATE_NAME:
            goals_by_name[nm] = {c: [cell(T + MET_ROW["B"] - 1 + j, c) for j in range(4)]
                                 for c in GOAL_COLS}

    # ---- active (top, alphabetized, visible) + recycled (bottom, hidden) ----
    active_set = {name for name, _, _ in active_cards}
    recycled = sorted([nm for nm in existing_names
                       if nm and nm.upper() != TEMPLATE_NAME and nm not in active_set],
                      key=str.lower)
    zc, zl = _zero_card(this_mon, today)
    all_cards = list(active_cards) + [(nm, zc, zl) for nm in recycled]
    n_active, n_total = len(active_cards), len(all_cards)
    print(f"  existing: {existing} | active: {n_active} | "
          f"recycled(hidden): {len(recycled)} | total: {n_total}")

    # ---- low-performer chart: last week <=50% retention, streak count ----
    last_mon = this_mon - dt.timedelta(days=7)
    prev_counts, marker = _chart_state(ws)
    new_week = (marker != last_mon.isoformat())
    listed = sorted(
        [(name, last["pct"]["total"]) for name, _, last in active_cards
         # Only a week with LOGGED data counts: the recruiter must have had
         # interviews scheduled that week (Sch > 0). A no-data week yields a
         # text "0%" (not a number) for pct, so it's excluded — it never lands
         # on the list or bumps the streak count. Guard on Sch>0 explicitly so
         # this can't regress if _frac ever changes. (Megan 2026-06-04)
         if isinstance(last["Sch"]["total"], (int, float))
         and last["Sch"]["total"] > 0
         and isinstance(last["pct"]["total"], (int, float))
         and last["pct"]["total"] <= 0.5],
        key=lambda x: x[1], reverse=True)              # greatest -> least
    chart_rows = []
    for name, pct in listed:
        prev = prev_counts.get(name, 0)
        cnt = (prev + 1 if prev else 1) if new_week else (prev or 1)
        chart_rows.append((name, pct, cnt))
    print(f"  low-performer chart: {len(chart_rows)} recruiter(s) <=50% — "
          f"{'NEW week (+1)' if new_week else 'same week (counts held)'}")

    # ---- 1) replicate the template block for any positions beyond existing ----
    reqs = [{"copyPaste": {
        "source": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": BLOCK_H,
                   "startColumnIndex": 0, "endColumnIndex": 19},
        "destination": {"sheetId": sid, "startRowIndex": k * STRIDE,
                        "endRowIndex": k * STRIDE + BLOCK_H,
                        "startColumnIndex": 0, "endColumnIndex": 19},
        "pasteType": "PASTE_NORMAL"}} for k in range(max(existing, 1), n_total)]
    if reqs:
        sh.batch_update({"requests": reqs})

    # ---- 2) fill values (+ restore goals by name) ----
    data = []

    def put(a1, vals):
        data.append({"range": f"'{TAB}'!{a1}", "values": [vals]})

    for k, (name, cur, last) in enumerate(all_cards):
        top = 1 + k * STRIDE
        put(f"{_col(L_NAME)}{top}", [name])
        put(f"{_col(R_NAME)}{top}", [name])
        drow = top + DATE_ROW - 1
        put(f"{_col(L_DAYS[0])}{drow}:{_col(L_DAYS[-1])}{drow}", cur["dates"])
        put(f"{_col(R_DAYS[0])}{drow}:{_col(R_DAYS[-1])}{drow}", last["dates"])
        for m in ("B", "Sch", "SU"):
            r = top + MET_ROW[m] - 1
            put(f"{_col(L_DAYS[0])}{r}:{_col(L_TOTAL)}{r}",
                cur[m]["days"] + [cur[m]["total"]])
            put(f"{_col(R_DAYS[0])}{r}:{_col(R_TOTAL)}{r}",
                last[m]["days"] + [last[m]["total"]])
        pr = top + PCT_ROW - 1
        put(f"{_col(L_DAYS[0])}{pr}:{_col(L_TOTAL)}{pr}",
            cur["pct"]["days"] + [cur["pct"]["total"]])
        put(f"{_col(R_DAYS[0])}{pr}:{_col(R_TOTAL)}{pr}",
            last["pct"]["days"] + [last["pct"]["total"]])
        gg = goals_by_name.get(name)               # carry goals with the person
        if gg:
            for c, vals in gg.items():
                for j, val in enumerate(vals):
                    if val != "":
                        put(f"{_col(c)}{top + MET_ROW['B'] - 1 + j}", [val])

    # Blank any stale leftover blocks beyond what we placed (defensive; keeps
    # goal columns A/B/K/L untouched).
    for k in range(n_total, existing):
        top = 1 + k * STRIDE
        put(f"{_col(L_NAME)}{top}", [""])
        put(f"{_col(R_NAME)}{top}", [""])
        for rr in range(DATE_ROW, PCT_ROW + 1):
            r = top + rr - 1
            put(f"{_col(L_DAYS[0])}{r}:{_col(L_TOTAL)}{r}", [""] * 6)
            put(f"{_col(R_DAYS[0])}{r}:{_col(R_TOTAL)}{r}", [""] * 6)

    # low-performer chart — clear then fill (U=name, V=%, W=weeks-on-list)
    data.append({"range": f"'{TAB}'!U{CHART_ROW0}:W{CHART_MAX}",
                 "values": [["", "", ""]] * (CHART_MAX - CHART_ROW0 + 1)})
    if chart_rows:
        data.append({"range":
            f"'{TAB}'!U{CHART_ROW0}:W{CHART_ROW0 + len(chart_rows) - 1}",
            "values": [[nm, pc, ct] for nm, pc, ct in chart_rows]})

    sh.values_batch_update({"valueInputOption": "RAW", "data": data})

    # ---- 3) % number format (all blocks) + hide recycled / unhide active ----
    fmt_reqs, pct_ranges = [], []
    for k in range(n_total):
        pr0 = k * STRIDE + (PCT_ROW - 1)
        rng = {"sheetId": sid, "startRowIndex": pr0, "endRowIndex": pr0 + 1,
               "startColumnIndex": L_DAYS[0] - 1, "endColumnIndex": R_TOTAL}
        fmt_reqs.append({"repeatCell": {"range": rng,
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
            "fields": "userEnteredFormat.numberFormat"}})
        if k < n_active:
            pct_ranges.append(rng)
        # Tint the day-label + date rows (rows 3-4) so they read as a header
        # band, distinct from the numbers below.
        r0 = k * STRIDE + 2
        for c0, c1 in ((L_DAYS[0] - 1, L_TOTAL), (R_DAYS[0] - 1, R_TOTAL)):
            fmt_reqs.append({"repeatCell": {"range": {"sheetId": sid,
                "startRowIndex": r0, "endRowIndex": r0 + 2,
                "startColumnIndex": c0, "endColumnIndex": c1},
                "cell": {"userEnteredFormat": {"backgroundColor": HEADER_BG}},
                "fields": "userEnteredFormat.backgroundColor"}})
    if n_active:
        fmt_reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": 0, "endIndex": n_active * STRIDE},
            "properties": {"hiddenByUser": False}, "fields": "hiddenByUser"}})
    hide_to = max(n_total, existing) * STRIDE
    if hide_to > n_active * STRIDE:
        fmt_reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": n_active * STRIDE, "endIndex": hide_to},
            "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    # chart: % format on V, + stamp the reference-week marker note on U1
    chart_pct_rng = {"sheetId": sid, "startRowIndex": CHART_ROW0 - 1,
                     "endRowIndex": CHART_MAX, "startColumnIndex": CHART_PCT_C - 1,
                     "endColumnIndex": CHART_PCT_C}
    fmt_reqs.append({"repeatCell": {"range": chart_pct_rng,
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
        "fields": "userEnteredFormat.numberFormat"}})
    fmt_reqs.append({"updateCells": {
        "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": CHART_NAME_C - 1, "endColumnIndex": CHART_NAME_C},
        "rows": [{"values": [{"note": f"counted_week={last_mon.isoformat()}"}]}],
        "fields": "note"}})
    pct_ranges.append(chart_pct_rng)          # color the chart % same as the sheet
    if fmt_reqs:
        sh.batch_update({"requests": fmt_reqs})

    # ---- 4) CF color rules over the ACTIVE % rows only ----
    meta = sh.fetch_sheet_metadata()
    count = next((len(s.get("conditionalFormats", [])) for s in meta["sheets"]
                  if s["properties"]["sheetId"] == sid), 0)
    cf = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
          for i in range(count - 1, -1, -1)]
    if pct_ranges:
        def rule(idx, cond, val, color):
            return {"addConditionalFormatRule": {"index": idx, "rule": {
                "ranges": pct_ranges,
                "booleanRule": {"condition": {"type": cond,
                    "values": [{"userEnteredValue": str(val)}]},
                    "format": {"backgroundColor": color}}}}}
        cf += [rule(0, "NUMBER_GREATER_THAN_EQ", 0.5, CF_GREEN),
               rule(1, "NUMBER_GREATER_THAN_EQ", 0.45, CF_GREY),
               rule(2, "NUMBER_LESS", 0.45, CF_RED)]
    if cf:
        sh.batch_update({"requests": cf})


if __name__ == "__main__":
    sys.exit(main())
