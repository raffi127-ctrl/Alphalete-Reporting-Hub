"""#7 Activation Rate by Rep must find its block by LABEL, never by column.

WHY (2026-09-14): the reader hardcoded AE14:AF{last}. On 2026-09-12 the churn
rolloff list gained 'Lines on Acct' and a real 'Disconnect Date', which pushed
the per-rep list from AE:AF to AG:AH. The writer survived — vantura_churn.fill
.rep_list_col derives its column on purpose — the reader did not. AE then held
only the helper block's few rows, so `last` came back under the header row and
the blank-guard skipped the section: Jamis, Atef and Sabrina all lost #7 from
their 4am thread on 9/13 and 9/14 while the numbers sat healthy two columns
over. Only Jamis's drop was named in the alert.

These lock the two halves of the fix: the block is found wherever it sits, and
a board that genuinely has no rep rows still refuses to post blank.
"""
import unittest

from automations.b2b_metrics import capture


class FakeWS:
    """Minimal gspread.Worksheet stand-in: a dense grid + A1 range reads."""

    def __init__(self, cells, title="LUCY CHURN"):
        self.title = title
        self._cells = cells          # {(row, col1based): value}

    def get(self, rng):
        import re
        m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)$", rng)
        c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        n1, n2 = _num(c1), _num(c2)
        out = []
        for r in range(r1, r2 + 1):
            row = [str(self._cells.get((r, c), "")) for c in range(n1, n2 + 1)]
            while row and row[-1] == "":
                row.pop()
            out.append(row)
        while out and not out[-1]:
            out.pop()
        return out


def _num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _board(rep_col, reps=20, hdr_row=15):
    """A churn tab whose per-rep list sits at `rep_col` (e.g. 'AE' or 'AG')."""
    c = _num(rep_col)
    cells = {(r, 27): "helper" for r in range(2, 8)}   # AA helper block
    cells[(hdr_row, c)] = "Rep Name"
    cells[(hdr_row, c + 1)] = "0-30 Day Activation Rate"
    for i in range(reps):
        cells[(hdr_row + 1 + i, c)] = "Rep {}".format(i)
        cells[(hdr_row + 1 + i, c + 1)] = "100.0%"
    return FakeWS(cells)


class RepListAnchor(unittest.TestCase):

    def test_finds_the_header_wherever_it_sits(self):
        for col, want in (("AE", 31), ("AG", 33), ("AK", 37)):
            with self.subTest(col=col):
                self.assertEqual(capture._rep_list_anchor(_board(col)),
                                 (want, 15))

    def test_survives_the_row_moving_too(self):
        self.assertEqual(capture._rep_list_anchor(_board("AG", hdr_row=22)),
                         (33, 22))

    def test_a1_col_round_trips(self):
        for n, letters in ((1, "A"), (26, "Z"), (27, "AA"), (31, "AE"),
                           (33, "AG"), (78, "BZ")):
            self.assertEqual(capture._a1_col(n), letters)

    def test_no_header_is_a_refusal_not_a_guess(self):
        """A board with no 'Rep Name' must raise, not screenshot some columns."""
        with self.assertRaises(ValueError) as e:
            capture._rep_list_anchor(FakeWS({(2, 27): "helper"}))
        self.assertIn("Rep Name", str(e.exception))


class RangeChosen(unittest.TestCase):
    """The range the shot is taken from, computed the way churn_tab_image does."""

    def _range(self, ws):
        c, r = capture._rep_list_anchor(ws)
        name, rate = capture._a1_col(c), capture._a1_col(c + 1)
        col = ws.get("{c}1:{c}200".format(c=name))
        last = max((i for i, x in enumerate(col, 1) if x and x[0].strip()),
                   default=0)
        if last <= r:
            raise ValueError("no rep rows")
        return "{n}{top}:{r}{last}".format(n=name, r=rate,
                                           top=max(1, r - 1), last=last)

    def test_the_live_shape_today(self):
        """AG15 header + 20 reps — what all four boards look like on 9/14."""
        self.assertEqual(self._range(_board("AG", reps=20)), "AG14:AH35")

    def test_the_old_shape_still_works(self):
        """A board still on the pre-9/12 layout must not break."""
        self.assertEqual(self._range(_board("AE", reps=20)), "AE14:AF35")

    def test_blank_board_still_refuses(self):
        """The header alone (no rep rows) must still skip, not post a 2-row
        blank — the 2026-07-22 guard, kept."""
        with self.assertRaises(ValueError):
            self._range(_board("AG", reps=0))

    def test_helper_block_alone_does_not_pass_as_reps(self):
        """The exact 9/13 failure in reverse: AA's helper rows are not the list,
        and the reader must not be looking at them in the first place."""
        ws = _board("AG", reps=20)
        self.assertEqual(self._range(ws), "AG14:AH35")


if __name__ == "__main__":
    unittest.main()
