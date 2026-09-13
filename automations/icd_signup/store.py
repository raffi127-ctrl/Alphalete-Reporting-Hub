"""Where a Lucy Eco sign-up goes: the 'ICD Signup' tab of the relay workbook.

THE SAME WORKBOOK THE RELAY ALREADY USES, on purpose. Everything about an ICD
office already lives in 'Lucy Access App' -- their keys, their relayed numbers,
their channel approvals -- and a sign-up that landed somewhere else would be
the one fact about an office you had to go looking for.

Mirrors disposition_signup.store: one row per office, a local-JSON fallback so
the form can be built and tested without touching the sheet, and an append that
never overwrites somebody else's row.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.icd_signup.schema import IcdSignup, STATUS_PENDING, stamp

SIGNUP_TAB = "ICD Signup"
_HEADER = ["office_key", "owner", "office_label", "contact", "platform",
           "timezone", "day_start", "day_end", "saturday", "sat_start",
           "sat_end", "ov_name", "knocks_cadence", "wanted_channels",
           "status", "submitted_at", "note"]

_LOCAL_FALLBACK = (Path(__file__).resolve().parents[2] / "output"
                   / "icd_signup_submissions.json")

try:                                     # gspread >= 5
    from gspread.exceptions import WorksheetNotFound as _WorksheetNotFound
except Exception:                        # noqa: BLE001
    class _WorksheetNotFound(Exception):
        pass


def _book():
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(P.RELAY_SPREADSHEET_ID)


def _tab(book=None):
    book = book or _book()
    try:
        return book.worksheet(SIGNUP_TAB)
    except _WorksheetNotFound:
        tab = book.add_worksheet(title=SIGNUP_TAB, rows=200,
                                 cols=len(_HEADER))
        tab.append_row(_HEADER)
        return tab


def _local() -> List[Dict]:
    try:
        return json.loads(_LOCAL_FALLBACK.read_text())
    except (OSError, ValueError):
        return []


def _save_local(rows: List[Dict]) -> None:
    _LOCAL_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    _LOCAL_FALLBACK.write_text(json.dumps(rows, indent=2))


def office_key_for(owner: str, taken=()) -> str:
    """First name, lowercased, with a number only if it has to disambiguate."""
    import re
    first = (owner or "").strip().split()[0] if (owner or "").strip() else ""
    base = re.sub(r"[^a-z]", "", first.lower()) or "office"
    if base not in taken:
        return base
    n = 2
    while "%s%d" % (base, n) in taken:
        n += 1
    return "%s%d" % (base, n)


def all_signups(book=None) -> List[IcdSignup]:
    try:
        rows = _tab(book).get_all_records()
    except Exception:  # noqa: BLE001 — no sheet access: fall back to local
        rows = _local()
    return [IcdSignup.from_row(r) for r in rows if (r.get("owner") or "").strip()]


def pending(book=None) -> List[IcdSignup]:
    return [s for s in all_signups(book) if s.status == STATUS_PENDING]


def get(office_key: str, book=None) -> Optional[IcdSignup]:
    key = (office_key or "").strip().lower()
    return next((s for s in all_signups(book) if s.office_key == key), None)


def submit(rec: IcdSignup, book=None) -> IcdSignup:
    """Append one sign-up as PENDING. Never overwrites an existing row.

    The office key is assigned HERE rather than by the form, because it has to
    be unique across everyone who has ever signed up and the form cannot see
    the others.
    """
    existing = all_signups(book)
    taken = {s.office_key for s in existing if s.office_key}
    rec = rec._replace(
        office_key=rec.office_key or office_key_for(rec.owner, taken),
        status=STATUS_PENDING,
        submitted_at=rec.submitted_at or stamp(),
    )
    row = rec.as_row()
    ordered = [row.get(h, "") for h in _HEADER]
    try:
        _tab(book).append_row(["TRUE" if v is True else
                               "FALSE" if v is False else v for v in ordered])
    except Exception:  # noqa: BLE001 — the owner's submission must not be lost
        rows = _local()
        rows.append(row)
        _save_local(rows)
    return rec


def set_status(office_key: str, status: str, note: str = "", book=None) -> bool:
    key = (office_key or "").strip().lower()
    try:
        tab = _tab(book)
        values = tab.get_all_values()
    except Exception:  # noqa: BLE001
        return False
    head = values[0] if values else _HEADER
    try:
        c_key = head.index("office_key")
        c_status = head.index("status")
        c_note = head.index("note")
    except ValueError:
        return False
    for i, row in enumerate(values[1:], start=2):
        if len(row) > c_key and (row[c_key] or "").strip().lower() == key:
            tab.update_cell(i, c_status + 1, status)
            if note:
                tab.update_cell(i, c_note + 1, note)
            return True
    return False
