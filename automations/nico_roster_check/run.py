"""Nico's 'Active Reps' tab — Daily Update roster ✕ weekly payroll (Carlos 2026-11-04).

Carlos: "I want to be able to see which active reps brought in revenue, so I
can see who's not getting paid. I also want to be able to see who the people
are that are supposed to be getting a check for the first time."

What it does, daily:
  1. Reads the Vantura Master's Daily Update (columns by HEADER via du_layout —
     never by position) and keeps the VERIZON-campaign people whose Status is
     Active / Showed to Classroom / Orientation Scheduled.
  2. Reads every "WE m.d" tab on Nico's book ("Nico Verizon Payroll") — the
     summary block col A..E down to TOTAL — newest week by (month, day).
  3. Rebuilds the "Active Reps" tab on Nico's book as plain values:
       section 1: the roster, each person's revenue + pay THIS week and a flag
                  (FIRST CHECK / REVENUE-NOT PAID / NOT PAID / paid),
       section 2: people EARNING this week who are NOT Active-VERIZON on the
                  Daily Update (mistagged campaign, Not Active, or missing) —
                  the reverse data-quality check.

Names: Daily Update spellings and payroll spellings drift ("Nico Murrugarra"
vs "Nicolas Murrugarra", "Jose Manuel Rojas" vs "Jose Rojas"), so matching is
exact-normalized first, then same last name + first-name prefix (>=3 chars).
Ambiguous fuzzy hits are treated as no match rather than guessed.

Dry-run by default; --write applies.

  python -m automations.nico_roster_check.run            # preview
  python -m automations.nico_roster_check.run --write    # rebuild the tab
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report.du_layout import resolve as du_resolve

MASTER_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master
NICO_ID = "1LxusYWQnSccBYyzJ_B7SJMWCT0zvYB4mJYFHL5uV8K0"      # Nico Verizon Payroll
DU_TAB = "Daily Update"
OUT_TAB = "Active Reps"

# Daily Update statuses that count as the live pipeline, in display order.
STATUS_ORDER = ["Active", "Showed to Classroom", "Orientation Scheduled"]

HDR_BG = {"red": 0.5216, "green": 0.1255, "blue": 0.0471}     # book's dark red


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _money(s) -> float:
    t = str(s or "").replace("$", "").replace(",", "").strip()
    if not t:
        return 0.0
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("()-")
    try:
        v = float(t)
    except ValueError:
        return 0.0
    return -v if neg else v


def _week_key(tab_title: str) -> Optional[Tuple[int, int, int]]:
    """'WE 11.7' -> sortable (year, month, day). Months 1-6 read as next year
    so a January tab outranks November once the book crosses the new year."""
    m = re.fullmatch(r"WE (\d{1,2})\.(\d{1,2})", tab_title.strip())
    if not m:
        return None
    mo, da = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12 and 1 <= da <= 31):
        return None
    return (2027 if mo <= 6 else 2026, mo, da)


def _read_du_verizon() -> List[dict]:
    from automations.recruiting_report import fill as _fill
    ws = _fill.open_by_key(MASTER_ID).worksheet(DU_TAB)
    vals = ws.get_all_values()
    lay = du_resolve(vals[0])

    def cell(row, key):
        i = lay.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    out = []
    for r in vals[1:]:
        camp = cell(r, "campaign").upper()
        name = cell(r, "name")
        if not name or not camp.startswith("VERIZON"):
            continue
        out.append({
            "name": name,
            "status": cell(r, "status"),
            "secondary": cell(r, "secondary"),
        })
    return out


def _read_weeks(book) -> Dict[str, Dict[str, dict]]:
    """{tab title: {normalized rep: {'name','rev','paid'}}} for every WE tab."""
    weeks: Dict[str, Dict[str, dict]] = {}
    for ws in book.worksheets():
        if _week_key(ws.title) is None:
            continue
        reps: Dict[str, dict] = {}
        for row in ws.get_values("A4:E200"):
            name = (row[0] if row else "").strip()
            if not name:
                continue
            if name.upper() == "TOTAL":
                break
            reps[_norm(name)] = {
                "name": name,
                "rev": _money(row[1] if len(row) > 1 else ""),
                "paid": _money(row[2] if len(row) > 2 else ""),
            }
        weeks[ws.title] = reps
    return weeks


def _match(norm_name: str, pool: Dict[str, dict]) -> Optional[str]:
    """Key in `pool` this person matches, or None. Exact first, then same
    last name + first-token prefix; two fuzzy candidates = no match."""
    if norm_name in pool:
        return norm_name
    toks = norm_name.split()
    if len(toks) < 2:
        return None
    first, last = toks[0], toks[-1]
    hits = []
    for key in pool:
        kt = key.split()
        if len(kt) < 2 or kt[-1] != last:
            continue
        kf = kt[0]
        if kf == first or (len(first) >= 3 and kf.startswith(first)) or \
                (len(kf) >= 3 and first.startswith(kf)):
            hits.append(key)
    return hits[0] if len(hits) == 1 else None


def build_rows() -> Tuple[List[List[str]], str]:
    """(grid rows for the tab, newest week title)."""
    from automations.recruiting_report import fill as _fill
    book = _fill.open_by_key(NICO_ID)

    roster = _read_du_verizon()
    weeks = _read_weeks(book)
    if not weeks:
        raise SystemExit("no WE tabs found on Nico's book")
    newest = max(weeks, key=lambda t: _week_key(t))
    cur = weeks[newest]
    _log(f"Daily Update VERIZON rows: {len(roster)}; weeks: "
         f"{sorted(weeks, key=_week_key)}; newest {newest} ({len(cur)} reps)")

    # Weeks before the newest, for the first-check test.
    prior_paid: Dict[str, float] = {}
    for t, reps in weeks.items():
        if t == newest:
            continue
        for k, v in reps.items():
            prior_paid[k] = prior_paid.get(k, 0.0) + v["paid"]

    def first_check(book_key: str) -> bool:
        return cur.get(book_key, {}).get("paid", 0) > 0 and \
            prior_paid.get(book_key, 0.0) <= 0

    now = dt.datetime.now().strftime("%-m/%-d/%Y %-I:%M %p")
    rows: List[List[str]] = [
        ["ACTIVE REPS — Daily Update ✕ payroll", "", "", "", ""],
        [f"Week shown: {newest}", "", "", f"Auto-updated daily · last: {now}", ""],
        ["", "", "", "", ""],
        ["Rep (Daily Update)", "Status", "Revenue this week",
         "Paid this week", "Flag"],
    ]

    live = [p for p in roster if p["status"] in STATUS_ORDER]
    matched_keys = set()
    sec1 = []
    for p in live:
        bk = _match(_norm(p["name"]), cur)
        rev = cur[bk]["rev"] if bk else 0.0
        paid = cur[bk]["paid"] if bk else 0.0
        if bk:
            matched_keys.add(bk)
        if paid > 0 and bk and first_check(bk):
            flag = "FIRST CHECK"
        elif paid > 0:
            flag = "paid"
        elif rev > 0:
            flag = "REVENUE, NOT PAID"
        elif p["status"] == "Active":
            flag = "NOT PAID — no revenue"
        else:
            flag = "no check yet"
        sec1.append((p, rev, paid, flag))

    sec1.sort(key=lambda x: (STATUS_ORDER.index(x[0]["status"]),
                             -x[2], -x[1], _norm(x[0]["name"])))
    for p, rev, paid, flag in sec1:
        rows.append([p["name"], p["status"],
                     f"${rev:,.2f}", f"${paid:,.2f}", flag])

    # Section 2 — earning this week but not on the live VERIZON roster.
    du_all = {_norm(p["name"]): p for p in roster}
    rows += [["", "", "", "", ""],
             ["EARNING THIS WEEK, NOT ACTIVE ON DAILY UPDATE", "", "", "", ""],
             ["Rep (payroll)", "Daily Update says", "Revenue this week",
              "Paid this week", ""]]
    sec2 = []
    for k, v in cur.items():
        if k in matched_keys or (v["rev"] <= 0 and v["paid"] <= 0):
            continue
        dk = _match(k, du_all)
        du_says = du_all[dk]["status"] if dk else "not on Daily Update (Verizon)"
        note = "FIRST CHECK" if first_check(k) else ""
        sec2.append([v["name"], du_says,
                     f"${v['rev']:,.2f}", f"${v['paid']:,.2f}", note])
    sec2.sort(key=lambda r: -_money(r[3]))
    rows += sec2 if sec2 else [["(none)", "", "", "", ""]]
    return rows, newest


def write_tab(rows: List[List[str]]) -> None:
    from automations.recruiting_report import fill as _fill
    book = _fill.open_by_key(NICO_ID)
    try:
        ws = book.worksheet(OUT_TAB)
    except Exception:
        ws = book.add_worksheet(OUT_TAB, rows=120, cols=6, index=2)
    ws.clear()
    ws.update(rows, "A1", raw=True)

    hdr_rows = [i for i, r in enumerate(rows)
                if r[0] in ("Rep (Daily Update)", "Rep (payroll)")]
    band_rows = [0] + [i for i, r in enumerate(rows)
                       if r[0].startswith("EARNING THIS WEEK")]
    sid = ws.id
    reqs = [
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 250}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": 5},
            "properties": {"pixelSize": 165}, "fields": "pixelSize"}},
    ]
    for r in band_rows:
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + 1,
                      "startColumnIndex": 0, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {
                "backgroundColor": HDR_BG,
                "textFormat": {"bold": True, "fontFamily": "Calibri",
                               "foregroundColor": {"red": 1, "green": 1,
                                                   "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    for r in hdr_rows:
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + 1,
                      "startColumnIndex": 0, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": .92, "green": .92, "blue": .92},
                "textFormat": {"bold": True, "fontFamily": "Calibri"}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
    # Flag colors: red for the not-paid flags, green for FIRST CHECK.
    for i, r in enumerate(rows):
        if r[4] == "FIRST CHECK":
            color = {"red": 0.0, "green": 0.45, "blue": 0.0}
        elif r[4] in ("REVENUE, NOT PAID", "NOT PAID — no revenue"):
            color = {"red": 0.8, "green": 0.0, "blue": 0.0}
        else:
            continue
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": i, "endRowIndex": i + 1,
                      "startColumnIndex": 4, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontFamily": "Calibri",
                               "foregroundColor": color}}},
            "fields": "userEnteredFormat.textFormat"}})
    book.batch_update({"requests": reqs})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="rebuild the Active Reps tab (default: preview only)")
    args = ap.parse_args(argv)

    rows, newest = build_rows()
    for r in rows:
        _log(" | ".join(c for c in r))
    if not args.write:
        _log("dry-run — nothing written (use --write)")
        return 0
    write_tab(rows)
    _log(f"wrote '{OUT_TAB}' ({len(rows)} rows, week {newest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
