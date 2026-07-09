"""Nightly schedule guard — the self-heal for launchd schedule drift, generalized
to EVERY timed report (not just the 4am orchestrator).

WHY: `git pull` updates a `deploy/com.alphalete.<x>.plist` FILE but never reloads
launchd, so launchd keeps firing whatever schedule it loaded at boot. That's the
recurring 4am->6am day-orchestrator drift AND why brand-audit-noon once fired at
2pm — every timed job carries the same risk, and every diagnostic that read the
plist FILE looked "fixed" while the live schedule was stale.

This runs ~02:45 daily (before the earliest daily job at 03:00) via
com.alphalete.orchestrator-schedule-guard. For each com.alphalete.* LaunchAgent
currently LOADED on THIS machine that has a committed deploy/<label>.plist with a
StartCalendarInterval, it re-bootstraps via install_agent (race-free: bootout ->
confirm gone -> bootstrap). No committed plist has RunAtLoad, so a reload NEVER
triggers an immediate run — it only refreshes the schedule launchd will honor, so
launchd can never hold a stale one and nobody has to remember to reinstall.

Skips (left alone): KeepAlive/always-on jobs (session-holder, keep-awake,
mini-control — no calendar), the guard itself (would bootout itself mid-run), and
high-frequency pollers (>2 intervals, or an interval with no Hour — e.g.
rc-autoread / resume-pushing) where "drift" is meaningless and a reload is pointless.

  python -m automations.day_orchestrator.schedule_guard          # reload all timed jobs
  python -m automations.day_orchestrator.schedule_guard --audit  # just list them + schedules
"""
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

from automations.day_orchestrator import install_agent

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"
SELF_LABEL = "com.alphalete.orchestrator-schedule-guard"


def _loaded_labels() -> list[str]:
    """Every com.alphalete.* LaunchAgent currently loaded in this user's domain."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return []
    labels = []
    for line in out.splitlines():
        lbl = line.split("\t")[-1].strip()
        if lbl.startswith("com.alphalete."):
            labels.append(lbl)
    return labels


def _timed_schedule(plist_path: Path):
    """Return the StartCalendarInterval entries if this is a once-daily/weekly
    TIMED job (each entry has an Hour, and there are at most 2 — a job with more,
    or an Hour-less entry, is a high-frequency poller we deliberately skip). Else
    None (KeepAlive/always-on, or a poller)."""
    try:
        d = plistlib.loads(plist_path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    sci = d.get("StartCalendarInterval")
    if sci is None:
        return None
    entries = sci if isinstance(sci, list) else [sci]
    if len(entries) > 2 or any("Hour" not in e for e in entries):
        return None
    return entries


def _fmt(entries) -> str:
    def one(e):
        wd = e.get("Weekday")
        return (f"wd{wd} " if wd is not None else "") + f"{int(e.get('Hour', 0)):02d}:{int(e.get('Minute', 0)):02d}"
    return ", ".join(one(e) for e in entries)


def _timed_jobs():
    """(label, name, entries) for every LOADED, committed, timed job except self."""
    out = []
    for label in sorted(set(_loaded_labels())):
        if label == SELF_LABEL:
            continue
        plist = DEPLOY / f"{label}.plist"
        if not plist.exists():
            continue
        entries = _timed_schedule(plist)
        if entries is None:
            continue
        out.append((label, label.replace("com.alphalete.", ""), entries))
    return out


def audit() -> int:
    jobs = _timed_jobs()
    print(f"SCHEDULE-AUDIT :: {len(jobs)} timed job(s) loaded on this machine:")
    for _label, name, entries in jobs:
        print(f"  {name:44s} {_fmt(entries)}")
    return 0


def main() -> int:
    if "--audit" in sys.argv[1:]:
        return audit()
    jobs = _timed_jobs()
    results = []
    for _label, name, entries in jobs:
        try:
            ok, msg = install_agent.install(name)
        except Exception as e:  # noqa: BLE001 — one bad job must not stop the rest
            ok, msg = False, f"reload raised: {type(e).__name__}: {str(e)[:100]}"
        results.append((ok, name, _fmt(entries), msg))
    ok_n = sum(1 for r in results if r[0])
    print(f"SCHEDULE-GUARD :: reloaded {ok_n}/{len(results)} timed job(s)")
    for ok, name, sched, msg in results:
        print(f"  {'OK ' if ok else 'FAIL'} {name} [{sched}]: {msg}")
    # Exit non-zero if ANY reload failed, so the guard log / Mini Control flags it.
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
