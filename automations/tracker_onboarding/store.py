"""Where a tracker-onboarding submission goes: the 'Tracker Onboarding' tab of
the AUTOMATION MASTER sheet, with a local-JSON fallback for building. Mirrors
office_onboarding.store; the sheet id is hardcoded (never a secret) so it can't
drift off the master workbook.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.tracker_onboarding.schema import TrackerRecord

MASTER_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
ONBOARDING_TAB = "Tracker Onboarding"

_HEADER = ["office_key", "config_json", "channel", "n_trackers",
           "submitted_at", "submitted_by"]

_LOCAL_FALLBACK = (Path(__file__).resolve().parents[2] / "output"
                   / "tracker_onboarding_submissions.json")

_CLIENT = None


def set_client(gspread_client) -> None:
    global _CLIENT
    _CLIENT = gspread_client


def get_client():
    """The injected gspread client (None if unset). Lets the form reuse the same
    client to enqueue a mini_control job (the queue is a tab on this same sheet)."""
    return _CLIENT


def _ws():
    if _CLIENT is None:
        return None
    ss = _CLIENT.open_by_key(MASTER_SHEET_ID)
    try:
        return ss.worksheet(ONBOARDING_TAB)
    except Exception:
        ws = ss.add_worksheet(title=ONBOARDING_TAB, rows=200, cols=len(_HEADER))
        ws.append_row(_HEADER)
        return ws


def save(rec: TrackerRecord) -> str:
    row = [rec.key, json.dumps(rec.to_json()), rec.channel_name,
           len(rec.trackers), rec.submitted_at, rec.submitted_by]
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
        except Exception:
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
                except Exception:
                    continue
        return out
    if _LOCAL_FALLBACK.exists():
        try:
            return json.loads(_LOCAL_FALLBACK.read_text())
        except Exception:
            return []
    return []


def record_from_json(d: dict) -> TrackerRecord:
    d = {k: v for k, v in d.items() if not k.startswith("_")}
    return TrackerRecord(**d)


def existing_registry(exclude_key: Optional[str] = None) -> "Dict[str, object]":
    """{'keys': [...], 'channels': {channel_id: key}} across the LIVE tracker orgs
    (slack_post.ORG_CHANNELS) + already-onboarded rows (minus exclude_key). Best-
    effort — a failed import just contributes nothing."""
    keys: List[str] = []
    channels: Dict[str, str] = {}
    try:
        from automations.tableau_screenshots import slack_post as _sp
        for k, cids in getattr(_sp, "ORG_CHANNELS", {}).items():
            # An office already applied into ORG_CHANNELS must not collide with
            # ITSELF on a re-apply (idempotent onboard_apply / a Post-now re-click).
            if exclude_key and k == exclude_key:
                continue
            keys.append(k)
            for cid in cids:
                channels.setdefault(cid, k)
    except Exception:
        pass
    for d in load_all():
        k = d.get("key")
        if k and k == exclude_key:
            continue
        if k:
            keys.append(k)
        cid = d.get("channel_id")
        if cid:
            channels.setdefault(cid, k or "(onboarded)")
    return {"keys": keys, "channels": channels}
