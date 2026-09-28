"""The OBCL picture groups by classroom and tints the names to match the sheet
(Megan 2026-09-28).

    python -m pytest automations/obcl_ov_sweep/test_snapshot_classroom.py -q
"""
import unittest

from automations.obcl_ov_sweep import snapshot as sn


def _rec(name, classroom):
    r = {c: {"v": "", "bg": None} for c in sn.COLUMNS}
    r["Name"] = {"v": name, "bg": None}
    r["Classroom"] = {"v": classroom, "bg": None}
    r["Start Time"] = {"v": "1:00", "bg": None}
    return r


class Grouping(unittest.TestCase):
    def test_rows_sort_into_classroom_groups(self):
        recs = [_rec("A", "Willie"), _rec("B", "Aimee"), _rec("C", "Willie"),
                _rec("D", "JD")]
        recs.sort(key=lambda x: (sn.classroom_key(x["Classroom"]["v"]),
                                 sn._start_key(x["Start Time"]["v"]),
                                 x["Name"]["v"].lower()))
        self.assertEqual([r["Classroom"]["v"] for r in recs],
                         ["Aimee", "JD", "Willie", "Willie"])

    def test_no_classroom_yet_sorts_last_not_first(self):
        keys = [sn.classroom_key(""), sn.classroom_key("Aimee")]
        self.assertEqual(sorted(keys), [keys[1], keys[0]])


class Colours(unittest.TestCase):
    def test_chip_fill_matches_the_sheet(self):
        self.assertEqual(sn.classroom_fill("Willie"), (53, 113, 78))
        self.assertEqual(sn.classroom_fill("aimee"), (251, 230, 168))

    def test_dark_chips_get_white_text_pastels_black(self):
        self.assertEqual(sn._ink_for(sn.classroom_fill("Safiya")),
                         (255, 255, 255))
        self.assertEqual(sn._ink_for(sn.classroom_fill("Aimee")), (0, 0, 0))

    def test_name_ink_is_readable_on_the_tinted_cell(self):
        # The name cells are themselves green/pink; a raw pastel chip as ink
        # is invisible on them.
        for room in sn.CLASSROOM_COLORS:
            for fill in ((255, 255, 255), (217, 234, 211), (244, 204, 204)):
                ink = sn.classroom_ink(room, fill)
                self.assertGreaterEqual(
                    sn._contrast(ink, fill), 3.0,
                    f"{room} on {fill} is too faint: {ink}")

    def test_unknown_classroom_draws_plain(self):
        self.assertIsNone(sn.classroom_fill("Someone New"))
        self.assertIsNone(sn.classroom_ink("Someone New"))


if __name__ == "__main__":
    unittest.main()
