"""Mini Control READ LANE — the queue split that keeps a log read off a report's heels.

    python -m automations.day_orchestrator.test_mini_control_lanes

Covers the two things that can actually hurt:
  1. The lanes PARTITION the queue — every action belongs to exactly one, so the
     two processes can never claim the same row (no locking, no leases).
  2. Orphan reclamation is PER-LANE. The read lane polls every 20s; a `rerun`
     legitimately runs for 22 minutes. If the read lane could reclaim it, it
     would mark a live job dead and invite the duplicate re-run that
     _reclaim_orphans exists to prevent (Megan 2026-08-19).

No network: _reclaim_orphans is driven with a fake worksheet.
"""
from __future__ import annotations

import datetime as dt

from automations.day_orchestrator import mini_control as mc


class _FakeWS:
    """Records _set() calls instead of touching a Sheet."""

    def __init__(self):
        self.updates = []           # (rownum, status)

    def update_cells(self, *a, **k):
        pass


def _fake_set(ws, rownum, status, result, finished=False):
    ws.updates.append((rownum, status))


def _row(action, status, started_min_ago=None):
    r = {"Action": action, "Status": status, "Args": "", "By": "test", "Result": ""}
    if started_min_ago is not None:
        ts = dt.datetime.now() - dt.timedelta(minutes=started_min_ago)
        r["Result"] = f"started {ts:%Y-%m-%dT%H:%M:%S}"
    return r


def _check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")
    return ok


def test_partition():
    """Every action belongs to exactly one lane — no row is orphaned or shared."""
    ok = True
    both, neither = [], []
    for action in mc.ACTIONS:
        m = mc._lane_owns(action, mc.LANE_MAIN)
        r = mc._lane_owns(action, mc.LANE_READ)
        if m and r:
            both.append(action)
        if not m and not r:
            neither.append(action)
    ok &= _check("no action is claimed by BOTH lanes", both, [])
    ok &= _check("no action is claimed by NEITHER lane", neither, [])
    # The read lane is exactly READONLY_ACTIONS, nothing crept in.
    read_actions = {a for a in mc.ACTIONS if mc._lane_owns(a, mc.LANE_READ)}
    ok &= _check("read lane == READONLY_ACTIONS",
                 read_actions, set(mc.READONLY_ACTIONS) & set(mc.ACTIONS))
    # Spot-check the ones that matter most in both directions.
    ok &= _check("logtail is a READ row", mc._lane_owns("logtail", mc.LANE_READ), True)
    ok &= _check("rerun is a MAIN row", mc._lane_owns("rerun", mc.LANE_MAIN), True)
    ok &= _check("rerun is NOT a read row", mc._lane_owns("rerun", mc.LANE_READ), False)
    # Case/whitespace from the Sheet must not flip a row into the wrong lane.
    ok &= _check("' LogTail ' still reads as a READ row",
                 mc._lane_owns(" LogTail ", mc.LANE_READ), True)
    # An unknown action falls to main, which is the lane that reports it failed
    # — otherwise a typo would sit 'queued' forever with nobody owning it.
    ok &= _check("unknown action falls to MAIN",
                 mc._lane_owns("not_a_real_action", mc.LANE_MAIN), True)
    return ok


def test_orphan_reclaim_is_per_lane():
    """THE hazard: the read lane must not reclaim main's long-running rerun."""
    ok = True
    orig_set = mc._set
    mc._set = _fake_set
    try:
        # A rerun 22 minutes in (past the 10-min grace) + a stale logtail.
        rows = [
            _row("rerun", "running", started_min_ago=22),
            _row("logtail", "running", started_min_ago=22),
        ]

        ws = _FakeWS()
        n = mc._reclaim_orphans(ws, rows, mc.LANE_READ)
        ok &= _check("read lane reclaims 1 row", n, 1)
        ok &= _check("read lane touched ONLY the logtail row (row 3)",
                     ws.updates, [(3, "orphaned")])

        ws = _FakeWS()
        n = mc._reclaim_orphans(ws, rows, mc.LANE_MAIN)
        ok &= _check("main lane reclaims 1 row", n, 1)
        ok &= _check("main lane touched ONLY the rerun row (row 2)",
                     ws.updates, [(2, "orphaned")])

        # Inside the grace window nothing is reclaimed by either lane.
        fresh = [_row("rerun", "running", started_min_ago=1),
                 _row("logtail", "running", started_min_ago=1)]
        for lane in (mc.LANE_MAIN, mc.LANE_READ):
            ws = _FakeWS()
            n = mc._reclaim_orphans(ws, fresh, lane)
            ok &= _check(f"{lane} lane leaves a 1-min-old row alone", n, 0)

        # The real-world shape from 2026-08-27: main is mid-backfill while the
        # read lane polls. The read lane must reclaim nothing at all.
        live = [_row("rerun", "running", started_min_ago=45)]
        ws = _FakeWS()
        n = mc._reclaim_orphans(ws, live, mc.LANE_READ)
        ok &= _check("read lane will NOT kill a 45-min live rerun", n, 0)
        ok &= _check("…and wrote nothing", ws.updates, [])
    finally:
        mc._set = orig_set
    return ok


def test_defaults_unchanged():
    """A caller that passes no lane behaves exactly as before the split."""
    ok = True
    import inspect
    ok &= _check("poll_once defaults to main",
                 inspect.signature(mc.poll_once).parameters["lane"].default,
                 mc.LANE_MAIN)
    ok &= _check("_reclaim_orphans defaults to main",
                 inspect.signature(mc._reclaim_orphans).parameters["lane"].default,
                 mc.LANE_MAIN)
    ok &= _check("restart_poller kicks BOTH labels",
                 mc.MINI_CONTROL_READ_LABEL != mc.MINI_CONTROL_LABEL, True)
    ok &= _check("the installer is registered",
                 "install_mini_control_read" in mc.ACTIONS, True)
    ok &= _check("the installer is PLUMBING (runs at cap)",
                 "install_mini_control_read" in mc.PLUMBING_ACTIONS, True)
    return ok


def main() -> int:
    ok = True
    for fn in (test_partition, test_orphan_reclaim_is_per_lane,
               test_defaults_unchanged):
        print(f"\n--- {fn.__name__} ---")
        ok &= fn()
    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
