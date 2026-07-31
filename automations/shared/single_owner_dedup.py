"""Per-owner "only what's new" filter for the single-owner Metrics posts.

Background — the bug this fixes (2026-07-31, flagged by Dylan Twaddle):
  Raf's #alphalete-sales Canceled-Orders / Disconnects posts show only the
  *previous day's* rows, because run.py dedups the Slack image against the
  destination Sheet tab (fill.find_new_rows). The per-office runner
  (office_metrics.runner -> canceled_orders/disconnects --owner X) has NO
  sheet to dedup against, so its `_run_single_owner` path posted EVERY row in
  the 30-day Status-Date window — i.e. the whole month — into channels like
  #palace-sales (Kash Rai) and #elevate-sales (Rashad).

This module gives the stateless single-owner path the same "new since last
run" behavior without a Sheet: a tiny per-owner JSON cache of the keys we've
already posted. Same dedup key each module uses on its Sheet tab:
    canceled_orders -> (Customer Name, SPM #)
    disconnects     -> (Customer Name, Account BAN)

First run for an owner (no cache yet) intentionally surfaces ONLY the most
recent Status-Date day and seeds the rest as already-seen, so rolling this
out to an office posts one clean day instead of dumping the backlog once.

Cross-platform (pathlib only) and Python 3.9-safe (the Mac mini runs 3.9).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# repo_root/automations/shared/single_owner_dedup.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]

# Prune keys first seen longer ago than this. Must exceed the pull's 30-day
# Status-Date window so a key can never be pruned while its row still shows up
# in the daily pull (which would let it re-post). 45 > 30 with margin.
_PRUNE_DAYS = 45


def _slug(owner: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (owner or "").strip().lower()).strip("_")
    return s or "owner"


def cache_path(subdir: str, owner: str) -> Path:
    """output/<subdir>/_posted/<owner-slug>.json — one file per owner."""
    return REPO_ROOT / "output" / subdir / "_posted" / (_slug(owner) + ".json")


def _row_key(row: Dict[str, str], key_fields: Sequence[str]) -> str:
    return "|".join((row.get(f, "") or "").strip() for f in key_fields)


def _parse_status(row: Dict[str, str], field: str) -> Optional[dt.date]:
    raw = (row.get(field, "") or "").strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _load_seen(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        seen = data.get("seen")
        return dict(seen) if isinstance(seen, dict) else {}
    except (ValueError, OSError):
        return {}


def _save_seen(path: Path, owner: str, seen: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"owner": owner, "seen": seen}, indent=2)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def filter_new(owner: str,
               rows: List[Dict[str, str]],
               key_fields: Sequence[str],
               subdir: str,
               *,
               persist: bool = True,
               status_date_field: str = "Status Date",
               first_run_latest_day_only: bool = True,
               today: Optional[dt.date] = None) -> List[Dict[str, str]]:
    """Return the subset of `rows` we haven't posted for this owner before.

    Mirrors fill.find_new_rows, but the "already posted" set lives in a
    per-owner JSON cache instead of a Sheet tab.

    persist=False (use for --dry-run) computes the new-rows subset for preview
    WITHOUT recording anything — so a dry preview never makes the real run skip
    those rows.
    """
    today = today or dt.date.today()
    path = cache_path(subdir, owner)
    seen = _load_seen(path)
    first_run = not seen

    new_rows = [r for r in rows if _row_key(r, key_fields) not in seen]

    # First-ever run for this owner: don't dump the 30-day backlog into the
    # channel — surface only the newest Status-Date day (everything older gets
    # seeded as already-seen just below).
    if first_run and first_run_latest_day_only and new_rows:
        dated = [(r, _parse_status(r, status_date_field)) for r in new_rows]
        present = [d for _, d in dated if d is not None]
        if present:
            latest = max(present)
            new_rows = [r for r, d in dated if d == latest]

    if persist:
        for r in rows:
            seen.setdefault(_row_key(r, key_fields), today.isoformat())
        cutoff = today - dt.timedelta(days=_PRUNE_DAYS)
        kept: Dict[str, str] = {}
        for k, v in seen.items():
            try:
                d = dt.date.fromisoformat(v)
            except (ValueError, TypeError):
                d = today  # undated/garbage -> treat as fresh, keep
            if d >= cutoff:
                kept[k] = v
        _save_seen(path, owner, kept)

    return new_rows
