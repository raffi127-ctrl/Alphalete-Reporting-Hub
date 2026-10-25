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
        # Raf 2026-10-25: Christian + Lala too, not only Chan's owners.
        labels = [l for l, _c in pairs]
        self.assertIn("Christian Esposito (Quantum Fiber)", labels)
        self.assertIn("Lajahnik Valentine (Quantum Fiber)", labels)
        self.assertIn("Nigel Marshall (Quantum Fiber)", labels)
        self.assertEqual(len(labels), len(set(labels)))

    def test_nobody_configured_means_no_blocks_and_no_login(self):
        with mock.patch.object(KN, "owner_boards", return_value=[]):
            self.assertEqual(KN.build(dt.date(2026, 10, 23), "x", {}), ([], []))

    def test_each_owner_gets_its_own_folder(self):
        # The board file is named by date only; a shared folder made every
        # PDF page the last owner's board (2026-10-25).
        import tempfile
        tmp = tempfile.mkdtemp()
        a = KN.owner_dir(tmp, "Christian Esposito (Quantum Fiber)")
        b = KN.owner_dir(tmp, "Nigel Marshall (Quantum Fiber)")
        self.assertNotEqual(a, b)
        self.assertTrue(a.is_dir() and b.is_dir())

    def test_one_pdf_for_all_plus_one_per_owner(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        tmp = Path(tempfile.mkdtemp())
        blocks = []
        for i, lab in enumerate(["David Pancoast (Quantum Fiber)",
                                 "Nigel Marshall (Quantum Fiber)"]):
            png = KN.owner_dir(tmp, lab) / "total_knocks_2026-10-24.png"
            Image.new("RGB", (40, 20), "white").save(png)
            blocks.append((lab, png))
        files = KN.pdf_files(blocks, dt.date(2026, 10, 24), tmp)
        self.assertEqual([l for l, _p in files], [
            "Lumen Owners - Daily Knocks disposition - Oct 24, 2026",
            "David Pancoast - Daily Knocks disposition - Oct 24, 2026",
            "Nigel Marshall - Daily Knocks disposition - Oct 24, 2026"])
        self.assertEqual(len({str(p) for _l, p in files}), 3)

    def test_weekly_is_the_last_sunday_week(self):
        # Sunday 10/25 and Friday 10/30 both carry Mon 10/19 - Sat 10/24.
        for d in (dt.date(2026, 10, 25), dt.date(2026, 10, 30)):
            self.assertEqual(KN.weekly_window(d),
                             (dt.date(2026, 10, 19), dt.date(2026, 10, 24)))
        self.assertEqual(KN.weekly_window(dt.date(2026, 11, 1))[1],
                         dt.date(2026, 10, 31))
        self.assertEqual(
            KN.weekly_attachment_label(dt.date(2026, 10, 24)),
            "Weekly Knock Dispositions - Lumen Owners - Oct 19-24, 2026")

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
