"""Office websites: unique per office, and built to pass Lucy's own audit."""
import re
import tempfile
import unittest
from pathlib import Path

from automations.online_presence import offices, site_builder as SB, site_copy

COPY = {k: f"{k} text" for k in site_copy.FIELDS}
COPY["hero_h1"] = "Line one\nLine two"


def _office(key="kash", **kw):
    base = dict(key=key, business_name="Kash Marketing", slack_channel="C1",
                address="100 Main Street, Suite 2, Dallas, TX 75201", phone="(214) 555-0100",
                website="https://kashmarketing.com", contact_email="careers@kashmarketing.com",
                instagram_url="https://www.instagram.com/kashmktg/", facebook_url="https://www.facebook.com/kashmktg")
    base.update(kw)
    return offices.Presence(**base)


class Builds(unittest.TestCase):
    def _build(self, p, extra=None):
        out = Path(tempfile.mkdtemp()) / p.key
        SB.build(p, out=out, extra=extra or {}, copy=COPY)
        return out

    def test_every_page_carries_name_address_phone_and_socials(self):
        out = self._build(_office())
        for page, _ in SB.PAGES:
            s = (out / page).read_text()
            self.assertIn("<title>Kash Marketing |", s)
            self.assertIn("100 Main Street, Suite 2, Dallas, TX 75201", s)
            self.assertIn("(214) 555-0100", s)
            self.assertIn("https://www.instagram.com/kashmktg/", s)
            self.assertIn('"@type": "LocalBusiness"', s)
        self.assertEqual((out / "CNAME").read_text().strip(), "kashmarketing.com")
        self.assertIn("https://kashmarketing.com/apply/", (out / "sitemap.xml").read_text())

    def test_no_pay_numbers_unless_the_office_gives_its_own(self):
        out = self._build(_office())
        self.assertNotRegex((out / "index.html").read_text(), r"\$\d")
        out = self._build(_office(), {"pay": [{"stage": "Entry", "time": "Weeks 1-4", "pay": "$900/wk"}]})
        self.assertIn("$900/wk", (out / "index.html").read_text())

    def test_nothing_reads_like_a_placeholder(self):
        s = (self._build(_office()) / "index.html").read_text().lower()
        for bad in ("placeholder", "lorem", "your photo", "photo here", "logo</span>"):
            self.assertNotIn(bad, s)

    def test_offices_get_different_looks(self):
        looks = {SB.pick_theme(_office(key=k), {}) for k in ("kash", "cyrus", "aya", "raf", "aiden", "nicolas")}
        self.assertGreater(len(looks), 1)
        self.assertEqual(SB.pick_theme(_office(), {"theme": "warm"}), "warm")

    def test_photos_are_used_and_counted(self):
        tmp = Path(tempfile.mkdtemp())
        photos = []
        for i in range(3):
            ph = tmp / f"p{i}.jpg"
            ph.write_bytes(b"\xff\xd8fake")
            photos.append(str(ph))
        out = self._build(_office(), {"photos": photos})
        self.assertTrue((out / "img" / "1.jpg").exists())
        self.assertIn('src="img/1.jpg"', (out / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
