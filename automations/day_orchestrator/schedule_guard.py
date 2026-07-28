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
high-frequency pollers — an interval with no Hour (e.g. rc-autoread /
resume-pushing) — where "drift" is meaningless and a reload is pointless.
Interval COUNT is not a skip signal: launchd has no "weekdays" field, so an
ordinary Mon-Sat daily job enumerates 6 intervals. See _timed_schedule.

  python -m automations.day_orchestrator.schedule_guard          # reload all timed jobs
  python -m automations.day_orchestrator.schedule_guard --audit  # just list them + schedules
"""
from __future__ import annotations

import plistlib
import re
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


# An XML comment may not contain "--", but several committed plists document
# their flags in one (`<!-- --no-pdf … -->`). launchd's own parser accepts them
# (`plutil -lint` says OK, and the jobs run), but Python's plistlib refuses the
# whole file — so those jobs silently vanished from the guard AND the audit.
# Strip comments and retry rather than drop a real job over a doc string.
_XML_COMMENT = re.compile(rb"<!--.*?-->", re.DOTALL)


def _load_plist(plist_path: Path):
    raw = plist_path.read_bytes()
    try:
        return plistlib.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    try:
        return plistlib.loads(_XML_COMMENT.sub(b"", raw))
    except Exception:  # noqa: BLE001
        return None


def _timed_schedule(plist_path: Path):
    """Return the StartCalendarInterval entries if this is a TIMED job — every
    entry carries an Hour. Else None (KeepAlive/always-on, or a high-frequency
    poller whose intervals have no Hour, e.g. rc-autoread / resume-pushing).

    Entry COUNT is deliberately not a filter. It used to be (">2 entries = a
    poller"), but that is the wrong proxy: launchd has no "weekdays" field, so a
    plain once-daily Mon-Sat job must enumerate one entry PER DAY — 6 entries,
    all Hour 20. That heuristic silently excluded ~12 ordinary timed jobs from
    the nightly drift reload (applicant-evening, sales-boards, b2b-quality,
    owners-call-reminder, override-bulletin-fri, pnl-office-fri, org-board-slack,
    vantura-slack-sales, …) — on a machine with a documented history of launchd
    firing every calendar job +2h. Those were exactly the jobs with no self-heal.
    An Hour-less interval is the honest poller signal, so that check stands alone.
    """
    d = _load_plist(plist_path)
    if d is None:
        return None
    sci = d.get("StartCalendarInterval")
    if sci is None:
        return None
    entries = sci if isinstance(sci, list) else [sci]
    if any("Hour" not in e for e in entries):
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

    # Daily coverage sweep: card any SCHEDULED job (4am batch OR standalone
    # launchd agent) that lacks a Hub card, so automations can never silently go
    # invisible. Confident-only + idempotent (safe to run on both machines).
    # Fully best-effort — a coverage hiccup must never fail the schedule guard.
    try:
        from automations.day_orchestrator import hub_coverage
        cov = (hub_coverage.sync(dry_run=False)
               + hub_coverage.sync_agents(dry_run=False)
               + hub_coverage.sync_launchd_system(dry_run=False))
        created = [m for m in cov if m.strip().startswith("✓")]
        print(f"SCHEDULE-GUARD :: coverage sweep — {len(created)} card(s) created/updated")
        for m in cov:
            print(m)
        unresolved = hub_coverage.audit_agents().get("unresolved", [])
        if unresolved:
            print("  ⚠️ agents with no resolvable card (review): "
                  + ", ".join(n for n, _why in unresolved))
    except Exception as e:  # noqa: BLE001 — never let coverage break the guard
        print(f"SCHEDULE-GUARD :: coverage sweep skipped ({type(e).__name__}: {str(e)[:80]})")

    # Exit non-zero if ANY reload failed, so the guard log / Mini Control flags it.
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
