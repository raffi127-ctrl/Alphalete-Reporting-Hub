"""Join OBCL + roster + Slack thread into "who sent, who didn't".

Two sources disagree about who owes a text and that disagreement is the point:
  OBCL column B  = who SHOULD message (Raf: "the 2nd round interviewer is who
                   should be messaging them")
  Saturday tags  = who Aisha ACTUALLY tagged

Anyone in one but not the other is surfaced as a flag rather than quietly
dropped -- a leader missing from the roll call never gets nudged, and that's
exactly the miss this report exists to catch.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.new_start_followup import obcl, roster as roster_mod, thread as thread_mod


class LeaderStatus:
    def __init__(self, leader, owed: int, tagged: bool, confirmation=None, covered_by=None):
        self.leader = leader
        self.owed = owed                  # new starts assigned in OBCL
        self.tagged = tagged              # in Aisha's Saturday roll call
        self.confirmation = confirmation  # thread_mod.Confirmation | None
        self.covered_by = covered_by      # another Leader who sent on their behalf

    @property
    def sent(self) -> bool:
        return self.confirmation is not None or self.covered_by is not None

    @property
    def claimed(self) -> Optional[int]:
        return self.confirmation.claimed if self.confirmation else None

    @property
    def short(self) -> bool:
        """Said "sent x2" but OBCL gave them 4. Unqualified "Sent" is taken at
        face value -- most leaders with one new start just write "Sent"."""
        return self.sent and self.claimed is not None and self.owed > 0 and self.claimed < self.owed

    @property
    def label(self) -> str:
        return self.leader.short or self.leader.name

    def sort_key(self):
        return self.label.lower()


class Reconciliation:
    def __init__(self):
        self.monday = None            # type: Optional[dt.date]
        self.tab = ""
        self.statuses = []            # type: List[LeaderStatus]
        self.unmatched_obcl = {}      # type: Dict[str, int]  OBCL name -> count, no roster entry
        self.tagged_unknown = []      # type: List[str]       Slack id tagged, not in roster
        self.thread = None            # type: Optional[dict]

    @property
    def sent(self) -> List[LeaderStatus]:
        return sorted([s for s in self.statuses if s.sent], key=LeaderStatus.sort_key)

    @property
    def pending(self) -> List[LeaderStatus]:
        return sorted([s for s in self.statuses if not s.sent], key=LeaderStatus.sort_key)

    @property
    def short(self) -> List[LeaderStatus]:
        return sorted([s for s in self.statuses if s.short], key=LeaderStatus.sort_key)

    @property
    def has_roll_call(self) -> bool:
        return bool(self.thread and self.thread.get("roll_call_ts"))

    @property
    def untagged(self) -> List[LeaderStatus]:
        """Owed new starts but never made it into the roll call.

        Meaningless before a roll call exists (everyone would be "untagged"),
        so it stays empty until one is up.
        """
        if not self.has_roll_call:
            return []
        return sorted([s for s in self.statuses if s.owed and not s.tagged],
                      key=LeaderStatus.sort_key)

    @property
    def owing(self) -> List[LeaderStatus]:
        """Everyone the roll call should tag: has at least one new start."""
        return sorted([s for s in self.statuses if s.owed], key=LeaderStatus.sort_key)


def build(monday: Optional[dt.date] = None, friday: Optional[dt.date] = None,
          client=None) -> Reconciliation:
    ros = roster_mod.load()
    monday, tab, starts = obcl.read_new_starts(monday)
    owed = obcl.counts_by_interviewer(starts)

    if friday is None:
        friday = monday - dt.timedelta(days=3)
    th = thread_mod.read_thread(friday=friday, client=client)

    rec = Reconciliation()
    rec.monday = monday
    rec.tab = tab
    rec.thread = th

    owed_by_id = {}  # type: Dict[str, int]
    for name, count in owed.items():
        leader = ros.by_obcl_name(name)
        if leader is None:
            rec.unmatched_obcl[name] = rec.unmatched_obcl.get(name, 0) + count
            continue
        owed_by_id[leader.slack_id] = owed_by_id.get(leader.slack_id, 0) + count

    covered = _covers(th["confirmations"], ros)

    # Every leader who either owes a text or was tagged gets a row.
    ids = set(owed_by_id) | set(th["tagged"])
    for sid in ids:
        leader = ros.by_id(sid)
        if leader is None:
            rec.tagged_unknown.append(sid)
            continue
        rec.statuses.append(
            LeaderStatus(
                leader=leader,
                owed=owed_by_id.get(sid, 0),
                tagged=sid in th["tagged"],
                confirmation=th["confirmations"].get(sid),
                covered_by=covered.get(sid),
            )
        )
    return rec


def _covers(confirmations, ros) -> Dict[str, object]:
    """Credit a leader when someone else sent for them.

    Raf's one-off: Sosa was in the hospital, so Juan replied "Sent (Sosa)".
    A parenthetical that resolves to another leader is read as cover, so the
    covered leader doesn't get nudged for a text that already went out.
    """
    import re

    out = {}  # type: Dict[str, object]
    for sender_id, conf in confirmations.items():
        for name in re.findall(r"\(([^)]{2,40})\)", conf.text):
            other = ros.by_obcl_name(name)
            if other is not None and other.slack_id != sender_id:
                out[other.slack_id] = ros.by_id(sender_id)
    return out


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_rollcall(rec: Reconciliation) -> str:
    """Saturday 8am roll call — Lucy's replacement for Aisha's hand-typed tags.

    Built from OBCL column B, so it's complete by construction. Each leader is
    tagged WITH their new-start count, which is what makes a later "Sent x2"
    against 3 owed obvious to everyone in the thread rather than something only
    this report notices.
    """
    from automations.new_start_followup import thread as thread_mod

    owing = rec.owing
    if not owing:
        return ""

    total = sum(s.owed for s in owing)
    lines = [
        "📣 *{}* — week of {}/{}".format(
            thread_mod.ROLLCALL_MARKER, rec.monday.month, rec.monday.day),
        "*{} new start{}* across *{} leader{}*. Please text yours today and "
        "reply *Sent* below.".format(
            total, "" if total == 1 else "s",
            len(owing), "" if len(owing) == 1 else "s"),
        "",
    ]
    for s in owing:
        lines.append("{}  —  {} new start{}".format(
            s.leader.mention, s.owed, "" if s.owed == 1 else "s"))

    lines.append("")
    lines.append("_Reply *Sent* (or *Sent x{}*) once you're done · "
                 "auto by Lucy from the OBCL sheet_".format(max(s.owed for s in owing)))

    # No follow-through flags at 8am -- nobody has sent yet. But anyone we
    # couldn't tag goes in, so their new start doesn't fall through.
    for line in _untaggable_lines(rec):
        lines.append(line)
    return "\n".join(lines)


def render_nudge(rec: Reconciliation, when: str) -> str:
    """Saturday reminder. Tags ONLY the people who still haven't replied, so
    the leaders who already sent theirs stop getting pinged."""
    pending = rec.pending
    if not pending:
        return ""
    tags = " ".join(s.leader.mention for s in pending)
    headline = {
        "morning": "Reminder — if you haven't texted your new starts yet, please send it now.",
        "midday": "Second reminder — please text your new starts and reply *Sent* here.",
        "evening": "Last call for today — please text your new starts before the day ends.",
    }.get(when, "Reminder — please text your new starts and reply *Sent* here.")

    lines = [
        "⏰ *New-Start Texts — {} still to go*".format(len(pending)),
        headline,
        "",
        tags,
        "",
        "_Reply *Sent* (or *Sent x3*) in this thread once you're done · auto by Lucy_",
    ]
    return "\n".join(lines)


def render_checklist(rec: Reconciliation) -> str:
    """Sunday roll-up — Raf's numbered ✅ list, rebuilt automatically."""
    statuses = sorted(rec.statuses, key=LeaderStatus.sort_key)
    total = len(statuses)
    done = len(rec.sent)

    lines = [
        # Built by hand, not strftime -- %-m/%-d is glibc-only and this has to
        # run on Windows too.
        "📋 *New-Start Texts — week of {}/{}*".format(rec.monday.month, rec.monday.day),
        "*{} of {} leaders have sent*".format(done, total),
        "",
    ]
    for i, s in enumerate(statuses, 1):
        mark = " ✅" if s.sent else ""
        detail = []
        if s.owed:
            detail.append("{} new start{}".format(s.owed, "" if s.owed == 1 else "s"))
        if s.covered_by is not None:
            detail.append("sent by {}".format(s.covered_by.short or s.covered_by.name))
        if s.short:
            detail.append("said *x{}*".format(s.claimed))
        tail = "  _({})_".format(", ".join(detail)) if detail else ""
        lines.append("{}. {}{}{}".format(i, s.label, mark, tail))

    pending = rec.pending
    if pending:
        lines.append("")
        lines.append("*Still need to send ({})*".format(len(pending)))
        lines.append(" ".join(s.leader.mention for s in pending))

    for line in _team_flags(rec):
        lines.append(line)
    # Still unaccounted for on Sunday, so it carries through to the roll-up.
    for line in _untaggable_lines(rec):
        lines.append(line)

    lines.append("")
    lines.append("_auto by Lucy · source: OBCL tab '{}'_".format(rec.tab))
    return "\n".join(lines)


def _untaggable_lines(rec: Reconciliation) -> List[str]:
    """Interviewers with new starts that we can't @-mention.

    Raf's call: this belongs IN the post, not the log. If nobody can tag
    Amberly, her new start silently goes untexted -- somebody reading the
    thread has to know to chase her another way.
    """
    if not rec.unmatched_obcl:
        return []
    out = ["", "⚠️ *Unable to tag — needs a manual reach-out*"]
    for name in sorted(rec.unmatched_obcl):
        count = rec.unmatched_obcl[name]
        out.append("   •  {} — {} new start{}".format(
            name, count, "" if count == 1 else "s"))
    return out


def _team_flags(rec: Reconciliation) -> List[str]:
    """Flags that belong in the Slack post — they're about people's follow-through
    and the team should see them."""
    out = []  # type: List[str]
    if rec.short:
        out.append("")
        out.append("⚠️ *Count looks short vs OBCL*")
        for s in rec.short:
            out.append("   •  {} — said *x{}*, OBCL shows *{}*".format(
                s.label, s.claimed, s.owed))
    if rec.untagged:
        out.append("")
        out.append("⚠️ *Has new starts but wasn't tagged*")
        for s in rec.untagged:
            out.append("   •  {} — {} new start{}".format(
                s.label, s.owed, "" if s.owed == 1 else "s"))
    return out


def ops_flags(rec: Reconciliation) -> List[str]:
    """Plumbing problems — console/log only, never posted.

    "Amberly Chum has no Slack match" is a note for whoever maintains
    leaders.json, not something to tag into a channel of 20 leaders.
    """
    out = []  # type: List[str]
    if rec.unmatched_obcl:
        out.append("In OBCL but no Slack match — add them to leaders.json:")
        for name in sorted(rec.unmatched_obcl):
            out.append("   •  {} — {} new start{}".format(
                name, rec.unmatched_obcl[name],
                "" if rec.unmatched_obcl[name] == 1 else "s"))
    if rec.tagged_unknown:
        out.append("Tagged in the thread but not in leaders.json:")
        for sid in sorted(rec.tagged_unknown):
            out.append("   •  {}".format(sid))
    return out


def render_text_list(rec: Reconciliation) -> str:
    """Plain-text console block: who to text, and their number if we have one."""
    lines = ["Leaders who have NOT sent ({}):".format(len(rec.pending))]
    for s in rec.pending:
        phone = s.leader.phone or "NO NUMBER ON FILE"
        lines.append("   {:<20} {}".format(s.label, phone))
    return "\n".join(lines)
