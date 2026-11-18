"""A busy relay (shared Apps Script lock) waits for the next pass; it does not
turn the LucyECO Social card red (11/16 + 11/17, raf's office)."""
import unittest

from automations.headshots import eco


class RelayBusy(unittest.TestCase):
    def test_lock_timeout_is_busy(self):
        e = eco.EcoError("relay refused: Exception: Lock timeout: another "
                         "process was holding the lock for too long.")
        self.assertTrue(eco.is_busy(e))

    def test_own_deadline_is_busy(self):
        e = eco.EcoError("relay didn't answer in 90s -- trying again next tick")
        self.assertTrue(eco.is_busy(e))

    def test_real_refusal_still_fails(self):
        self.assertFalse(eco.is_busy(eco.EcoError("relay refused: bad admin key")))
        self.assertFalse(eco.is_busy(eco.EcoError("relay answered a web page, not JSON")))

    def test_other_errors_still_fail(self):
        self.assertFalse(eco.is_busy(RuntimeError("Lock timeout")))
        self.assertFalse(eco.is_busy(ValueError("boom")))


if __name__ == "__main__":
    unittest.main()
