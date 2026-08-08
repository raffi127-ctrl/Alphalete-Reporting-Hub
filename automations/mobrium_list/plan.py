"""Decide what comes off the Mobrium List and what goes on it.

All the judgement lives here so the reasons are in one place and every line of
the report can cite one.

REMOVE somebody when they are named as terminated — by the 'Terminated Reps'
tab or by this week's sales board — UNLESS one of two things vetoes it:

  * their tracker Notes say FFP. Eve's rule: those stay.
  * OwnerVille still lists them on a live roster. That is a rehire, and the
    tracker row is about the first time they left. Tadana Manyangadze is the
    live example: on the tracker, and training new starts on this week's board.

Nothing else is allowed to trigger a removal. In particular, being ABSENT from
OwnerVille never does: a miss there is as likely to be a spelling the matcher
couldn't bridge as a person who really isn't on the roster (see ownerville.py —
the first matcher lost three working reps to middle names).

ADD everybody in the week's 'New Starts/Raf' box who isn't on the list yet and
isn't already terminated. Six of WE 8.9's eighteen new starts were terminated
inside the same week; adding them just to remove them on the same run would be
noise, so they're skipped and reported.

CONTACT DETAILS COME FROM OWNERVILLE — both the email and the phone. It is the
only source for a phone, and it is the trustworthy source for an email: the
board's email column drifts out of step with its names (see board.py). The
board's own scrape is a fallback for people OwnerVille can't resolve, and only
when the address plausibly belongs to them. Anyone who still ends up with
neither is added anyway, and named in the report as needing details — dropping
them silently would mean they never get added at all, because next week's box
holds a different week's people.

BLANK CELLS ON ROWS THAT ARE ALREADY THERE GET FILLED TOO. Only blanks: a cell
with anything in it is never touched. Somebody added on a week when OwnerVille
hadn't caught up (or when the matcher couldn't find them) would otherwise keep
an empty Phone column forever, because nothing else in this module ever looks at
an existing row again. Carlo Ferrino was exactly that — added with no phone on
2026-08-07, filled on the next run once the matcher learned about middle names.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from automations.mobrium_list import board as mboard
from automations.mobrium_list import sheet as msheet
from automations.mobrium_list.ownerville import Directory, Rep, norm_name

_PAREN = re.compile(r"\([^)]*\)")

# How stale a termination has to be before "still active in OwnerVille" is read
# as a REHIRE rather than as OwnerVille not having caught up yet.
#
# Both look identical in the data — terminated, and on a live roster — and
# getting it backwards keeps a departed rep on the list forever. OwnerVille's
# own lag is a day or two (measured 2026-08-07: Jade Sapp terminated 8/3 →
# retired 08-05, Adriannah Reyes 8/5 → 08-06, Christopher Cardenas 8/6 → 08-07),
# while a real rehire is months apart (Tadana Manyangadze: terminated 5/29,
# active and training new starts in August). A week sits clear of both.
#
# This is what stopped Karla Lopez — terminated the morning of 2026-08-07, still
# active in OwnerVille that afternoon — from being added as though she'd been
# rehired.
REHIRE_LAG_DAYS = 7


@dataclass(frozen=True)
class Removal:
    entry: msheet.Entry
    why: str


@dataclass(frozen=True)
class Kept:
    """Somebody a source called terminated, that we are deliberately keeping."""
    entry: msheet.Entry
    why: str


@dataclass(frozen=True)
class Addition:
    first: str
    last: str
    email: str
    phone: str
    source: str                 # where the contact details came from
    new_start: mboard.NewStart

    @property
    def full(self) -> str:
        return f"{self.first} {self.last}".strip()

    @property
    def complete(self) -> bool:
        return bool(self.email and self.phone)

    def values(self) -> list:
        return [self.first, self.last, self.email, self.phone]


@dataclass(frozen=True)
class Skipped:
    new_start: mboard.NewStart
    why: str


@dataclass(frozen=True)
class Fill:
    """A blank Email/Phone cell on an existing row that OwnerVille can answer."""
    entry: msheet.Entry
    email: str                  # '' = leave that cell alone
    phone: str

    @property
    def what(self) -> str:
        return " + ".join(w for w, v in (("email", self.email),
                                         ("phone", self.phone)) if v)


@dataclass
class Plan:
    removals: List[Removal]
    kept: List[Kept]
    additions: List[Addition]
    skipped: List[Skipped]
    fills: List[Fill]
    unsorted_tab: bool          # the tab wasn't in first-name order


def _split_name(name: str) -> Tuple[str, str]:
    """A board name -> (First, Last) for writing.

    Parentheticals come off — the box writes 'Qilu(Timothy) Zhao' and '(NC)' /
    '(Wk 2)' tags, and none of that belongs in a review-request list. The
    matching code keeps them (`name_tokens`); only the written form drops them.
    Capitalisation is left exactly as the board typed it.
    """
    words = [w.strip(" ,.") for w in _PAREN.sub(" ", str(name or "")).split()]
    words = [w for w in words if w]
    if not words:
        return str(name or "").strip(), ""
    if len(words) == 1:
        return words[0], ""
    return words[0], " ".join(words[1:])


def rehired(name: str, terminated, directory: Directory,
            today: dt.date) -> bool:
    """Is this person's live OwnerVille entry a rehire, or just lag?

    See REHIRE_LAG_DAYS. A termination with no date anywhere counts as a
    rehire, because there is nothing to call it recent.
    """
    if not directory.is_working(name):
        return False
    last = terminated.latest(name)
    return last is None or (today - last).days >= REHIRE_LAG_DAYS


def build(entries: List[msheet.Entry], new_starts: List[mboard.NewStart],
          terminated, directory: Directory, today: dt.date) -> Plan:
    removals: List[Removal] = []
    kept: List[Kept] = []
    for e in entries:
        if not terminated.is_terminated(e.full):
            continue
        rec = terminated.record(e.full)
        if rec is not None and rec.ffp:
            kept.append(Kept(e, f"marked FFP on {terminated.why(e.full)}"))
            continue
        if rehired(e.full, terminated, directory, today):
            last = terminated.latest(e.full)
            kept.append(Kept(
                e, f"active in OwnerVille again — rehired since "
                   f"{last.isoformat() if last else 'an undated termination'} "
                   f"({terminated.why(e.full)})"))
            continue
        removals.append(Removal(e, terminated.why(e.full)))

    on_list = {e.key for e in entries}
    additions: List[Addition] = []
    skipped: List[Skipped] = []
    seen = set()
    for ns in new_starts:
        key = norm_name(ns.name)
        if not key:
            continue
        if key in on_list:
            skipped.append(Skipped(ns, "already on the list"))
            continue
        if key in seen:
            skipped.append(Skipped(ns, "duplicate row in the box"))
            continue
        rec = terminated.record(ns.name)
        protected = ((rec is not None and rec.ffp)
                     or rehired(ns.name, terminated, directory, today))
        if terminated.is_terminated(ns.name) and not protected:
            skipped.append(Skipped(
                ns, f"already terminated — {terminated.why(ns.name)}"))
            continue
        seen.add(key)

        rep: Optional[Rep] = directory.find(ns.name)
        if rep is not None:
            first, last = rep.first.strip(), rep.last.strip()
            if not first and not last:
                first, last = _split_name(ns.name)
        else:
            first, last = _split_name(ns.name)

        email = rep.email if rep and rep.email else ""
        phone = mboard.pretty_phone(rep.phone) if rep and rep.phone else ""
        got = ["ownerville"] if (email or phone) else []
        notes: List[str] = []

        # The board fills only what OwnerVille couldn't, and an email off the
        # board has to look like it belongs to this person before it's used.
        if not email and ns.email:
            if mboard.belongs_to(ns.email, ns.name):
                email, got = ns.email, got + ["board"]
            else:
                notes.append(f"board email {ns.email} isn't theirs — left blank")
        if not phone and ns.phone:
            phone = ns.phone
            if "board" not in got:
                got.append("board")

        source = "+".join(got) or "nothing found"
        if notes:
            source = f"{source} ({'; '.join(notes)})"

        additions.append(Addition(first=first, last=last, email=email,
                                  phone=phone, source=source, new_start=ns))

    # Top up the blanks on rows that are already there — never a filled cell,
    # and never a row we're about to delete.
    going = {r.entry.row for r in removals}
    fills: List[Fill] = []
    for e in entries:
        if e.row in going or (e.email and e.phone):
            continue
        rep = directory.find(e.full)
        if rep is None:
            continue
        email = rep.email if not e.email else ""
        phone = mboard.pretty_phone(rep.phone) if not e.phone else ""
        if email or phone:
            fills.append(Fill(entry=e, email=email, phone=phone))

    return Plan(removals=removals, kept=kept, additions=additions,
                skipped=skipped, fills=fills,
                unsorted_tab=not msheet.is_sorted(entries))


def place(entries: List[msheet.Entry], plan: Plan) -> List[Tuple[int, list]]:
    """Turn the additions into (sheet row, values) pairs.

    Rows are computed against the list AS IT WILL BE AFTER the removals, and
    each addition is folded into that projection before the next one is placed
    — otherwise two people who sort next to each other both resolve to the same
    row and one lands out of order.
    """
    gone = {r.entry.row for r in plan.removals}
    surviving = [e for e in entries if e.row not in gone]
    # Renumber: after the deletions every surviving row moves up by however many
    # deleted rows sat above it.
    projected: List[msheet.Entry] = []
    for i, e in enumerate(surviving, 2):
        projected.append(msheet.Entry(row=i, first=e.first, last=e.last,
                                      email=e.email, phone=e.phone))

    out: List[Tuple[int, list]] = []
    if plan.unsorted_tab:
        # Don't guess a position on a tab that isn't in order — append instead.
        row = (projected[-1].row + 1) if projected else 2
        for i, a in enumerate(sorted(plan.additions,
                                     key=lambda x: (x.first.lower(), x.last.lower()))):
            out.append((row + i, a.values()))
        return out

    for a in sorted(plan.additions, key=lambda x: (x.first.lower(), x.last.lower())):
        row = msheet.insert_position(projected, a.first, a.last)
        out.append((row, a.values()))
        # Fold the new person in so the next placement sees them.
        projected = ([e for e in projected if e.row < row]
                     + [msheet.Entry(row=row, first=a.first, last=a.last,
                                     email=a.email, phone=a.phone)]
                     + [msheet.Entry(row=e.row + 1, first=e.first, last=e.last,
                                     email=e.email, phone=e.phone)
                        for e in projected if e.row >= row])
    return out
