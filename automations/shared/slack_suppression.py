"""People a report must never tag, text, or list — a do-not-ping list.

Raf, 2026-08-30, about two names on New-Start's "unable to tag" list:
"Giovanna and Heiddy I'm not worried about... I know their engagement, I don't
want LUCY to keep pinging."

Distinct from shared.slack_tag_learning on purpose, and it BEATS it. Learning
answers "who is this person?"; suppression answers "should we be chasing them
at all?" — and the answer stays no even after somebody tags them, which is
exactly the case here: Raf tagged Giovanna by hand in the same reply that
taught us her id. Without this ordering, learning her id would promote her
straight back into the ping list she was just removed from.

Suppression is SILENT by design: a suppressed person is not tagged, not texted,
and not listed as a gap either. Listing them would just move the nagging from
the person to whoever reads the report.

Universal on purpose (Megan: "this should be universal for any slack chat
report"). Any report can call is_suppressed()/filter_names(). Scope a name to
one report with `reports: ["new_start_followup"]`; omit it to suppress
everywhere.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from automations.shared.slack_tag_learning import _norm

STORE_PATH = Path(__file__).resolve().parent / "slack_do_not_ping.json"


def _load() -> dict:
    if not STORE_PATH.exists():
        return {"people": []}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — never take a report down over this
        return {"people": []}


def entries(report: Optional[str] = None) -> List[dict]:
    out = []
    for e in _load().get("people", []) or []:
        scope = e.get("reports")
        if scope and report and report not in scope:
            continue
        out.append(e)
    return out


def is_suppressed(name: str, report: Optional[str] = None) -> bool:
    key = _norm(name)
    if not key:
        return False
    for e in entries(report):
        if _norm(e.get("name", "")) == key:
            return True
        for alias in e.get("aliases", []) or []:
            if _norm(alias) == key:
                return True
    return False


def filter_names(names: Iterable[str], report: Optional[str] = None):
    """-> (kept, dropped). Callers report `dropped` to the LOG, never to Slack."""
    kept, dropped = [], []
    for n in names:
        (dropped if is_suppressed(n, report) else kept).append(n)
    return kept, dropped


def suppressed_ids(report: Optional[str] = None) -> Dict[str, str]:
    """slack_id -> name, for the entries that carry one."""
    return {e["id"]: e.get("name", "") for e in entries(report) if e.get("id")}
