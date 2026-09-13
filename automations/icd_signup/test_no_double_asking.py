"""Nothing the form collects is asked again by the installer.

Megan 2026-09-13: "the installer shouldn't ask for the same things they are
already filling out on the form... or the form shouldn't ask as well." One or
the other, never both.

It matters more than politeness. Every dialog in the installer is a place an
install stalls with nobody watching, and an office that answers the same
question twice has no way to know which answer counted -- so the second one is
also a chance to contradict the first.

WHAT THE INSTALLER STILL ASKS, ON PURPOSE:
  * the SaraPlus and OwnerVille passwords, which must be typed on their own
    machine and must never reach a web form;
  * "is this your office?", which is the guard against somebody running
    another office's code.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SETUP = (ROOT / "automations/icd_alerts/dist/setup.py").read_text()
GS = (ROOT / "resources/icd-alerts-relay.gs").read_text()
FORM = (ROOT / "icd_signup/app.py").read_text()


class TheInstallerSkipsWhatTheFormAsked(unittest.TestCase):

    # (what the form collects, the key it arrives as, the guard in setup.py)
    SHARED = [
        ("alert channels", "requested_channels",
         'rec.get("requested_channels") is not None'),
        ("knocks destinations", "requested_knocks_destinations",
         'rec.get("requested_knocks_destinations") is not None'),
        ("their OwnerVille name", "ov_name", 'rec.get("ov_name")'),
        ("selling hours", "hours_from_signup", 'rec.get("hours_from_signup")'),
    ]

    def test_each_shared_answer_has_a_skip_guard(self):
        for what, _key, guard in self.SHARED:
            self.assertIn(guard, SETUP,
                          "the installer re-asks for %s -- it has no guard on "
                          "the answer the form already collected" % what)

    def test_the_relay_hands_every_shared_answer_over(self):
        # A guard is useless if the answer never reaches install.json.
        for what, key, _guard in self.SHARED:
            self.assertIn(key, GS,
                          "doGet does not serve %s, so the installer's skip "
                          "guard can never fire" % what)

    def test_the_form_actually_collects_them(self):
        for needle in ("alert_channels_json", "knocks_json", "ov_name",
                       "day_start"):
            self.assertIn(needle, FORM,
                          "the form no longer collects %s, so the installer "
                          "should be asking for it again" % needle)


class ThePasswordsAreNeverOnTheForm(unittest.TestCase):
    """The one thing that must stay in the installer, and stay out of the web.

    The whole design rests on the SaraPlus login never leaving the office's own
    machine. A sign-up page that collected one would undo it quietly, and this
    is the cheapest place to notice.
    """

    def test_the_form_never_collects_a_saraplus_or_ownerville_login(self):
        """The thing that must never appear, named precisely.

        A masked field is not the problem -- the approve view uses one for the
        access code, and should. The problem would be THIS form asking for the
        credential that is supposed to live only on the office's own machine.
        """
        lowered = FORM.lower()
        for word in ("saraplus password", "ownerville password",
                     "your saraplus login", "your ownerville login"):
            self.assertNotIn(word, lowered,
                             "the sign-up form is asking for %r" % word)

    def test_the_only_masked_field_is_the_access_code(self):
        import re
        masked = re.findall(r'st\.text_input\(\s*"([^"]+)"[^)]*type="password"',
                            FORM)
        self.assertEqual([m.lower() for m in masked], ["access code"],
                         "a new masked field appeared: %s" % masked)

    def test_the_installer_still_asks_for_them(self):
        self.assertIn("ask_for_login", SETUP)
        self.assertIn("ownerville_until_it_works", SETUP)


if __name__ == "__main__":
    unittest.main()
