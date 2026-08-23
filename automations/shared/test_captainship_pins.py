"""NOT_IN_SOURCE — the expected-absence half of the pin list (2026-08-23).

`detect_went_dark` flags a rep with recent history on the tab who is missing
from today's pull. That is right for a rep dropped from a Tableau filter and
wrong for a rep who simply sells nothing that source measures: their blanks
match the source, but the flag re-fires every morning until their last numbers
age out of the ~6-day recent window — holding the report INCOMPLETE and, since
the partial-send rule, holding that captain's draft back from the send.

These pin the two things that make the suppression safe to have at all:

  (a) it is keyed by the FULL report slug, so silencing a rep on a captain's
      NEW INTERNET tab does NOT silence them on his WIRELESS one — where the
      same two reps do fill, and a real disappearance must still page;
  (b) it never touches anybody else's finding, and a map that empties out
      returns {} so the run reads CLEAN instead of INCOMPLETE.

Run:  python -m automations.shared.test_captainship_pins   (or via pytest)
"""
from __future__ import annotations

from automations.shared import captainship_pins as pins


def test_expected_absence_clears_the_finding():
    """Tony's NI tab: both reps hushed, nothing left -> clean, not INCOMPLETE."""
    wd = {"0-30": ["Kobe Cireus", "Melik El Jaiez"],
          "90": ["Melik El Jaiez"]}
    assert pins.drop_expected_absent(wd, "tony") == {}


def test_a_real_finding_on_the_same_tab_survives():
    """Suppressing the known two must not swallow a third rep going dark."""
    wd = {"0-30": ["Kobe Cireus", "Someone Else"]}
    assert pins.drop_expected_absent(wd, "tony") == {"0-30": ["Someone Else"]}


def test_wireless_tab_is_a_different_source():
    """'-wl' is NOT stripped: they fill on the wireless tab, so a dark reading
    there is real and has to keep paging."""
    wd = {"0-30": ["Kobe Cireus"]}
    assert pins.drop_expected_absent(wd, "tony-wl") == wd
    assert pins.absent_ok("tony-wl") == ()


def test_other_captains_are_untouched():
    wd = {"0-30": ["Kobe Cireus"]}
    assert pins.drop_expected_absent(wd, "wayne") == wd


def test_matching_ignores_case_and_spacing():
    """The Tableau spelling of the day can't slip past the list."""
    wd = {"0-30": ["  kobe   cireus "]}
    assert pins.drop_expected_absent(wd, "TONY") == {}


def test_not_in_source_is_not_not_on_team():
    """The two lists must stay separate: these reps ARE on Tony's captainship,
    so their numbers must still reach every other tab of his."""
    assert pins.names_for("tony") == ()
    assert not pins.is_pinned("tony", "Kobe Cireus")


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
