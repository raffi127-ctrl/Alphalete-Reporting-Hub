"""Deliver each leader's Saturday new-start text into a GROUP chat with Raf.

Raf (2026-08-30, via Megan): "make it a group message with him and the leader."
Before this the Saturday sweep sent 42 separate 1:1 iMessages from Lucy 1, and
Raf never saw the ask land or the reply come back. Every text now goes to a
3-way thread — Lucy's number, Raf, and the one leader — so the chase happens
where Raf can see it and jump in.

WHY THIS MODULE EXISTS AT ALL (the hard part, and it is not obvious):
**Messages' AppleScript cannot create a group chat.** Verified on macOS 26 the
day this was written:
  * `make new text chat` -> "Can't get text chat" (-1728). The `text chat`
    class was removed; the Messages.sdef only has account / chat / participant.
  * `make new chat with properties {participants:{...}}` -> "Can't make ...
    into type participant" (-1700), with raw handles AND with real participant
    references. The chat class's participants element is access="r".
  * The `send` command's `to` takes ONE participant or ONE chat -- no list.
So a group can only be *sent to* once it exists. Two paths, in order:

  1. FIND IT. `find_pair()` enumerates every chat with its participant handles
     (one osascript call, ~0.5s for a whole Messages library) and matches on
     the SET of last-10-digit handles. Once a Raf+leader thread exists, Messages
     reuses it forever, so week 2 onwards is always this path.
  2. CREATE IT via a Shortcut. The Shortcuts "Send Message" action is the only
     scriptable thing on macOS that accepts multiple recipients and opens a new
     group. Same pattern the swag card already uses (swag_welcome/imessage.py):
     hand the recipients and the body over as FILES, run `shortcuts run`.
     One-time build on Lucy 1 -- see SHORTCUT_SETUP below.

If neither path works the text still goes out 1:1 to the leader and the run
says so, loudly. A leader silently not getting chased is the one unacceptable
failure here (same rule as "no number on file" being a reported gap, not a
skip) -- Raf missing from one thread is a much smaller problem.

Raf's own number lives in the SAME machine-local overlay as the leaders'
(~/.config/recruiting-report/new-start-leader-phones.json), keyed by his Slack
ID. Never in leaders.json -- the repo is PUBLIC -- and it ships to Lucy 1 on
the existing `new-start-leader-phones` cred-file flow, no new plumbing.

Python 3.9-safe (the runner is 3.9).
"""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

# Rafael Hidalgo. Same id report.py @-mentions for the Terminated rows; reused
# here as the overlay key so his number rides the existing cred-file push.
RAF_SLACK_ID = "U045Z8N0ZQC"

# One-time build on Lucy 1. Named like the swag one so they sit together in
# the Shortcuts list.
SHORTCUT_NAME = "Alphalete Group Text"

# NOT a dot-folder: Shortcuts is sandboxed and read a hidden folder EMPTY on
# JD's Mac (2026-07-23), which silently sent nothing while exiting 0.
_HANDOFF_DIR = Path.home() / "AlphaleteGroupText"
_RECIPIENTS = _HANDOFF_DIR / "recipients.txt"
_BODY = _HANDOFF_DIR / "message.txt"

SHORTCUT_SETUP = """\
Build this once on Lucy 1 (Shortcuts app -> + -> name it exactly
"Alphalete Group Text"), 5 actions:
  1. Get File            path: ~/AlphaleteGroupText/recipients.txt
  2. Get Phone Numbers from Input      -> set variable "To"
  3. Get File            path: ~/AlphaleteGroupText/message.txt
  4. Get Text from Input               -> set variable "Body"
  5. Send Message  [Body]  to  [To]    ("Show When Run" OFF)
Then prove it without sending:
  lucy rerun new_start_texts_dry
Until it exists the Saturday texts still go out, 1:1, and the run reports
"no Raf group yet" per leader."""


class PairChatError(RuntimeError):
    pass


def _osascript(script: str, timeout: int = 180) -> str:
    if platform.system() != "Darwin":
        raise PairChatError("iMessage only works on macOS (needs Messages.app).")
    proc = subprocess.run(["osascript", "-e", script], capture_output=True,
                          text=True, timeout=timeout)
    if proc.returncode != 0:
        raise PairChatError((proc.stderr or "osascript failed").strip()[:300])
    return (proc.stdout or "").strip()


def last10(handle: str) -> str:
    """Compare handles by their last 10 digits.

    Messages stores the same person as "+12145551234", "(214) 555-1234" or
    "2145551234" depending on how the chat started, and an email handle has no
    digits at all (kept whole, lowercased, so Lucy's own address still matches
    itself rather than collapsing to "").
    """
    digits = "".join(c for c in (handle or "") if c.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return (handle or "").strip().lower()


def raf_phone() -> Optional[str]:
    """Raf's number from the machine-local overlay, or None."""
    from automations.new_start_followup import roster as roster_mod
    return (roster_mod.load_phones().get(RAF_SLACK_ID) or "").strip() or None


def list_chats() -> List[Dict]:
    """[{id, handles:[...]}] for every chat in this machine's Messages.

    `participants` is documented as "OTHER participants", so Lucy's own handle
    is absent: a Raf+leader group reads as exactly two handles.
    """
    out = _osascript(
        'tell application "Messages"\n'
        '  set res to ""\n'
        '  repeat with c in chats\n'
        '    set hs to ""\n'
        '    try\n'
        '      repeat with p in participants of c\n'
        '        set hs to hs & (handle of p) & ","\n'
        '      end repeat\n'
        '    end try\n'
        '    set res to res & (id of c) & tab & hs & linefeed\n'
        '  end repeat\n'
        '  return res\n'
        'end tell')
    chats = []
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        handles = [h for h in (parts[1] if len(parts) > 1 else "").split(",") if h.strip()]
        chats.append({"id": parts[0].strip(), "handles": handles})
    return chats


def find_pair(phones: List[str], chats: Optional[List[Dict]] = None) -> Optional[Dict]:
    """The existing group chat whose participants are EXACTLY `phones`.

    Set equality, not "contains": a chat that also holds 20 other people is a
    different conversation, and dropping this text into it would put one
    leader's chase in front of everybody.
    """
    want = set(last10(p) for p in phones if p)
    if len(want) < 2:
        return None
    for chat in (chats if chats is not None else list_chats()):
        if set(last10(h) for h in chat["handles"]) == want:
            return chat
    return None


def find_shortcut() -> Optional[str]:
    """The Shortcut's ACTUAL name, or None.

    Matched ignoring surrounding space and returned VERBATIM: Shortcuts keeps a
    trailing space in a name silently, and `shortcuts run` then needs the real
    one. An imported copy is exactly where that bites (swag-card lesson).
    """
    try:
        out = subprocess.run(["shortcuts", "list"], capture_output=True,
                             text=True, timeout=15).stdout
        for line in out.splitlines():
            if line.strip() == SHORTCUT_NAME.strip():
                return line
    except Exception:  # noqa: BLE001
        pass
    return None


def _shortcut_installed() -> bool:
    return find_shortcut() is not None


def _looks_like_phone(value: str) -> bool:
    """Hard gate before anything reaches the Shortcut.

    A non-number recipient is what leaves a "No recipients" compose sheet
    parked on screen with the message attached, waiting on a human forever
    (Megan, 2026-08-25). Fail here instead.
    """
    digits = "".join(c for c in (value or "") if c.isdigit())
    return 7 <= len(digits) <= 15


def _create_via_shortcut(phones: List[str], text: str) -> None:
    """Open a NEW group chat with `phones` by sending the first message there.

    The only scriptable multi-recipient send on macOS. Recipients and body ride
    FILES rather than the clipboard: the clipboard hand-off silently fails when
    this runs inside a daemon process rather than a Terminal.
    """
    bad = [p for p in phones if not _looks_like_phone(p)]
    if bad:
        raise PairChatError(
            "refusing to run the group Shortcut — {!r} isn't a phone number. "
            "It would strand a 'No recipients' compose window.".format(bad))
    _HANDOFF_DIR.mkdir(exist_ok=True)
    _RECIPIENTS.write_text(", ".join(phones), encoding="utf-8")
    _BODY.write_text(text, encoding="utf-8")
    actual = find_shortcut() or SHORTCUT_NAME
    proc = subprocess.run(["shortcuts", "run", actual],
                          capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise PairChatError(
            "the '{}' Shortcut failed: {}".format(
                SHORTCUT_NAME, (proc.stderr or "").strip()[:200]))


def _send_to_chat(chat_id: str, text: str) -> None:
    cid = chat_id.replace("\\", "\\\\").replace('"', '\\"')
    # AppleScript 2.0 literals understand \n; a raw newline inside the quoted
    # literal is a compile error.
    safe = (text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n"))
    _osascript('tell application "Messages"\n'
               '  set theChat to a reference to chat id "%s"\n'
               '  send "%s" to theChat\n'
               'end tell' % (cid, safe))


def deliver(leader_phone: str, text: str, *, dry_run: bool = True,
            chats: Optional[List[Dict]] = None) -> Dict:
    """Send `text` to the Raf+leader group, creating it if it doesn't exist.

    Returns {sent, mode, chat_id, created, note, error}. `mode` is "group",
    "group-new" or "direct". Resolution runs even on a dry run — it is the half
    most likely to be wrong, and it writes nothing.
    """
    res = {"sent": False, "mode": "direct", "chat_id": None, "created": False,
           "note": None, "error": None, "recipients": [leader_phone]}

    raf = raf_phone()
    if not raf:
        res["note"] = ("Raf's number isn't in the phone overlay (key %s) — "
                       "texting the leader 1:1." % RAF_SLACK_ID)
    else:
        res["recipients"] = [raf, leader_phone]
        chat = find_pair([raf, leader_phone], chats=chats)
        if chat:
            res.update(mode="group", chat_id=chat["id"])
            if dry_run:
                return res
            _send_to_chat(chat["id"], text)
            res["sent"] = True
            return res
        # No thread yet — the Shortcut is the only way to open one.
        if not _shortcut_installed():
            # One short line per leader; the full build steps print once, in
            # the run's summary, instead of 40 times.
            res["note"] = ("no Raf group yet and the '%s' Shortcut isn't on "
                           "this Mac — texting the leader 1:1."
                           % SHORTCUT_NAME)
        else:
            res.update(mode="group-new", created=True)
            if dry_run:
                return res
            try:
                _create_via_shortcut([raf, leader_phone], text)
                res["sent"] = True
                return res
            except PairChatError as exc:
                res["note"] = ("couldn't open the Raf group (%s) — texting the "
                               "leader 1:1." % exc)
                res.update(mode="direct", created=False,
                           recipients=[leader_phone])

    # Fallback: the original 1:1 send. A leader silently not chased is worse
    # than Raf missing from the thread.
    res["mode"] = "direct"
    res["recipients"] = [leader_phone]
    if dry_run:
        return res
    from automations.swag_welcome import imessage
    out = imessage.send(leader_phone, text, dry_run=False)
    res["sent"] = bool(out.get("sent"))
    res["error"] = out.get("error")
    return res


def readiness(leader_phones: Optional[List[str]] = None) -> List[str]:
    """Can this machine actually deliver into Raf groups? Read-only.

    Exists because the ordinary dry run can't answer it: once a week's .sent
    markers are down, every leader short-circuits to "already texted this week"
    and the delivery path is never reached, so the rehearsal goes quiet exactly
    when you most want it to talk (2026-08-30 — the first post-build dry run
    reported nothing at all). These three lines are marker-independent, so the
    rehearsal is honest on any day of the week.

    What it CANNOT prove: the Shortcut's folder bookmark and the Automation
    grant, both of which only fail when the Shortcut actually runs. A live
    send is the only proof of those.
    """
    from automations.swag_welcome.roster import pretty_phone
    lines = ["Raf-group readiness:"]

    raf = raf_phone()
    lines.append("  Raf's number      %s" % (
        pretty_phone(raf) or raf if raf else
        "MISSING from the phone overlay (key %s) — every text goes 1:1"
        % RAF_SLACK_ID))

    actual = find_shortcut()
    lines.append("  '%s'  %s" % (SHORTCUT_NAME, (
        "installed as %r" % actual if actual else
        "NOT INSTALLED — existing groups still work, new ones can't be opened")))

    try:
        chats = list_chats()
    except Exception as exc:  # noqa: BLE001
        lines.append("  Messages chats    UNREADABLE (%s) — everything goes 1:1"
                     % str(exc)[:120])
        return lines
    have = 0
    if raf and leader_phones:
        have = sum(1 for ph in leader_phones
                   if ph and find_pair([raf, ph], chats=chats))
        lines.append("  Raf groups        %d of %d leader(s) already have one; "
                     "the rest get opened on first send"
                     % (have, len([p for p in leader_phones if p])))
    else:
        lines.append("  Messages chats    %d readable" % len(chats))
    return lines


def describe(res: Dict) -> str:
    """Short per-leader label for the run output."""
    if res["mode"] == "group":
        return "group with Raf (%s)" % (res.get("chat_id") or "?")
    if res["mode"] == "group-new":
        return "NEW group with Raf"
    return "1:1"
