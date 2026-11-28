import unittest

from automations.rc_contact_sync import unread_guard as G


def m(i, direction="Inbound", status="Unread"):
    return {"id": i, "direction": direction, "readStatus": status}


class UnreadGuard(unittest.TestCase):
    def test_only_inbound_unread_is_remembered(self):
        self.assertEqual(G.unread_inbound([m(1), m(2, status="Read"), m(3, "Outbound")]), {"1"})

    def test_restores_only_what_lucy_turned_read(self):
        before = {"1", "2"}
        after = [m(1, status="Read"), m(2), m(3, status="Read")]   # 3 was read before: leave it
        self.assertEqual(G.to_restore(before, after), {"1"})

    def test_job_runs_when_snapshot_fails(self):
        orig = G._watch
        G._watch = lambda: (_ for _ in ()).throw(RuntimeError("no creds"))
        try:
            self.assertEqual(G.guarded(lambda: 0, log=lambda *a: None), 0)
        finally:
            G._watch = orig


if __name__ == "__main__":
    unittest.main()
