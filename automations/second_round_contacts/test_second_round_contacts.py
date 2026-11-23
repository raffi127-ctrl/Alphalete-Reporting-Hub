import datetime as dt
import unittest
from unittest import mock

from automations.second_round_contacts import config as C
from automations.second_round_contacts import contacts as K
from automations.second_round_contacts import roster as R
from automations.second_round_contacts import rules
from automations.second_round_contacts import state as S
from automations.second_round_contacts import run as RUN
from automations.second_round_contacts.run import plan_adds

T = dt.date(2026, 10, 31)


def ent(sr="2026-10-20", status=S.TRACKED):
    return {"second_round": sr, "status": status, "first_name": "Ana", "last_name": "Lopez"}


class Rules(unittest.TestCase):
    def test_under_a_week_waits(self):
        self.assertEqual(rules.decide(ent("2026-10-28"), {}, T)[0], rules.WAIT)

    def test_not_hired_after_a_week_is_removed(self):
        v, why = rules.decide(ent("2026-10-20"), {}, T)
        self.assertEqual(v, rules.DELETE)
        self.assertIn("not hired", why)

    def test_scheduled_start_waits_then_removed_at_three_weeks(self):
        f = {"bob": dt.date(2026, 10, 20)}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.WAIT)
        self.assertEqual(rules.decide(ent(), f, dt.date(2026, 11, 10))[0], rules.DELETE)

    def test_showed_and_badged_graduates(self):
        f = {"ns_showed": dt.date(2026, 10, 27), "progress": 100}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.HIRED)

    def test_showed_not_badged_waits_then_removed(self):
        f = {"ns_showed": dt.date(2026, 10, 27), "progress": 60}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.WAIT)
        v, why = rules.decide(ent(), f, dt.date(2026, 11, 20))
        self.assertEqual(v, rules.DELETE)
        self.assertIn("never fully badged", why)

    def test_unreadable_progress_never_removes(self):
        f = {"ns_showed": dt.date(2026, 9, 1), "progress": None}
        self.assertEqual(rules.decide(ent(), f, T)[0], rules.WAIT)

    # --- the 7pm pass (Raf, 2026-11-17) ---------------------------------

    def test_blank_on_the_day_waits_until_the_evening(self):
        """At 6am and 11:30 a blank only means nobody has marked it yet."""
        e = ent("2026-10-31")
        self.assertEqual(rules.decide(e, {}, T)[0], rules.WAIT)

    def test_evening_removes_anyone_not_marked_bob(self):
        v, why = rules.decide(ent("2026-10-31"), {}, T, evening=True)
        self.assertEqual(v, rules.DELETE)
        self.assertIn("not marked BOB", why)

    def test_evening_keeps_someone_marked_bob(self):
        f = {"bob": dt.date(2026, 10, 31)}
        self.assertEqual(rules.decide(ent("2026-10-31"), f, T, evening=True)[0],
                         rules.WAIT)

    def test_showed_up_alone_does_not_save_them(self):
        """Megan 2026-11-17: the keeper is BOB. Plenty are marked showed up,
        or even offered, and never start."""
        for f in ({"showed": dt.date(2026, 10, 31)},
                  {"offered": dt.date(2026, 10, 31)},
                  {"showed": dt.date(2026, 10, 31), "offered": dt.date(2026, 10, 31)}):
            self.assertEqual(rules.decide(ent("2026-10-31"), f, T, evening=True)[0],
                             rules.DELETE, f)

    def test_evening_also_looks_at_the_day_before(self):
        """Recruiters mark late, so the 7pm pass is the FIRST one to see
        yesterday's answer -- and has to be able to act on a blank
        (Megan, 2026-11-17)."""
        v, why = rules.decide(ent("2026-10-30"), {}, T, evening=True)
        self.assertEqual(v, rules.DELETE)
        self.assertIn("not marked BOB", why)

    def test_evening_stops_at_one_day_back(self):
        """Two days back is the standing rules' business, not a same-day cut."""
        self.assertEqual(rules.decide(ent("2026-10-29"), {}, T, evening=True)[0],
                         rules.WAIT)

    def test_evening_ignores_a_second_round_still_to_come(self):
        self.assertEqual(rules.decide(ent("2026-11-03"), {}, T, evening=True)[0],
                         rules.WAIT)

    def test_evening_keeps_yesterdays_marked_person(self):
        f = {"bob": dt.date(2026, 10, 30)}
        self.assertEqual(rules.decide(ent("2026-10-30"), f, T, evening=True)[0],
                         rules.WAIT)

    def test_evening_never_touches_a_graduated_contact(self):
        self.assertEqual(rules.decide(ent("2026-10-31", status=S.HIRED), {}, T,
                                      evening=True)[0], rules.KEEP)

    def test_hired_is_kept_forever(self):
        self.assertEqual(rules.decide(ent(status=S.HIRED), {}, dt.date(2027, 6, 1))[0], rules.KEEP)


class TheAuditReadsWholeWeeks(unittest.TestCase):
    """The report renders ONE WEEK and ignores any attempt to move it -- its
    week box is readonly and its URL parameters do nothing
    (office_admin.retention._retarget exists for that reason). So asking for
    35 days of COLUMNS found only the handful on screen.

    Probed 2026-11-22 on Raf's own office: 11/21 and 11/22 had links and
    every earlier day had none. On a Sunday that is two weekend days, both
    zero -- and the audit concluded that nobody in the fleet had been marked
    anything, then removed everybody older than a week.

    Read as retargeted WEEK ranges instead, the same office answered 936
    rows across all five labels, 146 of them Total Daily Bob. The marks were
    always there.

    This class replaces BobIsReadIntoTheFuture, whose forward window was
    added to explain that empty keeper read. config.py already recorded the
    reason as "now in doubt"; it is now answered outright, and Total Daily
    Bob comes back 45-55 a week BACKWARD, so it is a count of BOBs made, not
    of starts due.
    """

    def _weeks(self):
        seen = {}

        def fake(_a, office, labels, weeks, today=None):
            seen["weeks"] = list(weeks)
            seen["labels"] = tuple(labels)
            return []

        with mock.patch.object(RUN, "read_weeks", fake):
            RUN.gather_facts(None, ["11280"], set(), T)
        return seen

    def test_it_asks_for_weeks_not_days(self):
        w = self._weeks()["weeks"]
        self.assertTrue(w)
        for a, b in zip(w, w[1:]):
            self.assertEqual((b - a).days, 7, "consecutive week starts")

    def test_the_window_still_covers_the_whole_lookback(self):
        w = self._weeks()["weeks"]
        self.assertLessEqual(w[0], T - dt.timedelta(days=C.AUDIT_LOOKBACK_DAYS))
        self.assertGreaterEqual(w[-1] + dt.timedelta(days=6), T)

    def test_every_audit_label_is_asked_for(self):
        self.assertEqual(self._weeks()["labels"], C.AUDIT_LABELS)

    def test_a_week_hit_is_dated_at_its_end_never_its_start(self):
        """A week range cannot say which day inside it, and every rule that
        reads these dates measures an AGE. The earliest day would overstate
        every age and remove people early; the latest understates it, so the
        only mistake left is waiting too long."""
        import inspect
        src = inspect.getsource(RUN.read_weeks)
        self.assertIn("week_start + dt.timedelta(days=6)", src)
        self.assertIn("min(", src, "and never dated past today")


class KeeperMustHaveBeenRead(unittest.TestCase):
    """The evening rule removes everybody NOT marked BOB, so a read that
    returned no BOB rows at all cannot be treated as 'nobody was BOB'd' -- it
    would empty the whole group in one pass."""

    def _audit(self, seen):
        o = mock.Mock(owner="Raf", label="Raf", active=True, account="raf",
                      offices=["11280"], ov_campaign="RES-AT&T")
        a = {"first_name": "Ana", "last_name": "Lopez",
             "phone": "5125550147", "email": "ana@example.test"}
        k = S.key_for(a)
        e = dict(ent("2026-10-31"), **{x: a[x] for x in ("phone", "email")})
        e["resourceName"] = "people/1"
        sess = mock.MagicMock(); sess.__enter__.return_value = mock.Mock()
        with mock.patch("automations.applicant_tracker.applicantstream.session",
                        return_value=sess), \
                mock.patch.object(RUN.S, "load", return_value={"raf": {k: e}}), \
                mock.patch.object(RUN.S, "save"), \
                mock.patch.object(RUN, "gather_facts", return_value=({k: {}}, seen)), \
                mock.patch.object(RUN.K, "service", return_value=mock.Mock()), \
                mock.patch.object(RUN.K, "ensure_group", return_value={"resourceName": "g/1"}), \
                mock.patch.object(RUN.K, "still_exists", return_value=True), \
                mock.patch.object(RUN.K, "delete") as delete:
            RUN.run_audit([o], write=True, ownerville=False, evening=True,
                          today=T)
        return delete

    def test_an_empty_bob_read_removes_nobody(self):
        self.assertEqual(self._audit({C.LABEL_SHOWED}).call_count, 0)

    def test_a_real_bob_read_still_removes(self):
        self.assertEqual(self._audit({C.LABEL_BOB}).call_count, 1)


class AddsPassHonoursARemoval(unittest.TestCase):
    """The ping-pong guard. plan() only dedupes against the LIVE contacts, so
    the moment the audit takes somebody out they look brand new to the adds
    pass -- out at 7pm, back in at 6am, every day until the week rolls past."""

    APPLICANT = {"first_name": "Ana", "last_name": "Lopez",
                 "phone": "5125550147", "email": "ana@example.test"}

    def _run(self, status):
        o = mock.Mock(owner="Raf", label="Raf", active=True, account="raf",
                      offices=["19833"], ov_campaign="RES-AT&T")
        a = dict(self.APPLICANT)
        st = {"raf": {S.key_for(a): dict(ent(), status=status,
                                         removed="2026-10-30",
                                         reason="neither showed up nor offered",
                                         **{k: a[k] for k in ("phone", "email")})}}
        row = {"applicant": a, "status": "add", "why": "", "day": dt.date(2026, 10, 31)}
        sess = mock.MagicMock()
        sess.__enter__.return_value = mock.Mock()
        with mock.patch("automations.applicant_tracker.applicantstream.session",
                        return_value=sess), \
                mock.patch.object(RUN.S, "load", return_value=st), \
                mock.patch.object(RUN.S, "save"), \
                mock.patch.object(RUN, "read_offices", return_value=([("L", dt.date(2026, 10, 31), a)], [])), \
                mock.patch.object(RUN, "plan_adds", return_value=[row]), \
                mock.patch.object(RUN.K, "has_token", return_value=True), \
                mock.patch.object(RUN.K, "service", return_value=mock.Mock()), \
                mock.patch.object(RUN.K, "existing_index", return_value=({}, {})), \
                mock.patch.object(RUN.K, "ensure_group", return_value={"resourceName": "g/1"}), \
                mock.patch.object(RUN.K, "note_for", return_value="note"), \
                mock.patch.object(RUN.K, "display_name", return_value="Ana Lopez (2R 10/31)"), \
                mock.patch.object(RUN.K, "create", return_value="people/1") as create:
            RUN.run_pass([o], [dt.date(2026, 10, 31)], write=True)
        return create

    def test_a_removed_person_is_not_added_back(self):
        self.assertEqual(self._run(S.REMOVED).call_count, 0)

    def test_an_ordinary_new_person_is_still_added(self):
        self.assertEqual(self._run(S.TRACKED).call_count, 1)


class EveningLookBack(unittest.TestCase):
    """The other half of the 7pm look-back: putting somebody back."""

    def gone(self, sr="2026-10-31", by=rules.EVENING):
        e = ent(sr, status=S.REMOVED)
        e["removed"] = sr
        e["display"] = "Ana Lopez (2R 10/31)"
        if by:
            e["removed_by"] = by
        return e

    def test_a_late_bob_mark_puts_them_back(self):
        back, why = rules.restore(self.gone(), {"bob": dt.date(2026, 10, 31)}, T)
        self.assertTrue(back)
        self.assertIn("marked BOB", why)

    def test_a_late_showed_up_mark_is_not_enough(self):
        self.assertFalse(rules.restore(
            self.gone(), {"showed": dt.date(2026, 10, 31),
                          "offered": dt.date(2026, 10, 31)}, T)[0])

    def test_yesterdays_removal_is_still_in_the_window(self):
        back, _ = rules.restore(self.gone("2026-10-30"),
                                {"bob": dt.date(2026, 10, 30)}, T)
        self.assertTrue(back)

    def test_still_blank_stays_out(self):
        self.assertFalse(rules.restore(self.gone(), {}, T)[0])

    def test_the_evening_rule_is_undone_by_bob_only(self):
        """A booked start without BOB is exactly what the 7pm rule removes;
        bringing that back would be a daily in/out."""
        self.assertFalse(rules.restore(
            self.gone(), {"ns_sched": dt.date(2026, 11, 3)}, T)[0])

    def test_an_old_evening_removal_still_comes_back_on_bob(self):
        """Eve 2026-11-19: marked BOB days late still brings them back."""
        e = self.gone("2026-10-20")
        e["removed"] = "2026-10-20"
        back, why = rules.restore(e, {"bob": dt.date(2026, 11, 3)}, T)
        self.assertTrue(back)
        self.assertIn("marked BOB", why)

    def test_too_old_a_removal_is_no_longer_reviewed(self):
        e = self.gone("2026-08-01")
        e["removed"] = "2026-08-01"
        self.assertFalse(rules.restorable(e, T))


class EveryRemovalCanComeBack(unittest.TestCase):
    """Eve 2026-11-19: "what if they get marked BOB later, or end up hired?"
    Every removal comes back once the mark it was missing shows up."""

    def gone(self, reason, sr="2026-10-20", removed="2026-10-27", rule=None):
        e = ent(sr, status=S.REMOVED)
        e.update(removed=removed, reason=reason, display="Ana Lopez (2R 10/20)")
        if rule:
            e["removed_rule"] = rule
        return e

    NOT_HIRED = "not hired / left as a message: second round 2026-10-20, 7 days ago"

    def test_not_hired_comes_back_on_a_late_bob(self):
        back, why = rules.restore(self.gone(self.NOT_HIRED), {"bob": dt.date(2026, 11, 2)}, T)
        self.assertTrue(back)
        self.assertIn("marked BOB", why)

    def test_not_hired_comes_back_on_a_booked_or_showed_start(self):
        for f in ({"ns_sched": dt.date(2026, 10, 30)}, {"ns_showed": dt.date(2026, 10, 30)}):
            self.assertTrue(rules.restore(self.gone(self.NOT_HIRED), f, T)[0], f)

    def test_not_hired_reads_the_stamped_rule_too(self):
        e = self.gone("reworded someday", rule=rules.NOT_HIRED)
        self.assertTrue(rules.restore(e, {"bob": dt.date(2026, 11, 2)}, T)[0])

    def test_showed_or_offered_alone_does_not_bring_back(self):
        self.assertFalse(rules.restore(self.gone(self.NOT_HIRED),
                                       {"showed": dt.date(2026, 10, 20),
                                        "offered": dt.date(2026, 10, 30)}, T)[0])

    def test_still_blank_stays_out(self):
        self.assertFalse(rules.restore(self.gone(self.NOT_HIRED), {}, T)[0])

    def test_never_comes_back_just_to_be_taken_out_again(self):
        """A BOB already 3+ weeks old would be 'never showed' the same day."""
        self.assertFalse(rules.restore(self.gone(self.NOT_HIRED, sr="2026-09-20", removed="2026-10-27"),
                                       {"bob": dt.date(2026, 10, 1)}, T)[0])

    def test_no_show_comes_back_only_when_they_show(self):
        e = self.gone("new start never showed: scheduled 2026-10-01, 21 days ago")
        self.assertFalse(rules.restore(e, {"bob": dt.date(2026, 10, 1)}, T)[0])
        self.assertTrue(rules.restore(e, {"bob": dt.date(2026, 10, 1),
                                          "ns_showed": dt.date(2026, 10, 29),
                                          "progress": 40}, T)[0])

    def test_never_badged_comes_back_at_100(self):
        e = self.gone("never fully badged: 60% on View Progress 21 days after showing up")
        f = {"ns_showed": dt.date(2026, 10, 1)}
        self.assertFalse(rules.restore(e, dict(f, progress=80), T)[0])
        self.assertTrue(rules.restore(e, dict(f, progress=100), T)[0])

    def test_an_unknown_removal_is_left_alone(self):
        self.assertFalse(rules.restorable(self.gone("removed by hand"), T))

    def test_the_audit_puts_a_standing_removal_back_without_the_evening_flag(self):
        o = mock.Mock(owner="Raf", label="Raf", active=True, account="raf",
                      offices=["11280"], ov_campaign="RES-AT&T")
        a = {"first_name": "Ana", "last_name": "Lopez",
             "phone": "5125550147", "email": "ana@example.test"}
        k = S.key_for(a)
        e = dict(self.gone(self.NOT_HIRED), **{x: a[x] for x in ("phone", "email")})
        st = {"raf": {k: e}}
        sess = mock.MagicMock(); sess.__enter__.return_value = mock.Mock()
        with mock.patch("automations.applicant_tracker.applicantstream.session",
                        return_value=sess),                 mock.patch.object(RUN.S, "load", return_value=st),                 mock.patch.object(RUN.S, "save"),                 mock.patch.object(RUN, "gather_facts",
                                  return_value=({k: {"bob": dt.date(2026, 11, 2)}}, {C.LABEL_BOB})) as gf,                 mock.patch.object(RUN.K, "service", return_value=mock.Mock()),                 mock.patch.object(RUN.K, "ensure_group", return_value={"resourceName": "g/1"}),                 mock.patch.object(RUN.K, "note_for", return_value="note"),                 mock.patch.object(RUN.K, "create", return_value="people/9") as create:
            RUN.run_audit([o], write=True, ownerville=False, evening=False, today=T)
        self.assertIn(k, gf.call_args[0][2])
        self.assertEqual(create.call_count, 1)
        self.assertEqual(st["raf"][k]["status"], S.TRACKED)
        self.assertEqual(st["raf"][k]["resourceName"], "people/9")


    def test_a_tracked_contact_is_not_a_restore_candidate(self):
        self.assertFalse(rules.restorable(ent(), T))

    def test_a_removal_with_no_second_round_date_is_not_a_candidate(self):
        e = self.gone(self.NOT_HIRED)
        del e["second_round"]
        self.assertFalse(rules.restorable(e, T))


class EveningFlag(unittest.TestCase):
    def test_evening_implies_audit(self):
        """--evening alone used to be silently ignored on an adds run, which
        reads as 'the cleanup ran and found nothing'."""
        with mock.patch.object(RUN.R, "open_tab", return_value=None), \
                mock.patch.object(RUN.R, "read", return_value=[]), \
                mock.patch.object(RUN, "run_audit", return_value=0) as audit, \
                mock.patch.object(RUN, "run_pass", return_value=0) as adds:
            RUN.main(["--evening"])
        self.assertEqual(adds.call_count, 0)
        # no active owners, so neither runs -- the point is that it did not
        # fall through to the adds branch.
        self.assertEqual(audit.call_count, 0)

    def test_evening_takes_the_audit_branch(self):
        owner = mock.Mock(owner="Raf", label="Raf", active=True, account="raf")
        with mock.patch.object(RUN.R, "open_tab", return_value=None), \
                mock.patch.object(RUN.R, "read", return_value=[owner]), \
                mock.patch.object(RUN.K, "has_token", return_value=True), \
                mock.patch.object(RUN, "run_audit", return_value=0) as audit, \
                mock.patch.object(RUN, "run_pass", return_value=0) as adds:
            RUN.main(["--evening"])
        self.assertEqual(adds.call_count, 0)
        self.assertEqual(audit.call_count, 1)
        self.assertTrue(audit.call_args.kwargs["evening"])


class Roster(unittest.TestCase):
    def test_parse_rows(self):
        vals = [C.ROSTER_HEADERS,
                ["Omar Perez", "11280", "OmarReception@gmail.com", "Yes", "", "10/27/2026", "", "", ""],
                ["Someone", "", "x@y.com", "Yes", "", "", "", "", ""],
                ["Shaylee Miller", "office 24226", "shaylee.rec@gmail.com", "No", "RES-FIBER", "", "note", "", ""]]
        rows = R.parse_rows(vals)
        self.assertEqual([r.owner for r in rows], ["Omar Perez", "Shaylee Miller"])
        o = rows[0]
        self.assertEqual((o.office, o.account, o.active, o.ov_campaign, o.start),
                         ("11280", "omarreception@gmail.com", True, C.DEFAULT_OV_CAMPAIGN, dt.date(2026, 10, 27)))
        self.assertEqual((rows[1].office, rows[1].active, rows[1].ov_campaign), ("24226", False, "RES-FIBER"))

    def test_headers_in_any_order(self):
        vals = [["Reception Email", "Owner", "Active", "ApplicantStream Office ID"],
                ["a@b.com", "X Y", "yes", "123"]]
        self.assertEqual(R.parse_rows(vals)[0].office, "123")


class TwoOffices(unittest.TestCase):
    """Omar 2026-11-05: his own funnel is 24232, the first run read Raf's 24153."""

    A = {"first_name": "Ana", "last_name": "Lopez", "phone": "2145550101", "email": ""}

    def owner(self, cell="24232, 24153"):
        return R.parse_rows([C.ROSTER_HEADERS, ["Omar", cell, "r@x.com", "Yes", "", "", "", "", ""]])[0]

    def test_new_office_first_old_still_read(self):
        o = self.owner()
        self.assertEqual((o.office, o.offices), ("24232", ["24232", "24153"]))
        self.assertEqual(self.owner("24153").offices, ["24153"])

    def test_adds_keep_the_office_that_could_be_read(self):
        from automations.applicant_tracker.applicantstream import OfficeNotAvailable

        def fake(_app, office, _labels, _days):
            if office == "24232":
                raise OfficeNotAvailable("no")
            return [(C.LABEL_BOOKED, T, self.A)]
        with mock.patch.object(RUN, "read_lists", fake):
            found, errors = RUN.read_offices(None, ["24232", "24153"], C.ADD_LABELS, [T])
        self.assertEqual(len(found), 1)
        self.assertEqual(errors, ["office 24232 not available"])

    def test_audit_merges_offices_earliest_date(self):
        key = S.key_for(self.A)
        by_office = {"24232": [(C.LABEL_OFFERED, dt.date(2026, 11, 4), self.A)],
                     "24153": [(C.LABEL_OFFERED, dt.date(2026, 11, 2), self.A)]}
        with mock.patch.object(
                RUN, "read_weeks",
                lambda _a, office, _l, _w, _t=None: by_office[office]):
            facts, seen = RUN.gather_facts(None, ["24232", "24153"], {key}, T)
        self.assertEqual(facts[key]["offered"], dt.date(2026, 11, 2))
        self.assertEqual(seen, {C.LABEL_OFFERED})

    def test_audit_refuses_to_decide_on_an_unread_office(self):
        def fake(_a, office, _l, _w, _t=None):
            if office == "24153":
                raise RuntimeError("down")
            return []
        with mock.patch.object(RUN, "read_weeks", fake):
            with self.assertRaises(RuntimeError):
                RUN.gather_facts(None, ["24232", "24153"], {"p:1"}, T)

    def test_contacts_from_an_office_off_the_row_are_kept_not_audited(self):
        entries = {"p:1": {"office": "24153", "status": S.TRACKED},
                   "p:2": {"office": "24232", "status": S.TRACKED},
                   "p:3": {"office": "24153", "status": S.REMOVED}}
        self.assertEqual(RUN.from_old_office(self.owner("24232"), entries), {"p:1"})
        self.assertEqual(RUN.from_old_office(self.owner("24232, 24153"), entries), set())


class Contacts(unittest.TestCase):
    def test_display_and_note(self):
        a = {"first_name": "Ana", "last_name": "Lopez", "phone": "2145550101"}
        self.assertEqual(K.display_name(a, dt.date(2026, 10, 31)), "Ana Lopez (2R 10/31)")
        self.assertIn("AppStream 11280", K.note_for("Omar", "11280", dt.date(2026, 10, 31)))

    def test_state_key_prefers_phone(self):
        self.assertEqual(S.key_for({"phone": "(214) 555-0101", "email": "a@b.com"}), "p:2145550101")
        self.assertEqual(S.key_for({"email": "A@B.com"}), "e:a@b.com")


class Planning(unittest.TestCase):
    def test_earliest_day_wins_and_existing_skipped(self):
        a = {"first_name": "Ana", "last_name": "Lopez", "phone": "2145550101", "email": ""}
        b = {"first_name": "Bo", "last_name": "Diaz", "phone": "", "email": "bo@x.com"}
        found = [(C.LABEL_HELD, dt.date(2026, 10, 30), a), (C.LABEL_BOOKED, dt.date(2026, 10, 28), a),
                 (C.LABEL_BOOKED, dt.date(2026, 10, 29), b)]
        rows = plan_adds(found, {"2145550101": "Ana Lopez"}, {})
        by = {r["applicant"]["first_name"]: r for r in rows}
        self.assertEqual(by["Ana"]["status"], "exists")
        self.assertEqual(by["Bo"]["status"], "add")
        self.assertEqual(by["Bo"]["day"], dt.date(2026, 10, 29))
        self.assertEqual(by["Ana"]["day"], dt.date(2026, 10, 28))


if __name__ == "__main__":
    unittest.main()
