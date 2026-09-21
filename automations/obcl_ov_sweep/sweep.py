"""The pure half: who on the tab still owes a tick, and which ticks an
OwnerVille read earns. No browser, no Sheets — see test_sweep.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from automations.obcl_ov_sweep import config
from automations.shared import obcl_charts as oc


@dataclass
class Person:
    first: str
    last: str
    row: int                                   # 1-indexed sheet row
    final_status: str = ""
    cols: Dict[str, int] = field(default_factory=dict)   # label -> 1-indexed
    ticked: Dict[str, bool] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}".strip()

    @property
    def open_columns(self) -> List[str]:
        """Mapped columns present on this chart and not yet ticked."""
        return [c for c in config.COLUMNS
                if c in self.cols and not self.ticked.get(c)]


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in config.TRUTHY


def _gone(final_status: str) -> bool:
    s = (final_status or "").lower()
    return any(w in s for w in config.GONE_WORDS)


def people(values: List[List[str]]) -> List[Person]:
    """Everyone in EVERY chart on the tab — last week's carried chart too.

    Deliberately not blueink_docs.roster.parse_tab: that drops charts dated for
    another week, which is right for SENDING but wrong here. Quizzes and UIDs
    finish days after the start date, and those people are exactly the ones
    still sitting in the carried chart. Columns come from each chart's own
    header, by label.
    """
    out: List[Person] = []
    for ch in oc.find_charts(values):
        cols = ch["cols"]
        fi, la = cols.get("Name"), cols.get("Last Name")
        if not fi:
            continue
        fs = cols.get("Final Status")
        mapped = {c: cols[c] for c in config.COLUMNS if c in cols}
        for r in range(ch["start_row"], ch["end_row"] + 1):
            row = values[r - 1] if r - 1 < len(values) else []

            def cell(i):
                return row[i - 1].strip() if i and i - 1 < len(row) else ""

            first, last = cell(fi), cell(la)
            if not first or first == "Name":
                continue
            out.append(Person(
                first=first, last=last, row=r, final_status=cell(fs),
                cols=mapped,
                ticked={c: _truthy(cell(i)) for c, i in mapped.items()}))
    return out


def owner_submitted(p: Person) -> bool:
    """Already owner-submitted — Final Status says so, or the box is ticked.
    Owner Submit needs every other step done first, so there is nothing left
    to look up (Megan 2026-09-21: re-searching them "is a waste of time")."""
    return ("owner submit" in (p.final_status or "").lower()
            or bool(p.ticked.get("Owner Submit")))


def to_check(everyone: List[Person]) -> List[Person]:
    """People worth an OwnerVille lookup: something still open, not gone,
    not already owner-submitted."""
    return [p for p in everyone
            if p.open_columns and not _gone(p.final_status)
            and not owner_submitted(p)]


def earned(p: Person, done: Dict[str, object]) -> List[str]:
    """Columns to tick for `p`, given ov_table.done_columns' answer.

    Only a literal True ticks — False (not done) and None (header missing,
    so unread) both leave the box alone. Already-ticked columns are never
    returned, and nothing here ever un-ticks.
    """
    return [c for c in p.open_columns if done.get(c) is True]


def paint_plan(everyone: List[Person], ticked_now=(), ready_rows=()):
    """[(person, column, colour)] for EVERY sweep column of every active
    person — not only the boxes this pass ticked (Megan 2026-09-21: hand-ticked
    boxes were left white). Ticked (before or now) = GREEN; Owner Submit ready
    to submit = BLUE; anything else = LIGHT RED. Quit / terminated / no-show
    rows are left alone."""
    now = set(ticked_now)
    ready = set(ready_rows)
    out = []
    for p in everyone:
        if _gone(p.final_status):
            continue
        for c in config.COLUMNS:
            if c not in p.cols:
                continue
            if p.ticked.get(c) or (p.row, c) in now:
                out.append((p, c, config.DONE_GREEN))
            elif c == "Owner Submit" and p.row in ready:
                out.append((p, c, config.READY_BLUE))
            else:
                out.append((p, c, config.NOT_FOUND_RED))
    return out
