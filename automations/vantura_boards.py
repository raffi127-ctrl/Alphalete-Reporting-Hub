"""Vantura Master Sales Board — the three per-campaign board tabs (2026-10-02).

ONE "Sales Board" tab that held the B2B and BOX reps together became THREE
tabs with IDENTICAL geometry:

    B2B      "Sales Board"       (name unchanged — and it keeps the gold week cell)
    BOX      "BOX Sales Board"   (new)
    Verizon  "D2D Sales Board"   (existed before; now the same mechanics)

Geometry, every board: header row 4; reps from row 5; A '#', B REP, C Current
Week (=SUM(E:K)), D Last Wk, E..K Mon..Sun (INDEX-into-WeekData formulas that
the fills type over), L Campaign, M Trainer, N Field Status ('Nth Wk'), O Team,
P Leadership Status, AE start date. The rep block ends at the first TOTALS
LABEL in col B — "AT&T (B2B)" / "BOX" / "Verizon", each followed by "TOTAL" —
and NOT at a blank row (a cleared row inside the block is skipped, not a stop:
2026-09-14 a blank separator made week_roll see 6 reps of 46) and NOT at the
'#' column (the subtotal rows carry a number there too: 48/49/50 live).

The gold week cell is B2 on "Sales Board" ONLY. On the other two boards B2 is
the formula ='Sales Board'!$B$2 — read it as a value, never write it. WeekData
is shared and unchanged: key `Rep|WE` in A, Mon..Sun in B..H, week list J:K.

Every automation that reads reps off the board goes through here, so a
re-layout is one fix, not nine.
"""
from __future__ import annotations

BOARD_TABS = {"B2B": "Sales Board", "BOX": "BOX Sales Board",
              "Verizon": "D2D Sales Board"}
MAIN_TAB = BOARD_TABS["B2B"]                 # the gold week cell lives here
# col-B labels that END the rep block (the subtotal row, then TOTAL)
STAT_LABELS = {"at&t (b2b)", "box", "verizon", "total"}
SUBTOTAL_LABELS = {"B2B": "AT&T (B2B)", "BOX": "BOX", "Verizon": "Verizon"}
# Belt and braces: if a board ever loses its subtotal row, the '% on the
# Board' block is the next thing in col B and must never read as a rep.
_END_LABELS = STAT_LABELS | {"% on the board"}

HEADER_ROW, FIRST_REP_ROW = 4, 5
WE_CELL = "B2"
READ_RANGE = "A1:AE200"       # wide enough for any roster; the parse stops itself

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]
HEADERS = {"name": "REP", "cur_wk": "Current Week", "last_wk": "Last Wk",
           "campaign": "Campaign", "trainer": "Trainer",
           "field": "Field Status", "team": "Team",
           "lead": "Leadership Status"}
# 1-based columns to fall back on when a header is missing (the live layout)
FALLBACK = {"name": 2, "cur_wk": 3, "last_wk": 4, "campaign": 12,
            "trainer": 13, "field": 14, "team": 15, "lead": 16}
FALLBACK_DAYS = [5, 6, 7, 8, 9, 10, 11]


def tab_for(campaign) -> str:
    """Campaign label (as the board spells it in col L) -> its tab. Unknown or
    blank -> the main "Sales Board"."""
    key = str(campaign or "").strip().lower()
    for camp, tab in BOARD_TABS.items():
        if camp.lower() == key:
            return tab
    return MAIN_TAB


def campaign_of(tab: str) -> str:
    """Tab title -> campaign label ('' when it is not one of the boards)."""
    for camp, t in BOARD_TABS.items():
        if t == tab:
            return camp
    return ""


def is_stat_label(v) -> bool:
    return str(v or "").strip().lower() in STAT_LABELS


def _cell(grid, r: int, c: int) -> str:
    row = grid[r - 1] if 0 < r <= len(grid) else []
    return str(row[c - 1]).strip() if 0 < c <= len(row) else ""


def header_row(grid) -> int:
    """1-based row carrying the 'REP' header (0 when absent)."""
    for r in range(1, min(len(grid), 8) + 1):
        for c in range(1, len(grid[r - 1]) + 1):
            if _cell(grid, r, c).lower() == HEADERS["name"].lower():
                return r
    return 0


def columns(grid) -> dict:
    """{field: 1-based column} found by the header row's labels, falling back
    to the live layout for anything that is not labelled."""
    hr = header_row(grid)
    hdr = {}
    if hr:
        for c in range(1, len(grid[hr - 1]) + 1):
            hdr.setdefault(_cell(grid, hr, c).lower(), c)
    cols = {k: hdr.get(v.lower(), FALLBACK[k]) for k, v in HEADERS.items()}
    cols["days"] = [hdr.get(d.lower(), FALLBACK_DAYS[i])
                    for i, d in enumerate(DAYS)]
    cols["header_row"] = hr or HEADER_ROW
    return cols


def stat_row(grid) -> int:
    """1-based row of the first totals label in col B below the header — the
    subtotal row that ends the rep block. len(grid) + 1 when there is none."""
    cols = columns(grid)
    for r in range(cols["header_row"] + 1, len(grid) + 1):
        if _cell(grid, r, cols["name"]).lower() in _END_LABELS:
            return r
    return len(grid) + 1


def parse_board(grid, tab: str = "") -> list:
    """Rep rows off one board's grid: [{row, name, campaign, trainer, field,
    team, lead, days[7], last_wk, cur_wk, tab}], header-to-stat-label, blank
    names skipped."""
    cols = columns(grid)
    end = stat_row(grid)
    reps = []
    for r in range(cols["header_row"] + 1, end):
        name = _cell(grid, r, cols["name"])
        if not name:
            continue
        reps.append({
            "row": r, "name": name, "tab": tab,
            "campaign": _cell(grid, r, cols["campaign"]),
            "trainer": _cell(grid, r, cols["trainer"]),
            "field": _cell(grid, r, cols["field"]),
            "team": _cell(grid, r, cols["team"]),
            "lead": _cell(grid, r, cols["lead"]),
            "days": [_cell(grid, r, c) for c in cols["days"]],
            "last_wk": _cell(grid, r, cols["last_wk"]),
            "cur_wk": _cell(grid, r, cols["cur_wk"]),
        })
    return reps


def read_board(ws) -> list:
    """parse_board over the live tab (one read, A1:AE200)."""
    from automations.recruiting_report.fill import _retry
    return parse_board(_retry(ws.get, READ_RANGE), tab=ws.title)


def all_reps(sh, tabs=None) -> list:
    """Every rep on the three boards, each carrying the tab it sits on. A
    board tab that does not exist (yet) is skipped, not fatal."""
    from automations.recruiting_report.fill import _retry
    out = []
    for tab in (tabs or BOARD_TABS.values()):
        try:
            ws = _retry(sh.worksheet, tab)
        except Exception:  # noqa: BLE001 — WorksheetNotFound, or a stub
            continue
        out.extend(read_board(ws))
    return out


def week_label(sh) -> str:
    """The gold week cell, as text ('10.4'), off the main board."""
    from automations.recruiting_report.fill import _retry
    ws = _retry(sh.worksheet, MAIN_TAB)
    return str(_retry(ws.acell, WE_CELL).value or "").strip()
