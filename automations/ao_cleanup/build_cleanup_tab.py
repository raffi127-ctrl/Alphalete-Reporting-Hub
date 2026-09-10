"""Fill the 'AO Workspace Cleanup' tab so Rafael only has to tick boxes.

The worklist is NOT "everyone in Slack" -- it's every rep on the 'Terminated
Reps' tab whose `Slack Deact` column is not TRUE. Those are the people the
office already let go and nobody ever confirmed out of the AO workspace
(ao-pbns.slack.com). 2026-09-10: 2687 terminated rows, 1848 confirmed
deactivated; the rest is the backlog this tab exists to clear.

Column B ('Channel') is left blank on purpose. Listing which channels someone
is still in needs a Slack token with `channels:read` + `groups:read` +
`users:read`; the token on this machine (Evelyn's xoxp) carries only
identify/history/write scopes, so anything written there would be a guess.
`fill_channels.py` fills column B once such a token or export exists.

Run:
    python -m automations.ao_cleanup.build_cleanup_tab --dry-run
    python -m automations.ao_cleanup.build_cleanup_tab --tab "AO Cleanup SANDBOX"
    python -m automations.ao_cleanup.build_cleanup_tab
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

from automations.brand_audit.sheets import client

WORKBOOK_KEY = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"  # All in One Local Office - Raf
SOURCE_TAB = "Terminated Reps"
TARGET_TAB = "AO Workspace Cleanup"

# Read 'Terminated Reps' by HEADER LABEL, never by index: a column inserted
# upstream must not silently shift the read (CLAUDE.md).
SRC_NAME = "Rep Name"
SRC_LEAD = "Lead Rep"
SRC_DAYS = "# Days Worked"
SRC_TERM = "Termination Date WE"
SRC_OV = "Ownerville"
SRC_DEACT = "Slack Deact"
SRC_NOTES = "Notes"
SRC_YEAR = "Year"

# A-E are Eve's original columns; F onward is the context Rafael needs so he can
# decide without opening a second tab.
HEADERS = [
    "Rep Name", "Channel", "Remove from channel", "Remove from AO", "Notes",
    "Termination Date", "Lead Rep", "Days Worked", "Slack Deact (hoy)",
    "Dias desde baja",
]
FIRST_DATA_ROW = 2


def _norm_name(raw):
    """'Christian<TAB>Williams' / doubled spaces -> 'Christian Williams'."""
    return re.sub(r"\s+", " ", (raw or "").replace("\t", " ")).strip()


_SHEETS_EPOCH = dt.date(1899, 12, 30)  # Google's day 0


def _parse_date(raw):
    """Accepts 8/6/2024, 2024-08-06 and the bare serial (45686) some rows carry
    because their cell was never date-formatted."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    if re.match(r"^\d{5}(\.\d+)?$", raw):          # Sheets serial
        return _SHEETS_EPOCH + dt.timedelta(days=int(float(raw)))
    return None


def read_terminated(sh):
    # type: (...) -> List[dict]
    ws = sh.worksheet(SOURCE_TAB)
    values = ws.get_values()
    if not values:
        raise RuntimeError("'%s' came back empty" % SOURCE_TAB)
    header = [h.strip() for h in values[0]]
    idx = {}
    for label in (SRC_NAME, SRC_LEAD, SRC_DAYS, SRC_TERM, SRC_OV, SRC_DEACT,
                  SRC_NOTES, SRC_YEAR):
        if label not in header:
            raise RuntimeError("'%s' has no '%s' column (found: %s)"
                               % (SOURCE_TAB, label, header))
        idx[label] = header.index(label)

    def cell(row, label):
        i = idx[label]
        return row[i].strip() if i < len(row) else ""

    out = []
    for row in values[1:]:
        name = _norm_name(cell(row, SRC_NAME))
        if not name:
            continue
        out.append({
            "name": name,
            "lead": cell(row, SRC_LEAD),
            "days": cell(row, SRC_DAYS),
            "term_raw": cell(row, SRC_TERM),
            "term": _parse_date(cell(row, SRC_TERM)),
            "ownerville": cell(row, SRC_OV),
            "deact": cell(row, SRC_DEACT),
            "notes": cell(row, SRC_NOTES),
            "year": cell(row, SRC_YEAR),
        })
    return out


def pending(rows):
    # type: (List[dict]) -> List[dict]
    """Everyone whose Slack removal was never confirmed (Slack Deact != TRUE).

    One row per PERSON: a rehire terminated twice is still one Slack account,
    and two rows means Rafael ticks the same human twice. The most recent
    termination wins; the earlier ones are counted into Notes.
    """
    todo = [r for r in rows if r["deact"].strip().upper() != "TRUE"]
    by_name = {}  # type: Dict[str, dict]
    for r in todo:
        key = r["name"].casefold()
        prev = by_name.get(key)
        if prev is None:
            by_name[key] = dict(r, dupes=0)
            continue
        prev["dupes"] += 1
        if r["term"] and (not prev["term"] or r["term"] > prev["term"]):
            by_name[key] = dict(r, dupes=prev["dupes"])
    return sorted(by_name.values(),
                  key=lambda r: (r["term"] or dt.date(1900, 1, 1),
                                 r["name"].casefold()))


def build_rows(people, today, channels=None):
    # type: (List[dict], dt.date, Optional[Dict[str, str]]) -> List[list]
    channels = channels or {}
    out = []
    for p in people:
        age = (today - p["term"]).days if p["term"] else ""
        notes = []
        if p["notes"]:
            notes.append(p["notes"])
        if p["dupes"]:
            notes.append("terminado %d vez(ces) mas" % p["dupes"])
        if p["ownerville"].strip().upper() == "FALSE":
            notes.append("sigue en Ownerville")
        out.append([
            p["name"],
            channels.get(p["name"].casefold(), ""),
            False,
            False,
            " | ".join(notes),
            # normalised: a few source rows hold the bare serial, not a date
            p["term"].strftime("%m/%d/%Y") if p["term"] else p["term_raw"],
            p["lead"],
            p["days"],
            p["deact"] or "(vacio)",
            age,
        ])
    return out


def _checkbox_request(sheet_id, last_row):
    """Real checkboxes on C/D for EVERY data row (the tab only had 498)."""
    return {
        "setDataValidation": {
            "range": {"sheetId": sheet_id,
                      "startRowIndex": FIRST_DATA_ROW - 1, "endRowIndex": last_row,
                      "startColumnIndex": 2, "endColumnIndex": 4},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True},
        }
    }


def write_tab(sh, tab, rows, clear_extra=True):
    # type: (...) -> Tuple[int, str]
    ws = sh.worksheet(tab)
    needed = FIRST_DATA_ROW + len(rows) - 1
    if ws.row_count < needed:
        ws.add_rows(needed - ws.row_count)
    ws.update(values=[HEADERS], range_name="A1:J1",
                  value_input_option="USER_ENTERED")
    if rows:
        ws.update(values=rows,
                  range_name="A%d:J%d" % (FIRST_DATA_ROW, needed),
                  value_input_option="USER_ENTERED")
    if clear_extra and ws.row_count > needed:
        ws.batch_clear(["A%d:J%d" % (needed + 1, ws.row_count)])
    sh.batch_update({"requests": [
        _checkbox_request(ws.id, needed),
        {"updateSheetProperties": {
            "properties": {"sheetId": ws.id,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
    ]})
    return needed, ws.title


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fill the AO Workspace Cleanup tab")
    ap.add_argument("--tab", default=TARGET_TAB,
                    help="target tab (point at a duplicate while testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be written, touch nothing")
    ap.add_argument("--limit", type=int, default=0, help="first N people only")
    args = ap.parse_args(argv)

    sh = client().open_by_key(WORKBOOK_KEY)
    everyone = read_terminated(sh)
    people = pending(everyone)
    if args.limit:
        people = people[:args.limit]
    rows = build_rows(people, dt.date.today())

    deact = sum(1 for r in everyone if r["deact"].strip().upper() == "TRUE")
    print("terminated rows read : %d" % len(everyone))
    print("already Slack-deact  : %d" % deact)
    print("pending (this tab)   : %d personas" % len(rows))
    if rows:
        print("mas vieja : %s  %s" % (rows[0][5] or "sin fecha", rows[0][0]))
        print("mas nueva : %s  %s" % (rows[-1][5] or "sin fecha", rows[-1][0]))
    if args.dry_run:
        print("\n-- dry run, nothing written --")
        for r in rows[:10]:
            print(r)
        return 0
    last, title = write_tab(sh, args.tab, rows)
    print("\nwrote A1:J%d on '%s'" % (last, title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
