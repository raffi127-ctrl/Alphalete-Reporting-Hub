"""The headshot thread goes up on any day there are new starts, not Mondays.

Megan, 2026-11-24: "right now I think we only have it on Mondays. It should be
any day that there's new starts scheduled."

    python -m pytest automations/headshots/test_any_start_day.py -q
"""
import datetime as dt

import pytest

from automations.headshots import weekly_thread as W


# Noon on this week's Monday, as a Slack ts.
_THIS_WEEK = dt.datetime.combine(W.week_monday(),
                                 dt.time(12, 0)).timestamp()


class _Client:
    def __init__(self, existing=False):
        self.existing, self.posted = existing, []

    def conversations_history(self, channel, limit=200):
        if not self.existing:
            return {"messages": []}
        # THIS week's post. `find_week_anchor` only counts a marker dated on
        # or after the week's Monday, so a fixed old timestamp would be
        # invisible to it and the test would pass by posting a second thread.
        return {"messages": [{"ts": "%.1f" % _THIS_WEEK,
                              "text": ":camera_with_flash: *%s — Week of 11/23*"
                                      % W.MARKER}]}

    def chat_postMessage(self, channel, text):
        self.posted.append((channel, text))
        return {"ts": "1700000001.0"}


@pytest.fixture(autouse=True)
def _no_slack(monkeypatch):
    monkeypatch.setattr(W, "_client", lambda: _Client())


def test_the_monday_gate_is_gone():
    """A start can be any day, so the thread cannot be."""
    import inspect
    src = inspect.getsource(W.post_prompt)
    assert "Not Monday" not in src
    assert "weekday() != 0" not in src


def test_it_posts_midweek_when_somebody_is_starting(monkeypatch):
    client = _Client()
    monkeypatch.setattr(W, "_client", lambda: client)
    monkeypatch.setattr(W, "starts_this_week", lambda **k: True)
    ts = W.post_prompt(dry_run=False, channel="C1")
    assert ts and client.posted, "a Wednesday starter needs somewhere to post"


def test_a_quiet_week_posts_nothing(monkeypatch):
    """A prompt in a busy channel asking for headshots of nobody."""
    client = _Client()
    monkeypatch.setattr(W, "_client", lambda: client)
    monkeypatch.setattr(W, "starts_this_week", lambda **k: False)
    assert W.post_prompt(dry_run=False, channel="C1") is None
    assert client.posted == []


def test_force_posts_anyway(monkeypatch):
    client = _Client()
    monkeypatch.setattr(W, "_client", lambda: client)
    monkeypatch.setattr(W, "starts_this_week", lambda **k: False)
    assert W.post_prompt(dry_run=False, channel="C1", force=True)
    assert client.posted


def test_one_thread_per_week_not_one_per_day(monkeypatch):
    """The replies all belong together and the bot reads ONE thread. A thread
    per day would split a week's headshots across five places."""
    client = _Client(existing=True)
    monkeypatch.setattr(W, "_client", lambda: client)
    monkeypatch.setattr(W, "starts_this_week", lambda **k: True)
    ts = W.post_prompt(dry_run=False, channel="C1")
    assert ts == "%.1f" % _THIS_WEEK, "it found the one already up"
    assert client.posted == []


def test_an_unreadable_board_still_posts(monkeypatch):
    """"I could not look" must never read as "nobody is starting": a missing
    thread costs somebody their headshot on the one morning they are there."""
    from automations.icd_onboarding import fillers as F
    monkeypatch.setattr(F, "rows_anywhere",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    assert W.starts_this_week(monday=dt.date(2026, 11, 23)) is True


def test_somebody_marked_off_does_not_count(monkeypatch):
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    rows = [{"Name": "Gone", "Last Name": "Away",
             B.TERMINATED_AT: "11/23/2026"}]
    monkeypatch.setattr(F, "rows_anywhere", lambda *a, **k: rows)
    assert W.starts_this_week(monday=dt.date(2026, 11, 23)) is False


def test_each_office_is_asked_about_its_OWN_board():
    """Asking Raf's board about Omar's week is how a thread goes up in the
    wrong place, or not at all."""
    import inspect
    src = inspect.getsource(W.main)
    assert "o.key" in src and "office_key=key" in src


def test_the_agent_fires_every_day():
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[2] / "deploy"
            / "com.alphalete.headshots-monday.plist").read_text()
    assert "<key>Weekday</key>" not in text, \
        "a Weekday key is the Monday-only gate this change removed"
