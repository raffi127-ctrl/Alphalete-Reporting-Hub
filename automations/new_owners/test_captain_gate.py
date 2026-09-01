"""Two contracts of the captainship new-rep gate (2026-08-13).

(a) A MATURING COHORT IS NOT A NEW REP.
    Every captainship metrics tab carries a 0-30 section and a 30-60 one, and
    the 30-60 metric is a 30-60-DAYS-AGO cohort. Someone who joined ~45 days
    ago therefore gets their FIRST 30-60 row long after their 0-30 row was
    filled — `insert_missing_reps` reports that row as "added", and the gate
    read it as a new rep. It asked Evelyn for a ✅ on Audrey (Blue) Mendoza on
    2026-08-13, who had been in Starr's boxes on the Org Sales Board since WE
    7.19 and on the 0-30 rows since 7/23; the only possible resolution was
    "already had a row". Left alone it repeats for every rep ~45 days in.
    `observe_added(known=...)` drops those; a rep the tab has never seen still
    opens the gate.

(b) THE ✅ IS THE CONFIRMATION — AND ONLY A FAILURE SPEAKS.
    `resolve()` used to reply in the thread on every add ("added to the Starr
    captainship …"). Eve, 2026-08-13: not wanted — reacting already means "add
    them"; only tell her if something fails. So a clean add says nothing and
    the log tab keeps the record, while a failed add posts in the thread and
    leaves the rep PENDING. That pairing is the contract: without the failure
    notice, silence would mean both "done" and "broken".

Run:  python -m automations.new_owners.test_captain_gate   (or via pytest)

3.9-safe (no walrus, no match, no PEP-604 unions evaluated at runtime).
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from unittest import mock

from automations.new_owners import captain_gate, captain_watch
from automations.org_sales_board.review_gate import APPROVE_EMOJI, APPROVERS

TODAY = dt.date(2026, 8, 13)
GATE_TS = "1786623197.909789"
APPROVER_ID = sorted(APPROVERS)[0]
EMOJI = sorted(APPROVE_EMOJI)[0]


def _sections(*, upper: bool):
    """The {section: {rep_rows: {name: row}}} map the fills build. Cancel Rate
    keys it UPPERCASE, Activation Rate / ABP key it lowercase — both must fold
    to the same set, or the filter silently stops working on one of them."""
    def k(n):
        return n.upper() if upper else n.lower()
    return {
        "0-30": {"header_row": 2, "rep_rows": {k("Starr Rodenhurst"): 11,
                                               k("Audrey Mendoza"): 13}},
        "30-60": {"header_row": 17, "rep_rows": {k("Starr Rodenhurst"): 22}},
    }


class TestNamesOnTab(unittest.TestCase):
    def test_flattens_both_key_casings(self):
        for upper in (True, False):
            got = captain_watch.names_on_tab(_sections(upper=upper))
            self.assertEqual(got, {"starr rodenhurst", "audrey mendoza"},
                             msg="upper=%s" % upper)

    def test_junk_shapes_contribute_nothing_instead_of_raising(self):
        for bad in (None, {}, {"0-30": None}, {"0-30": {}}, {"0-30": {"rep_rows": None}}):
            self.assertEqual(captain_watch.names_on_tab(bad), set())


class TestObserveAddedFiltersMaturingCohorts(unittest.TestCase):
    def setUp(self):
        self.proposed = []

        def _fake_propose(names, **kw):
            self.proposed.append(list(names))
            return [{"name": n, "captain": kw.get("captain"), "ts": None}
                    for n in names]

        p = mock.patch.object(captain_gate, "propose", _fake_propose)
        p.start()
        self.addCleanup(p.stop)

    def test_rep_already_on_the_tab_does_not_open_a_gate(self):
        # Her 30-60 row is new; her 0-30 row is weeks old -> not a new rep.
        added = {"30-60": ["Audrey Mendoza"]}
        out = captain_watch.observe_added(
            added, captain="starr", source="Captainship Cancel Rate",
            known=captain_watch.names_on_tab(_sections(upper=True)),
            logfn=lambda *_a: None)
        self.assertEqual(self.proposed, [[]])
        self.assertEqual(out, [])

    def test_a_genuinely_new_rep_still_opens_the_gate(self):
        added = {"0-30": ["Nikola Vance"], "30-60": ["Audrey Mendoza",
                                                     "Nikola Vance"]}
        out = captain_watch.observe_added(
            added, captain="starr", source="Captainship Cancel Rate",
            known=captain_watch.names_on_tab(_sections(upper=False)),
            logfn=lambda *_a: None)
        self.assertEqual(self.proposed, [["Nikola Vance"]])
        self.assertEqual([a["name"] for a in out], ["Nikola Vance"])

    def test_without_known_nothing_is_filtered(self):
        captain_watch.observe_added(
            {"30-60": ["Audrey Mendoza"]}, captain="starr",
            source="Captainship Cancel Rate", logfn=lambda *_a: None)
        self.assertEqual(self.proposed, [["Audrey Mendoza"]])

    def test_the_skip_is_logged_not_silent(self):
        lines = []
        captain_watch.observe_added(
            {"30-60": ["Audrey Mendoza"]}, captain="starr",
            source="Captainship Cancel Rate",
            known={"Audrey Mendoza"}, logfn=lines.append)
        self.assertTrue(any("Audrey Mendoza" in l for l in lines), lines)


class _FakeBank:
    """Just enough of new_owners.bank for resolve()."""
    KIND_CAPTAINSHIP = "Captainship"

    def __init__(self):
        self.updates = []

    def open_log(self, ss, logfn=print):
        return "LOG_WS"

    def log_entries(self, lws):
        return [{"row": 10, "date": "08/13/2026", "kind": "Captainship",
                 "name": "Audrey Mendoza", "scope": "Starr",
                 "action": "awaiting ✅ (via Captainship Cancel Rate)",
                 "notes": GATE_TS}]

    def thread_anchor(self, lws, key):
        return {"channel": "C0BLLU9M0A2", "ts": "1786623197.113879"}

    def update_log(self, lws, row, *, action=None, notes=None, logfn=print):
        self.updates.append({"row": row, "action": action, "notes": notes})


class TestResolveDoesNotReply(unittest.TestCase):
    def setUp(self):
        self.bank = _FakeBank()
        self.client = mock.Mock()
        self.client.conversations_replies.return_value = {"messages": [
            {"ts": GATE_TS,
             "reactions": [{"name": EMOJI, "users": [APPROVER_ID]}]}]}
        for name, val in (("bank", self.bank),
                          ("cap_insert", mock.Mock()),
                          ("_client", lambda: self.client)):
            p = mock.patch.object(captain_gate, name, val)
            p.start()
            self.addCleanup(p.stop)
        captain_gate.cap_insert.add_rep.return_value = {
            "rows": {}, "already": "leaderboard/new_internet"}

    def test_a_failed_add_DOES_speak_and_stays_pending(self):
        # Silence means "done", so the one case that must never be silent is the
        # ✅ that couldn't be applied (Eve, 2026-08-13: "que solo avise si algo
        # falla"). The log line stays PENDING so the next run retries.
        captain_gate.cap_insert.add_rep.side_effect = ValueError(
            "no leaderboard/daily block found for 'Starr'")
        out = captain_gate.resolve(mock.Mock(), today=TODAY,
                                   logfn=lambda *_a: None)
        self.assertEqual(out["added"], [])
        self.assertEqual(self.bank.updates, [],
                         "a failed add must not be logged as added")
        self.client.chat_postMessage.assert_called_once()
        posted = self.client.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("Audrey Mendoza", posted)
        self.assertIn("Starr", posted)

    def test_approved_rep_is_added_and_logged_with_no_thread_reply(self):
        out = captain_gate.resolve(mock.Mock(), today=TODAY,
                                   logfn=lambda *_a: None)
        self.assertEqual([a["name"] for a in out["added"]], ["Audrey Mendoza"])
        self.assertEqual(out["added"][0]["approved_by"],
                         APPROVERS[APPROVER_ID])
        captain_gate.cap_insert.add_rep.assert_called_once()
        # the record still lands on the log tab…
        self.assertEqual(len(self.bank.updates), 1)
        self.assertIn("added ✅", self.bank.updates[0]["action"])
        # …and nothing is posted back to the channel.
        self.client.chat_postMessage.assert_not_called()


class ExcludedReps(unittest.TestCase):
    """A rep pinned out of a captainship is never offered for that captainship.

    2026-08-18: Atef Choudhury left Carlos' captainship for his own, taking
    Sabrina Alicea, and Joe Eckhart came off it — but Tableau has no Atef captain
    filter yet, so the captain-team pull still reads all three as Carlos' team
    and the gate asked Evelyn to put them back the same morning.
    """

    def test_pinned_rep_is_not_proposed_for_that_captain(self):
        self.assertTrue(captain_gate._excluded("Carlos", "Atef Choudhury"))
        self.assertTrue(captain_gate._excluded("Carlos", "Sabrina Alicea"))
        # both spellings of Joe: the board writes 'Joseph', people say 'Joe'
        self.assertTrue(captain_gate._excluded("Carlos", "Joe Eckhart"))
        self.assertTrue(captain_gate._excluded("Carlos", "Joseph Eckhart"))

    def test_the_same_name_is_fine_under_another_captain(self):
        """The pin is per-captain — Atef belongs in ATEF's boxes."""
        self.assertFalse(captain_gate._excluded("Atef", "Atef Choudhury"))

    def test_a_real_new_rep_still_gets_through(self):
        self.assertFalse(captain_gate._excluded("Carlos", "Jackie Leroy"))

    def test_marcos_barbosa_cannot_come_back_to_coltens_board(self):
        """2026-08-27: Marcos Barbosa came off Colten's captainship (and out
        from under Colten's org in the bulletins) the same day his three Org
        Sales Board rows were deleted. SmartCircle has NOT dropped him from
        Tableau's NDS captain filter, so the nightly scan still reads him as
        Colten's team — without the pin the gate offers him to Evelyn the next
        morning and one ✅ puts the rows straight back.

        Every spelling the captain arrives as has to hold: the scan passes the
        Tableau team name, the fills pass the slug.
        """
        for capt in ("Colten", "colten", "Colten's Team", "COLTEN"):
            self.assertTrue(captain_gate._excluded(capt, "Marcos Barbosa"), capt)
        self.assertTrue(captain_gate._excluded("Colten", "  marcos   barbosa "))
        # He is still an ICD elsewhere — the pin is Colten's alone.
        self.assertFalse(captain_gate._excluded("Jairo", "Marcos Barbosa"))


class PinnedRepIsNeverProposed(unittest.TestCase):
    """The pin is checked INSIDE propose(), the one door every report goes
    through — so the guarantee is 'no report can offer him', not 'the reports we
    remembered to patch'. Guarding this end-to-end and not just `_excluded`
    keeps a future refactor of propose() from quietly dropping the filter.
    """

    def _propose(self, names, captain, on_board=()):
        log = []
        with mock.patch.multiple(
                captain_gate, bank=mock.Mock(**{
                    "KIND_CAPTAINSHIP": "captainship",
                    "open_log.return_value": object(),
                    "log_entries.return_value": [],
                    "already_logged.return_value": False,
                }),
                already_on_board=mock.Mock(return_value=set(on_board))):
            out = captain_gate.propose(names, captain=captain,
                                       source="Tableau captain filter",
                                       ss=object(), dry_run=True,
                                       logfn=log.append)
        return out, " | ".join(log)

    def test_marcos_is_not_offered_for_colten(self):
        out, log = self._propose(["Marcos Barbosa"], "Colten")
        self.assertEqual(out, [])
        self.assertIn("pinned out of this captainship", log)

    def test_someone_else_on_the_same_scan_is_still_offered(self):
        out, _ = self._propose(["Marcos Barbosa", "Jackie Leroy"], "Colten")
        self.assertEqual([e["name"] for e in out], ["Jackie Leroy"])


class RepAlreadyOnTheBoardIsNeverProposed(unittest.TestCase):
    """2026-09-01 (Eve): the bonus report asked for a ✅ on Jeffrey Starr and
    Vincent Smith, who had been put into Carlos' boxes BY HAND weeks earlier.
    They had no log line, so the log — until now the gate's only memory —
    couldn't tell. A ✅ on either could only ever land on "already had a row".
    """

    _propose = PinnedRepIsNeverProposed._propose

    def test_they_are_logged_not_asked_about(self):
        out, log = self._propose(["Jeffrey Starr", "Vincent Smith"], "Carlos",
                                 on_board=["Jeffrey Starr", "Vincent Smith"])
        self.assertEqual(out, [])
        self.assertIn("already in this captainship's boxes", log)

    def test_a_genuinely_new_rep_on_the_same_scan_still_gets_asked(self):
        out, _ = self._propose(["Jeffrey Starr", "Jackie Leroy"], "Carlos",
                               on_board=["Jeffrey Starr"])
        self.assertEqual([e["name"] for e in out], ["Jackie Leroy"])

    def test_a_board_read_that_fails_still_asks(self):
        """Not knowing must fall back to ASKING — never to swallowing a rep."""
        out, _ = self._propose(["Jackie Leroy"], "Carlos", on_board=[])
        self.assertEqual([e["name"] for e in out], ["Jackie Leroy"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful()
             else 1)
