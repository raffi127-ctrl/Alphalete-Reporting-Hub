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
        src = Path(r.__file__).read_text(encoding="utf-8")
        block = src.split("for sid in no_data:")[1].split("per_chan_posted.append")[0]
        self.assertIn("_nodata_key(sid)", block)
        self.assertNotIn("already.append(sid)", block)

    def test_note_key_helper_matches_the_suffix(self):
        self.assertEqual(r._nodata_key("churn_air"), "churn_air__nodata")
        self.assertTrue(r._nodata_key("x").endswith(r._NODATA_SUFFIX))


class NothingNewPassSpeaksOnlyForWhatItRan(unittest.TestCase):
    """The early return of run() — the ONE place that reports on sections by
    reading the thread state instead of capturing them.

    2026-08-28: a `--only out_of_bounds` repair found that section already in
    every thread, took this path, and reported on the WHOLE office: Sabrina's
    three no-data churns came back as `missed` (their real ids are deliberately
    absent from `posted`), _write_manifest's scoped merge believed it, and a
    fresh 🚨 fired for three sections nobody had touched."""

    def _early_return(self, expected, only, done_all):
        """The early return's arithmetic, in the shape run() computes it."""
        exp = [i for i in expected if not only or i == only]
        nd = {s[:-len(r._NODATA_SUFFIX)] for s in done_all
              if s.endswith(r._NODATA_SUFFIX)}
        return {"no_data": [i for i in exp if i in nd],
                "present": [i for i in exp if i in done_all],
                "missed": [i for i in exp if i not in done_all and i not in nd]}

    EXPECTED = ["sales_metrics", "churn_wireless", "churn_int", "churn_air",
                "out_of_bounds"]
    DONE = {"sales_metrics", "out_of_bounds", "churn_wireless__nodata",
            "churn_int__nodata", "churn_air__nodata"}

    def test_only_pass_reports_on_its_own_section_alone(self):
        got = self._early_return(self.EXPECTED, "out_of_bounds", self.DONE)
        self.assertEqual(got["present"], ["out_of_bounds"])
        self.assertEqual(got["missed"], [])

    def test_a_noted_no_data_section_is_not_a_miss(self):
        got = self._early_return(self.EXPECTED, None, self.DONE)
        self.assertEqual(got["missed"], [])
        self.assertEqual(got["no_data"],
                         ["churn_wireless", "churn_int", "churn_air"])
        self.assertEqual(got["present"], ["sales_metrics", "out_of_bounds"])

    def test_a_genuinely_absent_section_is_still_a_miss(self):
        got = self._early_return(self.EXPECTED, None,
                                 self.DONE - {"sales_metrics"})
        self.assertEqual(got["missed"], ["sales_metrics"])

    def test_source_early_return_is_scoped_and_nodata_aware(self):
        src = Path(r.__file__).read_text(encoding="utf-8")
        block = src.split("nothing new — every expected section")[0]
        block = block.split("if not items:")[-1]
        self.assertIn("if not only or i[\"id\"] == only", block)
        self.assertIn("_NODATA_SUFFIX", block)


class RegressionsStillPage(unittest.TestCase):
    def test_blank_after_a_good_day_is_not_silenced(self):
        """Carlos 2026-08-25: a section that HAS data rendering blank is the
        incident this guard was built for. It must stay loud."""
        src = Path(r.__file__).read_text(encoding="utf-8")
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
