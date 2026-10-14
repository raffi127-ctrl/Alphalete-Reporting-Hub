"""Offline tests — no OwnerVille, no Slack.
    python -m unittest automations.rep_knock_threads.test_rep_knock_threads
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.rep_knock_threads import pull as P
from automations.rep_knock_threads import render as R
from automations.rep_knock_threads import run as RUN
from automations.rep_knock_threads import stats as S

OK = "Success, 95 feet is within range of 799 feet."
FAR = "Failure, 0.43 miles is out of range of 799 feet."
OFF = "Failure, User denied Geolocation"
NONE = "GPS data not available"


def k(when, status="No Answer", gps=OK, kid=1, rep="Ann Lee", rid="1",
      office="Alphalete Marketing, INC. (11280)"):
    return {"rep": rep, "rep_id": rid, "office": office, "when": when,
            "status": status, "color": "#E3DFDB", "address": "1 Main St",
            "gps": gps, "knock_id": kid}


class GpsText(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual([P.gps_kind(g) for g in (OK, FAR, OFF, NONE)],
                         ["ok", "fail", "fail", "none"])

    def test_short(self):
        self.assertEqual(P.gps_short(OK), "95 ft")
        self.assertEqual(P.gps_short(FAR), "0.43 mi away")
        self.assertEqual(P.gps_short(OFF), "Location turned off")
        self.assertEqual(P.gps_short(NONE), "No GPS")
        self.assertEqual(P.gps_short("Failure, 977 feet is out of range of 799 feet."),
                         "977 ft away")


class Pull(unittest.TestCase):
    def test_normalize_reads_rep_from_html(self):
        raw = {"rep": '<div class="rep-name-wrapper">\r\n Alexis Renteria (9500294)\r\n</div>',
               "office": "X (11280)", "statusName": "No Answer",
               "when": "2026-10-12 12:35:09", "address": "5201  BARTLETT DR",
               "gps": OK, "color": "#E3DFDB", "knockId": 7}
        r = P.normalize(raw)
        self.assertEqual((r["rep"], r["rep_id"], r["address"]),
                         ("Alexis Renteria", "9500294", "5201 BARTLETT DR"))

    def test_other_office_is_refused(self):
        rows = [k("2026-10-12 12:00:00"), k("2026-10-12 12:05:00", office="Calvin (22162)")]
        with self.assertRaises(P.PullError):
            P.check_office(rows, dt.date(2026, 10, 12))


class Stats(unittest.TestCase):
    def test_week_is_monday_to_sunday(self):
        self.assertEqual(S.week_start(dt.date(2026, 10, 18)), dt.date(2026, 10, 12))
        self.assertEqual(S.week_start(dt.date(2026, 10, 19)), dt.date(2026, 10, 19))

    def test_gap_leaves_out_breaks_and_overnight(self):
        t = lambda s: dt.datetime.fromisoformat(s)
        times = [t("2026-10-12 12:00"), t("2026-10-12 12:02"), t("2026-10-12 12:06"),
                 t("2026-10-12 13:30"),                       # 84-min lunch: out
                 t("2026-10-13 09:00"), t("2026-10-13 09:03")]
        self.assertAlmostEqual(S.avg_gap_min(times), (2 + 4 + 3) / 3)

    def test_talk_to_and_gps_shares(self):
        rows = [k("2026-10-12 12:00:00", "No Answer", OK, 1),
                k("2026-10-12 12:01:00", "Already has AT&T", FAR, 2),
                k("2026-10-12 12:02:00", "Inaccessible", NONE, 3),
                k("2026-10-12 12:03:00", "Sale", OFF, 4)]
        s = S.rep_week(rows, dt.date(2026, 10, 12))
        self.assertEqual(s["talk_to"], 2)            # AT&T + Sale
        self.assertEqual((s["gps_ok"], s["gps_fail"], s["gps_none"]), (1, 2, 1))
        self.assertEqual(s["days"][0]["fails"], 2)
        self.assertTrue(s["days"][1]["future"])

    def test_flag_is_todays_25pct_on_enough_doors(self):
        few = [k(f"2026-10-12 12:0{i}:00", gps=FAR, kid=i) for i in range(5)]
        self.assertFalse(S.rep_week(few, dt.date(2026, 10, 12))["flagged"])
        under = [k(f"2026-10-12 12:{i:02d}:00", gps=FAR if i < 4 else OK, kid=i)
                 for i in range(20)]                                   # 20%
        self.assertFalse(S.rep_week(under, dt.date(2026, 10, 12))["flagged"])
        over = [k(f"2026-10-12 12:{i:02d}:00", gps=FAR if i < 5 else OK, kid=i)
                for i in range(20)]                                    # 25%
        self.assertTrue(S.rep_week(over, dt.date(2026, 10, 12))["flagged"])

    def test_streak_counts_worked_days_and_skips_days_off(self):
        def day(d, fails, n=20, rid="1"):
            return [k(f"{d} 12:{i:02d}:00", gps=FAR if i < fails else OK, kid=f"{d}{i}",
                      rid=rid) for i in range(n)]
        by_day = {
            dt.date(2026, 10, 9): day("2026-10-09", 2),    # under → stops here
            dt.date(2026, 10, 10): day("2026-10-10", 10),  # over
            dt.date(2026, 10, 11): [],                     # Sunday off — skipped
            dt.date(2026, 10, 12): day("2026-10-12", 6),   # over
            dt.date(2026, 10, 13): day("2026-10-13", 8),   # over (today)
        }
        self.assertEqual(S.streak("1", by_day, dt.date(2026, 10, 13)), 3)
        self.assertEqual(S.flags(3), "🚩🚩🚩")
        by_day[dt.date(2026, 10, 13)] = day("2026-10-13", 1)          # today under
        self.assertEqual(S.streak("1", by_day, dt.date(2026, 10, 13)), 0)

    def test_carry_over_needs_2_day_streak_within_2_days(self):
        def day(d, fails, n=20, rid="1"):
            return [k(f"{d} 12:{i:02d}:00", gps=FAR if i < fails else OK, kid=f"{d}{i}",
                      rid=rid) for i in range(n)]
        wed = dt.date(2026, 10, 14)
        by_day = {dt.date(2026, 10, 12): day("2026-10-12", 8),
                  dt.date(2026, 10, 13): day("2026-10-13", 8), wed: []}
        self.assertEqual(S.today_streak("1", by_day, wed), (2, True))      # carried in
        by_day[wed] = day("2026-10-14", 1)                                  # 20 doors, 5%
        self.assertEqual(S.today_streak("1", by_day, wed), (0, False))     # broken
        by_day[wed] = day("2026-10-14", 9)                                  # over again
        self.assertEqual(S.today_streak("1", by_day, wed), (3, False))
        by_day = {dt.date(2026, 10, 13): day("2026-10-13", 8), wed: []}     # 1 day only
        self.assertEqual(S.today_streak("1", by_day, wed), (0, False))
        by_day = {dt.date(2026, 10, 10): day("2026-10-10", 8),              # too long ago
                  dt.date(2026, 10, 11): day("2026-10-11", 8), wed: []}
        self.assertEqual(S.today_streak("1", by_day, wed), (0, False))

    def test_alert_counts_only_unseen_failures(self):
        rows = [k("2026-10-12 12:00:00", gps=FAR, kid=1),
                k("2026-10-12 12:01:00", gps=OFF, kid=2),
                k("2026-10-12 12:02:00", gps=OK, kid=3)]
        fresh = S.new_failures(rows, {"1"})
        self.assertEqual([r["knock_id"] for r in fresh], [2])
        self.assertEqual(S.alert_line(fresh), "🚩 1 new GPS failure — 1 location turned off")
        self.assertEqual(S.alert_line([]), "")


class Run(unittest.TestCase):
    def test_parent_is_name_plus_flags_only(self):
        self.assertEqual(RUN.parent_text("Ann Lee", 2), "*Ann Lee* 🚩🚩")

    def test_reset_deletes_only_lucys_messages_parent_last(self):
        class Fake:
            def __init__(self):
                self.deleted, self.files = [], []
            def conversations_replies(self, **kw):
                return {"messages": [
                    {"ts": "1.0", "user": "LUCY"},                          # parent
                    {"ts": "1.1", "user": "LUCY", "files": [{"id": "F1"}]},
                    {"ts": "1.2", "user": "REP"},                           # a rep's reply
                ]}
            def files_delete(self, file):
                self.files.append(file)
            def chat_delete(self, channel, ts):
                self.deleted.append(ts)
        c = Fake()
        RUN.time.sleep = lambda s: None
        self.assertTrue(RUN.clear_thread(c, "1.0", "LUCY"))
        self.assertEqual(c.deleted, ["1.1", "1.0"])
        self.assertEqual(c.files, ["F1"])

    def test_repost_clear_keeps_the_name_post(self):
        class Fake:
            deleted = []
            def conversations_replies(self, **kw):
                return {"messages": [{"ts": "1.0", "user": "LUCY"},
                                     {"ts": "1.1", "user": "LUCY"}]}
            def files_delete(self, file): pass
            def chat_delete(self, channel, ts): self.deleted.append(ts)
        c = Fake()
        RUN.time.sleep = lambda s: None
        RUN.clear_thread(c, "1.0", "LUCY", keep_parent=True)
        self.assertEqual(c.deleted, ["1.1"])

    def test_hours_window(self):
        at = lambda h: dt.datetime(2026, 10, 14, h, 0)
        self.assertFalse(RUN.in_window(at(9)))
        self.assertTrue(RUN.in_window(at(10)))
        self.assertTrue(RUN.in_window(at(21)))
        self.assertFalse(RUN.in_window(at(22)))

    def test_render_draws_a_card(self):
        rows = [k(f"2026-10-13 12:{i:02d}:00", gps=FAR if i % 4 == 0 else OK, kid=i)
                for i in range(40)]
        s = S.rep_week(rows, dt.date(2026, 10, 13))
        with tempfile.TemporaryDirectory() as d:
            pages = R.render(s, as_of=dt.datetime(2026, 10, 13, 15), out=Path(d) / "c.png")
            self.assertEqual([p.name for p in pages], ["c_p1.png", "c_p2.png", "c_p3.png"])   # summary + 41 door lines
            self.assertTrue(all(p.stat().st_size > 5000 for p in pages))

    def test_door_pages_split_and_continue_the_day_banner(self):
        day = {"date": dt.date(2026, 10, 13)}
        items = [("banner", day)] + [("row", {}, i) for i in range(95)]
        pages = R._paginate(items)
        self.assertEqual([len(p) for p in pages], [40, 40, 18])   # banner+39 / cont.+39 / cont.+17
        self.assertEqual(pages[1][0], ("banner", day, True))
        self.assertEqual(pages[0][0], ("banner", day, False))
        # a second day's banner with <5 rows of room left starts a new page
        day2 = {"date": dt.date(2026, 10, 12)}
        items = [("banner", day)] + [("row", {}, i) for i in range(36)] \
            + [("banner", day2)] + [("row", {}, i) for i in range(10)]
        pages = R._paginate(items)
        self.assertEqual(pages[1][0], ("banner", day2, False))


if __name__ == "__main__":
    unittest.main()
