"""What this job created, per account -- the audit's memory."""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict

from automations.second_round_contacts import config as C

TRACKED, HIRED, REMOVED = "tracked", "hired", "removed"


def load() -> Dict[str, Dict[str, dict]]:
    if C.STATE_PATH.exists():
        try:
            return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- a corrupt file must not kill the run
            return {}
    return {}


def save(state: Dict[str, Dict[str, dict]]) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def key_for(a: dict) -> str:
    """phone10 first, else email -- the same identity plan() dedupes on."""
    from automations.applicant_contacts.extract import phone10
    p = phone10(a.get("phone", "") or "")
    return ("p:" + p) if p else ("e:" + (a.get("email", "") or "").strip().lower())


def entry(a: dict, *, resource_name: str, owner: str, office: str,
          second_round: dt.date, display: str) -> dict:
    return {"resourceName": resource_name, "display": display,
            "first_name": a.get("first_name", ""), "last_name": a.get("last_name", ""),
            "phone": a.get("phone", ""), "email": a.get("email", ""),
            "owner": owner, "office": office,
            "second_round": second_round.isoformat(),
            "created": dt.date.today().isoformat(), "status": TRACKED}
