"""An ORG-board removal has to follow through to the All Campaigns tab.

Eve, 2026-09-01: "cuando se eliminen owners de la org sales board (como hicimos
con lizette el otro día) que lógicamente los elimines también de 'All Campaigns
Org Sales Board'". Two tabs of the same workbook, two modules, two EXCLUDE
lists, and neither knew about the other.

The interesting half is when it must NOT fire. One All Campaigns line is a
person's total across EVERY campaign, so cascading a per-campaign removal would
erase the campaigns they still sell — the same scoping the two-week rule is
built on. These tests pin both directions.
"""
import types
import unittest

from automations.org_sales_board import roster_remove as rr
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB


def args(**kw):
    base = dict(no_cascade=False, sheet=SHEET_ID, tab=SANDBOX_TAB, owner=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def row(name):
    """A plan_removals()-shaped leftover row for `name`."""
    return {"asked": name, "name": name, "row0": 10, "kind": "leaderboard",
            "owner": "ALPHALETE ORG", "table": "Fiber - All Units"}


class Cascade(unittest.TestCase):
    def setUp(self):
        self.calls = []
        import automations.all_campaigns_board.roster_remove as ac
        import automations.all_campaigns_board.roster as acr
        self._ac, self._real_main = ac, ac.main
        self._acr, self._real_ex = acr, acr.EXCLUDE
        ac.main = lambda argv: self.calls.append(argv) or 0
        acr.EXCLUDE = {"gone rep"}
        self.addCleanup(self._restore)

    def _restore(self):
        self._ac.main = self._real_main
        self._acr.EXCLUDE = self._real_ex

    def _say(self, names, remaining, a):
        out = []
        real = rr.print
        try:
            rr.print = lambda *x, **k: out.append(" ".join(str(i) for i in x))
        except Exception:                     # builtins.print is not shadowable
            pass
        try:
            rr._cascade_all_campaigns(names, remaining, a)
        finally:
            try:
                rr.print = real
            except Exception:
                pass
        return " ".join(out)

    def test_a_name_fully_off_the_org_board_cascades(self):
        rr._cascade_all_campaigns(["Gone Rep"], [], args())
        self.assertEqual(self.calls, [["--names", "Gone Rep", "--apply"]])

    def test_a_name_still_on_the_org_board_does_not_cascade(self):
        """Removed from ONE campaign box, still selling another. Their All
        Campaigns line is the total of all of them and must survive."""
        rr._cascade_all_campaigns(["Gone Rep"], [row("Gone Rep")], args())
        self.assertEqual(self.calls, [])

    def test_a_mixed_batch_cascades_only_the_ones_fully_gone(self):
        self._acr.EXCLUDE = {"gone rep", "also gone"}
        rr._cascade_all_campaigns(["Gone Rep", "Still Here", "Also Gone"],
                                  [row("Still Here")], args())
        self.assertEqual(self.calls, [["--names", "Gone Rep|Also Gone", "--apply"]])

    def test_another_board_never_cascades(self):
        """The Country Sales Board reaches this module through --sheet/--tab and
        has nothing to do with the All Campaigns roster."""
        rr._cascade_all_campaigns(
            ["Gone Rep"], [],
            args(sheet="1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE",
                 tab="Country Sales Board"))
        self.assertEqual(self.calls, [])

    def test_no_cascade_flag_is_honoured(self):
        rr._cascade_all_campaigns(["Gone Rep"], [], args(no_cascade=True))
        self.assertEqual(self.calls, [])

    def test_a_name_missing_from_the_all_campaigns_exclude_is_not_deleted(self):
        """Its own --apply aborts on this by design — the auto-add would put
        them straight back. Cascading into that abort would just look broken."""
        self._acr.EXCLUDE = set()
        rr._cascade_all_campaigns(["Gone Rep"], [], args())
        self.assertEqual(self.calls, [])

    def test_a_failure_never_raises_into_a_finished_removal(self):
        """The ORG rows are already deleted by the time this runs. Raising here
        would read as 'the removal failed' when half of it succeeded."""
        def boom(_argv):
            raise RuntimeError("quota")
        self._ac.main = boom
        rr._cascade_all_campaigns(["Gone Rep"], [], args())   # must not raise


if __name__ == "__main__":
    unittest.main()
