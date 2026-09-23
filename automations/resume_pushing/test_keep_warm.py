"""Browser-free checks on keeping the CDP Chrome warm between ticks. Run:

    python -m automations.resume_pushing.test_keep_warm

WHY THIS EXISTS (2026-09-22). Every tick used to launch its own Chrome and kill
it on the way out. Indeed challenges the FIRST resume a browser opens and then
lets that session through, so a browser that dies every two minutes fights a new
"Verify you are human" every two minutes — and on the day the challenge stopped
auto-clearing, six offices across two machines filled ZERO phone numbers while
AppStream itself was perfectly healthy.

What is pinned here:
  * a clean session LEAVES Chrome running; a session that raised KILLS it (a
    wedged or half-logged-in browser is never handed to the next tick),
  * reuse needs both the flag and a port that actually answers,
  * idle browsers go stale and get reaped, and a profile with no marker counts
    as stale (we only keep what we can prove is in use),
  * the teardown still runs — and still kills — when the caller raises.

No browser, no network, no Slack, no sends.
"""
from __future__ import annotations  # Lucy 2 / Lucy 4 run Python 3.9

import tempfile
from pathlib import Path

from . import run as rp


def _check(label, got, expected) -> bool:
    ok = got == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}"
          f"{'' if ok else f'  (expected {expected!r})'}")
    return ok


def test_reuse_decision() -> bool:
    print("when to reuse a running browser")
    ok = True
    ok &= _check("port answering + keep-warm on",
                 rp._should_reuse_browser(True, True), True)
    ok &= _check("nothing listening", rp._should_reuse_browser(False, True), False)
    ok &= _check("keep-warm switched off",
                 rp._should_reuse_browser(True, False), False)
    ok &= _check("a dead port never reads as alive",
                 rp._cdp_port_alive(9), False)
    return ok


def test_kill_decision() -> bool:
    print("when to kill on the way out")
    ok = True
    ok &= _check("clean session is left warm",
                 rp._should_kill_on_exit(False, True), False)
    ok &= _check("a session that raised is killed",
                 rp._should_kill_on_exit(True, True), True)
    ok &= _check("keep-warm off: always killed",
                 rp._should_kill_on_exit(False, False), True)
    ok &= _check("keep-warm off AND raised: killed",
                 rp._should_kill_on_exit(True, False), True)
    # A browser Indeed never let through is retired even though nothing raised:
    # keeping it pins the office behind the same closed gate forever, while a cold
    # Chrome gets a fresh challenge it often passes.
    ok &= _check("a walled browser is retired, not kept",
                 rp._should_kill_on_exit(False, True, "never cleared"), True)
    ok &= _check("a healthy browser with no suspicion is kept",
                 rp._should_kill_on_exit(False, True, ""), False)
    try:
        rp.mark_browser_suspect("Indeed's check never cleared")
        ok &= _check("marking a suspect flips the decision",
                     rp._should_kill_on_exit(False, True), True)
        rp._clear_browser_suspect()
        ok &= _check("clearing it restores keep-warm",
                     rp._should_kill_on_exit(False, True), False)
    finally:
        rp._clear_browser_suspect()
    return ok


def test_staleness() -> bool:
    print("reaping idle browsers")
    ok = True
    ok &= _check("unused 10 min is still warm", rp._is_stale(1000, 1600, 45), False)
    ok &= _check("unused 60 min is stale", rp._is_stale(1000, 4600, 45), True)
    ok &= _check("no marker counts as stale", rp._is_stale(0, 4600, 45), True)
    ok &= _check("exactly at the TTL is not yet stale",
                 rp._is_stale(1000, 1000 + 45 * 60, 45), False)
    return ok


def test_cleared_browser_survives_the_night() -> bool:
    """A browser that got through Indeed's check must outlive the overnight gap;
    one that never did is cheap to replace and goes on the short TTL."""
    print("a cleared browser is kept across the night")
    ok = True
    t = 1_000_000.0
    night = 9 * 3600          # 10pm -> 7am, longer than the ordinary idle TTL
    ok &= _check("cleared browser survives the night",
                 rp._is_stale(t, t + night, cleared=True), False)
    ok &= _check("uncleared browser does not",
                 rp._is_stale(t, t + night, cleared=False), True)
    ok &= _check("even a cleared browser goes eventually",
                 rp._is_stale(t, t + (rp.KEEP_WARM_CLEARED_TTL_MIN + 1) * 60,
                              cleared=True), True)
    ok &= _check("the long TTL really does span a night",
                 rp.KEEP_WARM_CLEARED_TTL_MIN * 60 > night, True)
    return ok


def test_marker_round_trip() -> bool:
    print("the cleared flag survives a round trip")
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="rp-mark-"))
    orig, rp.CDP_PROFILE = rp.CDP_PROFILE, str(tmp)
    try:
        rp._touch_lastuse(cleared=True)
        ok &= _check("reads back as cleared", rp._read_lastuse()[1], True)
        rp._touch_lastuse(cleared=False)
        ok &= _check("and as not cleared", rp._read_lastuse()[1], False)
        # The marker predates the flag on any machine already running keep-warm.
        Path(rp._lastuse_path()).write_text("1790000000.0")
        ok &= _check("an old bare-epoch marker still parses",
                     rp._read_lastuse(), (1790000000.0, False))
        Path(rp._lastuse_path()).write_text("nonsense")
        ok &= _check("garbage reads as stale-and-uncleared",
                     rp._read_lastuse(), (0.0, False))
    finally:
        rp.CDP_PROFILE = orig
    return ok


def test_lastuse_marker() -> bool:
    print("the last-use marker")
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="rp-warm-"))
    orig, rp.CDP_PROFILE = rp.CDP_PROFILE, str(tmp)
    try:
        rp._touch_lastuse()
        p = Path(rp._lastuse_path())
        ok &= _check("marker written beside the profile", p.exists(), True)
        val, cleared = rp._read_lastuse()
        import time as _t
        ok &= _check("marker holds a recent timestamp",
                     abs(_t.time() - val) < 60, True)
        ok &= _check("a plain touch is not marked cleared", cleared, False)
        ok &= _check("a fresh marker is not stale",
                     rp._is_stale(val, _t.time(), 45), False)
    finally:
        rp.CDP_PROFILE = orig
    return ok


def test_reaper_skips_own_and_live() -> bool:
    """The reaper must never kill the office it is about to use, and must leave a
    recently-used browser alone."""
    print("the reaper's guard rails")
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="rp-reap-"))
    killed: list = []
    rows = {
        "A": {"office_id": "A", "cdp_profile": str(tmp / "a"),
              "cdp_port": "9401", "cdp_kill_pat": "prof_a"},
        "B": {"office_id": "B", "cdp_profile": str(tmp / "b"),
              "cdp_port": "9402", "cdp_kill_pat": "prof_b"},
    }
    for name in ("a", "b"):
        (tmp / name).mkdir()
    # 'A' is the office this run uses; 'B' is alive but last used an hour ago.
    (tmp / "b" / ".rp_lastuse").write_text("1")

    import subprocess as _sp
    import sys
    import types
    fake = types.ModuleType("automations.applicant_push.offices")
    fake.OFFICES = rows
    orig_mod = sys.modules.get("automations.applicant_push.offices")
    sys.modules["automations.applicant_push.offices"] = fake
    orig_profile, rp.CDP_PROFILE = rp.CDP_PROFILE, str(tmp / "a")
    orig_alive, rp._cdp_port_alive = rp._cdp_port_alive, lambda port=None, timeout=1.5: True
    orig_run, _sp.run = _sp.run, lambda *a, **k: killed.append(a[0]) or types.SimpleNamespace(returncode=0)
    orig_log, rp._log = rp._log, lambda *a, **k: None
    try:
        n = rp.reap_stale_warm_browsers()
        ok &= _check("one stale browser reaped", n, 1)
        ok &= _check("it was B's, not our own A's",
                     [c for c in killed if "prof_b" in c], [["pkill", "-f", "prof_b"]])
        ok &= _check("our own office was never killed",
                     any("prof_a" in c for c in killed), False)
    finally:
        rp.CDP_PROFILE = orig_profile
        rp._cdp_port_alive = orig_alive
        _sp.run = orig_run
        rp._log = orig_log
        if orig_mod is not None:
            sys.modules["automations.applicant_push.offices"] = orig_mod
        else:
            sys.modules.pop("automations.applicant_push.offices", None)
    return ok


def main() -> int:
    print("keep-warm browser\n")
    results = [test_reuse_decision(), test_kill_decision(), test_staleness(),
               test_cleared_browser_survives_the_night(),
               test_marker_round_trip(),
               test_lastuse_marker(), test_reaper_skips_own_and_live()]
    print("\n" + ("ALL OK" if all(results) else "FAILURES ABOVE"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
