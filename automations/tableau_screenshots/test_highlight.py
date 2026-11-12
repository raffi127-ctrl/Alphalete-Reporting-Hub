"""Eco owners' rows highlighted on their own channel's trackers (Rafael 2026-11-12).

  python -m unittest automations.tableau_screenshots.test_highlight
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from automations.tableau_screenshots import highlight as H

NAMES = ["CHAN PARK", "STARR RODENHURST", "TRANG CANAVAN", "SAHIL MULTANI"]


def _board(path: Path) -> Path:
    """A tiny Tableau-like table: grey rules, dark borders, one name per row."""
    im = Image.new("RGB", (500, 20 + 16 * len(NAMES)), "white")
    d = ImageDraw.Draw(im)
    for i, n in enumerate(NAMES):
        y = 10 + 16 * i
        d.text((14, y + 2), n, fill="black")
        d.text((300, y + 2), str(10 * (i + 1)), fill="black")
        d.line([(10, y + 15), (480, y + 15)], fill=(200, 200, 200))
    d.line([(10, 10), (10, 10 + 16 * len(NAMES))], fill=(60, 60, 60))
    d.line([(250, 10), (250, 10 + 16 * len(NAMES))], fill=(60, 60, 60))
    im.save(path)
    return path


class RowsTest(unittest.TestCase):
    def test_one_band_per_row_and_paint_turns_it_yellow(self):
        with tempfile.TemporaryDirectory() as d:
            p = _board(Path(d) / "b.png")
            bands = H.rows_of(Image.open(p))
            self.assertEqual(len(bands), len(NAMES))
            out = H.highlighted(p, "starr", [bands[1]])
            top, bot, segs = bands[1]
            r, g, b = Image.open(out).convert("RGB").getpixel(
                (segs[0][0] + 2, (top + bot) // 2))
            self.assertGreater(r, 200)
            self.assertLess(b, 120)          # yellow, not white
            # the row above is untouched
            self.assertEqual(Image.open(out).convert("RGB").getpixel(
                (segs[0][0] + 2, bands[0][0] + 1)), (255, 255, 255))


class MatchTest(unittest.TestCase):
    def test_exact_truncated_and_wrong(self):
        self.assertTrue(H._matches("STARR RODENHURST", ["Starr Rodenhurst"]))
        self.assertTrue(H._matches("CHRISTOPHER HU", ["Christopher Hurst"]))
        self.assertFalse(H._matches("STEVEN SYKES", ["Starr Rodenhurst"]))
        self.assertFalse(H._matches("STA", ["Starr Rodenhurst"]))

    def test_a_wrong_answer_from_claude_is_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            p = _board(Path(d) / "b.png")
            fake = [{"name": "Starr Rodenhurst", "band": 3,
                     "text_read": "TRANG CANAVAN"}]
            with mock.patch.object(H, "_ask", return_value=fake):
                self.assertEqual(H.locate(p, {"Starr Rodenhurst":
                                              ["Starr Rodenhurst"]}), {})


class WhoTest(unittest.TestCase):
    def tearDown(self):
        H.FORCE = False

    def test_switched_off_means_plain_everywhere(self):
        H.FORCE = False
        with mock.patch.object(H, "LIVE", False),                 mock.patch.object(H, "locate") as loc:
            hl = H.Highlighter(rows=self.ROWS, eco={H.norm("Starr Rodenhurst")})
            self.assertEqual(hl.png_for("C1", "x.png"), "x.png")
            loc.assert_not_called()

    ROWS = [
        {"key": "starr", "owner": "Starr Rodenhurst", "channel_ids": ["C1"]},
        {"key": "nii", "owner": "Nii Tagoe", "channel_ids": ["C2"]},
        {"key": "joseph", "owner": "Joseph Logan", "emails": ["x@y.z"]},
    ]

    def test_only_eco_slack_channels(self):
        eco = {H.norm("Starr Rodenhurst"), H.norm("Joseph Logan")}
        self.assertEqual(H.channel_owners(self.ROWS, eco),
                         {"C1": "Starr Rodenhurst"})

    def test_non_eco_channel_and_shared_channel_get_the_plain_png(self):
        H.FORCE = True
        hl = H.Highlighter(rows=self.ROWS, eco={H.norm("Starr Rodenhurst")})
        with mock.patch.object(H, "locate") as loc:
            self.assertEqual(hl.png_for("C2", "x.png"), "x.png")
            self.assertEqual(hl.png_for("C_ALPHALETE", "x.png"), "x.png")
            loc.assert_not_called()

    def test_eco_channel_gets_its_own_row(self):
        with tempfile.TemporaryDirectory() as d:
            p = _board(Path(d) / "b.png")
            band = H.rows_of(Image.open(p))[1]
            H.FORCE = True
            hl = H.Highlighter(rows=self.ROWS,
                               eco={H.norm("Starr Rodenhurst")})
            with mock.patch.object(H, "locate",
                                   return_value={"Starr Rodenhurst": [band]}), \
                    mock.patch.object(H, "spellings", side_effect=lambda o: [o]):
                out = hl.png_for("C1", p, {"id": "att_country"})
            self.assertNotEqual(Path(out), p)
            self.assertTrue(Path(out).exists())
            self.assertEqual(hl.owner_for_org("starr"), "Starr Rodenhurst")
            self.assertEqual(hl.owner_for_org("nii"), "")

    def test_claude_failure_posts_plain_and_switches_off(self):
        H.FORCE = True
        hl = H.Highlighter(rows=self.ROWS, eco={H.norm("Starr Rodenhurst")})
        with mock.patch.object(H, "locate", side_effect=RuntimeError("no key")), \
                mock.patch.object(H, "spellings", side_effect=lambda o: [o]):
            self.assertEqual(hl.png_for("C1", "a.png"), "a.png")
        with mock.patch.object(H, "locate") as loc:
            self.assertEqual(hl.png_for("C1", "b.png"), "b.png")
            loc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
