"""#6's blank-guard: a real zero posts; an unwritten board still doesn't."""
import unittest

from automations.b2b_metrics.capture import _assert_rolloff_has_data


class _Ws:
    title = "Lucy Churn"

    def __init__(self, top, list_cell="#N/A"):
        self.top, self.list_cell = top, list_cell

    def get(self, rng):
        if rng == "A1:A200":
            return [["0-30 Day Rolloff List"], ["Days left = (Posted+30)"],
                    ["Filter:"], ["Product"], ["Days Left"], [self.list_cell]]
        return self.top


def _top(row, picked="Wireless"):
    return [["Filter:", picked],
            ["Product", "Activations", "Disconnects", "Churn %"], row]


class RolloffGuard(unittest.TestCase):
    def test_zero_disconnects_on_a_written_board_passes(self):
        _assert_rolloff_has_data(_Ws(_top(["Wireless", "77", "0", "0.00%"])), None)

    def test_disconnects_but_empty_list_still_blocks(self):
        with self.assertRaises(ValueError):
            _assert_rolloff_has_data(_Ws(_top(["Wireless", "77", "3", "3.9%"])), None)

    def test_unwritten_board_still_blocks(self):
        for row in (["Wireless", "", ""], ["Wireless", "#N/A", "#N/A"],
                    ["Wireless", "0", "0"], ["Wireless"]):
            with self.assertRaises(ValueError):
                _assert_rolloff_has_data(_Ws(_top(row)), None)

    def test_other_product_row_does_not_vouch(self):
        with self.assertRaises(ValueError):
            _assert_rolloff_has_data(_Ws(_top(["Air", "26", "0"])), None)

    def test_real_rows_pass_without_reading_the_table(self):
        _assert_rolloff_has_data(_Ws([], list_cell="6d"), None)


if __name__ == "__main__":
    unittest.main()
