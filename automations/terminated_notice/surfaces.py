"""WHERE a terminated ICD has to come off — one declarative table.

This is the whole point of the module: when Megan or Eve logs someone on the
'Terminated ICDs' tab, nobody should have to remember the 11 places that person
is still wired into. The scan walks this table, keeps only the surfaces that
actually still mention them, and the checklist that gets posted is that result.

ADDING A REPORT IS ONE LINE HERE. No hardcoded row/column anywhere: a Sheet
surface is found by TAB TITLE or by searching cells for the name, and a code
surface is a plain substring search of the file. Templates and rosters change;
label/name lookup survives (CLAUDE.md, 'No hardcoded rows or columns').

Four kinds:

  SheetTab   — the ICD has their own tab in this workbook. Fix: HIDE it. Never
               delete: the recruiting + financial reports both skip hidden tabs,
               and the data stays readable for anyone who needs last quarter's
               numbers.
  SheetCells — the ICD is a ROW inside somebody else's tab (a captainship block
               on the Org Sales Board). Fix: a person edits the board — often
               with org_sales_board's roster_remove, because rows there carry
               SUM ranges and chart series that a hand-delete would shear.
  Code       — a roster literal in the repo. Fix: a one-line edit + push.
  Always     — listed with its instruction unless run.py can check it. Google
               Contacts is checked (read-only) since 2026-09-11; the line only
               falls back to the generic instruction when no card matches.

LEAVE_ALONE is the other half and matters just as much: surfaces where a
terminated ICD stays ON PURPOSE. The cancels/disconnects rosters are filters
over historical rows — pulling a closed office out mid-week silently drops that
week's numbers out of their captain's totals, which is why Kimberly Rodriguez
and Melik El Jaiez are both still listed there. The checklist says so out loud,
so nobody "finishes the job" and quietly changes a report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# --------------------------------------------------------------------------
# surface kinds
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SheetTab:
    """A workbook where the ICD gets their own tab."""
    label: str
    workbook_id: str
    fix: str = "hide the tab (don't delete — the data stays)"
    # Set when hiding is NOT enough because the report walks every tab
    # regardless of the hidden flag (focus_office_att.daily does exactly this).
    hiding_is_not_enough: str = ""


@dataclass(frozen=True)
class SheetCells:
    """A workbook where the ICD is a row inside a shared tab. `tabs` lists the
    LIVE tabs only — a backup copy is not a place anyone has to edit, and
    listing six of them buries the one that matters."""
    label: str
    workbook_id: str
    tabs: tuple = ()
    fix: str = "their rows come off the board"
    # Tabs whose own convention for "this person left" is a HIDDEN ROW, so a
    # name found in a hidden row there is the finished state, not a to-do.
    # Captainship Bonuses is the one: raf_captainship_bonus.sheet_fill treats
    # hidden rows as departed reps and never fills them. It is listed per tab
    # on purpose — on Overrides Math a hidden row would still count in the
    # SUM, so hiding there is NOT done. (Melik El Jaiez, 2026-09-11: his row
    # 49 had been hidden for weeks and the checklist still said 'clear A49'.)
    hidden_row_is_done: tuple = ()
    # Tabs where a terminated ICD's row STAYS while it still shows money, and
    # comes off only once every $ cell on it reads $0 (Eve, 2026-09-11, about
    # Melik on Overrides Math: "cuando deje de proveer revenue y esté en $0 se
    # puede sacar"). A row still in money is listed under Leave alone, not
    # To do — otherwise the checklist asks for the opposite of the rule.
    keep_while_paid: tuple = ()


@dataclass(frozen=True)
class Code:
    """A roster literal in the repo.

    `resolved` is for the files where the terminated-correct state is not
    "the name is gone". office-mapping.json is the one that matters: a closed
    office BELONGS in the `skip` bucket, with a reason and a retired date —
    deleting the entry outright would let auto_onboard_tabs re-add the tab on
    the next run. Without this hook the checklist would nag forever about a
    file that is already right."""
    label: str
    path: str
    fix: str = "take their name out of the list"
    resolved: object = None      # (text, candidates) -> bool, or None


@dataclass(frozen=True)
class Always:
    """Listed every time UNLESS the run could check it. `check` names the
    checker in run.py ('contacts'); when that checker comes back with an
    answer — done or still to do — its line replaces this one. When it can't
    tell (no token, no card that matches the name) this line stays: 'I
    couldn't tell' has to read as 'still to do', never as done."""
    label: str
    fix: str
    check: str = ""


@dataclass(frozen=True)
class LeaveAlone:
    """Listed as deliberately untouched, with the reason."""
    label: str
    why: str


# --------------------------------------------------------------------------
# resolved-state checks
# --------------------------------------------------------------------------

def _only_in_skip(text: str, cands) -> bool:
    """True when an office-mapping file mentions the ICD ONLY in its `skip`
    bucket — the state a closed office is supposed to end in. Any mention in
    confirmed / needs_review / sales_only means the report still tries the
    office, so the checklist should still say so.

    Unparseable file -> False: 'I couldn't tell' has to read as 'still to do',
    never as done."""
    import json
    keys = {" ".join(str(c).strip().lower().split()) for c in cands}
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return False
    for bucket in ("confirmed", "needs_review", "sales_only"):
        for e in (data.get(bucket) or []):
            blob = json.dumps(e, ensure_ascii=False).lower()
            if any(k and k in blob for k in keys):
                return False
    return True


# --------------------------------------------------------------------------
# the table
# --------------------------------------------------------------------------

SURFACES: List[object] = [
    SheetTab(
        "ATT Program - Focus Report",
        "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE",
    ),
    SheetTab(
        "Daily Rep Breakdown - ATT Program",
        "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY",
        hiding_is_not_enough=(
            "hiding won't stop it — that report fills every tab it finds, "
            "hidden or not"),
    ),
    SheetCells(
        "Alphalete ORG Sales Board",
        "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E",
        tabs=("Alphalete ORG Sales Board", "KTS ", "Int WoW Report",
              "Captainship Bonuses", "Overrides Math"),
        hidden_row_is_done=("Captainship Bonuses",),
        keep_while_paid=("Overrides Math",),
    ),
    Code("Recruiting office map",
         "automations/recruiting_report/office-mapping.json",
         fix="move their entry from `confirmed` to `skip`, with a reason + "
             "`retired` date — that's what stops AppStream being asked for a "
             "closed office, and stops auto_onboard_tabs re-adding them",
         resolved=lambda text, cands: _only_in_skip(text, cands)),
    Code("Due Diligence roster",
         "automations/recruiting_report/dd_roster.json"),
    Code("Applicant Tracker offices",
         "automations/recruiting_report/offices.json"),
    Code("Knocks / Time Gaps office ids",
         "automations/recruiting_report/icd_office_mappings.json"),
    Code("Focus Office ATT owners",
         "automations/focus_office_att/setup_tabs.py"),
    Code("Captainship draft emails",
         "automations/captainship_drafts/config.py",
         fix="take their email out of their captain's list — seed_groups.py "
             "rebuilds the contact group from it, so the code has to change "
             "too, not just the group"),
    Code("Owner Showdown",
         "automations/owner_showdown/roster.py",
         fix="take them off the competitor list (skip if that contest is over)"),
    Code("Owner Showdown emails",
         "automations/owner_showdown/distro.py",
         fix="take them off the thread (skip if that contest is over)"),
    Always("Google Contacts",
           "take them out of their captain's contact group",
           check="contacts"),
]

LEAVE_ALONE: List[LeaveAlone] = [
    LeaveAlone(
        "Canceled Orders and Disconnects",
        "their PAST rows keep pulling into their captain's totals. Taking a "
        "closed office out mid-week silently drops that week's numbers."),
]


def code_surfaces() -> List[Code]:
    return [s for s in SURFACES if isinstance(s, Code)]


def sheet_surfaces() -> List[object]:
    return [s for s in SURFACES if isinstance(s, (SheetTab, SheetCells))]


def always_surfaces() -> List[Always]:
    return [s for s in SURFACES if isinstance(s, Always)]
