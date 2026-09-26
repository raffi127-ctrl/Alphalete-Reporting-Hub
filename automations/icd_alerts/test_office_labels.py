"""An office's owner and label as a reader sees them.

Both came off the self-serve sign-up form as free text, and both went wrong in
ways nothing complained about:

  * Carlos typed his name all lowercase, so "carlos hidalgo — carlos's Local
    Office" is what the Hub card, the invite listing and every Slack line built
    from `label` said.
  * He runs TWO offices (B2B AT&T and B2B Box) under one first name, so the
    derived label was identical for both. The roster printed the same entry
    twice with nothing to tell them apart -- and one of them being stalled
    while the other is fine is exactly when a reader needs to know which is
    which.

Neither is cosmetic once a line says "no board from Carlos's Local Office".

    .venv/bin/python -m unittest automations.icd_alerts.test_office_labels
"""
from __future__ import annotations

import unittest

from automations.icd_alerts import offices as O


def _off(key, owner, label, campaign="att", active=True):
    return O.AlertOffice(key=key, owner=owner, label=label, channels=(),
                         timezone="America/Chicago", active=active,
                         campaign=campaign)


class CasingOnlyWhereTheTypingSaysNothing(unittest.TestCase):
    def test_all_lowercase_gets_title_cased(self):
        self.assertEqual(O.typed_name("carlos hidalgo"), "Carlos Hidalgo")

    def test_all_uppercase_too(self):
        self.assertEqual(O.typed_name("CARLOS HIDALGO"), "Carlos Hidalgo")

    def test_deliberate_casing_is_never_touched(self):
        # .title() would wreck both of these, and this roster holds both.
        self.assertEqual(O.typed_name("Ryan McSpadden"), "Ryan McSpadden")
        self.assertEqual(O.typed_name("Aya Al-Khafaji"), "Aya Al-Khafaji")
        self.assertEqual(O.typed_name("Roshan Amin Ahmad"),
                         "Roshan Amin Ahmad")

    def test_blank_and_junk_are_safe(self):
        self.assertEqual(O.typed_name(""), "")
        self.assertEqual(O.typed_name(None), "")
        self.assertEqual(O.typed_name("   "), "")

    def test_the_derived_label_inherits_the_fix(self):
        o = O._office_from_signup({"office_key": "carlos",
                                   "owner": "carlos hidalgo"})
        self.assertEqual(o.owner, "Carlos Hidalgo")
        self.assertEqual(o.label, "Carlos's Local Office")

    def test_an_owner_typed_label_is_left_as_they_wrote_it(self):
        # Not a person's name -- title-casing would mangle AT&T and the like.
        o = O._office_from_signup({"office_key": "x", "owner": "sam jones",
                                   "office_label": "the AT&T room"})
        self.assertEqual(o.label, "the AT&T room")


class CollidingLabelsNameTheirCampaign(unittest.TestCase):
    def test_two_offices_one_owner_are_told_apart(self):
        got = O._disambiguate({
            "carlos": _off("carlos", "Carlos Hidalgo", "Carlos's Local Office",
                           campaign="b2b_box"),
            "carlos-b2batt": _off("carlos-b2batt", "Carlos Hidalgo",
                                  "Carlos's Local Office", campaign="b2b_att"),
        })
        self.assertEqual(got["carlos"].label,
                         "Carlos's Local Office (B2B — Box Energy)")
        self.assertEqual(got["carlos-b2batt"].label,
                         "Carlos's Local Office (B2B — AT&T)")

    def test_an_owner_with_one_office_is_left_plain(self):
        got = O._disambiguate({
            "kash": _off("kash", "Kash Rai", "Kash's Local Office"),
            "cyrus": _off("cyrus", "Cyrus Wade", "Cyrus's Local Office"),
        })
        self.assertEqual(got["kash"].label, "Kash's Local Office")
        self.assertEqual(got["cyrus"].label, "Cyrus's Local Office")

    def test_a_switched_off_twin_does_not_tag_the_live_one(self):
        # khalil sits in the code table OFF while khalil-nds runs from the form.
        got = O._disambiguate({
            "khalil": _off("khalil", "Khalil Mansour", "Khalil's Local Office",
                           campaign="nds", active=False),
            "khalil-nds": _off("khalil-nds", "Khalil Mansour",
                               "Khalil's Local Office", campaign="nds"),
        })
        self.assertEqual(got["khalil-nds"].label, "Khalil's Local Office")

    def test_same_campaign_falls_back_to_the_key(self):
        # The tag cannot separate these, so using it would hand back two
        # identical labels AGAIN -- noise, and still ambiguous.
        got = O._disambiguate({
            "khalil": _off("khalil", "Khalil Mansour", "Khalil's Local Office",
                           campaign="nds"),
            "khalil-nds": _off("khalil-nds", "Khalil Mansour",
                               "Khalil's Local Office", campaign="nds"),
        })
        self.assertEqual(
            sorted(o.label for o in got.values()),
            ["Khalil's Local Office (khalil)",
             "Khalil's Local Office (khalil-nds)"])

    def test_an_unknown_campaign_still_produces_something_usable(self):
        got = O._disambiguate({
            "a": _off("a", "Sam Jones", "Sam's Local Office", campaign="zzz"),
            "b": _off("b", "Sam Jones", "Sam's Local Office", campaign="att"),
        })
        self.assertEqual(len({o.label for o in got.values()}), 2)
        self.assertNotIn("Sam's Local Office",
                         {o.label for o in got.values()})


class TheLiveRosterReadsCleanly(unittest.TestCase):
    def test_every_active_office_has_its_own_label(self):
        offs = O.active()
        labels = [o.label for o in offs]
        dupes = sorted({l for l in labels if labels.count(l) > 1})
        self.assertEqual(dupes, [], "two offices share a label: %s" % dupes)

    def test_no_owner_is_left_all_lowercase(self):
        bad = [o.key for o in O.active()
               if o.owner and o.owner == o.owner.lower()]
        self.assertEqual(bad, [])

    def test_a_label_is_never_used_as_a_key(self):
        # The whole change is safe only because routing keys off `key`. If a
        # label ever becomes an identifier, this file is the warning.
        for o in O.active():
            self.assertEqual(O.get(o.key).key, o.key)


if __name__ == "__main__":
    unittest.main()
