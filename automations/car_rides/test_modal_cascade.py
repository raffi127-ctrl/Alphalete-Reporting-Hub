"""One failed edit must not fail every edit behind it.

2026-09-24, the 10:30 pass: `rodolfo` timed out waiting for the select2 search
box, apply_edit returned False with the Edit Layer modal still open, and the
seven territories after it all died on "<div id=territoryModal> intercepts
pointer events". 8 flags, 0 edits applied. The manifest is what made it
visible — those flags exit 3, which the wrapper publishes as `success`.

    python -m unittest automations.car_rides.test_modal_cascade -v
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.car_rides import run


class FakePage:
    """A page whose modal closes after `closes_after` dismiss attempts."""

    def __init__(self, open_now=True, closes_after=1):
        self.open = open_now
        self.left = closes_after
        self.keys: list[str] = []
        self.clicked: list[str] = []

    # --- the surface apply_edit / _dismiss_modal touch ---
    class _Keyboard:
        def __init__(self, page):
            self.page = page

        def press(self, key):
            self.page.keys.append(key)
            self.page._attempt()

    @property
    def keyboard(self):
        return FakePage._Keyboard(self)

    def _attempt(self):
        self.left -= 1
        if self.left <= 0:
            self.open = False

    def locator(self, sel):
        page = self

        class _Loc:
            first = None

            def click(self, timeout=None):
                page.clicked.append(sel)
                page._attempt()

        loc = _Loc()
        loc.first = loc
        return loc

    def wait_for_timeout(self, _ms):
        pass


class DismissModalTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(run, "_modal_open",
                                  side_effect=lambda p: p.open)
        patch.start()
        self.addCleanup(patch.stop)

    def test_nothing_open_is_free(self):
        p = FakePage(open_now=False)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.keys, [])

    def test_escape_closes_it(self):
        p = FakePage(closes_after=1)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.keys, ["Escape"])

    def test_a_select2_swallows_the_first_escape(self):
        """Inside an open select2 the first Escape closes the DROPDOWN and the
        modal stays put — which is why the second press exists."""
        p = FakePage(closes_after=2)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.keys, ["Escape", "Escape"])

    def test_it_falls_back_to_the_close_control(self):
        p = FakePage(closes_after=3)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.clicked, [run._MODAL_CLOSE])

    def test_a_stuck_modal_is_reported_not_hidden(self):
        said = []
        p = FakePage(closes_after=99)
        self.assertFalse(run._dismiss_modal(p, log=said.append))
        self.assertIn("will not close", said[0])

    def test_the_close_control_never_reaches_the_page_behind_it(self):
        """A miss here would click a territory row underneath the modal."""
        self.assertNotIn(":not(", run._MODAL_CLOSE)
        for part in run._MODAL_CLOSE.split(","):
            self.assertTrue(part.strip().startswith(".modal"), part)


class ApplyEditLeavesThePageClean(unittest.TestCase):
    """The three places a leftover modal used to poison the next territory."""

    def _source(self):
        import inspect
        return inspect.getsource(run.apply_edit)

    def test_it_clears_a_leftover_before_clicking_a_row(self):
        head = self._source().split("try:")[0]
        self.assertIn("_dismiss_modal", head)

    def test_both_failure_paths_dismiss(self):
        src = self._source()
        tails = [b for b in src.split("except Exception as e:")[1:]]
        self.assertEqual(len(tails), 2)
        for t in tails:
            self.assertIn("_dismiss_modal", t.split("return False")[0])


if __name__ == "__main__":
    unittest.main()


class TheSearchBoxIsATextarea(unittest.TestCase):
    """THE TWO-MONTH OUTAGE (2026-09-24). OwnerVille runs select2 4.1, whose
    MULTI-select search box is `<textarea class="select2-search__field">`. This
    module looked for `input.select2-search__field`, which can never match it,
    so every edit carrying an `add` burned 30s and threw — while remove-only
    edits, which never touch that box, went through. 519 runs since 2026-07-16,
    46 edits applied, every one of them remove-only.

    Probed live on Lucy 2 before the fix: `.select2-search__field` resolves to
    TEXTAREA, and #territoryModal holds THREE of them (Assigned Sales Rep(s),
    Car Ride Captain, Guest Pass Rep(s) — the last one disabled).
    """

    def test_the_search_box_is_matched_by_class_not_tag(self):
        self.assertEqual(run.SEARCH_FIELD, ".select2-search__field")
        for tag in ("input", "textarea"):
            self.assertFalse(run.SEARCH_FIELD.startswith(tag),
                             "a tag prefix breaks on the next select2 bump")

    def test_no_input_only_selector_survives_in_the_edit_path(self):
        import inspect
        src = inspect.getsource(run.apply_edit)
        self.assertNotIn("input.select2-search__field", src)
        self.assertNotIn(".select2-search input", src)

    def test_every_field_locator_is_scoped_to_assigned_sales_reps(self):
        """Three multi-selects share these class names. An unscoped `.first`
        could strip a Car Ride Captain chip instead of a rider."""
        self.assertIn("select.territoryAssignedUsers", run.ASSIGNED_REPS)
        import inspect
        src = inspect.getsource(run.apply_edit)
        body = src[src.index("ctr = page.locator"):]
        for unscoped in ("page.locator(\n                f\"li.select2-selection__choice",
                         "page.locator(f\"li.select2-selection__choice"):
            self.assertNotIn(unscoped, body)
        self.assertIn("ctr.locator(", body)

    def test_the_dropdown_is_read_from_the_open_container(self):
        """select2 appends its results to <body>, not inside the modal."""
        import inspect
        self.assertIn(".select2-container--open .select2-results__option",
                      inspect.getsource(run.apply_edit))

    def test_an_ambiguous_name_flags_instead_of_adding_someone(self):
        """Two Andrews on the roster used to mean adding whichever the list put
        on top — to a car ride, silently."""
        import inspect
        src = inspect.getsource(run.apply_edit)
        self.assertIn("_pick_option(rep, texts)", src)
        self.assertIn("refusing to guess", src)
        self.assertIn("len(hits) != 1", src)


class PickingTheRightPerson(unittest.TestCase):
    """_pick_option, on the names that actually came out of OwnerVille."""

    # The exact list the 12:27 live run saw when it typed "Michelle".
    FLORES = ["Kandice Michelle Flores", "Michelle Flores"]

    def test_the_exact_name_wins_over_a_longer_one_containing_it(self):
        """The first live add flagged this instead of guessing — right call,
        wrong question: one of the two IS the exact person."""
        self.assertEqual(run._pick_option("Michelle Flores", self.FLORES), [1])

    def test_the_longer_name_still_picks_itself(self):
        self.assertEqual(
            run._pick_option("Kandice Michelle Flores", self.FLORES), [0])

    def test_a_middle_name_on_ownervilles_side_is_the_same_person(self):
        opts = ["Gavin Dimitri Natividad", "Eduardo Alvarez"]
        self.assertEqual(run._pick_option("Gavin Natividad", opts), [0])

    def test_two_people_sharing_a_surname_are_not_one_person(self):
        opts = ["Ruby Flores", "Janel Fernandez"]
        self.assertEqual(run._pick_option("Flores", opts), [0])
        self.assertEqual(len(run._pick_option("Aaron De La Torre",
                                              ["Aaron De La Torre",
                                               "Andrew De La Torre"])), 1)

    def test_a_real_tie_still_refuses(self):
        self.assertEqual(len(run._pick_option("Andrew", ["Andrew De La Torre",
                                                         "Andrew Smith"])), 2)

    def test_nobody_matching_is_not_a_match(self):
        self.assertEqual(run._pick_option("Nobody Here", self.FLORES), [])

    def test_a_high_confidence_tie_does_not_fall_through_to_a_looser_rung(self):
        """A looser rung can only widen a tie, never resolve it."""
        opts = ["Chris Vela", "Chris Vela"]
        self.assertEqual(len(run._pick_option("Chris Vela", opts)), 2)


class ARemoveIsIdempotent(unittest.TestCase):
    """2026-09-24, the 12:34 live pass: its ONLY failure was the plan removing
    the same rep from the same territory twice — the leader edit took
    'Eduardo A.' off `andrew`, then the one-rep-one-car-ride edit spent 30s
    hunting a chip that was already gone. Nothing was wrong."""

    def test_the_planner_does_not_schedule_it_twice(self):
        expected = {"Andrew De La Torre": ["Danniel Alvarenga"],
                    "Nick Smedra": ["Eduardo Alvarez"]}
        terrs = [{"name": "andrew",
                  "reps": ["Andrew De La Torre", "Eduardo Alvarez"]}]
        plan = run.plan_campaign(expected, terrs, [], log=lambda m: None)
        removes = [r for e in plan["edits"] if e["territory"] == "andrew"
                   for r in e.get("remove", [])]
        self.assertEqual(len(removes), len(set(removes)), removes)

    def test_a_chip_that_is_already_gone_is_not_a_failure(self):
        import inspect
        src = inspect.getsource(run.apply_edit)
        body = src[src.index("for rep in edit.get(\"remove\""):]
        self.assertIn("chip.count() == 0", body)
        self.assertIn("continue", body.split("already gone")[1][:200])

    def test_the_remove_click_cannot_burn_the_full_default_timeout(self):
        import inspect
        src = inspect.getsource(run.apply_edit)
        self.assertIn("timeout=10_000", src)
