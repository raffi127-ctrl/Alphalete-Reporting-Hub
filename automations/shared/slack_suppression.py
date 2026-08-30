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

import datetime as dt
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from automations.shared.slack_tag_learning import _norm

# Committed base: hand-curated, shared with every machine.
STORE_PATH = Path(__file__).resolve().parent / "slack_do_not_ping.json"

# What a RUN writes (Lucy adding someone because they were asked to in the
# thread). NEVER the committed file: a dirty tracked file on Lucy 1 makes
# `lucy update`'s autostash conflict, which exits 0 and takes the 4am batch
# with it. output/ is gitignored. Promote with --promote on the laptop.
LOCAL_PATH = (Path(__file__).resolve().parents[2] / "output" / "shared"
              / "slack_do_not_ping.local.json")


def _read(path: Path) -> dict:
    if not path.exists():
        return {"people": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — never take a report down over this
        return {"people": []}


def _all_people() -> List[dict]:
    """Committed + local. A local entry for the same name wins, so an
    'actually, start pinging them again' can undo a committed one."""
    people = list(_read(STORE_PATH).get("people", []) or [])
    for local in _read(LOCAL_PATH).get("people", []) or []:
        people = [p for p in people
                  if _norm(p.get("name", "")) != _norm(local.get("name", ""))]
        people.append(local)
    return people


def entries(report: Optional[str] = None) -> List[dict]:
    out = []
    for e in _all_people():
        if e.get("removed"):        # an explicit un-suppress
            continue
        scope = e.get("reports")
        if scope and report and report not in scope:
            continue
        out.append(e)
    return out


def local_only() -> List[dict]:
    """Entries this machine added that aren't committed yet."""
    base = {_norm(p.get("name", "")) for p in _read(STORE_PATH).get("people", []) or []}
    return [p for p in _read(LOCAL_PATH).get("people", []) or []
            if _norm(p.get("name", "")) not in base or p.get("removed")]


def suppress(name: str, why: str, report: Optional[str] = None,
             asked_by: str = "") -> None:
    """Stop pinging `name`. Writes the LOCAL overlay only."""
    data = _read(LOCAL_PATH)
    people = [p for p in data.setdefault("people", [])
              if _norm(p.get("name", "")) != _norm(name)]
    entry = {"name": name, "why": why, "added": dt.date.today().isoformat()}
    if report:
        entry["reports"] = [report]
    if asked_by:
        entry["asked_by"] = asked_by
    people.append(entry)
    data["people"] = people
    _save_local(data)


def unsuppress(name: str, why: str, asked_by: str = "") -> None:
    """Start pinging `name` again — recorded as an explicit tombstone so it
    also overrides a COMMITTED entry, which a local file otherwise couldn't."""
    data = _read(LOCAL_PATH)
    people = [p for p in data.setdefault("people", [])
              if _norm(p.get("name", "")) != _norm(name)]
    entry = {"name": name, "why": why, "removed": True,
             "added": dt.date.today().isoformat()}
    if asked_by:
        entry["asked_by"] = asked_by
    people.append(entry)
    data["people"] = people
    _save_local(data)


def _save_local(data: dict) -> None:
    data["_note"] = (
        "MACHINE-LOCAL do-not-ping changes made at runtime (Lucy acting on a "
        "request in the thread). Gitignored: writing the committed store would "
        "dirty a tracked file and break `lucy update`. 'removed': true is an "
        "un-suppress that overrides the committed list."
    )
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")


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
