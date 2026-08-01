"""Cross-machine store for Texas de Brazil's AUTO-DETECTED leaders.

The report detects Break-a-Leader promotions and Best Car Ride Leader off the
sales board and accumulates them, for the month, in a LOCAL json
(~/recruiting-report/output/texas_de_brazil_leaders_state.json). That file is
per-machine, so each machine only knows what it happened to see: the mini had
Zoria's promotion and Marchetti's car-ride, the laptop did not, and the same
board rendered from the laptop silently paid out 25 fewer points (2026-07-31).
Reports are supposed to run from ANY machine, so the detections have to live
somewhere both sides can see.

Same shape as [tdb_manual_store] — a tab in the shared library Sheet, one row
per competition period, merged into the run machine's local json by
tdb_sync_inputs before (and after) each run.

ONLY the accumulated detections are shared. The `baseline` (each rep's
Leadership Status at first sighting) stays machine-local ON PURPOSE: it's the
"before" picture a promotion is detected against, and merging two machines'
baselines could invent a promotion that never happened.

Merging is UNION-ONLY — a machine can add a leader, never remove one. Use
EXCLUDE_NEW_LEADERS in the report to drop a bad detection.
"""
from __future__ import annotations

import datetime

from automations.recruiting_report import fill as _fill

SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # shared library Sheet
TAB = "TdB Leaders State"
HEADERS = ["Period", "New Leaders", "Car Ride", "Updated By", "Updated At"]
_LAST_COL = chr(ord("A") + len(HEADERS) - 1)   # 'E'


def _ws():
    import gspread as _gs
    sh = _fill.open_by_key(SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=TAB, rows=100, cols=len(HEADERS))
        ws.update([HEADERS], f"A1:{_LAST_COL}1")
        return ws


def _parse_pairs(text: str) -> list[list[str]]:
    """'Promoter > New Leader' per line -> [[promoter, new_leader], ...]."""
    out = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ">" in line:
            a, b = line.split(">", 1)
            out.append([a.strip(), b.strip()])
        else:
            out.append(["", line])
    return out


def _fmt_pairs(pairs) -> str:
    return "\n".join(f"{(p[0] or '').strip()} > {(p[1] or '').strip()}".strip(" >")
                     if (p[0] or "").strip() else str(p[1]).strip()
                     for p in pairs)


def _union_pairs(*groups) -> list[list[str]]:
    """Union promotion pairs, keyed on the NEW LEADER (first sighting wins) —
    matches how the report itself de-dups detections."""
    seen, out = set(), []
    for g in groups:
        for p in g or []:
            p = [str(p[0] or "").strip(), str(p[1] or "").strip()] if len(p) > 1 else ["", str(p[0]).strip()]
            k = p[1].lower()
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(p)
    return out


def _union_names(*groups) -> list[str]:
    seen, out = set(), []
    for g in groups:
        for n in g or []:
            n = str(n).strip()
            if not n or n.lower() in seen:
                continue
            seen.add(n.lower())
            out.append(n)
    return out


def get(period: str) -> dict:
    """The shared detections for a period. Missing/unreachable -> empty lists."""
    blank = {"new_leaders": [], "car_ride": [], "exists": False}
    try:
        rows = _ws().get_all_records()
    except Exception:
        return blank
    for r in rows:
        if str(r.get("Period", "")).strip() == period:
            return {"new_leaders": _parse_pairs(r.get("New Leaders", "")),
                    "car_ride": [x.strip() for x in
                                 str(r.get("Car Ride", "") or "").splitlines() if x.strip()],
                    "exists": True}
    return blank


def merge(period: str, new_leaders=None, car_ride=None, by: str = "sync") -> dict:
    """Union the caller's detections into the period row and return the result.
    Never removes anything. Best-effort: on any Sheet trouble the caller's own
    lists come back unchanged so a run is never blocked."""
    try:
        cur = get(period)
    except Exception:
        return {"new_leaders": list(new_leaders or []), "car_ride": list(car_ride or []),
                "ok": False}
    merged_p = _union_pairs(cur["new_leaders"], new_leaders)
    merged_c = _union_names(cur["car_ride"], car_ride)
    changed = (merged_p != cur["new_leaders"]) or (merged_c != cur["car_ride"])
    if changed:
        try:
            ws = _ws()
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            vals = [period, _fmt_pairs(merged_p), "\n".join(merged_c), by, stamp]
            target = None
            for i, r in enumerate(ws.get_all_records(), start=2):
                if str(r.get("Period", "")).strip() == period:
                    target = i
                    break
            if target:
                ws.update([vals], f"A{target}:{_LAST_COL}{target}", value_input_option="RAW")
            else:
                ws.append_row(vals, value_input_option="RAW")
        except Exception:
            return {"new_leaders": merged_p, "car_ride": merged_c, "ok": False}
    return {"new_leaders": merged_p, "car_ride": merged_c, "ok": True, "changed": changed}
