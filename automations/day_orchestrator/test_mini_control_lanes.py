"""Mini Control lanes — the queue split that keeps a log read, and a text, off a
report's heels.

    python -m automations.day_orchestrator.test_mini_control_lanes

Covers the two things that can actually hurt:
  1. The lanes PARTITION the queue — every action belongs to exactly one, so the
     two processes can never claim the same row (no locking, no leases).
  2. Orphan reclamation is PER-LANE. The read lane polls every 20s; a `rerun`
     legitimately runs for 22 minutes. If the read lane could reclaim it, it
     would mark a live job dead and invite the duplicate re-run that
     _reclaim_orphans exists to prevent (Megan 2026-08-19).

  3. The TEXT lane (2026-10-26) owns exactly TEXT_ACTIONS while it is running,
     and main takes them back when it is not — a text is never stranded and
     never claimed by two lanes.

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
    for text_live in (True, False):
        shared, neither = [], []
        for action in mc.ACTIONS:
            owners = [ln for ln in mc.LANES
                      if (ln != mc.LANE_TEXT or text_live)
                      and mc._lane_owns(action, ln, text_live)]
            if len(owners) > 1:
                shared.append((action, owners))
            if not owners:
                neither.append(action)
        tag = "text lane up" if text_live else "text lane DOWN"
        ok &= _check(f"[{tag}] no action is claimed by two lanes", shared, [])
        ok &= _check(f"[{tag}] no action is claimed by NO lane", neither, [])
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


def test_text_lane_ownership():
    """The text lane takes ONLY the sends; main stops taking them — unless the
    text lane is down, when main takes them back."""
    ok = True
    T, M, R = mc.LANE_TEXT, mc.LANE_MAIN, mc.LANE_READ
    text_rows = {a for a in mc.ACTIONS if mc._lane_owns(a, T)}
    ok &= _check("text lane == TEXT_ACTIONS", text_rows,
                 set(mc.TEXT_ACTIONS) & set(mc.ACTIONS))
    ok &= _check("every TEXT_ACTION is a real action",
                 sorted(set(mc.TEXT_ACTIONS) - set(mc.ACTIONS)), [])
    ok &= _check("TEXT and READ sets don't overlap",
                 sorted(set(mc.TEXT_ACTIONS) & set(mc.READONLY_ACTIONS)), [])
    for a in ("text_dispositions", "textgroup", "text_tracker", "text_obcl",
              "sendtext", "textgroup_image"):
        ok &= _check(f"{a} -> text lane", mc._lane_owns(a, T), True)
        ok &= _check(f"{a} NOT main while text lane is up",
                     mc._lane_owns(a, M, text_live=True), False)
        ok &= _check(f"{a} -> main while text lane is DOWN",
                     mc._lane_owns(a, M, text_live=False), True)
        ok &= _check(f"{a} never read", mc._lane_owns(a, R), False)
    # The 10/26 shape: the reports that held the texts stay on main.
    for a in ("rerun", "update", "restart_poller", "run_b2b_dispositions"):
        ok &= _check(f"{a} stays on main", mc._lane_owns(a, M), True)
        ok &= _check(f"{a} is not a text row", mc._lane_owns(a, T), False)
    # Messages LOOKUPS send nothing: they stay on the read lane.
    for a in ("find_group", "group_members", "text_resolve", "text_replies"):
        ok &= _check(f"{a} stays a READ row", mc._lane_owns(a, R), True)
        ok &= _check(f"{a} not a text row", mc._lane_owns(a, T), False)
    ok &= _check("' TextGroup ' (sheet case/space) is still a text row",
                 mc._lane_owns(" TextGroup ", T), True)
    ok &= _check("unknown action never lands on the text lane",
                 mc._lane_owns("not_a_real_action", T), False)
    return ok


def test_text_lane_liveness():
    """Heartbeat file: fresh = live; stale or missing = down."""
    import pathlib
    import tempfile
    ok = True
    orig = mc.TEXT_LANE_HEARTBEAT
    with tempfile.TemporaryDirectory() as d:
        mc.TEXT_LANE_HEARTBEAT = pathlib.Path(d) / "sub" / "hb.alive"
        try:
            ok &= _check("no heartbeat file = down", mc._text_lane_live(), False)
            mc._beat_text_lane()
            ok &= _check("fresh beat = live", mc._text_lane_live(), True)
            later = mc.TEXT_LANE_HEARTBEAT.stat().st_mtime + mc.TEXT_LANE_STALE_S + 1
            ok &= _check("stale beat = down", mc._text_lane_live(now=later), False)
        finally:
            mc.TEXT_LANE_HEARTBEAT = orig
    return ok


def test_orphan_reclaim_respects_lane_tag():
    """A text row can run on main (text lane down) or on the text lane. The
    lane that STARTED it is the only one that may reclaim it."""
    ok = True
    orig_set = mc._set
    mc._set = _fake_set
    try:
        def tagged(action, lane, mins=22):
            r = _row(action, "running", started_min_ago=mins)
            r["Result"] += f" · {lane} lane"
            return r
        rows = [tagged("text_tracker", mc.LANE_MAIN),   # main covered for text
                tagged("text_tracker", mc.LANE_TEXT),
                tagged("rerun", mc.LANE_MAIN)]
        ws = _FakeWS()
        mc._reclaim_orphans(ws, rows, mc.LANE_TEXT)
        ok &= _check("text lane reclaims only the row IT started (row 3)",
                     ws.updates, [(3, "orphaned")])
        ws = _FakeWS()
        mc._reclaim_orphans(ws, rows, mc.LANE_MAIN, text_live=True)
        ok &= _check("main reclaims its own text + rerun rows, not the text lane's",
                     ws.updates, [(2, "orphaned"), (4, "orphaned")])
        ws = _FakeWS()
        mc._reclaim_orphans(ws, rows, mc.LANE_READ)
        ok &= _check("read lane touches none of them", ws.updates, [])
        # Untagged (older code) rows fall back to the action-name split.
        old = [_row("textgroup", "running", started_min_ago=22)]
        ws = _FakeWS()
        mc._reclaim_orphans(ws, old, mc.LANE_TEXT)
        ok &= _check("untagged text row -> text lane reclaims it",
                     ws.updates, [(2, "orphaned")])
        ws = _FakeWS()
        mc._reclaim_orphans(ws, old, mc.LANE_MAIN, text_live=True)
        ok &= _check("untagged text row -> main leaves it while text lane is up",
                     ws.updates, [])
    finally:
        mc._set = orig_set
    return ok


def test_text_pass_order():
    """Text lane: pure sends before captures; main's order is untouched."""
    ok = True
    rows = [{"Action": "text_tracker"}, {"Action": "text_dispositions"},
            {"Action": "textgroup"}, {"Action": "text_obcl"}]
    got = [r["Action"] for _, r in mc._pass_order(rows, mc.LANE_TEXT)]
    ok &= _check("text lane runs text_tracker last", got[-1], "text_tracker")
    ok &= _check("…and keeps the sends in sheet order (plumbing first)",
                 got[:-1], ["textgroup", "text_dispositions", "text_obcl"])
    got = [r["Action"] for _, r in mc._pass_order(rows)]
    ok &= _check("main lane order unchanged",
                 got, ["textgroup", "text_tracker", "text_dispositions", "text_obcl"])
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
    ok &= _check("text-lane installer registered + PLUMBING",
                 "install_mini_control_text" in mc.ACTIONS
                 and "install_mini_control_text" in mc.PLUMBING_ACTIONS, True)
    ok &= _check("three distinct lane labels",
                 len({mc.MINI_CONTROL_LABEL, mc.MINI_CONTROL_READ_LABEL,
                      mc.MINI_CONTROL_TEXT_LABEL}), 3)
    import pathlib
    plist = (pathlib.Path(mc.__file__).resolve().parents[2] / "deploy"
             / f"{mc.MINI_CONTROL_TEXT_LABEL}.plist")
    ok &= _check("text-lane plist ships in deploy/", plist.exists(), True)
    if plist.exists():
        import plistlib
        d = plistlib.loads(plist.read_bytes())
        args = d.get("ProgramArguments", [])
        ok &= _check("plist runs --lane text",
                     args[args.index("--lane") + 1] if "--lane" in args else None,
                     mc.LANE_TEXT)
        ok &= _check("plist label matches", d.get("Label"), mc.MINI_CONTROL_TEXT_LABEL)
    return ok


def test_restart_kicks_all_lanes():
    """restart_poller must reload the text lane too (no real launchctl)."""
    ok = True
    calls = []

    class _P:
        def __init__(self, argv, **k):
            calls.append(argv)
    orig = mc.subprocess.Popen
    mc.subprocess.Popen = _P
    try:
        good, _msg = mc._action_restart_poller("")
    finally:
        mc.subprocess.Popen = orig
        mc._restart_scheduled_at = None
    cmd = " ".join(calls[0]) if calls else ""
    ok &= _check("restart_poller scheduled", good, True)
    for label in (mc.MINI_CONTROL_LABEL, mc.MINI_CONTROL_READ_LABEL,
                  mc.MINI_CONTROL_TEXT_LABEL):
        ok &= _check(f"kicks {label}", label in cmd, True)
    return ok


def test_outbox_drainer():
    """Who drains the local text outbox: text lane always, main only while the
    text lane is down, read lane never."""
    ok = True
    calls = []
    import types
    fake = types.SimpleNamespace(pending=lambda: ["t"],
                                 drain=lambda send, log: (calls.append(1) or (1, 0)))
    import sys as _sys
    orig_mod = _sys.modules.get("automations.day_orchestrator.text_outbox")
    orig_live = mc._text_lane_live
    _sys.modules["automations.day_orchestrator.text_outbox"] = fake
    import automations.day_orchestrator as pkg
    orig_attr = getattr(pkg, "text_outbox", None)
    pkg.text_outbox = fake
    try:
        for lane, live, want in ((mc.LANE_TEXT, True, 1), (mc.LANE_MAIN, True, 0),
                                 (mc.LANE_MAIN, False, 1), (mc.LANE_READ, False, 0)):
            calls.clear()
            mc._text_lane_live = lambda now=None, _l=live: _l
            mc._drain_text_outbox(dry_run=False, sandbox=False, lane=lane)
            ok &= _check(f"{lane} lane (text lane {'up' if live else 'down'}) drains",
                         len(calls), want)
    finally:
        mc._text_lane_live = orig_live
        if orig_mod is not None:
            _sys.modules["automations.day_orchestrator.text_outbox"] = orig_mod
        if orig_attr is not None:
            pkg.text_outbox = orig_attr
    return ok


def main() -> int:
    ok = True
    for fn in (test_partition, test_orphan_reclaim_is_per_lane,
               test_text_lane_ownership, test_text_lane_liveness,
               test_orphan_reclaim_respects_lane_tag, test_text_pass_order,
               test_defaults_unchanged, test_restart_kicks_all_lanes,
               test_outbox_drainer):
        print(f"\n--- {fn.__name__} ---")
        ok &= fn()
    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


def test_lane_suite_passes():
    """pytest entry: the checks above RETURN their result (they print every
    line rather than stop at the first), which pytest ignores — so assert the
    whole suite here."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
