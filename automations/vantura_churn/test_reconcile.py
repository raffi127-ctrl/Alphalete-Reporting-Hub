"""The stale-CHURNRATES rescue in the Vantura churn reconciliation gate.

Pinned from the real 2026-08-25 failure. The 0-30 window drops the accounts
posted 31 days ago every morning, and that cohort is the mature end of the
list — it carries far more than its share of the disconnects. So when
CHURNRATES hasn't rolled its window forward yet, the dashboard reads HIGHER
than we do, the churn rate misses the 0.5pp band, and the gate blocks a write
whose numbers were right all along.

That day, CARLOS computed 22/383 = 5.74% against a dashboard reading 391 and
6.40%. The three "missing" disconnects were NORBERTO P (Air), Baibhav G and
Rajendra J (Internet) — all posted 7/25, all at the top of the tab's own
roll-off helper the day before. Re-summarised against YESTERDAY's cutoff the
same Order Log gives 25/389 = 6.43% vs the dashboard's 6.40%.

What these pin:
  (a) that shape passes, and what gets WRITTEN is today's fresh number;
  (b) a real structural break (wrong owner, a dropped product type, a
      truncated pull) is NOT rescued — a one-day shift can't close those;
  (c) a dashboard two or more days behind still FAILS, with the reason named,
      because that is a CHURNRATES problem nobody should sleep through.

Run:  python -m automations.vantura_churn.test_reconcile   (or via pytest)
"""
from __future__ import annotations

from automations.vantura_churn import run as vc


def _s(disc: int, base: int) -> dict:
    """Minimal churn_summary shape — only the totals the gate reads."""
    return {"disc_total": disc, "base_total": base}


def _quiet(*_a):
    pass


def test_stale_dashboard_passes_and_today_is_what_stands():
    """2026-08-25, CARLOS. Today misses by 0.66pp; yesterday reconciles."""
    today = _s(22, 383)
    dash = {"base": 391, "rate": 0.0640, "raw": {}}
    # Today's window alone -> the failure that actually fired.
    assert vc._compare("CARLOS", today, dash, _quiet)
    # With yesterday's window offered, the gate clears.
    assert vc._reconcile("CARLOS", today, dash, _quiet,
                         prev_summary=_s(25, 389),
                         prev2_summary=_s(27, 395)) == []


def test_atef_and_jamis_still_pass_on_their_own():
    """The two offices that reconciled that morning must not need the rescue."""
    assert vc._reconcile("ATEF", _s(21, 791),
                         {"base": 827, "rate": 0.0290, "raw": {}}, _quiet) == []
    assert vc._reconcile("JAMIS", _s(16, 366),
                         {"base": 374, "rate": 0.0430, "raw": {}}, _quiet) == []


def test_a_dropped_product_type_is_not_rescued():
    """PRODUCT_MAP stops matching 'WIRELESS' — 336 of Carlos's 383 units and 18
    of his 22 disconnects vanish. Shifting the window a day moves a handful of
    records; it cannot move that."""
    broken = _s(4, 47)            # Carlos with only Air + Internet left
    dash = {"base": 391, "rate": 0.0640, "raw": {}}
    problems = vc._reconcile("CARLOS", broken, dash, _quiet,
                             prev_summary=_s(7, 53),
                             prev2_summary=_s(9, 59))
    assert problems, "a structural break must still fail"


def test_wrong_owner_is_not_rescued():
    """A pull that came back as somebody else — base off by most of itself."""
    problems = vc._reconcile("CARLOS", _s(6, 120),
                             {"base": 391, "rate": 0.0640, "raw": {}}, _quiet,
                             prev_summary=_s(7, 124),
                             prev2_summary=_s(8, 128))
    assert problems


def test_two_days_behind_fails_and_says_why():
    """D-2 is diagnosed, never tolerated: that is CHURNRATES, not us."""
    problems = vc._reconcile("CARLOS", _s(19, 377),
                             {"base": 391, "rate": 0.0640, "raw": {}}, _quiet,
                             prev_summary=_s(21, 381),
                             prev2_summary=_s(25, 389))
    assert problems
    assert any("2 days behind" in p or "≥2 days behind" in p
               for p in problems), problems


def test_no_prev_summary_behaves_exactly_as_before():
    """--skip-reconcile paths and old callers keep the original verdict."""
    dash = {"base": 391, "rate": 0.0640, "raw": {}}
    assert vc._reconcile("CARLOS", _s(22, 383), dash, _quiet) == \
        vc._compare("CARLOS", _s(22, 383), dash, _quiet)


def test_unreadable_dashboard_cell_still_fails():
    """No numbers at all is not a staleness question — it stays a problem."""
    dash = {"base": None, "rate": None, "raw": {"Churn Rate": "%null%"}}
    assert vc._reconcile("CARLOS", _s(22, 383), dash, _quiet,
                         prev_summary=_s(25, 389))


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
