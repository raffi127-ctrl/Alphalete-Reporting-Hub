import datetime as dt
import unittest
from unittest import mock

from automations.lumen_owners import knocks as KN


class KnocksTest(unittest.TestCase):
    def test_same_owner_list_as_chans_captainship(self):
        with mock.patch("automations.shared.terminated_icds.terminated_lookup",
                        return_value=lambda n: False):
            pairs = KN.owner_boards({}, logfn=lambda *a: None)
        self.assertIn("David Pancoast (Quantum Fiber)", [l for l, _c in pairs])
        self.assertTrue(all(c["campaign_id"] == "7" for _l, c in pairs))

    def test_nobody_configured_means_no_blocks_and_no_login(self):
        with mock.patch.object(KN, "owner_boards", return_value=[]):
            self.assertEqual(KN.build(dt.date(2026, 10, 23), "x", {}), ([], []))

    def test_failed_board_is_a_note(self):
        s = KN.note_html([("David Pancoast (Quantum Fiber)", "no knocks")])
        self.assertIn("David Pancoast (Quantum Fiber)", s)
        self.assertIn("could not be pulled", s)


    def test_boards_go_as_one_attached_pdf(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from automations.shared import report_email as RE
        tmp = Path(tempfile.mkdtemp())
        png = tmp / "b.png"
        Image.new("RGB", (40, 20), "white").save(png)
        from automations.captainship_drafts.pdf_pages import compose
        pdf = compose([("David Pancoast (Quantum Fiber)", png)], tmp / "k.pdf")
        msg = RE.build_message(
            subject="s", to=["a@x.com"], title="Lumen Owners",
            blocks=[(KN.PDF_LABEL, None, None, "attached")],
            files=[(KN.PDF_LABEL, pdf)])
        atts = [(p.get_filename(), p.get_content_type())
                for p in msg.iter_attachments()]
        self.assertIn("application/pdf", [t for _n, t in atts])
        self.assertTrue(any(n and n.endswith(".pdf") for n, _t in atts))


if __name__ == "__main__":
    unittest.main()
