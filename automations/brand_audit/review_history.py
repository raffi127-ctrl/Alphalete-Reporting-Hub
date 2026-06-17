"""Per-audit count snapshots, so we can report 'new since the last audit'
(reviews, and later social posts) without a full per-item feed.

Each run records {company: {site: [{ts, total}, ...]}}. The delta is
(current total) - (the most recent PRIOR snapshot's total) — i.e. what changed
since the last time this audit ran. The first audit has no prior snapshot, so
the delta is None ('—, baseline set') until the next run. Works for anything
that exposes a running total (Google reviews, Glassdoor reviews, later post
counts); an unreadable source is simply skipped.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_PATH = Path.home() / ".config" / "brand-audit" / "review_history.json"


def _load() -> dict:
    try:
        return json.loads(_PATH.read_text())
    except Exception:
        return {}


def _save(state: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(state, indent=2))


def _now():
    return datetime.now(timezone.utc)


def new_since_last_audit(company: str, site: str, total) -> int | None:
    """New items vs the most recent prior snapshot, or None if there's no prior
    snapshot yet (first audit). Pure read — call BEFORE record()."""
    if total is None:
        return None
    snaps = (_load().get(company, {}) or {}).get(site, [])
    prior = [s["total"] for s in snaps if isinstance(s.get("total"), int)]
    if not prior:
        return None
    return max(0, int(total) - prior[-1])   # last recorded = previous audit


# Back-compat alias
new_since_last_week = new_since_last_audit


def record(company: str, site: str, total) -> None:
    """Append this audit's snapshot (skip if total is unknown)."""
    if total is None:
        return
    state = _load()
    state.setdefault(company, {}).setdefault(site, []).append(
        {"ts": _now().isoformat(), "total": int(total)})
    state[company][site] = state[company][site][-26:]  # keep ~26 audits
    _save(state)
