"""Pure tests for penetration_shot's URL (the live part was proven in Chrome)."""
import unittest
from urllib.parse import unquote

from automations.captainship_drafts import penetration_shot as P


class T(unittest.TestCase):
    def test_url_filters_owners_only(self):
        u = unquote(P.view_url(["Kash Rai", "Trang Canavan"]))
        self.assertIn("Owner Name=Kash Rai,Trang Canavan", u)
        # these two blank the board when put in the link (11/26)
        self.assertNotIn("Penetration View", u)
        self.assertNotIn("Account Captain Email", u)

    def test_section_is_preview_only(self):
        from automations.captainship_drafts import config
        self.assertNotIn("penetration",
                         [k for _, k in config.BY_KEY["rafael"].sections])


if __name__ == "__main__":
    unittest.main()
