"""Answer people who @-tag Lucy in the week's new-start thread.

Raf, 2026-08-30: "I want to be able to talk to LUCY in this thread, is there a
way to make that happen by tagging her?"

Lucy is Slack user U0BCG8F9B5Z (app A0BCK6R17HB) — that is what an
"@Lucy Reporting" tag resolves to, confirmed off her own roll-call posts. A
reply in this thread mentioning her is treated as a question for her.

THE RULE THAT MAKES THIS SAFE TO RUN UNATTENDED: Lucy answers ONLY from the
report's own state. The facts block is built here, in code, from the same
Reconciliation the posts are rendered from; the model's job is to pick the
relevant parts and phrase them, never to supply facts of its own. A question
the state can't answer gets "I've flagged this for Megan" — it does NOT get a
guess. This is a channel of ~20 leaders reading it as the system of record for
who has to text whom, so a confident wrong answer is worse than no answer.

AND IT NEVER CLAIMS TO HAVE DONE SOMETHING. "Stop pinging Heiddy" is a real
request that needs a real change (shared/slack_do_not_ping.json); Lucy
acknowledges and flags it. A bot that says "done!" and changed nothing is how
a person stops checking.

Idempotent per mention: a per-week state file records which message timestamps
have been answered, and the thread is re-read before posting, so a double run
can't double-answer.

DEFAULT IS DRY-RUN. --live is what posts. Standing rule in this repo is to ask
before any Slack send, and an auto-responder is the one thing that sends
without a human in the loop — so the first pass is meant to be read, not
trusted.

    python -m automations.new_start_followup.run --mode thread-replies
    python -m automations.new_start_followup.run --mode thread-replies --live
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

LUCY_USER_ID = "U0BCG8F9B5Z"
MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")

STATE_DIR = (Path(__file__).resolve().parents[2] / "output"
             / "new_start_followup" / "thread_replies")

MODEL = "claude-sonnet-5"

SYSTEM = """You are Lucy, the reporting bot for a door-to-door sales company. \
Someone has tagged you in the Slack thread for this week's new-start texts.

Answer ONLY from the FACTS block. It is the complete state of the report — if \
something is not in it, you do not know it, and you must say so rather than \
guess. Never invent a name, a number, or a status.

If they are ASKING YOU TO CHANGE SOMETHING (stop pinging a person, add \
someone, fix a name, change the schedule), do NOT claim to have done it. Say \
you have flagged it for Megan, who makes the change. You cannot change \
anything yourself.

Style: plain and short, 1-3 sentences. No emoji, no greeting, no sign-off. \
Write like a colleague answering in a thread. Do not use @-mentions."""


def _state_path(monday) -> Path:
    return STATE_DIR / ("%s.json" % monday.isoformat())


def _load_state(monday) -> dict:
    p = _state_path(monday)
    if not p.exists():
        return {"answered": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"answered": []}


def _save_state(monday, state: dict) -> None:
    p = _state_path(monday)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def questions(rec, state: dict) -> List[dict]:
    """Thread replies that tag Lucy and haven't been answered yet.

    Lucy's OWN posts are skipped — she quotes people's names and would
    otherwise answer herself forever.
    """
    th = rec.thread or {}
    answered = set(state.get("answered") or [])
    out = []
    for msg in th.get("replies") or []:
        if msg.get("ts") in answered:
            continue
        if msg.get("user") == LUCY_USER_ID:
            continue
        if msg.get("subtype"):
            continue
        text = msg.get("text") or ""
        if LUCY_USER_ID not in MENTION_RE.findall(text):
            continue
        if float(msg.get("ts", 0)) <= float(th.get("anchor_ts") or 0):
            continue
        out.append(msg)
    return out


def facts(rec) -> str:
    """Everything Lucy is allowed to know, as plain text.

    Built from the Reconciliation the posts are rendered from, so an answer
    can't disagree with the post above it.
    """
    lines = ["Week of %s (new starts begin Monday)." % rec.monday.isoformat()]
    sent = [s.leader.name for s in rec.sent]
    pending = [s.leader.name for s in rec.pending]
    lines.append("%d of %d leaders have replied Sent."
                 % (len(sent), len(rec.statuses)))
    lines.append("Replied Sent: " + (", ".join(sorted(sent)) or "nobody yet"))
    lines.append("Still owe a text: " + (", ".join(sorted(pending)) or "nobody"))
    if rec.unmatched_obcl:
        lines.append("On the OBCL but with no Slack account we can tag, so they "
                     "need a manual reach-out: "
                     + ", ".join(sorted(rec.unmatched_obcl)))
    if rec.suppressed:
        lines.append("Deliberately NOT being pinged (someone asked for them to "
                     "be left alone): " + ", ".join(sorted(rec.suppressed)))
    if rec.learned:
        lines.append("Newly recognised this week from a hand-tag in the thread: "
                     + ", ".join(sorted(rec.learned)))
    if rec.needs_leader:
        lines.append("%d new start(s) have no leader assigned — their OBCL row "
                     "says Terminated." % rec.needs_leader)
    departed = [s.leader.name for s in rec.statuses if s.departed]
    if departed:
        lines.append("No longer in the channel, so never tagged: "
                     + ", ".join(sorted(departed)))
    lines.append(
        "How the report works: the roster comes from the screenshot posted in "
        "this thread on Friday. New starts marked Declined or Failed "
        "Background are not counted and their interviewer is not tagged about "
        "them. Leaders reply 'Sent' in this thread to be marked done. Lucy "
        "also texts each leader on Saturday morning, in a group message with "
        "Raf.")
    return "\n".join(lines)


def answer(question_text: str, rec) -> str:
    """One reply, grounded in `facts`. Raises if the model can't be reached."""
    import anthropic
    from automations.brand_audit import credentials

    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    # Mentions are opaque ids in the raw text and read as noise to the model.
    cleaned = MENTION_RE.sub("", question_text).strip()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=SYSTEM,
        messages=[{"role": "user", "content":
                   "FACTS:\n%s\n\nSomeone asked you in the thread:\n%s"
                   % (facts(rec), cleaned)}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "text", "")).strip()


def run(rec, live: bool = False, client=None) -> Dict:
    """Answer every unanswered @Lucy in the thread. -> {lines, answered}."""
    from automations.shared import slack_metrics_post as smp

    state = _load_state(rec.monday)
    pending = questions(rec, state)
    result = {"lines": [], "answered": 0}
    if not pending:
        result["lines"].append("No unanswered questions for Lucy in the thread.")
        return result

    client = client or smp._client()
    for msg in pending:
        asked = (msg.get("text") or "").strip()
        try:
            reply = answer(asked, rec)
        except Exception as exc:  # noqa: BLE001
            result["lines"].append(
                "COULDN'T ANSWER %s: %s" % (msg.get("ts"), str(exc)[:160]))
            continue
        if not reply:
            result["lines"].append("Model returned nothing for %s — skipped."
                                   % msg.get("ts"))
            continue
        result["lines"].append("Q (%s): %s" % (msg.get("ts"), asked[:200]))
        result["lines"].append("A: %s" % reply)
        if not live:
            result["lines"].append("   [dry-run] not posted.")
            continue
        client.chat_postMessage(channel=rec.thread["channel"],
                                thread_ts=rec.thread["anchor_ts"], text=reply)
        state.setdefault("answered", []).append(msg["ts"])
        _save_state(rec.monday, state)
        result["answered"] += 1
        result["lines"].append("   posted.")
    return result
