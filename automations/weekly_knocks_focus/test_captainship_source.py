"""python -m unittest automations.weekly_knocks_focus.test_captainship_source

The --captainships source, offline: the OFFICE TOTALS it re-computes from Lucy
3's rows sidecar must be the row the weekly board itself draws, and a board
without its sidecar (or with no reps) is not a board.
"""
import contextlib
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.captainship_drafts import config as CC
from automations.knocks_access_watch import audit as A
from automations.weekly_knock_dispositions import board as B
from automations.weekly_knock_dispositions.test_teams import _rep
from automations.weekly_knocks_focus import box as BX
from automations.weekly_knocks_focus import run as R

SAT = dt.date(2026, 9, 12)


def _write(root: Path, captain: str, office: str, payload):
    d = root / f"knock_dispo_{captain}" / R._slug(office)
    d.mkdir(parents=True)
    png = d / f"weekly_knock_dispositions_{SAT.isoformat()}.png"
    png.write_bytes(b"png")
    if payload is not None:
        (d / f"rows_{png.stem}.json").write_text(json.dumps(payload),
                                                   encoding="utf-8")
    return png


class NoOfficeAccess(unittest.TestCase):
    """A missing board is a SKIP only when the access snapshot says we cannot
    pull that office — the 2026-09-17 69/71 exit 1 on Austin Eldredge and
    Nigel Gilbert, two of Pat's eight ungranted owners."""

    def setUp(self):
        R._ACCESS_SNAPSHOT = None
        self.addCleanup(setattr, R, "_ACCESS_SNAPSHOT", None)

    @staticmethod
    def _snapshot(statuses, age_days=0):
        when = dt.datetime.now() - dt.timedelta(days=age_days)
        return {"checked_at": when.isoformat(timespec="seconds"),
                "statuses": statuses}

    def _load(self, state):
        return mock.patch(
            "automations.knocks_access_watch.run.load_state",
            return_value=state)

    def test_ungranted_owner_is_a_skip(self):
        with self._load(self._snapshot({"pat/Nigel Gilbert": A.MISSING,
                                        "pat/Bill Fischer": A.PENDING})):
            why = R._no_office_access("Nigel Gilbert")
        self.assertIn("not on the Office Access list", why)

    def test_granted_owner_still_fails(self):
        with self._load(self._snapshot({"pat/John Richard Young": A.OK})):
            self.assertIsNone(R._no_office_access("John Richard Young"))

    def test_reachable_on_either_captainship_wins(self):
        with self._load(self._snapshot({"pat/Alex Touati": A.MISSING,
                                        "tony/Alex Touati": A.OK})):
            self.assertIsNone(R._no_office_access("Alex Touati"))

    def test_unknown_owner_no_snapshot_or_stale_snapshot_all_fail(self):
        with self._load(self._snapshot({"pat/Nigel Gilbert": A.MISSING})):
            self.assertIsNone(R._no_office_access("Eric Zech"))
        with self._load({}):
            R._ACCESS_SNAPSHOT = None
            self.assertIsNone(R._no_office_access("Nigel Gilbert"))
        with self._load(self._snapshot({"pat/Nigel Gilbert": A.MISSING},
                                       age_days=30)):
            R._ACCESS_SNAPSHOT = None
            self.assertIsNone(R._no_office_access("Nigel Gilbert"))

    def test_the_sweep_counts_a_gapped_owner_as_fine(self):
        def _run(office, why):
            with contextlib.ExitStack() as st:
                st.enter_context(mock.patch.object(
                    R, "_captainship_board", return_value=(None, None)))
                st.enter_context(mock.patch.object(
                    R, "_tab_for", return_value=office))
                st.enter_context(mock.patch.object(
                    R, "_no_office_access", return_value=why))
                return R.run_office(office, SAT, None, True,
                                    skip_missing=True, source="captainship")

        self.assertTrue(_run("Nigel Gilbert", "not on the Office Access list"))
        self.assertFalse(_run("Eric Zech", None))


class CaptainshipBoard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(CC, "RENDER_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_totals_are_the_boards_own_row(self):
        reps = [_rep("Ana Uno", talk=30, knocks=600),
                _rep("Beto Dos", talk=12, knocks=300)]
        png = _write(self.root, "pat", "John Richard Young",
                     {"ov_rows": reps, "apps": {"Ana Uno": 3}, "dispo_cols": []})
        data, got = R._captainship_board("John Richard Young", SAT)
        self.assertEqual(got, png)
        want = [r for r in B.compute_rows(reps, {"Ana Uno": 3}, [])
                if r[1] == B.TOTALS_LABEL]
        self.assertEqual(len(want), 1)
        want = want[0]
        self.assertEqual(data["totals"], want)
        self.assertEqual(data["headers"], B.headers_for([], False))
        # and it lands in the box like the Sunday file does
        from automations.weekly_knocks_focus.test_box import COL_B
        header, updates, _missing = BX.plan(data["headers"], data["totals"],
                                            COL_B)
        self.assertEqual(header, 46)
        by_label = {lab: v for _r, lab, v in updates}
        self.assertEqual(by_label["Mon-Fri Total Knocks"],
                         want[data["headers"].index("Mon–Fri Total Knocks")])

    def test_no_sidecar_or_no_reps_is_no_board(self):
        _write(self.root, "pat", "Eric Zech", None)
        self.assertEqual(R._captainship_board("Eric Zech", SAT), (None, None))
        _write(self.root, "tony", "Tony Chavez",
               {"ov_rows": [], "apps": None, "dispo_cols": []})
        self.assertEqual(R._captainship_board("Tony Chavez", SAT), (None, None))

    def test_other_week_is_not_found(self):
        _write(self.root, "pat", "Eric Zech",
               {"ov_rows": [_rep("Ana Uno")], "apps": None, "dispo_cols": []})
        self.assertEqual(R._captainship_board("Eric Zech", dt.date(2026, 9, 19)),
                         (None, None))


if __name__ == "__main__":
    unittest.main()


class CacheBackfill(unittest.TestCase):
    """--from-cache: an old week's totals come from the shared pull cache, with
    the apps columns left blank rather than guessed."""

    def test_totals_without_apps(self):
        reps = [_rep("Ana Uno", talk=30, knocks=600)]
        from automations.shared import knock_week_cache as KWC
        week = {"offices": {KWC.office_key("Ana's Office", None): {
            "office": "Ana's Office", "schema": KWC.SCHEMA,
            "rows": reps, "dispo_cols": []}}}
        with mock.patch.object(KWC, "_read_week", return_value=week):
            data = R._cache_board("Ana's Office", SAT)
        want = [r for r in B.compute_rows(reps, None, []) if r[1] == B.TOTALS_LABEL][0]
        self.assertEqual(data["totals"], want)
        i = data["headers"].index("Mon–Sat Total Apps")
        self.assertEqual(str(data["totals"][i]).strip(), "")

    def test_no_hit_is_no_board(self):
        from automations.shared import knock_week_cache as KWC
        with mock.patch.object(KWC, "_read_week", return_value={}):
            self.assertIsNone(R._cache_board("Nobody", SAT))
        empty = {"offices": {KWC.office_key("Nobody", None): {
            "office": "Nobody", "schema": KWC.SCHEMA,
            "rows": [], "dispo_cols": []}}}
        with mock.patch.object(KWC, "_read_week", return_value=empty):
            self.assertIsNone(R._cache_board("Nobody", SAT))


class CacheSchemaFloor(unittest.TestCase):
    """--min-schema: an older entry is readable on purpose for a backfill, and
    what it lacks comes out BLANK (board.OPTIONAL_COLUMNS), never guessed."""

    def setUp(self):
        from automations.shared import knock_week_cache as KWC
        self.KWC = KWC
        rows = [_rep("Ana Uno", talk=30, knocks=600)]
        for r in rows:                      # an older pull carried no per-day leads
            r.pop("total_leads_knocked", None)
        self.week = {"offices": {KWC.office_key("Ana's Office", None): {
            "office": "Ana's Office", "schema": 5,
            "rows": rows, "dispo_cols": []}}}

    def test_default_refuses_an_older_entry(self):
        with mock.patch.object(self.KWC, "_read_week", return_value=self.week):
            self.assertIsNone(R._cache_board("Ana's Office", SAT))

    def test_floor_lets_it_through(self):
        with mock.patch.object(self.KWC, "_read_week", return_value=self.week):
            data = R._cache_board("Ana's Office", SAT, min_schema=5)
        self.assertIsNotNone(data)
        self.assertEqual(data["totals"][1], B.TOTALS_LABEL)
