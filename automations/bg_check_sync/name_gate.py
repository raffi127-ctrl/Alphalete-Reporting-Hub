"""The legal-name gate: Sterling's name is the real one, the OBCL's may be a nickname.

WHY THIS EXISTS (Eve's Loom + Megan, 2026-08-26). An applicant types their LEGAL
name into Sterling. The recruiter types whatever the applicant said in the
interview into the OBCL — for one girl that was "Nikki", and her legal name is
Shomanique. Three systems then hold three spellings: Sterling has the legal one,
OwnerVille has whatever was typed when the profile was made, and the OBCL has
the nickname. The BG result email says "Coleman, Shomanique", the sheet row says
"Nikki Coleman", nothing matches, her col K never fills, and somebody ends up
emailing activations to get the name fixed by hand. Raf wants that loop closed:
Sterling is the source of truth, OwnerVille must match it exactly, and the OBCL
gets updated to the legal name.

WHAT THIS MODULE DOES. Finds the pairs (a roster person nobody's email matched +
a Sterling result nobody's row matched), and asks a human before touching
anything.

WHY A HUMAN GATE AND NOT A RENAME (Megan 2026-08-26). The only join we have is
the surname. Sterling result emails carry a name and nothing else — no candidate
email, no DOB (verified; see the name-collision note in the project memory) — so
"Nikki Coleman is Shomanique Coleman" is an inference, not a fact. Getting it
wrong is not a typo: it staples one person's background check onto another
person's row, which is the exact failure mode the whole compliance rule in
parse.py exists to prevent. So a proposal is POSTED, not applied:

    ✅ by Tiff / Alisson / Aimee  -> we rename the OBCL row (and say so)
    ❌                            -> we never ask again, and we flag it loudly:
                                     that BG check is lined up with the WRONG
                                     applicant and needs a human to unpick it
    no reaction                   -> nothing happens, ever. Silence is not
                                     consent when the write is somebody's name.

That default is the opposite of fiber_owners_distro's gate (where no reaction
means "remove"), and deliberately so — there the un-acted default undoes a
mailing list, here it would rewrite a person's identity on the onboarding sheet.

OWNERVILLE. Megan wants the OV profile to match exactly too. Renaming a rep in
OV is a browser job on the p=201 rep table -> profile page, which this report
(headless, 3x a day, no OV session) cannot do yet. Until that lands, every
approved rename names the OV edit in the confirmation reply so the person who
just ✅'d can do it in the same minute they're already looking at the row —
rather than the automation silently leaving OV wrong and nobody knowing.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from automations.bg_check_sync import parse, slack_post
from automations.bg_check_sync.match import (_name_tokens, _norm_key, _subset,
                                             best_event)
from automations.bg_check_sync.parse import BGEvent, norm
from automations.shared.name_case import titlecase_name

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "output" / "bg_name_gate_state.json"

APPROVE_EMOJI = "white_check_mark"   # ✅ yes, same person — rename
REJECT_EMOJI = "x"                   # ❌ no — wrong applicant

# Onboarding owns the sheet, so onboarding answers this. Same three people
# digi_docs escalates to, same ids, confirmed in this channel 2026-08-26.
DECIDERS = (
    ("Alisson", "U0BBG374GE9"),    # Alisson Rodriguez
    ("Tiff", "U0B9924FHCL"),       # Tiffani Brown
    ("Aimee", "U0APVP29QSD"),      # Aimee Garibay
)
DECIDER_IDS = {uid for _, uid in DECIDERS}

# HOW FAR BACK A RESULT CAN BE AND STILL BE THEIRS (Megan 2026-08-26). The check
# link goes out the moment somebody is HIRED, and a new start can be scheduled a
# month or more out -- so "taken five weeks before their start week" is a normal
# hire, not a stale result from an older cohort. The first version of this
# assumed reps were checked the week before they start and cut off at 28 days,
# which would have dropped exactly those month-out hires. The window is wide
# enough for a long runway now; the timing still gets SHOWN, it just no longer
# throws anything away for being early.
LOOKBACK_DAYS = 120

# The other end. Results come back PASSED after somebody has already started
# (Megan 2026-08-26) — Sterling takes as long as it takes, and a rep who started
# Monday can clear the following month. An event dated after the start week is
# therefore completely ordinary and must not be dropped; the real guard against
# pairing somebody else's result is claimed_anywhere(), not this window.
FORWARD_DAYS = 60

# What "the timing agrees" means: taken inside a normal hiring runway before
# their start, or shortly after it (a link that went out late). Outside that the
# line says so and the question sorts lower — it never throws the pair away.
NORMAL_RUNWAY_DAYS = 90
AFTER_START_GRACE = 30

# The sheet columns the rename touches. Names are D (first) / E (last); K is the
# status this report already owns.
FIRST_COL_A1 = "D"
LAST_COL_A1 = "E"

# A row that already shows Passed/Failed under a nickname is NOT excluded — it is
# the most common shape of the real thing. The live example is row 175 of the
# rolling tab: "Nikki Valentine", email Shuminiquevalentine@yahoo.com, col K
# "Passed". Somebody typed that status in by hand because the Sterling result
# came back under the legal name and never matched the row. Skipping her would
# have skipped the case this was built for. The status rides along in the
# question instead, so whoever answers can see it.
TERMINAL = {parse.PASSED, parse.FAILED, parse.UNPERFORMABLE}


@dataclass
class Proposal:
    """One 'these two are the same person' question, and its answer."""
    pid: str                       # stable id: week + both normalized names
    week: str                      # M/D/YYYY of the start week
    sheet_first: str
    sheet_last: str
    legal_first: str
    legal_last: str
    key: str                       # the roster person's key, to patch in place
    locations: list = field(default_factory=list)   # [(tab, row1)]
    evidence: str = ""             # the Sterling subject that drives it
    evidence_date: str = ""
    current: str = ""              # what col K says today, for the reader
    email: str = ""                # col G — the reader's fastest tiebreak
    corroborated: bool = False     # does that email back the Sterling name?
    taken_on: str = ""             # ISO date the applicant TOOK the check
    result_on: str = ""            # ISO date the result we're quoting landed
    days_before_start: Optional[int] = None   # negative = taken after they started
    fresh: bool = False            # does the timing fit this start week?

    def as_entry(self) -> dict:
        """The shape apply_renames writes from."""
        return {"pid": self.pid,
                "sheet_first": self.sheet_first, "sheet_last": self.sheet_last,
                "legal_first": self.legal_first, "legal_last": self.legal_last,
                "key": self.key, "locations": [tuple(l) for l in self.locations]}

    @property
    def signals(self) -> int:
        """How many of the two independent checks agree. Sorts the questions."""
        return int(self.corroborated) + int(self.fresh)

    @property
    def sheet_name(self) -> str:
        return f"{self.sheet_first} {self.sheet_last}".strip()

    @property
    def legal_name(self) -> str:
        return f"{self.legal_first} {self.legal_last}".strip()


def _pid(week: str, person, event: BGEvent) -> str:
    return "|".join([week, _norm_key(person.first, person.last),
                     _norm_key(event.first, event.last)])


def _local_part(email: str) -> str:
    """The address, lowercased, stripped to letters and digits, before the @."""
    return re.sub(r"[^a-z0-9]", "", (email or "").split("@")[0].lower())


def backed_by_email(email: str, legal_first: str) -> bool:
    """Does the candidate's OWN address carry the Sterling first name?

    Shuminiquevalentine@yahoo.com does; Tavavasquez.81@gmail.com does on the
    4-letter stem (Tavaiesha -> 'tava'); Angiep8k@gmail.com does not carry
    'Gabriel' and jmgarcia.mini@gmail.com does not carry 'Robert'.

    ADVISORY, NEVER A FILTER. A real applicant can absolutely use their nickname
    in their address -- there is a Lanequa Simpson on this very sheet at
    nikki.creative@zohomail.com -- so a miss here means "no help", not "not the
    same person". It only decides what the question is LABELLED and which order
    the questions are asked in.
    """
    local = _local_part(email)
    stem = re.sub(r"[^a-z0-9]", "", (legal_first or "").lower())[:4]
    return bool(local and len(stem) >= 3 and stem in local)


def taken_date(group: list) -> Optional[dt.date]:
    """When the check was TAKEN — the earliest message in the group.

    Sterling's first email for a person is the E-Invite ("...is Complete" =
    they took it); the score follows minutes or days later. The earliest date is
    therefore the moment that actually locates them in time, and the score
    email's date only says when the lab finished.
    """
    dates = [d for d in (_event_date(e) for e in group) if d is not None]
    return min(dates) if dates else None


def _event_date(e: BGEvent) -> Optional[dt.date]:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", e.date or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def claimed_anywhere(rolling_vals: list, events: list[BGEvent]) -> set:
    """ids of every event that belongs to SOMEBODY on the checklist — any week.

    Without this the pairing is week-blind, and the first live dry run showed
    exactly what that costs: Sterling's "Rios Rivera, Carlos Esteban" is Carlos
    Rivera, who starts 9/7. Looking only at the 8/24 cohort, that result had no
    owner and Alex Rivera had no email, so the gate offered them to each other.
    The rolling tab holds every week in one read we have already paid for, so
    the check is free — and an event with a rightful owner elsewhere is never a
    nickname for someone here."""
    from automations.bg_check_sync import match as _match
    everyone = _match.consolidate(_match.roster_blocks_in_window(
        rolling_vals, dt.date.min, dt.date.max, "D2D OBCL"))
    owned = _match.match_events_to_people(everyone, events)
    return {id(e) for evs in owned.values() for e in evs}


def propose(roster: list, events: list[BGEvent], matched: dict,
            monday: dt.date, week: str,
            claimed_ids: Optional[set] = None) -> list[Proposal]:
    """The pairing. Pure — no Slack, no sheet, no state.

    A proposal needs BOTH sides to be orphans and the surname to line up:
      * the roster person matched NO email at all (a matched person is already
        understood; a nickname that matched is not a nickname), and
      * the Sterling result was claimed by NOBODY on the whole checklist — not
        this week's roster and not any other week's (see claimed_anywhere), and
      * the surnames are token-compatible ('Coleman' == 'Coleman', and the same
        compound-surname allowance the normal matcher makes), and
      * the first names actually DIFFER (equal firsts is a matcher bug, not a
        nickname), and
      * within this week, exactly ONE orphan person and ONE orphan NAME carry
        that surname. Two of either and we cannot tell which is which, so we ask
        nothing — a question that invites a guess is worse than no question.

    "One orphan NAME", not one orphan email: Sterling sends several messages per
    check (the E-Invite, then the score), so the real Shuminique Valentine
    arrives as two events under one name. Counting events instead of people
    made her look ambiguous and asked nothing — which is how the first pass
    missed the very row (rolling 175 / 8.24 tab 25, "Pending (Name Issue)")
    that a human had already given up on and typed a note into.
    """
    claimed = {id(e) for evs in matched.values() for e in evs}
    claimed |= (claimed_ids or set())
    orphan_people = [p for p in roster if not matched.get(p.key)]
    window_start = monday - dt.timedelta(days=LOOKBACK_DAYS)
    window_end = monday + dt.timedelta(days=FORWARD_DAYS)

    orphan_events = []
    for e in events:
        if id(e) in claimed:
            continue
        d = _event_date(e)
        if d is not None and not (window_start <= d <= window_end):
            continue
        orphan_events.append(e)

    out: list[Proposal] = []
    for p in orphan_people:
        p_last = _name_tokens(p.last)
        hits: dict[str, list] = {}
        for e in orphan_events:
            if (_subset(p_last, _name_tokens(e.last))
                    and norm(p.first) != norm(e.first)):
                hits.setdefault(_norm_key(e.first, e.last), []).append(e)
        if len(hits) != 1:
            continue
        group = next(iter(hits.values()))
        # The most advanced message is the one worth quoting — "Score PASS"
        # tells the reader more than the invite that preceded it.
        e = best_event(group)
        # ...and the surname has to be unique on OUR side too, or we would be
        # offering one Sterling result to whichever namesake we happened to
        # iterate over first.
        rivals = [q for q in orphan_people
                  if _subset(_name_tokens(q.last), _name_tokens(e.last))]
        if len({q.key for q in rivals}) != 1:
            continue
        # Sterling shouts some names (TAVAIESHA VASQUEZ). The checklist is
        # title-cased like every other board we write, so fix the case once,
        # here, and let the question, the state file and the write all agree.
        legal_first = titlecase_name(e.first)
        legal_last = titlecase_name(e.last)
        taken = taken_date(group)
        gap = (monday - taken).days if taken else None
        out.append(Proposal(
            pid=_pid(week, p, e), week=week,
            sheet_first=p.first, sheet_last=p.last,
            legal_first=legal_first, legal_last=legal_last,
            key=p.key, locations=list(p.locations),
            evidence=e.subject, evidence_date=e.date,
            current=(p.current or "").strip(),
            email=getattr(p, "email", ""),
            corroborated=backed_by_email(getattr(p, "email", ""), legal_first),
            taken_on=taken.isoformat() if taken else "",
            result_on=(_event_date(e).isoformat() if _event_date(e) else ""),
            days_before_start=gap,
            fresh=(gap is not None
                   and -AFTER_START_GRACE <= gap <= NORMAL_RUNWAY_DAYS),
        ))
    # Most-agreeing first: the ones a reader can answer at a glance shouldn't be
    # buried under the ones that need thinking about.
    return sorted(out, key=lambda x: (-x.signals, x.sheet_last.lower()))


# --- state ------------------------------------------------------------------
# One file, keyed by pid, so the answer can arrive hours after the question and
# any of the day's three passes can act on it. A pid that reached 'applied' or
# 'rejected' is never asked again.

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def unanswered(proposals: list[Proposal], state: dict) -> list[Proposal]:
    """Proposals we have never posted. Anything already pending/applied/rejected
    is left alone — re-posting a pending question is how a channel learns to
    ignore the bot."""
    return [p for p in proposals if p.pid not in state]


# --- ask --------------------------------------------------------------------

def _client():
    """The xoxp USER token — Lucy on the mini. The bot token cannot post as Lucy
    and is not in this private room (reference_lucy_slack_tokens)."""
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def render_parent(n: int, start_week: Optional[str] = None) -> str:
    """The one message that explains the ask — so no person's line has to.

    Megan 2026-08-26, on the first version: "wayyyy too much wording and super
    confusing." Everything that is the same for every person lives here and is
    said once; a person's own line carries only what is different about them.
    """
    tags = " ".join(f"<@{uid}>" for _, uid in DECIDERS)
    head = "Name doesn't match their background check" if n == 1 else \
           f"{n} names don't match their background check"
    if start_week:
        head += f" — starting {start_week}"
    return (f"*{head}*\n"
            f"✅ = same person → I'll fix the checklist + OwnerVille\n"
            f"❌ = different person → I'll leave it alone\n"
            f"{tags}")


def render_line(p: Proposal) -> str:
    """One person, two lines: who Sterling ran, and the one fact that helps.

    The checklist name, an arrow, the Sterling name — that IS the question.
    Underneath it goes their email (the thing that settles most of these at a
    glance) and when they took the check. Nothing else: the ✅/❌ meanings are
    in the parent, and repeating them under every name is what made the first
    version unreadable.
    """
    bits = []
    if p.email:
        bits.append(f"{p.email}"
                    + (" — matches the Sterling name" if p.corroborated else ""))
    if p.taken_on:
        try:
            d = dt.date.fromisoformat(p.taken_on)
            bits.append(f"took the check {d:%b} {d.day}")
        except ValueError:
            pass
    if not p.fresh and p.days_before_start is not None:
        bits.append("timing is odd — worth a look")
    detail = "\n" + " · ".join(bits) if bits else ""
    return f"*{p.sheet_name}* → *{p.legal_name}*?{detail}"


def week_thread(week: str, channel: str) -> Optional[str]:
    """The BG status thread already open for `week` in `channel`, if any.

    The questions belong INSIDE that thread (Megan 2026-08-26, announcing this
    to the office: "she will post in the BG status update thread for that week").
    It is the post those three people already read every morning, and it keeps
    one week's business in one place instead of starting a second conversation
    beside it.
    """
    try:
        entry = slack_post._week_channels(slack_post._load_state(), week).get(channel)
    except Exception:  # noqa: BLE001
        return None
    return (entry or {}).get("parent_ts")


def _refresh_group(cli, channel: str, pending: list, group: list, intro: str,
                   state: dict) -> int:
    """Rewrite the text of questions already posted, leaving their reactions and
    their place in the thread alone."""
    by_pid = {p.pid: p for p in group}
    done = 0
    intro_ts = ""
    for proposal in pending:
        entry = state.get(proposal.pid) or {}
        intro_ts = intro_ts or entry.get("intro_ts", "")
        try:
            cli.chat_update(channel=channel, ts=entry["reply_ts"],
                            text=render_line(by_pid[proposal.pid]))
            done += 1
        except Exception as e:  # noqa: BLE001
            print(f"[name-gate] couldn't rewrite {proposal.sheet_name}: {e}")
    if intro_ts:
        try:
            cli.chat_update(channel=channel, ts=intro_ts, text=intro)
        except Exception as e:  # noqa: BLE001
            print(f"[name-gate] couldn't rewrite the intro: {e}")
    if done:
        print(f"[name-gate] rewrote {done} question(s) already in the thread")
    return done


def latest_thread(channel: str) -> tuple:
    """(week, parent_ts) of the most recent BG status thread in `channel`.

    Where a question goes when its OWN start week has no thread yet. Only the
    current and next week get threads, but a mismatch is found the day the check
    comes back — which for a month-out hire is weeks before their thread exists.
    Holding the question until then is the one thing that must not happen: the
    whole point is the admins seeing what's needed while there is still time to
    fix it (Megan 2026-08-26, "so we can get people onboarded asap").
    """
    try:
        state = slack_post._load_state()
    except Exception:  # noqa: BLE001
        return "", None
    best = ("", None, None)
    for week in state:
        d = _week_date(week)
        entry = slack_post._week_channels(state, week).get(channel) or {}
        ts = entry.get("parent_ts")
        if d and ts and (best[2] is None or d > best[2]):
            best = (week, ts, d)
    return best[0], best[1]


def _week_date(week: str):
    from automations.bg_check_sync import match as _match
    return _match.parse_header_date(week)


def post_proposals(proposals: list[Proposal], state: dict, *, dry_run: bool = True,
                   channel: Optional[str] = None) -> int:
    """Ask about each mismatch, as replies under that week's BG status thread.

    Falls back to its own parent message when the week has no thread yet (a
    brand-new week whose roster post hasn't gone out). dry_run prints the exact
    text and writes no state — the standing "ask before any Slack post" rule
    means this report never surprises the channel.
    """
    if not proposals:
        return 0
    channel = channel or slack_post.CHANNEL_IDS[0]
    by_week: dict[str, list[Proposal]] = {}
    for p in proposals:
        by_week.setdefault(p.week, []).append(p)

    posted = 0
    for week, group in by_week.items():
        parent_ts = week_thread(week, channel)
        host_week = week
        if not parent_ts:
            host_week, parent_ts = latest_thread(channel)
        # Say whose week it is when the question is riding in another week's
        # thread, so nobody reads it as this week's problem.
        elsewhere = bool(parent_ts) and host_week != week
        intro = render_parent(len(group), start_week=week if elsewhere else None)
        if dry_run:
            where = (f"the {host_week} BG status thread ({parent_ts})" if parent_ts
                     else f"{channel} as a new thread")
            print(f"[name-gate] (dry-run) would post in {where}:")
            print("  " + intro.replace("\n", "\n  "))
            for p in group:
                print("  ↳ " + render_line(p).replace("\n", "\n    "))
            continue

        cli = _client()
        pending = [p for p in group
                   if (state.get(p.pid) or {}).get("status") == "pending"
                   and (state.get(p.pid) or {}).get("reply_ts")]
        if pending:
            # Already asked. Correct the wording in place — a second copy of the
            # same question is how a channel ends up with two answers.
            refreshed = _refresh_group(cli, channel, pending, group, intro, state)
            posted += refreshed
            continue
        if parent_ts:
            intro_ts = cli.chat_postMessage(
                channel=channel, thread_ts=parent_ts, text=intro)["ts"]
        else:
            parent_ts = cli.chat_postMessage(channel=channel, text=intro)["ts"]
            intro_ts = parent_ts
        now = dt.datetime.now().isoformat(timespec="seconds")
        for p in group:
            reply = cli.chat_postMessage(channel=channel, thread_ts=parent_ts,
                                         text=render_line(p))
            # No seeded ✅/❌: the poster is Lucy and a pre-filled reaction both
            # reads as a decision already taken and would have to be excluded
            # from the count. They tap their own.
            state[p.pid] = {
                "status": "pending", "channel": channel,
                "parent_ts": parent_ts, "reply_ts": reply["ts"],
                "asked_at": now, "week": p.week,
                "sheet_first": p.sheet_first, "sheet_last": p.sheet_last,
                "legal_first": p.legal_first, "legal_last": p.legal_last,
                "key": p.key, "locations": [list(l) for l in p.locations],
                "evidence": p.evidence, "intro_ts": intro_ts,
            }
            posted += 1
    if posted:
        print(f"[name-gate] asked about {posted} name mismatch(es) in {channel}")
    return posted


# --- read the answer --------------------------------------------------------

def _thread_reactions(cli, channel: str, parent_ts: str) -> dict:
    """{ts: [reaction dicts]} for one thread. conversations_replies, not
    reactions.get — the token lacks that scope (same as the fiber gate)."""
    out: dict = {}
    try:
        for m in cli.conversations_replies(channel=channel, ts=parent_ts).get("messages", []):
            out[m["ts"]] = m.get("reactions") or []
    except Exception as e:  # noqa: BLE001
        print(f"[name-gate] could not read thread {parent_ts}: {e}")
    return out


def _voted(reactions: list, emoji: str) -> Optional[str]:
    """The first decider who reacted with `emoji`, or None. Anyone else's
    reaction is ignored — this is onboarding's call to make."""
    for r in reactions:
        if r.get("name") != emoji:
            continue
        who = DECIDER_IDS.intersection(r.get("users") or [])
        if who:
            return sorted(who)[0]
    return None


def collect_decisions(state: dict) -> tuple[list[dict], list[dict]]:
    """Read every pending proposal's reactions. Returns (approved, rejected) as
    the raw state entries, each stamped with pid/decided_by. ❌ wins over ✅: if
    the room disagrees, the answer that touches nobody's name is the safe one."""
    pending = {pid: e for pid, e in state.items() if e.get("status") == "pending"}
    if not pending:
        return [], []
    cli = _client()
    threads: dict = {}
    approved, rejected = [], []
    for pid, entry in pending.items():
        ch, parent = entry.get("channel"), entry.get("parent_ts")
        if not (ch and parent and entry.get("reply_ts")):
            continue
        key = (ch, parent)
        if key not in threads:
            threads[key] = _thread_reactions(cli, ch, parent)
        reactions = threads[key].get(entry["reply_ts"], [])
        no = _voted(reactions, REJECT_EMOJI)
        yes = _voted(reactions, APPROVE_EMOJI)
        if no:
            rejected.append({**entry, "pid": pid, "decided_by": no})
        elif yes:
            approved.append({**entry, "pid": pid, "decided_by": yes})
    return approved, rejected


# --- do it ------------------------------------------------------------------

def apply_renames(sh, approved: list[dict], state: dict, *,
                  dry_run: bool = True) -> list[dict]:
    """Write the legal name into cols D/E everywhere the person appears.

    Guarded read-before-write: a location is only touched if it STILL holds the
    nickname we asked about. Rows move (the rolling tab gets blocks inserted
    above them) and people edit the sheet by hand between the question and the
    answer — writing a name into whatever row happens to be at that index now is
    exactly the accident this whole gate exists to avoid.
    """
    from automations.recruiting_report import fill
    done = []
    for entry in approved:
        want_first = entry["legal_first"]
        want_last = entry["legal_last"]
        old_first = entry["sheet_first"]
        old_last = entry["sheet_last"]
        by_tab: dict[str, list] = {}
        skipped = []
        for tab, row in entry.get("locations", []):
            try:
                ws = sh.worksheet(tab)
                cur = fill._retry(ws.get, f"{FIRST_COL_A1}{row}:{LAST_COL_A1}{row}")
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{tab}!{row} ({e})")
                continue
            got = (cur[0] if cur else []) + ["", ""]
            if norm(got[0]) != norm(old_first) or norm(got[1]) != norm(old_last):
                now_name = f"{got[0]} {got[1]}".strip()
                skipped.append(f"{tab}!{row} (now '{now_name}')")
                continue
            by_tab.setdefault(tab, []).append(row)
        written = 0
        for tab, rows in by_tab.items():
            data = [{"range": f"{FIRST_COL_A1}{r}:{LAST_COL_A1}{r}",
                     "values": [[want_first, want_last]]} for r in rows]
            written += len(data)
            if not dry_run:
                fill._retry(sh.worksheet(tab).batch_update, data,
                            value_input_option="USER_ENTERED")
        verb = "would rename" if dry_run else "renamed"
        print(f"[name-gate] {verb} {old_first} {old_last} -> {want_first} {want_last} "
              f"in {written} row(s)" + (f"; skipped {', '.join(skipped)}" if skipped else ""))
        if not dry_run:
            state[entry["pid"]] = {**state.get(entry["pid"], {}), **{
                "status": "applied",
                "decided_by": entry.get("decided_by"),
                "applied_at": dt.datetime.now().isoformat(timespec="seconds"),
                "rows_written": written,
                "skipped": skipped,
            }}
        done.append({**entry, "rows_written": written, "skipped": skipped})
    return done


def record_rejections(rejected: list[dict], state: dict, *, dry_run: bool = True) -> None:
    """❌ means the Sterling result belongs to somebody else. Remember it so we
    never ask again, and let the caller shout about it."""
    if dry_run:
        return
    for entry in rejected:
        state[entry["pid"]] = {**state.get(entry["pid"], {}), **{
            "status": "rejected",
            "decided_by": entry.get("decided_by"),
            "decided_at": dt.datetime.now().isoformat(timespec="seconds"),
        }}


def confirm(applied: list[dict], rejected: list[dict], *, dry_run: bool = True,
            channel: Optional[str] = None) -> None:
    """Reply in each thread with what actually happened — including the
    OwnerVille edit we cannot make ourselves yet."""
    cli = None if dry_run else _client()
    for entry in applied:
        legal = f"{entry['legal_first']} {entry['legal_last']}".strip()
        old = f"{entry['sheet_first']} {entry['sheet_last']}".strip()
        rows = entry.get("rows_written", 0)
        text = (f"Done — checklist updated: {old} → *{legal}* ({rows} row(s)).\n"
                f"Still needs a human: set their *OwnerVille profile* to "
                f"{legal} so it matches Sterling exactly "
                f"(Sales Rep → click the name → edit on the profile page).")
        if entry.get("skipped"):
            text += f"\nNot touched: {', '.join(entry['skipped'])}."
        _reply(cli, entry, text, dry_run)
    for entry in rejected:
        old = f"{entry['sheet_first']} {entry['sheet_last']}".strip()
        legal = f"{entry['legal_first']} {entry['legal_last']}".strip()
        text = (f"Understood — leaving {old} alone and I won't ask again.\n"
                f"Heads up: that means the Sterling check for *{legal}* belongs to "
                f"someone who isn't on this week's checklist, so nobody's BG status "
                f"is being driven by it.")
        _reply(cli, entry, text, dry_run)


def _reply(cli, entry: dict, text: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[name-gate] (dry-run) would reply in thread {entry.get('reply_ts')}:\n"
              f"  {text}")
        return
    try:
        (cli or _client()).chat_postMessage(
            channel=entry["channel"], thread_ts=entry["parent_ts"], text=text)
    except Exception as e:  # noqa: BLE001
        print(f"[name-gate] confirmation reply failed: {e}")


# --- the green tint ---------------------------------------------------------
# Megan 2026-08-26: "once the name is confirmed that it matches, let's tint
# these green." Confirmed means the checklist name and the name Sterling ran the
# check under are the same string -- either because they always were, or because
# a ✅ made them so. The tint is the at-a-glance answer to "can I trust this
# row's name", which is the question that sends people to email activations.
#
# Both tabs, always. A person who is on the rolling tab AND on their dated tab
# is one person with two rows, and tinting only one of them would say the other
# is unverified. `locations` already carries every row they appear on, so this
# falls out of the same list the status write uses.
#
# BACKGROUND ONLY. The names on this sheet are pink and bold and that is
# somebody's choice, not ours -- writing a background colour leaves the font
# exactly as it was. [[don't touch user data without confirming]]
CONFIRMED_BG = {"red": 0.85, "green": 0.94, "blue": 0.83}   # light green


def names_agree(sheet_first: str, sheet_last: str,
                legal_first: str, legal_last: str) -> bool:
    """Same person, same spelling — case and spacing don't count as different."""
    return (norm(sheet_first) == norm(legal_first)
            and norm(sheet_last) == norm(legal_last))


def confirmed_locations(roster: list, matched: dict) -> dict:
    """{tab: [(row, person key), ...]} for everyone whose checklist name matches
    the name Sterling ran their check under.

    Driven off the events that actually matched them, so a row only goes green
    when a real background check backs the spelling. Somebody with no result
    yet is not wrong, just unverified — they stay untinted.
    """
    out: dict[str, list] = {}
    for p in roster:
        events = matched.get(p.key) or []
        if not any(names_agree(p.first, p.last, e.first, e.last) for e in events):
            continue
        for tab, row in p.locations:
            out.setdefault(tab, []).append((row, p.key))
    return out


TINTED_KEY = "_tinted"


def tint_confirmed(sh, by_tab: dict, state: dict, *, dry_run: bool = True) -> int:
    """Paint cols D:E green for every newly-confirmed row.

    Only NEW ones. This report runs three times a day against a 70-row roster,
    and re-painting the same green over the same green all week is API calls
    spent to change nothing -- and per-cell format loops are what 429 the next
    report's writes. Who has been painted is remembered per tab by NAME, not by
    row: rows slide down whenever a new week's block is inserted above them, and
    Sheets carries the colour with the cell when they do.
    """
    if not by_tab:
        return 0
    from automations.recruiting_report import fill
    done = state.setdefault(TINTED_KEY, {})
    painted = 0
    tabs_touched = 0
    for tab, entries in by_tab.items():
        seen = set(done.get(tab, []))
        fresh = [(row, key) for row, key in entries if key not in seen]
        if not fresh:
            continue
        tabs_touched += 1
        ranges = [{"range": f"{FIRST_COL_A1}{row}:{LAST_COL_A1}{row}",
                   "format": {"backgroundColor": CONFIRMED_BG}}
                  for row, _ in sorted(set(fresh))]
        painted += len(ranges)
        if not dry_run:
            fill._retry(sh.worksheet(tab).batch_format, ranges)
            done[tab] = sorted(seen | {key for _, key in fresh})
    if painted:
        print(f"[name-gate] {'(dry-run) would tint' if dry_run else 'tinted'} "
              f"{painted} confirmed name(s) green across {tabs_touched} tab(s)")
    return painted


# --- the un-gated half: matched people whose spelling still isn't Sterling's --
# Megan 2026-08-26: "Sterling is the true truth." When we already KNOW who
# somebody is, there is nothing to ask — their row just has to say what Sterling
# ran. That covers everyone the matcher paired up, including the near-misses it
# forgives: the checklist's "Erica Glenn" is Sterling's "Erica Glenn Jackson",
# "Carlos Rivera" is "Carlos Rios Rivera". Same person, proven by the match,
# spelled short on the sheet.
#
# No ✅ needed and none asked for. The gate exists for the one case where
# identity is a GUESS -- a nickname that shares nothing with the legal name but
# a surname (Nikki / Shuminique). Here the match itself is the proof, so asking
# would just be three people rubber-stamping something already known.

def spelling_fixes(roster: list, matched: dict, week: str) -> list[dict]:
    """Rename entries for matched people whose sheet name isn't Sterling's.

    Shaped like the gate's approved entries so apply_renames handles both — same
    read-before-write guard, same per-location writes.
    """
    out = []
    for p in roster:
        ev = best_event(matched.get(p.key) or [])
        if ev is None:
            continue
        legal_first = titlecase_name(ev.first)
        legal_last = titlecase_name(ev.last)
        if names_agree(p.first, p.last, legal_first, legal_last):
            continue
        out.append({
            "pid": f"spelling|{week}|{p.key}",
            "sheet_first": p.first, "sheet_last": p.last,
            "legal_first": legal_first, "legal_last": legal_last,
            "key": p.key, "locations": [tuple(l) for l in p.locations],
            "decided_by": "sterling",
        })
    return out
