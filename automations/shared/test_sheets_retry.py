"""The master-sheet open has to survive a rate limit and explain a real fault."""
import unittest

from automations.shared import sheets_retry as SR


class _APIError(Exception):
    """Stands in for gspread.exceptions.APIError (which carries .code)."""
    def __init__(self, code, msg="boom"):
        super().__init__(msg)
        self.code = code


class _OldAPIError(Exception):
    """gspread 5.x shape: the status only lives on .response."""
    def __init__(self, code):
        super().__init__("boom")
        self.response = type("R", (), {"status_code": code})()


class _Client:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def open_by_key(self, key):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "SHEET:" + key


class OpenSheet(unittest.TestCase):
    def setUp(self):
        self.slept = []

    def _open(self, client, **kw):
        return SR.open_sheet(client, "MASTER", sleeper=self.slept.append, **kw)

    def test_a_rate_limit_is_waited_out_not_raised(self):
        c = _Client([_APIError(429), _APIError(429)])
        self.assertEqual(self._open(c), "SHEET:MASTER")
        self.assertEqual(c.calls, 3)
        self.assertEqual(self.slept, [1.0, 2.0])

    def test_a_transient_5xx_is_retried_too(self):
        c = _Client([_APIError(503)])
        self.assertEqual(self._open(c), "SHEET:MASTER")

    def test_the_gspread_5x_error_shape_is_read_too(self):
        self.assertEqual(SR.status_code(_OldAPIError(429)), 429)
        self.assertTrue(SR.is_retryable(_OldAPIError(500)))

    def test_a_permission_error_fails_immediately(self):
        """403 means access is gone — retrying only makes the form slower."""
        c = _Client([_APIError(403), _APIError(403), _APIError(403), _APIError(403)])
        with self.assertRaises(_APIError):
            self._open(c)
        self.assertEqual(c.calls, 1)
        self.assertEqual(self.slept, [])

    def test_it_gives_up_and_re_raises_the_real_error(self):
        c = _Client([_APIError(429)] * 10)
        with self.assertRaises(_APIError) as cm:
            self._open(c)
        self.assertEqual(cm.exception.code, 429)
        self.assertEqual(c.calls, SR._TRIES)

    def test_every_explanation_is_a_plain_sentence(self):
        """What a form shows an ICD: no stack trace, no 'redacted' boilerplate."""
        for code in (429, 503, 403, 404, 401):
            said = SR.explain(_APIError(code))
            self.assertNotIn("Traceback", said)
            self.assertTrue(said.endswith(".") or said.endswith("!"), said)
        self.assertIn("rate-limited", SR.explain(_APIError(429)))
        self.assertIn("Megan", SR.explain(_APIError(403)))


if __name__ == "__main__":
    unittest.main()
