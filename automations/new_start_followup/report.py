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
import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.new_start_followup import (
    membership, obcl, roster as roster_mod, thread as thread_mod)


DEPARTED_NOTE = "No longer a channel member"

# Last roster taken off the weekly screenshot by a machine that can read it,
# used when THIS machine can't (the mini's Slack token has no files:read).
# Written by fix_rollcall.py --snapshot. Only ever used for its own week.
# One snapshot file per funnel (thread.FUNNELS names them); this constant stays
# as the main funnel's path because fix_rollcall imports it.
SNAPSHOT_PATH = Path(__file__).resolve().parent / "roster_snapshot.json"


def snapshot_path(funnel: dict) -> Path:
    return Path(__file__).resolve().parent / funnel["snapshot"]


class LeaderStatus:
    def __init__(self, leader, owed: int, tagged: bool, confirmation=None,
                 covered_by=None, departed: bool = False):
        self.leader = leader
        self.owed = owed                  # new starts assigned in OBCL
        self.tagged = tagged              # in Aisha's Saturday roll call
        self.confirmation = confirmation  # thread_mod.Confirmation | None
        self.covered_by = covered_by      # another Leader who sent on their behalf
        self.departed = departed          # left #rafs-office-recruiting

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
        self.tagged_no_starts = []    # type: List[str]       Slack id tagged, but owes nothing
        self.thread = None            # type: Optional[dict]

    @property
    def sent(self) -> List[LeaderStatus]:
        return sorted([s for s in self.statuses if s.sent], key=LeaderStatus.sort_key)

    @property
    def pending(self) -> List[LeaderStatus]:
        """Still owes a text AND is still reachable.

        Departed leaders are excluded everywhere `pending` is used -- nudge
        tags, the "still need to send" line, and the texts -- so a former
        employee is never pinged. They're surfaced under `departed` instead.
        """
        return sorted([s for s in self.statuses if not s.sent and not s.departed],
                      key=LeaderStatus.sort_key)

    @property
    def departed(self) -> List[LeaderStatus]:
        """Gone from the channel but still had new starts assigned in OBCL —
        somebody else has to cover those."""
        return sorted([s for s in self.statuses if s.departed and s.owed],
                      key=LeaderStatus.sort_key)

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
        # Departed leaders are untagged BY DESIGN -- reporting them here would
        # read as an oversight to fix. They're listed under `departed` instead.
        return sorted(
            [s for s in self.statuses if s.owed and not s.tagged and not s.departed],
            key=LeaderStatus.sort_key)

    @property
    def owing(self) -> List[LeaderStatus]:
        """Everyone the roll call should tag: has a new start and is still here."""
        return sorted([s for s in self.statuses if s.owed and not s.departed],
                      key=LeaderStatus.sort_key)


def build(monday: Optional[dt.date] = None, friday: Optional[dt.date] = None,
          client=None, allow_sheet_roster: bool = False,
          roster_json=None, funnel: Optional[dict] = None) -> Reconciliation:
    if funnel is None:
        funnel = thread_mod.FUNNELS[0]  # main funnel — the pre-8/24 behaviour
    poster = funnel["poster"]
    ros = roster_mod.load()
    if monday is None:
        monday = obcl.upcoming_monday()

    # A roster SNAPSHOT taken on a machine that can read the screenshot, so a
    # machine that can't (the mini, whose token has no files:read) still works
    # off the true list instead of the OBCL sheet. Written by
    # `fix_rollcall.py --snapshot`. Interviewer -> count only: new-start names
    # never go in, the repo is PUBLIC.
    if roster_json is not None:
        snap = json.loads(Path(roster_json).read_text(encoding="utf-8"))
        owed = {k: int(v) for k, v in (snap.get("owed") or {}).items()}
        if not owed:
            raise RuntimeError("Roster snapshot {} has no 'owed' counts.".format(roster_json))
        snap_monday = snap.get("monday")
        if snap_monday and snap_monday != monday.isoformat():
            raise RuntimeError(
                "Roster snapshot is for the week of {}, but this run is for {}. "
                "Re-take it with --snapshot.".format(snap_monday, monday.isoformat()))
        tab = snap.get("source") or "roster snapshot"
        print("[roster] snapshot {}: {} new starts across {} interviewers"
              .format(roster_json, sum(owed.values()), len(owed)))
        # Still cross-read the sheet: the snapshot is the screenshot's tag list,
        # and the needs-a-manual-reach-out names (Quigley Nolan) live only on the
        # sheet. Skipping this silently dropped him from the corrected roll call.
        return _assemble(monday, friday, client, ros, owed, tab,
                         _sheet_only_untaggable(monday, owed, ros)
                         if funnel["key"] == "main" else {},
                         poster=poster)

    # Roster source = Aisha's weekly SCREENSHOT (the true reach-out list), read
    # via Claude vision. The live OBCL tab carries people we're NOT moving forward
    # with + duplicate rows, so we no longer derive the roster from it (Raf
    # 2026-08-03).
    from automations.new_start_followup import screenshot_roster
    # The OBCL sheet cross-read only runs for the MAIN funnel: the sheet mixes
    # both funnels' rows, so checking it against one funnel's screenshot would
    # flag the OTHER funnel's people as needing a manual reach-out in the
    # wrong thread.
    tab = "{} screenshot".format("Aisha's" if funnel["key"] == "main"
                                 else "Tiffani's")
    sheet_only = {}  # type: Dict[str, int]
    try:
        rows = screenshot_roster.fetch_roster_rows(monday.isoformat(),
                                                   poster=poster)
        owed = {}
        for r in rows:
            intv = (r.get("interviewer") or "").strip()
            if intv:
                owed[intv] = owed.get(intv, 0) + 1
        print("[roster] {}: {} new starts across {} interviewers"
              .format(tab, sum(owed.values()), len(owed)))
        if funnel["key"] == "main":
            sheet_only = _sheet_only_untaggable(monday, owed, ros)
    except Exception as exc:  # noqa: BLE001
        # The OBCL sheet is NOT a safe stand-in for the screenshot: it holds
        # not-moving-forward + duplicate rows, so building a TAG list from it
        # @-mentions people who have no new start. That is exactly what happened
        # on 2026-08-08 -- the vision call 400'd ("Could not process image"), the
        # report silently fell back, and Bill Hirwa was tagged for OBCL row 12
        # (Arnold Smith), a row Aisha's screenshot doesn't carry. Megan: "you
        # tagged Bill but he doesn't have anyone in the screenshot posted."
        #
        # Aisha posts the screenshot Friday afternoon (16:56 that week, 15h
        # before the 8am roll call), so a missing one means the READ broke, not
        # that she's late. Refusing is cheap: the roll call is idempotent on its
        # own marker, so the next scheduled pass posts it once the read works.
        # A snapshot for THIS week is the screenshot's own data, just taken
        # elsewhere — so it's a real answer, not a guess like the sheet. Lets the
        # weekend keep running on a machine that can't do the file download.
        snap_owed = _snapshot_for(monday, snapshot_path(funnel))
        if snap_owed:
            print("WARNING: screenshot roster unavailable ({}); using the roster "
                  "snapshot for {} instead ({} new starts across {} interviewers)."
                  .format(exc, monday.isoformat(), sum(snap_owed.values()),
                          len(snap_owed)))
            return _assemble(monday, friday, client, ros, snap_owed,
                             tab + " (snapshot)",
                             _sheet_only_untaggable(monday, snap_owed, ros)
                             if funnel["key"] == "main" else {},
                             poster=poster)
        if not allow_sheet_roster:
            raise RuntimeError(
                "Couldn't read the {} roster screenshot ({}). Refusing to build "
                "the roll call from the OBCL sheet -- it carries not-moving-"
                "forward and duplicate rows, so it tags leaders who have no new "
                "start. Nothing was posted; the next scheduled pass will post it "
                "once the screenshot reads. To override anyway, re-run with "
                "--allow-sheet-roster.".format(funnel["label"], exc))
        print("WARNING: screenshot roster unavailable ({}); --allow-sheet-roster "
              "given, so falling back to the OBCL sheet. Counts and tags may "
              "include rows Aisha's screenshot excludes -- CHECK BEFORE POSTING."
              .format(exc))
        monday, tab, starts = obcl.read_new_starts(monday)
        owed = obcl.counts_by_interviewer(starts)

    return _assemble(monday, friday, client, ros, owed, tab, sheet_only,
                     poster=poster)


def _assemble(monday, friday, client, ros, owed, tab, sheet_only,
              poster=None) -> Reconciliation:
    """Join the chosen roster against the thread. Shared by every roster source
    so they can't drift apart."""
    if friday is None:
        friday = monday - dt.timedelta(days=3)
    th = thread_mod.read_thread(friday=friday, client=client, poster=poster)

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

    # Sheet-only interviewers nobody can @-mention. Never tagged, never nudged --
    # they only ever reach the "needs a manual reach-out" list.
    for name, count in sheet_only.items():
        rec.unmatched_obcl[name] = rec.unmatched_obcl.get(name, 0) + count

    covered = _covers(th["confirmations"], ros)

    # Former employees: never tag them, never text them.
    try:
        gone = membership.departed_ids(client=client)
    except Exception as exc:  # noqa: BLE001
        # A membership read failing must not take the whole report down --
        # worst case we tag someone who left, which is what we do today.
        print("WARNING: couldn't read channel membership ({}). "
              "Treating everyone as active.".format(exc))
        gone = set()

    # A leader gets a row if they OWE a text or they replied "Sent" — a leader
    # who confirms is always credited, even if their name never matched a roster
    # row that week (Raf: some 'Sent' replies weren't caught).
    #
    # Being TAGGED is deliberately not enough. The roll call is Lucy's own post,
    # so feeding its mentions back in makes a bad tag self-sustaining: on
    # 2026-08-08 the 8am roll call ran off the sheet fallback and tagged Bill
    # Hirwa, Anthony Coca and Pranish Shrestha, none of whom had a new start —
    # and every later pass would have re-tagged them off that same post.
    ids = set(owed_by_id) | set(th["confirmations"])
    for sid in th["tagged"]:
        leader = ros.by_id(sid)
        if leader is None:
            if sid not in rec.tagged_unknown:
                rec.tagged_unknown.append(sid)
        elif sid not in ids:
            rec.tagged_no_starts.append(leader.name)
    for sid in ids:
        leader = ros.by_id(sid)
        if leader is None:
            if sid not in rec.tagged_unknown:
                rec.tagged_unknown.append(sid)
            continue
        rec.statuses.append(
            LeaderStatus(
                leader=leader,
                owed=owed_by_id.get(sid, 0),
                tagged=sid in th["tagged"],
                confirmation=th["confirmations"].get(sid),
                covered_by=covered.get(sid),
                departed=sid in gone,
            )
        )
    return rec


def _snapshot_for(monday: dt.date, path: Path = SNAPSHOT_PATH) -> Dict[str, int]:
    """The roster snapshot, but ONLY if it's for `monday`. {} otherwise.

    Week-matched on purpose: last week's snapshot would tag last week's leaders
    about last week's new starts, which is worse than not posting.
    """
    try:
        if not path.exists():
            return {}
        snap = json.loads(path.read_text(encoding="utf-8"))
        if snap.get("monday") != monday.isoformat():
            print("[roster] ignoring the snapshot — it's for the week of {}, "
                  "not {}.".format(snap.get("monday"), monday.isoformat()))
            return {}
        return {k: int(v) for k, v in (snap.get("owed") or {}).items()}
    except Exception as exc:  # noqa: BLE001
        print("[roster] couldn't read the snapshot ({}).".format(exc))
        return {}


def _sheet_only_untaggable(monday: dt.date, owed: Dict[str, int],
                           ros) -> Dict[str, int]:
    """OBCL-sheet interviewers who are missing from the screenshot AND can't be
    @-mentioned -> name -> new-start count.

    Aisha's screenshot is a picture of one moment. A row added to the OBCL sheet
    afterwards isn't in it -- Megan's case (2026-08-08): she added Quigley Nolan,
    who is no longer with us, so there's nobody to tag and someone has to reach
    out by hand. Without this the row vanishes between the screenshot and the
    Sunday roll-up, and that new start goes untexted with nobody told.

    Deliberately narrow, so Raf's 2026-08-03 call still holds:
      - anyone the screenshot already lists is skipped (it owns the counts)
      - anyone who DOES resolve to a roster leader is skipped, so a sheet row the
        screenshot dropped can never turn back into an @-mention
    What's left is only ever a name in the manual-reach-out list.
    """
    try:
        _, _, starts = obcl.read_new_starts(monday)
    except Exception as exc:  # noqa: BLE001 — advisory: never fail the report
        print("WARNING: couldn't cross-check the OBCL sheet ({}); interviewers "
              "on the sheet but not the screenshot won't be flagged.".format(exc))
        return {}

    seen = set(roster_mod._norm(n) for n in owed)
    out = {}  # type: Dict[str, int]
    for name, count in obcl.counts_by_interviewer(starts).items():
        key = roster_mod._norm(name)
        if not key or key in seen:
            continue
        if ros.by_obcl_name(name) is not None:
            continue
        out[name] = count
        seen.add(key)
    if out:
        print("[roster] on the OBCL sheet but not the screenshot, and not "
              "taggable: {}".format(", ".join(sorted(out))))
    return out


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

def render_rollcall(rec: Reconciliation, tag: bool = True) -> str:
    """Saturday 8am roll call — Lucy's replacement for Aisha's hand-typed tags.

    Built from OBCL column B, so it's complete by construction. Each leader is
    tagged WITH their new-start count, which is what makes a later "Sent x2"
    against 3 owed obvious to everyone in the thread rather than something only
    this report notices.

    tag=False posts plain names instead of @-mentions — for a thread whose
    recruiter already hand-tagged everyone (Tiffani), so the counts and the
    marker land without pinging the same people twice (Megan 2026-08-22).
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
            s.leader.mention if tag else s.label,
            s.owed, "" if s.owed == 1 else "s"))

    lines.append("")
    lines.append("_Reply *Sent* (or *Sent x{}*) once you're done · "
                 "auto by Lucy from the OBCL sheet_".format(max(s.owed for s in owing)))

    # No follow-through flags at 8am -- nobody has sent yet. But anyone we
    # couldn't tag goes in, so their new start doesn't fall through.
    for line in _departed_lines(rec):
        lines.append(line)
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
    # Former employees don't count against the score -- they can't send.
    active = [s for s in statuses if not s.departed]
    done = len(rec.sent)

    lines = [
        # Built by hand, not strftime -- %-m/%-d is glibc-only and this has to
        # run on Windows too.
        "📋 *New-Start Texts — week of {}/{}*".format(rec.monday.month, rec.monday.day),
        "*{} of {} leaders have sent*".format(done, len(active)),
        "",
    ]
    for i, s in enumerate(statuses, 1):
        mark = " ✅" if s.sent else ""
        detail = []
        if s.owed:
            detail.append("{} new start{}".format(s.owed, "" if s.owed == 1 else "s"))
        if s.departed:
            detail.append(DEPARTED_NOTE)
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
    # Still unaccounted for on Sunday, so these carry through to the roll-up.
    for line in _departed_lines(rec):
        lines.append(line)
    for line in _untaggable_lines(rec):
        lines.append(line)

    lines.append("")
    # Only a real OBCL tab title gets the "OBCL tab" prefix; the screenshot and
    # its snapshot already read as a source ("Aisha's screenshot (snapshot)").
    src = (rec.tab if "screenshot" in rec.tab
           else "OBCL tab '{}'".format(rec.tab))
    lines.append("_auto by Lucy · source: {}_".format(src))
    return "\n".join(lines)


def _departed_lines(rec: Reconciliation) -> List[str]:
    """Leaders who left the channel but still have new starts on the sheet.

    Named, not tagged -- the @-mention is the whole thing we're avoiding. Their
    new starts still need somebody, so this has to be visible in the post.
    """
    if not rec.departed:
        return []
    out = ["", "⚠️ *{}* — someone else needs to cover these".format(DEPARTED_NOTE)]
    for s in rec.departed:
        out.append("   •  {} — {} new start{}".format(
            s.leader.name, s.owed, "" if s.owed == 1 else "s"))
    return out


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
    if rec.tagged_no_starts:
        # A MIS-TAG: the roll call pinged them for a new start the roster doesn't
        # give them. They're dropped from the nudge and the checklist rather than
        # chased -- but it stays visible here, because a mis-tag means the roll
        # call ran on the wrong roster (see the sheet-fallback guard in build()).
        out.append("Tagged in the roll call but has NO new starts this week — "
                   "mis-tagged, and dropped from the nudge/checklist:")
        for name in sorted(rec.tagged_no_starts):
            out.append("   •  {}".format(name))
    return out


def render_text_list(rec: Reconciliation) -> str:
    """Plain-text console block: who to text, and their number if we have one."""
    from automations.swag_welcome.roster import pretty_phone

    lines = ["Leaders who have NOT sent ({}):".format(len(rec.pending))]
    for s in rec.pending:
        phone = pretty_phone(s.leader.phone) or "NO NUMBER — can't text"
        lines.append("   {:<20} {}".format(s.label, phone))
    return "\n".join(lines)
