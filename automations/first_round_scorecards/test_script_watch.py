import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.first_round_scorecards import grade
from automations.first_round_scorecards import script_watch as sw

DAY = dt.date(2026, 10, 12)


def answer(**kw):
    a = {"is_first_round_script": True, "not_script_reason": "",
         "changes": ["Entry pay is now $1,100-1,600 a week."],
         "lines": [{"portion": "face_to_face", "text": "All face to face."},
                   {"portion": "management", "text": "Management in 6 months."},
                   {"portion": "wrap_up", "text": "Call before 5pm."}],
         "keys": [{"portion": p, "key": "it"} for p in ("face_to_face", "management", "wrap_up")],
         "not_in_first_round": ["pay"],
         "rules": [{"item": k, "rule": f"rule {k}"} for k in sw.ITEM_KEYS],
         "mon_fri_ok": False}
    a.update(kw)
    return a


class PickTest(unittest.TestCase):
    def test_newest_file_in_the_script_folder(self):
        bms = [{"id": "Bk1", "title": "1st ROUNDS SCRIPT", "type": "folder"},
               {"id": "Bk2", "parent_id": "Bk1", "title": "old.pdf", "entity_id": "F0AAAAAAAA1",
                "date_created": 100},
               {"id": "Bk3", "parent_id": "Bk1", "title": "new.pdf",
                "link": "https://x.slack.com/files/U1/F0BBBBBBBB2/new.pdf", "date_created": 200},
               {"id": "Bk4", "title": "Office address", "link": "https://maps.google.com"}]
        self.assertEqual(sw.pick(bms)["id"], "Bk3")
        self.assertEqual(sw._file_id(sw.pick(bms)), "F0BBBBBBBB2")

    def test_no_script_file(self):
        self.assertIsNone(sw.pick([{"id": "B", "title": "1st ROUNDS SCRIPT"},
                                   {"id": "C", "title": "Zoom link", "link": "https://zoom.us"}]))


class OverrideTest(unittest.TestCase):
    def test_answer_becomes_override(self):
        o = sw.to_override(answer())
        self.assertEqual(o["na"], ["pay"])
        self.assertIn("pay_entry", o["drop"])
        self.assertNotIn("wrap_up", o["drop"])

    def test_missing_rule_is_refused(self):
        a = answer(rules=[{"item": "retail", "rule": "x"}])
        with self.assertRaises(ValueError):
            sw.to_override(a)

    def test_grade_loads_it_and_can_go_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "o.json"
            path.write_text(json.dumps({"Jairo Ruiz": sw.to_override(answer())}), encoding="utf-8")
            with mock.patch.object(grade, "OVERRIDES", path):
                grade.load_overrides()
                b = grade.build("Jairo Ruiz")
                self.assertEqual([k for k, _ in b["portions"]],
                                 ["face_to_face", "management", "wrap_up"])
                self.assertIn("rule commute", b["rules"])
                self.assertEqual(b["na"], {"pay"})
                path.unlink()
                grade.load_overrides()
                self.assertEqual(grade.OFFICES["Jairo Ruiz"], {"format": "profits"})
        grade.load_overrides()


class FakeSlack:
    token = "xoxp-test"

    def __init__(self, bms):
        self.bms, self.dms = bms, []

    def api_call(self, method, params=None):
        return {"bookmarks": self.bms}

    def conversations_open(self, users):
        return {"channel": {"id": "G1"}}

    def chat_postMessage(self, channel, text, **kw):
        self.dms.append(text)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patches = [mock.patch.object(sw, "LEDGER", d / "seen.json"),
                        mock.patch.object(sw, "OUT_DIR", d),
                        mock.patch.object(sw, "SCRIPTS_DIR", d / "scripts"),
                        mock.patch.object(grade, "OVERRIDES", d / "o.json"),
                        mock.patch.object(sw, "channels", lambda: {"C1": "Jairo Ruiz"})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()
        grade.load_overrides()

    def bms(self, fid, when):
        return [{"id": "B1", "title": "1st ROUNDS SCRIPT"},
                {"id": "B2", "parent_id": "B1", "title": "s.pdf", "entity_id": fid,
                 "date_created": when}]

    def test_first_look_only_remembers_then_a_new_file_is_applied(self):
        slack = FakeSlack(self.bms("F0AAAAAAAA1", 1))
        self.assertEqual(sw.check(client=slack, today=DAY), 0)
        self.assertEqual(slack.dms, [])
        # same day again: no second pass
        slack.bms = self.bms("F0BBBBBBBB2", 2)
        self.assertEqual(sw.check(client=slack, today=DAY), 0)
        with mock.patch.object(sw, "_download", return_value=({"name": "s.pdf",
                                                               "filetype": "pdf"}, b"%PDF")), \
                mock.patch.object(sw, "read_script", return_value=answer()):
            self.assertEqual(sw.check(client=slack, today=DAY + dt.timedelta(days=1)), 1)
        self.assertIn("New 1st round script for Jairo Ruiz", slack.dms[0])
        self.assertIn("$1,100-1,600", slack.dms[0])
        self.assertEqual(grade.build("Jairo Ruiz")["na"], {"pay"})

    def test_unreadable_file_keeps_old_script_and_retries(self):
        slack = FakeSlack(self.bms("F0AAAAAAAA1", 1))
        sw.check(client=slack, today=DAY)
        slack.bms = self.bms("F0BBBBBBBB2", 2)
        with mock.patch.object(sw, "_download", return_value=({"name": "s.pdf"}, b"x")), \
                mock.patch.object(sw, "read_script", side_effect=RuntimeError("boom")):
            self.assertEqual(sw.check(client=slack, today=DAY + dt.timedelta(days=1)), 0)
        self.assertIn("couldn't read it", slack.dms[0])
        self.assertNotIn("C1", json.loads(sw.LEDGER.read_text(encoding="utf-8")))
        self.assertEqual(grade.OFFICES["Jairo Ruiz"], {"format": "profits"})


if __name__ == "__main__":
    unittest.main()
