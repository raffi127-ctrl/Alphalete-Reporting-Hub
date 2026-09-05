"""Checkpoint 2: the master Terminated Reps list.

Source path (spell it out, per house rule):
  workbook  https://docs.google.com/spreadsheets/d/1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4
  tab       "Terminated Reps"  (gid 835099438)
  header    row 1
  columns   "Rep Name", "Lead Rep", "Termination Date WE", "Ownerville",
            "Slack Deact", "Notes", "Year"
  rows      2..end, one per terminated rep (~2,700 as of 2026-09-05)

WHY THIS EXISTS (Megan 2026-09-05, after Evelyn pointed at the tab: "I'll add
this to Lucy as well so that there are 2 checkpoints before texting happens").

Checkpoint 1 is the OBCL marker: whoever terminates a leader replaces their
name in the "2ND Round Interviewer" cell with the literal "Terminated", and
those rows are never tagged or texted (2026-08-23). It only fires if somebody
remembers to edit that cell.

This is checkpoint 2, and it closes a hole the module already knew about:
membership is replayed from channel_join/channel_leave messages, so a leader
whose Slack account is merely DEACTIVATED is never seen to "leave" and stays
textable forever. Every match found on 2026-09-05 carried Slack Deact = TRUE —
precisely the people that gap misses. One of them, Tadana (on the sheet as
"Tadana Manyangadze", terminated 5/29/2026), was texted in the first live
sweep that morning.

MATCHING
  * "Rep Name" holds first and last separated by a literal TAB
    ("Christian\\tWilliams"), so whitespace is collapsed before normalizing.
  * Names are normalized with roster._norm, which folds accents — that is what
    matches the sheet's "Anh Dinh" to the roster's "Anh Đinh".
  * A leader matches on ANY of their known names (roster.Leader.keys(), i.e.
    display name + every OBCL alias). "Tadana Jeti" only matches because
    "Tadana Manyangadze" is on her alias list.

REHIRES
  A row whose Notes say "rehired" does NOT block. That lives in the SHEET on
  purpose — the sheet is the source of truth and Evelyn maintains it, so a
  parallel override list in this repo would just drift out of sync. Rows are
  never deleted (they are payroll history), hence an annotation rather than a
  removal.

FAILURE MODE
  A read failure does NOT stop the sweep: checkpoint 1 still stands, and a
  leader silently never chased is this module's stated worst outcome. It warns
  loudly and the run reports itself as running on one checkpoint instead of two.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

TAB_TITLE = "Terminated Reps"
NAME_HEADER = "Rep Name"
DATE_HEADER = "Termination Date WE"
LEAD_HEADER = "Lead Rep"
NOTES_HEADER = "Notes"
OV_HEADER = "Ownerville"
DEACT_HEADER = "Slack Deact"

# A Notes value containing this (case-insensitive) means "back on the team" —
# see REHIRES above.
REHIRED_MARK = "rehired"


class TerminatedRep:
    def __init__(self, raw_name: str, date: str, lead: str, notes: str,
                 ownerville: str, slack_deact: str, row: int):
        self.raw_name = raw_name
        self.date = date
        self.lead = lead
        self.notes = notes
        self.ownerville = ownerville
        self.slack_deact = slack_deact
        self.row = row

    @property
    def rehired(self) -> bool:
        return REHIRED_MARK in (self.notes or "").lower()

    def describe(self) -> str:
        """One line for a human deciding whether this block is right."""
        bits = ["terminated {}".format(self.date or "date unknown")]
        if self.lead:
            bits.append("lead {}".format(self.lead))
        if (self.slack_deact or "").strip().upper() == "TRUE":
            bits.append("Slack deactivated")
        if self.notes:
            bits.append("notes: {}".format(self.notes[:40]))
        return "{} ({}, '{}' row {})".format(
            self.raw_name, ", ".join(bits), TAB_TITLE, self.row)


def _clean(value: str) -> str:
    """Collapse the tab-separated 'First\\tLast' into a plain name."""
    return re.sub(r"\s+", " ", (value or "").replace("\t", " ")).strip()


def load(sheet_id: Optional[str] = None) -> Dict[str, TerminatedRep]:
    """normalized name -> TerminatedRep, for every non-rehired row.

    Raises on a read/shape problem so the caller can decide (texts.run treats
    it as advisory — see FAILURE MODE above).
    """
    from automations.recruiting_report import fill
    from automations.new_start_followup import obcl, roster as roster_mod

    sh = fill.open_by_key(sheet_id or obcl.SHEET_ID)
    ws = fill.worksheet_ci(sh, TAB_TITLE)
    values = ws.get_all_values()
    if not values:
        raise RuntimeError("'{}' is empty".format(TAB_TITLE))

    header = values[0]
    norm = [re.sub(r"\s+", " ", (h or "")).strip().lower() for h in header]

    def col(label: str, required: bool = True) -> int:
        want = label.strip().lower()
        if want in norm:
            return norm.index(want)
        if required:
            raise RuntimeError(
                "'{}' column {!r} not found. Headers: {}".format(
                    TAB_TITLE, label, [h for h in header if h]))
        return -1

    i_name = col(NAME_HEADER)
    i_date = col(DATE_HEADER, required=False)
    i_lead = col(LEAD_HEADER, required=False)
    i_notes = col(NOTES_HEADER, required=False)
    i_ov = col(OV_HEADER, required=False)
    i_deact = col(DEACT_HEADER, required=False)

    def cell(row: List[str], idx: int) -> str:
        return (row[idx] if 0 <= idx < len(row) else "").strip()

    out: Dict[str, TerminatedRep] = {}
    for n, row in enumerate(values[1:], start=2):
        raw = _clean(cell(row, i_name))
        if not raw:
            continue          # the tab carries trailing blank rows
        rep = TerminatedRep(raw, cell(row, i_date), cell(row, i_lead),
                            cell(row, i_notes), cell(row, i_ov),
                            cell(row, i_deact), n)
        if rep.rehired:
            continue
        key = roster_mod._norm(raw)
        if not key:
            continue
        # Last row wins: the sheet is chronological, so a later row is the more
        # recent word on that person.
        out[key] = rep
    return out


_CACHE = None  # type: Optional[Dict[str, TerminatedRep]]


def load_cached(sheet_id: Optional[str] = None) -> Dict[str, TerminatedRep]:
    """load(), read at most once per process.

    The tab is ~2,700 rows and both the text sweep and the numbers backfill
    need it in the same run; re-reading would be a second full fetch for an
    answer that cannot have changed mid-sweep.
    """
    global _CACHE
    if _CACHE is None:
        _CACHE = load(sheet_id)
    return _CACHE


def reset_cache() -> None:
    """Tests, and any caller that wants a genuinely fresh read."""
    global _CACHE
    _CACHE = None


def find(leader, table: Dict[str, TerminatedRep]) -> Optional[TerminatedRep]:
    """The terminated row for `leader`, matched on ANY name they answer to."""
    if not table:
        return None
    for key in leader.keys():
        hit = table.get(key)
        if hit is not None:
            return hit
    return None
