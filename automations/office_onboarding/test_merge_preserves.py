"""`apply` regenerating a registry must not eat what the FORM can't express.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.office_onboarding.test_merge_preserves

WHAT THIS GUARDS (2026-09-05). `_merge_json` said "merge" and did
`existing[key] = row` — a whole-record overwrite. `_office_row` rebuilds every
field from the 'Office Onboarding' submission, and `per_office_views` is empty
for any office that didn't enrol a bespoke view URL, which is nearly all of
them. So a hand-authored view override survived exactly until the next
enrolment ran `apply`.

The live cost: Jamis's three B2B churn sections were pointed at ALLTEAMWireless
on 2026-09-04 (c10f46e) because the shared team view returns nothing for his
Owner & Office. At 17:30 that evening an unrelated enrolment auto-committed
(305719c) and reset him — and Sabrina — to `per_office_views: {}`. The next
morning b2b_metrics dropped `jamis: churn_wireless / churn_int / churn_air`
again, and the channel read it as the same bug coming back rather than as a
fix being deleted.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automations.office_onboarding import apply


def _row(key, **over):
    row = {
        "key": key,
        "label": "Jamis's B2B Office",
        "channel_name": "Jamis-leaders",
        "per_office_views": {},
        "enrolled_reports": ["b2b_sales"],
        "notes": "",
    }
    row.update(over)
    return row


class MergePreservesHandTuning(unittest.TestCase):
    def _merge(self, existing, rows):
        # Under REPO_ROOT: the summary line _merge_json returns calls
        # path.relative_to(REPO_ROOT), which raises for a /tmp path.
        with tempfile.TemporaryDirectory(dir=apply.REPO_ROOT) as d:
            p = Path(d) / "onboarded_offices.json"
            p.write_text(json.dumps(existing))
            apply._merge_json(p, rows, write=True)
            return {r["key"]: r for r in json.loads(p.read_text())}

    def test_regenerated_empty_views_do_not_wipe_an_override(self):
        """The exact 305719c regression: {} must not beat three live URLs."""
        views = {"b2b_churn_wireless": "https://tableau/…WIRELESS",
                 "b2b_churn_int": "https://tableau/…NEW%20INTERNET",
                 "b2b_churn_air": "https://tableau/…AIR%2FAWB"}
        out = self._merge([_row("jamis", per_office_views=views)],
                          [_row("jamis")])
        self.assertEqual(out["jamis"]["per_office_views"], views)

    def test_the_form_still_wins_when_it_actually_says_something(self):
        """Preserving must not freeze the registry: a real submitted change —
        a renamed channel, a re-pointed view — has to apply."""
        out = self._merge(
            [_row("jamis", channel_name="#old",
                  per_office_views={"b2b_churn_air": "https://old"})],
            [_row("jamis", channel_name="#new",
                  per_office_views={"b2b_churn_air": "https://new"})])
        self.assertEqual(out["jamis"]["channel_name"], "#new")
        self.assertEqual(out["jamis"]["per_office_views"],
                         {"b2b_churn_air": "https://new"})

    def test_a_brand_new_office_is_written_whole(self):
        out = self._merge([_row("jamis")], [_row("sabrina")])
        self.assertEqual(sorted(out), ["jamis", "sabrina"])

    def test_other_offices_are_untouched(self):
        views = {"b2b_churn_air": "https://tableau/…AIR%2FAWB"}
        out = self._merge(
            [_row("jamis", per_office_views=views), _row("sabrina")],
            [_row("sabrina", channel_name="#moved")])
        self.assertEqual(out["jamis"]["per_office_views"], views)
        self.assertEqual(out["sabrina"]["channel_name"], "#moved")


if __name__ == "__main__":
    unittest.main()
