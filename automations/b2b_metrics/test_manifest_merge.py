"""A scoped b2b_metrics repair has to be able to close the day out.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.b2b_metrics.test_manifest_merge

WHAT THIS GUARDS (Megan 2026-08-25). `_write_manifest` used to be gated on
`publishable`, which is false for ANY `--only` run — so a scoped re-post wrote no
manifest at all. Skipping stopped a one-section run from clobbering the full
run's result, and it did, but it also meant the re-run that FIXED the section
never cleared it: the manifest kept naming `carlos: order_tiered_bonus` as
missing, the report kept verifying INCOMPLETE, and it kept asking for the same
repair. Carlos's 8/25 thread collected a duplicate Activation Rate and two extra
Customer Churns before anyone could tell the alert was describing a problem that
no longer existed — while the section it was actually complaining about had been
sitting in the thread since 08:44.

Same defect, same morning, as the one 31db227 fixed for daily_metrics.

The contract has two halves and BOTH are load-bearing:

  scoped run  -> MERGES: sections it ran are replaced, sections it didn't keep
                 whatever the full run said. That is what lets a repair clear
                 the day.
  full run    -> STATES: it speaks for everything, no merge.

And the guard rails around them: yesterday's manifest is never merged into, a
scoped run with no manifest from today invents nothing, and a scoped run that
CRASHES reports only its own section as missing — claiming the full set there
would re-open a day that was clean.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.b2b_metrics import runner

TODAY = dt.date.today().isoformat()
YESTERDAY = (dt.date.today() - dt.timedelta(days=1)).isoformat()


def _manifest(succeeded, failed, day=TODAY):
    return {"run_ts": day + "T04:00:00", "succeeded": list(succeeded),
            "failed": list(failed)}


class _Written:
    """Captures the write_manifest call instead of touching disk."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, report_id, **kw):
        self.calls.append(dict(report_id=report_id, **kw))

    @property
    def last(self):
        return self.calls[-1]


@contextlib.contextmanager
def _stubbed(fake):
    """Install `fake` as automations.shared.run_manifest, on BOTH resolution
    paths, with the real module's output dir sandboxed underneath.

    `runner._write_manifest` does `from automations.shared import run_manifest`,
    and once anything in the process has genuinely imported that submodule, the
    import resolves through the PACKAGE ATTRIBUTE, not sys.modules — so a
    sys.modules-only patch is silently bypassed. That made these tests
    order-dependent: green on their own, and in a full-suite run (where
    daily_metrics/test_manifest_merge imports run_manifest for real first) they
    called the REAL write_manifest, left the recorder empty, and failed with an
    IndexError that pointed nowhere near the cause. Worse than the red: the real
    call WROTE output/manifests/b2b_metrics.json — a fixture claiming a clean
    run, for a report that runs on Lucy 2, sitting exactly where the Hub reads
    run outcomes (Megan 2026-08-25).

    So: patch the attribute too, and point MANIFEST_DIR at a temp dir whatever
    happens. A stub that degrades to writing production data is not a stub.
    """
    import automations.shared as _pkg
    from automations.shared import run_manifest as _real
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict("sys.modules",
                             {"automations.shared.run_manifest": fake}), \
             mock.patch.object(_pkg, "run_manifest", fake), \
             mock.patch.object(_real, "MANIFEST_DIR", Path(tmp)):
            yield


def _run_write(per_office, *, scoped, prior):
    """Call _write_manifest with run_manifest stubbed; returns the recorder."""
    w = _Written()
    fake = mock.Mock()
    fake.write_manifest = w
    fake.read_manifest = mock.Mock(return_value=prior)
    with _stubbed(fake):
        runner._write_manifest(per_office, scoped=scoped)
    return w


# The morning this came from: the 4am full run posted 10 of Carlos's 11 sections
# and dropped order_tiered_bonus.
FULL_RUN_PRIOR = _manifest(
    succeeded=["carlos: sales_metrics", "carlos: activation_rate",
               "carlos: churn_wireless", "carlos: order_log"],
    failed=["carlos: order_tiered_bonus"])

# ...then the scoped repair re-posted just that one, successfully.
REPAIR = [{"key": "carlos", "present": ["order_tiered_bonus"], "missed": [],
           "deferred": [], "failed": False}]


class AScopedRepairClosesTheDay(unittest.TestCase):

    def test_the_repaired_section_leaves_failed(self):
        """THE BUG. Until this, the fix could never clear its own alert."""
        w = _run_write(REPAIR, scoped=True, prior=FULL_RUN_PRIOR)
        self.assertEqual(w.last["failed"], [])

    def test_the_repaired_section_lands_in_succeeded(self):
        w = _run_write(REPAIR, scoped=True, prior=FULL_RUN_PRIOR)
        self.assertIn("carlos: order_tiered_bonus", w.last["succeeded"])

    def test_it_appears_exactly_once(self):
        """It was in failed[] before; it must not now be in BOTH lists, nor
        twice in one."""
        w = _run_write(REPAIR, scoped=True, prior=FULL_RUN_PRIOR)
        self.assertEqual(w.last["succeeded"].count("carlos: order_tiered_bonus"), 1)
        self.assertNotIn("carlos: order_tiered_bonus", w.last["failed"])

    def test_untouched_sections_keep_their_verdict(self):
        """The whole reason skipping existed — a one-section run must not wipe
        the other ten."""
        w = _run_write(REPAIR, scoped=True, prior=FULL_RUN_PRIOR)
        for sid in ("carlos: sales_metrics", "carlos: activation_rate",
                    "carlos: churn_wireless", "carlos: order_log"):
            self.assertIn(sid, w.last["succeeded"])

    def test_another_offices_failure_is_not_cleared_by_carlos_repair(self):
        """Sections are namespaced by office; a repair for one must not vouch
        for another."""
        prior = _manifest(succeeded=[], failed=["carlos: order_tiered_bonus",
                                                "atef: sales_metrics"])
        w = _run_write(REPAIR, scoped=True, prior=prior)
        self.assertEqual(w.last["failed"], ["atef: sales_metrics"])

    def test_a_still_failing_repair_stays_failed(self):
        """A repair that ran and missed again must not read as fixed."""
        again = [{"key": "carlos", "present": [], "missed": ["order_tiered_bonus"],
                  "deferred": [], "failed": False}]
        w = _run_write(again, scoped=True, prior=FULL_RUN_PRIOR)
        self.assertIn("carlos: order_tiered_bonus", w.last["failed"])

    def test_a_prior_office_run_failed_tag_is_still_recognised(self):
        """The crash path records '<office>: <section> (office run failed)'. The
        repair has to match that entry, or the tagged copy survives forever."""
        prior = _manifest(
            succeeded=[],
            failed=["carlos: order_tiered_bonus (office run failed)"])
        w = _run_write(REPAIR, scoped=True, prior=prior)
        self.assertEqual(w.last["failed"], [])


class AFullRunJustStatesTheResult(unittest.TestCase):

    def test_a_full_run_does_not_merge(self):
        """It speaks for everything, so yesterday's ghosts must not ride along."""
        stale = _manifest(succeeded=["carlos: gone_section"],
                          failed=["carlos: also_gone"])
        full = [{"key": "carlos", "present": ["sales_metrics"], "missed": [],
                 "deferred": [], "failed": False}]
        w = _run_write(full, scoped=False, prior=stale)
        self.assertEqual(w.last["succeeded"], ["carlos: sales_metrics"])
        self.assertEqual(w.last["failed"], [])

    def test_a_full_run_never_reads_the_prior_manifest(self):
        fake = mock.Mock()
        fake.write_manifest = _Written()
        fake.read_manifest = mock.Mock(return_value=FULL_RUN_PRIOR)
        full = [{"key": "carlos", "present": ["sales_metrics"], "missed": [],
                 "deferred": [], "failed": False}]
        with _stubbed(fake):
            runner._write_manifest(full, scoped=False)
        fake.read_manifest.assert_not_called()


class TheGuardRails(unittest.TestCase):

    def test_yesterdays_manifest_is_never_merged_into(self):
        """Merging it would resurrect yesterday's missing sections into today."""
        old = _manifest(succeeded=[], failed=["carlos: churn_air"],
                        day=YESTERDAY)
        w = _run_write(REPAIR, scoped=True, prior=old)
        self.assertEqual(w.calls, [], "nothing may be written")

    def test_no_manifest_today_means_write_nothing(self):
        """A one-section run can't vouch for the others, so it leaves the state
        alone rather than inventing a day."""
        w = _run_write(REPAIR, scoped=True, prior=None)
        self.assertEqual(w.calls, [])

    def test_a_bookkeeping_failure_never_raises(self):
        """A manifest write must NEVER sink the report."""
        fake = mock.Mock()
        fake.read_manifest = mock.Mock(side_effect=RuntimeError("disk gone"))
        fake.write_manifest = mock.Mock(side_effect=RuntimeError("disk gone"))
        with _stubbed(fake):
            runner._write_manifest(REPAIR, scoped=True)      # must not raise
            runner._write_manifest(REPAIR, scoped=False)     # must not raise


class EntryIdentity(unittest.TestCase):
    """_entry_base is what makes a repair recognise its own prior entry."""

    def test_the_crash_tag_is_stripped(self):
        self.assertEqual(
            runner._entry_base("carlos: order_log (office run failed)"),
            "carlos: order_log")

    def test_a_plain_entry_is_unchanged(self):
        self.assertEqual(runner._entry_base("carlos: order_log"),
                         "carlos: order_log")

    def test_a_section_whose_name_merely_contains_the_words_is_untouched(self):
        plain = "carlos: office run failed report"
        self.assertEqual(runner._entry_base(plain), plain)


if __name__ == "__main__":
    unittest.main()
