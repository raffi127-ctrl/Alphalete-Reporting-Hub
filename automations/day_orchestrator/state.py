"""Day-state persistence + per-day lockfile + control file.

The orchestrator is a resident process, but it must survive a reboot/crash: it
writes the whole day's state to disk after EVERY report transition, so a relaunch
resumes (re-reads the file) instead of re-running completed work. A per-day
lockfile stops two orchestrators racing.

Files (under output/day_state/):
  <date>.json          full day-state (statuses, attempts, reasons)
  <date>.lock          pid lockfile (resident-process guard)
  <date>.control.json  stop/resume map written by control.py (phone/CLI)

Stdlib only. Timestamps are naive local (the mini's CST) — these run as a normal
launchd process, not the Workflow sandbox, so datetime.now() is fine.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

# Repo root = three parents up from this file (automations/day_orchestrator/state.py)
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "output" / "day_state"


# ---- terminal + non-terminal statuses (mirror design §5) ----
DONE = "DONE"                       # ran + verify confirms cells filled
INCOMPLETE = "INCOMPLETE"           # exit 0 but verify found blanks (names them)
FAILED = "FAILED"                   # errored during run
MISSED_NOT_READY = "MISSED_NOT_READY"   # never ready by backstop
BLOCKED_SESSION = "BLOCKED_SESSION"     # ownerville stale, never recovered
HALTED_FOR_FIX = "HALTED_FOR_FIX"       # human stopped it (control.py)
MANUAL_PENDING_UPLOAD = "MANUAL_PENDING_UPLOAD"  # upload-gated, file absent
SKIPPED = "SKIPPED"                 # not scheduled today
PENDING = "PENDING"                 # not yet attempted / waiting (non-terminal)
STILL_TRYING = "STILL_TRYING"       # attempted, data not ready, in the loop

TERMINAL = {DONE, INCOMPLETE, FAILED, MISSED_NOT_READY, BLOCKED_SESSION,
            HALTED_FOR_FIX, MANUAL_PENDING_UPLOAD, SKIPPED}


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


@dataclass
class ReportState:
    report_id: str
    status: str = PENDING
    attempts: int = 0
    # Auto-retries of just the FAILED PARTS of an INCOMPLETE run (via the
    # manifest's retry_args). Separate from `attempts` (whole-report runs) so a
    # part-retry can't consume the report's run budget. Capped in run.py.
    auto_retries: int = 0
    last_reason: str = ""
    last_attempt_ts: Optional[str] = None
    waiting_on: Optional[str] = None          # which source it's blocked on (for the email)
    missing: List[str] = field(default_factory=list)  # specific blanks from reconcile
    display_name: str = ""
    hub_run_id: Optional[str] = None          # open Hub Activity "started" row (yellow pill); None = no live pill

    def is_terminal(self) -> bool:
        return self.status in TERMINAL


@dataclass
class DayState:
    date: str
    started_ts: str = field(default_factory=_now)
    checkpoint_sent: bool = False
    final_sent: bool = False
    session_alert_sent: bool = False
    reports: Dict[str, ReportState] = field(default_factory=dict)

    # ---- transitions ----
    def set(self, report_id: str, status: str, reason: str = "",
            waiting_on: Optional[str] = None, missing: Optional[List[str]] = None,
            bump_attempt: bool = False) -> None:
        rs = self.reports[report_id]
        rs.status = status
        rs.last_reason = reason
        rs.waiting_on = waiting_on
        if missing is not None:
            rs.missing = missing
        if bump_attempt:
            rs.attempts += 1
            rs.last_attempt_ts = _now()

    def pending_ids(self) -> List[str]:
        return [r.report_id for r in self.reports.values() if not r.is_terminal()]

    def all_terminal(self) -> bool:
        return all(r.is_terminal() for r in self.reports.values())

    def by_status(self, *statuses) -> List[ReportState]:
        s = set(statuses)
        return [r for r in self.reports.values() if r.status in s]


# ---------- persistence ----------

def _state_path(date: str) -> Path:
    return STATE_DIR / f"{date}.json"


def load_or_create(date: str, report_ids_with_names: Dict[str, str]) -> DayState:
    """Load today's state if it exists (resume), else create a fresh one seeded
    with every scheduled report as PENDING."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = _state_path(date)
    if p.exists():
        try:
            raw = json.loads(p.read_text())
            reports = {rid: ReportState(**rs) for rid, rs in raw.get("reports", {}).items()}
            ds = DayState(
                date=raw["date"],
                started_ts=raw.get("started_ts", _now()),
                checkpoint_sent=raw.get("checkpoint_sent", False),
                final_sent=raw.get("final_sent", False),
                session_alert_sent=raw.get("session_alert_sent", False),
                reports=reports,
            )
            # Add any newly-scheduled reports not in the saved file.
            for rid, name in report_ids_with_names.items():
                if rid not in ds.reports:
                    ds.reports[rid] = ReportState(report_id=rid, display_name=name)
            return ds
        except Exception:
            pass  # corrupt → rebuild fresh below
    ds = DayState(date=date)
    for rid, name in report_ids_with_names.items():
        ds.reports[rid] = ReportState(report_id=rid, display_name=name)
    return ds


def save(ds: DayState) -> None:
    """Atomic write (temp + replace) so a crash mid-write never corrupts state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = _state_path(ds.date)
    payload = {
        "date": ds.date,
        "started_ts": ds.started_ts,
        "checkpoint_sent": ds.checkpoint_sent,
        "final_sent": ds.final_sent,
        "session_alert_sent": ds.session_alert_sent,
        "reports": {rid: asdict(rs) for rid, rs in ds.reports.items()},
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(p)


# ---------- lockfile (resident-process guard) ----------

def _lock_path(date: str) -> Path:
    return STATE_DIR / f"{date}.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def acquire_lock(date: str) -> bool:
    """Return True if we got the day's lock. False if another LIVE orchestrator
    holds it (its pid is still running). A stale lock (dead pid) is reclaimed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lp = _lock_path(date)
    if lp.exists():
        try:
            old = int(lp.read_text().strip() or "0")
        except ValueError:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            return False
    lp.write_text(str(os.getpid()))
    return True


def release_lock(date: str) -> None:
    lp = _lock_path(date)
    try:
        if lp.exists() and lp.read_text().strip() == str(os.getpid()):
            lp.unlink()
    except OSError:
        pass


# ---------- control file (stop/resume; written by control.py) ----------

def control_path(date: str) -> Path:
    return STATE_DIR / f"{date}.control.json"


def read_control(date: str) -> Dict[str, str]:
    """Return {report_id: 'stop'|'resume'}. Tolerant of a missing/corrupt file."""
    p = control_path(date)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def write_control(date: str, mapping: Dict[str, str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = control_path(date)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mapping, indent=2))
    tmp.replace(p)
