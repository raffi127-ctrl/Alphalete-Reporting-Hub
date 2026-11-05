"""The "2R Contacts" tab: which owners get the sync, and where."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import List, Optional

from automations.second_round_contacts import config as C


@dataclass
class Owner:
    row: int                    # sheet row (1-based)
    owner: str
    office: str
    account: str
    active: bool
    ov_campaign: str
    start: Optional[dt.date]
    notes: str
    # Every office to read, current one first (`office` is always offices[0]).
    offices: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.offices = self.offices or [self.office]

    @property
    def label(self) -> str:
        return "%s (office %s -> %s)" % (self.owner, ", ".join(self.offices), self.account)


def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip()


def parse_rows(values: List[List[str]]) -> List[Owner]:
    """Sheet values (header row first) -> Owners. Columns found by header
    text; rows with no owner, office or email are ignored."""
    if not values:
        return []
    hdr = [_norm(h).lower() for h in values[0]]

    def col(name):
        key = name.lower()
        return hdr.index(key) if key in hdr else None

    ci = {h: col(h) for h in C.ROSTER_HEADERS}
    out: List[Owner] = []
    for i, r in enumerate(values[1:], start=2):
        def at(h):
            k = ci.get(h)
            return _norm(r[k]) if k is not None and k < len(r) else ""
        owner, office, account = at("Owner"), at("ApplicantStream Office ID"), at("Reception Email")
        if not (owner and office and account):
            continue
        start = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                start = dt.datetime.strptime(at("Start Date"), fmt).date()
                break
            except ValueError:
                continue
        # "24232, 24153" = moved to a new funnel: the new office first, then the
        # old one, which keeps being read while people still finish there.
        offices = re.findall(r"\d+", office) or [office]
        out.append(Owner(row=i, owner=owner, office=offices[0], offices=offices,
                         account=account.lower(),
                         active=at("Active").lower() in ("yes", "y", "true", "on"),
                         ov_campaign=at("OwnerVille Campaign") or C.DEFAULT_OV_CAMPAIGN,
                         start=start, notes=at("Notes")))
    return out


def open_tab(create: bool = True):
    """The roster worksheet on the Org workbook (created with headers and a
    Yes/No dropdown on Active when missing). Never cleared."""
    from automations.recruiting_report.fill import _retry, open_by_key
    from automations.org_sales_board.run import SHEET_ID
    ss = open_by_key(SHEET_ID)
    for w in ss.worksheets():
        if _norm(w.title).lower() == C.ROSTER_TAB.lower():
            return w
    if not create:
        return None
    ws = _retry(ss.add_worksheet, title=C.ROSTER_TAB, rows=100, cols=len(C.ROSTER_HEADERS))
    _retry(ws.update, [C.ROSTER_HEADERS], "A1")
    n = len(C.ROSTER_HEADERS)
    _retry(ss.batch_update, {"requests": [
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": n},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.9, "blue": 0.97}}},
                        "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
        {"setDataValidation": {"range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": 100, "startColumnIndex": 3, "endColumnIndex": 4},
                               "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Yes"}, {"userEnteredValue": "No"}]},
                                        "showCustomUi": True, "strict": False}}},
        {"updateSheetProperties": {"properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
    ]})
    return ws


def read(ws=None) -> List[Owner]:
    from automations.recruiting_report.fill import _retry
    ws = ws or open_tab()
    return parse_rows(_retry(ws.get_all_values))


def stamp(ws, owner: Owner, result: str, when: Optional[dt.datetime] = None) -> None:
    """Last Run / Last Result on the owner's row (the only cells we write)."""
    from automations.recruiting_report.fill import _retry
    when = when or dt.datetime.now()
    hdr = [_norm(h).lower() for h in _retry(ws.row_values, 1)]
    try:
        c_run, c_res = hdr.index("last run") + 1, hdr.index("last result") + 1
    except ValueError:
        return
    _retry(ws.update_cell, owner.row, c_run, when.strftime("%m/%d/%Y %H:%M"))
    _retry(ws.update_cell, owner.row, c_res, result[:200])
