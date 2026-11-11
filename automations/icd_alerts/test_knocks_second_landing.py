"""The second landing on Disposition by Rep gets retries too.

On the new OwnerVille the knocks read lands on the page, chooses the client
in the page's own switcher, and lands again. That second landing had one 25s
try; a slow office computer lost the whole read to it (Colten, 2026-11-11:
126 reads in six days).

    python -m unittest automations.icd_alerts.test_knocks_second_landing
"""
import inspect
import unittest

from automations.icd_alerts import ov_read
from automations.shared import ownerville_knocks as K


class _Locator:
    def select_option(self, *_a, **_k):
        return None


class _Page:
    """Times out on the first `fail` loads, then loads."""

    def __init__(self, fail):
        self.fail = fail
        self.loads = 0

    def goto(self, *_a, **_k):
        self.loads += 1
        if self.loads <= self.fail:
            raise TimeoutError("Page.goto: Timeout 25000ms exceeded.")

    def wait_for_selector(self, *_a, **_k):
        return None

    def locator(self, *_a, **_k):
        return _Locator()

    def wait_for_load_state(self, *_a, **_k):
        return None


class SecondLandingTests(unittest.TestCase):
    def test_a_slow_load_is_tried_again_by_default(self):
        page = _Page(fail=2)
        K.navigate(page, "RQST", "11/11/2026", log=lambda m: None)
        self.assertEqual(page.loads, 3)

    def test_one_try_gives_up_on_the_first_slow_load(self):
        # What the second landing used to ask for.
        page = _Page(fail=1)
        with self.assertRaises(TimeoutError):
            K.navigate(page, "RQST", "11/11/2026", attempts=1, log=lambda m: None)

    def test_the_knocks_read_never_asks_for_a_single_try(self):
        src = inspect.getsource(ov_read.read_knocks)
        self.assertNotIn("attempts=1", src)


if __name__ == "__main__":
    unittest.main()
