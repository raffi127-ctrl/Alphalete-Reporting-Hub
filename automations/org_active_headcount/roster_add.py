"""Give a NEW owner a row on the 'Org Active Headcount' tab.

Eve, 2026-10-20 (Hasan Salame): a new owner goes onto the ORG Sales Board the
day of their first sale (new_owners bank), from there onto the All Campaigns
board by itself — and the Headcount tab has to follow the same day. It used to
be a manual step, because nothing on this tab ever inserted a row.

Called by new_owners.hook right after board_add puts the person on the ORG
board. Advisory: a failure here leaves the ORG board exactly as it is.

THE THREE PEOPLE BLOCKS (all found by daily.find_*, never by row number):

  1. ongoing weekly   A =A{above}+1 · B name · C =SUMIF(daily B, B, daily RUN)
                      · App Avg / WE history = frozen values
  2. daily            A =A{above}+1 · B name · day + App Avg cells = values the
                      daily run writes · RUNNING WEEK = formula · LAST/PREVIOUS
                      WEEK'S TOTALS = frozen values
  3. delta box        A =ROW()-ROW(..) · formulas read the daily block by name
                      · Record / App Avg / 'Last week' per day = values ·
                      'Campaign' + 'Org Head' helper columns = what the daily
                      run uses to pick the person's tracker

Each row is COPIED from the neighbour it pushes down (so formulas, formatting
and black-on-black columns come along) and every non-formula cell is cleared:
inheriting the neighbour's numbers would invent a headcount that never existed.
The day cells stay EMPTY, which is what tells daily.run to fill them (it only
writes empty cells) — the same morning, from the person's campaign tracker.

INSERTED AT THE LAST DATA ROW, NOT PAST IT — the same rule, for the same reason,
as all_campaigns_board.roster._insert_position: Sheets only grows a range when
the inserted row falls inside it. Every total, SUMIF and CHOOSECOLS on the tab
then widens by itself. The daily run's sort re-ranks the blocks afterwards.

    python -m automations.org_active_headcount.roster_add "Name" "ATT Fiber Team" "Rafael"          # dry run
    python -m automations.org_active_headcount.roster_add "Name" "ATT Fiber Team" "Rafael" --apply
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List, Optional

from automations.recruiting_report.fill import _retry
from automations.org_active_headcount import daily as dl

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

# ORG Sales Board section label (what the New Owners bank holds) -> the value
# the delta box's 'Campaign' column uses (daily.CAMPAIGN_SOURCE keys, cased as
# the tab writes them). A campaign missing here has no tracker on this tab
# (Retail Internet) and is skipped with a log line, not guessed.
CAMPAIGN_TAG = {
    "att fiber team": "Fiber",
    "att nds team": "NDS",
    "b2b": "B2B",
    "box": "BOX",
    "retail je": "JE",
    "retail nl": "Retail NL",
}
# Bank 'Org Head' -> the tab's 'Org Head' spelling. Anything else keeps its
# first word ('Carlos', 'Colten').
ORG_HEAD_TAG = {"rafael": "Raf", "raf": "Raf"}


def campaign_tag(label: str) -> Optional[str]:
    return CAMPAIGN_TAG.get(" ".join((label or "").lower().split()))


def org_head_tag(org_head: str) -> str:
    first = (org_head or "").strip().split(" ")[0]
    return ORG_HEAD_TAG.get(first.lower(), first.capitalize())


def _helper_col(g, sub_row: int, label: str) -> Optional[int]:
    """Column of a delta-box helper header ('Campaign' / 'Org Head') on the
    sub-header row — wherever Eve parked it."""
    row = g[sub_row - 1] if 0 < sub_row <= len(g) else []
    return next((k for k in range(1, len(row) + 1)
                 if dl._c(g, sub_row, k).lower() == label), None)


def already_on_tab(g, name: str) -> bool:
    return any(n.strip().lower() == name.strip().lower()
               for _, n, _ in dl.find_daily(g)["rows"])


def plan(g, name: str) -> Dict[str, int]:
    """{block: row to insert at}, each read off THIS grid (before any insert)."""
    od, dd, de = dl.find_ongoing(g), dl.find_daily(g), dl.find_delta(g)
    return {"ongoing": od["rows"][-1],
            "daily": dd["rows"][-1][0],
            "delta": de["rows"][-1][0]}


def _insert_and_copy(ws, at: int, width: int) -> None:
    """Insert one row at `at` and copy the row it pushed down (at + 1) onto it."""
    sid = ws.id
    _retry(ws.spreadsheet.batch_update, {"requests": [
        {"insertDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                       "startIndex": at - 1, "endIndex": at},
                             "inheritFromBefore": True}},
        {"copyPaste": {"source": {"sheetId": sid, "startRowIndex": at,
                                  "endRowIndex": at + 1, "startColumnIndex": 0,
                                  "endColumnIndex": width},
                       "destination": {"sheetId": sid, "startRowIndex": at - 1,
                                       "endRowIndex": at, "startColumnIndex": 0,
                                       "endColumnIndex": width},
                       "pasteType": "PASTE_NORMAL"}}]})


def _clean_row(ws, at: int, name: str, old_name: str, *,
               rank_chain: bool, first_row: int,
               extra: Optional[Dict[int, str]] = None) -> List[dict]:
    """Updates for the freshly copied row: name in B, the neighbour's name
    swapped out of any formula that spells it, every plain value cleared, and
    (chained blocks) the col-A rank re-linked for this row and the next."""
    t = ws.title
    f = _retry(ws.get_all_values, value_render_option="FORMULA")
    row = f[at - 1] if at - 1 < len(f) else []
    data = [{"range": f"{t}!B{at}", "values": [[name]]}]
    for c0, val in enumerate(row):
        if c0 <= 1:
            continue                                  # A (rank) / B (name)
        v = str(val)
        if v.startswith("="):
            if old_name and old_name in v:
                data.append({"range": f"{t}!{dl.A(c0 + 1)}{at}",
                             "values": [[v.replace(old_name, name)]]})
        elif v != "":
            data.append({"range": f"{t}!{dl.A(c0 + 1)}{at}", "values": [[""]]})
    for k, v in (extra or {}).items():
        data = [d for d in data if d["range"] != f"{t}!{dl.A(k)}{at}"]
        data.append({"range": f"{t}!{dl.A(k)}{at}", "values": [[v]]})
    if rank_chain:
        # The pasted '=A{above}+1' is already right for `at`; the row pushed to
        # at + 1 still names the cell above the insert, so it would repeat the
        # number. Re-link it (all_campaigns_board.roster._rank_col_a).
        data.append({"range": f"{t}!A{at}",
                     "values": [[1 if at == first_row else f"=A{at - 1}+1"]]})
        data.append({"range": f"{t}!A{at + 1}", "values": [[f"=A{at}+1"]]})
    return data


def add_owner(ws, name: str, campaign_label: str, org_head: str, *,
              dry_run: bool = True, logfn=print) -> dict:
    """Add `name` to the three blocks. Returns {'status': ..., rows...}.
    status: 'added' | 'would_add' | 'already' | 'no_campaign'."""
    tag = campaign_tag(campaign_label)
    if not tag:
        logfn(f"  headcount: {name} — campaign {campaign_label!r} has no "
              f"tracker on the Headcount tab; not added")
        return {"status": "no_campaign"}
    head = org_head_tag(org_head)
    g = _retry(ws.get_all_values)
    if already_on_tab(g, name):
        logfn(f"  headcount: {name} already has a row — nothing to do")
        return {"status": "already"}
    p = plan(g, name)
    if dry_run:
        logfn(f"  headcount (dry-run): would add {name} [{tag} / {head}] -> "
              f"weekly row {p['ongoing']}, daily row {p['daily']}, delta row "
              f"{p['delta']} (each pushes that block's last row down one)")
        return {"status": "would_add", **p}

    width = max(len(r) for r in g)
    done: Dict[str, int] = {}

    # Lowest block first, re-reading the grid after every insert so each block
    # is located on true row numbers, not adjusted arithmetically.
    # ---- 3. delta box
    g = _retry(ws.get_all_values)
    de = dl.find_delta(g)
    at = de["rows"][-1][0]
    old = de["rows"][-1][1]
    _insert_and_copy(ws, at, width)
    time.sleep(1)
    g = _retry(ws.get_all_values)
    extra = {}
    for label, val in (("campaign", tag), ("org head", head)):
        k = _helper_col(g, de["sub"], label)
        if k:
            extra[k] = val
        else:
            logfn(f"  ⚠ headcount: no '{label}' column in the delta box — "
                  f"{name}'s is not set; the daily run may not find a tracker")
    _retry(ws.spreadsheet.values_batch_update, {
        "valueInputOption": "USER_ENTERED",
        "data": _clean_row(ws, at, name, old, rank_chain=False, first_row=0,
                           extra=extra)})
    done["delta_row"] = at

    # ---- 2. daily block
    g = _retry(ws.get_all_values)
    dd = dl.find_daily(g)
    at, old = dd["rows"][-1][0], dd["rows"][-1][1]
    _insert_and_copy(ws, at, width)
    time.sleep(1)
    _retry(ws.spreadsheet.values_batch_update, {
        "valueInputOption": "USER_ENTERED",
        "data": _clean_row(ws, at, name, old, rank_chain=True,
                           first_row=dd["rows"][0][0])})
    done["daily_row"] = at

    # ---- 1. ongoing weekly block
    g = _retry(ws.get_all_values)
    od = dl.find_ongoing(g)
    at = od["rows"][-1]
    old = dl._c(g, at, 2)
    _insert_and_copy(ws, at, width)
    time.sleep(1)
    _retry(ws.spreadsheet.values_batch_update, {
        "valueInputOption": "USER_ENTERED",
        "data": _clean_row(ws, at, name, old, rank_chain=True,
                           first_row=od["rows"][0])})
    done["weekly_row"] = at

    logfn(f"  headcount: + {name} [{tag} / {head}] -> weekly row "
          f"{done['weekly_row']}, daily row {done['daily_row']}, delta row "
          f"{done['delta_row']}; the daily run fills the days")
    return {"status": "added", **done}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name")
    ap.add_argument("campaign", help="ORG board section, e.g. 'ATT Fiber Team'")
    ap.add_argument("org_head", help="e.g. 'Rafael', 'Carlos', 'Colten'")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sandbox", action="store_true",
                    help=f"write {dl.SANDBOX_TAB!r} instead of the live tab")
    a = ap.parse_args(argv)
    ws = dl.open_tab(sandbox=a.sandbox)
    res = add_owner(ws, a.name, a.campaign, a.org_head, dry_run=not a.apply)
    return 0 if res["status"] in ("added", "would_add", "already") else 1


if __name__ == "__main__":
    sys.exit(main())
