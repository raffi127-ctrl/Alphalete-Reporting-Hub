"""The 'después de arreglar quedan' line on owners' boards counts only what
Lucy would really write: the '#' column stays out, a real fix stays in."""
import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.sales_board_fixer import checks as K, run as R


def _rank():
    return K.Finding(kind="different_formula", tab="t", where="A5", detail="",
                     before='=IF(B5<>"",ROW()-3,"")', after="=A4+1", value="=A4+1")


def _font():
    return K.Finding(kind="font", tab="t", where="C5", detail="", request={"x": 1})


class OwnerRecount(unittest.TestCase):
    def _last_line(self, recount, kinds=frozenset({"different_formula", "font"})):
        out = io.StringIO()
        with mock.patch.object(R, "load", return_value={"values": [], "sheet_id": 1}), \
                mock.patch.object(R, "audit", side_effect=[[], recount]), \
                mock.patch.object(R, "apply", return_value=[]), \
                mock.patch.object(R, "backup", return_value="b"), \
                mock.patch.object(K, "old_note_requests", return_value=([], [])), \
                mock.patch.object(R, "_drop_past", side_effect=lambda f, *_: f), \
                mock.patch.object(K, "is_board", return_value=True), \
                mock.patch.object(K, "layout", return_value=SimpleNamespace(name_col=2)), \
                contextlib.redirect_stdout(out):
            R.run_tabs(mock.Mock(), ["Sales Board"], "s", True, kinds=kinds)
        return [l for l in out.getvalue().splitlines() if "quedan" in l][0].strip()

    def test_rank_column_is_not_work_left(self):
        self.assertEqual(self._last_line([_rank()]),
                         "después de arreglar quedan: 1 (0 arreglables)")

    def test_a_real_fix_still_counts(self):
        self.assertEqual(self._last_line([_rank(), _font()]),
                         "después de arreglar quedan: 2 (1 arreglables)")

    def test_a_kind_outside_the_owner_list_is_left_out(self):
        self.assertEqual(self._last_line([_font()], kinds=frozenset({"different_formula"})),
                         "después de arreglar quedan: 0 (0 arreglables)")


if __name__ == "__main__":
    unittest.main()
