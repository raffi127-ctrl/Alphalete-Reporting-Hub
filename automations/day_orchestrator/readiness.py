"""Readiness — is a report's data actually available yet?

Locked design (Megan 2026-06-23):
  * TABLEAU only gets a readiness gate. The probe asks "are today's rows actually
    present in the extract?" — a date-coverage check, NOT a clock time.
  * AppStream is always up to date → no probe, immediately ready.
  * pure-API → ready.
  * upload-gated → MANUAL (handled by the loop, not probed here).

Per-source, cached per pass, MONOTONIC: once a Tableau source has today's data it
never un-refreshes, so a READY verdict sticks and we stop probing it.

Session gate: every Tableau/AppStream probe first checks the ownerville session
is warm (the holder exports cookies every few minutes). If stale, the source is
NOT ready with reason 'ownerville session stale' — fail closed, never run with a
dead session (design §8).
"""
from __future__ import annotations

import datetime as dt
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from automations.day_orchestrator import registry


@dataclass
class Readiness:
    ready: bool
    reason: str


# ---------------- session warmth ----------------

def session_status(stale_after_minutes: int = 20) -> Tuple[bool, float, str]:
    """(warm, age_minutes, reason). Warm = the holder's exported ownerville
    storage_state file was refreshed within `stale_after_minutes`. The holder
    re-exports every few minutes while the session is live; a stale file means
    the session went down and needs a re-seed on the mini."""
    try:
        from automations.shared.tableau_patchright import OWNERVILLE_STORAGE_STATE as ov
    except Exception as e:  # import shouldn't fail, but never crash the probe
        return False, float("inf"), f"cannot import storage_state path ({e})"
    p = Path(ov)
    if not p.exists():
        return False, float("inf"), (
            f"no ownerville session yet ({p.name} missing) — seed the holder on the mini")
    age_min = (dt.datetime.now().timestamp() - p.stat().st_mtime) / 60.0
    if age_min > stale_after_minutes:
        return False, age_min, (
            f"ownerville session stale ({age_min:.0f}m since last export; "
            f"holder may be down) — re-seed the mini")
    return True, age_min, "warm"


# ---------------- per-source probe cache (monotonic) ----------------

class ReadinessCache:
    """One per orchestrator run. Caches a source's verdict for the whole day:
    once READY, sticky (never re-probe). NOT-ready is re-probed each pass."""

    def __init__(self, cfg: registry.Config, *, dry_run: bool, target_date: dt.date,
                 stale_after_minutes: int = 20, verbose: bool = True):
        self.cfg = cfg
        self.dry_run = dry_run
        self.target_date = target_date
        self.stale_after = stale_after_minutes
        self.verbose = verbose
        self._ready: Dict[str, Readiness] = {}   # sticky READY verdicts

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [readiness] {msg}", flush=True)

    def source_ready(self, source_id: str) -> Readiness:
        if source_id in self._ready:
            return self._ready[source_id]            # sticky
        r = self._probe_source(source_id)
        if r.ready:
            self._ready[source_id] = r               # cache only READY (monotonic)
        return r

    def report_ready(self, rpt: registry.Report) -> Readiness:
        """A report is ready when ALL its data sources are ready. AppStream/API
        are immediately ready; upload is never gated here."""
        if rpt.source_type in ("appstream", "api"):
            return Readiness(True, f"{rpt.source_type} — immediately ready (no probe)")
        if rpt.source_type == "upload":
            return Readiness(True, "upload — manual (not gated)")
        # tableau: require a warm session, then every source ready.
        warm, age, why = session_status(self.stale_after)
        if not warm:
            return Readiness(False, why)
        for sid in rpt.data_sources:
            r = self.source_ready(sid)
            if not r.ready:
                return Readiness(False, f"{sid}: {r.reason}")
        return Readiness(True, "all sources ready")

    # ---- the actual Tableau probe ----
    def _probe_source(self, source_id: str) -> Readiness:
        scfg = self.cfg.sources.get(source_id, {})
        probe = scfg.get("probe", {})
        ptype = probe.get("type", "not_configured")

        if ptype == "not_configured":
            # Dry-run: let the full loop exercise. Live: force wiring first.
            if self.dry_run:
                return Readiness(True, "stubbed READY (dry-run; probe not wired)")
            return Readiness(False, "probe not wired — set the view URL before cutover")

        if ptype == "tableau_date_coverage":
            return self._probe_tableau_date_coverage(source_id, probe)

        return Readiness(False, f"unknown probe type {ptype!r}")

    def _probe_tableau_date_coverage(self, source_id: str, probe: dict) -> Readiness:
        """Lightweight: pull the source view's crosstab and confirm the target
        day's rows are present (max date >= target) with a row-count floor.
        Reuses the report stack's own patchright crosstab download — no fresh
        login (warm session), retried internally by the helper."""
        view_url = probe.get("view_url")
        crosstab_sheet = probe.get("crosstab_sheet")
        date_col = probe.get("date_col")
        min_rows = int(probe.get("min_rows", 1))
        if not (view_url and crosstab_sheet and date_col):
            return Readiness(False, "probe misconfigured (need view_url/crosstab_sheet/date_col)")

        try:
            from automations.shared.tableau_patchright import download_crosstab_patchright
        except Exception as e:
            return Readiness(False, f"cannot import tableau helper ({e})")

        out = Path(tempfile.gettempdir()) / f"probe_{source_id.replace(':', '_')}.csv"
        try:
            download_crosstab_patchright(view_url, crosstab_sheet, out, verbose=False)
        except Exception as e:
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"extract not pullable yet ({line})")

        ok, why = _csv_covers_date(out, date_col, self.target_date, min_rows)
        return Readiness(ok, why)


def _csv_covers_date(csv_path: Path, date_col: str, target: dt.date,
                     min_rows: int) -> Tuple[bool, str]:
    """True when the CSV has >= min_rows data rows and its max date in `date_col`
    reaches `target`. Tolerant date parsing; if no date parses, NOT ready."""
    import csv as _csv

    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
    except Exception as e:
        return False, f"cannot read probe CSV ({e})"

    if len(rows) < min_rows:
        return False, f"only {len(rows)} row(s) (< {min_rows} floor) — extract still filling"

    max_date = None
    for r in rows:
        d = _parse_date(r.get(date_col, ""))
        if d and (max_date is None or d > max_date):
            max_date = d
    if max_date is None:
        return False, f"no parseable dates in column {date_col!r}"
    if max_date >= target:
        return True, f"data through {max_date.isoformat()} (>= {target.isoformat()})"
    return False, f"data only through {max_date.isoformat()} (need {target.isoformat()})"


def _parse_date(s: str) -> Optional[dt.date]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%-m/%-d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
