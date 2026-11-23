"""Pure merge logic: SaraPlus Activities rows -> what to write on the tab.

No network here, so it is all unit-tested (test_sheet.py).

Rules:
  * One row per Order ID. An Order ID already on the tab is never re-added
    and never overwritten (Raf's NOTES sit beside it).
  * New rows go on TOP (row 2), newest first -- the way Raf laid it out.
  * Date -> 'm/d/yy' in Date, '3:02 PM' in TIME. SaraPlus's export writes
    '11/21/26 15:02 tt' (a broken .NET format string: 24h clock plus a
    literal 'tt'); the grid shows '11/21/26 03:02 PM'. Both parse.
  * Raf's own rows with a blank TIME get it filled from their Date (he typed
    TIME by hand: "it just has to translate it into normal timing").
    Only BLANK TIME cells are touched.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

_DATE_RE = re.compile(
    r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm]|tt)?\s*$")


def parse_when(text: str) -> Optional[dt.datetime]:
    """'11/21/26 15:02 tt' / '11/21/26 03:02 PM' / '11/21/2026 3:02 PM'."""
    m = _DATE_RE.match(text or "")
    if not m:
        return None
    mo, d, y, h, mi, ampm = m.groups()
    y = int(y)
    if y < 100:
        y += 2000
    h = int(h)
    if ampm and ampm.lower() in ("am", "pm"):
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ampm.lower() == "pm" else 0)
    try:
        return dt.datetime(y, int(mo), int(d), h, int(mi))
    except ValueError:
        return None


def fmt_date(t: dt.datetime) -> str:
    return "%d/%d/%02d" % (t.month, t.day, t.year % 100)


def fmt_time(t: dt.datetime) -> str:
    """'3:02 PM' -- no %-I (Windows has no '-' flag)."""
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def header_index(header_row: List[str]) -> Dict[str, int]:
    """normalized label -> 0-based column."""
    out = {}
    for i, h in enumerate(header_row):
        k = _norm(h)
        if k and k not in out:
            out[k] = i
    return out


def row_when(row: List[str], date_col: int, time_col: int) -> Optional[dt.datetime]:
    """A tab row's moment: Raf's '11/21/26 15:02 tt' or ours '11/23/26' + '2:34 PM'."""
    d = row[date_col] if date_col < len(row) else ""
    t = row[time_col] if time_col < len(row) else ""
    return parse_when(d) or parse_when("%s %s" % (d, t))


def placements(existing: List[List[str]], new_rows: List[List[str]],
               date_col: int, time_col: int) -> List[Tuple[int, List[str]]]:
    """[(sheet_row_1based, row)] to insert ONE AT A TIME, in this order, so
    every new row lands in its time slot (newest first) instead of all on
    top. SaraPlus shows some records late (a 1:46 PM order appearing after a
    2:33 PM one, 2026-11-23); top-only inserts left those out of order."""
    ts = [row_when(r, date_col, time_col) or dt.datetime.min for r in existing[1:]]
    out = []
    for row in sorted(new_rows, key=lambda r: row_when(r, date_col, time_col)
                      or dt.datetime.min):
        t = row_when(row, date_col, time_col) or dt.datetime.min
        j = next((i for i, x in enumerate(ts) if x < t), len(ts))
        ts.insert(j, t)
        out.append((j + 2, row))
    return out


def records_from_table(headers: List[str], rows: List[List[str]]) -> List[Dict[str, str]]:
    """Export/grid rows -> dicts keyed by the export's own header text.
    Drops rows without an Order ID (pager, footer, 'no records')."""
    idx = header_index(headers)
    key = idx.get(_norm("Order ID"))
    if key is None:
        raise ValueError("no 'Order ID' column in the Activities export -- "
                         "headers were: %s" % ", ".join(h for h in headers if h))
    out = []
    for r in rows:
        if key >= len(r) or not (r[key] or "").strip():
            continue
        rec = {}
        for h in headers:
            i = idx.get(_norm(h))
            if i is not None and h:
                rec[h.strip()] = (r[i] if i < len(r) else "").strip()
        out.append(rec)
    return out


def plan(existing: List[List[str]], records: List[Dict[str, str]],
         column_source: Dict[str, str], time_header: str, key_header: str
         ) -> Tuple[List[List[str]], List[Tuple[int, int, str]]]:
    """(new_rows_top_down, time_fills).

    new_rows_top_down: full-width rows to insert at row 2, newest first.
    time_fills: (sheet_row_1based, col_1based, value) for blank TIME cells on
    rows ALREADY on the tab. Rows are counted BEFORE the insert; the caller
    shifts them by len(new_rows).
    """
    if not existing:
        raise ValueError("the tab has no header row")
    hdr = header_index(existing[0])
    missing = [h for h in list(column_source) + [time_header, key_header]
               if _norm(h) not in hdr]
    if missing:
        raise ValueError("tab row 1 is missing %s -- found: %s"
                         % (", ".join(repr(m) for m in missing),
                            ", ".join(c for c in existing[0] if c)))
    key_col = hdr[_norm(key_header)]
    date_col = hdr[_norm("Date")]
    time_col = hdr[_norm(time_header)]
    width = max(len(existing[0]), max(hdr.values()) + 1)

    have = set()
    for r in existing[1:]:
        if key_col < len(r) and r[key_col].strip():
            have.add(r[key_col].strip().upper())

    rec_norm = [{_norm(k): v for k, v in rec.items()} for rec in records]
    fresh = []
    seen = set()
    for rec in rec_norm:
        oid = (rec.get(_norm("Order ID")) or "").strip()
        if not oid or oid.upper() in have or oid.upper() in seen:
            continue
        seen.add(oid.upper())
        fresh.append(rec)

    def when(rec):
        return parse_when(rec.get(_norm("Date"), "")) or dt.datetime.min

    fresh.sort(key=when, reverse=True)

    new_rows = []
    for rec in fresh:
        row = [""] * width
        for tab_label, src_label in column_source.items():
            row[hdr[_norm(tab_label)]] = rec.get(_norm(src_label), "")
        t = parse_when(rec.get(_norm("Date"), ""))
        if t:
            row[date_col] = fmt_date(t)
            row[time_col] = fmt_time(t)
        new_rows.append(row)

    fills = []
    for i, r in enumerate(existing[1:], start=2):
        cur = r[time_col].strip() if time_col < len(r) else ""
        if cur:
            continue
        t = parse_when(r[date_col] if date_col < len(r) else "")
        if t:
            fills.append((i, time_col + 1, fmt_time(t)))
    return new_rows, fills
