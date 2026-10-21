"""What the office switcher is allowed to call an ACCESS DENIAL (2026-09-01).

`_switch_office` returning False is not a small thing: `fetch_one` /
`fetch_one_daily` turn it into `{}`, daily_focus files that under `denied` —
a bucket it deliberately NEVER retries — and the morning post in
#claudecorrections-and-requests reads

    AppStream refused these — needs access (3): …

which sends somebody off to request access from eStream / Smart Circle.

The 2026-08-29 fix (300475c4) made the dropdown WAIT instead of snapshotting it
after 800ms, which killed the common race. What it left: when the dropdown never
answers at all, the code still returns False — and "this account can't reach the
office" is not the same fact as "nothing rendered in 16s". On 2026-09-01 that
posted Frank Matos, Jose Velasquez and Joseph Delgado as needing access; all
three had pulled clean the day before and carry a full previous week on Colten
Wright's tab.

So the rule pinned here: under `confirm_denial=True` a denial must be BACKED —
a dropdown that actually answered without the office, or the switcher's own
preloaded office list saying it isn't there. Anything else raises, which the
callers already read as transient and retry. The plain True/False contract the
single-office callers (resume_pushing, oat_processing, funnel_board,
recruiter_retention) were written against is unchanged.

Run:  python -m automations.recruiting_report.test_fetch_office_switch
      (or via pytest)

3.9-safe — the mini runs Python 3.9.
"""
from __future__ import annotations

import sys

from patchright.sync_api import TimeoutError as PWTimeout

from automations.recruiting_report import fetch_office as fo

MENU_SELECTOR = ".ui-autocomplete li, .ui-menu li"


class _Item:
    def __init__(self, text, clicked):
        self._text = text
        self._clicked = clicked

    def inner_text(self):
        return self._text

    def click(self, **kw):
        # A click that waits for its own navigation times out on AppStream's
        # slow office reload (2026-10-21) — the fake refuses one.
        if not kw.get("no_wait_after"):
            raise PWTimeout("click waited for navigation inside its own timeout")
        if getattr(self, "stale", False):
            raise PWTimeout("Locator.click: Timeout 8000ms exceeded.")
        self._clicked.append(self._text)

    def wait_for(self, **kw):
        return None


class _Box:
    """Stands in for a locator — only the calls _switch_office makes."""

    def __init__(self, items=None):
        self._items = items or []

    def count(self):
        return 1

    def click(self, **kw):
        return None

    def fill(self, *a, **kw):
        return None

    def type(self, *a, **kw):
        return None

    def all(self):
        return list(self._items)


class _Nav:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakePage:
    """menu: the dropdown rows, or None when the switcher never answers.
    source: the switcher's preloaded office-id list, or None when the
    autocomplete is server-side and there is no local list to ask."""

    def __init__(self, menu=None, source=None):
        self.menu = menu
        self.source = source
        self.clicked = []
        self.keyboard = self
        self.mouse = self

    # _dismiss_overlays
    def press(self, *a, **kw):
        return None

    def move(self, *a, **kw):
        return None

    def locator(self, selector, has_text=None):
        if selector == MENU_SELECTOR:
            items = [_Item(t, self.clicked) for t in (self.menu or [])]
            for it in items:
                it.stale = getattr(self, "stale_first", False)
            return _Box(items)
        if has_text is not None:              # the fresh :visible retry row
            hit = [t for t in (self.menu or []) if has_text in t]
            row = _Item(hit[0] if hit else "", self.clicked)
            row.stale = getattr(self, "stale_always", False)
            return _FirstOf(row)
        return _Box()

    def wait_for_timeout(self, *a, **kw):
        return None

    def evaluate(self, js):
        return self.source

    def expect_navigation(self, **kw):
        return _Nav()


class _FirstOf:
    def __init__(self, row):
        self.first = row


def test_a_stale_row_is_retyped_not_waited_on():
    """2026-10-20: the dropdown re-rendered between find and click; click()
    waited 30s per office and daily_focus ran out its 45 minutes. The row is
    retyped and the FRESH row for the same office id is clicked."""
    page = _FakePage(menu=["22434\nJose Velasquez\nLegacy Shore"])
    page.stale_first = True
    assert _call(page, confirm_denial=True) is True
    assert page.clicked == ["22434\nJose Velasquez\nLegacy Shore"]


def test_a_row_that_never_takes_a_click_is_transient():
    page = _FakePage(menu=["22434\nJose Velasquez\nLegacy Shore"])
    page.stale_first = True
    page.stale_always = True
    try:
        _call(page, confirm_denial=True)
    except PWTimeout as e:
        assert "would not take a click" in str(e)
    else:
        raise AssertionError("a stale row must raise (retryable)")


def test_the_click_leaves_the_reload_wait_to_expect_navigation():
    """2026-10-21: click(timeout=8000) also waited for the office reload it
    started — "click action done, waiting for scheduled navigations" then
    Timeout 8000ms, on clicks that worked. Both the first click and the
    retyped one must pass no_wait_after=True."""
    page = _FakePage(menu=["22434\nJose Velasquez\nLegacy Shore"])
    assert _call(page, confirm_denial=True) is True
    page = _FakePage(menu=["22434\nJose Velasquez\nLegacy Shore"])
    page.stale_first = True
    assert _call(page, confirm_denial=True) is True


def _call(page, office_id="22434", **kw):
    return fo._switch_office(page, office_id, "Jose Velasquez", **kw)


def test_menu_has_the_office_switches():
    page = _FakePage(menu=["22434\nJose Velasquez\nLegacy Shore Marketing, Inc."])
    assert _call(page, confirm_denial=True) is True
    assert page.clicked, "the matching item must actually be clicked"


def test_silent_dropdown_with_the_office_in_the_account_is_not_a_denial():
    """The 2026-09-01 case: the office IS on the account, the dropdown just
    never answered. Must raise (retryable), never post 'needs access'."""
    page = _FakePage(menu=None, source=["23221", "22434", "20788", "22477"])
    try:
        _call(page, confirm_denial=True)
    except PWTimeout as e:
        assert "access denial" in str(e)
    else:
        raise AssertionError("a silent dropdown was reported as an access denial")


def test_silent_dropdown_and_account_lacks_the_office_is_a_denial():
    page = _FakePage(menu=None, source=["23221", "20788", "22477"])
    assert _call(page, confirm_denial=True) is False


def test_answered_dropdown_without_the_office_is_a_denial():
    """A real answer that holds no row for this id is a real access gap —
    no need to ask anything else."""
    page = _FakePage(menu=["22477\nGeorge Delgado\nSkyline Elite, Inc."], source=None)
    assert _call(page, confirm_denial=True) is False


def test_silent_dropdown_and_nothing_to_ask_is_not_a_denial():
    page = _FakePage(menu=None, source=None)
    try:
        _call(page, confirm_denial=True)
    except PWTimeout:
        pass
    else:
        raise AssertionError("an unknowable result was reported as a denial")


def test_plain_callers_keep_the_true_false_contract():
    """resume_pushing / oat_processing / funnel_board / recruiter_retention drive
    one fixed office and branch on False — they must not start seeing raises."""
    page = _FakePage(menu=None, source=None)
    assert _call(page) is False


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("  ok   %s" % t.__name__)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("  FAIL %s: %s: %s" % (t.__name__, type(e).__name__, e))
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
