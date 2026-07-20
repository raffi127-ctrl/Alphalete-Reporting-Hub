"""Text the leaders who still haven't sent. RUNS ON LUCY 1 (iMessage).

The Sunday half of Raf's manual loop: after the checklist goes up, he opens
Messages and texts everyone still missing. This sends those from Lucy 1.

Deliberately NOT on a launchd timer. These are personal messages to ~20 people
from a real phone number, so they go out when a human asks -- via the Hub button
or the CLI -- never on a schedule.

    # see exactly who'd get what (no messages sent)
    python -m automations.new_start_followup.run --mode text

    # actually send
    python -m automations.new_start_followup.run --mode text --send
"""
from __future__ import annotations

from typing import List, Optional

from automations.swag_welcome import imessage
from automations.swag_welcome.roster import pretty_phone

CHANNEL_NAME = "#rafs-office-recruiting"


def compose(status, monday) -> str:
    """The nudge text. Kept short and specific -- it names the count so the
    leader knows how many they owe without opening Slack."""
    name = (status.leader.name or "").split()[0] if status.leader.name else "there"
    owed = status.owed
    what = ("your new start" if owed == 1
            else "your {} new starts".format(owed) if owed else "your new starts")
    return (
        "Hey {name}! Quick reminder to text {what} starting Monday {m}/{d} — "
        "then reply “Sent” in the new-starts thread in {ch} so we know "
        "it's done. Let me know if you need the message to copy.".format(
            name=name, what=what, m=monday.month, d=monday.day, ch=CHANNEL_NAME)
    )


class Outcome:
    def __init__(self, status, text: str, sent: bool, skipped: Optional[str] = None,
                 error: Optional[str] = None):
        self.status = status
        self.text = text
        self.sent = sent
        self.skipped = skipped   # why we didn't even try
        self.error = error       # why the send failed

    @property
    def label(self) -> str:
        return self.status.label


def run(rec, send: bool = False) -> List[Outcome]:
    """Text every pending leader. `send=False` composes without sending."""
    pending = rec.pending
    outcomes = []  # type: List[Outcome]

    if send and pending:
        ready, why = imessage.messages_ready()
        if not ready:
            raise RuntimeError(
                "Messages isn't ready on this machine ({}). These texts have to "
                "go from Lucy 1.".format(why))

    for status in pending:
        text = compose(status, rec.monday)
        phone = status.leader.phone
        if not phone:
            # No number is a REPORTED gap, not a silent skip -- otherwise a
            # leader quietly never gets chased.
            outcomes.append(Outcome(status, text, False,
                                    skipped="no number in leaders.json"))
            continue
        if not send:
            outcomes.append(Outcome(status, text, False, skipped="dry-run"))
            continue
        result = imessage.send(phone, text, dry_run=False)
        outcomes.append(Outcome(status, text, bool(result.get("sent")),
                                error=result.get("error")))
    return outcomes


def render(outcomes: List[Outcome], send: bool) -> str:
    lines = []
    if not outcomes:
        return "Nobody is pending — no texts to send."

    for out in outcomes:
        phone = pretty_phone(out.status.leader.phone) or "NO NUMBER"
        if out.sent:
            mark = "sent"
        elif out.error:
            mark = "FAILED: {}".format(out.error)
        elif out.skipped == "dry-run":
            mark = "would send"
        else:
            mark = "SKIPPED: {}".format(out.skipped)
        lines.append("{:<20} {:<16} {}".format(out.label, phone, mark))
        lines.append("    {}".format(out.text))
        lines.append("")

    sent = sum(1 for o in outcomes if o.sent)
    blocked = [o for o in outcomes if o.skipped and o.skipped != "dry-run"]
    failed = [o for o in outcomes if o.error]

    if send:
        lines.append("Sent {} of {}.".format(sent, len(outcomes)))
    else:
        lines.append("[dry-run] {} message(s) composed, none sent. "
                     "Re-run with --send to text them.".format(len(outcomes)))
    if blocked:
        lines.append("INCOMPLETE — {} leader(s) have no number: {}".format(
            len(blocked), ", ".join(o.label for o in blocked)))
        lines.append("  Fill them in with: python -m "
                     "automations.new_start_followup.contacts --write   (on Lucy 1)")
    if failed:
        lines.append("INCOMPLETE — {} send(s) failed: {}".format(
            len(failed), ", ".join(o.label for o in failed)))
    return "\n".join(lines)
