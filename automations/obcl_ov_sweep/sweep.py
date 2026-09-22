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
    bg_status: str = ""
    blue_ink: bool = False
    location: object = None                    # None = chart has no Location col
    chart_date: object = None                  # date the person's chart is for
    status_col: int = 0                        # 1-indexed Final Status column

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
        bg = cols.get("BG Status : Last Checked")
        bi = cols.get("Blue Ink")
        lo = cols.get("Location")
        cdate = oc.chart_date(ch)
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
                ticked={c: _truthy(cell(i)) for c, i in mapped.items()},
                bg_status=cell(bg), blue_ink=_truthy(cell(bi)),
                location=cell(lo) if lo else None, chart_date=cdate, status_col=fs or 0))
    return out


def owner_submitted(p: Person) -> bool:
    """Already owner-submitted — Final Status says so, or the box is ticked.
    Owner Submit needs every other step done first, so there is nothing left
    to look up (Megan 2026-09-21: re-searching them "is a waste of time")."""
    return ("owner submit" in (p.final_status or "").lower()
            or bool(p.ticked.get("Owner Submit")))


def no_show(p: Person, today=None) -> bool:
    """Blank Final Status AND blank Location once their start day has passed
    = never came. Digi Docs only adds people who show up, so OwnerVille has no
    record of them — searching cost ~10 min a pass for 15 such rows on
    2026-09-21 (Sung Par, Antashia Rich: "0 entries" under Show All). On their
    start day itself they're still checked: the status just isn't filled yet."""
    import datetime as _dt
    today = today or _dt.date.today()
    if p.location is None:              # no Location column: can't tell, so no
        return False
    if (p.final_status or "").strip() or p.location.strip():
        return False
    return bool(p.chart_date and p.chart_date < today)


def to_check(everyone: List[Person]) -> List[Person]:
    """People worth an OwnerVille lookup: something still open, not gone,
    not already owner-submitted."""
    return [p for p in everyone
            if p.open_columns and not _gone(p.final_status)
            and not owner_submitted(p) and not no_show(p)]


def earned(p: Person, done: Dict[str, object]) -> List[str]:
    """Columns to tick for `p`, given ov_table.done_columns' answer.

    Only a literal True ticks — False (not done) and None (header missing,
    so unread) both leave the box alone. Already-ticked columns are never
    returned, and nothing here ever un-ticks.
    """
    return [c for c in p.open_columns if done.get(c) is True]


def sheet_bg_pending(p: Person) -> bool:
    """Owner Submit YELLOW straight off the sheet (Megan 2026-09-21: "that
    group of pending BGs"): every other sweep box on the row is ticked — Digi
    Docs, Quizzes, Headshot, UID (Blue Ink doesn't count) — and the BG is still
    pending: BG Status says Pending ("Taken - Pending") or Unperformable (Megan,
    same day: "and the unperformables that have everything else done"), or
    Final Status says "Pending on OV" (Faith Moss). Needs no OwnerVille read."""
    others = [c for c in config.COLUMNS if c != "Owner Submit" and c in p.cols]
    if not others or not all(p.ticked.get(c) for c in others):
        return False
    # Blue Ink does NOT block yellow (Megan 2026-09-21, David Dean / Jomanah
    # Bennett): it's outside OwnerVille onboarding, so it can't hold up the
    # owner submit.
    bg = (p.bg_status or "").lower()
    return ("pending" in bg or "unperformable" in bg
            or "pending on ov" in (p.final_status or "").lower())


def paint_plan(everyone: List[Person], ticked_now=(), ready_rows=(),
               bg_pending_rows=(), sheet_only: bool = False):
    """[(person, column, colour)] for EVERY sweep column of every active
    person — not only the boxes this pass ticked (Megan 2026-09-21: hand-ticked
    boxes were left white). Ticked (before or now) = GREEN; Owner Submit ready
    to submit = BLUE; Owner Submit done-but-BG-pending = YELLOW; anything else
    = LIGHT RED. Quit / terminated / no-show
    rows are left alone."""
    now = set(ticked_now)
    ready = set(ready_rows)
    bg_wait = set(bg_pending_rows)
    out = []
    for p in everyone:
        if _gone(p.final_status) or no_show(p):
            continue
        for c in config.COLUMNS:
            if c not in p.cols:
                continue
            if p.ticked.get(c) or (p.row, c) in now:
                out.append((p, c, config.DONE_GREEN))
            elif c == "Owner Submit" and p.row in ready:
                out.append((p, c, config.READY_BLUE))
            elif c == "Owner Submit" and (p.row in bg_wait
                                          or sheet_bg_pending(p)):
                out.append((p, c, config.BG_PENDING_YELLOW))
            elif c == "Owner Submit" and sheet_only:
                # Without an OwnerVille read we can't know blue (or the OV-only
                # yellow) — leave the last Lucy pass's colour alone rather than
                # overwrite it with red (2026-09-21: wiped Govany Torres' blue).
                continue
            else:
                out.append((p, c, config.NOT_FOUND_RED))
    return out


# Final Status values this sweep may move ON to "Owner submitted" — all
# EARLIER in the process. Anything else (Activations Email sent, Sara+
# Received, MISSING ID, Terminated, ...) is left exactly as a person set it.
STATUS_BEFORE_SUBMIT = {"", "showed up to cr", "pending on ov",
                        "needs blueink", "waiting on bgc"}
OWNER_SUBMITTED = "Owner submitted"      # the dropdown's exact spelling


def status_updates(everyone: List[Person], ticked_now=()) -> List[Person]:
    """People whose Final Status should now read "Owner submitted" (Megan
    2026-09-21): Owner Submit ticked AND Blue Ink ticked — someone still
    missing Blue Ink stays "Needs BlueInk"."""
    now = set(ticked_now)
    out = []
    for p in everyone:
        if not p.status_col or _gone(p.final_status):
            continue
        submitted = (p.ticked.get("Owner Submit")
                     or (p.row, "Owner Submit") in now)
        if (submitted and p.blue_ink
                and (p.final_status or "").strip().lower()
                in STATUS_BEFORE_SUBMIT):
            out.append(p)
    return out
