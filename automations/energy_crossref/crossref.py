"""Three counts of the same day's Energy sales, lined up rep by rep.

    Slack        the last running board of the night in #alphalete-sales
    Sales Board  the 'EN' cell under yesterday on 'Alphalete SALES BOARD 2025'
    Webform      the Base Power Energy Google Form, one row per sale

The first two are already read by `energy_slack_fill` (which is what WRITES the
EN column every morning), so they are imported rather than re-implemented — one
parser for the running board, one roster lookup, one alias list.

WHAT COUNTS AS "OWED". A rep owes one webform per SALE, and the two sale counts
can disagree (a sale reaches the board by other routes than the evening post).
So the expectation is `max(slack, board)` per rep: that never under-tags someone
who really is short, and a disagreement between the two is reported instead of
being silently resolved.

A rep who filed MORE forms than they have sales is never netted off against a
rep who filed fewer — it is listed as its own oddity. Netting them would hide
both halves of what is usually one misspelled name.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from automations.energy_crossref import webform as W
from automations.energy_slack_fill import parse as P
from automations.energy_slack_fill import run as EF


@dataclass
class RepLine:
    """One rep's three counts."""
    board_name: str
    row: int
    slack: int = 0
    board: int = 0
    forms: int = 0
    dupes: list = field(default_factory=list)

    @property
    def expected(self) -> int:
        return max(self.slack, self.board)

    @property
    def missing(self) -> int:
        return max(0, self.expected - self.forms)

    @property
    def extra(self) -> int:
        return max(0, self.forms - self.expected)


@dataclass
class Result:
    day: dt.date
    reps: list[RepLine]
    slack_total: int = 0
    board_total: int = 0
    forms_total: int = 0
    tally: int | None = None
    goal: int | None = None
    warnings: list[str] = field(default_factory=list)
    board_tab: str = ""
    post_time: str = ""

    @property
    def missing_total(self) -> int:
        return sum(r.missing for r in self.reps)

    @property
    def short(self) -> list[RepLine]:
        """Reps who owe a form — the tag list, ALPHABETICAL.

        Not worst-first: the tag line is a roll-call, and Evelyn's posts have
        always read Charley, Edgar, Zoria — i.e. by name — so a rep looking for
        themselves scans it the same way every morning."""
        return sorted((r for r in self.reps if r.missing),
                      key=lambda r: r.board_name.lower())

    @property
    def dupes(self) -> list[tuple[str, str]]:
        return [(r.board_name, why) for r in self.reps for _a, _b, why in r.dupes]


def _blank_slack_day(blocks, day) -> bool:
    return P.last_block_for(blocks, day) is None


def build(day: dt.date, blocks, grid, rows: dict[int, str],
          forms: dict[str, W.RepForms], form_warnings: list[str]) -> Result:
    """Line up the three sources for `day`. Pure — every read already happened."""
    res = Result(day=day, reps=[], warnings=list(form_warnings))
    lines = {r: RepLine(board_name=rows[r], row=r) for r in rows}

    # --- Sales Board: the EN cell under this weekday -----------------------
    col = EF.metric_col(grid, day)
    if col is None:
        res.warnings.append(
            f"no 'EN' column under {day.strftime('%A')} on the board tab — the "
            "Sales Board count is 0 for every rep and cannot be trusted")
    else:
        for r in rows:
            cur = str(EF._cell(grid, r, col)).strip()
            if cur.isdigit():
                lines[r].board = int(cur)

    # --- Slack: the last running board of the night ------------------------
    blk = P.last_block_for(blocks, day)
    if blk is None:
        res.warnings.append(
            f"no Energy board was posted in {EF.CHANNEL[0]} for {day} — the "
            "Slack count is 0 and only the Sales Board is speaking")
    else:
        res.tally, res.goal = blk.tally, blk.goal
        res.slack_total = blk.total
        res.post_time = blk.when.astimezone(P.TZ).strftime("%H:%M")
        for line in blk.lines:
            row, note = EF.match_rep(line.name, rows)
            if row is None:
                res.warnings.append(
                    f"Slack line {line.raw!r} ({line.count} sale(s)) — {note}; "
                    "those sales are counted in the Slack total but belong to "
                    "nobody, so nobody can be asked for their webform")
                continue
            lines[row].slack += line.count
        if blk.tally is not None and blk.tally != blk.total:
            res.warnings.append(
                f"the office's own tally says {blk.tally}/{blk.goal or '?'} but "
                f"the posted lines add to {blk.total} — the Slack count may be off")
        elif blk.tally is None:
            res.warnings.append(
                "the Energy block never posted its 'N/goal' tally line — nothing "
                "independently confirms the Slack count")

    # --- Webform: match each filer to a board row --------------------------
    for key, rf in forms.items():
        row, note = EF.match_rep(rf.rep, rows)
        if row is None:
            res.warnings.append(
                f"webform filed by {rf.rep!r} ({rf.count} form(s)) — {note}; not "
                "counted against anyone. Fix the spelling on the board, or add "
                "it to ALIASES in energy_slack_fill/parse.py")
            continue
        lines[row].forms += rf.count
        for a, b in rf.dupes:
            why = W._same_sale(a, b) or "same sale"
            lines[row].dupes.append((a, b, (
                f"{rf.rep} filed the same sale twice (rows {a.row} and "
                f"{b.row}) — {why}; the second form does NOT count as a "
                "second sale")))

    res.reps = [lines[r] for r in sorted(lines)]
    res.board_total = sum(l.board for l in res.reps)
    res.forms_total = sum(rf.count for rf in forms.values())
    if blk is not None and res.slack_total != res.board_total:
        res.warnings.append(
            f"Slack says {res.slack_total} sale(s) and the Sales Board says "
            f"{res.board_total} — they normally agree; each rep is asked for the "
            "HIGHER of their two counts")
    return res
