"""A transcript as people read it: in Slack (on a phone) and as plain text.

Every turn starts on its own line with a coloured square, the speaker and the
clock, so a coach can scroll a long one and still see at a glance who is
talking. Rep is blue, Customer orange -- the same two colours everywhere.
"""
from __future__ import annotations

from typing import Dict, List

from automations.lucy_transcriber.transcribe import ROLES, _clock

DOT = {"R": "🟦", "C": "🟧", "O": "⬜"}
# Slack shows ~4,000 characters before "Show more"; keep each message under it.
CHUNK = 3500
# Past this many messages the thread is a wall -- send a file instead.
MAX_MESSAGES = 5

FEEDBACK_ASK = ("💬 *Coaches:* reply right here with feedback 👇 "
                "I keep every note so I can learn what closes deals.")


def _len(sec: float) -> str:
    return _clock(sec)


def header(t: Dict) -> str:
    talk = t.get("talk") or {}
    split = " · ".join("{} {} {}%".format(DOT[sp], ROLES[sp], talk[sp])
                       for sp in ("R", "C", "O") if talk.get(sp))
    return "📝 *Transcript* · {} long\n{}".format(_len(t["seconds"]), split or "")


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


def slack_messages(t: Dict) -> List[str]:
    """The thread reply, split into Slack-sized messages. [] = too long to
    post inline (the caller uploads as_text() as a file instead)."""
    msgs, cur = [], header(t)
    for block in turn_lines(t):
        if len(cur) + len(block) + 2 > CHUNK:
            msgs.append(cur)
            cur = block
        else:
            cur += "\n\n" + block
    if len(cur) + len(FEEDBACK_ASK) + 2 > CHUNK:
        msgs += [cur, FEEDBACK_ASK]
    else:
        msgs.append(cur + "\n\n" + FEEDBACK_ASK)
    return msgs if len(msgs) <= MAX_MESSAGES else []


def as_text(t: Dict) -> str:
    talk = t.get("talk") or {}
    split = ", ".join("{} {}%".format(ROLES[sp], talk[sp])
                      for sp in ("R", "C", "O") if talk.get(sp))
    head = "Transcript - {} long - talk time: {}".format(_len(t["seconds"]), split)
    return head + "\n\n" + "\n".join(turn_lines(t, mrkdwn=False)) + "\n"


NO_TALK = ("🎧 I listened to the whole thing but couldn't hear anyone talking. "
           "Hold the phone a little closer (screen up, in a top pocket) and send it again?")
UNREADABLE = ("🎧 I couldn't open that file as audio. A Voice Memo or a Slack "
              "audio clip works best. Send it again? ¡Gracias!")
