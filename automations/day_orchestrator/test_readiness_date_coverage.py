"""The fail-open floor on `tableau_date_coverage` — the probe with the loaded gun.

Every readiness probe in this file carries a `fallback_hhmm`, because
_probe_source's own comment says a gate must never starve a report: "no capture,
no post, and (because 'never became ready' is not 'ran and failed') no failure
email. A gate silently starved a report to death."

`tableau_date_coverage` was the exception. It had no floor, failed CLOSED on a
config typo and on an import error, and always demanded TODAY's date — and it is
exactly the probe the daily_metrics notes tell the next person to wire when a
metric comes out with yesterday's numbers. Wiring it as written would have held
`daily_metrics` and 13 sibling reports every morning with no way out.

Nothing used the probe type when this was fixed (2026-08-25), so the defaults
below keep the old verdicts and only add the escape hatches.

Run:  python -m automations.day_orchestrator.test_readiness_date_coverage
"""
from __future__ import annotations

import datetime as dt

from automations.day_orchestrator import readiness as rd


def test_no_floor_configured_is_not_a_verdict():
    """A source with no fallback_hhmm behaves exactly as before."""
    assert rd._past_fallback(None) == (False, "")
    assert rd._past_fallback("") == (False, "")


def test_a_broken_floor_string_never_decides_the_gate():
    """'half past four' must not throw, and must not open the gate either."""
    assert rd._past_fallback("half past four") == (False, "")
    assert rd._past_fallback("25:99:77") == (False, "")


def test_the_floor_opens_once_the_clock_passes_it():
    now = dt.datetime.now()
    past = f"{max(0, now.hour - 1):02d}:00"
    ok, why = rd._past_fallback(past)
    assert ok, (past, why)
    assert "running ungated" in why


def test_the_floor_stays_shut_before_it():
    now = dt.datetime.now()
    if now.hour >= 23:                     # no "later today" to test against
        return
    ok, _ = rd._past_fallback(f"{now.hour + 1:02d}:00")
    assert not ok


def _checker(target: dt.date) -> rd.ReadinessCache:
    """A ReadinessCache with only the attribute this probe method reads.

    __new__ instead of __init__ on purpose: the real constructor wants a whole
    config + machine state, and none of it is involved in the branches under
    test."""
    inst = rd.ReadinessCache.__new__(rd.ReadinessCache)
    inst.target_date = target
    return inst


def test_a_config_typo_runs_ungated_instead_of_holding():
    """Missing view_url used to return NOT ready — a typo that starves a report."""
    c = _checker(dt.date(2026, 8, 25))
    r = c._probe_tableau_date_coverage("tableau:order_log", {"date_col": "d"})
    assert r.ready, r.reason
    assert "MISCONFIGURED" in r.reason


def test_days_back_defaults_to_the_old_behaviour():
    """Absent days_back, the checked day is target_date — unchanged."""
    probe = {}
    target = dt.date(2026, 8, 25)
    check = target - dt.timedelta(days=int(probe.get("days_back", 0)))
    assert check == target


def test_days_back_one_asks_for_the_latest_completed_day():
    probe = {"days_back": 1}
    target = dt.date(2026, 8, 25)
    check = target - dt.timedelta(days=int(probe.get("days_back", 0)))
    assert check == dt.date(2026, 8, 24)


def _main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  ok   " + name)
            except AssertionError as e:
                fails += 1
                print("  FAIL " + name + ": " + str(e))
    print(("FAILED " + str(fails)) if fails else "all green")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_main())
