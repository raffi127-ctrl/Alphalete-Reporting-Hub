"""The group-text part of the sign-up form, as an owner first sees it.

Megan 2026-11-12: "it should have imessage texts default to yes instead of no
like it does now and show my number to add to the group ... it also needs to
boldly say - group cannot include androids".

    .venv/bin/python -m unittest automations.icd_signup.test_text_form_defaults

Runs the page with Streamlit's own test harness. Nothing is submitted, so
nothing is written to the sign-up sheet and no key is minted.
"""
import unittest
from pathlib import Path

from automations.icd_signup import schema as S

APP = Path(__file__).resolve().parents[2] / "icd_signup" / "app.py"

try:
    from streamlit.testing.v1 import AppTest
except Exception:  # noqa: BLE001 -- the Lucys' python has no streamlit
    AppTest = None


@unittest.skipIf(AppTest is None, "streamlit is not installed here")
class TheGroupTextQuestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.at = AppTest.from_file(str(APP), default_timeout=60).run()

    def _radio(self):
        return next(r for r in self.at.radio if r.key == "want_texts")

    def test_it_opens_on_yes(self):
        self.assertFalse(self.at.exception, self.at.exception)
        self.assertEqual(self._radio().value, "Yes")

    def test_megans_number_and_lucys_email_are_both_there_to_add(self):
        box = next(i.value for i in self.at.info
                   if "add these two to the group chat" in i.value)
        self.assertIn("**Megan:** " + S.MEGAN_GROUP_NUMBER, box)
        self.assertIn("**Lucy:** " + S.LUCY_IMESSAGE, box)

    def test_no_androids_is_said_in_bold_on_its_own(self):
        warned = [w.value for w in self.at.warning]
        self.assertIn("**The group cannot include Androids.** iPhones only.",
                      warned)

    def test_choosing_no_takes_the_whole_section_away(self):
        at = AppTest.from_file(str(APP), default_timeout=60).run()
        next(r for r in at.radio if r.key == "want_texts").set_value("No").run()
        self.assertNotIn(S.MEGAN_GROUP_NUMBER, " ".join(i.value for i in at.info))
        self.assertEqual([w.value for w in at.warning
                          if "Androids" in w.value], [])


class TheNumberItShows(unittest.TestCase):
    def test_it_is_megans_and_reads_as_a_phone_number(self):
        self.assertEqual(S.phone_e164(S.MEGAN_GROUP_NUMBER), "+14197697114")


if __name__ == "__main__":
    unittest.main()
