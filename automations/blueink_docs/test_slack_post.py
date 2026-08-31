"""The Slack reply is the only place a held-back person is visible.

The sheet can't show it on its own: the green tint marks what THIS report sent,
so a packet the team sent by hand leaves the row looking untouched. On
2026-08-31 that cost Megan a morning working out why Jose Laureano and Javion
Hunt were skipped -- both had packets from 8/24. Hence these tests.

The distinction that matters and is easy to break: a held person is NOT a
failure. Failures get the recruiters tagged to go send something; held people
already have their paperwork and there is nothing for anyone to do. Mixing the
two either buries a real name or sends three people chasing a non-problem.
"""
from automations.blueink_docs import slack_post as sp


def test_held_people_are_named_with_the_date():
    body = sp.build_thread(52, [], None,
                           [("Javion Hunt", "Sent 8/24/26"),
                            ("Jose Laureano", "Sent 8/24/26")])
    assert "*2* not sent — already had a packet:" in body
    # The DATE is the point: it's what tells a reader whether to chase a
    # signature or leave it alone.
    assert "• *Jose Laureano* — already sent on 8/24/26" in body
    assert "• *Javion Hunt* — already sent on 8/24/26" in body


def test_held_people_are_not_counted_as_failures():
    body = sp.build_thread(52, [], None, [("Jose Laureano", "Sent 8/24/26")])
    assert "*0* failed to send" in body
    # Nobody is asked to do anything about a person who already has docs.
    assert "sent manually" not in body
    for uid in sp.TAG_USER_IDS:
        assert uid not in body


def test_real_failures_still_tag_the_recruiters():
    body = sp.build_thread(50, [("Ada Brown", "no usable email on the sheet")],
                           None, [("Jose Laureano", "Sent 8/24/26")])
    assert "*1* failed to send" in body
    assert "these need to be sent manually" in body
    # Both sections present, and the failure is not swallowed by the held list.
    assert "• *Ada Brown* — no usable email on the sheet" in body
    assert "• *Jose Laureano* — already sent on 8/24/26" in body


def test_a_completed_packet_reads_as_completed():
    body = sp.build_thread(0, [], None, [("Jose Laureano", "Completed 8/24/26")])
    assert "already completed on 8/24/26" in body


def test_unclassifiable_verdict_passes_through_verbatim():
    """_held_phrase only rewrites "<Status> <date>". Anything else -- e.g.
    "a packet this report couldn't classify" -- must survive unmangled rather
    than be forced into a sentence that misstates what we know."""
    why = "a packet this report couldn't classify"
    assert sp._held_phrase(why) == why
    assert why in sp.build_thread(0, [], None, [("Cy Vance", why)])


def test_nothing_held_leaves_the_message_as_it_was():
    """The quiet Monday shape Megan signed off on 2026-08-24 must not grow a
    stray empty section."""
    body = sp.build_thread(52, [], None, [])
    assert body == "*52* new starts sent\n*0* failed to send"


def test_singular_plural():
    assert "*1* new start sent" in sp.build_thread(1, [], None, [])
    assert "*2* new starts sent" in sp.build_thread(2, [], None, [])
