"""Tell Megan an office has asked to join.

Megan 2026-09-13: "they should be 'signing' up first and then I'm alerted."
This is the alert. It goes to the corrections channel -- the standing place
for requests -- and carries the one command that turns the request into a
real office.

BEST EFFORT BY DESIGN, like tracker_onboarding and disposition_signup before
it: the sign-up is already saved by the time this runs, so a missing Slack
token or a failed post must never look like a failed submission to the person
who filled the form.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from automations.icd_signup.schema import IcdSignup, tz_label

# The one-click approve, straight from the ping. Gated by the access code on
# the other side -- this is the switch that puts an office's numbers in front
# of their whole team.
APPROVE_URL = "https://lucyeco.streamlit.app/join-lucy-eco?approve=%s"

CADENCE_WORDS = {15: "every 15 minutes", 30: "every 30 minutes",
                 60: "once an hour", 0: "at 2:00, 5:15 and 9:00",
                 -1: "not wanted"}


def lines(rec: IcdSignup, link: str = "") -> Tuple[str, List[str]]:
    """(headline, thread detail). SHORT.

    It used to carry everything the form collected -- hours, timezone,
    computer, contact, their OwnerVille name, their setup link, the terminal
    fallback and three italic paragraphs of explanation. Megan, looking at the
    first real one: "this is way too much info."

    It is a notification, not a record. The record is the sheet. What somebody
    reading this actually has to do is exactly two things: put Lucy in the
    rooms, and click approve. Everything else was pushing those two off the
    screen.
    """
    head = "*New sign-up — %s* (`%s`)" % (rec.owner, rec.office_key)

    rooms = []
    for c in list(rec.alert_channels) + [d.get("channel") for d
                                         in rec.knocks_destinations]:
        if c and c not in rooms:
            rooms.append(c)

    detail = ["*Add Lucy to:*"]
    detail += ["   • %s" % c for c in rooms] or ["   _no channel named yet_"]

    # A GROUP TEXT IS THEIRS TO ADD LUCY TO, not ours -- we cannot put
    # ourselves into somebody else's chat. The form asks them to, so this is
    # a line to CHECK, not to do. It earns its space because a chat name that
    # does not match sends to nobody and reports success, so an unchecked one
    # is silence on both ends.
    from automations.icd_signup.schema import group_name
    texts = [group_name(t) for t in rec.text_groups if group_name(t)]
    if texts:
        detail += ["", "*Check Lucy is in their group text:*"]
        detail += ["   • %s" % t for t in texts]

    detail += ["", "*Approve:*  %s" % (APPROVE_URL % rec.office_key)]
    return head, detail


def notify(rec: IcdSignup, *, send: bool = False, link: str = "",
           log=print) -> "Tuple[bool, str]":
    """(posted, why_not). The reason is RETURNED, not just logged.

    On Streamlit Cloud a log line goes nowhere anybody will read, so a failed
    ping used to be pure silence: the sign-up sat on the tab and nobody was
    told it existed. Megan's own test on 2026-09-13 landed perfectly and
    pinged nothing, and the only way to find out why was to go looking.
    """
    head, detail = lines(rec, link)
    log(head)
    for d in detail:
        log("   %s" % d)
    if not send:
        return False, "not sending"
    try:
        from automations.icd_alerts import offices as O, post as P
        ts = P._slack(O.OPS_CHANNEL, head)
        P._slack(O.OPS_CHANNEL, "\n".join(detail), thread_ts=ts)
        return True, ""
    except Exception as e:  # noqa: BLE001 — the sign-up is already saved
        why = "%s: %s" % (type(e).__name__, str(e)[:160])
        log("could not post the sign-up alert: %s" % why)
        return False, why
