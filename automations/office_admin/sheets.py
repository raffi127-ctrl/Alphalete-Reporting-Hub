"""The two tabs: 'Office Admins' (logins) and 'Admin Requests' (button presses).

Columns are found by header text, never by index. Both tabs are created with
headers on first use and never cleared. The hosted page injects its own
gspread client (set_client); on a Lucy the repo's normal client is used.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Dict, List, Optional

from automations.office_admin import config as C

_CLIENT = None


def set_client(gc) -> None:
    global _CLIENT
    _CLIENT = gc


def _retry(fn, *a, **kw):
    """Sheets 429/5xx retry. Its own (not recruiting_report.fill's) so the
    hosted page imports nothing but gspread."""
    import time
    for i in range(5):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code not in (429, 500, 502, 503) or i == 4:
                raise
            time.sleep(2 ** i * 3)


def _book(sheet_id: str = ""):
    sid = C.sheet_id(sheet_id)
    if _CLIENT is not None:
        return _retry(_CLIENT.open_by_key, sid)
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(sid)


def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip()


def open_tab(title: str, headers: List[str], sheet_id: str = ""):
    ss = _book(sheet_id)
    for w in ss.worksheets():
        if _norm(w.title).lower() == title.lower():
            return w
    ws = _retry(ss.add_worksheet, title=title, rows=200, cols=len(headers))
    _retry(ws.update, [headers], "A1")
    return ws


def records(values: List[List[str]]) -> List[Dict[str, str]]:
    """Header row + rows -> [{header: value, '_row': n}] (1-based rows)."""
    if not values:
        return []
    hdr = [_norm(h) for h in values[0]]
    out = []
    for i, r in enumerate(values[1:], start=2):
        d = {h: (str(r[k]).strip() if k < len(r) else "") for k, h in enumerate(hdr) if h}
        d["_row"] = i
        out.append(d)
    return out


def col_letter(n: int) -> str:
    """1 -> A, 27 -> AA."""
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _set_cells(ws, row: int, updates: Dict[str, str]) -> None:
    hdr = [_norm(h) for h in _retry(ws.row_values, 1)]
    data = []
    for h, v in updates.items():
        if h not in hdr:
            continue
        a1 = "%s%d" % (col_letter(hdr.index(h) + 1), row)
        data.append({"range": a1, "values": [[v]]})
    if data:
        _retry(ws.batch_update, data, value_input_option="RAW")


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------ admins tab --

def admins_tab(sheet_id: str = ""):
    return open_tab(C.ADMINS_TAB, C.ADMINS_HEADERS, sheet_id)


def read_admins(ws) -> List[Dict[str, str]]:
    return records(_retry(ws.get_all_values))


def append_admin(ws, row: Dict[str, str]) -> None:
    _retry(ws.append_row, [row.get(h, "") for h in C.ADMINS_HEADERS],
           value_input_option="RAW")


def set_admin_cells(ws, row: int, updates: Dict[str, str]) -> None:
    _set_cells(ws, row, updates)


# ---------------------------------------------------------- requests tab --

def requests_tab(sheet_id: str = ""):
    return open_tab(C.REQUESTS_TAB, C.REQUESTS_HEADERS, sheet_id)


def read_requests(ws) -> List[Dict[str, str]]:
    return records(_retry(ws.get_all_values))


def add_request(ws, *, username: str, office_key: str, action: str,
                details: Optional[dict] = None) -> str:
    if action not in C.ACTIONS:
        raise ValueError("unknown action %r" % action)
    rid = uuid.uuid4().hex[:12]
    row = {"Request ID": rid, "Requested At": now_str(), "Username": username,
           "Office Key": office_key, "Action": action,
           "Details": json.dumps(details or {}), "Status": C.QUEUED}
    _retry(ws.append_row, [row.get(h, "") for h in C.REQUESTS_HEADERS],
           value_input_option="RAW")
    return rid


def update_request(ws, row: int, **fields) -> None:
    """update_request(ws, 5, Status='done', Result='...')."""
    m = {k.replace("_", " "): v for k, v in fields.items()}
    m.setdefault("Updated At", now_str())
    _set_cells(ws, row, m)


def loads(s: str) -> dict:
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}
