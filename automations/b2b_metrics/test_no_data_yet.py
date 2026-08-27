"""A new office with no data yet is not a failure.

2026-08-27: Sabrina was onboarded the night before and enrolled in wireless /
INT / AIR churn before her office had any. All three rendered blank, and the
blank-render guard (correctly) refused to post empty boards — but it filed them
as MISSES, which cost three things every single morning:

  * her thread showed a silent hole (8 of the 11 its header promised)
  * #claudecorrections got a 🚨 incident
  * the ONE shared b2b-metrics Hub card read "partial" for Carlos, Atef and
    Jamis too, none of whom had anything wrong

and none of it would have stopped until a human remembered to re-enrol her.
Megan: "if there isn't data yet, it should just say that and then when the data
comes in start posting it. We can't remember to go in and check to add all
metrics."

The discriminator is whether this office has EVER had data for the section.
That preserves the 2026-08-17 rule — a section that HAS produced data and goes
blank is a regression and must still page loudly (Carlos's blank board, 8/25).
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from automations.b2b_metrics import runner as r


class EverPostedLedger(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.p = Path(self._tmp.name) / "_ever_posted.json"
        self._patch = mock.patch.object(r, "_EVER_POSTED", self.p)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_unknown_office_section_has_never_posted(self):
        self.assertFalse(r.has_ever_posted("sabrina", "churn_air"))

    def test_recording_a_post_flips_it(self):
        import datetime as dt
        r.record_ever_posted("sabrina", "churn_air", dt.date(2026, 9, 4))
        self.assertTrue(r.has_ever_posted("sabrina", "churn_air"))
        self.assertFalse(r.has_ever_posted("sabrina", "churn_int"))
        self.assertFalse(r.has_ever_posted("carlos", "churn_air"))

    def test_ledger_is_per_office_not_global(self):
        """Carlos having churn_air must never silence Sabrina's, or a genuinely
        new office inherits another office's history and goes quiet wrongly."""
        import datetime as dt
        r.record_ever_posted("carlos", "churn_air", dt.date(2026, 9, 4))
        self.assertFalse(r.has_ever_posted("sabrina", "churn_air"))

    def test_a_corrupt_ledger_reads_as_nothing_recorded(self):
        self.p.write_text("{not json")
        self.assertFalse(r.has_ever_posted("sabrina", "churn_air"))

    def test_recording_never_raises(self):
        """Bookkeeping must not cost a post that already succeeded."""
        with mock.patch.object(r, "_EVER_POSTED", Path("/nope/cannot/write.json")):
            r.record_ever_posted("sabrina", "churn_air", "2026-09-04")  # no raise

    def test_survives_a_lost_file_by_self_healing(self):
        import datetime as dt
        r.record_ever_posted("sabrina", "churn_air", dt.date(2026, 9, 4))
        self.p.unlink()
        self.assertFalse(r.has_ever_posted("sabrina", "churn_air"))
        r.record_ever_posted("sabrina", "churn_air", dt.date(2026, 9, 5))
        self.assertTrue(r.has_ever_posted("sabrina", "churn_air"))


class NoDataIsNotAMiss(unittest.TestCase):
    """The three surfaces the old behaviour got wrong."""

    def test_no_data_stays_out_of_missed(self):
        items = [{"id": "churn_air"}, {"id": "sales_metrics"}]
        all_present = {"sales_metrics"}
        no_data = {"churn_air"}
        missed = [i["id"] for i in items
                  if i["id"] not in all_present and i["id"] not in no_data]
        self.assertEqual(missed, [])          # → Hub card stays green

    def test_a_real_miss_is_still_a_miss(self):
        items = [{"id": "churn_air"}, {"id": "order_log"}]
        all_present = set()
        no_data = {"churn_air"}
        missed = [i["id"] for i in items
                  if i["id"] not in all_present and i["id"] not in no_data]
        self.assertEqual(missed, ["order_log"])

    def test_note_key_is_not_the_section_id(self):
        """THE subtle one. If the note were recorded under the real section id,
        tomorrow's pre-capture dedup would skip the section and it would never
        notice the data arriving — defeating the whole feature."""
        sid = "churn_air"
        note_key = "{}__nodata".format(sid)
        already = [note_key]
        self.assertNotIn(sid, already)

    def test_source_keeps_the_section_out_of_already(self):
        src = Path(r.__file__).read_text()
        block = src.split("for sid in no_data:")[1].split("per_chan_posted.append")[0]
        self.assertIn("__nodata", block)
        self.assertNotIn("already.append(sid)", block)


class RegressionsStillPage(unittest.TestCase):
    def test_blank_after_a_good_day_is_not_silenced(self):
        """Carlos 2026-08-25: a section that HAS data rendering blank is the
        incident this guard was built for. It must stay loud."""
        src = Path(r.__file__).read_text()
        branch = src.split("except BlankRender as br:")[1].split("except Exception")[0]
        self.assertIn("has_ever_posted", branch)
        # the loud path must NOT mark it deferred/no_data
        loud = branch.split("else:")[0]
        self.assertNotIn("no_data.append", loud)
        self.assertNotIn("deferred.append", loud)
        # the quiet path must do both
        quiet = branch.split("else:")[1]
        self.assertIn("no_data.append", quiet)
        self.assertIn("deferred.append", quiet)


if __name__ == "__main__":
    unittest.main()
