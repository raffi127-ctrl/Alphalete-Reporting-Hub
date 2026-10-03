"""Vantura Master Sales Board — the three per-campaign board tabs (2026-10-02).

ONE "Sales Board" tab that held the AT&T and BOX reps together became THREE
tabs with IDENTICAL geometry:

    NDS      "NDS Sales Board"      (the AT&T program; keeps the gold week cell)
    BOX      "BOX Sales Board"
    Verizon  "Verizon Sales Board"

NDS, NOT B2B (Carlos 2026-10-03): the AT&T program on this office's board is
called NDS now. On the SHEET that means the main tab is "NDS Sales Board"
(was "Sales Board"), the Verizon tab is "Verizon Sales Board" (was "D2D Sales
Board"), col L / Roll Call col D say "NDS" (was "B2B") and the subtotal row
reads "AT&T NDS" (was "AT&T (B2B)"). Old Roll Call rows (terminated history)
still say "B2B", and so does every backup copy, so "B2B" is a LEGACY ALIAS of
"NDS" whenever a sheet value is READ (canon_campaign), and "NDS" is what gets
WRITTEN. Nothing internal was renamed: the Slack threads ("B2B Metrics"), the
`--program B2B` flags, the order-log sources, the Tableau names and the module
names (b2b_metrics, vantura_payout_estimate.board_b2b_reps …) all still say
B2B — tab_for("B2B") simply lands on the NDS tab.

Geometry, every board: header row 4; reps from row 5; A '#', B REP, C Current
Week (=SUM(E:K)), D Last Wk, E..K Mon..Sun (INDEX-into-WeekData formulas that
the fills type over), L Campaign, M Trainer, N Field Status ('Nth Wk'), O Team,
P Leadership Status, AE start date. The rep block ends at the first TOTALS
LABEL in col B — "AT&T NDS" / "BOX" / "Verizon", each followed by "TOTAL" —
and NOT at a blank row (a cleared row inside the block is skipped, not a stop:
2026-09-14 a blank separator made week_roll see 6 reps of 46) and NOT at the
'#' column (the subtotal rows carry a number there too: 48/49/50 live).

The gold week cell is B2 on "NDS Sales Board" ONLY. On the other two boards
B2 is the formula ='NDS Sales Board'!$B$2 — read it as a value, never write
it. WeekData is shared and unchanged: key `Rep|WE` in A, Mon..Sun in B..H,
week list J:K.

Every automation that reads reps off the board goes through here, so a
re-layout (or a rename) is one fix, not nine. board_ws() opens a board by
campaign and falls back to the tab's OLD title, so code deployed before the
sheet is renamed (or run against a backup copy) still finds the boards.
"""
from __future__ import annotations

BOARD_TABS = {"NDS": "NDS Sales Board", "BOX": "BOX Sales Board",
              "Verizon": "Verizon Sales Board"}
MAIN_CAMPAIGN = "NDS"                       # the AT&T program
MAIN_TAB = BOARD_TABS[MAIN_CAMPAIGN]        # the gold week cell lives here
# Campaign labels a sheet may still carry for a program, -> today's label.
# "B2B" is what the AT&T rows said until 2026-10-03 (and what terminated
# Roll Call history still says); it reads as NDS and is never written back.
LEGACY_CAMPAIGNS = {"B2B": "NDS"}
# The tab titles each board had before 2026-10-03, tried when today's title
# is not on the sheet (a not-yet-renamed board, or a backup copy).
LEGACY_TABS = {"NDS": ("Sales Board",), "Verizon": ("D2D Sales Board",)}
# Every title a board tab has ever had — for protected-tab lists and the
# audit's formula scans, which have to recognise both spellings.
ALL_BOARD_TABS = tuple(BOARD_TABS.values()) + tuple(
    t for camp in BOARD_TABS for t in LEGACY_TABS.get(camp, ()))
# col-B labels that END the rep block (the subtotal row, then TOTAL). The old
# "at&t (b2b)" stays so the 10-2 backup copy (and a not-yet-relabelled board)
# still parse.
SUBTOTAL_LABELS = {"NDS": "AT&T NDS", "BOX": "BOX", "Verizon": "Verizon"}
LEGACY_SUBTOTAL_LABELS = {"NDS": ("AT&T (B2B)",)}
STAT_LABELS = ({v.lower() for v in SUBTOTAL_LABELS.values()}
               | {v.lower() for vs in LEGACY_SUBTOTAL_LABELS.values() for v in vs}
               | {"total"})
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

_CANON = {camp.lower(): camp for camp in BOARD_TABS}
_CANON.update({old.lower(): new for old, new in LEGACY_CAMPAIGNS.items()})


def canon_campaign(label) -> str:
    """A campaign label as a sheet (or a caller) spells it -> the label the
    board uses today: "B2B" / "b2b" / "NDS" -> "NDS", "Box" -> "BOX",
    "VERIZON" -> "Verizon". Anything else comes back stripped, as-is, so a
    campaign this module does not know ("JE", "Base") still compares equal to
    itself."""
    s = str(label or "").strip()
    return _CANON.get(s.lower(), s)


def tab_for(campaign) -> str:
    """Campaign label (as the board spells it in col L, or a program key such
    as "B2B") -> its tab. Unknown or blank -> the main "NDS Sales Board"."""
    return BOARD_TABS.get(canon_campaign(campaign), MAIN_TAB)


def campaign_of(tab: str) -> str:
    """Tab title -> campaign label ('' when it is not one of the boards).
    Knows the old titles too, so a snapshot or a sheet from before the
    2026-10-03 rename still resolves."""
    for camp, t in BOARD_TABS.items():
        if t == tab or tab in LEGACY_TABS.get(camp, ()):
            return camp
    return ""


def is_stat_label(v) -> bool:
    return str(v or "").strip().lower() in STAT_LABELS


def _retry_or_call(fn, *args, **kwargs):
    """fill._retry when it is importable (the live stack); a plain call where
    it is not (the hermetic audit tests stub that module down to open_by_key).
    """
    try:
        from automations.recruiting_report.fill import _retry
    except Exception:  # noqa: BLE001 — ImportError, or a stub without _retry
        return fn(*args, **kwargs)
    return _retry(fn, *args, **kwargs)


def board_ws(sh, campaign_or_tab):
    """The worksheet of one board, by campaign ("NDS", "B2B", "BOX",
    "Verizon") or by tab title (today's or the old one). Tries today's title
    first, then the titles that board used to have; raises the LAST lookup's
    error when none of them is on the sheet, so the caller sees the same
    WorksheetNotFound it always did."""
    camp = campaign_of(str(campaign_or_tab)) or canon_campaign(campaign_or_tab)
    if camp not in BOARD_TABS:
        # not a board at all (a caller passing some other tab through) —
        # behave like a plain worksheet lookup.
        return _retry_or_call(sh.worksheet, str(campaign_or_tab))
    titles = (BOARD_TABS[camp],) + tuple(LEGACY_TABS.get(camp, ()))
    err = None
    for title in titles:
        try:
            return _retry_or_call(sh.worksheet, title)
        except Exception as e:  # noqa: BLE001 — WorksheetNotFound, or a stub
            err = e
    raise err


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
    """Rep rows off one board's grid: [{row, name, campaign, campaign_raw,
    trainer, field, team, lead, days[7], last_wk, cur_wk, tab}],
    header-to-stat-label, blank names skipped. `campaign` is canonical (a
    legacy "B2B" row reads as "NDS"); `campaign_raw` is the cell as typed."""
    cols = columns(grid)
    end = stat_row(grid)
    reps = []
    for r in range(cols["header_row"] + 1, end):
        name = _cell(grid, r, cols["name"])
        if not name:
            continue
        raw = _cell(grid, r, cols["campaign"])
        reps.append({
            "row": r, "name": name, "tab": tab,
            "campaign": canon_campaign(raw), "campaign_raw": raw,
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
    return parse_board(_retry_or_call(ws.get, READ_RANGE), tab=ws.title)


def all_reps(sh, tabs=None) -> list:
    """Every rep on the three boards, each carrying the tab it sits on. A
    board tab that does not exist (yet) is skipped, not fatal. `tabs` may
    name campaigns or tab titles (today's or the old ones)."""
    out = []
    for key in (tabs or list(BOARD_TABS)):
        try:
            ws = board_ws(sh, key)
        except Exception:  # noqa: BLE001 — WorksheetNotFound, or a stub
            continue
        out.extend(read_board(ws))
    return out


def week_label(sh) -> str:
    """The gold week cell, as text ('10.4'), off the main board."""
    ws = board_ws(sh, MAIN_CAMPAIGN)
    return str(_retry_or_call(ws.acell, WE_CELL).value or "").strip()
