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
                 stale_after_minutes: int = 20, verbose: bool = True,
                 gate_unprobed: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run
        self.target_date = target_date
        self.stale_after = stale_after_minutes
        self.verbose = verbose
        self.gate_unprobed = gate_unprobed
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
        if rpt.source_type == "email":
            return self._probe_email(rpt)
        # tableau: require a warm session, then every source ready.
        warm, age, why = session_status(self.stale_after)
        if not warm:
            return Readiness(False, why)
        for sid in rpt.data_sources:
            r = self.source_ready(sid)
            if not r.ready:
                return Readiness(False, f"{sid}: {r.reason}")
        return Readiness(True, "all sources ready")

    # ---- email-fed reports: ready when this week's source email has landed ----
    def _probe_email(self, rpt: registry.Report) -> Readiness:
        """No clock gate — ready only once the report's weekly source email is in.
        residential_rep_count waits for Archey's xlsx (reusing the report's OWN
        _expected_week_ending + email_source.latest_week_ending, so the gate and
        the report agree). Other email reports have no probe yet → run on schedule.
        Fail-OPEN on a probe error (IMAP hiccup) so a transient blip can't block
        forever — the report itself still refuses to fill from a missing email."""
        try:
            if rpt.report_id == "residential_rep_count":
                from automations.residential_rep_count import email_source
                from automations.residential_rep_count.run import _expected_week_ending
                expected = _expected_week_ending(self.target_date)
                latest = email_source.latest_week_ending()
                if latest and latest >= expected:
                    return Readiness(True, f"Archey email WE {expected.month}/{expected.day} is in")
                seen = f"latest WE {latest.month}/{latest.day}" if latest else "none found"
                return Readiness(
                    False, f"waiting on Archey's WE {expected.month}/{expected.day} email ({seen})")
            if rpt.report_id == "frontier_opt":
                # Ready once the two DAILY Events PDFs (by-store + events) have
                # landed — they carry the sales/percentages. The quality
                # scorecard lags ~2wk and the report forces it to the run week,
                # so it isn't a gate. Partial-safe either way.
                from automations.alphalete_org_report import frontier_email_source as fes
                avail = fes.latest_available()
                dailies = sum(1 for g in avail if "Daily Sales" in g)
                if dailies >= 2:
                    return Readiness(True, f"Frontier Events PDFs in ({len(avail)}/3)")
                return Readiness(
                    False, f"waiting on Frontier Events daily PDFs ({dailies}/2 in)")
            if rpt.report_id == "financial_report":
                # 3 senders land across Tue–Wed (hubtruth Tue PM, melissab Wed,
                # jsanchez Mon/Tue); a Thursday run should see all 3. Ready once
                # >=2 are in (the dominant hubtruth + at least one more). The
                # report is incremental/partial-safe, so this only avoids a
                # too-early empty run — a missing sender is filled next run.
                from automations.financial_report import email_source as fes
                n = fes.any_available(since_days=7)
                if n >= 2:
                    return Readiness(True, f"Financial workbooks in ({n}/3 senders)")
                return Readiness(
                    False, f"waiting on this week's Financial workbooks ({n}/3 senders in)")
            return Readiness(True, "email — no probe wired; running on schedule")
        except Exception as e:  # noqa: BLE001 — fail open; the report self-guards
            return Readiness(
                True, f"email probe error ({type(e).__name__}) — running; report self-guards")

    # ---- the actual Tableau probe ----
    def _probe_source(self, source_id: str) -> Readiness:
        scfg = self.cfg.sources.get(source_id, {})
        probe = scfg.get("probe", {})
        ptype = probe.get("type", "not_configured")

        if ptype == "not_configured":
            # No real readiness probe wired for this source yet. Default: just
            # run on the report's not_before schedule (like the manual process
            # did) — the report's own Tableau pull + the circle-back retry handle
            # a not-yet-refreshed extract. Set settings.gate_unprobed_sources=true
            # to instead BLOCK until a real probe is wired (hardening later).
            if self.gate_unprobed:
                return Readiness(False, "no readiness probe wired (gated)")
            return Readiness(True, "no readiness probe — running on schedule")

        if ptype == "tableau_date_coverage":
            return self._probe_tableau_date_coverage(source_id, probe)

        if ptype == "box_daily":
            return self._probe_box_daily(source_id, probe)

        return Readiness(False, f"unknown probe type {ptype!r}")

    def _probe_box_daily(self, source_id: str, probe: dict) -> Readiness:
        """Box (B2BBOXEnergyTracker/BoxDailyTracker) is the ORG Sales Board's
        LAST-landing source — its extract refreshes ~7-8am with the prior day's
        final numbers, so a board run before that writes incomplete Box columns.
        That's why the board used to sit on a hard cadence.not_before='08:00'
        (Megan 2026-07-11: replace the clock with a real readiness gate so it runs
        in its order the moment Box is in). This probe pulls the Box weekday-
        crosstab and confirms its max date has reached the latest COMPLETED
        reporting day — using the board's OWN week.completed_days (rollover-safe:
        Tue→[Mon], Mon→last Sun, Sat→Fri) and its OWN pull+parse, so the gate
        matches exactly what the fill reads. `min_rows` floors out a garbage/partial
        pull. The session-warmth gate already ran in report_ready(), so the warm
        ownerville cookies are reused (no fresh login)."""
        min_rows = int(probe.get("min_rows", 5))
        try:
            from automations.org_sales_board import section_pull as _sp
            from automations.org_sales_board import week as _wk
            from automations.shared.tableau_patchright import download_crosstab_patchright
        except Exception as e:  # noqa: BLE001
            return Readiness(False, f"cannot import Box pull ({e})")
        completed = _wk.completed_days(self.target_date)
        if not completed:
            return Readiness(True, "no completed reporting day to gate on — running")
        target = max(completed)
        spec = _sp.BOX_SPEC
        out = Path(tempfile.gettempdir()) / f"probe_{source_id.replace(':', '_')}.csv"
        try:
            download_crosstab_patchright(spec.view_url, spec.crosstab_sheet, out,
                                         verbose=False)
        except Exception as e:  # noqa: BLE001
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"Box extract not pullable yet ({line})")
        try:
            parsed = _sp.parse_crosstab_byday(spec, out, self.target_date)
        except Exception as e:  # noqa: BLE001
            return Readiness(False, f"Box crosstab not parseable yet ({str(e)[:100]})")
        owners = [o for o, m in parsed.items() if m.get(spec.metric)]
        if len(owners) < min_rows:
            return Readiness(False, f"Box crosstab thin ({len(owners)} owners "
                                    f"< {min_rows}) — extract not refreshed")
        maxd = max(d for o in owners for d in parsed[o][spec.metric])
        if maxd >= target:
            return Readiness(True, f"Box fresh through {maxd.isoformat()} "
                                   f"(need ≥ {target.isoformat()})")
        return Readiness(False, f"Box only through {maxd.isoformat()}, need "
                                f"{target.isoformat()} — extract not refreshed")

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
