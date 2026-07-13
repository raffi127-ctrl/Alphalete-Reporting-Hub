"""Runtime seam reports use to read the harvest cache INSTEAD of scraping —
DEFAULT-OFF, fail-safe.

The live 4am path is UNCHANGED until `HARVEST_MODE=on` is set in a report's
environment (the canary flip). With no env var, `should_use_cache()` is False and
report code never even imports the rest of this package — behaviour is identical
to today.

Fail-safe by design: a cache MISS, staleness, or ANY error falls back to the live
scrape (returns None so the caller runs its existing download). The cache can only
ever REPLACE a live pull with byte-identical data or defer to live — it can never
serve stale data (loader hard-fails) and can never break a report (falls back).

Flip / rollback:
    HARVEST_MODE=on   in a report's env  → that report reads cache when present
    unset HARVEST_MODE                    → instant rollback to live scrape
Granularity is per-report via WHERE the env is set (e.g. only daily_metrics's
subprocess for the canary), so no report-list parsing is needed here.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
from pathlib import Path
from typing import Optional


def should_use_cache() -> bool:
    """True only when explicitly enabled. Fail-closed on anything unexpected."""
    return os.environ.get("HARVEST_MODE", "off").strip().lower() == "on"


def _log(msg: str) -> None:
    if os.environ.get("HARVEST_VERBOSE", "").strip():
        print(f"[harvest.adapter] {msg}", flush=True)


def try_cache_view(view_url: str, crosstab_sheet: str, out_path: Path,
                   *, target_date: Optional[dt.date] = None,
                   filters: Optional[dict] = None,
                   pull_mode: str = "saved_view") -> Optional[Path]:
    """If harvesting is enabled AND a verified cache entry exists for this exact
    (view_url, sheet, filters, pull_mode) on target_date, copy it to out_path and
    return it. Otherwise return None so the caller does its normal live download.

    Keyed on the ACTUAL view_url passed at call time, so owner-variant reports
    (Rashad/Aya inject their own CHURN_*_VIEW_URL) resolve to their own cache
    entry automatically.
    """
    if not should_use_cache():
        return None
    try:
        # Local imports so a default-off report never pulls this chain in.
        from automations.harvest.needs import DataNeed
        from automations.harvest.loader import load_harvest, StaleCacheError
        target_date = target_date or dt.date.today()
        need = DataNeed(workbook="", view_url=view_url, crosstab_sheet=crosstab_sheet,
                        filters=filters or {}, pull_mode=pull_mode)
        try:
            src = load_harvest(need, target_date)
        except StaleCacheError as e:
            _log(f"cache miss/stale → live: {e}")
            return None
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out_path)
        _log(f"served from cache: {crosstab_sheet} ← {src.name} → {out_path}")
        return out_path
    except Exception as e:  # noqa: BLE001 — never let the seam break a report
        _log(f"adapter error ({type(e).__name__}: {e}) → live fallback")
        return None
