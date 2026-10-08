"""raf_guest: the filter keeps exactly the roster's rows, and the merge can
only ever ADD rows — a missing or stale Lucy 1 pull must cost the guest reps'
rows (loudly), never the report. All offline: no SaraPlus, no Sheets."""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import unittest
from unittest import mock

from automations.sp_order_log import raf_guest as RG


def _csv(rows, fields=("User Name", "Order ID", "Status")):
    out = io.StringIO()
    out.write(",".join(fields) + "\n")
    for r in rows:
        out.write(",".join(str(r.get(f, "")) for f in fields) + "\n")
    return out.getvalue().encode("utf-8-sig")


ROSTER = ["Jorge Gramajo", "Jose Pimentel Lugo", "Yariel Caban"]


class TestFilter(unittest.TestCase):
    def _filter(self, data):
        with mock.patch("automations.total_knocks.guests.roster",
                        return_value=list(ROSTER)):
            return RG.filter_csv(data, log=lambda *a, **k: None)

    def test_keeps_roster_drops_host(self):
        data = _csv([
            {"User Name": "JORGE GRAMAJO", "Order ID": "1"},
            {"User Name": "Jose Manuel Pimentel Lugo", "Order ID": "2"},
            {"User Name": "Yariel Caban Roadtrip", "Order ID": "3"},
            {"User Name": "Rafael Hidalgo", "Order ID": "4"},
            {"User Name": "JORGE GRAMAJO", "Order ID": "5"},
        ])
        filtered, counts = self._filter(data)
        kept = list(RG.csv.DictReader(io.StringIO(
            filtered.decode("utf-8-sig"))))
        self.assertEqual({r["Order ID"] for r in kept}, {"1", "2", "3", "5"})
        self.assertEqual(counts, {"Jorge Gramajo": 2,
                                  "Jose Pimentel Lugo": 1,
                                  "Yariel Caban": 1})

    def test_username_header_spacing(self):
        data = _csv([{"UserName": "JORGE GRAMAJO", "Order ID": "1"}],
                    fields=("UserName", "Order ID"))
        filtered, counts = self._filter(data)
        self.assertEqual(counts, {"Jorge Gramajo": 1})

    def test_no_username_column_raises(self):
        data = _csv([{"Rep": "JORGE GRAMAJO"}], fields=("Rep",))
        with self.assertRaises(RuntimeError):
            self._filter(data)

    def test_name_map_override(self):
        data = _csv([{"User Name": "GLORIA SCOTT", "Order ID": "1"}])
        with mock.patch.dict(RG.RAF_NAME_MAP,
                             {"GLORIA SCOTT": "Yariel Caban"}):
            _, counts = self._filter(data)
        self.assertEqual(counts, {"Yariel Caban": 1})


class TestMerge(unittest.TestCase):
    CARLOS = _csv([{"User Name": "OWN REP", "Order ID": "C1"}])
    GUEST = _csv([{"User Name": "JORGE GRAMAJO", "Order ID": "R1"}])

    def _env(self, *, hours_old=0.0, csv_bytes=None):
        pulled = dt.datetime.now() - dt.timedelta(hours=hours_old)
        return {"pulled": pulled.isoformat(timespec="seconds"),
                "start": "2026-09-07", "end": "2026-10-08", "rows": 1,
                "csv": base64.b64encode(
                    self.GUEST if csv_bytes is None else csv_bytes).decode()}

    def _rows(self, data):
        return list(RG.csv.DictReader(io.StringIO(
            data.decode("utf-8-sig"))))

    def test_fresh_pull_merges(self):
        out = RG.merge(self.CARLOS, log=lambda *a, **k: None,
                       fetcher=lambda log: self._env())
        self.assertEqual([r["Order ID"] for r in self._rows(out)],
                         ["C1", "R1"])

    def test_stale_pull_is_refused(self):
        out = RG.merge(self.CARLOS, log=lambda *a, **k: None,
                       fetcher=lambda log: self._env(hours_old=48))
        self.assertEqual(out, self.CARLOS)

    def test_missing_pull_is_survived(self):
        out = RG.merge(self.CARLOS, log=lambda *a, **k: None,
                       fetcher=lambda log: None)
        self.assertEqual(out, self.CARLOS)

    def test_fetcher_blowup_is_survived(self):
        def boom(log):
            raise RuntimeError("sheets down")
        out = RG.merge(self.CARLOS, log=lambda *a, **k: None, fetcher=boom)
        self.assertEqual(out, self.CARLOS)

    def test_column_union_keys_by_header(self):
        guest = _csv([{"User Name": "JORGE GRAMAJO", "Order ID": "R1",
                       "Fiber Speed": "1G"}],
                     fields=("User Name", "Order ID", "Fiber Speed"))
        out = RG.merge_rows(self.CARLOS, guest, log=lambda *a, **k: None)
        rows = self._rows(out)
        self.assertEqual(rows[0]["Fiber Speed"], "")
        self.assertEqual(rows[1]["Fiber Speed"], "1G")
        self.assertEqual(rows[1]["Order ID"], "R1")

    def test_envelope_round_trip(self):
        env = json.loads(json.dumps(self._env()))
        self.assertLess(RG._age_hours(env), 1.0)


if __name__ == "__main__":
    unittest.main()
