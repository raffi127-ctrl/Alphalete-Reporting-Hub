"""Readiness gate — moved into the harvester so each unique source is probed
ONCE per day, not once per report. A READY verdict is sticky (monotonic).

SHADOW-ONLY. Nothing on the live 4am path imports this. See README.md.

Mirrors the orchestrator's model (day_orchestrator/readiness.py): sticky READY
in `_ready`, NOT-ready re-probed each pass. Reuses the SAME date-coverage check
(`_csv_covers_date`) the orchestrator already ships.

For the churn cluster specifically: schedule_config's `tableau:churn` source is
`probe.type == not_configured` (no date_col), so a churn need declares no
`date_col`. In that case readiness reduces to "the pull succeeded and returned
a non-empty crosstab" — the same effective gate the reports have today (they
wait inside drive_crosstab_dialog's render wait, then fail on an empty parse).
When a need DOES declare a date_col, we run the real coverage probe.
"""
from __future__ import annotations

import datetime as dt
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict

from automations.harvest.needs import DataNeed, cache_key
# Reuse the orchestrator's date-coverage logic verbatim.
from automations.day_orchestrator.readiness import _csv_covers_date


@dataclass
class Readiness:
    ready: bool
    reason: str


class ReadinessTracker:
    """One per harvest run. Sticky READY per source (keyed by cache_key)."""

    def __init__(self, target_date: dt.date):
        self.target_date = target_date
        self._ready: Dict[str, Readiness] = {}
        self._last_probe: Dict[str, dict] = {}

    def last_probe(self, need: DataNeed) -> dict:
        return self._last_probe.get(cache_key(need), {})

    def ready(self, need: DataNeed, page, *, download: Callable) -> Readiness:
        key = cache_key(need)
        if key in self._ready:                     # sticky READY
            return self._ready[key]

        if not need.date_col:
            # No coverage probe wired for this source. Ready-by-default; the
            # actual pull + row_count>0 is the effective gate (recorded on the
            # manifest). This matches how the churn reports gate today.
            r = Readiness(True, "no date_col probe — gated by non-empty pull")
            self._last_probe[key] = {"type": "none", "passed": True}
            self._ready[key] = r
            return r

        # Real coverage probe: pull the view once into a temp file and check its
        # date column reaches target_date. (Reuses the warm session `page`.)
        try:
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
                probe_path = Path(tf.name)
            download(need.view_url, need.crosstab_sheet, probe_path,
                     verbose=False, page=page)
            ok, why = _csv_covers_date(probe_path, need.date_col,
                                       self.target_date, need.min_rows)
            self._last_probe[key] = {"type": "date_coverage", "date_col": need.date_col,
                                     "passed": bool(ok), "detail": why}
            r = Readiness(bool(ok), why)
        except Exception as e:  # noqa: BLE001 — not-ready, re-probed next pass
            r = Readiness(False, f"probe error ({type(e).__name__}: {e})")
            self._last_probe[key] = {"type": "date_coverage", "passed": False,
                                     "detail": str(e)}
        if r.ready:
            self._ready[key] = r                    # cache only READY (monotonic)
        return r
