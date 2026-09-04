"""Why somebody stops being removed from the Mobrium List, and the three
reasons it used to happen silently (2026-09-04).

    python -m unittest automations.mobrium_list.test_removals -v

1. A LIVE OWNERVILLE ROW IS NOT A REHIRE. Retiring an account is a human's
   job (the tracker's own 'Ownerville' tick records that somebody went and did
   it), so a record nobody got around to retiring used to age past
   REHIRE_LAG_DAYS and turn into a permanent "rehired — keeping" that nothing
   could age back out of. The same veto runs on the ADD side, so the next
   week's new-starts box put the person straight back on.
2. THE BOARD'S OWN FILING FILTERS BLINDED THE READER. `scan_full` drops a
   previous tab's terminations older than four days and drops this tab's T
   marks when the previous tab already carried them — right for the tracker,
   which appends a row per termination, wrong for a weekly reader: a rep
   marked after Friday's run falls through both by the next Friday. On
   2026-09-04 the board's last three weeks named 87 people and `scan`
   returned 32. `marked_names` is the unfiltered read.
3. A NEAR-MISS SPELLING IS NOT A REMOVAL, BUT IT IS NOT SILENCE EITHER. The
   contact lookup matches loosely and removals match exactly, so the two can
   disagree; the run now names anyone caught in the gap.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.mobrium_list import board as mboard
from automations.mobrium_list import plan as mplan
from automations.mobrium_list import sheet as msheet
from automations.mobrium_list import terminated as mterm
from automations.mobrium_list.ownerville import Directory, Rep

TODAY = dt.date(2026, 9, 4)


def entry(row, first, last):
    return msheet.Entry(row=row, first=first, last=last, email="e@x.com",
                        phone="(817) 600-2840")


def index(*, tracker=(), board=(), checks=(), active=()):
    """A TerminatedIndex without a Sheet. `tracker` is (name, date, notes)."""
    records = {}
    for name, date, notes in tracker:
        rec = mterm.Record(name=name, rows=[1])
        if date:
            rec.dates.append(date)
        if notes:
            rec.notes.add(notes)
        records[mterm.norm_name(name)] = rec
    return mterm.TerminatedIndex(
        records,
        {mterm.norm_name(n): (n, d) for n, d in board},
        {mterm.norm_name(n): (n, why) for n, why in checks},
        {mterm.norm_name(n): n for n in active})


def directory(*reps):
    return Directory(reps)


def rep(name, start="", roster="active"):
    first, _, last = name.partition(" ")
    return Rep(first=first, last=last, email="e@x.com", phone="817-600-2840",
               start=start, retired="", roster=roster)


def box(name):
    return [mboard.NewStart(name=name, email="", phone="",
                            tab="Sales Board WE 9.6", row=90)]


class RehireNeedsEvidence(unittest.TestCase):

    def test_a_stale_ownerville_account_is_not_a_rehire(self):
        """Terminated 16 days ago, no start date since, not on this week's
        board — an account nobody retired, not a return."""
        term = index(tracker=[("Alexis Streit", dt.date(2026, 8, 19), "")])
        dr = directory(rep("Alexis Streit", start="07-14-2026"))
        self.assertFalse(mplan.rehired("Alexis Streit", term, dr, TODAY))
        p = mplan.build([entry(2, "Alexis", "Streit")], [], term, dr, TODAY)
        self.assertEqual([r.entry.full for r in p.removals], ["Alexis Streit"])

    def test_an_ownerville_start_after_the_termination_is_a_rehire(self):
        term = index(tracker=[("Myra Singleton", dt.date(2026, 7, 31), "")])
        dr = directory(rep("Myra Singleton", start="08-11-2026"))
        self.assertTrue(mplan.rehired("Myra Singleton", term, dr, TODAY))
        p = mplan.build([entry(2, "Myra", "Singleton")], [], term, dr, TODAY)
        self.assertEqual(p.removals, [])
        self.assertIn("start date after", p.kept[0].why)

    def test_this_weeks_board_working_is_a_rehire(self):
        """Tadana Manyangadze: terminated 5/29, on the board in August."""
        term = index(tracker=[("Tadana Manyangadze", dt.date(2026, 5, 29), "")],
                     active=["Tadana Manyangadze"])
        dr = directory(rep("Tadana Manyangadze", start="01-06-2025"))
        self.assertTrue(mplan.rehired("Tadana Manyangadze", term, dr, TODAY))
        p = mplan.build([entry(2, "Tadana", "Manyangadze")], [], term, dr, TODAY)
        self.assertEqual(p.removals, [])

    def test_ownerville_lag_still_beats_everything(self):
        """Karla Lopez, terminated yesterday and still active: not a rehire,
        and not kept."""
        term = index(board=[("Karla Lopez", dt.date(2026, 9, 3))])
        dr = directory(rep("Karla Lopez", start="08-25-2026"))
        self.assertFalse(mplan.rehired("Karla Lopez", term, dr, TODAY))
        p = mplan.build([entry(2, "Karla", "Lopez")], [], term, dr, TODAY)
        self.assertEqual([r.entry.full for r in p.removals], ["Karla Lopez"])

    def test_ffp_still_shields(self):
        term = index(tracker=[("Basil Elhassan", None, "FFP")])
        dr = directory(rep("Basil Elhassan", start="02-03-2026"))
        p = mplan.build([entry(2, "Basil", "Elhassan")], [], term, dr, TODAY)
        self.assertEqual(p.removals, [])
        self.assertIn("FFP", p.kept[0].why)

    def test_absence_from_ownerville_never_keeps_anyone(self):
        term = index(board=[("Ivan Soto", dt.date(2026, 9, 4))])
        p = mplan.build([entry(2, "Ivan", "Soto")], [], term, directory(), TODAY)
        self.assertEqual([r.entry.full for r in p.removals], ["Ivan Soto"])


class Reported(unittest.TestCase):

    def test_a_contradicted_t_is_flagged_not_removed(self):
        """Kaleb Muvunyi on WE 8.23: Roll Call 'T' on Wednesday and Thursday
        while Apps and Int both read 1 on the same days."""
        term = index(checks=[("Kaleb Muvunyi", "WE 8.23: Apps and Int read 1")])
        p = mplan.build([entry(2, "Kaleb", "Muvunyi")], [], term,
                        directory(), TODAY)
        self.assertEqual(p.removals, [])
        self.assertEqual([f.entry.full for f in p.flagged], ["Kaleb Muvunyi"])

    def test_a_near_miss_spelling_is_reported_not_removed(self):
        term = index(tracker=[("Deavion Hunter Allen", dt.date(2026, 8, 1), "")])
        p = mplan.build([entry(2, "Deavion", "Allen")], [], term,
                        directory(), TODAY)
        self.assertEqual(p.removals, [])
        self.assertEqual([n.entry.full for n in p.near], ["Deavion Allen"])
        self.assertIn("Deavion Hunter Allen", p.near[0].why)

    def test_a_different_person_is_not_a_near_miss(self):
        term = index(tracker=[("Chris Martinez", dt.date(2026, 8, 1), "")])
        p = mplan.build([entry(2, "Chris", "Martin")], [], term,
                        directory(), TODAY)
        self.assertEqual(p.near, [])


class NoLongerReAdded(unittest.TestCase):
    """The ADD side runs the same veto, so the old rule put back what the
    previous run had removed."""

    def test_a_terminated_new_start_is_not_re_added(self):
        term = index(tracker=[("Alexis Streit", dt.date(2026, 8, 19), "")])
        dr = directory(rep("Alexis Streit", start="07-14-2026"))
        p = mplan.build([], box("Alexis Streit"), term, dr, TODAY)
        self.assertEqual(p.additions, [])
        self.assertEqual(len(p.skipped), 1)
        self.assertIn("already terminated", p.skipped[0].why)

    def test_a_real_rehire_in_the_box_is_still_added(self):
        term = index(tracker=[("Tadana Manyangadze", dt.date(2026, 5, 29), "")],
                     active=["Tadana Manyangadze"])
        dr = directory(rep("Tadana Manyangadze", start="01-06-2025"))
        p = mplan.build([], box("Tadana Manyangadze"), term, dr, TODAY)
        self.assertEqual([a.full for a in p.additions], ["Tadana Manyangadze"])


if __name__ == "__main__":
    unittest.main()
