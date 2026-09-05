"""The enrollment auto-commit must never push away a value somebody put there.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tracker_onboarding.test_deletion_guard

WHAT THIS GUARDS (2026-09-05). On 2026-09-04 Jamis's and Sabrina's B2B churn
view URLs were hand-authored into b2b_metrics/onboarded_offices.json, because
the shared team view returns nothing for their Owner & Office. At 17:30 an
unrelated enrollment ran this job; `office_onboarding.apply` regenerated both
offices with `per_office_views: {}` (the onboarding form has no column for
those URLs) and the auto-commit pushed the erasure to main under the same
generic message it uses for everything:

    enrollments: auto-commit confirmed offices
    - regenerated from the Tracker Onboarding + Office Onboarding tabs

Next morning b2b_metrics dropped jamis: churn_wireless / churn_int / churn_air,
and it read as the bug returning rather than as a fix being deleted.

`apply._merge_json` was fixed to merge rather than overwrite, which closes that
specific hole. This guard closes the class: a regeneration that REMOVES a
non-empty value stops before the commit, and the message names what changed.
"""
from __future__ import annotations

import json
import unittest

from automations.tracker_onboarding import auto_commit as ac


URLS = {
    "b2b_churn_wireless": "https://tableau/…WIRELESS",
    "b2b_churn_int": "https://tableau/…NEW%20INTERNET",
    "b2b_churn_air": "https://tableau/…AIR%2FAWB",
}


def _office(key, **over):
    o = {"key": key, "report_id": f"{key}_metrics", "label": f"{key}'s office",
         "channel_name": f"#{key}", "owner_office": f"{key.upper()} [inc.]",
         "per_office_views": dict(URLS), "notes": ""}
    o.update(over)
    return o


def _changes(before, after):
    return ac.registry_changes(json.dumps(before), json.dumps(after))


class TheLiveRegression(unittest.TestCase):
    """The exact 305719c shape: three URLs -> {} on two offices at once."""

    def test_emptying_per_office_views_is_a_deletion(self):
        d = _changes([_office("jamis"), _office("sabrina")],
                     [_office("jamis", per_office_views={}),
                      _office("sabrina", per_office_views={})])
        self.assertEqual(sorted(d["deleted"]),
                         ["jamis.per_office_views", "sabrina.per_office_views"])

    def test_it_is_reported_per_office_not_per_url(self):
        """The whole dict going empty is ONE deletion to read, not three."""
        d = _changes([_office("jamis")], [_office("jamis", per_office_views={})])
        self.assertEqual(d["deleted"], ["jamis.per_office_views"])

    def test_dropping_one_url_of_three_is_still_caught(self):
        fewer = {k: v for k, v in URLS.items() if k != "b2b_churn_air"}
        d = _changes([_office("jamis")],
                     [_office("jamis", per_office_views=fewer)])
        self.assertEqual(d["deleted"],
                         ["jamis.per_office_views.b2b_churn_air"])


class OrdinaryTrafficIsNotBlocked(unittest.TestCase):
    def test_a_new_office_is_an_addition(self):
        d = _changes([_office("jamis")], [_office("jamis"), _office("sabrina")])
        self.assertEqual(d["deleted"], [])
        self.assertEqual(d["added"], ["sabrina"])

    def test_editing_a_value_is_a_change_not_a_deletion(self):
        d = _changes([_office("jamis")],
                     [_office("jamis", channel_name="#renamed")])
        self.assertEqual(d["deleted"], [])
        self.assertEqual(d["changed"], ["jamis.channel_name"])

    def test_reordering_offices_is_not_a_deletion(self):
        """Records are matched on their own id — a list compared positionally
        would read a re-order as a mass wipe."""
        a, b = _office("jamis"), _office("sabrina")
        d = _changes([a, b], [b, a])
        self.assertEqual((d["deleted"], d["added"], d["changed"]), ([], [], []))

    def test_turning_an_office_off_is_not_a_deletion(self):
        """`on_scheduler: false` is the documented off switch; False is falsy
        but it is a real value."""
        d = _changes({"reports": {"x": {"on_scheduler": True}}},
                     {"reports": {"x": {"on_scheduler": False}}})
        self.assertEqual(d["deleted"], [])
        self.assertEqual(d["changed"], ["reports.x.on_scheduler"])

    def test_a_field_that_was_already_empty_is_not_a_deletion(self):
        d = _changes([_office("jamis", notes="")],
                     [_office("jamis", notes="")])
        self.assertEqual(d["deleted"], [])

    def test_filling_a_previously_empty_field_is_an_addition(self):
        d = _changes([_office("jamis", notes="")],
                     [_office("jamis", notes="now says something")])
        self.assertEqual(d["added"], ["jamis.notes"])


class RemovingAWholeOffice(unittest.TestCase):
    def test_it_blocks(self):
        d = _changes([_office("jamis"), _office("sabrina")], [_office("jamis")])
        self.assertEqual(d["deleted"], ["sabrina"])


class FileLevelEdgeCases(unittest.TestCase):
    def test_a_brand_new_file_has_nothing_to_delete(self):
        d = ac.registry_changes("", json.dumps([_office("jamis")]))
        self.assertEqual(d["deleted"], [])
        self.assertEqual(d["note"], "new file")

    def test_unparseable_new_content_blocks(self):
        d = ac.registry_changes(json.dumps([_office("jamis")]), "{not json")
        self.assertTrue(d["deleted"])

    def test_unparseable_old_content_degrades_to_allow(self):
        """Can't compare — never worse than the behaviour before this guard."""
        d = ac.registry_changes("{not json", json.dumps([_office("jamis")]))
        self.assertEqual(d["deleted"], [])
        self.assertIn("did not parse", d["note"])


class TheCommitMessageNamesWhatChanged(unittest.TestCase):
    """The old message was three generic lines whether this job added an office
    or removed six URLs, so `git log -p` on the file read as routine."""

    def test_a_deletion_is_named(self):
        d = _changes([_office("jamis")], [_office("jamis", per_office_views={})])
        line = ac._summarize("automations/b2b_metrics/onboarded_offices.json", d)
        self.assertIn("onboarded_offices.json", line)
        self.assertIn("-jamis.per_office_views", line)

    def test_adds_and_edits_are_named(self):
        d = _changes([_office("jamis")],
                     [_office("jamis", channel_name="#new"), _office("sabrina")])
        line = ac._summarize("x/onboarded_offices.json", d)
        self.assertIn("+sabrina", line)
        self.assertIn("~jamis.channel_name", line)

    def test_a_long_list_is_truncated_not_dumped(self):
        before = {f"k{i}": "v" for i in range(50)}
        before["kept"] = "v"          # so the container isn't itself emptied
        d = _changes(before, {"kept": "v"})
        line = ac._summarize("x.json", d)
        self.assertEqual(len(d["deleted"]), 50)
        self.assertIn("more", line)
        self.assertLess(len(line), 300)


class Helpers(unittest.TestCase):
    def test_is_empty_leaves_zero_and_false_alone(self):
        for v in (0, False, 0.0):
            self.assertFalse(ac._is_empty(v), v)
        for v in (None, "", {}, []):
            self.assertTrue(ac._is_empty(v), v)

    def test_keyed_needs_unique_non_empty_ids(self):
        self.assertIsNone(ac._keyed([{"key": "a"}, {"key": "a"}]))
        self.assertIsNone(ac._keyed([{"key": ""}, {"key": "b"}]))
        self.assertIsNone(ac._keyed(["not", "dicts"]))
        self.assertEqual(sorted(ac._keyed([{"key": "a"}, {"key": "b"}])),
                         ["a", "b"])

    def test_the_real_registry_is_keyable(self):
        """If the shipped file ever stops being a keyed list, the guard would
        silently fall back to positional compare — catch that here."""
        import pathlib
        p = (pathlib.Path(ac.REPO_ROOT)
             / "automations" / "b2b_metrics" / "onboarded_offices.json")
        self.assertIsNotNone(ac._keyed(json.loads(p.read_text())))


if __name__ == "__main__":
    unittest.main()
