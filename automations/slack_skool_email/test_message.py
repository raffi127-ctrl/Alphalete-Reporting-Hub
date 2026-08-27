"""Tests for the Slack/Skool email. Nothing here touches Gmail, the Sheet or
Slack -- every failure mode below is one that would otherwise be discovered by
thirty new starts reading a broken email.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.slack_skool_email import config, message, run

SLACK = "https://join.slack.com/t/ao-pbns/shared_invite/zt-testtest-abc"
SKOOL = "https://www.skool.com/alphalete-marketing-8578/about?ref=deadbeef"


# --- the copy ---------------------------------------------------------------

def test_text_part_shows_the_url_and_html_puts_it_on_the_word():
    """The two parts must agree: same destinations, different presentation."""
    text = message.render_text(slack_link=SLACK, skool_link=SKOOL)
    html = message.render_html(slack_link=SLACK, skool_link=SKOOL)

    # plain text keeps the URL visible -- a stranger can see where it goes
    assert "Slack <{}>".format(SLACK) in text
    assert "Skool <{}>".format(SKOOL) in text
    assert "[[" not in text

    # HTML puts the link on the word
    assert '<a href="{}">Slack</a>'.format(SLACK) in html
    assert '<a href="{}">Skool</a>'.format(SKOOL) in html
    assert "[[" not in html


def test_html_escapes_the_copy_rather_than_letting_it_inject():
    html = message.render_html(slack_link=SLACK, skool_link=SKOOL)
    # the apostrophe in "We're" must be escaped, not raw
    assert "We&#x27;re" in html or "We&#39;re" in html
    assert "<script" not in html.lower()


def test_no_images_and_no_attachments():
    """Deliberate: a 52-recipient BCC from a personal Gmail is already the
    shape filters watch, and an attachment to strangers reads as phishing."""
    msg = message.build(["a@x.com"], slack_link=SLACK, skool_link=SKOOL)
    types = [p.get_content_type() for p in msg.walk()]
    assert types == ["multipart/alternative", "text/plain", "text/html"]
    assert not any(t.startswith("image/") for t in types)


def test_telemapper_is_named_the_way_the_store_names_it():
    """The store lists "TeleMapper 3" by KLE. It is the one app with no join
    link, so a wrong name is the only thing standing between a new start and
    the right download."""
    text = message.render_text(slack_link=SLACK, skool_link=SKOOL)
    assert "TeleMapper 3 by KLE" in text
    assert "Telemapper 3.0" not in text


def test_body_refuses_when_a_link_marker_was_deleted(monkeypatch):
    """Megan edits the copy and drops a marker: the link would vanish silently
    and the email would still look sent."""
    monkeypatch.setattr(config, "BODY", "Hey! join [[Skool->skool]]")
    with pytest.raises(message.CopyError):
        message.render_text(slack_link=SLACK, skool_link=SKOOL)
    with pytest.raises(message.CopyError):
        message.render_html(slack_link=SLACK, skool_link=SKOOL)


def test_body_refuses_an_empty_link(monkeypatch):
    monkeypatch.setattr(config, "_links", lambda: {})
    with pytest.raises(message.CopyError):
        message.render_text(slack_link="", skool_link=SKOOL)


def test_body_says_w4_not_w2():
    """The one substantive error in the hand-sent version. A W-2 is what the
    company sends the employee in January; a new hire fills out a W-4."""
    out = message.render_body(slack_link=SLACK, skool_link=SKOOL)
    assert "W-4" in out
    assert "W2" not in out and "W-2" not in out


# --- the envelope -----------------------------------------------------------

def test_everyone_is_bcc_and_nobody_is_to():
    """Recipients must not see each other's addresses."""
    msg = message.build(["a@x.com", "b@y.com"], slack_link=SLACK,
                        skool_link=SKOOL)
    assert msg["To"] is None
    assert "a@x.com" in msg["Bcc"] and "b@y.com" in msg["Bcc"]
    assert config.FROM_ACCOUNT in msg["From"]


def test_refuses_to_build_an_empty_send():
    with pytest.raises(message.CopyError):
        message.build([], slack_link=SLACK, skool_link=SKOOL)


# --- who gets it ------------------------------------------------------------

class _P:
    def __init__(self, name, email, eligible=True):
        self.name, self.email, self.eligible = name, email, eligible


def test_recipients_skip_the_ineligible_and_dedupe():
    """Someone on BOTH of Monday's charts must not get two copies."""
    people = [
        _P("Ana", "ana@x.com"),
        _P("Ben", "ben@x.com", eligible=False),
        _P("Ana", "ANA@x.com"),          # same person, second chart
        _P("Cal", ""),                   # no address on the sheet
    ]
    assert run._recipients(people) == ["ana@x.com"]


# --- the links --------------------------------------------------------------

def test_link_problems_flags_a_missing_link(monkeypatch):
    monkeypatch.setattr(config, "_links", lambda: {"skool_link": SKOOL})
    monkeypatch.delenv("SLACK_INVITE_LINK", raising=False)
    problems = config.link_problems()
    assert any("Slack invite link" in p for p in problems)


def test_link_problems_flags_a_stale_slack_link(monkeypatch):
    old = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    monkeypatch.setattr(config, "_links", lambda: {
        "slack_invite_link": SLACK, "skool_link": SKOOL,
        "slack_link_updated": old})
    assert any("days ago" in p for p in config.link_problems())


def test_a_fresh_slack_link_raises_nothing(monkeypatch):
    fresh = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    monkeypatch.setattr(config, "_links", lambda: {
        "slack_invite_link": SLACK, "skool_link": SKOOL,
        "slack_link_updated": fresh})
    assert config.link_problems() == []


def test_an_undated_slack_link_is_flagged(monkeypatch):
    """No paste date means we cannot tell how close to Slack's 30-day ceiling
    the link is. Silence there would be a dead link discovered by a new start.
    There is no never-expires opt-out on purpose: Slack does not offer one."""
    monkeypatch.setattr(config, "_links", lambda: {
        "slack_invite_link": SLACK, "skool_link": SKOOL})
    assert any("how close it is to expiring" in p
               for p in config.link_problems())


def test_links_that_are_not_the_right_service_are_caught(monkeypatch):
    """Paste the Skool link into the Slack slot and it should not send."""
    fresh = dt.date.today().isoformat()
    monkeypatch.setattr(config, "_links", lambda: {
        "slack_invite_link": SKOOL, "skool_link": SKOOL,
        "slack_link_updated": fresh})
    assert any("join.slack.com" in p for p in config.link_problems())


# --- the re-send guard ------------------------------------------------------

def test_the_resend_guard_still_matches_the_subject():
    """The guard searches Sent mail for SUBJECT_SEARCH. If someone rewords the
    subject and forgets this, the search matches nothing, the guard passes, and
    the whole cohort gets a second copy."""
    assert config.SUBJECT_SEARCH in config.SUBJECT
    # punctuation-free: Gmail's search treats it unevenly
    assert config.SUBJECT_SEARCH.replace(" ", "").isalnum()


def test_the_subject_names_the_company():
    """It arrives from an address they have never seen, with no visible To:
    line. The company name is the trust signal."""
    assert "Alphalete" in config.SUBJECT
    assert config.SUBJECT == config.SUBJECT.strip()
    assert "!" not in config.SUBJECT and config.SUBJECT != config.SUBJECT.upper()


# --- the wrong-week gate ----------------------------------------------------

def test_refuses_a_tab_from_last_week():
    """The Monday nobody built the new tab. "Newest" is then LAST week's, and
    52 people who started a week ago get told orientation is today."""
    monday = dt.date(2026, 8, 31)
    msg = run._wrong_week("D2D OBCL 8.24", today=monday)
    assert msg and "Refusing to send" in msg
    assert "--tab" in msg          # says how to override on purpose


def test_accepts_this_weeks_tab():
    monday = dt.date(2026, 8, 31)
    assert run._wrong_week("D2D OBCL 8.31", today=monday) is None


def test_refuses_a_tab_with_no_readable_date():
    assert run._wrong_week("D2D OBCL", today=dt.date(2026, 8, 31))


def test_an_explicitly_named_tab_is_allowed_through():
    """--tab is a person being deliberate; the gate warns but doesn't block."""
    assert run._wrong_week("D2D OBCL 8.24", explicit=True,
                           today=dt.date(2026, 8, 31)) is None


# --- Gmail scopes -----------------------------------------------------------

def test_the_token_asks_for_enough_to_run_the_resend_guard():
    """gmail.compose alone can send but CANNOT search Sent mail, so the guard
    403s and takes the whole run down with it (2026-08-26). If someone trims
    the scopes back to the "minimal" one, this fails instead of Monday."""
    from automations.slack_skool_email import gmail_reception as gm
    assert any(s.endswith("/gmail.compose") for s in gm.SCOPES)
    assert any(s.endswith("/gmail.readonly") for s in gm.SCOPES)


def test_a_broken_guard_is_a_refusal_not_a_green_light():
    """GuardUnavailable must be its own type: "I couldn't check" is not the
    same answer as "it hasn't been sent"."""
    from automations.slack_skool_email import gmail_reception as gm
    assert issubclass(gm.GuardUnavailable, Exception)
