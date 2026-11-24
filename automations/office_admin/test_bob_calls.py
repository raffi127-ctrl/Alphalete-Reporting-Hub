"""The "calls are done" press, and the gate it opens.

Megan, 2026-11-24: "the daily update should be sent out every day, but it
can't be sent out until the BOB calls are done."

    python -m pytest automations/office_admin/test_bob_calls.py -q
"""
import datetime as dt

import pytest

from automations.office_admin import bob_calls as BOB

DAY = dt.date(2026, 11, 24)


class _WS:
    def __init__(self, rows=()):
        self.grid = [list(BOB.HEADERS)] + [list(r) for r in rows]
        self.appended = []

    def get_all_values(self):
        return self.grid

    def append_row(self, row, **kw):
        self.appended.append(row)
        self.grid.append(list(row))


@pytest.fixture(autouse=True)
def _own_tab(monkeypatch):
    ws = _WS()
    monkeypatch.setattr(BOB, "_tab", lambda sheet_id="": ws)
    return ws


def test_nothing_pressed_means_not_done():
    assert BOB.done("raf", DAY) is False


def test_a_press_is_remembered_for_that_day(_own_tab):
    assert BOB.mark("raf", by="Alisson", day=DAY) is True
    assert BOB.done("raf", DAY) is True


def test_a_press_is_only_for_its_own_day(_own_tab):
    BOB.mark("raf", day=DAY)
    assert BOB.done("raf", DAY + dt.timedelta(days=1)) is False
    assert BOB.done("raf", DAY - dt.timedelta(days=1)) is False


def test_a_press_is_only_for_its_own_office(_own_tab):
    BOB.mark("raf", day=DAY)
    assert BOB.done("omar", DAY) is False


def test_pressing_twice_writes_one_row(_own_tab):
    """Somebody pressing again because nothing visibly happened must not be a
    second row and not a second anything."""
    assert BOB.mark("raf", day=DAY) is True
    assert BOB.mark("raf", day=DAY) is False
    assert len(_own_tab.appended) == 1


def test_the_key_is_not_case_sensitive(_own_tab):
    BOB.mark("RAF", day=DAY)
    assert BOB.done("raf", DAY) is True


def test_an_unreadable_sheet_reads_as_NOT_done(monkeypatch):
    """The gate fails CLOSED. An update that posts because the sheet was
    unreachable is the exact thing the gate exists to stop, and a held update
    is visible the moment somebody looks for it."""
    def boom(sheet_id=""):
        raise OSError("no sheet")
    monkeypatch.setattr(BOB, "_tab", boom)
    assert BOB.done("raf", DAY) is False


def test_waiting_on_names_everybody_who_has_not_pressed(_own_tab):
    BOB.mark("raf", day=DAY)
    assert BOB.waiting_on(["raf", "omar", "cyrus"], DAY) == ["omar", "cyrus"]


def test_an_unreadable_sheet_owes_everybody(monkeypatch):
    def boom(sheet_id=""):
        raise OSError("no sheet")
    monkeypatch.setattr(BOB, "_tab", boom)
    assert BOB.waiting_on(["raf", "omar"], DAY) == ["raf", "omar"]


def test_no_office_key_is_never_done():
    assert BOB.done("", DAY) is False
    with pytest.raises(ValueError):
        BOB.mark("")


# ------------------------------------------------- what the gate actually does

def test_the_press_does_not_post_anything():
    """It gates; it does not send. A press that posted directly would mean a
    mis-press sends an office its day's record with nothing in it."""
    import inspect
    src = inspect.getsource(BOB)
    for word in ("chat_postMessage", "post_reply", "slack_metrics_post"):
        assert word not in src, word


def test_the_daily_update_holds_its_POST_and_nothing_else():
    """The sheet and the picture are still made -- what is held is the post,
    because the thing that would be wrong is an office reading its day's
    record with the answers missing."""
    import inspect
    from automations.raf_daily_update import run as DU
    src = inspect.getsource(DU.main)
    at = src.index("bob_calls")
    held = src[at:at + 600]
    assert "args.post = False" in held, "it holds the post"
    assert "return" not in held.split("args.post = False")[0], \
        "and does not bail out of the run"


def test_there_is_a_way_past_the_gate_and_it_says_so():
    """A day somebody pressed nothing and the office wants it anyway."""
    import inspect
    from automations.raf_daily_update import run as DU
    src = inspect.getsource(DU.main)
    assert "force_post" in src
    assert "--force-post posts anyway" in src
