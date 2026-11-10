"""Each office's own Digi Docs bundle choices.

Megan, 2026-11-09: *"Digi docs + Owner Submit - when an icd enrolls we should
ask them this question to make sure we send it right for them specifically."*

WHY THIS EXISTS. `config.py` holds ALPHALETE's four answers -- the campaign, the
bundle type, the bundle, the commission bundle -- as plain constants, with a
note on BUNDLE_TYPE saying "a wireless or retail office will want a different
one — that is the day someone comes looking for this constant". This is that
day. An ICD sending Alphalete's bundle is not a near miss; it is a different
contract mailed to a real person, and `BUNDLE_EXPECT_SINGLE_OPTION` exists
because picking row one of a list that quietly grew is how that happens.

WHERE THE ANSWERS LIVE: the **Office Settings** tab of the relay workbook, one
row per office, beside the State/City/AppStream answers setup already collects.
Not a dict in code -- an owner enrolling at 9pm cannot edit a Python file, and
the relay already owns this tab.

READ BY HEADER NAME, NEVER BY POSITION. That tab gained an `Owner` column from
another session on 2026-11-06 and a position-based read returned the wrong cell
silently ([[feedback_no_hardcoded_columns]]).

AN UNANSWERED OFFICE IS REFUSED, NOT DEFAULTED. Falling back to Alphalete's
answers is exactly the failure this prevents, so `for_office` raises and the
caller stops. The ONE exception is Alphalete itself, whose answers are the
constants by definition.

WHAT IS ASKED AND WHAT IS DERIVED. Only two of the four are real questions:

  * **Campaign** -- already collected as `ov_program`; it also decides which
    bundles exist, since the bundle list is per campaign.
  * **Bundle type** -- a real choice (door-to-door vs wireless vs retail).
  * **Bundle** -- NOT asked. Under a bundle type the dropdown holds exactly one
    real option, and `BUNDLE_EXPECT_SINGLE_OPTION` already refuses rather than
    guessing when it holds more. Asking an owner to retype a string the page
    can read is the kind of input this codebase does not do.
  * **Commission bundle** -- a real choice, because it is the office's own pay
    agreement and no page can infer it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

TAB = "Office Settings"

# The tab's column headings for each answer. Changed here and nowhere else.
COL_OFFICE = "Office"
COL_CAMPAIGN = "OV Campaign"
COL_BUNDLE_TYPE = "Bundle Type"
COL_BUNDLE = "Bundle"
COL_COMMISSION = "Commission Bundle"

ANSWER_COLUMNS = (COL_CAMPAIGN, COL_BUNDLE_TYPE, COL_BUNDLE, COL_COMMISSION)

# Alphalete's own office key. Its answers are config.py's constants -- it is
# the office they were written for.
HOUSE = "raf"


class NotAnswered(RuntimeError):
    """This office has never been asked. The caller must stop, not default."""


@dataclass(frozen=True)
class Bundle:
    office: str
    campaign: str
    bundle_type: str
    bundle: str                 # "" means: read it off the page (single option)
    commission: tuple           # labels to TICK; everything else is left alone

    def missing(self) -> List[str]:
        out = []
        if not self.campaign:
            out.append(COL_CAMPAIGN)
        if not self.bundle_type:
            out.append(COL_BUNDLE_TYPE)
        if not self.commission:
            out.append(COL_COMMISSION)
        return out


def _house() -> Bundle:
    from automations.digi_docs import config as C
    return Bundle(office=HOUSE, campaign=C.ADD_CAMPAIGN,
                  bundle_type=C.BUNDLE_TYPE, bundle=C.BUNDLE,
                  commission=tuple(C.COMMISSION_BUNDLES_TICK))


def _rows(book=None) -> List[Dict[str, str]]:
    """Office Settings as {header: value} rows. [] when it cannot be read."""
    try:
        if book is None:
            from automations.icd_alerts import post as P
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        grid = book.worksheet(TAB).get_all_values()
    except Exception:          # noqa: BLE001 — no tab yet is not an error here
        return []
    if not grid:
        return []
    head = [str(h).strip() for h in grid[0]]
    out = []
    for r in grid[1:]:
        out.append({h: (r[i].strip() if i < len(r) else "")
                    for i, h in enumerate(head) if h})
    return out


def for_office(office_key: str, book=None) -> Bundle:
    """That office's answers. RAISES when it has not been asked.

    Never falls back to Alphalete's: a bundle is a contract, and the wrong one
    is mailed to a real person before anybody notices.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        raise NotAnswered("no office given")
    if key == HOUSE:
        return _house()
    for r in _rows(book):
        if r.get(COL_OFFICE, "").strip().lower() != key:
            continue
        got = Bundle(
            office=key,
            campaign=r.get(COL_CAMPAIGN, ""),
            bundle_type=r.get(COL_BUNDLE_TYPE, ""),
            bundle=r.get(COL_BUNDLE, ""),
            commission=tuple(x.strip() for x in r.get(COL_COMMISSION, "").split("|")
                             if x.strip()),
        )
        missing = got.missing()
        if missing:
            raise NotAnswered(
                "%s has no %s on the %s tab. Run the setup question on that "
                "office's computer — its OwnerVille is the only place the real "
                "choices can be read." % (key, ", ".join(missing), TAB))
        return got
    raise NotAnswered(
        "%s is not on the %s tab at all, so its bundle choices have never been "
        "asked. Nothing is sent." % (key, TAB))


def answered(office_key: str, book=None) -> bool:
    """True when this office could send today. Never raises."""
    try:
        for_office(office_key, book)
        return True
    except Exception:          # noqa: BLE001
        return False


def save(office_key: str, *, campaign: str = "", bundle_type: str = "",
         bundle: str = "", commission=(), book=None, log=print) -> bool:
    """Write an office's answers onto the tab. Only the ones given.

    BY HEADER, and a column the tab does not have yet is ADDED rather than
    written over whatever happens to sit in that position. Other sessions edit
    this tab; nothing here touches a column it does not own.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        return False
    try:
        if book is None:
            from automations.icd_alerts import post as P
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        ws = book.worksheet(TAB)
        grid = ws.get_all_values()
    except Exception as e:     # noqa: BLE001
        log("  office settings not readable: %s" % type(e).__name__)
        return False
    if not grid:
        return False
    head = [str(h).strip() for h in grid[0]]

    want = {}
    if campaign:
        want[COL_CAMPAIGN] = campaign
    if bundle_type:
        want[COL_BUNDLE_TYPE] = bundle_type
    if bundle:
        want[COL_BUNDLE] = bundle
    if commission:
        want[COL_COMMISSION] = " | ".join(commission)
    if not want:
        return False

    # Add any heading the tab does not carry yet, at the end.
    for name in want:
        if name not in head:
            head.append(name)
            ws.update_cell(1, len(head), name)

    at = next((i for i, r in enumerate(grid[1:], start=2)
               if r and r[0].strip().lower() == key), None)
    if at is None:
        at = len(grid) + 1
        ws.update_cell(at, head.index(COL_OFFICE) + 1, key)
    for name, value in want.items():
        ws.update_cell(at, head.index(name) + 1, value)
    log("  saved %s for %s" % (", ".join(sorted(want)), key))
    return True
