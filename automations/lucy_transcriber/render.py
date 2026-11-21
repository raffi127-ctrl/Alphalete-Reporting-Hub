"""A transcript as people read it: in Slack (on a phone) and as plain text.

Every turn starts on its own line with a coloured square, the speaker and the
clock, so a coach can scroll a long one and still see at a glance who is
talking. Rep is blue, Customer orange -- the same two colours everywhere.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from automations.lucy_transcriber.transcribe import ROLES, _clock

DOT = {"R": "🟦", "C": "🟧", "O": "⬜"}
# Slack shows ~4,000 characters before "Show more"; keep each message under it.
CHUNK = 3500
# Past this many messages the thread is a wall -- send a file instead.
MAX_MESSAGES = 5

# Text fallback only (the PDF couldn't be made).
REP_END = ""
# Uplines get the PDF with this line -- no feedback ask: only Raf grades.
UPLINE_FYI = "📎 A copy of {first}'s pitch for you."
COACH_ASK = ("💬 Reply right here with feedback for {first} 👇 "
             "I keep every note so I can learn what closes deals.")

GOT_IT = "🎧 Got it! Your transcript will be here in a minute or two."
HELP = ("👋 Send me a recording of your pitch -- a Voice Memo or a Slack audio "
        "clip -- and I'll send back the whole conversation, every line marked "
        "🟦 Rep or 🟧 Customer.")
SAVED = "white_check_mark"     # reaction on a coach's feedback reply

# Megan 2026-11-21: ask each rep who their upline is; Raf always gets a copy.
ASK_UPLINE = ("👤 *Who should get a copy?* Pick your upline -- as many people "
              "as you want -- then tap *Submit*. Raf always gets one.")
SUBMIT_LATER = ("👆 Tap *Submit* in the message above to send copies to your "
                "upline and Raf.")

NO_TALK = ("🎧 I listened to the whole thing but couldn't hear anyone talking. "
           "Hold the phone a little closer (screen up, in a top pocket) and send it again?")
UNREADABLE = ("🎧 I couldn't open that file as audio. A Voice Memo or a Slack "
              "audio clip works best. Send it again? ¡Gracias!")
TOO_BIG = ("🎧 That file is too big for me ({mb} MB). Can you send it in "
           "shorter pieces? One door per recording is perfect.")
TOO_LONG = ("🎧 That one is {len} -- I transcribe up to 3 hours at a time. "
            "Send it in shorter pieces? One door per recording is perfect.")
GAVE_UP = ("🎧 Something went wrong on my side with this one -- I've flagged "
           "it to the team. Sorry! Send it again later?")


def header(t: Dict, who: Optional[str] = None) -> str:
    talk = t.get("talk") or {}
    split = " · ".join("{} {} {}%".format(DOT[sp], ROLES[sp], talk[sp])
                       for sp in ("R", "C", "O") if talk.get(sp))
    title = "*{}'s pitch*".format(who) if who else "*Transcript*"
    return "📝 {} · {} long\n{}".format(title, _clock(t["seconds"]), split)


def ready(t: Dict) -> str:
    """The one line on the rep's PDF. Who gets copies is said ONCE, on the
    'Got it' message after Submit -- not again here (Megan 2026-11-21: "it's
    redundant, says it went to Raf twice")."""
    return "📝 *Your pitch transcript* · {} long".format(_clock(t["seconds"]))


def turn_lines(t: Dict, mrkdwn: bool = True) -> List[str]:
    out = []
    for tu in t["turns"]:
        who = ROLES[tu["speaker"]]
        if mrkdwn:
            out.append("{} *{}* `{}`\n{}".format(DOT[tu["speaker"]], who,
                                                _clock(tu["start"]), tu["text"]))
        else:
            out.append("[{}] {}: {}".format(_clock(tu["start"]), who, tu["text"]))
    return out


def slack_messages(t: Dict, end: str = REP_END, who: Optional[str] = None,
                   head: bool = True) -> List[str]:
    """The reply, split into Slack-sized messages, `end` on the last one.
    head=False leaves the header off (the coach's copy carries it on the
    parent message instead). [] = too long to post inline (the caller
    uploads as_text() as a file)."""
    msgs, cur = [], header(t, who) if head else ""
    for block in turn_lines(t):
        if cur and len(cur) + len(block) + 2 > CHUNK:
            msgs.append(cur)
            cur = block
        else:
            cur = cur + "\n\n" + block if cur else block
    if not end:
        msgs.append(cur)
    elif len(cur) + len(end) + 2 > CHUNK:
        msgs += [cur, end]
    else:
        msgs.append(cur + "\n\n" + end)
    return msgs if len(msgs) <= MAX_MESSAGES else []


def as_text(t: Dict, who: Optional[str] = None) -> str:
    talk = t.get("talk") or {}
    split = ", ".join("{} {}%".format(ROLES[sp], talk[sp])
                      for sp in ("R", "C", "O") if talk.get(sp))
    head = "{} - {} long - talk time: {}".format(
        "{}'s pitch".format(who) if who else "Transcript", _clock(t["seconds"]), split)
    return head + "\n\n" + "\n".join(turn_lines(t, mrkdwn=False)) + "\n"
