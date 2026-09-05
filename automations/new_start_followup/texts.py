"""Text each leader who owes a new-start text. RUNS ON LUCY 1 (iMessage,
alphaletereporting@gmail.com — the same account that runs owner_chat_texts).

UN-PARKED 2026-08-23 (Raf's Loom): "the leaders suck at checking Slack...
they respond quickly if they get a text." Scheduled Saturday 8:30am CST —
after the 8:00 roll call, so the Slack thread the text links to already
exists. This replaces Raf hand-texting 30+ leaders every weekend.

Since 2026-08-30 each text lands in a GROUP with Raf and the one leader, not a
1:1 (Raf via Megan: "make it a group message with him and the leader") — see
pair_chat.py, which also explains why creating that group needs a Shortcut.

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

from automations.new_start_followup import pair_chat, terminated
from automations.swag_welcome import imessage
from automations.swag_welcome.roster import pretty_phone

# Where the "reply Sent" thread lives — used only for the human-readable
# channel name in error text; the actual link is built from the thread itself.
WORKSPACE_URL = "https://ao-pbns.slack.com"

# Per-(week, leader) sent markers. output/ is git-ignored and machine-local,
# which is right: the marker records what THIS machine already texted.
MARKER_DIR = Path(__file__).resolve().parents[2] / "output" / "new_start_followup" / "texts"


def thread_link(rec) -> Optional[str]:
    """Permalink that opens THAT WEEK'S THREAD, not the channel.

    Built by hand from channel + ts — the p<ts> permalink format is stable and
    saves an API call per text.

    The `?thread_ts=…&cid=…` tail is load-bearing (Raf 2026-09-05: "the link
    that Lucy sends, its a thread of the recruiting slack and that doesn't help
    the rep" — his Loom: it "takes them to the whole rafs office recruiting").
    A bare /archives/<cid>/p<ts> drops the reader in the CHANNEL and makes them
    hunt for the right post; the same permalink WITH the thread parameters is
    what Slack's own "Copy link" produces on a threaded message, and it opens
    the thread pane directly on that week's roster. Same anchor message either
    way — only the destination changes.

    The channel is whatever the thread was found in (it has already moved once,
    2026-08-22), so nothing here is hardcoded and a rename can't break it.
    """
    th = rec.thread or {}
    channel = th.get("channel")
    ts = th.get("anchor_ts")
    if not channel or not ts:
        return None
    return "{}/archives/{}/p{}?thread_ts={}&cid={}".format(
        WORKSPACE_URL, channel, str(ts).replace(".", ""), ts, channel)


def compose(status, monday, link: Optional[str] = None,
            starts: Optional[list] = None) -> str:
    """Raf's short ask, from Lucy, with the thread link — then the leader's
    new starts as "Name - phone" lines (Megan 2026-08-23: leaders kept asking
    where to find the contact info; Willvim did exactly that on 8/23).

    THIS is what the OBCL Phone column is for — it's the NEW START'S number,
    handed TO the leader inside the message. It must never be a send target.
    """
    name = (status.leader.name or "").split()[0] if status.leader.name else "there"
    many = len(starts) > 1 if starts else status.owed != 1
    # Raf 2026-09-05: "new starts that you have scheduled this Monday" — the old
    # "that start this Monday" read as if Lucy were telling them who starts.
    # Singular/plural is kept from the original: he wrote the plural because the
    # leader he screenshotted had two.
    what = ("your new starts that you have scheduled this Monday" if many
            else "your new start that you have scheduled this Monday")
    text = ("Hey {name}, it's Lucy! Can you text {what} and reply Sent in "
            "the Slack thread once done please? I'll attach the message to "
            "send to them, just copy, paste and edit your name and their name "
            "in the message please!".format(name=name, what=what))
    if link:
        text += "\n" + link
    if starts:
        text += "\n"
        for ns_name, ns_phone in starts:
            text += "\n{} - {}".format(ns_name, ns_phone or "no number on the OBCL")
    return text


# Raf's script for the leader to forward to their new start (2026-09-05, his
# Slack message + Loom). It ships as its OWN iMessage, and that is the whole
# point: iMessage copies a WHOLE message or nothing, so a template appended to
# the ask above could not be copied without also copying the ask. The `X`
# placeholders are Raf's own — he wants the leader to edit both names, and one
# template has to serve a leader with several new starts.
NEW_START_SCRIPT = (
    "Hey X, this is X I look forward to seeing you at the office on Monday!\n"
    "I know they told me that they got your gift all ready! The rest of the "
    "team is excited to meet you. Out of everyone I've interviewed, I'm "
    "genuinely fired up that you're one of the people starting on Monday. Are "
    "you good with the office address? Is there anything that you need from "
    "me?\n"
    "Dress is business Professional\n"
    "Shouldn't go longer than 5:00pm"
)


def compose_script() -> str:
    """The second message: the copy/paste script, alone and nothing else."""
    return NEW_START_SCRIPT


def _join_note(existing: Optional[str], extra: str) -> str:
    """Keep a routing note (e.g. the 1:1 fallback) AND a script failure — the
    second must never overwrite the first, they are different problems."""
    return "{} · {}".format(existing, extra) if existing else extra


def starts_by_leader(monday) -> dict:
    """slack_id -> [(new-start name, pretty phone), ...] off the week's OBCL tab.

    The screenshot decides WHO owes a text; the sheet is where the new starts'
    names and numbers live, so the detail lines come from here. Advisory: a
    sheet read failing means the texts go out without the list, not not at all.
    """
    from automations.new_start_followup import obcl, roster as roster_mod
    from automations.swag_welcome.roster import normalize_phone, pretty_phone

    ros = roster_mod.load()
    out = {}  # type: dict
    seen = set()
    try:
        _, _, rows = obcl.read_new_starts(monday)
    except Exception as exc:  # noqa: BLE001
        print("WARNING: couldn't read the OBCL sheet ({}) — texts go out "
              "without the name/number lines.".format(exc))
        return {}
    for ns in rows:
        if ns.dropped or not ns.interviewer or not ns.name:
            continue
        leader = ros.by_obcl_name(ns.interviewer)
        if leader is None:      # incl. rows marked "Terminated"
            continue
        key = (leader.slack_id, roster_mod._norm(ns.name))
        if key in seen:         # the sheet carries duplicate rows sometimes
            continue
        seen.add(key)
        e164, _ = normalize_phone(ns.phone or "")
        shown = pretty_phone(e164) if e164 else (ns.phone or "").strip()
        out.setdefault(leader.slack_id, []).append((ns.name.strip(), shown))
    return out


class Outcome:
    def __init__(self, status, text: str, sent: bool, skipped: Optional[str] = None,
                 error: Optional[str] = None, route: str = "",
                 note: Optional[str] = None):
        self.status = status
        self.text = text
        self.sent = sent
        self.skipped = skipped   # why we didn't even try
        self.error = error       # why the send failed
        self.route = route       # "group with Raf" / "NEW group with Raf" / "1:1"
        self.note = note         # why it fell back off the group route

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
    details = starts_by_leader(rec.monday)

    # Every text goes to a 3-way thread — Lucy, Raf, the leader (Raf via Megan,
    # 2026-08-30). The chat index is read ONCE for the whole sweep: it's a
    # single osascript call over the entire Messages library, and doing it per
    # leader would be 40+ round trips for the same answer.
    chats = None
    try:
        chats = pair_chat.list_chats()
    except Exception as exc:  # noqa: BLE001 — degrade to 1:1, never to nothing
        print("WARNING: couldn't read the Messages chat list ({}) — texts go "
              "out 1:1 instead of in a group with Raf.".format(exc))

    # CHECKPOINT 2: the master Terminated Reps list (Megan 2026-09-05, "so that
    # there are 2 checkpoints before texting happens"). Checkpoint 1 is the OBCL
    # "Terminated" marker, which only fires if somebody edits that cell; this
    # one catches the leaver whose Slack account was merely deactivated, which
    # channel-membership replay can never see.
    #
    # Advisory on failure: checkpoint 1 still stands, and never chasing a leader
    # is worse than the sweep running on one checkpoint — but the run says so.
    global _LAST_TERMINATED_ERROR
    terminated_table = {}
    _LAST_TERMINATED_ERROR = None
    try:
        terminated_table = terminated.load_cached()
    except Exception as exc:  # noqa: BLE001
        _LAST_TERMINATED_ERROR = str(exc)[:160]
        print("WARNING: couldn't read the '{}' tab ({}) — running on the OBCL "
              "marker alone.".format(terminated.TAB_TITLE,
                                     _LAST_TERMINATED_ERROR))

    for status in pending:
        text = compose(status, rec.monday, link=link,
                       starts=details.get(status.leader.slack_id))
        # Checked BEFORE the number and before the marker: a terminated leader
        # must not be texted even if they have a number, and must not be
        # reported as a numbers gap (that would put an ex-employee's name in
        # the Slack "numbers needed" post for someone to helpfully fill in).
        gone = terminated.find(status.leader, terminated_table)
        if gone is not None:
            outcomes.append(Outcome(
                status, text, False,
                skipped="TERMINATED — {}".format(gone.describe())))
            continue

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
        if chats is None:
            # The chat index didn't read, so we can't tell an existing Raf
            # group from a missing one. Send 1:1 rather than let the Shortcut
            # open a duplicate thread beside one that already exists.
            result = {"sent": False, "mode": "direct", "note":
                      "Messages chat list unreadable — sent 1:1", "error": None}
            if send:
                out = imessage.send(phone, text, dry_run=False)
                result["sent"] = bool(out.get("sent"))
                result["error"] = out.get("error")
        else:
            result = pair_chat.deliver(phone, text, dry_run=not send,
                                       chats=chats)
        route = pair_chat.describe(result)
        if not send:
            outcomes.append(Outcome(status, text, False, skipped="dry-run",
                                    route=route, note=result.get("note")))
            continue
        ok = bool(result.get("sent"))
        note = result.get("note")
        if ok:
            import datetime as dt
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(dt.datetime.now().isoformat(timespec="seconds"))
            # A group we just opened is a real chat NOW. Re-read the index so
            # it carries a real chat id — the Shortcut sends without telling us
            # the guid, and a placeholder entry would send the next message
            # into `chat id ""`.
            #
            # This re-read MUST happen before the script message below, not
            # just before the next leader: the script is a SECOND send to the
            # same people, and without a real chat id pair_chat would run the
            # Shortcut again and open a DUPLICATE group beside the one we just
            # made.
            if result.get("created"):
                try:
                    chats = pair_chat.list_chats()
                except Exception:  # noqa: BLE001
                    pass
            # Raf's copy/paste script, as its own message (2026-09-05): iMessage
            # copies a whole message or nothing, so this cannot ride along with
            # the ask above.
            try:
                second = pair_chat.deliver(phone, compose_script(),
                                           dry_run=False, chats=chats)
                if not second.get("sent"):
                    note = _join_note(note, "SCRIPT MESSAGE NOT SENT: {}".format(
                        second.get("error") or "unknown error"))
            except Exception as exc:  # noqa: BLE001 — the ask already landed
                note = _join_note(note, "SCRIPT MESSAGE NOT SENT: {}".format(
                    str(exc)[:120]))
        outcomes.append(Outcome(status, text, ok, error=result.get("error"),
                                route=route, note=note))
    return outcomes


# Set by run() when checkpoint 2 could not be read, so render() can say the
# sweep ran degraded. Module-level because run() returns a plain list and every
# caller renders the run it just did; render() takes it as an explicit argument
# too, so a test never depends on that ordering.
_LAST_TERMINATED_ERROR = None  # type: Optional[str]


def render(outcomes: List[Outcome], send: bool,
           terminated_note: Optional[str] = None) -> str:
    if terminated_note is None:
        terminated_note = _LAST_TERMINATED_ERROR
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
        lines.append("{:<20} {:<16} {:<22} {}".format(
            out.label, phone, out.route or "", mark))
        if out.note:
            lines.append("    ! {}".format(out.note))
        lines.append("    {}".format(out.text.replace("\n", "\n    ")))
        lines.append("")

    sent = sum(1 for o in outcomes if o.sent)
    # A terminated leader is a DELIBERATE skip, not a gap to chase — it must
    # never land in the "no number" list, or their name goes into the Slack
    # numbers-needed post for someone to helpfully fill in.
    stopped = [o for o in outcomes
               if o.skipped and o.skipped.startswith("TERMINATED")]
    blocked = [o for o in outcomes if o.skipped
               and not o.skipped.startswith("TERMINATED")
               and o.skipped not in ("dry-run", "already texted this week")]
    failed = [o for o in outcomes if o.error]

    # The script is byte-identical for every leader, so it prints ONCE here
    # rather than 24 times above — but it has to print, or a preview silently
    # shows half of what actually goes out.
    lines.append("SECOND MESSAGE (same thread, sent right after each ask above "
                 "— identical for everyone):")
    lines.append("    " + compose_script().replace("\n", "\n    "))
    lines.append("")

    if send:
        lines.append("Sent {} of {}.".format(sent, len(outcomes)))
    else:
        lines.append("[dry-run] {} leader(s) composed x2 messages, none sent. "
                     "Re-run with --live to text them.".format(len(outcomes)))
    # Loud, never silent: a wrong block means a leader's new starts go unchased,
    # so the name, the date and the sheet row are all here to be checked.
    if stopped:
        lines.append("NOT TEXTED — {} leader(s) are on the '{}' list:".format(
            len(stopped), terminated.TAB_TITLE))
        for o in stopped:
            lines.append("  {} — {}".format(
                o.label, o.skipped[len("TERMINATED — "):]))
        lines.append("  Their new starts still need a leader assigned. If "
                     "someone here was REHIRED, put 'rehired' in that row's "
                     "Notes on the sheet and they text again next run.")
    if terminated_note:
        lines.append("INCOMPLETE — ran on ONE checkpoint: couldn't read the "
                     "'{}' tab ({}). Only the OBCL 'Terminated' marker "
                     "applied.".format(terminated.TAB_TITLE, terminated_note))
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

    # The ask landing without the script is a HALF delivery: the leader is told
    # "I'll attach the message to send to them" and then gets nothing to paste.
    # It can't fail the marker (that would re-send the ask to everyone), so it
    # has to be loud here instead.
    no_script = [o for o in outcomes if o.note and "SCRIPT MESSAGE NOT SENT" in o.note]
    if no_script:
        lines.append("INCOMPLETE — {} leader(s) got the ask but NOT the "
                     "copy/paste script: {}".format(
                         len(no_script), ", ".join(o.label for o in no_script)))
        lines.append("  They were promised an attached message. Re-send the "
                     "script to them by hand, or clear their .sent marker to "
                     "re-run the pair.")

    # Raf asked to be in every one of these threads — a leader who fell back to
    # a 1:1 is a gap he can't see, so it gets named, not buried in the log.
    solo = [o for o in outcomes if o.route == "1:1" and o.skipped != "already texted this week"]
    if solo:
        lines.append("NOT IN A GROUP WITH RAF — {} leader(s) went 1:1: {}".format(
            len(solo), ", ".join(o.label for o in solo)))
        lines.append("  " + pair_chat.SHORTCUT_SETUP.replace("\n", "\n  "))
    return "\n".join(lines)
