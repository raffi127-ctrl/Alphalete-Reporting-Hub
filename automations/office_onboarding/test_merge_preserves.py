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


class OwnerOfficeKeepsItsTableauShape(unittest.TestCase):
    """The other half of the same 2026-09-04 revert, closed 2026-09-14.

    The empty-value guard above stopped the form's `{}` from eating a view
    override. It did nothing for a WRONG non-empty value, and the docstring
    said so: Sabrina's `owner_office` came off the form as "Sabrina Alicea
    Alisei Inc." while Tableau spells it "SABRINA ALICEA [alisei, inc.]", and
    the fix "needs re-correcting after a submission".

    Nobody re-corrected it. The un-matchable value sat in the committed JSON
    for ten days and only surfaced when `test_no_data_yet` began failing on it
    — ten days of `_slice_is_plausible` calling every one of her Owner & Office
    sections a misconfiguration, which was true and unread.
    """

    _merge = MergePreservesHandTuning._merge

    TABLEAU = "SABRINA ALICEA [alisei, inc.]"
    FORM = "Sabrina Alicea Alisei Inc."

    def test_the_forms_unbracketed_value_does_not_win(self):
        out = self._merge([_row("sabrina", owner_office=self.TABLEAU)],
                          [_row("sabrina", owner_office=self.FORM)])
        self.assertEqual(out["sabrina"]["owner_office"], self.TABLEAU)

    def test_a_real_renamed_office_still_applies(self):
        """Both shaped = the form is saying something real. It must win, or the
        registry freezes and a genuine rename can never land."""
        new = "SABRINA ALICEA [alisei holdings, inc.]"
        out = self._merge([_row("sabrina", owner_office=self.TABLEAU)],
                          [_row("sabrina", owner_office=new)])
        self.assertEqual(out["sabrina"]["owner_office"], new)

    def test_a_first_submission_is_taken_as_is(self):
        """A brand-new office has nothing stored to protect — the form's value
        is all there is, shaped or not. `_slice_is_plausible` is what catches a
        bad one on its first morning, loudly."""
        out = self._merge([], [_row("sabrina", owner_office=self.FORM)])
        self.assertEqual(out["sabrina"]["owner_office"], self.FORM)

    def test_an_unshaped_stored_value_is_not_protected(self):
        """Protecting a bad stored value would make it permanent."""
        out = self._merge([_row("sabrina", owner_office=self.FORM)],
                          [_row("sabrina", owner_office=self.TABLEAU)])
        self.assertEqual(out["sabrina"]["owner_office"], self.TABLEAU)

    def test_the_refusal_is_reported_not_swallowed(self):
        """A silent refusal is how the last one cost ten days — the summary has
        to name the field so whoever ran `apply` goes and fixes the form."""
        with tempfile.TemporaryDirectory(dir=apply.REPO_ROOT) as d:
            p = Path(d) / "onboarded_offices.json"
            p.write_text(json.dumps([_row("sabrina",
                                          owner_office=self.TABLEAU)]))
            summary = apply._merge_json(
                p, [_row("sabrina", owner_office=self.FORM)], write=True)
        self.assertIn("sabrina.owner_office", summary)
        self.assertIn("Office Onboarding", summary)

    def test_only_owner_office_is_judged(self):
        """The shape rule is about Tableau's Owner & Office field. A label or a
        note has no brackets and must merge normally."""
        out = self._merge([_row("sabrina", label="A [bracketed] label")],
                          [_row("sabrina", label="plain label")])
        self.assertEqual(out["sabrina"]["label"], "plain label")


class LiveRegistryIsSliceable(unittest.TestCase):
    """The committed file itself, not a fixture — the bad value was IN it."""

    def test_every_onboarded_owner_office_is_tableau_shaped(self):
        rows = json.loads(
            (apply.REPO_ROOT / "automations" / "b2b_metrics"
             / "onboarded_offices.json").read_text())
        for r in rows:
            value = (r.get("owner_office") or "").strip()
            if not value:
                continue        # blank is a different case (an AS-IS override)
            self.assertTrue("[" in value and "]" in value,
                            "{}: {!r} can never match Tableau's "
                            "'NAME [office]'".format(r.get("key"), value))


if __name__ == "__main__":
    unittest.main()
