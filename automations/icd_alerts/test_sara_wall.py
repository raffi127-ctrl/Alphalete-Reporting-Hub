"""SaraPlus's Change Password page, on a laptop we do not own.

WHAT THIS PAGE ACTUALLY MEANS was settled the hard way on 2026-09-12: it is
USUALLY A WEDGED CHROME PROFILE, not an expired account. The identical
credential walked straight into DealerPages from an incognito window and from
a fresh empty profile while one profile sat stuck on it for thirty passes, and
the password was changed twice for a problem a ninety-second retry disproved.

That makes the ICD laptop the best possible place to handle it: nobody is
sitting there, so the fix has to be automatic. These tests pin three things:

  * a wall HEALS ITSELF -- rotate the profile, try once more;
  * a second wall on a BRAND-NEW profile is the real every-few-weeks reset,
    and says so, because that is the one case a human must act on;
  * and none of it ever reaches an owner in our words. The shared messages
    name Chrome profiles, set_credentials and password character rules; an
    ICD in another state can act on exactly two things -- re-enter the
    password, or tell us.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import sara_read
from automations.shared import saraplus as S


def _wall(msg="SaraPlus served its Change Password page"):
    return S.SaraPasswordWall(msg)


class OwnerFacingMessages(unittest.TestCase):
    """What an ICD reads. Never our plumbing."""

    def test_real_reset_tells_them_to_set_a_new_password(self):
        msg = str(sara_read._as_owner_problem(
            S.SaraPasswordChangeRequired("whatever we say internally")))
        self.assertIn("NEW password", msg)
        self.assertIn("password step", msg)

    def test_bad_password_is_not_confused_with_the_wall(self):
        msg = str(sara_read._as_owner_problem(
            S.SaraError("SaraPlus login failed -- still on the login page")))
        self.assertIn("did not accept", msg)

    def test_wall_never_blames_the_password(self):
        # The 2026-09-12 mistake, pinned: a stuck profile must not read as an
        # expired credential, or somebody changes a password that was right.
        msg = str(sara_read._as_owner_problem(_wall()))
        self.assertNotIn("did not accept", msg)

    def test_no_hub_internals_reach_an_owner(self):
        for err in (_wall(), S.SaraPasswordChangeRequired("x"),
                    S.SaraError("still on the login page")):
            msg = str(sara_read._as_owner_problem(err))
            for jargon in ("set_credentials", "Chrome profile", "profile_dir",
                           "rotate_profile", "DealerPages"):
                self.assertNotIn(jargon, msg, "%r leaked %r" % (err, jargon))


class Healing(unittest.TestCase):
    """The automatic part -- the whole reason an ICD does not get a phone call."""

    def _run(self, outcomes):
        """Drive _heal_and_login with a scripted sequence of login outcomes."""
        calls = {"opens": 0, "rotations": 0}

        def fake_context(p, headless):
            return mock.MagicMock()

        def fake_login(page, log=print):
            i = calls["opens"]
            calls["opens"] += 1
            out = outcomes[i]
            if isinstance(out, Exception):
                raise out
            return out

        with mock.patch.object(sara_read, "_context", fake_context), \
             mock.patch.object(sara_read, "_sign_in_raw", fake_login), \
             mock.patch.object(S, "rotate_profile",
                               lambda *a, **k: calls.__setitem__(
                                   "rotations", calls["rotations"] + 1)):
            try:
                _ctx, _page, base = sara_read._heal_and_login(
                    object(), True, log=lambda *a, **k: None)
                return calls, base, None
            except sara_read.AccountProblem as e:
                return calls, None, str(e)

    def test_clean_login_never_rotates(self):
        calls, base, err = self._run(["https://sara/e/(S(x))/"])
        self.assertIsNone(err)
        self.assertEqual(calls["rotations"], 0)
        self.assertEqual(calls["opens"], 1)

    def test_a_wall_heals_itself_without_anybody(self):
        calls, base, err = self._run([_wall(), "https://sara/e/(S(y))/"])
        self.assertIsNone(err, "the retry should have succeeded")
        self.assertEqual(calls["rotations"], 1)
        self.assertEqual(calls["opens"], 2)

    def test_a_second_wall_is_the_real_reset(self):
        calls, base, err = self._run([_wall(), _wall()])
        self.assertIsNotNone(err)
        self.assertIn("NEW password", err)
        self.assertEqual(calls["rotations"], 1, "rotate once, not forever")

    def test_a_bad_password_is_not_healed(self):
        # Rotating the profile for a wrong password would throw away a good
        # browser and still fail -- and hide the real cause behind it.
        calls, base, err = self._run(
            [S.SaraError("SaraPlus login failed -- still on the login page")])
        self.assertIn("did not accept", err)
        self.assertEqual(calls["rotations"], 0)


if __name__ == "__main__":
    unittest.main()
