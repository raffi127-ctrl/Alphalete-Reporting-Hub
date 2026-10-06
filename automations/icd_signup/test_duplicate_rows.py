"""A key on two rows: the human's answer wins, wherever it sits.

Jairo submitted ~15 times on 2026-09-29. Some keys landed on two or three rows,
the decline reached only the first, readers took the last, and five refused
keys came back on -- any relay from them would have gone to Megan's DM.
No network: every sheet here is a fake.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import offices as O
from automations.icd_signup import store
from automations.icd_signup.schema import IcdSignup


def _row(key, status, **kw):
    r = {"office_key": key, "owner": "Jairo Ruiz", "status": status,
         "timezone": "America/New_York", "platform": "mac", "campaign": "nds"}
    r.update(kw)
    return r


class AlertsReadTheStrongestRow(unittest.TestCase):

    def test_a_pending_duplicate_does_not_undo_a_decline(self):
        got = O._one_per_key([_row("jairo7", "declined"),
                              _row("jairo7", "pending")])
        self.assertFalse(got["jairo7"].active)

    def test_order_does_not_matter(self):
        got = O._one_per_key([_row("jairo7", "pending"),
                              _row("jairo7", "declined")])
        self.assertFalse(got["jairo7"].active)

    def test_an_approved_key_stays_on_beside_a_pending_copy(self):
        got = O._one_per_key([_row("jairo15", "approved"),
                              _row("jairo15", "pending")])
        self.assertTrue(got["jairo15"].active)


class TheStoreReadsTheStrongestRow(unittest.TestCase):

    def test_one_entry_per_key_with_the_decline(self):
        recs = [IcdSignup.from_row(r) for r in
                (_row("jairo", "declined"), _row("jairo", "pending"),
                 _row("jairo", "pending"), _row("kash", "approved"))]
        got = {s.office_key: s.status for s in store.one_per_key(recs)}
        self.assertEqual(got, {"jairo": "declined", "kash": "approved"})


class DecliningReachesEveryRow(unittest.TestCase):

    def test_every_row_for_the_key_is_written(self):
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [
            ["office_key", "owner", "status", "note"],
            ["jairo", "Jairo Ruiz", "declined", ""],
            ["kash", "Kash", "approved", ""],
            ["jairo", "Jairo Ruiz", "pending", ""],
        ]
        with mock.patch.object(store, "_tab", return_value=tab):
            self.assertTrue(store.set_status("jairo", "declined", note="dup"))
        ranges = [u["range"] for u in tab.batch_update.call_args[0][0]]
        self.assertEqual(sorted(ranges), ["C2", "C4", "D2", "D4"])


class NoKeyIsPickedBlind(unittest.TestCase):

    def test_an_unreadable_tab_saves_a_draft_and_mints_nothing(self):
        rec = IcdSignup.from_row(_row("", "pending", contact="j@x.com"))
        with mock.patch.object(store, "_read_rows",
                               side_effect=RuntimeError("quota")), \
             mock.patch.object(store, "_local", return_value=[]), \
             mock.patch.object(store, "_save_local") as save, \
             mock.patch.object(store, "_tab") as tab:
            saved, landed = store.submit(rec)
        self.assertFalse(landed)
        save.assert_called_once()
        tab.return_value.append_row.assert_not_called()


if __name__ == "__main__":
    unittest.main()
