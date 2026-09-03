"""Which boxes may send an iMessage from this job's LaunchAgent.

Not a preference — a macOS consent, granted per EXECUTABLE IDENTITY. On Lucy 1
the Allow was clicked for /bin/bash on a wrapper, which is what this agent runs
as. On Lucy 2 it was clicked for the mini_control poller (.venv/bin/python) and
never for a wrapper, which is why b2b_dispositions queues its texts to the
poller instead of sending from its scheduled job.

An unconsented send does not raise, it BLOCKS on a dialog nobody will click —
about five minutes, every tick. So this is a list you add to only after somebody
has sent once from the agent's own identity with a human at the keyboard.
"""
from automations.gap_alerts import config as C


def test_lucy_1_can_text():
    assert C.can_text("Lucy 1")


def test_lucy_2_cannot():
    """Adding it here without clicking Allow as /bin/bash on that box turns
    every B2B tick into a five-minute hang."""
    assert not C.can_text("Lucy 2")
    assert "Lucy 2" not in C.TEXTING_MACHINES


def test_an_unknown_box_is_assumed_not_to_have_consent():
    """Fail closed: a skipped route is loud and recoverable, a hung tick is
    neither."""
    assert not C.can_text("Lucy 7")
    assert not C.can_text("some-new-mini")
