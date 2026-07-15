"""Write detected customer responses into the source sheet's feedback columns.
Non-destructive to unrelated rows: only the matched customer's feedback cell is
written."""
from __future__ import annotations

import datetime as dt

from automations.recruiting_report import fill as _rfill
from automations.rc_autoread import run as _rc

from . import pull as _src
from .pull import norm_phone
from .detect import all_responses


def _col_letter(i: int) -> str:
    return chr(ord("A") + i)


def write_responses_to_source(dry_run: bool, days: int, logfn=print) -> int:
    """For every customer who has replied to the inquiry, write the conversation
    into the feedback column of their most-recent matching row in the source
    sheet. Handles the per-row column shift; matches by phone."""
    token = _rc.get_access_token(logfn=lambda *a: None)
    logfn("Scanning RingCentral for replies...")
    resp = all_responses(token, max(days, 7), logfn)
    logfn(f"{len(resp)} customer response(s) detected")

    src = _rfill.open_by_key(_src.SRC_ID)
    written, placed = 0, set()
    for tab, fb_header in _src.SOURCE_FEEDBACK_TABS:
        ws = src.worksheet(tab)
        v = ws.get_all_values()
        if not v:
            continue
        h = v[0]
        phi = _src._hidx(h, "Customer Phone")
        fbi = _src._hidx(h, fb_header)
        sdi = _src._hidx(h, "Status Date")
        if phi is None or fbi is None:
            logfn(f"  {tab}: missing phone/feedback column — skipped")
            continue
        best = {}   # phone -> (status_date, sheet_row, feedback_col_idx)
        for j, r in enumerate(v[1:]):
            pa = next((c for c in (phi, phi - 1, phi + 1)
                       if 0 <= c < len(r) and _src._PHONE.match(r[c] or "")), None)
            if pa is None:
                continue
            ph = norm_phone(r[pa])
            if ph not in resp:
                continue
            off = pa - phi
            d = (_src.parse_date(r[sdi + off], dt.date.today())
                 if sdi is not None and 0 <= sdi + off < len(r) else None) or dt.date.min
            row = j + 2
            if ph not in best or (d, row) > (best[ph][0], best[ph][1]):
                best[ph] = (d, row, fbi + off)
        for ph, (d, row, col) in best.items():
            cell = f"{_col_letter(col)}{row}"
            placed.add(ph)
            if dry_run:
                logfn(f"  would write {tab}!{cell}  ({ph})")
            else:
                ws.update(range_name=cell, values=[[resp[ph][0]]])
            written += 1
        if best:
            logfn(f"  {tab}: {len(best)} response(s)")
    missing = set(resp) - placed
    if missing:
        logfn(f"  NOTE: {len(missing)} responded phone(s) had no matching source "
              f"row: {sorted(missing)[:5]}")
    return written
