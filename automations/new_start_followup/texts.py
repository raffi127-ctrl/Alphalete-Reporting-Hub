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


def compose(status, monday, script: Optional[str] = None) -> str:
    """The nudge text.

    Two things it must do:
      1. SAY IT'S LUCY. An unexpected text about new starts from an unknown
         number reads like spam otherwise.
      2. CARRY the copy/paste script rather than offering to send it. Nothing
         reads replies to Lucy's number, so "let me know if you need it" would
         be a promise nobody keeps -- the leader would sit waiting on an answer
         that never comes. Including it up front removes the round trip.

    Falls back to pointing at the Slack thread when the script can't be found,
    which is still self-serve.
    """
    name = (status.leader.name or "").split()[0] if status.leader.name else "there"
    owed = status.owed
    what = ("your new start" if owed == 1
            else "your {} new starts".format(owed) if owed else "your new starts")

    lines = [
        "Hey {name}, it's Lucy! Quick reminder to text {what} starting "
        "Monday {m}/{d} — then reply “Sent” in the new-starts thread in {ch} "
        "so we know it's done.".format(
            name=name, what=what, m=monday.month, d=monday.day, ch=CHANNEL_NAME),
    ]
    if script:
        lines.append("")
        lines.append("Here's the message to copy — just swap out the X's:")
        lines.append("")
        lines.append(script)
    else:
        lines.append("")
        lines.append("The message to copy is in that same thread in {}.".format(
            CHANNEL_NAME))
    return "\n".join(lines)


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


def resolve_phones(rec) -> int:
    """Fill in any missing leader numbers from the OBCL phone book.

    A number already on the leader (the machine-local overlay) WINS -- that's
    hand-entered and authoritative. This only fills blanks, and only for the
    people we're about to text, so a normal status run never pays for it.
    """
    from automations.new_start_followup import obcl

    need = [s.leader for s in rec.pending if not s.leader.phone]
    if not need:
        return 0
    book = obcl.phone_book()
    filled = 0
    for leader in need:
        for key in leader.keys():
            if key in book:
                leader.phone = book[key]
                filled += 1
                break
    return filled


def run(rec, send: bool = False) -> List[Outcome]:
    """Text every pending leader. `send=False` composes without sending."""
    resolve_phones(rec)
    pending = rec.pending
    outcomes = []  # type: List[Outcome]

    if send and pending:
        ready, why = imessage.messages_ready()
        if not ready:
            raise RuntimeError(
                "Messages isn't ready on this machine ({}). These texts have to "
                "go from Lucy 1.".format(why))

    script = (rec.thread or {}).get("script")
    for status in pending:
        text = compose(status, rec.monday, script=script)
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
        lines.append("  They're not in the OBCL phone book (never a new start "
                     "themselves, or a different name spelling).")
        lines.append("  Fill them in with: python -m "
                     "automations.new_start_followup.contacts --write   (on Lucy 1)")
    if failed:
        lines.append("INCOMPLETE — {} send(s) failed: {}".format(
            len(failed), ", ".join(o.label for o in failed)))
    return "\n".join(lines)
