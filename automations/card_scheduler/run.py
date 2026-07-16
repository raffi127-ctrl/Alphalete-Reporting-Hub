"""Auto-run uploaded Hub cards assigned to THIS machine, at their scheduled time.

Megan's rule: assigning a card to Lucy 1 / Lucy 2 means it must auto-run on that
machine. Uploaded cards live in the shared "Report Library" Sheet (not the
orchestrator's registry), so this is a small scheduler JUST for them — decoupled
from the day_orchestrator (which only runs registered reports).

Runs from launchd every ~10 min. Each pass:
  1. read the shared library, keep cards whose `assignees` include this machine's
     Lucy profile AND that have a runnable `module` + a `schedule`,
  2. a card is DUE if today matches its weekdays (or it's daily) AND now is in
     [scheduled_time, scheduled_time + GRACE) AND it hasn't already run today,
  3. run each due card as a subprocess (`python -m <module> <args>`), wrapped in
     the Hub's publish_running/publish_done so it shows on the card + in the
     daily digest, and record it ran today (local marker → no double-runs).

The 4–8am vs after-8am distinction in the rule is about MECHANISM (morning batch
vs standalone); for uploaded cards this one scheduler covers both — a card just
runs at its time. Safe by default: --dry-run (and the committed default rollout)
only REPORTS what would run; nothing executes until --live.

Usage:
  python -m automations.card_scheduler.run [--live] [--dry-run] [--now HH:MM]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

SHARED_LIBRARY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
SHARED_LIBRARY_TAB = "Report Library"

# How long after a card's scheduled time it may still start (covers the launchd
# cadence + a busy machine). Must be >= the launchd interval so a card can't slip
# between two passes.
GRACE_MIN = 20

# Per-machine "already ran today" marker (never committed).
_STATE = Path.home() / ".config" / "recruiting-report" / "card-scheduler-ran.json"

_LUCY = {"Lucy 1", "Lucy 2"}


def _machine() -> str:
    from automations.shared import hub_identity
    return hub_identity.machine_name()


def _read_library() -> list[dict]:
    from automations.recruiting_report import fill as _fill
    ws = _fill.open_by_key(SHARED_LIBRARY_SHEET_ID).worksheet(SHARED_LIBRARY_TAB)
    out = []
    for r in ws.get_all_records():
        try:
            meta = json.loads(r.get("Metadata") or "{}")
        except Exception:
            meta = {}
        meta.setdefault("id", str(r.get("ID") or "").strip())
        meta.setdefault("name", str(r.get("Name") or meta.get("id")))
        if not meta.get("module"):
            meta["module"] = str(r.get("Module") or "") or None
        out.append(meta)
    return out


def _parse_hm(time_str: str) -> tuple[int, int] | None:
    """(hour, minute) from '8:30 AM' / '11:00 AM'."""
    s = (time_str or "").strip().upper()
    if not s:
        return None
    ampm = s[-2:] if s.endswith(("AM", "PM")) else None
    if ampm:
        s = s[:-2].strip()
    try:
        hh, mm = (s.split(":") + ["0"])[:2]
        hh, mm = int(hh), int(mm)
    except (ValueError, IndexError):
        return None
    if ampm == "PM" and hh != 12:
        hh += 12
    elif ampm == "AM" and hh == 12:
        hh = 0
    return (hh, mm) if 0 <= hh <= 23 and 0 <= mm <= 59 else None


def _assigned_here(meta: dict, machine: str) -> bool:
    return machine in (meta.get("assignees") or [])


def _due(meta: dict, now: dt.datetime) -> tuple[bool, str]:
    """(is_due, reason-if-not) for a card at `now`, ignoring the ran-today check."""
    sched = meta.get("schedule")
    if not isinstance(sched, dict):
        return False, "no schedule"
    hm = _parse_hm(sched.get("time"))
    if not hm:
        return False, "no/ødd time"
    freq = str(sched.get("frequency") or "").lower()
    weekdays = sched.get("weekdays")
    if freq != "daily":
        if not weekdays or now.weekday() not in [int(d) for d in weekdays]:
            return False, "not scheduled today"
    sched_dt = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    delta_min = (now - sched_dt).total_seconds() / 60
    if delta_min < 0:
        return False, f"not yet (runs {sched.get('time')})"
    if delta_min >= GRACE_MIN:
        return False, f"missed window (was {sched.get('time')})"
    return True, ""


def _load_ran(today: str) -> set[str]:
    try:
        data = json.loads(_STATE.read_text())
    except Exception:
        return set()
    return set(data.get(today, []))


def _mark_ran(today: str, card_id: str) -> None:
    try:
        data = json.loads(_STATE.read_text())
    except Exception:
        data = {}
    data = {today: sorted(set(data.get(today, [])) | {card_id})}  # keep only today
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(data))


def _run_card(meta: dict) -> tuple[bool, str]:
    """Run one card's module as a subprocess, wrapped in the Hub run-log so it
    shows on the card + in the daily digest."""
    module = meta["module"]
    args = meta.get("args") or []
    cid, name = meta.get("id"), meta.get("name")
    run_id = None
    try:
        from automations.day_orchestrator import hub_publish
        run_id = hub_publish.publish_running(cid, name)
    except Exception:
        run_id = None
    cmd = [sys.executable, "-m", module, *[str(a) for a in args]]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45 * 60)
    ok = proc.returncode == 0
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(
            cid, name, status="success" if ok else "failed", run_id=run_id)
    except Exception:
        pass
    tail = "\n".join((proc.stdout or proc.stderr or "").splitlines()[-3:])[:200]
    return ok, f"exit {proc.returncode} · {tail}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually run due cards (default: report only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would run and exit (same as omitting --live)")
    ap.add_argument("--now", default=None, help="override current HH:MM (testing)")
    args = ap.parse_args(argv)

    now = dt.datetime.now()
    if args.now:
        h, m = args.now.split(":")
        now = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    today = now.date().isoformat()
    machine = _machine()
    ts = now.isoformat(timespec="seconds")

    try:
        library = _read_library()
    except Exception as e:
        print(f"[{ts}] card-scheduler: library read failed: "
              f"{type(e).__name__}: {e}", flush=True)
        return 1

    mine = [m for m in library if _assigned_here(m, machine)]
    ran_today = _load_ran(today)
    live = args.live and not args.dry_run

    fired = 0
    for meta in mine:
        cid = meta.get("id")
        if not meta.get("module"):
            print(f"[{ts}] card-scheduler: skip {cid} — no module to run", flush=True)
            continue
        if cid in ran_today:
            continue
        due, why = _due(meta, now)
        if not due:
            continue
        if not live:
            print(f"[{ts}] card-scheduler: WOULD run {cid} "
                  f"({meta.get('schedule', {}).get('time')}) [dry-run]", flush=True)
            continue
        print(f"[{ts}] card-scheduler: running {cid} …", flush=True)
        _mark_ran(today, cid)   # mark BEFORE running so a crash can't double-fire
        ok, detail = _run_card(meta)
        fired += 1
        print(f"[{ts}] card-scheduler: {cid} {'ok' if ok else 'FAILED'} · {detail}",
              flush=True)

    print(f"[{ts}] card-scheduler: {machine} · {len(mine)} assigned here · "
          f"{fired} run{'' if live else ' (dry-run: none run)'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
