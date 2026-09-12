"""Sales have to land as NUMBERS, not as text that looks like numbers.

gspread's `batch_update` defaults to RAW, which stores the string "2" as TEXT.
Every roll-up on the sales board is a SUM or SUMIFS and both skip text without a
word, so a text "2" is a sale that silently never counts. Found 2026-09-11:
Andrew Sanborn is the only rep this module writes and all seven of his cells
were text — his 7 Thursday apps never reached his team's row. The cell renders
identically, which is why it went unnoticed for a month.

This test reads the source, because the bug is an ABSENT argument: there is no
return value or state to assert on, and a mock of the sheet would only prove the
mock's default.
"""
import inspect
import re
import unittest

import gspread

from automations.rep_sales_fill import run


class WritesAreUserEntered(unittest.TestCase):
    def test_the_write_passes_user_entered(self):
        src = inspect.getsource(run.main)
        call = re.search(r"_retry\(ws\.batch_update,.*?\)\n", src, re.S)
        self.assertIsNotNone(call, "no se encontró la escritura en main()")
        self.assertIn('value_input_option="USER_ENTERED"', call.group(0))

    def test_gspread_still_defaults_to_raw(self):
        """If this ever fails, gspread changed its default and the comment in
        run.py is stale — not that the fix became unnecessary."""
        sig = inspect.signature(gspread.Worksheet.batch_update)
        self.assertIs(sig.parameters["raw"].default, True)

    def test_no_other_bare_batch_update_in_the_module(self):
        """A second writer added later must not reintroduce the RAW default."""
        src = inspect.getsource(run)
        for m in re.finditer(r"ws\.batch_update", src):
            tail = src[m.start():m.start() + 400]
            self.assertIn("value_input_option", tail,
                          "una escritura sin value_input_option en run.py")


if __name__ == "__main__":
    unittest.main()
