"""A day the office's ECO machine relayed nothing, on a login with no Office
Access to that office, is "no knocks logged" — not a failure (Eve 2026-11-23:
Lucy 2's login lost the B2B offices when Carlos moved to NDS; Sunday 11/22
paged for Luke/Eveliz/Valeria who relay fine every other day)."""
import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

from automations.b2b_metrics import runner as r

ACCESS_ERR = RuntimeError(
    "Couldn't impersonate 'Luke Baldwin' in ownerville: not on this login's "
    "ownerville Office Access list — office 20958 is not listed")


class _O:
    key = "luke"
    knocks_office = "Luke Baldwin"
    owner = "Luke Baldwin"


def _run(relay_msg, scrape_exc):
    def relay(key, name, day, log=print):
        log(relay_msg)
        return None

    def scrape(name, day):
        raise scrape_exc

    with mock.patch("automations.rashad_metrics.knocks_relay.relayed_rows",
                    relay), \
         mock.patch("automations.rashad_metrics.knocks_pull.pull_office_knocks",
                    scrape):
        return r._knocks(_O(), Path("."), lambda *a: None,
                         today=dt.date(2026, 11, 23))


class EcoQuietDay(unittest.TestCase):
    def test_eco_silent_and_no_access_is_no_knocks(self):
        with self.assertRaises(r.NoKnocksLogged) as cm:
            _run("[knocks-relay] luke relayed nothing for 2026-11-22 — "
                 "scraping.", ACCESS_ERR)
        self.assertEqual(cm.exception.args[0], dt.date(2026, 11, 22))

    def test_not_an_eco_office_still_fails(self):
        with self.assertRaises(RuntimeError):
            _run("[knocks-relay] sabrina is not an active ECO office — "
                 "scraping.", ACCESS_ERR)

    def test_other_scrape_errors_still_fail(self):
        with self.assertRaises(TimeoutError):
            _run("[knocks-relay] luke relayed nothing for 2026-11-22 — "
                 "scraping.", TimeoutError("ownerville timed out"))


if __name__ == "__main__":
    unittest.main()
