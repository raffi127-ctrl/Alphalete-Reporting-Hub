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


# --- the OTHER road to "already had a packet" (2026-09-14) -------------------
# Blue Ink's own lookup is only half of it. Someone we sent in an EARLIER week
# is dropped from the send list before that lookup ever runs, off our own
# ledger, so nothing downstream saw them: no deeper colour, no line here. Their
# row read exactly like a row nobody had touched -- which is how Le'derius
# Arnold (sent 9/7) came to look un-sent on the 9/14 tab.

class _Person:
    """Enough of a NewStart for _handle_held: a name and a row to tint."""

    def __init__(self, name, row, email=""):
        self.name, self.row, self.email = name, row, email
        self.blueink_col = 14


def test_ledger_held_people_are_tinted_and_named():
    from automations.blueink_docs import run
    tinted = {}

    class _WS:
        title = "D2D OBCL 9.14"

    def _fake_highlight(ws, people, color=None):
        tinted["people"] = [p.name for p in people]
        tinted["color"] = color
        return len(people)

    real = run.mark.highlight
    run.mark.highlight = _fake_highlight
    try:
        carried = [(_Person("Le'derius Arnold", 50), "Sent 9/7/26"),
                   (_Person("Billy Garvin", 3), "Sent 8/31/26")]
        pairs, problems = run._handle_held(_WS(), [], {}, carried)
    finally:
        run.mark.highlight = real

    assert tinted["people"] == ["Le'derius Arnold", "Billy Garvin"]
    # The DEEPER green -- a packet from an earlier week usually means a
    # rescheduled start, and that has to be distinguishable from today's send.
    assert tinted["color"] == run.mark.CARRIED_BLUE
    assert problems == []
    body = sp.build_thread(36, [], None, pairs)
    assert "*2* not sent — already had a packet:" in body
    assert "• *Le'derius Arnold* — already sent on 9/7/26" in body
    assert "*0* failed to send" in body


def test_both_kinds_of_hold_appear_together():
    # One held by Blue Ink's history, one by our ledger: same section, one list.
    from automations.blueink_docs import run

    class _WS:
        title = "t"

    real = run.mark.highlight
    run.mark.highlight = lambda ws, people, color=None: len(people)
    try:
        hand_sent = _Person("Bailey Soda", 54, "baileysoda@gmail.com")
        pairs, problems = run._handle_held(
            _WS(), [hand_sent], {"baileysoda@gmail.com": "Sent 9/12/26"},
            [(_Person("Le'derius Arnold", 50), "Sent 9/7/26")])
    finally:
        run.mark.highlight = real
    assert problems == []
    body = sp.build_thread(36, [], None, pairs)
    assert "• *Bailey Soda* — already sent on 9/12/26" in body
    assert "• *Le'derius Arnold* — already sent on 9/7/26" in body


def test_an_ambiguous_same_name_hold_is_still_a_problem():
    # The one hold that IS a problem must not be swept into the quiet list.
    from automations.blueink_docs import run

    class _WS:
        title = "t"

    real = run.mark.highlight
    run.mark.highlight = lambda ws, people, color=None: len(people)
    try:
        pp = _Person("Ana Lopez", 7, "ana@x.com")
        pairs, problems = run._handle_held(
            _WS(), [pp], {"ana@x.com": "same name, different address"},
            [(_Person("Billy Garvin", 3), "Sent 8/31/26")])
    finally:
        run.mark.highlight = real
    assert problems == [("Ana Lopez", "same name, different address")]
    assert [n for n, _ in pairs] == ["Billy Garvin"]
