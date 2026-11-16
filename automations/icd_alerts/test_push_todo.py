"""The resume-push to-do list travels from an office computer to its Slack
channel -- and the things that would quietly lose it on the way do not.

WHY THIS EXISTS (2026-11-15). The noon/4pm "recruiting to-do" post in
Carlos's channel -- who the walk found no phone number for, grouped by Indeed
account -- stopped on 2026-10-20, the day his office (11580) left Lucy 2 for
his own computer, and nobody noticed for 26 days. The office machine kept
writing the list to its own disk; nothing carried it back. The relay now
does (resume_push._file_todo), and Lucy 1's poster posts it (push_todo).

Three things in particular are pinned here, each a way the list could
silently come back wrong:
  * the relay SCRUBS every email address off a fault. Accounts are emails, so
    they travel as bare domains, and the post has to group them exactly as
    it did from a local snapshot;
  * a row can only hold ~6000 characters. A long list is cut from the end and
    SAYS SO, rather than arriving as half a JSON object and posting nothing;
  * the poster posts once per slot per office, never a stale list twice, and
    only for offices whose row in offices.py says post_todo -- Colten's and
    Raf's names never land in a channel that was not set up for them.

Touches nothing outside a temp dir: no browser, no Sheet, no Slack.

    python -m unittest automations.icd_alerts.test_push_todo
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from automations.icd_alerts import package
from automations.icd_alerts import push_todo as PT
from automations.icd_alerts import relay as R
from automations.icd_alerts import resume_push as RP
from automations.oat_processing import summary as S

DAY = dt.date(2026, 11, 15)
CARLOS = {"office_key": "carlos", "push_resumes": True}
RAF = {"office_key": "raf", "push_resumes": True}

SNAP = {"nophone": [
            {"name": "Dana Reyes", "account": "jobs@fasttrack-strategies.com", "days": 3},
            {"name": "Al Burke", "account": "hire@peaksalesstrategies.com", "days": 0},
            {"name": "jose.r@gmail.com", "account": "jobs@fasttrack-strategies.com", "days": 1},
            {"name": "No Acct", "account": "", "days": None},
            "Bare Name"],
        "retext": [{"name": "Zed Alpha", "account": "jobs@fasttrack-strategies.com", "days": 9}],
        "queue_total": 20, "at": "11:58", "date": DAY.isoformat(),
        "complete": True, "covered": 23, "queue_start": 23}


def _unreadable_fixed(entries):
    """What the walk's email fallback has to become on the wire."""
    out = []
    for e in entries:
        if isinstance(e, dict) and "@" in e["name"]:
            e = dict(e, name=RP.UNREADABLE_NAME)
        out.append(e)
    return out


class Packing(unittest.TestCase):

    def test_accounts_travel_as_domains_and_names_never_as_emails(self):
        body = RP.pack_todo(SNAP, "11580", True)
        wire = RP.todo_detail(body)
        self.assertNotIn("@", wire, "an email address would be scrubbed to [email]")
        self.assertIn("fasttrack-strategies.com", body["nophone"])
        self.assertIn(RP.UNREADABLE_NAME, wire)
        self.assertEqual(body["office"], "11580")
        self.assertTrue(body["live"])
        self.assertEqual((body["complete"], body["covered"], body["queue_start"],
                          body["queue_total"], body["at"]), (True, 23, 23, 20, "11:58"))

    def test_the_scrub_leaves_the_list_intact(self):
        """relay._scrub is the guardrail that keeps logins and customer
        addresses on the laptop. It must still run on this -- and this must
        survive it unchanged."""
        wire = RP.todo_detail(RP.pack_todo(SNAP, "11580", True))
        with mock.patch.object(R.C, "creds", return_value={
                "email": "lucy@example.com", "password": "hunter22"}):
            after = R._scrub(wire, {"relay_key": "abcdef12"})
        self.assertEqual(after, wire)
        self.assertNotIn("[email]", after)
        self.assertEqual(json.loads(after)["nophone"],
                         json.loads(wire)["nophone"])

    def test_the_post_renders_the_wire_exactly_as_the_local_snapshot(self):
        body = RP.pack_todo(SNAP, "11580", True)
        back = RP.unpack_todo(json.loads(RP.todo_detail(body)))
        for bucket in ("nophone", "retext"):
            local = S.render_section("t", S._entries_of(_unreadable_fixed(SNAP[bucket])))
            wire = S.render_section("t", S._entries_of(back[bucket]))
            self.assertEqual(wire, local, bucket)
        self.assertIn("*Fast Track Strategies* (2):",
                      S.render_section("t", S._entries_of(back["nophone"])))

    def test_a_bare_domain_names_the_account_like_its_email_did(self):
        self.assertEqual(S._account_name("fasttrack-strategies.com"),
                         S._account_name("jobs@fasttrack-strategies.com"))
        self.assertEqual(S._account_name("peaksalesstrategiestx.com"),
                         "Peak Sales Strategies")
        self.assertEqual(S._account_name(""), "")
        self.assertEqual(S._account_name("Indeed"), "")     # no domain, no guess
        self.assertEqual(S._account_name("J. Smith"), "")

    def test_a_list_too_long_for_the_row_is_cut_from_the_end_and_says_so(self):
        many = {"nophone": [{"name": "Applicant Number %03d Longname" % i,
                             "account": "jobs@acct%d.com" % (i % 5), "days": i % 9}
                            for i in range(400)],
                "retext": [], "queue_total": 400, "at": "09:00",
                "date": DAY.isoformat(), "complete": True, "covered": 400,
                "queue_start": 400}
        body = RP.pack_todo(many, "11580", True)
        self.assertLessEqual(len(RP.todo_detail(body)), RP.TODO_DETAIL_MAX)
        kept = sum(len(v) for v in body["nophone"].values())
        self.assertGreater(kept, 100)
        self.assertEqual(kept + body["cut"], 400)
        # From the END: the first applicants in the queue are all still there.
        names = [p[0] for v in body["nophone"].values() for p in v]
        self.assertIn("Applicant Number 000 Longname", names)
        self.assertNotIn("Applicant Number 399 Longname", names)
        json.loads(RP.todo_detail(body))     # whole, never half an object

    def test_a_short_list_is_never_cut(self):
        self.assertEqual(RP.pack_todo(SNAP, "11580", True)["cut"], 0)

    def test_days_that_are_not_a_number_become_none(self):
        body = RP.pack_todo({"nophone": [{"name": "A B", "account": "", "days": "3"},
                                         {"name": "C D", "account": "", "days": True}],
                             "retext": []}, "11580", True)
        self.assertEqual(body["nophone"][""], [["A B", None], ["C D", None]])

    def test_one_row_per_office_on_a_many_office_machine(self):
        self.assertEqual(RP.todo_summary(RAF, "23965"), "push todo 23965")
        self.assertEqual(RP.todo_summary(CARLOS, "11580"), "push todo")


class FilingTheRow(unittest.TestCase):
    """_file_todo runs in push()'s finally, after _file_stats: it reads the
    snapshot the walk just wrote and hands it to the relay. Best effort."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._cwd = os.getcwd()
        os.chdir(self.tmp)
        from automations.oat_processing import config as OC
        self._suffix = OC.FILE_SUFFIX
        OC.FILE_SUFFIX = "-11580"
        os.makedirs("output")
        self.filed = []

        def fake_report(stage, summary, detail="", day=None, log=None, office_key=""):
            self.filed.append((stage, summary, detail, office_key))
            return True
        self.patches = [
            mock.patch.object(R, "report_fault", fake_report),
            mock.patch.object(RP, "push_record", lambda: CARLOS),
            mock.patch.object(RP, "_log", lambda *a, **k: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        from automations.oat_processing import config as OC
        OC.FILE_SUFFIX = self._suffix
        os.chdir(self._cwd)

    def _snapshot(self, snap=SNAP, day=None):
        day = day or dt.date.today()
        with open("output/oat-flagged-%s-11580.json" % day.isoformat(), "w") as fh:
            json.dump(snap, fh)

    def test_a_live_walk_files_its_list(self):
        self._snapshot()
        RP._file_todo({"reached": True, "office": "11580", "rc": 0}, live=True)
        self.assertEqual(len(self.filed), 1)
        stage, summary, detail, key = self.filed[0]
        self.assertEqual((stage, summary, key), (RP.TODO_STAGE, "push todo", "carlos"))
        body = json.loads(detail)
        self.assertEqual(body["office"], "11580")
        self.assertEqual(RP.unpack_todo(body)["nophone"][0]["name"], "Dana Reyes")

    def test_a_dry_run_files_nothing(self):
        """Names leave the machine only for an office really being pushed."""
        self._snapshot()
        RP._file_todo({"reached": True, "office": "11580", "rc": 0}, live=False)
        self.assertEqual(self.filed, [])

    def test_a_walk_that_did_not_finish_files_nothing(self):
        self._snapshot()
        RP._file_todo({"reached": True, "office": "11580", "rc": 2}, live=True)
        self.assertEqual(self.filed, [])

    def test_no_snapshot_today_files_nothing(self):
        self._snapshot(day=dt.date.today() - dt.timedelta(days=1))
        RP._file_todo({"reached": True, "office": "11580", "rc": 0}, live=True)
        self.assertEqual(self.filed, [])

    def test_the_relay_failing_never_reaches_the_push(self):
        self._snapshot()
        with mock.patch.object(R, "report_fault", side_effect=RuntimeError("boom")):
            RP._file_todo({"reached": True, "office": "11580", "rc": 0}, live=True)

    def test_it_is_called_after_the_stats_row(self):
        src = (pathlib.Path(RP.__file__)).read_text()
        body = src[src.index("def push("):]
        self.assertLess(body.index("_file_stats(out, live, sent_office_today, result)"),
                        body.index("_file_todo(out, live)"))


HEAD = ["Office", "Day", "Stage", "Summary", "Detail", "Count", "First At",
        "Last At", "Local Time", "Agent", "Platform", "Last Posted At"]


def _row(office_key, oid, at, day=DAY.isoformat(), snap=SNAP, **over):
    body = RP.pack_todo(dict(snap, at=at), oid, True)
    body.update(over)
    return [office_key, day, RP.TODO_STAGE, "push todo", RP.todo_detail(body),
            "3", "x", "11/15/2026 %s:01" % at, "", "icd_alerts/5", "Darwin", ""]


class _Book:
    def __init__(self, rows, strict=False):
        self.rows = rows
        self.reads = 0
        self.strict = strict

    def worksheet(self, name):
        assert name == "ICD Faults", name
        if self.strict:
            raise AssertionError("the Sheet was read outside a posting hour")
        self.reads += 1
        return self

    def get_all_values(self):
        return [HEAD] + self.rows


class Posting(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.calls = []

        def fake_post(date, t, dry_run=False, edit=False, coverage=None,
                      channel=None, office_short=None):
            self.calls.append({"date": date, "t": t, "dry_run": dry_run,
                               "coverage": coverage, "channel": channel,
                               "office_short": office_short})
            return {"ok": True}
        self.patches = [mock.patch.object(PT, "STATE_PATH", self.tmp / "state.json"),
                        mock.patch.object(S, "post_nophone_report", fake_post)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _tick(self, rows, hhmm, send=True, book=None):
        h, m = [int(x) for x in hhmm.split(":")]
        book = book or _Book(rows)
        lines = []
        out = PT.post_push_todo(DAY, send=send, book=book,
                                now=dt.datetime(2026, 11, 15, h, m), log=lines.append)
        return out, lines, book

    def test_the_offices_that_post_are_the_relay_ones_with_post_todo(self):
        ids = {o["office_id"] for o in PT.relay_offices()}
        self.assertEqual(ids, {"11580", "23467", "11901"})
        for oid in ("14733", "11280", "23965", "24065"):
            self.assertNotIn(oid, ids, "post_todo is off for %s" % oid)

    def test_the_noon_tick_posts_carlos_into_his_channel(self):
        out, lines, _ = self._tick([_row("carlos", "11580", "11:58")], "12:03")
        self.assertEqual([(o["office"], o["slot"], o["ok"]) for o in out],
                         [("11580", "noon", True)])
        c = self.calls[0]
        self.assertEqual(c["channel"], "C09L1S3MQ1E")
        self.assertEqual(c["office_short"], "office 11580, Carlos")
        self.assertEqual(c["date"], DAY)
        self.assertFalse(c["dry_run"])
        names = [e["name"] for e in c["t"]["nophone"]]
        self.assertEqual(len(names), 5)
        self.assertIn("Dana Reyes", names)
        self.assertIn("Al Burke", names)
        self.assertEqual(c["t"]["nophone"][0]["account"], "fasttrack-strategies.com")
        self.assertEqual(c["coverage"]["complete"], True)
        self.assertNotIn("as_of", c["coverage"], "a fresh list needs no as-of")
        self.assertTrue(any("posted the noon list" in l for l in lines))

    def test_offices_without_a_row_wait_and_say_so_once(self):
        _, lines1, _ = self._tick([_row("carlos", "11580", "11:58")], "12:03")
        _, lines2, _ = self._tick([_row("carlos", "11580", "11:58")], "12:04")
        self.assertEqual(sum("Atef" in l and "no walk relayed" in l for l in lines1), 1)
        self.assertEqual(sum("Atef" in l for l in lines2), 0, "said once per slot")

    def test_the_slot_posts_once(self):
        rows = [_row("carlos", "11580", "11:58")]
        self._tick(rows, "12:03")
        self._tick(rows, "12:04")
        self._tick(rows, "12:59")
        self.assertEqual(len(self.calls), 1)

    def test_the_four_pm_post_needs_a_newer_walk(self):
        self._tick([_row("carlos", "11580", "11:58")], "12:03")
        # The machine stopped: the same walk is still the newest at 4pm.
        _, lines, _ = self._tick([_row("carlos", "11580", "11:58")], "16:02")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(any("not repeating" in l for l in lines), lines)
        # It walked again: the 4pm list posts, and the thread label is 4pm's.
        out, _, _ = self._tick([_row("carlos", "11580", "15:50")], "16:03")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(out[0]["slot"], "4pm")

    def test_a_list_hours_old_is_marked_as_of(self):
        self._tick([_row("carlos", "11580", "09:12")], "12:03")
        self.assertEqual(self.calls[0]["coverage"]["as_of"], "9:12 AM")

    def test_a_cut_list_tells_the_header(self):
        self._tick([_row("carlos", "11580", "11:58", cut=7)], "12:03")
        self.assertEqual(self.calls[0]["coverage"]["cut"], 7)

    def test_outside_the_two_hours_nothing_is_read_or_posted(self):
        for hhmm in ("08:00", "11:59", "13:00", "15:59", "17:00", "22:30"):
            out, _, _ = self._tick([_row("carlos", "11580", "11:58")], hhmm,
                                   book=_Book([], strict=True))
            self.assertEqual(out, [], hhmm)
        self.assertEqual(self.calls, [])

    def test_once_everyone_has_posted_the_sheet_is_not_read_again(self):
        rows = [_row("carlos", "11580", "11:58"), _row("atef", "23467", "11:50"),
                _row("khalil-nds", "11901", "11:40")]
        _, _, book = self._tick(rows, "12:03")
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(book.reads, 1)
        _, _, book2 = self._tick(rows, "12:04", book=_Book(rows, strict=True))
        self.assertEqual(len(self.calls), 3)

    def test_a_dry_run_posts_nothing_and_remembers_nothing(self):
        out, _, _ = self._tick([_row("carlos", "11580", "11:58")], "12:03", send=False)
        self.assertTrue(self.calls[0]["dry_run"])
        self.assertFalse((self.tmp / "state.json").exists())
        self.assertEqual(out[0]["sent"], False)
        # ...so the real tick after it still posts.
        self._tick([_row("carlos", "11580", "11:58")], "12:04")
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.calls[1]["dry_run"])

    def test_rows_for_other_offices_other_days_other_stages_are_ignored(self):
        rows = [
            _row("colten", "14733", "11:00"),                     # post_todo off
            _row("raf", "11280", "11:00"),                         # grouped, off
            _row("carlos", "11580", "11:58", day="2026-11-14"),    # yesterday
            ["carlos", DAY.isoformat(), "probe-push-stats", "push stats",
             json.dumps({"office": "11580", "end": 3}), "1", "", "", "", "", "", ""],
            ["carlos", DAY.isoformat(), RP.TODO_STAGE, "push todo", "{not json",
             "1", "", "", "", "", "", ""],
        ]
        out, _, _ = self._tick(rows, "12:03")
        self.assertEqual(out, [])
        self.assertEqual(self.calls, [])

    def test_the_day_cell_is_matched_however_sheets_displays_it(self):
        out, _, _ = self._tick([_row("carlos", "11580", "11:58", day="11/15/2026")],
                               "12:03")
        self.assertEqual([o["office"] for o in out], ["11580"])

    def test_the_newest_walk_wins_when_an_office_has_two_rows(self):
        rows = [_row("carlos-b2batt", "11580", "10:00"),
                _row("carlos", "11580", "11:58")]
        self._tick(rows, "12:03")
        self.assertEqual(self.calls[0]["coverage"].get("as_of"), None)
        self.assertEqual(len(self.calls), 1)

    def test_one_office_failing_does_not_cost_the_others(self):
        def boom(date, t, **k):
            if k.get("channel") == "C0B85KRS5FU":      # Atef's
                raise RuntimeError("channel_not_found")
            self.calls.append(k)
            return {"ok": True}
        with mock.patch.object(S, "post_nophone_report", boom):
            out, lines, _ = self._tick([_row("atef", "23467", "11:50"),
                                        _row("carlos", "11580", "11:58"),
                                        _row("khalil-nds", "11901", "11:40")], "12:03")
        self.assertEqual(sorted(o["office"] for o in out), ["11580", "11901"])
        self.assertTrue(any("FAILED" in l and "Atef" in l for l in lines))


class StaysOnOurSide(unittest.TestCase):
    """push_todo imports post.py, which must never reach an office computer;
    the shipped half is resume_push, which already does."""

    def test_the_poster_half_does_not_ship(self):
        self.assertNotIn("automations/icd_alerts/push_todo.py", package.AGENT_FILES)
        self.assertIn("automations/icd_alerts/resume_push.py", package.AGENT_FILES)

    def test_the_shipped_half_imports_nothing_new_at_module_level(self):
        import ast
        tree = ast.parse(pathlib.Path(RP.__file__).read_text())
        top = {n.module for n in tree.body if isinstance(n, ast.ImportFrom)}
        self.assertEqual({m for m in top if m and m.startswith("automations")},
                         {"automations.icd_alerts"})

    def test_the_preview_outside_the_hours_posts_nothing(self):
        buf = io.StringIO()
        with redirect_stdout(buf), \
                mock.patch.object(PT, "post_push_todo",
                                  side_effect=AssertionError("posted")):
            rc = PT.main(["--at", "09:30"])
        self.assertEqual(rc, 0)
        self.assertIn("not a posting hour", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
