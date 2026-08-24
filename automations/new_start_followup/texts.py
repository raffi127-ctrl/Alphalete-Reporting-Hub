"""Text each leader who owes a new-start text. RUNS ON LUCY 1 (iMessage,
alphaletereporting@gmail.com — the same account that runs owner_chat_texts).

UN-PARKED 2026-08-23 (Raf's Loom): "the leaders suck at checking Slack...
they respond quickly if they get a text." Scheduled Saturday 8:30am CST —
after the 8:00 roll call, so the Slack thread the text links to already
exists. This replaces Raf hand-texting 30+ leaders every weekend.

The copy mirrors the message Raf already sends from Lucy's number (Megan's
screenshot, 8/23): short ask + the Slack thread link. Two rules survive from
the 7/19 build:
  1. SAY IT'S LUCY — an unexpected text from an unknown number reads as spam.
  2. Confirmations are routed to the Slack thread ("reply Sent"), never to
     the phone number — nothing reads replies to Lucy's number.

Terminated leaders can't be texted by construction: an OBCL row marked
"Terminated" never becomes a LeaderStatus (report._assemble routes it to
rec.needs_leader), and departed leaders are excluded from rec.pending.

Idempotent per (week, leader): a .sent marker is dropped after each
successful send, so a retried run only texts whoever it missed.

    # see exactly who'd get what (no messages sent)
    python -m automations.new_start_followup.run --mode sat-texts

    # actually send (the launchd agent runs this)
    python -m automations.new_start_followup.run --mode sat-texts --live
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from automations.swag_welcome import imessage
from automations.swag_welcome.roster import pretty_phone

# Where the "reply Sent" thread lives — used only for the human-readable
# channel name in error text; the actual link is built from the thread itself.
WORKSPACE_URL = "https://ao-pbns.slack.com"

# Per-(week, leader) sent markers. output/ is git-ignored and machine-local,
# which is right: the marker records what THIS machine already texted.
MARKER_DIR = Path(__file__).resolve().parents[2] / "output" / "new_start_followup" / "texts"


def thread_link(rec) -> Optional[str]:
    """Permalink to the week's thread (the Friday anchor post).

    Built by hand from channel + ts — the p<ts> permalink format is stable and
    saves an API call per text.
    """
    th = rec.thread or {}
    channel = th.get("channel")
    ts = th.get("anchor_ts")
    if not channel or not ts:
        return None
    return "{}/archives/{}/p{}".format(WORKSPACE_URL, channel,
                                       str(ts).replace(".", ""))


def compose(status, monday, link: Optional[str] = None) -> str:
    """Raf's short ask, from Lucy, with the thread link.

    No per-leader counts (Raf 2026-08-23) — "your new starts" covers however
    many they have.
    """
    name = (status.leader.name or "").split()[0] if status.leader.name else "there"
    what = "your new start" if status.owed == 1 else "your new starts"
    text = ("Hey {name}, it's Lucy! Can you text {what} starting Monday "
            "and reply Sent in the Slack thread once done please?".format(
                name=name, what=what))
    if link:
        text += "\n" + link
    return text


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


# NEVER fill numbers from the OBCL sheet. Its Phone column is the NEW START'S
# number, not the interviewer's (Megan 2026-08-23) — the old name-match fill
# ("leaders were new starts once") was one collision away from texting a
# brand-new hire a leader chase message. obcl.phone_book() was deleted for
# this. Leader numbers come ONLY from the machine-local overlay
# (~/.config/recruiting-report/new-start-leader-phones.json), which
# roster.load() already applies. Fill it from alphaletereception@'s Google
# Contacts (contacts_google.py --write on the laptop, then
# `lucy push_cred_file new-start-leader-phones 'Lucy 1'`), or by hand.


def _marker(monday, slack_id: str) -> Path:
    return MARKER_DIR / monday.isoformat() / ("%s.sent" % slack_id)


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

    link = thread_link(rec)
    if not link:
        print("WARNING: couldn't build the thread link — texts go out without it.")

    for status in pending:
        text = compose(status, rec.monday, link=link)
        phone = status.leader.phone
        if not phone:
            # No number is a REPORTED gap, not a silent skip -- otherwise a
            # leader quietly never gets chased.
            outcomes.append(Outcome(status, text, False,
                                    skipped="no number on file"))
            continue
        marker = _marker(rec.monday, status.leader.slack_id)
        if marker.exists():
            outcomes.append(Outcome(status, text, False,
                                    skipped="already texted this week"))
            continue
        if not send:
            outcomes.append(Outcome(status, text, False, skipped="dry-run"))
            continue
        result = imessage.send(phone, text, dry_run=False)
        ok = bool(result.get("sent"))
        if ok:
            import datetime as dt
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(dt.datetime.now().isoformat(timespec="seconds"))
        outcomes.append(Outcome(status, text, ok, error=result.get("error")))
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
        lines.append("    {}".format(out.text.replace("\n", "\n    ")))
        lines.append("")

    sent = sum(1 for o in outcomes if o.sent)
    blocked = [o for o in outcomes if o.skipped
               and o.skipped not in ("dry-run", "already texted this week")]
    failed = [o for o in outcomes if o.error]

    if send:
        lines.append("Sent {} of {}.".format(sent, len(outcomes)))
    else:
        lines.append("[dry-run] {} message(s) composed, none sent. "
                     "Re-run with --live to text them.".format(len(outcomes)))
    if blocked:
        lines.append("INCOMPLETE — {} leader(s) have no number: {}".format(
            len(blocked), ", ".join(o.label for o in blocked)))
        lines.append("  Numbers come ONLY from the machine-local overlay "
                     "(never the OBCL — its Phone column is the new start's).")
        lines.append("  Fill from reception's Google Contacts (laptop): python -m "
                     "automations.new_start_followup.contacts_google --write")
        lines.append("  then: lucy push_cred_file new-start-leader-phones 'Lucy 1'")
    if failed:
        lines.append("INCOMPLETE — {} send(s) failed: {}".format(
            len(failed), ", ".join(o.label for o in failed)))
    return "\n".join(lines)
