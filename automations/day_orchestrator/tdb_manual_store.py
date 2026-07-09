"""Live cross-machine store for Texas de Brazil manual inputs — the dinner date
and any BACKFILL leaders (promotions / car-ride the board auto-detect missed).

Lives in a 'TdB Manual Inputs' tab of the shared library Sheet so BOTH sides use
one source of truth with the shared Google login:
  - the Hub card WRITES it (Maud/Megan type dinner date + backfill leaders), and
  - the mini's run READS it (tdb_sync_inputs merges it into the local JSON the
    report reads) — so a leader typed on the laptop reaches the mini instantly,
    with no code editing and no git push. This is what stops the recurring
    "edit the code cell -> wipe the delivery layer" cycle: leaders are DATA now.

Row per competition period ('YYYY-MM'). Promotions text = one 'Promoter > New
Leader' per line (matches load_manual_inputs); Car Ride = one name per line.
"""
from __future__ import annotations

import datetime

from automations.recruiting_report import fill as _fill

SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # shared library Sheet
TAB = "TdB Manual Inputs"
HEADERS = ["Period", "Promotions", "Car Ride", "Dinner Day", "Dinner Time",
           "Updated By", "Updated At"]
_LAST_COL = chr(ord("A") + len(HEADERS) - 1)   # 'G'


def _ws():
    import gspread as _gs
    sh = _fill.open_by_key(SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=TAB, rows=100, cols=len(HEADERS))
        ws.update([HEADERS], f"A1:{_LAST_COL}1")
        return ws


def get(period: str) -> dict:
    """Return {'promotions','car_ride','dinner_day','dinner_time','exists'} for a
    period. exists=False (all blank) when there's no row yet."""
    blank = {"promotions": "", "car_ride": "", "dinner_day": "", "dinner_time": "",
             "exists": False}
    try:
        rows = _ws().get_all_records()
    except Exception:
        return blank
    for r in rows:
        if str(r.get("Period", "")).strip() == period:
            return {"promotions": str(r.get("Promotions", "") or ""),
                    "car_ride": str(r.get("Car Ride", "") or ""),
                    "dinner_day": str(r.get("Dinner Day", "") or ""),
                    "dinner_time": str(r.get("Dinner Time", "") or ""),
                    "exists": True}
    return blank


def all() -> dict:
    """Every period row keyed by period — one Sheet read (for the Hub card)."""
    try:
        rows = _ws().get_all_records()
    except Exception:
        return {}
    out = {}
    for r in rows:
        p = str(r.get("Period", "")).strip()
        if p:
            out[p] = {"promotions": str(r.get("Promotions", "") or ""),
                      "car_ride": str(r.get("Car Ride", "") or ""),
                      "dinner_day": str(r.get("Dinner Day", "") or ""),
                      "dinner_time": str(r.get("Dinner Time", "") or "")}
    return out


def set(period: str, *, promotions=None, car_ride=None, dinner_day=None,
        dinner_time=None, by: str = "hub") -> None:
    """Upsert a period row. Only fields passed (not None) are changed; the rest
    keep their current value."""
    ws = _ws()
    rows = ws.get_all_records()
    target, cur = None, {}
    for i, r in enumerate(rows, start=2):     # row 1 = headers
        if str(r.get("Period", "")).strip() == period:
            target, cur = i, r
            break

    def pick(new, key):
        return new if new is not None else str(cur.get(key, "") or "")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    vals = [period, pick(promotions, "Promotions"), pick(car_ride, "Car Ride"),
            pick(dinner_day, "Dinner Day"), pick(dinner_time, "Dinner Time"), by, stamp]
    if target:
        ws.update([vals], f"A{target}:{_LAST_COL}{target}", value_input_option="RAW")
    else:
        ws.append_row(vals, value_input_option="RAW")
