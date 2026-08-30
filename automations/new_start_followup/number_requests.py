"""Chase missing leader numbers through the Slack thread itself.

Megan 2026-08-23: "anyone you can't text you should post that in the slack
thread @raf and @aisha for them to then be able to respond with the number or
ignore it. If anyone responds with the number, then you should read it and
send the text."

Two halves:
  * ensure_request(): one post per week in the main-funnel thread —
    "📱 New-Start Texts — numbers needed" @Raf @Aisha, numbered list of the
    leaders with no number on file. Idempotent on its marker, same trick as
    the roll call.
  * process(): read the replies BELOW that post, parse "Name - number" lines
    (Raf's real formats: "Eli Rodriguez is elijah Rodriguez # 4697749466",
    "Hayden Wilson 4696492566", "logan - terminated"), save the number to the
    machine-local overlay, SEND that leader's text, and reply "✅ Texted ..."
    so Raf/Aisha see it landed. "Name - terminated" resolves the gap without
    a text (recorded per-week so the list stops re-listing them).

Name matching: a gap leader matches a reply line when their normalized full
name appears in it, or their first name does and only ONE gap leader has that
first name. A line with two phone-sized digit runs is skipped as ambiguous —
texting a wrong number is worse than waiting.

RUNS ON LUCY 1 (the sends). The Saturday/Sunday `new_start_number_replies`
orchestrator entry exits 1 while gaps remain so the orchestrator keeps
re-polling through the day (same retry idiom as owner_chat_texts' trackers).
Python 3.9-safe.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MARKER = "New-Start Texts — numbers needed"

RAF_ID = "U045Z8N0ZQC"     # Rafael Hidalgo
AISHA_ID = "U083X5ZJWSH"   # Aisha Ceron (main-funnel poster)

STATE_DIR = (Path(__file__).resolve().parents[2] / "output"
             / "new_start_followup" / "number_requests")


def _state_path(monday: dt.date) -> Path:
    return STATE_DIR / ("%s.json" % monday.isoformat())


def _load_state(monday: dt.date) -> dict:
    try:
        return json.loads(_state_path(monday).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — absent/corrupt = fresh
        return {"terminated": []}


def _save_state(monday: dt.date, state: dict) -> None:
    p = _state_path(monday)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1), encoding="utf-8")


def gap_statuses(rec) -> List:
    """Pending leaders we can't text: no number, not resolved as terminated."""
    state = _load_state(rec.monday)
    gone = set(state.get("terminated") or [])
    return [s for s in rec.pending
            if not s.leader.phone and s.leader.slack_id not in gone]


def render_request(gaps) -> str:
    lines = [
        "📱 *{}* — <@{}> <@{}>".format(MARKER, RAF_ID, AISHA_ID),
        "I couldn't text these leaders — no number on file. Reply here with "
        "`Name - number` and I'll send their text (or `Name - terminated`):",
        "",
    ]
    for i, s in enumerate(gaps, 1):
        lines.append("{}. {}".format(i, s.leader.name))
    lines.append("")
    lines.append("_auto by Lucy_")
    return "\n".join(lines)


def _replies(client, rec) -> List[dict]:
    return client.conversations_replies(
        channel=rec.thread["channel"], ts=rec.thread["anchor_ts"], limit=200
    ).get("messages", [])


def find_request(replies: List[dict]) -> Optional[dict]:
    from automations.new_start_followup.thread import _strip
    for msg in replies:
        if MARKER in _strip(msg.get("text", "")):
            return msg
    return None


def _fill_from_contacts(rec, gaps, client=None, live: bool = False) -> Dict[str, str]:
    """Fill missing leader numbers from reception's Contacts, then TEXT them.

    Best-effort and non-fatal: the reception OAuth token isn't on every
    machine, and a report must never die because a lookup it only tries as a
    courtesy wasn't available. Returns {name: e164} for what it filled.

    Sending is part of the same step on purpose. Filling the number alone only
    resolves the ASK -- the leader still owes their new start a text, and
    nothing else would ever send it: the late-number path only fires when a
    number arrives as a thread REPLY, which this one never will. The gap would
    close silently with nobody texted.
    """
    from automations.new_start_followup import (
        contacts_google, pair_chat, roster as roster_mod, texts)

    names = [g.leader.name for g in gaps]
    try:
        found = contacts_google.numbers_for(names)
    except Exception as exc:  # noqa: BLE001
        print("[numbers] couldn't check reception's Contacts ({}) — asking in "
              "the thread instead.".format(str(exc)[:140]))
        return {}
    if not found:
        return {}

    phones = roster_mod.load_phones()
    filled = []
    for g in gaps:
        num = found.get(g.leader.name)
        if not num:
            continue
        print("[numbers] {} found in reception's Contacts.".format(g.leader.name))
        g.leader.phone = num
        phones[g.leader.slack_id] = num
        filled.append(g)
    if not live:
        print("[numbers] [dry-run] overlay not written, no texts sent.")
        return found
    roster_mod.save_phones(phones)

    link = texts.thread_link(rec)
    details = None
    for status in filled:
        marker = texts._marker(rec.monday, status.leader.slack_id)
        if marker.exists():
            continue
        if details is None:
            details = texts.starts_by_leader(rec.monday)
        body = texts.compose(status, rec.monday, link=link,
                             starts=details.get(status.leader.slack_id))
        # Same 3-way delivery as the Saturday sweep, so Raf is in this one too
        # (Megan 2026-08-30: "raf should be included in the text to kenneth").
        result = pair_chat.deliver(status.leader.phone, body, dry_run=False)
        if not result.get("sent"):
            print("[numbers] SEND FAILED for {}: {}".format(
                status.leader.name, result.get("error")))
            continue
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(dt.datetime.now().isoformat(timespec="seconds"))
        print("[numbers] texted {} ({}).".format(
            status.leader.name, pair_chat.describe(result)))
        if client is not None and rec.thread:
            try:
                client.chat_postMessage(
                    channel=rec.thread["channel"],
                    thread_ts=rec.thread["anchor_ts"],
                    text="✅ Found {}'s number and sent their text.".format(
                        status.leader.name))
            except Exception as exc:  # noqa: BLE001 — the text already went
                print("[numbers] couldn't confirm in the thread: {}".format(
                    str(exc)[:120]))
    return found


def ensure_request(rec, client=None, live: bool = False) -> Optional[str]:
    """Post the numbers-needed request if gaps exist and none is up yet.
    Returns a human line describing what happened (None = nothing to do)."""
    gaps = gap_statuses(rec)
    if gaps:
        # LOOK BEFORE ASKING (Megan 2026-08-30: "shouldn't you just have looked
        # at the reception email contacts once he was on?"). Kenneth Guzman was
        # asked about in the thread while his number sat in reception's
        # Contacts the whole time — he only became a leader that morning, when
        # a hand-tag taught Lucy who he was, and nothing re-checked Contacts
        # for a leader who arrived mid-week. Tagging two people to ask for
        # something we already have is the kind of noise that teaches everyone
        # to ignore the post.
        filled = _fill_from_contacts(rec, gaps, client=client, live=live)
        if filled:
            gaps = gap_statuses(rec)
    if not gaps:
        return None
    from automations.shared import slack_metrics_post as smp
    client = client or smp._client()
    if find_request(_replies(client, rec)) is not None:
        return "numbers-needed post already in the thread ({} gap(s) listed)".format(len(gaps))
    body = render_request(gaps)
    print("-" * 46)
    print(body)
    print("-" * 46)
    if not live:
        return "[dry-run] would post the numbers-needed request ({} gap(s))".format(len(gaps))
    client.chat_postMessage(channel=rec.thread["channel"],
                            thread_ts=rec.thread["anchor_ts"], text=body)
    return "posted the numbers-needed request ({} gap(s))".format(len(gaps))


def _match_leader(line_norm: str, gaps) -> Optional[object]:
    """Full normalized name in the line wins; else a first name that is unique
    among the gaps."""
    from automations.new_start_followup.roster import _norm
    for s in gaps:
        if _norm(s.leader.name) and _norm(s.leader.name) in line_norm:
            return s
    firsts = {}  # type: Dict[str, List]
    for s in gaps:
        fn = _norm((s.leader.name or "").split()[0]) if s.leader.name else ""
        if fn:
            firsts.setdefault(fn, []).append(s)
    for fn, matches in firsts.items():
        if len(matches) == 1 and re.search(r"\b%s\b" % re.escape(fn), line_norm):
            return matches[0]
    return None


def parse_replies(replies: List[dict], after_ts: str, gaps) -> List[Tuple[object, str]]:
    """-> [(gap LeaderStatus, '+1…' | 'terminated'), ...] from human replies
    below the request post. One line = one resolution."""
    from automations.new_start_followup.thread import _strip
    from automations.new_start_followup.roster import _norm
    from automations.swag_welcome.roster import normalize_phone

    out = []
    seen = set()
    for msg in replies:
        if float(msg["ts"]) <= float(after_ts) or msg.get("subtype"):
            continue
        text = _strip(msg.get("text", ""))
        if MARKER in text:
            continue
        for line in text.splitlines():
            line_norm = _norm(line)
            if not line_norm:
                continue
            status = _match_leader(line_norm, gaps)
            if status is None or status.leader.slack_id in seen:
                continue
            if "terminat" in line_norm:
                seen.add(status.leader.slack_id)
                out.append((status, "terminated"))
                continue
            runs = re.findall(r"[\d][\d\-\.\(\)\s]{5,}[\d]", line)
            nums = []
            for r in runs:
                e164, _ = normalize_phone(r)
                if e164:
                    nums.append(e164)
            nums = list(dict.fromkeys(nums))
            if len(nums) != 1:
                continue  # none, or ambiguous — wait for a clearer reply
            seen.add(status.leader.slack_id)
            out.append((status, nums[0]))
    return out


def process(rec, live: bool = False) -> dict:
    """One poll pass: read replies, save numbers, send texts, confirm.
    Returns {"resolved": [...], "gaps_remaining": [...], "lines": [...]}"""
    from automations.new_start_followup import roster as roster_mod, texts
    from automations.shared import slack_metrics_post as smp
    from automations.swag_welcome.roster import pretty_phone

    client = smp._client()
    lines = []  # type: List[str]
    replies = _replies(client, rec)
    request = find_request(replies)

    gaps = gap_statuses(rec)
    resolved = []
    if request is not None and gaps:
        state = _load_state(rec.monday)
        details = None
        link = texts.thread_link(rec)
        for status, val in parse_replies(replies, request["ts"], gaps):
            if val == "terminated":
                lines.append("{} marked terminated in the thread — dropped "
                             "from the list, no text.".format(status.leader.name))
                if live:
                    state.setdefault("terminated", []).append(status.leader.slack_id)
                resolved.append(status)
                continue
            if details is None:
                details = texts.starts_by_leader(rec.monday)
            status.leader.phone = val
            body = texts.compose(status, rec.monday, link=link,
                                 starts=details.get(status.leader.slack_id))
            if not live:
                lines.append("[dry-run] would save {} for {} and text them."
                             .format(pretty_phone(val), status.leader.name))
                resolved.append(status)
                continue
            phones = roster_mod.load_phones()
            phones[status.leader.slack_id] = val
            roster_mod.save_phones(phones)
            marker = texts._marker(rec.monday, status.leader.slack_id)
            if marker.exists():
                lines.append("{} already texted this week — number saved only."
                             .format(status.leader.name))
                resolved.append(status)
                continue
            # Same 3-way delivery as the Saturday sweep — a number that
            # arrives late still puts Raf in the thread (Raf, 2026-08-30).
            from automations.new_start_followup import pair_chat
            result = pair_chat.deliver(val, body, dry_run=False)
            if result.get("sent"):
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(dt.datetime.now().isoformat(timespec="seconds"))
                client.chat_postMessage(
                    channel=rec.thread["channel"],
                    thread_ts=rec.thread["anchor_ts"],
                    text="✅ Got it — texted {}.".format(status.leader.name))
                lines.append("Texted {} at {} ({}).".format(
                    status.leader.name, pretty_phone(val),
                    pair_chat.describe(result)))
                if result.get("note"):
                    lines.append("  ! {}".format(result["note"]))
                resolved.append(status)
            else:
                lines.append("SEND FAILED for {}: {}".format(
                    status.leader.name, result.get("error")))
        if live:
            _save_state(rec.monday, state)

    remaining = [s for s in gap_statuses(rec)
                 if s not in resolved and not s.leader.phone]
    note = ensure_request(rec, client=client, live=live)
    if note:
        lines.append(note)
    if remaining:
        lines.append("Still missing a number: {}".format(
            ", ".join(s.leader.name for s in remaining)))
    else:
        lines.append("No number gaps left this week.")
    return {"resolved": resolved, "gaps_remaining": remaining, "lines": lines}
