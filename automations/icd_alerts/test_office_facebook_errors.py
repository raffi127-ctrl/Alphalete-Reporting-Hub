"""What Graph said, kept whole.

2026-11-16: raf's page logged `fb_reply_error · Permissions error` 70 times in
one day with zero successful replies, and that headline alone cannot tell the
two causes apart:

  * the page token is missing pages_manage_engagement -> EVERY reply fails,
    and it is a connection problem somebody has to grant
  * Graph refuses a comment on one particular recommendation story -> that one
    review is a dead end and parking it is correct

code / error_subcode / error_user_msg are what separate them, and _graph used
to drop all three, keeping only err["message"]. Same mistake as the knocks
alert cutting off its own "Headers seen:" list.

Run:  python -m unittest automations.icd_alerts.test_office_facebook_errors
"""
from __future__ import annotations

import unittest


from automations.icd_alerts import office_facebook as FB


class TheErrorKeepsItsEvidence(unittest.TestCase):

    def test_code_and_subcode_survive(self):
        t = FB._err_text({"message": "(#200) Permissions error", "code": 200,
                          "error_subcode": 1446036, "type": "OAuthException"})
        self.assertIn("Permissions error", t)
        self.assertIn("code 200", t)
        self.assertIn("subcode 1446036", t)
        self.assertIn("OAuthException", t)

    def test_the_user_facing_message_is_appended(self):
        t = FB._err_text({"message": "(#200) Permissions error", "code": 200,
                          "error_user_msg": "This Page needs the manage "
                                            "engagement permission."})
        self.assertIn("manage engagement", t)

    def test_fbtrace_is_kept_because_support_asks_for_it(self):
        t = FB._err_text({"message": "boom", "fbtrace_id": "AbC123"})
        self.assertIn("AbC123", t)

    def test_a_bare_message_still_works(self):
        self.assertEqual(FB._err_text({"message": "plain"}), "plain")

    def test_an_empty_error_does_not_crash(self):
        self.assertTrue(FB._err_text({}))

    def test_it_stays_bounded(self):
        t = FB._err_text({"message": "z" * 5000, "code": 1, "fbtrace_id": "x"})
        self.assertLessEqual(len(t), 400)


class SignedOutIsStillItsOwnThing(unittest.TestCase):
    """Code 190 must keep raising the bare sentinel the callers compare to."""

    def test_the_sentinel_is_not_decorated(self):
        # reply_job compares str(e) == "signed_out" exactly; decorating it
        # would silently turn a signed-out page into a generic error.
        import inspect
        src = inspect.getsource(FB._graph)
        self.assertIn('raise RuntimeError("signed_out")', src)


class TheRefusalMatcherStillFires(unittest.TestCase):
    """eco_fb._refused keys on the word 'permission'; the richer text must not
    break the parking that stopped the 140x retry loop."""

    def test_the_decorated_text_is_still_recognised_as_a_refusal(self):
        from automations.online_presence import eco_fb as E
        t = FB._err_text({"message": "(#200) Permissions error", "code": 200,
                          "error_subcode": 1446036})
        self.assertTrue(E._refused(t))


if __name__ == "__main__":
    unittest.main()
