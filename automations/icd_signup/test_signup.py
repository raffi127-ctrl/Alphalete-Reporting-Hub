"""The sign-up gate: an office asks, Megan is told, nothing exists until she says so.

THE ORDER IS THE POINT (Megan 2026-09-13). Enrolling used to begin with us
typing an office into the roster and collecting their details afterwards. The
tests that matter here are the ones about what must NOT happen before approval:
no key, no roster entry, no push. An abandoned form has to leave nothing behind.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_signup import approve as A, request_notify as N, store
from automations.icd_signup import schema as S
from automations.icd_signup.schema import (IcdSignup, STATUS_APPROVED,
                                           STATUS_PENDING)


def _rec(**kw):
    # NAMES A CHANNEL BY DEFAULT. It did not, and that only started to matter
    # when "named nothing" stopped counting as a refused approval -- an office
    # that leaves it blank has nothing to approve, not a failure. These cases
    # are about a channel being good or refused, so they need one named.
    base = dict(owner="Cyrus Wade", office_label="", platform="mac",
                timezone="America/Chicago", day_start="13:30", day_end="20:30",
                saturday=True, sat_start="11:15", sat_end="16:00",
                ov_name="", knocks_cadence=15, wanted_channels="#ambient",
                alert_channels_json='["#ambient"]',
                contact="cy@example.com", office_key="cyrus")
    base.update(kw)
    return IcdSignup(**base)


class WhatTheFormRefuses(unittest.TestCase):

    def test_a_half_filled_form_says_what_is_wrong_in_their_words(self):
        bad = _rec(owner="Cy", contact="", day_start="half one")
        problems = " ".join(bad.problems())
        self.assertIn("first and last name", problems)
        self.assertIn("email or phone", problems)
        self.assertIn("13:30", problems)
        # No jargon: they are reading this, not us.
        for word in ("schema", "validation", "field", "None"):
            self.assertNotIn(word, problems)

    def test_saturday_times_only_matter_if_they_sell_saturdays(self):
        self.assertEqual(_rec(saturday=False, sat_start="", sat_end="").problems(), [])

    def test_a_good_form_has_no_complaints(self):
        self.assertEqual(_rec().problems(), [])


class OfficeNames(unittest.TestCase):

    def test_first_name_becomes_the_office(self):
        self.assertEqual(store.office_key_for("Cyrus Wade"), "cyrus")

    def test_a_second_kash_does_not_collide_with_the_first(self):
        # The key is the prefix of their relay key and the thing that routes
        # their numbers; two offices sharing one would cross the streams.
        self.assertEqual(store.office_key_for("Kash Patel", taken={"kash"}),
                         "kash2")

    def test_a_name_we_cannot_use_still_produces_something(self):
        self.assertTrue(store.office_key_for("!!!"))


class ApprovalGatesPosting(unittest.TestCase):
    """What approval means SINCE 2026-09-13, and what it stopped meaning.

    It used to create the office: mint the key, write the roster, push. Megan
    asked for the office to be installed and waiting before she looks ("their
    machine is set up so that when I approve it's good to go"), so the key is
    theirs at sign-up and the roster comes off the sheet.

    That leaves approval as the one gate that matters: WHERE THEIR NUMBERS
    POST. It is the only one whose failure is visible to somebody else's team.
    """

    def _approve(self, rec, channel_rc=0, knocks_rc=0):
        with mock.patch.object(store, "get", return_value=rec), \
             mock.patch.object(store, "pending", return_value=[]), \
             mock.patch.object(store, "set_status") as setst, \
             mock.patch.object(A, "_already_approved", return_value=False), \
             mock.patch("automations.icd_alerts.approve.cmd_approve",
                        return_value=channel_rc) as chan, \
             mock.patch("automations.icd_alerts.approve.cmd_knocks",
                        return_value=knocks_rc) as knocks:
            rc = A.approve(rec.office_key if rec else "nobody",
                           log=lambda *a, **k: None)
        return rc, setst, chan, knocks

    def test_an_unknown_office_approves_nothing(self):
        rc, setst, chan, _k = self._approve(None)
        chan.assert_not_called()
        setst.assert_not_called()
        self.assertNotEqual(rc, 0)

    def test_an_already_approved_office_is_not_approved_twice(self):
        rc, setst, chan, _k = self._approve(_rec(status=STATUS_APPROVED))
        chan.assert_not_called()
        setst.assert_not_called()
        self.assertEqual(rc, 1)

    def test_a_refused_channel_leaves_them_pending(self):
        # Marking them approved while nothing posts is the worst outcome: it
        # reads as done and no team ever sees a number.
        rc, setst, _c, knocks = self._approve(_rec(), channel_rc=1)
        setst.assert_not_called()
        knocks.assert_not_called()
        self.assertNotEqual(rc, 0)

    def test_an_office_already_approved_by_hand_is_switched_on(self):
        """Colten 2026-09-22: approved from the terminal at 8:50, then the
        link said 'could not be approved yet' because nothing was pending."""
        rec = _rec()
        with mock.patch.object(store, "get", return_value=rec), \
             mock.patch.object(store, "pending", return_value=[]), \
             mock.patch.object(store, "set_status") as setst, \
             mock.patch.object(A, "_already_approved", return_value=True), \
             mock.patch("automations.icd_alerts.approve.cmd_approve") as chan, \
             mock.patch("automations.icd_alerts.approve.cmd_knocks") as knocks:
            rc = A.approve(rec.office_key, log=lambda *a, **k: None)
        self.assertEqual(rc, 0)
        chan.assert_not_called()
        knocks.assert_not_called()
        self.assertEqual(setst.call_args[0][1], STATUS_APPROVED)

    def test_a_good_channel_switches_them_on(self):
        rc, setst, chan, knocks = self._approve(_rec())
        self.assertEqual(rc, 0)
        chan.assert_called_once()
        knocks.assert_called_once()
        self.assertEqual(setst.call_args[0][1], STATUS_APPROVED)

    def test_an_office_that_declined_a_board_is_not_given_one(self):
        _rc, _s, _c, knocks = self._approve(_rec(knocks_cadence=-1))
        knocks.assert_not_called()


class TheAlert(unittest.TestCase):

    def test_it_says_who_and_how_to_approve_and_little_else(self):
        """A notification, not a record. The record is the sheet.

        It used to carry hours, timezone, computer, contact, their OwnerVille
        name, their setup link and three paragraphs of explanation, which
        pushed the two things somebody must actually DO off the screen
        (Megan 2026-09-13: "this is way too much info").
        """
        head, detail = N.lines(_rec())
        self.assertIn("Cyrus Wade", head)
        body = "\n".join(detail)
        self.assertIn("?approve=cyrus", body)
        self.assertLess(len(detail), 10, "the ping is growing again")
        for gone in ("Selling hours", "Computer:", "Reach them at",
                     "OwnerVille"):
            self.assertNotIn(gone, body, "%r is back in the ping" % gone)

    def test_a_failed_post_is_not_a_failed_signup(self):
        with mock.patch("automations.icd_alerts.post._slack",
                        side_effect=RuntimeError("slack down")):
            posted, why = N.notify(_rec(), send=True, log=lambda *a, **k: None)
        self.assertFalse(posted)
        # AND IT SAYS WHY. On Streamlit Cloud a log line goes nowhere anybody
        # reads, so a failed ping was pure silence -- the sign-up sat on the
        # tab and nobody was told it existed (2026-09-13).
        self.assertIn("slack down", why)

    def test_a_good_post_reports_no_reason(self):
        with mock.patch("automations.icd_alerts.post._slack",
                        return_value="ts1"):
            posted, why = N.notify(_rec(), send=True, log=lambda *a, **k: None)
        self.assertTrue(posted)
        self.assertEqual(why, "")


if __name__ == "__main__":
    unittest.main()


class MultipleChannelsSurvive(unittest.TestCase):
    """An office can want more than one room, at more than one cadence.

    Megan 2026-09-13, looking at the deployed form: "we lost the option for
    multi channel options for both sara and knock reporting." The installer
    has always allowed four alert channels and four knocks destinations each
    with its OWN cadence -- the owners' room hourly and the rep channel every
    fifteen minutes is a normal answer. The form had flattened both into one
    text box and one cadence, which silently narrowed what an office could ask
    for at the exact moment they were asked.
    """

    def _rec(self, alerts, dests):
        import json
        return _rec(alert_channels_json=json.dumps(alerts),
                    knocks_json=json.dumps(dests))

    def test_several_alert_channels_survive_the_round_trip(self):
        r = self._rec(["C1", "#two"], [])
        self.assertEqual(r.alert_channels, ["C1", "#two"])

    def test_each_knocks_destination_keeps_its_own_cadence(self):
        r = self._rec([], [{"channel": "#reps", "cadence_min": 15},
                           {"channel": "C0OWN", "cadence_min": 60}])
        self.assertEqual([d["cadence_min"] for d in r.knocks_destinations],
                         [15, 60])

    def test_a_junk_cell_does_not_lose_the_signup(self):
        # Sheets hands back whatever is in the cell; an unparseable one must
        # cost the channels, never the whole record.
        r = _rec(alert_channels_json="not json at all")
        self.assertEqual(r.alert_channels, [])
        self.assertEqual(r.owner, "Cyrus Wade")

    def test_every_room_lucy_needs_is_still_listed(self):
        # The one detail that survived the trim, because it is the thing that
        # stops a sign-up dead.
        r = self._rec(["C1"], [{"channel": "#reps", "cadence_min": 15,
                                "label": "Every 15 minutes"}])
        body = "\n".join(N.lines(r, link="x")[1])
        self.assertIn("C1", body)
        self.assertIn("#reps", body)


class TheTabGrowsItsOwnColumns(unittest.TestCase):
    """A new field must reach the sheet under a NAME, not just a position.

    Caught live 2026-09-13. alert_channels_json and knocks_json were added to
    _HEADER, but the tab already existed, so its header row never gained them.
    append_row wrote the values PAST the end of the header -- in the sheet,
    under no column name.

    Everything looked like it worked: the sign-up saved, the key was minted,
    the setup link came back. But the relay reads those columns BY NAME to
    hand them to the installer, found no such column, and served an empty
    list -- so an office's channels were dropped silently between the form
    they typed them into and their own machine.
    """

    def test_a_missing_column_is_appended_to_the_header(self):
        existing = store._HEADER[:-2]          # a tab from before the change
        written = {}

        class FakeTab:
            def row_values(self, _n):
                return list(existing)

            def update(self, range_name=None, values=None, **kw):
                written["range"] = range_name
                written["values"] = values

        store._ensure_header(FakeTab())
        self.assertEqual(written.get("values"), [store._HEADER[-2:]])
        # Appended AFTER the last existing column, never over one.
        self.assertEqual(written.get("range"),
                         "%s1" % store._a1_col(len(existing) + 1))

    def test_a_current_header_is_left_alone(self):
        touched = []

        class FakeTab:
            def row_values(self, _n):
                return list(store._HEADER)

            def update(self, **kw):
                touched.append(kw)

        store._ensure_header(FakeTab())
        self.assertEqual(touched, [], "an up-to-date header must not be rewritten")

    def test_a_sheet_that_will_not_answer_does_not_lose_the_signup(self):
        class FakeTab:
            def row_values(self, _n):
                raise RuntimeError("sheets is having a day")

        store._ensure_header(FakeTab())      # must not raise

    def test_column_letters_survive_past_z(self):
        self.assertEqual(store._a1_col(26), "Z")
        self.assertEqual(store._a1_col(27), "AA")


class AFailedSaveIsNeverReportedAsSuccess(unittest.TestCase):
    """Megan submitted on 2026-09-13 and was told "that is in". Nothing
    existed: no row on the tab, no key, no ping. The write had thrown, and
    submit() had quietly written a local draft instead -- on Streamlit Cloud
    that file sits on a disposable filesystem, so it was gone immediately.

    Reporting success for a write that failed is worse than failing loudly,
    because nobody goes looking for something they were told had worked.
    """

    def test_a_failed_write_reports_landed_false(self):
        with mock.patch.object(store, "_tab", side_effect=RuntimeError("no sheet")), \
             mock.patch.object(store, "_save_local"), \
             mock.patch.object(store, "_local", return_value=[]), \
             mock.patch.object(store, "all_signups", return_value=[]):
            _rec_out, landed = store.submit(_rec())
        self.assertFalse(landed)

    def test_a_good_write_reports_landed_true(self):
        class FakeTab:
            def append_row(self, *a, **k):
                pass

        with mock.patch.object(store, "_tab", return_value=FakeTab()), \
             mock.patch.object(store, "all_signups", return_value=[]):
            _rec_out, landed = store.submit(_rec())
        self.assertTrue(landed)

    def test_no_key_is_minted_for_a_signup_that_never_saved(self):
        # Handing out a relay key for a sign-up nobody has a record of would
        # leave a machine able to relay into an office that does not exist.
        with mock.patch.object(store, "submit", return_value=(_rec(), False)), \
             mock.patch.object(store, "mint_and_record_key") as mint:
            _r, link, landed = store.submit_and_key(_rec())
        mint.assert_not_called()
        self.assertFalse(landed)
        self.assertEqual(link, "")

    def test_a_saved_signup_whose_key_fails_still_counts_as_landed(self):
        # Their answers ARE on the tab; Megan can send the link by hand.
        with mock.patch.object(store, "submit", return_value=(_rec(), True)), \
             mock.patch.object(store, "mint_and_record_key",
                               side_effect=RuntimeError("relay keys locked")):
            _r, link, landed = store.submit_and_key(_rec())
        self.assertTrue(landed)
        self.assertEqual(link, "")


class TheFormUsesStreamlitsCredentials(unittest.TestCase):
    """The deployed form must read the secrets, not the repo's files.

    THE FIRST LIVE SIGN-UP WAS LOST TO THIS (2026-09-13). _book() went
    straight to recruiting_report.fill.open_by_key, which authenticates from
    credential FILES -- fine on a Lucy and on Megan's laptop, nonexistent on
    Streamlit Cloud, where the credentials are in st.secrets and nowhere else.
    Every submission threw, fell into the local-draft fallback, and died on a
    disposable filesystem. The secrets had been right the whole time; nothing
    ever read them.

    Every other form in this repo already injected a client. This one did not,
    because it was only ever tested from a laptop where the file path worked
    -- which is exactly the shape of bug that testing locally cannot find.
    """

    def tearDown(self):
        store.set_client(None)

    def test_an_injected_client_is_what_opens_the_workbook(self):
        opened = {}

        class FakeClient:
            def open_by_key(self, key):
                opened["key"] = key
                return "the-book"

        store.set_client(FakeClient())
        self.assertEqual(store._book(), "the-book")
        from automations.icd_alerts import post as P
        self.assertEqual(opened["key"], P.RELAY_SPREADSHEET_ID)

    def test_without_one_it_still_works_off_the_files(self):
        # A Lucy, a laptop or a test has no Streamlit secrets and must keep
        # using the file path.
        store.set_client(None)
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        return_value="file-book") as f:
            self.assertEqual(store._book(), "file-book")
        f.assert_called_once()

    def test_the_app_actually_injects_it(self):
        import pathlib
        app = (pathlib.Path(__file__).resolve().parents[2]
               / "icd_signup" / "app.py").read_text()
        self.assertIn("build_gs_client", app)
        self.assertIn("store.set_client", app)


class OneClickApproval(unittest.TestCase):
    """The link marks the row; Lucy 3 does the approving.

    Megan 2026-09-13: "this should be a link that we can just click and it
    runs." It cannot run there. Approving means resolving Slack channels,
    checking Lucy is in each one and writing the sign-off, and the form runs
    on Streamlit Cloud with a token that is a stranger to that workspace --
    which is exactly how the sign-up ping failed earlier the same day.

    So the click leaves APPROVE_REQUESTED and the poster does the real thing,
    with every check intact, and reports back either way.
    """

    def test_the_click_only_marks_the_row(self):
        with mock.patch.object(store, "set_status", return_value=True) as ss:
            self.assertTrue(store.request_approval("cy", by="the link"))
        args = ss.call_args[0]
        self.assertEqual(args[1], S.STATUS_APPROVE_REQUESTED)

    def test_the_ping_carries_a_clickable_link(self):
        body = "\n".join(N.lines(_rec(), link="x")[1])
        self.assertIn("?approve=cyrus", body)

    def test_the_ping_lists_every_room_lucy_needs(self):
        import json as _json
        r = _rec(alert_channels_json=_json.dumps(["#a", "#shared"]),
                 knocks_json=_json.dumps([{"channel": "#shared",
                                           "cadence_min": 30},
                                          {"channel": "#b",
                                           "cadence_min": 60}]))
        body = "\n".join(N.lines(r, link="x")[1])
        self.assertIn("Add Lucy to", body)
        for room in ("#a", "#b", "#shared"):
            self.assertIn(room, body)
        # deduped -- one line per room, however many ways it was asked for
        self.assertEqual(body.count("   • #shared"), 1)

    def test_an_office_with_no_rooms_says_so_rather_than_nothing(self):
        r = _rec(alert_channels_json="[]", knocks_json="[]")
        body = "\n".join(N.lines(r, link="x")[1])
        self.assertIn("no channel named yet", body)


class NamingNoChannelIsNotARefusal(unittest.TestCase):
    """An office that leaves the alert channel blank has nothing to approve
    there -- "not sure yet" is an answer the form allows. Treating it as a
    refusal bailed out of the whole approval BEFORE the knocks board, which
    Carlos had named two channels for (2026-09-15)."""

    def _approve(self, rec):
        with mock.patch.object(store, "get", return_value=rec), \
             mock.patch.object(store, "pending", return_value=[]), \
             mock.patch.object(store, "set_status") as setst, \
             mock.patch.object(A, "_already_approved", return_value=False), \
             mock.patch("automations.icd_alerts.approve.cmd_approve",
                        return_value=1) as chan, \
             mock.patch("automations.icd_alerts.approve.cmd_knocks",
                        return_value=0) as knocks:
            rc = A.approve(rec.office_key, log=lambda *a, **k: None)
        return rc, setst, chan, knocks

    def test_the_board_is_still_approved(self):
        rc, setst, chan, knocks = self._approve(
            _rec(alert_channels_json="[]"))
        chan.assert_not_called()
        knocks.assert_called_once()
        self.assertEqual(rc, 0)
        setst.assert_called_once()
