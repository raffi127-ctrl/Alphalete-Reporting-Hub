"""Guards on the JavaScript this module injects into the page.

A browser-side syntax error costs a full queue round trip to find out about —
the run reaches Lucy 2, opens a session, loads the page and only then dies —
so the cheap checks belong here. Both of these were real: `[^\\n]` written in
a non-raw Python literal put an actual newline inside a regex character class
(SyntaxError), and `\\\\d` became an escaped backslash that could never match
a date, so the date fields were never found by value.

  python -m unittest automations.sms_audit.test_pull_log
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parent / "pull_log.py"


def _injected_js():
    """Every string literal in the module that is JavaScript — the ones handed
    to page.evaluate. Their VALUE is what the browser parses, which is the
    thing worth checking, not the source spelling."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "=>" in n.value]


class InjectedJsTest(unittest.TestCase):
    def test_there_is_js_to_check(self):
        self.assertGreater(len(_injected_js()), 3)

    def test_no_regex_literal_contains_a_real_newline(self):
        """A regex literal cannot span lines. `[^\\n]` in a non-raw Python
        string becomes a real newline and the whole evaluate dies with
        'Invalid regular expression'."""
        for lineno, js in _injected_js():
            for m in re.finditer(r"/[^/\n]*\n[^/\n]*/\)", js):
                self.fail("line {}: regex literal spans a newline: {!r}"
                          .format(lineno, m.group(0)[:60]))

    def test_no_double_escaped_character_class(self):
        r"""`\\d` in the delivered JS matches a literal backslash, not a digit.
        It is not a syntax error, so it fails silently — the date inputs are
        simply never matched and the report quietly returns today."""
        for lineno, js in _injected_js():
            for m in re.finditer(r"\\\\[dswSWn]", js):
                self.fail("line {}: {!r} reaches the browser as an escaped "
                          "backslash".format(lineno, m.group(0)))

    def test_all_four_date_fields_are_set(self):
        """The form carries FOUR date fields: startDate/endDate in MM-DD-YYYY
        (the visible boxes) and hidden startDate2/endDate2 in MM/DD/YYYY. The
        server reads the *2 pair, so setting only the visible boxes leaves the
        hidden pair on today and Search returns today while the boxes on
        screen say otherwise. That is exactly what the first two probes did."""
        js = " ".join(j for _l, j in _injected_js())
        for name in ("startDate", "endDate", "startDate2", "endDate2"):
            self.assertTrue('"{}"'.format(name) in js or "'{}'".format(name) in js,
                            "{} is never set".format(name))

    def test_the_hidden_pair_gets_slashes_not_hyphens(self):
        from automations.sms_audit import pull_log as P
        self.assertEqual("09-25-2026".replace("-", "/"), "09/25/2026")
        src = MODULE.read_text(encoding="utf-8")
        self.assertIn('slash_lo, slash_hi = lo.replace("-", "/")', src)
        self.assertTrue(hasattr(P, "_set_range"))

    def test_the_fallback_pattern_accepts_either_separator(self):
        """If the names ever change, the fallback finds inputs by the date
        already in them — and both spellings are on this page."""
        rx = re.compile(r"^\d{2}[-/]\d{2}[-/]\d{4}$")
        self.assertTrue(rx.match("09-25-2026"))
        self.assertTrue(rx.match("09/25/2026"))
        self.assertFalse(rx.match("2026-09-25"))
        js = " ".join(j for _l, j in _injected_js())
        self.assertIn(r"\d{2}[-/]\d{2}[-/]\d{4}", js)


class HeaderMapTest(unittest.TestCase):
    def test_every_kept_column_has_a_header_to_come_from(self):
        from automations.sms_audit import pull_log as P
        self.assertEqual(set(P.COLUMNS), set(P.HEADER_MAP.values()))

    def test_the_header_keys_are_the_page_spelling_lowercased(self):
        from automations.sms_audit import pull_log as P
        # the grid's own headers, from the live page
        for header in ("type", "queued at", "sent at", "sender phone",
                       "recipient phone", "sms type", "body", "status", "sent by"):
            self.assertIn(header, P.HEADER_MAP)


if __name__ == "__main__":
    unittest.main()
