"""Destination-tab helpers for the Captainship ABP & 6-days-out fills.

The tabs in "Captainship Metrics Report - ABP and 6 days out" are the SAME
one-column-per-day layout as the Activation Rate tabs (one % per day, newest in
B, history growing right), so the column-level machinery — headroom, the daily
insert at B, the writer — is imported from that module rather than forked.
Only the two box LABELS differ, so `find_boxes` is local:

    A1  WAYNE RUDE                        <- owner name, never touched
    A2  ABP %                        B2 date (real date, 'ddd m/d/yy')
    A3  Captainship Avg              B3 %   (PERCENT 0.00%)
    A4  Rep                          B4 '%'
    A5.. rep names                   B5.. % (PERCENT 0.00%)
    ... blank spacer rows ...
    A15 % of Ongoing 6+ Days Sales   <- second box; its row number differs per
                                        tab (Sahil's is at 12, Starr's at 17),
                                        so it is ALWAYS found by label

The second box is matched on '6+ DAY', not on the full sentence — 'ABP %' is
matched on 'ABP'. Neither string can collide with a rep name or with
'Captainship Avg'.
"""
from __future__ import annotations

from automations.new_internet_churn import fill as _shared
from automations.captainship_activation_rate import fill as _act

# "Captainship Metrics Report - ABP and 6 days out" workbook. A DIFFERENT
# workbook from the Cancel/Activation one (1P95Bxz...) even though several tab
# gids match — it was duplicated from it.
SHEET_ID = "1XlHdh3OIQYmyY7VGTZWc-OK-rIlz6ClomLULyR5I0y0"

# Report slug -> tab name. Short captain names, like the Activation tabs.
TABS = {
    "wayne": "ABP & 6 days out - Wayne (ATT Fiber)",
    "starr": "ABP & 6 days out - Starr (ATT Fiber)",
    "chan":  "ABP & 6 days out - Chan (ATT Fiber)",
    "tony":  "ABP & 6 days out - Tony (ATT Fiber)",
    "sahil": "ABP & 6 days out - Sahil (ATT Fiber)",
}

# Box key -> marker substring in col A (uppercase, whitespace-normalized).
BOX_LABELS = (
    ("abp",   "ABP"),
    ("6days", "6+ DAY"),
)

_norm = _shared._norm
_has_pct = _shared._has_pct
_date_label = _shared._date_label

# Row-level and column-level ops are layout-agnostic given a `boxes` dict —
# reuse them so the two reports can't drift apart.
insert_missing_reps = _shared.insert_missing_reps
today_already_filled = _act.today_already_filled
ensure_headroom = _act.ensure_headroom
insert_one_col_at_b = _act.insert_one_col_at_b
write_today = _act.write_today


def open_ws(slug: str):
    return _shared.open_by_key(SHEET_ID).worksheet(TABS[slug])


def find_boxes(ws) -> dict:
    """Locate each box by its col-A label. Returns the churn-shaped dict
    {box: {header_row, office_avg_row, rep_header_row, rep_rows}} so every
    shared helper accepts it unchanged.

    Everything is found by LABEL, never by row number: the second box sits at a
    different row on every tab, and a rep insert moves it further down.
    """
    grid = _shared._retry(ws.get_all_values)
    col_a = [(r[0] if r else "") for r in grid]
    n_rows = len(col_a)

    found: dict = {}
    for i, label in enumerate(col_a):
        norm = _norm(label)
        for box, marker in BOX_LABELS:
            if box in found or marker not in norm:
                continue
            found[box] = i + 1          # 1-indexed sheet row
            break

    boxes: dict = {}
    ordered = sorted(found.items(), key=lambda kv: kv[1])
    for idx, (box, header_row) in enumerate(ordered):
        end_row = (ordered[idx + 1][1] - 1
                   if idx + 1 < len(ordered) else n_rows)

        # Avg row ('Captainship Avg') and rep-header row ('Rep') by LABEL —
        # a manual row insert breaks the +1/+2 offsets.
        office_avg_row = None
        rep_header_row = None
        for r in range(header_row + 1, min(end_row, n_rows) + 1):
            norm = _norm(col_a[r - 1])
            if norm == "REP":
                rep_header_row = r
                break
            if office_avg_row is None and "AVG" in norm:
                office_avg_row = r
        if rep_header_row is None:
            rep_header_row = header_row + 2
        if office_avg_row is None:
            office_avg_row = header_row + 1

        rep_rows: dict = {}
        for r in range(rep_header_row + 1, min(end_row, n_rows) + 1):
            name = col_a[r - 1].strip()
            if not name:
                continue
            norm = _norm(name)
            if norm == "REP" or "AVG" in norm:
                continue
            rep_rows[name.lower()] = r
        boxes[box] = {
            "header_row": header_row,
            "office_avg_row": office_avg_row,
            "rep_header_row": rep_header_row,
            "rep_rows": rep_rows,
        }
    return boxes
