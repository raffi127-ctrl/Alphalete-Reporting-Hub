"""The note that says we have just re-sent their documents.

Megan, 2026-11-23: "on those 2 reminder emails we're sending -- if they have
NOT taken it yet -- we need to resend it and say that we've resent it in the
email."

THE RESEND ITSELF WAS ALREADY BUILT (chase.py): the day before a start and
the morning of it, anybody still unsigned gets Blue Ink's invitation sent
again, off the signer's own packet. It is the same action as the Resend
behind the "..." on a signer in the Blue Ink app.

WHAT WAS MISSING IS THE SENTENCE. Blue Ink's remind takes NO MESSAGE -- the
endpoint was asked on 2026-11-23 and its PUT fields are packet attributes
(key, the auth flags, status) and nothing else. So the resend fires Blue
Ink's own stock invitation, which arrives looking exactly like the first one,
with nothing to say it is a reminder or that anybody did anything. A person
who has been meaning to get to it reads that as a duplicate and ignores it.

So the sentence comes from US, right after the resend lands.

ONLY AFTER A RESEND THAT WORKED. If the remind failed, nothing is sent: an
email saying "we have just re-sent it" when nothing was re-sent is worse than
silence, because they go looking for a message that is not there and conclude
the whole thing is broken.

FROM RECEPTION, which is the address they already reply to, and the one a
reply about paperwork should land in. Same mailbox and token as the Monday
Slack/Skool note (slack_skool_email.gmail_reception).
"""
from __future__ import annotations

from email.message import EmailMessage
from typing import Optional

SUBJECT = {
    "day_before": "Your start paperwork - we've just re-sent it",
    "morning_of": "Your start paperwork - last call before today",
}

# NO LINK OF OUR OWN. The only working link is the one inside Blue Ink's
# email, tied to their packet -- anything we pasted would either be that same
# link copied (and wrong the moment a packet is re-issued) or a sign-in page
# they do not have an account for.
_BODY = {
    "day_before": (
        "Hi {first},\n\n"
        "You start tomorrow, and our records show your onboarding documents "
        "are not signed yet.\n\n"
        "We've just re-sent them, so there's a fresh email from BlueInk in "
        "your inbox now. Open that one and sign the forms before tomorrow -- "
        "it takes a few minutes, and we can't get you set up without them.\n\n"
        "If you can't find it, check your spam folder, then reply to this "
        "email and we'll sort it out.\n\n"
        "See you tomorrow,\n"
        "Alphalete Marketing"
    ),
    "morning_of": (
        "Hi {first},\n\n"
        "You start today and your onboarding documents still aren't signed.\n\n"
        "We've just re-sent them -- look for the email from BlueInk that has "
        "arrived in the last few minutes and sign the forms before you come "
        "in. It only takes a few minutes.\n\n"
        "If you can't find it, check your spam folder, then reply to this "
        "email and we'll sort it out.\n\n"
        "See you today,\n"
        "Alphalete Marketing"
    ),
}


def first_name(name: str) -> str:
    """What to call them. The whole name is used when it is one word, and
    nothing becomes "there" rather than an empty greeting."""
    parts = [p for p in str(name or "").replace(",", " ").split() if p]
    return parts[0] if parts else "there"


def kind_key(kind: str) -> str:
    """One reminder kind, however the caller spells it.

    `chase.py` names the two chases "day-before" and "morning-of"; the
    templates here are keyed "day_before" and "morning_of". Nothing reconciled
    them, and `send` turns an unknown kind into a WORD FOR THE LOG rather than
    an error -- so the chase printed "reminded ... + unknown reminder kind:
    'morning-of'" and counted the person as done. The email half could never
    have gone out, for either chase, since the day it was written
    (found by a dry run against the live app, 2026-11-24).

    Normalised rather than renamed: the ledger's own note carries the hyphen
    spelling, and `already_chased` matches on that text, so changing it would
    make everybody chased before today eligible for a second reminder.
    """
    return str(kind or "").strip().lower().replace("-", "_")


def build(name: str, email: str, kind: str) -> EmailMessage:
    kind = kind_key(kind)
    if kind not in _BODY:
        raise ValueError("unknown reminder kind: %r" % kind)
    msg = EmailMessage()
    msg["To"] = email
    msg["Subject"] = SUBJECT[kind]
    msg.set_content(_BODY[kind].format(first=first_name(name)))
    return msg


def send(name: str, email: str, kind: str, *, really: bool,
         log=print) -> Optional[str]:
    """Send it (or say what would go). Returns a word for the chase's log.

    NEVER RAISES. The resend has already happened by the time this runs, and
    a mail failure must not make the chase report the resend as failed --
    that is how somebody re-runs it and a person gets two of everything.
    """
    if not str(email or "").strip():
        return "no email address"
    try:
        msg = build(name, email, kind)
    except ValueError as exc:
        return str(exc)
    if not really:
        return "would email"
    try:
        from automations.slack_skool_email import gmail_reception as GR
        GR.assert_right_mailbox()
        GR.send(msg)
        return "emailed"
    except Exception as exc:                        # noqa: BLE001
        log("      could not email %s: %s" % (email, type(exc).__name__))
        return "email failed (%s)" % type(exc).__name__
