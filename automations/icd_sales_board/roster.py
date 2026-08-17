"""The persistent roster — the half of the board an owner owns.

Everything here is owner-set operational truth that no Tableau pull can know:
who is on the team, when they started, what level they are, which car ride
they're on, and whether they're still active. It is deliberately SEPARATE from
the weekly sales tabs, because those get regenerated every week and rewritten
every day — anything stored in them is lost on the next build. Megan
(2026-08-17): the owner sets it "and it has to remain".

TENURE IS COMPUTED, NEVER TYPED. Raf's board carries tenure inside the name
cell — "Anthony Vargas (Wk 2)" — which means somebody has to bump every one of
those every Monday, and the suffix breaks name-matching against Tableau. Store
the START DATE once and the week number is right forever, with no upkeep.

Levels reuse the ladder the Leader's Call deck already uses, so a rep's level
means the same thing in both places.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

# The leadership ladder, ascending. Same names + order as
# leaders_call.build_pdf.LEVEL_COLORS, so a promotion recognized on the Monday
# call and a level set on the board can never disagree about what exists.
# Ascending. The top rungs match leaders_call.build_pdf.LEVEL_COLORS so a
# promotion recognized on the Monday call means the same thing here. The bottom
# two come from Raf's board, which actually uses "In Training" and "Entry Level"
# below Level 1 (counted live 2026-08-17: In Training 4, Entry Level 24,
# Level 1 31, Level 2 3, Mastermind 2). A ladder missing rungs that are in use
# would force every new rep to be mislabelled.
LEVELS = ["In Training", "Entry Level", "Level 1", "Level 2", "Level 3",
          "Mastermind", "Partner", "Ownership"]

# Status values the owner can set. Sourced from the columns Raf's "Line Up" tab
# already uses (r44+), so this is his vocabulary, not a new one.
STATUSES = ["Active", "New Start", "FFP", "Roadtrip", "OFF", "O-NA",
            "Late to match ups", "STF", "Terminated"]

# A rep with one of these is not expected in the field, so they must not count
# toward "reps that rolled a zero" or drag "% of reps selling" down. You cannot
# roll a zero on a day you were never scheduled to work.
NOT_IN_FIELD = {"OFF", "O-NA", "Terminated", "FFP"}


@dataclass
class Rep:
    name: str
    start_date: str = ""        # ISO. The ONLY tenure input.
    level: str = "Level 1"
    team: str = ""              # car-ride leader / team name
    status: str = "Active"
    terminated_on: str = ""     # ISO. Set when status becomes Terminated.
    notes: str = ""

    @property
    def is_terminated(self) -> bool:
        return self.status == "Terminated"

    def gone_by(self, day: dt.date) -> bool:
        """Were they already gone on this date?

        False when the termination date is unknown — better to show a normal
        row than to grey out days someone may well have worked."""
        if not self.is_terminated or not self.terminated_on:
            return False
        try:
            return day >= dt.date.fromisoformat(self.terminated_on)
        except ValueError:
            return False

    def week_number(self, on: dt.date | None = None) -> int | None:
        """Which week of employment they're in, 1-based. None if no start date.

        Counts calendar weeks from the Monday of their start week, so everyone
        who started in the same week is the same 'Wk N' — which is how the field
        talks about it, and how Raf's board labels it."""
        if not self.start_date:
            return None
        try:
            start = dt.date.fromisoformat(self.start_date)
        except ValueError:
            return None
        on = on or dt.date.today()
        if on < start:
            return None
        start_mon = start - dt.timedelta(days=start.weekday())
        on_mon = on - dt.timedelta(days=on.weekday())
        return ((on_mon - start_mon).days // 7) + 1

    def tenure_label(self, on: dt.date | None = None) -> str:
        w = self.week_number(on)
        if w is None:
            return ""
        return "Veteran" if w > 4 else f"Wk {w}"

    @property
    def in_field(self) -> bool:
        return self.status not in NOT_IN_FIELD


# ---------------------------------------------------------------------------
# Storage. INTERIM: a local JSON per office, so the site is usable before the
# per-office workbooks exist (blocked on the Drive scope — see the recipe).
# When those land, swap _path() for the office's "Roster" tab; the shape here is
# already the tab's columns, so nothing above changes.
# ---------------------------------------------------------------------------
STORE = Path("output/icd_sales_board/rosters")


def _path(office_key: str) -> Path:
    return STORE / f"{office_key}.json"


def load(office_key: str) -> list:
    p = _path(office_key)
    if not p.exists():
        return []
    try:
        return [Rep(**r) for r in json.loads(p.read_text(encoding="utf-8"))]
    except (ValueError, OSError, TypeError):
        return []


def save(office_key: str, reps: list) -> None:
    """Overwrite this office's roster.

    Owner-entered data — never call this with a partial list built from a
    filtered view, or the rows filtered out are deleted."""
    STORE.mkdir(parents=True, exist_ok=True)
    _path(office_key).write_text(
        json.dumps([asdict(r) for r in reps], indent=2), encoding="utf-8")


_WK_TAG = __import__("re").compile(r"wk\s*(\d+)", __import__("re").I)


def _seed_start_date(tags: list, week_start: dt.date | None) -> str:
    """Turn a board's '(Wk 2)' tag into a real start date.

    Raf's board already tracks tenure by hand in the name cell. Rather than ask
    an owner to key 60 start dates to migrate, read the tag once: a rep marked
    'Wk 2' during the week beginning `week_start` started one week earlier.
    Only ever used when CREATING a rep, so it can't overwrite a real date the
    owner set later."""
    if not week_start:
        return ""
    for t in tags or []:
        m = _WK_TAG.search(t or "")
        if m:
            n = max(1, int(m.group(1)))
            return (week_start - dt.timedelta(weeks=n - 1)).isoformat()
    return ""


def set_attrs(office_key: str, attrs: dict) -> int:
    """Save the owner's Team / Leadership for each rep, additively.

    Only writes the fields passed, and only when they carry a value — so
    clearing a cell leaves the board's own value showing rather than silently
    blanking a rep's team. Reps not mentioned are untouched, which means a
    filtered or sorted view can never wipe the rows it wasn't showing."""
    existing = {r.name.strip().lower(): r for r in load(office_key)}
    changed = 0
    for name, vals in (attrs or {}).items():
        key = (name or "").strip().lower()
        if not key:
            continue
        rep = existing.get(key) or Rep(name=(name or "").strip())
        for field_name in ("team", "level", "status"):
            new = (vals.get(field_name) or "").strip()
            if new and new != getattr(rep, field_name):
                setattr(rep, field_name, new)
                changed += 1
        # Stamp the termination date the first time they are marked gone, and
        # clear it if they are put back on — otherwise an un-terminated rep
        # keeps a date and their days stay greyed out.
        if rep.is_terminated and not rep.terminated_on:
            rep.terminated_on = (vals.get("terminated_on")
                                 or dt.date.today().isoformat())
        elif not rep.is_terminated:
            rep.terminated_on = ""
        existing[key] = rep
    save(office_key, sorted(existing.values(), key=lambda r: r.name.lower()))
    return changed


def upsert(office_key: str, reps: list,
           week_start: dt.date | None = None) -> list:
    """Merge names discovered in a sales pull into the roster WITHOUT touching
    what the owner set.

    `reps` is a list of names, or of (name, tags) pairs when the board carries
    tenure tags worth seeding. A rep who shows up in the pull but isn't on the
    roster gets added; a rep already there keeps their start date, level, team
    and status exactly as the owner left them. That is what makes the roster
    survive every rebuild — the pull can add people, never edit them."""
    existing = {r.name.strip().lower(): r for r in load(office_key)}
    for item in reps:
        name, tags = item if isinstance(item, (tuple, list)) else (item, [])
        key = (name or "").strip().lower()
        if not key or key in existing:
            continue
        existing[key] = Rep(name=name.strip(),
                            start_date=_seed_start_date(tags, week_start))
    out = sorted(existing.values(), key=lambda r: r.name.lower())
    save(office_key, out)
    return out
