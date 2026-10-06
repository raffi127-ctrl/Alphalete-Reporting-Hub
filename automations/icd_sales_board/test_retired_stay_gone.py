"""How the LucyEco roster is assembled: who gets on, and who stays off.

The LucyEco roster is assembled from three places -- profiles.load(), every
Active ICD = YES row on the org bulletin, and the live ad-photo owners.
Only the first consulted the retired list, so Ronald Dawson, retired on
Megan's instruction, reappeared on the PUBLIC page the same day because the
bulletin still reads YES for him (Megan 2026-10-06).

No network: the sheet is a fake.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from automations.icd_sales_board import profiles as P


class TheAccessor(unittest.TestCase):

    def _with(self, payload):
        return mock.patch.object(
            P, "_FILE", mock.Mock(read_text=lambda: json.dumps(payload)))

    def test_it_lower_cases_for_comparison(self):
        with self._with({"retired": ["Ronald Dawson", "Steve McElwee"]}):
            self.assertEqual(P.retired_names(),
                             {"ronald dawson", "steve mcelwee"})

    def test_blanks_do_not_become_a_name(self):
        with self._with({"retired": ["", "  ", "Ronald Dawson"]}):
            self.assertEqual(P.retired_names(), {"ronald dawson"})

    def test_no_retired_key_is_an_empty_set_not_a_crash(self):
        with self._with({"per_icd": {}}):
            self.assertEqual(P.retired_names(), set())

    def test_an_unreadable_file_retires_nobody(self):
        with mock.patch.object(P, "_FILE", mock.Mock(
                read_text=mock.Mock(side_effect=OSError("gone")))):
            self.assertEqual(P.retired_names(), set())


class TheRosterDropsThem(unittest.TestCase):
    """The filter must be applied AFTER every source has appended."""

    def test_a_retired_name_from_the_bulletin_is_dropped(self):
        from automations.icd_sales_board import enrollment as EN
        names = ["Kash Patel", "Ronald Dawson", "Rafael Hidalgo"]
        gone = {"ronald dawson"}
        kept = [n for n in names if n.strip().lower() not in gone]
        self.assertEqual(kept, ["Kash Patel", "Rafael Hidalgo"])
        # and the real accessor agrees about him
        self.assertIn("ronald dawson", P.retired_names())
        self.assertNotIn("kash patel", P.retired_names())

    def test_he_is_absent_from_the_assembled_roster(self):
        """End to end, against the real registries."""
        from automations.icd_sales_board import enrollment as EN
        got = EN.rows()
        if not got:
            self.skipTest("registries unreadable here")
        who = {(r.get("ICD") or r.get("Office") or "").strip().lower()
               for r in got}
        self.assertNotIn("ronald dawson", who)


class SignupsReachTheRoster(unittest.TestCase):
    """An office that signed up today is an office we run something for.

    Luke Baldwin and Jennifer Figueroa enrolled on 2026-10-06 and appeared
    nowhere on the page: the roster knew the board, the org bulletin and the
    ad-photo config, and a same-day sign-up is on none of the three."""

    def _names(self):
        from automations.icd_sales_board import enrollment as EN
        got = EN.rows()
        if not got:
            self.skipTest("registries unreadable here")
        return {(r.get("ICD") or r.get("Office") or "").strip() for r in got}

    def test_an_approved_signup_is_on_the_roster(self):
        self.assertIn("Luke Baldwin", self._names())

    def test_a_pending_signup_is_on_the_roster(self):
        """Jennifer's only live row is pending -- she is still installing."""
        self.assertIn("Jennifer Figueroa", self._names())

    def test_a_declined_only_owner_never_reaches_the_public_page(self):
        from automations.icd_signup import store as S
        from automations.icd_signup.schema import IcdSignup
        real = S.all_signups

        def _with_a_refusal(book=None, strict=False):
            out = list(real(book, strict=strict))
            out.append(IcdSignup.from_row(
                {"office_key": "refusedperson", "owner": "Refused Person",
                 "campaign": "att", "status": "declined", "platform": "mac",
                 "timezone": "America/Chicago"}))
            return out

        with mock.patch.object(S, "all_signups", _with_a_refusal):
            self.assertNotIn("Refused Person", self._names())

    def test_retirement_beats_a_fresh_signup(self):
        """Filtered last, so signing up again cannot undo a retirement."""
        from automations.icd_signup import store as S
        from automations.icd_signup.schema import IcdSignup
        real = S.all_signups

        def _with_a_retiree(book=None, strict=False):
            out = list(real(book, strict=strict))
            out.append(IcdSignup.from_row(
                {"office_key": "ronald", "owner": "Ronald Dawson",
                 "campaign": "att", "status": "approved", "platform": "mac",
                 "timezone": "America/Chicago"}))
            return out

        with mock.patch.object(S, "all_signups", _with_a_retiree):
            self.assertNotIn("Ronald Dawson", self._names())


class OnePersonOneRow(unittest.TestCase):
    """The roster resolves names through the ICD Aliases sheet.

    The org bulletin calls him 'Salik Waqar'; every other registry calls him
    'Salik Mallick' (his own address is salikmallick6@). He arrived as two
    offices, and a third -- 'Salik Hammad' -- came from ad_photo_threads,
    which labels his thread with both names because the room is shared.
    The alias sheet already held every one of those spellings; nothing on
    the page was reading it (Megan 2026-10-06: "this is the same person").
    """

    def test_the_alias_sheet_resolves_every_known_spelling(self):
        from automations.focus_office_att import aliases as AL
        raw = AL.load_aliases()
        if not raw:
            self.skipTest("alias sheet unreadable here")
        for spelling in ("Salik Waqar", "Salik Hammad", "Salik Malick",
                         "Salik Mallick"):
            self.assertEqual(AL.alias_to_canonical(spelling, raw),
                             "Salik Mallick", spelling)

    def test_canon_leaves_an_unknown_name_alone(self):
        from automations.icd_sales_board import enrollment as EN
        self.assertEqual(EN._canon("Nobody Inparticular"),
                         "Nobody Inparticular")

    def test_he_is_one_row_on_the_roster(self):
        from automations.icd_sales_board import enrollment as EN
        got = EN.rows()
        if not got:
            self.skipTest("registries unreadable here")
        hits = [r for r in got
                if "salik" in (r.get("ICD") or "").lower()]
        self.assertEqual([r["ICD"] for r in hits], ["Salik Mallick"])

    def test_the_merged_row_keeps_what_each_source_knew(self):
        """The bulletin's campaign has to survive the rename, or merging
        him silently blanks the column it came from."""
        from automations.icd_sales_board import enrollment as EN
        got = EN.rows()
        if not got:
            self.skipTest("registries unreadable here")
        r = next((r for r in got if r.get("ICD") == "Salik Mallick"), None)
        self.assertIsNotNone(r)
        self.assertTrue(r.get("Campaigns"),
                        "campaign came from the bulletin row and was lost")
        self.assertEqual(r.get("Ad Photo Threads"), EN.ENROLLED,
                         "his ad thread is live under a third spelling")


if __name__ == "__main__":
    unittest.main()
