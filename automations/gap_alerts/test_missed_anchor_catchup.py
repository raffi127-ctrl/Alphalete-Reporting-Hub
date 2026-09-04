"""A lost tick must not cost a whole cadence period.

`_dest_due` used to be a pure clock test — `(anchor - offset) % cadence == 0` —
with no memory of what had actually been sent. On the anchor minute: due. One
minute later: not due, whether or not the anchor tick delivered anything. And a
tick has three ordinary ways to be lost: the machine-wide ownerville lock (some
other run held it past the 120s budget), the pid lock (the previous pass
overran), or a pull failure.

2026-09-03 is the shape of it. Raf's board went out at 8:02 PM; the 8:15 tick
logged `SKIPPED this tick — another run has held the ownerville session`; 8:20
and 8:21 then logged "nothing due", because they were not anchors. His next
possible board was 8:30 — half an hour of silence on a report that says every
fifteen minutes, from ONE missed tick, with nothing anywhere calling it a
failure.

Comparing anchors keeps the cadence exact and adds recovery: one board per
anchor, never two, and the next wake after a lost tick picks up the anchor it
missed.
"""
import datetime as dt

from automations.gap_alerts import run as R
from automations.gap_alerts import config as C


CHAT = {"kind": "imessage", "name": "Alphalete Partners", "cadence_min": 15}
HOURLY = {"kind": "slack", "channel_id": "C09JG28CD27", "cadence_min": 60}
RAF = {"key": "rafael", "name": "Rafael Hidalgo"}


def _at(h, m):
    return dt.datetime(2026, 9, 3, h, m)


def test_anchor_is_the_most_recent_one_not_the_clock():
    assert R._dest_anchor(CHAT, RAF, _at(20, 15)) == "2026-09-03T20:15"
    # 8:20 and 8:21 are not anchors; both still belong to the 8:15 one.
    assert R._dest_anchor(CHAT, RAF, _at(20, 20)) == "2026-09-03T20:15"
    assert R._dest_anchor(CHAT, RAF, _at(20, 21)) == "2026-09-03T20:15"
    assert R._dest_anchor(CHAT, RAF, _at(20, 30)) == "2026-09-03T20:30"


def test_hourly_and_quarter_hourly_keep_their_own_anchors():
    assert R._dest_anchor(HOURLY, RAF, _at(20, 45)) == "2026-09-03T20:00"
    assert R._dest_anchor(CHAT, RAF, _at(20, 45)) == "2026-09-03T20:45"


def test_a_missed_anchor_is_picked_up_by_the_next_wake(monkeypatch):
    """THE REGRESSION. Sent for 8:00, the 8:15 tick was lost — 8:20 must be
    due, not wait until 8:30."""
    monkeypatch.setattr(R, "_state",
                        lambda: {"_last_anchor":
                                 {"rafael|imessage:Alphalete Partners":
                                  "2026-09-03T20:00"}})
    assert R._dest_due(CHAT, _at(20, 20), cfg=RAF)
    assert R._dest_due(CHAT, _at(20, 21), cfg=RAF)


def test_it_does_not_send_twice_for_one_anchor(monkeypatch):
    """The other half: the :01 catch-up wake exists because launchd can skip a
    minute, and it must find the :00 run's work already done."""
    monkeypatch.setattr(R, "_state",
                        lambda: {"_last_anchor":
                                 {"rafael|imessage:Alphalete Partners":
                                  "2026-09-03T20:15"}})
    assert not R._dest_due(CHAT, _at(20, 15), cfg=RAF)
    assert not R._dest_due(CHAT, _at(20, 16), cfg=RAF)
    assert not R._dest_due(CHAT, _at(20, 20), cfg=RAF)
    # ...and the next anchor is due again.
    assert R._dest_due(CHAT, _at(20, 30), cfg=RAF)


def test_cadence_is_still_exact(monkeypatch):
    """An hourly destination does not become quarter-hourly just because the
    office's chat is."""
    monkeypatch.setattr(R, "_state",
                        lambda: {"_last_anchor":
                                 {"rafael|slack:C09JG28CD27":
                                  "2026-09-03T20:00"}})
    for m in (15, 20, 30, 45, 59):
        assert not R._dest_due(HOURLY, _at(20, m), cfg=RAF)
    assert R._dest_due(HOURLY, _at(21, 0), cfg=RAF)


def test_fixed_slots_are_never_caught_up_late():
    """A board stamped "First Knocks 2:00 PM" arriving at 3:10 is not the
    thing that was asked for — slots are moments, not intervals."""
    slot_dest = {"kind": "slack", "channel_id": "C1",
                 "cadence_min": C.SLOT_CADENCE, "slots": ["14:00"]}
    assert R._dest_anchor(slot_dest, RAF, _at(15, 10)) is None
    assert not R._dest_due(slot_dest, _at(15, 10), cfg=RAF)
    assert R._dest_due(slot_dest, _at(14, 0), cfg=RAF)


def test_a_failed_send_leaves_the_board_still_owed(tmp_path, monkeypatch):
    """Stamps are written only for destinations a route actually took — the
    same rule _mark_sent follows. Otherwise a failed tick would convince the
    next wake the board had gone out."""
    monkeypatch.setattr(C, "STATE_PATH", tmp_path / "state.json")
    R._mark_dest_anchors(RAF, [], _at(20, 15))
    assert R._last_dest_anchor(RAF, CHAT) is None
    R._mark_dest_anchors(RAF, [CHAT], _at(20, 15))
    assert R._last_dest_anchor(RAF, CHAT) == "2026-09-03T20:15"
