"""A metrics thread that POSTED must not be alerted as one that didn't.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_metric_kind_wording

WHAT THIS GUARDS (2026-09-08). `office_metrics.runner` writes kind="metric"
from both of its `write_manifest` calls, and there was no such kind in
section_drop_alert._KINDS — so it fell through to 'section'. The runner said so
itself, in the log, on the way past:

    ⚠ section-drop alert: kind 'metric' has no wording — falling back to
      'section' ("it did NOT post"), which may be wrong. Add it to _KINDS.

It was wrong. Both hammad_metrics and daily_metrics dropped ONE metric that
morning; each had posted every other one, and each got:

    dropped 1 section this run — it did NOT post.
    The thread is live but incomplete.

The thread had posted. daily_metrics' own note on the same alert read
"8/9 metrics posted to #alphalete-sales", its churn sheets had filled
(0-30/30/60/90-day = 49/46/52/54 rows) and three of its four charts had
uploaded — only one `files.completeUploadExternal` call had failed. "It did NOT
post" sends the reader hunting a thread that is sitting in the channel.

Same mistake, same fix as `owner` in [[test_expected_miss_wording]]: a kind
nobody worded gets described by whichever kind it aliased to.
"""
from __future__ import annotations

import unittest

from automations.shared import section_drop_alert as sda


class TheMetricKind(unittest.TestCase):
    def test_metric_kind_exists(self):
        """Absent, it aliases to 'section' — which is the whole bug."""
        self.assertIn("metric", sda._KINDS)
        self.assertEqual(sda._KINDS["metric"]["what"], "metric")

    def test_it_never_claims_the_thread_did_not_post(self):
        blob = " ".join(str(v) for v in sda._KINDS["metric"].values()).lower()
        self.assertNotIn("did not post", blob)
        self.assertNotIn("thread is live but incomplete", blob)

    def test_it_is_not_in_the_fill_shaped_passlist(self):
        """_FILL_SHAPED means 'reads fine as a section'. This one does not, so
        listing it there would silence the warning without fixing the wording."""
        self.assertNotIn("metric", sda._FILL_SHAPED)

    def test_the_tail_headline_survives_any_count(self):
        """`headline` is formatted with tail=tail_headline, so the tail is
        substituted VERBATIM — a `{s}` inside it is never expanded. It has to
        read correctly for one metric and for several."""
        spec = sda._KINDS["metric"]
        self.assertNotIn("{", spec["tail_headline"])
        for n in (1, 3):
            line = spec["headline"].format(
                tail=spec["tail_headline"], report_id="hammad_metrics",
                n=n, what=spec["what"], s="s" if n != 1 else "", items="")
            self.assertNotIn("{", line)


class TheComposedAlert(unittest.TestCase):
    """The real 2026-09-08 hammad_metrics payload, end to end."""

    FAILED = ["🌐 New Internet + 📊 Wireless Churn"]
    NOTE = "8/9 metrics posted to #elite-prime-sales; failed: churn"

    def _blob(self):
        return sda._compose("hammad_metrics", self.FAILED, None,
                            self.NOTE, kind="metric")

    def test_it_no_longer_says_the_thread_did_not_post(self):
        self.assertNotIn("it did NOT post", self._blob())

    def test_it_says_metric_not_section(self):
        blob = self._blob()
        self.assertIn("dropped 1 metric this run", blob)
        self.assertNotIn("dropped 1 section this run", blob)

    def test_it_still_names_what_is_missing_and_carries_the_note(self):
        blob = self._blob()
        self.assertIn("New Internet", blob)
        self.assertIn("8/9 metrics posted", blob)

    def test_a_caller_supplied_fix_still_wins(self):
        """daily_metrics passes its own scoped `lucy rerun … --only churn`
        line; the kind's default must not override it."""
        blob = sda._compose(
            "daily_metrics", self.FAILED,
            {"fix": "lucy rerun daily_metrics --only churn"},
            self.NOTE, kind="metric")
        self.assertIn("lucy rerun daily_metrics --only churn", blob)

    def test_no_unexpanded_placeholder_reaches_slack(self):
        self.assertNotIn("{", self._blob())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
