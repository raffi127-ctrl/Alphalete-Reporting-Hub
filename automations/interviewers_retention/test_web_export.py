"""python -m unittest automations.interviewers_retention.test_web_export"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from automations.interviewers_retention import build, web_export as we


def _mapping(folder: Path):
    (folder / "office-mapping.json").write_text(json.dumps({
        "confirmed": [{"sheet_tab": "Drew Tepper - NDS", "office_id": "1", "as_owner": "DREW TEPPER"},
                      {"sheet_tab": "Andrew Burton", "office_id": "2", "as_owner": "Andre Burton Jr"}],
        "skip": [{"sheet_tab": "Closed Guy", "office_id": "3", "retired": "2026-10-01"},
                 {"sheet_tab": "No Access Owner", "office_id": "4"}],
    }), encoding="utf-8")


class OrgTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _mapping(Path(self.tmp.name))
        self.org = we.Org(Path(self.tmp.name), overrides={"Nic Lujan": "org", "Drew Tepper": "not-org"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_names(self):
        self.assertTrue(self.org.has_name("Andre Burton"))          # one name inside the other
        self.assertTrue(self.org.has_name("No Access Owner"))       # skip, not retired
        self.assertFalse(self.org.has_name("Closed Guy"))           # retired office
        self.assertFalse(self.org.has_name("Somebody Else"))
        self.assertTrue(self.org.has_name("Nic Lujan"))             # forced in
        self.assertFalse(self.org.has_name("Drew Tepper"))          # forced out

    def test_ids_skip_retired_and_suffix(self):
        self.assertEqual(self.org.ids, {"1": "Drew Tepper", "2": "Andrew Burton"})

    def test_org_rows(self):
        d = dt.date(2026, 11, 16)
        r = lambda oid, owner: build.DayRow(d, d, oid, owner, 2, 1)      # noqa: E731
        all_rows = [r("2", "ANDRE BURTON JR"), r("9", "Outsider"), r("7", "Nic L")]
        service = [build.DayRow(d, d, "7", "Nic Lujan", 2, 1)]
        out = we.org_rows(all_rows, service, self.org)
        self.assertEqual(sorted((x.office_id, x.owner) for x in out),
                         [("2", "Andrew Burton"), ("7", "Nic Lujan")])


class JsonTest(unittest.TestCase):
    def test_views_and_chunks(self):
        d = dt.date(2026, 11, 23)
        li = build.DayLine("Ana", owner="In Org", days={d: [2, 1]}, history=[0.5])
        lo = build.DayLine("Out Org Office", days={d: [4, 4]}, history=[None])
        days_b = build.DayBoard("W", "s", "Interviewer", [d], [li, build.DayLine("Bo", owner="Out", days={d: [1, 1]})],
                                history_labels=["11/16"])
        off_b = build.DayBoard("W", "s", "Office", [d], [lo], history_labels=["11/16"])
        pod_i = build.Board("P", "s", "Interviewer", [build.Line("Ana", 2, 1, owner="In Org")])
        pod_o = build.Board("P", "s", "Office", [build.Line("In Org", 2, 1)])
        org = we.Org(Path(tempfile.mkdtemp()), overrides={"In Org": "org"})
        doc = we.to_json(service=(days_b, off_b, pod_i, pod_o), org_boards=(off_b, pod_o), org=org,
                         intro="<b>x</b>", notes=["n"], generated=dt.datetime(2026, 11, 26, 9, 0))
        self.assertEqual(set(doc["views"]), {"service", "org"})
        self.assertEqual(len(doc["views"]["service"]["boards"][0]["lines"]), 2)
        self.assertEqual([l["name"] for l in doc["views"]["org"]["boards"][0]["lines"]], ["Ana"])
        self.assertEqual(doc["views"]["service"]["boards"][0]["lines"][0]["days"], [[2, 1]])
        self.assertEqual(doc["intro"], "x")
        old = we.CHUNK
        try:
            we.CHUNK = 100
            parts = we.chunks(doc)
            self.assertGreater(len(parts), 1)
            self.assertEqual(json.loads("".join(parts)), json.loads(json.dumps(doc)))
        finally:
            we.CHUNK = old


if __name__ == "__main__":
    unittest.main()
