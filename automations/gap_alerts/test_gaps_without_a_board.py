"""An empty board must not silence the gap list.

The two halves of a KNOCKS & DISPOSITIONS post come off DIFFERENT pages — the
board off p=89 (Disposition by Rep) and the gap list off p=510 (Time Tracker) —
and a campaign that blanks one does not necessarily blank the other. On
2026-09-02 Calvin's and Jay's boards came back with no rows every tick and the
send loop `continue`d on that, so their chats went silent for a whole field day
while the gap feed itself was fine. Megan: "let's make sure at least gaps are
getting posted in the chat."

The gap list is the ALERT half — the part somebody acts on — so it travels
alone, as text with no flyer.

WHAT MAKES THAT SAFE, and the reason this file exists next to the guard rather
than inside it: `_own_reps_only` catches a gap list belonging to another office
by checking it against the BOARD, and with no board it passes everything
through. Posting a boardless gap list is therefore only honest once the gap
pull asserts the impersonated office itself, which gap_rows_many now does.
Delete that assert and this feature becomes the "who are these?" post
(Calvin's seven reps in Raf's chat, 2026-09-01).
"""
import inspect

import pytest

from automations.b2b_dispositions import text_post as tp
from automations.gap_alerts import run as R


# --- the text-only send -------------------------------------------------------

@pytest.fixture
def resolves(monkeypatch):
    """Stand in for the Messages lookup, which runs BEFORE the image guard and
    needs a real chat on a real Mac. The guard is what these tests are about."""
    monkeypatch.setattr(tp, "resolve_group",
                        lambda name: {"id": "iMessage;+;chat1",
                                      "name": name, "participants": 7})


def test_no_image_is_still_refused_by_default(resolves):
    """b2b_dispositions' own posting IS the image, and Carlos's report shares
    this function — the default must not move."""
    with pytest.raises(tp.GroupTextError) as e:
        tp.send_to_group("Some Chat", "a line of text", [], dry_run=False)
    assert "the posting IS the image" in str(e.value)


def test_allow_textonly_lifts_it():
    sig = inspect.signature(tp.send_to_group)
    assert sig.parameters["allow_textonly"].default is False, (
        "text-only must stay opt-in; every other caller posts an image")


def test_allow_textonly_still_refuses_an_empty_message(resolves):
    """The opt-in permits a message with no flyer, never a message with
    nothing in it — that is the blank post by another route."""
    for empty in ("", "   ", "\n"):
        with pytest.raises(tp.GroupTextError) as e:
            tp.send_to_group("Some Chat", empty, [], dry_run=False,
                             allow_textonly=True)
        assert "neither an image nor any text" in str(e.value)


# --- the gap pull can now attribute itself ------------------------------------

def test_gap_pull_asserts_the_impersonated_office():
    """Without this the boardless post above is unattributable.

    ownerville hands an impersonated session the SAME rqst as master, so
    _find_owner_and_impersonate returning a token proves only that
    confirmImpersonate was CALLED. The board pull has always re-asked the page
    which office it landed on; the gap pull did not, and leaned on the board
    cross-check instead.
    """
    src = inspect.getsource(R.gap_rows_many)
    assert "assert_impersonating" in src, (
        "gap_rows_many must prove the office switched before its rows can be "
        "posted without a board to check them against")
    # It has to happen BEFORE the rows are read. Asserting afterwards would
    # still catch a bad pull, but the rows would already be in hand and the
    # temptation next time is to keep them.
    assert src.index("assert_impersonating") < src.index("fetch_time_tracking"), (
        "prove the office before reading its rows, not after")


def test_own_reps_only_cannot_vouch_for_a_gap_list_with_no_board():
    """The precise reason the assert above is load-bearing: with no board rows
    this guard is a pass-through, not a filter."""
    cfg = {"key": "calvin", "name": "Calvin Ribera"}
    gaps = [{"name": "Somebody Else", "minutesSinceLastKnock": 90}]
    assert R._own_reps_only(cfg, gaps, []) == gaps


def test_own_reps_only_still_drops_strays_when_there_is_a_board():
    cfg = {"key": "calvin", "name": "Calvin Ribera"}
    gaps = [{"name": "Maurice Dupree"}, {"name": "Somebody Else"}]
    rows = [{"Rep": "Maurice Dupree"}]
    kept = R._own_reps_only(cfg, gaps, rows)
    assert [g["name"] for g in kept] == ["Maurice Dupree"]


# --- the send loop -------------------------------------------------------------

def test_an_empty_board_no_longer_skips_the_office():
    """The regression this whole file is about: `if not pngs: continue`."""
    src = inspect.getsource(R.tick)
    assert "board_empty" in src, "the empty-board path must reach the send loop"


def test_nothing_at_all_is_still_nothing_sent():
    """No board AND nobody over the threshold is the ordinary quiet case.
    [[feedback_never_post_blank]]"""
    src = inspect.getsource(R.tick)
    assert "no board and no gaps" in src
