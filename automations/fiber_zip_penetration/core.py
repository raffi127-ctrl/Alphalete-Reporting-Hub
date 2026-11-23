"""Pure logic: parse the by-zip crosstab, find the Line Up tab + columns, plan
the cell writes and the color rules. No network here (tested in test_core).

Tableau column  ->  Raf's column on the Line Up (row 2 headers):
  Assigned Fiber Lead Penetration -> Current Penetration Rate        (colored)
  Total Sales                     -> Total Current Sales
  Sales Needed                    -> Sales Needed to be at 2% Over 17 wks
  Expected Fiber Sales (copy)     -> Expected Fiber Sales over 17 wks for 2%
  Days Since Last Sale            -> Days since last Sale
  (none: sheet formula)           -> Sales needed to be 1%+ Over 17 weeks
                                     = Fiber doors * 1% / 17  (Raf's own formula)

Colors on Current Penetration Rate (Raf's legend): red 0.99% or less,
yellow 1% - 1.49%, green 1.5% +.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- Tableau crosstab -----------------------------------------------------
T_OWNER = "Account_Owner_Name__c"
T_ZIP = "Customer Zip"
T_LEADS = "Lead Count"
T_PCT = "Assigned Fiber Lead Penetration"
T_SALES = "Total Sales"
T_NEEDED = "Sales Needed"
T_EXPECTED = "Expected Fiber Sales (copy)"
T_DAYS = "Days Since Last Sale"

# --- sheet headers (lower-cased, spaces collapsed) -------------------------
H_ZIP = "zip code"
H_DOORS = "fiber doors"
H_PCT = "current penetration rate"
H_NEED1 = "sales needed to be 1%+ over 17 weeks"
# sheet header -> crosstab field key
FIELDS = {
    H_PCT: "pct",
    "total current sales": "sales",
    "sales needed to be at 2% over 17 wks": "needed",
    "expected fiber sales over 17 wks for 2%": "expected",
    "days since last sale": "days",
}

RED, YELLOW, GREEN = ({"red": 0.957, "green": 0.8, "blue": 0.8},
                      {"red": 1.0, "green": 0.949, "blue": 0.8},
                      {"red": 0.851, "green": 0.918, "blue": 0.827})

LINEUP = re.compile(r"^\s*line\s*up\s*(?:we\s*)?(\d{1,2})\.(\d{1,2})\s*$", re.I)


def norm(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def zip5(z) -> str:
    s = re.sub(r"\D", "", str(z or ""))
    return s.zfill(5) if 0 < len(s) <= 5 else s


def _num(s: str) -> Optional[float]:
    s = (s or "").replace(",", "").replace("Days", "").replace("Day", "").strip()
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100 if pct else v


def decode(path: Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return raw.decode("latin-1", "replace")


def parse_zips(text: str) -> Dict[str, Dict[str, dict]]:
    """{owner: {zip: {pct, sales, needed, expected, days, leads}}}.

    A zip that shows up twice for one owner (Raf's 75024: one 'TN' row with 1
    lead next to the real 'TX' row) keeps the row with more leads."""
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    head = [norm(h) for h in rows[0]]

    def col(label: str) -> int:
        return head.index(norm(label))

    ix = {k: col(v) for k, v in (("owner", T_OWNER), ("zip", T_ZIP), ("leads", T_LEADS),
                                 ("pct", T_PCT), ("sales", T_SALES), ("needed", T_NEEDED),
                                 ("expected", T_EXPECTED), ("days", T_DAYS))}
    out: Dict[str, Dict[str, dict]] = {}
    for r in rows[1:]:
        if len(r) <= max(ix.values()):
            continue
        owner, z = r[ix["owner"]].strip(), zip5(r[ix["zip"]])
        if not owner or owner.lower() == "total" or not z.isdigit():
            continue
        rec = {k: _num(r[i]) for k, i in ix.items() if k not in ("owner", "zip")}
        cur = out.setdefault(owner, {}).get(z)
        if cur is None or (rec["leads"] or 0) > (cur["leads"] or 0):
            out[owner][z] = rec
    return out


# --- the tab ------------------------------------------------------------------
def week_sunday(today: dt.date) -> dt.date:
    """Tabs are named by the week's Sunday (Mon..Sun week)."""
    return today + dt.timedelta(days=(6 - today.weekday()) % 7)


def tab_date(title: str, today: dt.date) -> Optional[dt.date]:
    m = LINEUP.match(title or "")
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            c = dt.date(y, mo, d)
        except ValueError:
            continue
        if best is None or abs((c - today).days) < abs((best - today).days):
            best = c
    return best


def target_tabs(titles: List[str], today: dt.date) -> List[str]:
    """This week's Line Up, plus next week's if somebody already made it.
    No current one yet -> the newest Line Up (so the numbers never go stale)."""
    dated = [(tab_date(t, today), t) for t in titles]
    dated = [(d, t) for d, t in dated if d]
    if not dated:
        return []
    cur = [t for d, t in sorted(dated) if d >= week_sunday(today)]
    return cur or [max(dated)[1]]


def layout(values: List[List[str]]) -> Optional[dict]:
    """Header row = the one carrying 'Current Penetration Rate'. Zip column =
    the 'Zip Code' header nearest to its left (the Line Up has two)."""
    for r, row in enumerate(values[:10]):
        h = [norm(x) for x in row]
        if H_PCT not in h:
            continue
        pct_c = h.index(H_PCT)
        zips = [c for c, x in enumerate(h) if x == H_ZIP and c < pct_c]
        if not zips:
            return None
        cols = {f: h.index(lab) for lab, f in FIELDS.items() if lab in h}
        return {"header_row": r, "zip": zips[-1], "cols": cols,
                "doors": h.index(H_DOORS) if H_DOORS in h else None,
                "need1": h.index(H_NEED1) if H_NEED1 in h else None}
    return None


def a1(row0: int, col0: int) -> str:
    s, c = "", col0 + 1
    while c:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return "%s%d" % (s, row0 + 1)


def plan(values: List[List[str]], formulas: List[List[str]], lay: dict,
         data: Dict[str, dict]) -> Tuple[List[dict], dict]:
    """Cell writes for every zip row + a summary. Only the mapped columns are
    touched; a zip Tableau doesn't have gets its cells blanked (no stale
    numbers), never another column."""
    writes, matched, missing = [], [], []
    last = lay["header_row"]
    for r in range(lay["header_row"] + 1, len(values)):
        row = values[r]
        z = zip5(row[lay["zip"]] if lay["zip"] < len(row) else "")
        if not z.isdigit():
            continue
        last = r
        rec = data.get(z)
        (matched if rec else missing).append(z)
        for f, c in lay["cols"].items():
            v = rec.get(f) if rec else None
            if v is None:
                cell = ""
            elif f == "pct":
                cell = "%.2f%%" % (v * 100)
            else:
                cell = int(v) if float(v).is_integer() else v
            writes.append({"range": a1(r, c), "values": [[cell]]})
        if lay["need1"] is not None and lay["doors"] is not None:
            f = formulas[r][lay["need1"]] if r < len(formulas) and lay["need1"] < len(formulas[r]) else ""
            if not str(f).strip():
                writes.append({"range": a1(r, lay["need1"]),
                               "values": [["=%s*1%%/17" % a1(r, lay["doors"])]]})
    extra = sorted(set(data) - set(matched))
    return writes, {"matched": matched, "missing": missing, "not_on_sheet": extra,
                    "first_row": lay["header_row"] + 1, "last_row": last}


def cf_requests(sheet_id: int, lay: dict, last_row0: int, existing: List[dict]) -> List[dict]:
    """Red/yellow/green on Current Penetration Rate. Drops any older rule on
    that same column first, so the daily run never stacks duplicates."""
    c = lay["cols"].get("pct")
    if c is None:
        return []
    r1, r2 = lay["header_row"] + 1, last_row0 + 1
    reqs = []
    for i in reversed(range(len(existing))):
        rngs = existing[i].get("ranges", [])
        if any(g.get("startColumnIndex") == c and g.get("endColumnIndex") == c + 1 for g in rngs):
            reqs.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": i}})
    rng = {"sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
           "startColumnIndex": c, "endColumnIndex": c + 1}
    top = a1(r1, c)
    rules = (('=AND(ISNUMBER(%s),%s<0.01)' % (top, top), RED),
             ('=AND(ISNUMBER(%s),%s>=0.01,%s<0.015)' % (top, top, top), YELLOW),
             ('=AND(ISNUMBER(%s),%s>=0.015)' % (top, top), GREEN))
    for i, (formula, color) in enumerate(rules):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": [rng],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                          "values": [{"userEnteredValue": formula}]},
                            "format": {"backgroundColor": color}}}}})
    return reqs
