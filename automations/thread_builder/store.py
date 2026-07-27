"""Where a Thread Builder edit goes: a 'Thread Plans' tab in the same AUTOMATION
MASTER sheet the onboarding form uses — the shared config store the Lucy reports
sync from each morning. Local-JSON fallback so the editor works while building
(no creds → nothing touches the live sheet; sandbox-first).

UNLIKE office_onboarding.store (append-only log of enrollments), this is an
UPSERT store: a plan is the office's CURRENT thread, so re-saving REPLACES its
row. One row per (campaign, office_key).

Flow:  admin editor  --save-->  this tab  --thread_builder.sync-->
       automations/shared/thread_plans.json  --resolver-->  the runners.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

# Same master sheet as onboarding — one config workbook.
from automations.office_onboarding.store import MASTER_SHEET_ID  # noqa: F401

PLANS_TAB = "Thread Plans"
_HEADER = ["campaign", "office_key", "ordered_ids", "updated_at", "updated_by"]

_LOCAL_FALLBACK = (Path(__file__).resolve().parents[2] / "output"
                   / "thread_plans_store.json")

_CLIENT = None


def set_client(gspread_client) -> None:
    global _CLIENT
    _CLIENT = gspread_client


def _ws():
    """The 'Thread Plans' worksheet, created (with header) if missing. None when
    no client is injected — callers fall back to local JSON."""
    if _CLIENT is None:
        return None
    ss = _CLIENT.open_by_key(MASTER_SHEET_ID)
    try:
        return ss.worksheet(PLANS_TAB)
    except Exception:
        ws = ss.add_worksheet(title=PLANS_TAB, rows=200, cols=len(_HEADER))
        ws.append_row(_HEADER)
        return ws


# --- local fallback helpers -------------------------------------------------
def _local_read() -> dict:
    if _LOCAL_FALLBACK.exists():
        try:
            return json.loads(_LOCAL_FALLBACK.read_text())
        except Exception:
            return {}
    return {}


def _local_write(data: dict) -> None:
    _LOCAL_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    _LOCAL_FALLBACK.write_text(json.dumps(data, indent=2, sort_keys=True))


def _key(campaign: str, office_key: str) -> str:
    return "{}::{}".format(campaign, office_key)


# --- public API -------------------------------------------------------------
def save_plan(campaign: str, office_key: str, ordered_ids: List[str],
              *, updated_by: str = "", updated_at: str = "") -> str:
    """Upsert one office's plan. Returns 'sheet' or 'local'."""
    ids_json = json.dumps(list(ordered_ids))
    ws = _ws()
    if ws is not None:
        rows = ws.get_all_records()
        for i, r in enumerate(rows):          # 0-based data row -> sheet row i+2
            if (str(r.get("campaign")) == campaign
                    and str(r.get("office_key")) == office_key):
                ws.update("A{0}:E{0}".format(i + 2),
                          [[campaign, office_key, ids_json, updated_at, updated_by]])
                return "sheet"
        ws.append_row([campaign, office_key, ids_json, updated_at, updated_by])
        return "sheet"
    data = _local_read()
    data[_key(campaign, office_key)] = {"campaign": campaign,
                                        "office_key": office_key,
                                        "ordered_ids": list(ordered_ids),
                                        "updated_at": updated_at,
                                        "updated_by": updated_by}
    _local_write(data)
    return "local"


def clear_plan(campaign: str, office_key: str) -> bool:
    """Remove one office's plan (reverts it to the runner default). True if a row
    was present."""
    ws = _ws()
    if ws is not None:
        rows = ws.get_all_records()
        for i, r in enumerate(rows):
            if (str(r.get("campaign")) == campaign
                    and str(r.get("office_key")) == office_key):
                ws.delete_rows(i + 2)
                return True
        return False
    data = _local_read()
    if data.pop(_key(campaign, office_key), None) is None:
        return False
    _local_write(data)
    return True


def load_all() -> Dict[str, Dict[str, List[str]]]:
    """{campaign: {office_key: [ordered ids]}} — every saved plan. This is what
    thread_builder.sync materializes into thread_plans.json."""
    out: Dict[str, Dict[str, List[str]]] = {}

    def _add(campaign, office_key, ids):
        if not campaign or not office_key or not isinstance(ids, list):
            return
        out.setdefault(campaign, {})[office_key] = [str(x) for x in ids]

    ws = _ws()
    if ws is not None:
        for r in ws.get_all_records():
            raw = r.get("ordered_ids") or "[]"
            try:
                ids = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                continue
            _add(str(r.get("campaign")), str(r.get("office_key")), ids)
        return out
    for rec in _local_read().values():
        _add(rec.get("campaign"), rec.get("office_key"), rec.get("ordered_ids"))
    return out


def plan_for(campaign: str, office_key: str) -> Optional[List[str]]:
    return load_all().get(campaign, {}).get(office_key)
