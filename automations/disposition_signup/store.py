"""Where a disposition sign-up goes: the 'Disposition Signup' tab of the
AUTOMATION MASTER sheet, with a local-JSON fallback for building.

Mirrors tracker_onboarding.store — same sheet, same hardcoded id (never a
secret, so it cannot drift off the master workbook), same one-JSON-row-per-
office shape.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.disposition_signup.schema import DispositionRecord

MASTER_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
SIGNUP_TAB = "Disposition Signup"

_HEADER = ["office_key", "config_json", "owner", "cadence", "routes",
           "status", "submitted_at", "submitted_by"]


# gspread raises WorksheetNotFound for "no tab by that name" and APIError for
# everything else (429s, 403s, transient 5xx). Only the first means "create it".
try:                                     # gspread >= 5
    from gspread.exceptions import WorksheetNotFound as _WorksheetNotFound
except Exception:                        # noqa: BLE001
    class _WorksheetNotFound(Exception):
        pass


_LOCAL_FALLBACK = (Path(__file__).resolve().parents[2] / "output"
                   / "disposition_signup_submissions.json")

_CLIENT = None


def set_client(gspread_client) -> None:
    global _CLIENT
    _CLIENT = gspread_client


def get_client():
    """The injected gspread client (None in local-draft mode). Lets the form
    reuse one client to enqueue the mini_control job — that queue is a tab on
    this same sheet."""
    return _CLIENT


def _row_values(rec: DispositionRecord) -> list:
    return [rec.key, json.dumps(rec.to_json()), rec.owner,
            rec.cadence_label(), " | ".join(rec.routes()), rec.status,
            rec.submitted_at, rec.submitted_by]


def _ws():
    if _CLIENT is None:
        return None
    ss = _CLIENT.open_by_key(MASTER_SHEET_ID)
    try:
        return ss.worksheet(SIGNUP_TAB)
    except _WorksheetNotFound:              # a 429 is not a missing tab
        ws = ss.add_worksheet(title=SIGNUP_TAB, rows=200, cols=len(_HEADER))
        ws.append_row(_HEADER)
        return ws


def save(rec: DispositionRecord) -> str:
    row = _row_values(rec)
    ws = _ws()
    if ws is not None:
        if not ws.get_all_values():
            ws.append_row(_HEADER)
        ws.append_row(row)
        return "sheet"
    _LOCAL_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    data = []
    if _LOCAL_FALLBACK.exists():
        try:
            data = json.loads(_LOCAL_FALLBACK.read_text())
        except Exception:                            # noqa: BLE001
            data = []
    data.append(rec.to_json())
    _LOCAL_FALLBACK.write_text(json.dumps(data, indent=2))
    return "local"


def load_all() -> "List[dict]":
    ws = _ws()
    if ws is not None:
        out = []
        for r in ws.get_all_records():
            raw = r.get("config_json") or ""
            if raw:
                try:
                    out.append(json.loads(raw))
                except Exception:                    # noqa: BLE001
                    continue
        return out
    if _LOCAL_FALLBACK.exists():
        try:
            return json.loads(_LOCAL_FALLBACK.read_text())
        except Exception:                            # noqa: BLE001
            return []
    return []


def update(rec: DispositionRecord) -> str:
    """Overwrite the (last) existing row for rec.key in place — Megan
    confirming a pending request, or an owner re-submitting their own. Falls
    back to append when the key has no row yet."""
    ws = _ws()
    if ws is not None:
        keys = ws.col_values(1)
        row_i = None
        for i, k in enumerate(keys[1:], start=2):   # skip header
            if k == rec.key:
                row_i = i                            # last match wins
        if row_i is None:
            return save(rec)
        end_col = chr(ord("A") + len(_HEADER) - 1)
        ws.update("A%d:%s%d" % (row_i, end_col, row_i), [_row_values(rec)])
        return "sheet"
    data = []
    if _LOCAL_FALLBACK.exists():
        try:
            data = json.loads(_LOCAL_FALLBACK.read_text())
        except Exception:                            # noqa: BLE001
            data = []
    data = [d for d in data if d.get("key") != rec.key]
    data.append(rec.to_json())
    _LOCAL_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    _LOCAL_FALLBACK.write_text(json.dumps(data, indent=2))
    return "local"


def load_one(key: str) -> "Optional[dict]":
    """The (last) submission for this office key, or None."""
    hit = None
    for d in load_all():
        if d.get("key") == key:
            hit = d
    return hit


def record_from_json(d: dict) -> DispositionRecord:
    d = {k: v for k, v in d.items() if not k.startswith("_")}
    # Tolerate a row written by an older/newer form: an unknown column must not
    # crash the confirm view or the apply, it just isn't carried.
    known = set(DispositionRecord.__dataclass_fields__)
    return DispositionRecord(**{k: v for k, v in d.items() if k in known})


def existing_registry(exclude_key: "Optional[str]" = None) -> "Dict[str, object]":
    """{'keys': [...], 'groups': {imessage group (lower): key}} across the LIVE
    gap_alerts offices + every already-submitted row (minus exclude_key).
    Best-effort — a failed import contributes nothing."""
    keys: List[str] = []
    groups: Dict[str, str] = {}
    try:
        from automations.gap_alerts import config as C
        for o in C.OFFICES:
            k = o.get("key", "")
            if not k or k == exclude_key:
                continue
            keys.append(k)
            grp = (o.get("group") or "").strip().lower()
            if grp:
                groups.setdefault(grp, k)
    except Exception:                                # noqa: BLE001
        pass
    for d in load_all():
        k = d.get("key")
        if not k or k == exclude_key:
            continue
        if k not in keys:
            keys.append(k)
        grp = (d.get("imessage_group") or "").strip().lower()
        if grp:
            groups.setdefault(grp, k)
    return {"keys": keys, "groups": groups}
