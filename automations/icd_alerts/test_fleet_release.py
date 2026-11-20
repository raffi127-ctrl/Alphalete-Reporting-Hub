"""The office-release reading: what each group means, and what it must not say."""
import unittest
from unittest import mock

from automations.icd_alerts import fleet_release as FR
from automations.icd_alerts import relay as R


class _Tab:
    def __init__(self, values):
        self._v = values

    def get_all_values(self):
        return self._v


class _Book:
    def __init__(self, tabs):
        self._tabs = tabs

    def worksheet(self, name):
        if name not in self._tabs:
            raise KeyError(name)
        return _Tab(self._tabs[name])


def _row(office, day, machines):
    import json
    r = [""] * 11
    r[0], r[1] = office, day
    r[10] = json.dumps(machines)
    return r


def _book(rows):
    return _Book({FR.P.RELAY_TAB: [["office", "day"]] + rows,
                  FR.P.KNOCKS_TAB: [["office", "day"]]})


class BlobRelease(unittest.TestCase):
    def test_a_missing_key_is_none_not_empty(self):
        """Too old to be asked must not read as 'answered nothing'."""
        self.assertIsNone(FR._blob_release({"name": "iMac"}))

    def test_an_empty_stamp_is_empty_not_none(self):
        self.assertEqual("", FR._blob_release({"agent_release": ""}))

    def test_a_release_comes_back_trimmed(self):
        self.assertEqual(
            "2026.11.19.2",
            FR._blob_release({"agent_release": " 2026.11.19.2 "}))

    def test_junk_blob_does_not_raise(self):
        self.assertIsNone(FR._blob_release("not a dict"))


class Grouping(unittest.TestCase):
    def _report(self, rows, published="2026.11.19.2"):
        out = []
        return FR.report(book=_book(rows), published=published,
                         log=out.append), out

    def test_current_behind_and_unknown_land_in_their_own_groups(self):
        got, _ = self._report([
            _row("raf", "2026-11-19", {
                "m1": {"name": "Raf iMac", "last": "2026-11-19T17:00:00",
                       "agent_release": "2026.11.19.2"}}),
            _row("kash", "2026-11-19", {
                "m2": {"name": "Kash Mac", "last": "2026-11-19T17:00:00",
                       "agent_release": "2026.11.18.1"}}),
            _row("old", "2026-11-19", {
                "m3": {"name": "Old Mac", "last": "2026-11-19T17:00:00"}}),
        ])
        self.assertEqual(["raf"], [m["office"] for m in got["current"]])
        self.assertEqual(["kash"], [m["office"] for m in got["behind"]])
        self.assertEqual(["old"], [m["office"] for m in got["unknown"]])

    def test_an_empty_stamp_is_its_own_group_not_behind(self):
        """'never self-updated' is a different problem from 'a release late'."""
        got, _ = self._report([
            _row("new", "2026-11-19", {
                "m4": {"name": "New Mac", "last": "2026-11-19T17:00:00",
                       "agent_release": ""}}),
        ])
        self.assertEqual([], got["behind"])
        self.assertEqual(["new"], [m["office"] for m in got["never"]])

    def test_unknown_is_never_reported_as_an_all_clear(self):
        _, lines = self._report([
            _row("old", "2026-11-19", {
                "m3": {"name": "Old Mac", "last": "2026-11-19T17:00:00"}}),
        ])
        self.assertTrue(any("not an all-clear" in ln for ln in lines), lines)

    def test_newest_row_wins_for_the_same_machine(self):
        """An office relays all day; yesterday's release must not be the answer."""
        got, _ = self._report([
            _row("raf", "2026-11-18", {
                "m1": {"name": "Raf iMac", "last": "2026-11-18T09:00:00",
                       "agent_release": "2026.11.18.1"}}),
            _row("raf", "2026-11-19", {
                "m1": {"name": "Raf iMac", "last": "2026-11-19T17:00:00",
                       "agent_release": "2026.11.19.2"}}),
        ])
        self.assertEqual(["raf"], [m["office"] for m in got["current"]])
        self.assertEqual([], got["behind"])

    def test_no_published_release_means_nothing_is_called_current(self):
        """GitHub unreachable must not silently mark the fleet up to date."""
        got, _ = self._report([
            _row("raf", "2026-11-19", {
                "m1": {"name": "Raf iMac", "last": "2026-11-19T17:00:00",
                       "agent_release": "2026.11.19.2"}}),
        ], published=None)
        self.assertEqual([], got["current"])


class Payload(unittest.TestCase):
    def test_every_payload_carries_the_release(self):
        """Four call sites; an office that only knocks must answer too."""
        import re
        with open(R.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertEqual(4, len(re.findall(r'"agent_release": agent_release\(\)', src)),
                         "every payload that carries 'agent' must carry the release")
        self.assertEqual(
            src.count('"agent": AGENT_VERSION,'),
            len(re.findall(r'"agent_release": agent_release\(\)', src)))

    def test_release_is_empty_not_an_exception_when_unreadable(self):
        with mock.patch("automations.icd_alerts.selfupdate.applied_release",
                        side_effect=OSError("no stamp")):
            self.assertEqual("", R.agent_release())

    def test_the_relay_script_keeps_it(self):
        """The .gs must merge it, or the Macs report into a void."""
        import pathlib
        gs = (pathlib.Path(R.__file__).resolve().parents[2]
              / "resources" / "icd-alerts-relay.gs").read_text(encoding="utf-8")
        self.assertIn("agent_release: body.agent_release", gs)


if __name__ == "__main__":
    unittest.main()
