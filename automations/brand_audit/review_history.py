"""Weekly review-count snapshots, so we can report 'new reviews in the last 7
days' without a per-review feed.

Each run records {company: {site: [{ts, total}, ...]}}. The weekly delta is
(current total) - (the snapshot closest to ~7 days ago). The first run has no
baseline, so the delta is None ('—') until the next weekly run. This works for
any site that gives a total count (Google, Glassdoor); a site we couldn't read
is simply skipped.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_PATH = Path.home() / ".config" / "brand-audit" / "review_history.json"
_BASELINE_MIN_AGE_DAYS = 6  # don't diff against a snapshot younger than this


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


def new_since_last_week(company: str, site: str, total) -> int | None:
    """Return new reviews vs the snapshot nearest ~7 days ago, or None if there
    isn't a baseline old enough yet. Pure read — does not record."""
    if total is None:
        return None
    snaps = (_load().get(company, {}) or {}).get(site, [])
    cutoff = _now() - timedelta(days=_BASELINE_MIN_AGE_DAYS)
    eligible = []
    for s in snaps:
        try:
            ts = datetime.fromisoformat(s["ts"])
            if ts <= cutoff and isinstance(s.get("total"), int):
                eligible.append((ts, s["total"]))
        except Exception:
            continue
    if not eligible:
        return None
    eligible.sort(key=lambda x: x[0])           # oldest..newest
    baseline_total = eligible[-1][1]            # most recent eligible
    return max(0, total - baseline_total)


def record(company: str, site: str, total) -> None:
    """Append today's snapshot (skip if total is unknown)."""
    if total is None:
        return
    state = _load()
    state.setdefault(company, {}).setdefault(site, []).append(
        {"ts": _now().isoformat(), "total": int(total)})
    # keep the last ~26 snapshots per site (half a year of weekly runs)
    state[company][site] = state[company][site][-26:]
    _save(state)
