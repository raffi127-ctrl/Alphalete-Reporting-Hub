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

from automations.icd_signup.schema import IcdSignup

CADENCE_WORDS = {15: "every 15 minutes", 30: "every 30 minutes",
                 60: "once an hour", 0: "at 2:00, 5:15 and 9:00",
                 -1: "not wanted"}


def lines(rec: IcdSignup, link: str = "") -> Tuple[str, List[str]]:
    """(headline, thread detail). Corrections-channel house style: one line in
    the room, the detail in the thread."""
    head = ("*New Lucy Eco sign-up — %s* wants their office on credit-check "
            "alerts." % rec.owner)
    sat = ("Sat %s–%s" % (rec.sat_start, rec.sat_end) if rec.saturday
           else "no Saturday")
    detail = [
        "*%s* — `%s`" % (rec.owner, rec.office_key),
        "• Selling hours: M–F %s–%s · %s · %s"
        % (rec.day_start, rec.day_end, sat, rec.timezone.split("/")[-1]),
        "• Computer: %s" % ("Mac" if rec.platform == "mac" else "Windows PC"),
        "• Knocks board: %s" % CADENCE_WORDS.get(rec.knocks_cadence, "?"),
        "• Reach them at: %s" % (rec.contact or "_not given_"),
    ]
    if rec.ov_name:
        detail.append("• Their name in OwnerVille: %s" % rec.ov_name)
    if rec.wanted_channels:
        detail.append("• Channels they mentioned: %s" % rec.wanted_channels)
    detail += [
        "",
        (("• _They already have their setup link and can install now — "
          "approving decides where their numbers POST._\n"
          "• Their link, if they lose it: %s" % link) if link else
         "• _No key was written, so SEND THEM THEIR LINK by hand:_ "
         "`python -m automations.icd_alerts.invite %s`" % rec.office_key),
        "",
        "Approve them with:",
        "```python -m automations.icd_signup.approve %s```" % rec.office_key,
        ("_That is what turns their numbers into posts. Until you run it they "
         "can install and relay, and nothing reaches a channel._" if link else
         "_Nothing exists until you run it._"),
    ]
    return head, detail


def notify(rec: IcdSignup, *, send: bool = False, link: str = "",
           log=print) -> bool:
    head, detail = lines(rec, link)
    log(head)
    for d in detail:
        log("   %s" % d)
    if not send:
        return False
    try:
        from automations.icd_alerts import offices as O, post as P
        ts = P._slack(O.OPS_CHANNEL, head)
        P._slack(O.OPS_CHANNEL, "\n".join(detail), thread_ts=ts)
        return True
    except Exception as e:  # noqa: BLE001 — the sign-up is already saved
        log("could not post the sign-up alert: %s: %s"
            % (type(e).__name__, str(e)[:120]))
        return False
