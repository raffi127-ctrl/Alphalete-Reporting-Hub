"""Raf's %-commission workbook (Raf Loom 2026-11-23; Maud owns the build).

Raf pays his local-office reps a % of the revenue they bring in. From the ORG
DD Detail crosstab this builds an .xlsx with:

  Edited    the columns Raf keeps, sorted by rep. Rule notes (Sunday internet,
            carried-over new-start sales) go in Description Detail. cl.Category WEARABLES /
            TABLET copied into the empty cl.Product cell.
  Reps Name & Commission payout
            A Rep | B % (yellow, editable) | C Revenue | D Total Payout |
            E Level / Rule (+ lost-leadership reason) | F Lost Leadership
            Pay checkbox, Level 1-3 only (ticked = 35%) |
            G Sunday Internet Revenue | H Commission | I Guarantee |
            J Base Pay | K Bonus | L Gas Bonus.   D = MAX(H, I) + J + K + L.
  <rep>     one tab per paid rep: the payout details that apply to them
            (nothing 0 / blank / "No"; no Level / Rule), their sales, then
            their Pending / Disconnect / Cancel lines from Lucy's Order Log.
            No tab for held new starts or reps not on the last 2 boards.
  Raw       Raf's office rows untouched. ALWAYS present - require_raw()
            refuses to save a workbook without it.

THE % RULES (Maud 2026-11-24, "How You Get Paid" grid). First match wins:

  1  NEW START HELD — in the New Starts box of the board 3 boards back (DD
     week Sunday - 14 days). % blank, purple. Their sales are carried onto
     NEXT week's sheet (pass the previous week's sheet as carry_from).
  2  SPECIAL DEAL — SPECIAL_PCT (Willie Henderson, Chloe Johnson, Bas El
     Hassan, Thomas Crenshaw, Algemar Kennel 70%; Amjad Malhas 85%), every week.
  3  LINKEDIN — 'Linkedin' in the board's "Add applied to" column (DY) on
     either of the last 2 boards -> 70%.
  4  BOARD LEVEL — Leadership Status on the last 2 boards (newest first):
     In Training / Entry 35%, Level 1/2/3 40%, Mastermind 70%.
     LOST LEADERSHIP PAY: a Level 1/2/3 rep who was 'Late' on the Saturday
     roll call of the DD week's board, or 'Late' 2+ times that week, gets 35%
     (reason in E, box in F ticked). Every Level 1-3 rep has the box:
     tick it to drop them to 35%, untick to restore their level %. Pink row
     while ticked. Other levels have no box.
  5  otherwise — not on the last 2 boards, or in the New Starts box with no
     level: % blank, orange.

  GUARANTEE: the board's "Guarantee" column (DZ on WE 11.29) on the last 2
  boards -> they get the higher of the guarantee or their commission, even
  with no sales. A new start with a guarantee is never held. Green row,
  except LinkedIn reps (Maud 11/24: they don't need the green).
  GAS BONUS: board "Gas Bonus" column (DX) on the last 2 boards: "$100" is
  paid as is; "$100 if 5+ apps" only with 5+ apps (= distinct customers on
  the rep's DD lines this week).
  BASE PAY + BONUS (BASE_PAY / BONUS_ROWS): Bas El Hassan $1,000 + "Bas'
  Total Bonus" + 70% commission; Algemar Kennel $1,000 + "Algemar's 5% from
  everyone else's Gross Profit" + 70% commission if any; Willie Henderson + "Willie's
  Partner Pay". Bonuses come from "RAF PNL 2026 (NEW)" (All in One - Raf),
  the column for the week before the DD week (DD WE 11/22 -> WE 11/15),
  found by row label so inserted rows don't break it.
  SUNDAY INTERNET: new-internet lines (Internet 25/300/500/1000/5000, not
  upgrades) with a Sunday sale date pay 85% (or the rep's % if higher).
  NO REP: DD lines with no rep get their own row named by what they are
  (e.g. 'Port Line'), % blank, grey. Captain Bonus lines are left out.

Every DD line of a rep counts (bonuses and chargebacks included). "Last 2
boards" = the two newest 'Sales Board WE m.d' tabs up to this week's Sunday.

    python -m automations.commission_sheet.pct_payout --out output/x.xlsx
    python -m automations.commission_sheet.pct_payout --dd-file dd.csv --out x.xlsx
    python -m automations.commission_sheet.pct_payout --dd-file dd.csv --out x.xlsx \\
        --carry-from <last week's RH sheet id>
    python -m automations.commission_sheet.pct_payout --restyle old.xlsx --out new.xlsx
"""
import argparse
import collections
import colorsys
import datetime as dt
import re
import unicodedata
from pathlib import Path

from automations.commission_sheet.sources import read_crosstab
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

CORP_PREFIX = "Alphalete Marketing Inc"   # Raf's local office (11479)
OWNER = "Hidalgo"

EDITED_COLS = [  # (header shown, source column)  — names per Maud 2026-11-23
    ("Rep Full Name", "REP.Name"),
    ("Sale Date", "cl.Sale Date"),
    ("Activation Date", "cl.Activation Date"),
    ("Product", "cl.Product"),
    ("Description", "cl.Description"),
    ("Tier", "cl.Tier"),
    ("Description Detail", "cl.Description Detail"),
    ("Order Type", "cl.Order Type"),
    ("Customer Name", "cl.Customer Name"),
    ("Total $ to ICD", "Total $ to ICD"),
]
#: Rule notes (Sunday internet, carried over) go in this column — no separate
#: Note column (Maud 2026-11-24).
NOTE_COL = "Description Detail"
#: Old Tableau-style headers -> new ones, so --restyle can fix workbooks built
#: before the rename (e.g. the WE 11.14 sample).
OLD_HEADERS = {"REP.Full Name": "Rep Full Name", "cl.Sale Date": "Sale Date",
               "cl.Activation Date": "Activation Date", "cl.Product": "Product",
               "cl.Description": "Description", "cl.Tier": "Tier",
               "cl.Description Detail": "Description Detail",
               "cl.Order Type": "Order Type", "cl.Customer Name": "Customer Name"}
MOVE_TO_PRODUCT = {"WEARABLES", "TABLET"}

# --- the % rules ------------------------------------------------------------
LEVEL_PCT = {
    "in training": 0.35,
    "entry level": 0.35,
    "level 1": 0.40,
    "level 2": 0.40,
    "level 3": 0.40,
    "mastermind": 0.70,
}
#: Levels that lose leadership pay (drop to LOST_LEADERSHIP_PCT).
LEADER_LEVELS = {"level 1", "level 2", "level 3"}
LOST_LEADERSHIP_PCT = 0.35
#: Maud's standing deals, every week. Matched on the name with any
#: (nickname) dropped, so the board's 'Amjad (MJ) Malhas' matches.
SPECIAL_PCT = {
    "Willie Henderson": 0.70,
    "Chloe Johnson": 0.70,
    "Bas El Hassan": 0.70,          # Maud: "Basil"
    "Thomas Crenshaw": 0.70,
    "Amjad Malhas": 0.85,
    "Algemar Kennel": 0.70,         # Maud 11/24: commission too, if he has sales
}
#: Fixed weekly base pay, on top of everything else.
BASE_PAY = {"Bas El Hassan": 1000.0, "Algemar Kennel": 1000.0}
#: Weekly bonus from RAF PNL 2026 (NEW), matched on the start of the row label.
BONUS_ROWS = {
    "Bas El Hassan": "Bas' Total Bonus",                              # row 31
    "Algemar Kennel": "Algemar's 5% from everyone else",              # row 39
    "Willie Henderson": "Willie's Partner Pay",                       # row 40
}
#: Paid base + bonus only — no % on their own sales. (Empty: Algemar now 70%.)
NO_COMMISSION: set = set()
BONUS_TAB = "RAF PNL 2026 (NEW)"
LINKEDIN_PCT = 0.70
SUNDAY_INTERNET_PCT = 0.85
SUNDAY_NOTE = "Sunday internet 85%"
#: New internet only — upgrades ('Upgrade Internet 1000') don't qualify.
NEW_INTERNET = re.compile(r"^internet \d+$", re.I)
#: DD lines with no rep that are NOT shown (Maud: Captain Bonus can't be on it).
NO_REP_SKIP = {"captain bonus", "captain's bonus"}
#: Board "Gas Bonus" column (DX): "$100" = always, "$100 if 5+ apps" = only
#: with that many apps (distinct customers on the rep's DD lines) this week.
GAS_RULE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)(?:.*?(\d+)\s*\+?\s*apps?)?", re.I)
#: Rep tabs list their Pending / Disconnect / Cancel lines from Lucy's daily
#: Order Log (Tableau ATT Tracker 2.1 - D2D, Raf's view, last ~1 month).
#: Lines only, no $ (Maud 2026-11-24).
PENDING_BANNER = "Pending / Disconnect / Cancel"
PENDING_COLS = ["Order Date", "Customer Name", "Package", "Product Type",
                "Status", "Install Date", "Activation Date"]
BOARD_COUNT = 2                      # "the last 2 boards"
NEW_START_LAG_DAYS = 14              # box 3 boards back = DD Sunday - 14

KIND_HELD, KIND_EXTRA, KIND_MISSING = "held", "extra", "missing"
NOTE_NOT_ON = "Not on the last 2 boards"
NOTE_HELD = "New start — held, paid next week"
NOTE_EXTRA = "No rep on this DD line"

MONEY = '"$"#,##0.00'
HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")       # editable %
MISSING_FILL = PatternFill("solid", fgColor="F8CBAD")     # orange: type a %
HELD_FILL = PatternFill("solid", fgColor="D9D2E9")        # purple: new start held
EXTRA_FILL = PatternFill("solid", fgColor="D9D9D9")       # grey: no rep
LOST_FILL = PatternFill("solid", fgColor="F4B6C2")        # pink: lost leadership
GUARANTEE_FILL = PatternFill("solid", fgColor="C6EFCE")   # green: has a guarantee
LABEL_FILL = PatternFill("solid", fgColor="DDEBF7")       # rep-tab labels, TOTAL
CENTER = Alignment(horizontal="center", vertical="center")
_EDGE = Side(style="thin", color="8EA9C8")
BORDER = Border(left=_EDGE, right=_EDGE, top=_EDGE, bottom=_EDGE)
TAB_EDITED = "Edited"
TAB_PAYOUT = "Reps Name & Commission payout"
TAB_RAW = "Raw"
PAYOUT_HEADERS = ["Rep Name", "Commission %", "Revenue Brought In", "Total Payout",
                  "Level / Rule", "Lost Leadership Pay", "Sunday Internet Revenue",
                  "Commission", "Guarantee", "Base Pay", "Bonus", "Gas Bonus"]
#: Rep tab: label, payout-tab column, number format. Rows 1..len, sales below.
REP_DETAILS = [
    ("Commission %", "B", "0%"),
    ("Revenue Brought In", "C", MONEY),
    ("Sunday Internet Revenue (85%)", "G", MONEY),
    ("Lost Leadership Pay", "F", None),
    ("Commission", "H", MONEY),
    ("Guarantee", "I", MONEY),
    ("Base Pay", "J", MONEY),
    ("Bonus", "K", MONEY),
    ("Gas Bonus", "L", MONEY),
    ("Total Payout", "D", MONEY),
]
#: Rep tab: detail rows from row 1 down to the first blank row (only the
#: details that apply), one blank row, then the sales header.


def money(s):
    if isinstance(s, (int, float)):
        return float(s)
    s = (s or "").replace("$", "").replace(",", "").strip()
    neg = s.startswith("(") or s.startswith("-")
    s = s.strip("()-")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def clean_name(s):
    return re.sub(r"\s*\(\d+\)\s*$", "", s or "").strip()


def _name_key(s):
    """'Alexis (Lexi) Justice (Wk 2)' and 'Alexis Justice' -> 'alexis justice'."""
    s = re.sub(r"\([^)]*\)", " ", str(s or "").replace("\xa0", " "))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _date(s):
    if s is None or str(s) in ("", "NaT", "nan", "None"):
        return None
    if isinstance(s, dt.datetime):
        return s.date()
    if isinstance(s, dt.date):
        return s
    try:
        m, d, y = (int(x) for x in str(s).strip().split("/"))
        return dt.date(y, m, d)
    except ValueError:
        return None


def _add_note(cur, note):
    cur = str(cur or "").strip()
    if note in cur:
        return cur
    return f"{cur} · {note}" if cur else note


def _md_date(v):
    d = _date(v)
    return f"{d.month}/{d.day}/{d.year}" if d else (v or "")


def _md(d):
    return f"{d.month}.{d.day:02d}" if d else "?"


def header(ws, labels):
    ws.append(labels)
    for c in ws[1]:
        c.font, c.fill = HEAD, HEAD_FILL
    ws.freeze_panes = "A2"


def widths(ws, w):
    for i, x in enumerate(w, 1):
        ws.column_dimensions[get_column_letter(i)].width = x


def safe_title(name, used):
    t = re.sub(r"[\[\]\*\?/\\:]", "", name)[:31].strip("'")
    base, n = t, 2
    while t.lower() in used:
        t = f"{base[:28]} {n}"
        n += 1
    used.add(t.lower())
    return t


# --- the board --------------------------------------------------------------
class Board:
    """What the rules need from Raf's sales board."""

    def __init__(self):
        self.levels = {}       # key -> (level, tab)   newest of the last 2 boards
        self.on_boards = set() # key: anywhere (roster or box) on the last 2 boards
        self.in_box = set()    # key: in a New Starts box on the last 2 boards
        self.linkedin = {}     # key -> tab
        self.late = {}         # key -> reason   (DD week's board)
        self.held = set()      # key: New Starts box 3 boards back
        self.gas = {}          # key -> (board text, tab)  newest of the last 2 boards
        self.guarantee = {}    # key -> (amount, tab)  newest of the last 2 boards
        self.names = {}        # key -> name as the board spells it
        self.tabs = []         # titles read, for the log
        self.held_tab = None


def _grid(sh, title):
    return sh.worksheet(title).get_values(value_render_option="UNFORMATTED_VALUE")


def _titles(BD, grid):
    return {BD._norm(v): i for i, v in enumerate(grid[0], 1) if BD._norm(v)}


def _box_rows(BD, grid, lay):
    for r in range(lay.box_first_row, len(grid) + 1):
        if str(BD._cell(grid, r, lay.box_name_col) or "").strip():
            yield r


def _late_marks(BD, grid, lay, r):
    """Weekdays (0=Mon) this roster row's Roll Call says 'Late'."""
    hdr = grid[lay.header_row - 1] if lay.header_row else []
    out = []
    for wd, c1, c2 in lay.day_blocks:
        for c in range(c1, c2 + 1):
            if c - 1 < len(hdr) and BD._norm(hdr[c - 1]) == "roll call":
                if BD._norm(BD._cell(grid, r, c)).startswith("late"):
                    out.append(wd)
    return out


def _display(raw):
    """'Lance Brogdon (Wk 3)' -> 'Lance Brogdon' (tenure markers off)."""
    s = " ".join(str(raw or "").replace("\xa0", " ").split())
    return re.sub(r"(\s*\((?:wk[^)]*|nc|rt)\))+\s*$", "", s, flags=re.I).strip()


def read_bonuses(dd_sunday):
    """{rep: (amount, 'WE m/d')} from RAF PNL 2026 (NEW), week before the DD week."""
    from automations.recruiting_report.fill import open_by_key
    from automations.shared.workbooks import ALL_IN_ONE_RAF
    week = dd_sunday - dt.timedelta(days=7)
    want = f"we {week.month}/{week.day}"
    serial = (week - dt.date(1899, 12, 30)).days      # header cells are dates
    grid = open_by_key(ALL_IN_ONE_RAF).worksheet(BONUS_TAB).get_values(
        value_render_option="UNFORMATTED_VALUE")
    cols = [i for i, v in enumerate(grid[0])
            if v == serial or " ".join(str(v).lower().split()) == want]
    if not cols:
        raise RuntimeError(f"{BONUS_TAB!r} has no 'WE {week.month}/{week.day}' column")
    col, out = cols[0], {}
    for rep, label in BONUS_ROWS.items():
        rows = [r for r in grid if r and str(r[0]).strip().lower().startswith(label.lower())]
        if len(rows) != 1:
            raise RuntimeError(f"{BONUS_TAB!r}: {len(rows)} rows start with {label!r}")
        v = rows[0][col] if col < len(rows[0]) else ""
        out[rep] = (round(money(v), 2), f"WE {week.month}/{week.day}")
    return out


def read_board(dd_sunday, run_date=None):
    from automations.terminated_reps import board as BD
    run_date = run_date or dt.date.today()
    this_sunday = run_date + dt.timedelta(days=(6 - run_date.weekday()) % 7)
    sh = BD.open_by_key(BD.SHEET_ID)
    tabs = BD.week_tabs(sh, run_date)
    by_date = dict(tabs)
    b = Board()

    # the last 2 boards, newest first: levels, LinkedIn, who's on them
    for d, title in [t for t in tabs if t[0] <= this_sunday][::-1][:BOARD_COUNT]:
        b.tabs.append(title)
        grid = _grid(sh, title)
        lay = BD.find_layout(grid)
        titles = _titles(BD, grid)
        lv_col, li_col = titles.get("leadership status"), titles.get("add applied to")
        g_col = titles.get("guarantee")
        gas_col = titles.get("gas bonus")

        def _guarantee(key, r):
            amt = money(BD._cell(grid, r, g_col)) if g_col else 0.0
            if amt > 0 and key not in b.guarantee:
                b.guarantee[key] = (amt, title)
            gas = str(BD._cell(grid, r, gas_col) or "").strip() if gas_col else ""
            if gas and money(gas.split(" ")[0]) > 0 and key not in b.gas:
                b.gas[key] = (gas, title)
        for r in lay.roster_rows:
            key = _name_key(BD._cell(grid, r, lay.name_col))
            if not key:
                continue
            b.on_boards.add(key)
            _guarantee(key, r)
            b.names.setdefault(key, _display(BD._cell(grid, r, lay.name_col)))
            level = BD._norm(BD._cell(grid, r, lv_col)) if lv_col else ""
            if level and key not in b.levels:
                b.levels[key] = (level, title)
            if li_col and "linkedin" in BD._norm(BD._cell(grid, r, li_col)).replace(" ", ""):
                b.linkedin.setdefault(key, title)
        for r in _box_rows(BD, grid, lay):
            key = _name_key(BD._cell(grid, r, lay.box_name_col))
            b.on_boards.add(key)
            b.in_box.add(key)
            _guarantee(key, r)
            b.names.setdefault(key, _display(BD._cell(grid, r, lay.box_name_col)))
            if li_col and "linkedin" in BD._norm(BD._cell(grid, r, li_col)).replace(" ", ""):
                b.linkedin.setdefault(key, title)

    # lost leadership pay: the DD week's board
    title = by_date.get(dd_sunday)
    if title:
        grid = _grid(sh, title)
        lay = BD.find_layout(grid)
        sat = dd_sunday - dt.timedelta(days=1)
        for r in lay.roster_rows:
            key = _name_key(BD._cell(grid, r, lay.name_col))
            marks = _late_marks(BD, grid, lay, r) if key else []
            if 5 in marks:
                b.late[key] = f"Late Sat {sat.month}/{sat.day}"
            elif len(marks) >= 2:
                b.late[key] = f"Late {len(marks)}x WE {_md(dd_sunday)}"
    else:
        print(f"!! no board tab for WE {_md(dd_sunday)} — lateness not checked")

    # new starts held: the New Starts box 3 boards back
    title = by_date.get(dd_sunday - dt.timedelta(days=NEW_START_LAG_DAYS))
    if title:
        b.held_tab = title
        grid = _grid(sh, title)
        lay = BD.find_layout(grid)
        b.held = {_name_key(BD._cell(grid, r, lay.box_name_col))
                  for r in _box_rows(BD, grid, lay)}
    else:
        print("!! no board tab 3 boards back — no new starts held")
    return b


def gas_for(rep, board, apps):
    """Gas bonus $ from the board's DX text, or None. apps: {key: distinct customers}."""
    key = _name_key(rep)
    if key not in board.gas:
        return None
    m = GAS_RULE.search(board.gas[key][0])
    if not m:
        return None
    need = int(m.group(2)) if m.group(2) else 0
    return money(m.group(1)) if apps.get(key, 0) >= need else None


def read_pending(csv_path=None, log=print):
    """({rep key: [line dict]}, 'through m/d') from Lucy's Order Log — every
    line that isn't Active/Posted (Pending, Shipped, Scheduled, Cancelled,
    Disconnected…). Downloads Raf's Order Log crosstab unless a csv is given."""
    import tempfile
    from automations.uploaded import order_log as OL
    if not csv_path:
        log("   downloading Lucy's Order Log (Tableau ATT Tracker 2.1 - D2D)…")
        csv_path = OL.download_order_log_crosstab(
            Path(tempfile.mkdtemp(prefix="order_log_")) / "order_log.csv",
            verbose=False)
    df = OL._load_and_clean(Path(csv_path))
    out = collections.defaultdict(list)
    last = None
    for rec in df.to_dict("records"):
        rep_ = str(rec.get("Rep") or "").strip()
        d = _date(rec.get("Order Date"))
        if d and (last is None or d > last):
            last = d
        if not rep_ or rep_.lower() == "nan" or OL._pdc_code(rec.get("Status")) is None:
            continue
        line = {c: ("" if str(rec.get(c)) in ("nan", "NaT", "None") else rec.get(c))
                for c in PENDING_COLS}
        line["Package"] = re.sub(r"\s*-\s*nan$", "", str(line["Package"] or ""))
        out[_name_key(rep_)].append(line)
    for k in out:
        # still in flight first, then Disconnected, then Cancelled
        out[k].sort(key=lambda r: ("PDC".index(OL._pdc_code(r["Status"])),
                                   OL._status_sort_key(r["Status"]),
                                   _date(r["Order Date"]) or dt.date.min))
    return dict(out), (f"through {last.month}/{last.day}" if last else "")


#: Faded versions of the Order Log's status colors (Maud 2026-11-24).
PENDING_RED = {"Cancelled", "Disconnected", "Pending Valid Payment", "Porting Issue"}
PENDING_ORANGE = {"Delivered"}


def _status_fill(status):
    st = str(status or "").strip()
    hexc = ("FCE4E4" if st in PENDING_RED else
            "FDEBD9" if st in PENDING_ORANGE else "FFF8DC")
    return PatternFill("solid", fgColor=hexc)


def rule_for(rep, board):
    """(pct, kind, note in E, lost-leadership reason for F, level pct if leader).

    kind: 'held' | 'missing' | 'leader' | 'set'."""
    key = _name_key(rep)
    if rep in NO_COMMISSION or key in {_name_key(n) for n in NO_COMMISSION}:
        return 0.0, "set", "Base pay + bonus (no commission)", "", None
    if key in board.held and key not in board.guarantee:
        return None, KIND_HELD, NOTE_HELD, "", None
    specials = {_name_key(n): p for n, p in SPECIAL_PCT.items()}
    if key in specials:
        return specials[key], "set", "Special deal", "", None
    if key in board.linkedin:
        return LINKEDIN_PCT, "set", "LinkedIn", "", None
    if key in board.levels:
        level, tab = board.levels[key]
        note = level.title()
        if level not in LEVEL_PCT:
            return None, KIND_MISSING, f"{level.title()} — no % for this level", "", None
        pct = LEVEL_PCT[level]
        if level in LEADER_LEVELS:
            return pct, "leader", note, board.late.get(key, ""), pct
        return pct, "set", note, "", None
    if key in board.in_box:
        return None, KIND_MISSING, "New Starts box — no level", "", None
    return None, KIND_MISSING, NOTE_NOT_ON, "", None


# --- carry-over -------------------------------------------------------------
def carried_lines(sheet_id):
    """Last week's held new starts' sales, from last week's RH sheet."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    pay = sh.worksheet(TAB_PAYOUT).get_values(value_render_option="UNFORMATTED_VALUE")
    held = {r[0] for r in pay[1:] if len(r) > 4 and str(r[4]).startswith("New start")}
    if not held:
        return [], sh.title
    m = re.search(r"RH (\d+)\.(\d+)", sh.title)
    label = f"Carried from WE {m.group(1)}.{m.group(2)}" if m else "Carried from last week"
    out = []
    for r in sh.worksheet(TAB_EDITED).get_values(value_render_option="FORMATTED_VALUE")[1:]:
        if r and r[0] in held:
            r = list(r) + [""] * (len(EDITED_COLS) - len(r))
            rec = {lbl: r[i] for i, (lbl, _) in enumerate(EDITED_COLS)}
            rec["Total $ to ICD"] = money(rec["Total $ to ICD"])
            rec[NOTE_COL] = _add_note(rec[NOTE_COL], label)
            out.append(rec)
    return out, sh.title


# --- styling ----------------------------------------------------------------
def product_fills(products):
    """One blue per product: hues spread from teal-blue to periwinkle, light and
    mid tints alternating so neighbouring products read as different. Black
    text stays readable on every shade."""
    names = sorted({(p or "").strip() for p in products}, key=str.lower)
    n = max(len(names) - 1, 1)
    fills = {}
    for i, name in enumerate(names):
        hue = (190 + 40 * i / n) / 360
        light = (0.93, 0.85, 0.78)[i % 3]
        r, g, b = colorsys.hls_to_rgb(hue, light, 0.62)
        fills[name] = PatternFill("solid", fgColor="%02X%02X%02X" % (
            round(r * 255), round(g * 255), round(b * 255)))
    return fills


def _box(ws, r1, r2, c1, c2):
    """Center + border every cell in the block."""
    for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
        for c in row:
            c.alignment, c.border = CENTER, BORDER


def _header_row(ws, row, c1, c2):
    for c in next(ws.iter_rows(min_row=row, max_row=row, min_col=c1, max_col=c2)):
        c.font, c.fill = HEAD, HEAD_FILL


def _fill_by_product(ws, r1, r2, ncols, product_col, fills):
    for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=1, max_col=ncols):
        f = fills.get((row[product_col - 1].value or "").strip())
        if f:
            for c in row:
                c.fill = f


def style_workbook(wb):
    """Centered text, borders on every table, navy headers, rows shaded by
    product; payout rows colored by rule. Works on a fresh build or on an
    existing workbook of this shape."""
    ed = wb[TAB_EDITED]
    ncol = sum(1 for c in ed[1] if c.value not in (None, ""))
    fills = product_fills(ed.cell(r, 4).value for r in range(2, ed.max_row + 1))
    _header_row(ed, 1, 1, ncol)
    _fill_by_product(ed, 2, ed.max_row, ncol, 4, fills)
    _box(ed, 1, ed.max_row, 1, ncol)

    wr = wb[TAB_PAYOUT]
    last = wr.max_row
    while last > 1 and wr.cell(last, 1).value in (None, ""):
        last -= 1
    pcols = 4                                   # every titled column in row 1
    while wr.cell(1, pcols + 1).value not in (None, "") and pcols < 12:
        pcols += 1
    _header_row(wr, 1, 1, pcols)
    for r in range(2, last + 1):
        e = str(wr.cell(r, 5).value or "") if pcols >= 5 else ""
        row_fill = None
        if str(wr.cell(r, 1).value).strip().upper() == "TOTAL":
            row_fill = LABEL_FILL
        elif e.startswith("New start"):
            row_fill = HELD_FILL
        elif e == NOTE_EXTRA:
            row_fill = EXTRA_FILL
        elif wr.cell(r, 2).value in (None, ""):
            row_fill = MISSING_FILL             # no % yet — make it obvious
        elif (pcols >= 9 and wr.cell(r, 9).value not in (None, "", 0)
              and not e.startswith("LinkedIn")):
            row_fill = GUARANTEE_FILL           # has a guarantee
        if row_fill:
            for c in range(1, pcols + 1):
                wr.cell(r, c).fill = row_fill
        else:
            wr.cell(r, 2).fill = INPUT_FILL
    _box(wr, 1, last, 1, pcols)
    if pcols >= 6:
        # Lost leadership pay — auto-filled or typed in F — turns the row pink.
        wr.conditional_formatting.add(
            f"A2:{get_column_letter(pcols)}{last}",
            FormulaRule(formula=['AND($F2=TRUE,$A2<>"TOTAL")'],
                        fill=LOST_FILL,
                        stopIfTrue=True))

    for ws in wb.worksheets:
        if ws.title in (TAB_EDITED, TAB_PAYOUT, TAB_RAW):
            continue
        top = 1
        while ws.cell(top + 1, 1).value not in (None, ""):
            top += 1
        hdr = top + 2
        for r in range(1, top + 1):               # the detail labels
            ws.cell(r, 1).fill = LABEL_FILL
        _box(ws, 1, top, 1, 2)
        pend = next((r for r in range(hdr, ws.max_row + 1)
                     if str(ws.cell(r, 1).value or "").startswith(PENDING_BANNER)), None)
        end = (pend - 2) if pend else ws.max_row
        if end >= hdr:                            # sales header, then sales
            _header_row(ws, hdr, 1, ncol - 1)
            _fill_by_product(ws, hdr + 1, end, ncol - 1, 3, fills)
            _box(ws, hdr, end, 1, ncol - 1)
        if pend:                                  # Order Log pendings
            n = len(PENDING_COLS)
            ws.merge_cells(start_row=pend, start_column=1, end_row=pend, end_column=n)
            b = ws.cell(pend, 1)
            b.fill = PatternFill("solid", fgColor="FF000000")
            b.font = Font(bold=True, color="FFFFFF")
            b.alignment = CENTER
            if ws.max_row > pend:
                for c in range(1, n + 1):
                    hc = ws.cell(pend + 1, c)
                    hc.fill = PatternFill("solid", fgColor="BFBFBF")
                    hc.font = Font(bold=True)
                si = PENDING_COLS.index("Status") + 1
                for r in range(pend + 2, ws.max_row + 1):
                    f = _status_fill(ws.cell(r, si).value)
                    for c in range(1, n + 1):
                        ws.cell(r, c).fill = f
                        ws.cell(r, c).alignment = CENTER
            _box(ws, pend, ws.max_row, 1, n)

    if TAB_RAW in wb.sheetnames:
        raw = wb[TAB_RAW]
        _header_row(raw, 1, 1, raw.max_column)
        _box(raw, 1, raw.max_row, 1, raw.max_column)


def require_raw(wb, expected_rows=None):
    """Every workbook this makes keeps a Raw tab with the untouched Tableau
    rows (Maud 2026-11-23: "always keep a tab with the Raw data"). Refuse to
    save without it."""
    if TAB_RAW not in wb.sheetnames:
        raise RuntimeError("no Raw tab - refusing to save without the raw data")
    have = wb[TAB_RAW].max_row - 1
    if have < 1 or (expected_rows is not None and have != expected_rows):
        raise RuntimeError(f"Raw tab has {have} data rows, expected "
                           f"{expected_rows if expected_rows is not None else '1+'}")


def restyle(src, out):
    """Apply the new header names + styling to an already-built workbook,
    keeping every value, formula and typed % as it is."""
    wb = load_workbook(src)
    for ws in wb.worksheets:
        if ws.title == TAB_RAW:
            continue
        for row in (1, 6):
            for c in ws[row]:
                if isinstance(c.value, str) and c.value.strip() in OLD_HEADERS:
                    c.value = OLD_HEADERS[c.value.strip()]
    style_workbook(wb)
    require_raw(wb)
    wb.save(out)
    print(f"restyled -> {out}")


# --- build ------------------------------------------------------------------
def dd_sunday(raw, ix):
    """Week-ending Sunday of the DD rows (DD week is the Saturday)."""
    c = collections.Counter(r[ix["cl.DD Week"]] for r in raw if r[ix["cl.DD Week"]])
    if not c:
        return None
    week = _date(c.most_common(1)[0][0])
    return week + dt.timedelta(days=(6 - week.weekday()) % 7)


def is_sunday_internet(rec):
    d = _date(rec["Sale Date"])
    return bool(d and d.weekday() == 6 and NEW_INTERNET.match(str(rec["Product"]).strip()))


def main(src, out, use_board=True, carry_from=None, run_date=None,
         pending_file=None):
    rows = read_crosstab(Path(src))
    h = rows[0]
    ix = {n.strip(): i for i, n in enumerate(h)}
    raw = [r for r in rows[2:]
           if r[0].startswith(CORP_PREFIX) and OWNER in r[ix["cl.ICD Owner Name"]]]

    edited, extra_labels = [], []
    for r in raw:
        rep = clean_name(r[ix["REP.Name"]])
        cat = r[ix["cl.Category"]].strip()
        if not rep and cat.lower() in NO_REP_SKIP:
            continue                         # Captain Bonus — never on the sheet
        rec = {}
        for label, col in EDITED_COLS:
            rec[label] = r[ix[col]] if col else ""
        if cat.upper() in MOVE_TO_PRODUCT and not rec["Product"].strip():
            rec["Product"] = cat.upper()
        if not rep:                          # no rep: its own row, named as is
            rep = rec["Product"].strip() or cat or "No rep"
            extra_labels.append(rep)
        rec["Rep Full Name"] = rep
        rec["Total $ to ICD"] = money(rec["Total $ to ICD"])
        if is_sunday_internet(rec):
            rec[NOTE_COL] = _add_note(rec[NOTE_COL], SUNDAY_NOTE)
        edited.append(rec)

    carried, carried_from = [], None
    if carry_from:
        carried, carried_from = carried_lines(carry_from)
        edited += carried
    edited.sort(key=lambda d: (d["Rep Full Name"].lower(), d["Product"].lower()))
    extras = sorted(set(extra_labels), key=str.lower)

    sunday = dd_sunday(raw, ix)
    board = Board()
    if use_board and sunday:
        try:
            board = read_board(sunday, run_date)
        except Exception as e:                          # noqa: BLE001
            print(f"!! could not read Raf's board ({type(e).__name__}: {e}) — "
                  "every % left blank")
    bonuses = {}
    if use_board and sunday:
        try:
            bonuses = read_bonuses(sunday)
        except Exception as e:                          # noqa: BLE001
            print(f"!! could not read bonuses ({type(e).__name__}: {e}) — Bonus left blank")

    pending, pending_label = {}, ""
    if use_board or pending_file:
        try:
            pending, pending_label = read_pending(pending_file)
        except Exception as e:                          # noqa: BLE001
            print(f"!! could not read the Order Log ({type(e).__name__}: {e}) "
                  "— no Pending section on the rep tabs")

    # Everyone with sales, plus anyone paid without sales: base pay, a bonus,
    # or a guarantee ("if they don't have commission they still get it").
    names = {d["Rep Full Name"] for d in edited} - set(extras)
    have = {_name_key(n) for n in names}
    for n in list(BASE_PAY) + list(BONUS_ROWS):
        if _name_key(n) not in have:
            names.add(n)
            have.add(_name_key(n))
    # Gas bonus: apps = distinct customers on the rep's DD lines this week.
    custs = collections.defaultdict(set)
    for d in edited:
        if d.get("Customer Name"):
            custs[_name_key(d["Rep Full Name"])].add(str(d["Customer Name"]).strip().lower())
    apps = {k: len(v) for k, v in custs.items()}
    for key in list(board.guarantee) + [k for k in board.gas
                                         if gas_for(board.names.get(k, k), board, apps)]:
        if key not in have:
            names.add(board.names.get(key) or key.title())
            have.add(key)
    reps = sorted(names, key=str.lower)
    base_by_key = {_name_key(n): v for n, v in BASE_PAY.items()}
    bonus_by_key = {_name_key(n): v for n, v in bonuses.items()}
    no_comm = {_name_key(n) for n in NO_COMMISSION}

    wb = Workbook()
    # --- Edited ------------------------------------------------------------
    ws = wb.active
    ws.title = TAB_EDITED
    header(ws, [c for c, _ in EDITED_COLS])
    for d in edited:
        ws.append([d[c] for c, _ in EDITED_COLS])
    for (c,) in ws.iter_rows(min_row=2, min_col=10, max_col=10):
        c.number_format = MONEY
    ws.auto_filter.ref = ws.dimensions
    widths(ws, [24, 12, 14, 30, 16, 9, 26, 16, 26, 14])
    last = ws.max_row
    A, J, K = (f"Edited!${c}$2:${c}${last}" for c in "AJG")   # K = note column

    # --- Reps Name & Commission payout ------------------------------------
    wr = wb.create_sheet(TAB_PAYOUT)
    header(wr, PAYOUT_HEADERS)
    results, tabbed = {}, []
    lpct = LOST_LEADERSHIP_PCT
    for i, name in enumerate(reps + extras, 2):
        key = _name_key(name)
        if name in extras:
            pct, kind, note, lost, lvl = None, KIND_EXTRA, NOTE_EXTRA, "", None
        else:
            pct, kind, note, lost, lvl = rule_for(name, board)
        g_amt = board.guarantee.get(key, (None, ""))[0] if name not in extras else None
        base = base_by_key.get(key) if name not in extras else None
        bonus = bonus_by_key.get(key) if name not in extras else None
        if g_amt:
            note += " · Guarantee"
        if bonus:
            note += f" · Bonus {bonus[1]}"
        gas = gas_for(name, board, apps) if name not in extras else None
        if gas:
            note += " · Gas bonus"
        if lost:
            note += f" · {lost}"
        wr.cell(i, 1, name)
        paid = pct is not None and key not in no_comm
        leader = paid and kind == "leader"
        if leader:
            # Level 1-3: ticked box = loses leadership pay -> 35%. Untick to pay
            # the level % again (Maud 2026-11-24).
            p = wr.cell(i, 2, f'=IF(F{i}=TRUE,{lpct},{lvl})')
        else:
            p = wr.cell(i, 2, pct)
        p.number_format = "0%"
        wr.cell(i, 3, f"=SUMIF({A},A{i},{J})").number_format = MONEY
        wr.cell(i, 4, f'=IF(COUNT(H{i}:L{i})=0,"",MAX(N(H{i}),N(I{i}))+N(J{i})+N(K{i})+N(L{i}))'
                ).number_format = MONEY
        wr.cell(i, 5, note)
        wr.cell(i, 6, bool(lost) if leader else None)   # bool -> checkbox
        wr.cell(i, 7, f'=SUMIFS({J},{A},A{i},{K},"*{SUNDAY_NOTE}*")').number_format = MONEY
        if key not in no_comm:
            wr.cell(i, 8, f'=IF(B{i}="","",(C{i}-G{i})*B{i}'
                          f'+G{i}*MAX(B{i},{SUNDAY_INTERNET_PCT}))').number_format = MONEY
        for col, v in ((9, g_amt), (10, base), (11, bonus[0] if bonus else None),
                       (12, gas)):
            if v is not None:
                wr.cell(i, col, v).number_format = MONEY
        results[name] = (pct if not lost else lpct, kind, note, lost, g_amt, base,
                         bonus[0] if bonus else None, gas)
        if name not in extras and kind != KIND_HELD and not note.startswith(NOTE_NOT_ON):
            tabbed.append(name)
    n = len(reps) + len(extras) + 1
    t = n + 1
    wr.cell(t, 1, "TOTAL").font = Font(bold=True)
    for col in ("C", "D", "G", "H", "I", "J", "K", "L"):
        c = wr[f"{col}{t}"]
        c.value = f"=SUM({col}2:{col}{n})"
        c.number_format, c.font = MONEY, Font(bold=True)
    wr["N1"] = ("Yellow % can be typed over; each rep's tab follows. Level 1-3 "
                "reps have a Lost Leadership Pay box: ticked = Entry Level 35% "
                "(the reason is in Level / Rule), untick to pay their level %. Total Payout = "
                "higher of Commission or Guarantee, + Base Pay + Bonus + Gas Bonus. "
                "Orange = no level, type a %. Purple = new start, paid next week. "
                "Green = guarantee (not LinkedIn). Grey = DD line with no rep. Pink = lost leadership pay.")
    wr["N1"].font = Font(italic=True)
    widths(wr, [28, 14, 20, 14, 40, 22, 22, 14, 14, 14, 14, 14])

    # --- one tab per paid rep: every detail, then their sales ---------------
    used = {"edited", "reps name & commission payout", "raw"}
    look = "'Reps Name & Commission payout'!"
    for rep in tabbed:
        wt = wb.create_sheet(safe_title(rep, used))
        wt["A1"], wt["B1"] = "Rep", rep
        wt["A1"].font = Font(bold=True)
        wt["B1"].font = Font(bold=True, size=13)
        # Only what applies to this rep — nothing that's 0, blank or "No".
        _p, _k, _n, lost, g_amt, base, bonus, gas = results[rep]
        rev = sum(d["Total $ to ICD"] for d in edited if d["Rep Full Name"] == rep)
        sun = sum(d["Total $ to ICD"] for d in edited if d["Rep Full Name"] == rep
                  and SUNDAY_NOTE in str(d[NOTE_COL] or ""))
        show = {"B": _p is not None, "C": bool(rev), "G": bool(sun), "F": bool(lost),
                "H": bool(rev) and _p is not None, "I": bool(g_amt), "J": bool(base),
                "K": bool(bonus), "L": bool(gas), "D": True}
        r = 1
        for label, col, fmt in REP_DETAILS:
            if not show.get(col):
                continue
            r += 1
            idx = f"INDEX({look}${col}:${col},MATCH($B$1,{look}$A:$A,0))"
            wt.cell(r, 1, label).font = Font(bold=True)
            if col == "F":
                f = f'=IFERROR(IF({idx}=TRUE,"Yes — Entry Level 35%",""),"")'
            else:
                f = f'=IFERROR({idx},"")'
            c = wt.cell(r, 2, f)
            if fmt:
                c.number_format = fmt
        wt.cell(r, 2).font = Font(bold=True, size=13, color="006100")
        wt.append([])
        mine = [d for d in edited if d["Rep Full Name"] == rep]
        if mine:                                  # no sales -> no empty header
            wt.append([c for c, _ in EDITED_COLS[1:]])
        for d in mine:
            wt.append([d[c] for c, _ in EDITED_COLS[1:]])
            wt.cell(wt.max_row, 9).number_format = MONEY
        lines = pending.get(_name_key(rep), [])
        if pending_label and lines:               # nothing pending -> no section
            wt.append([])
            wt.append([f"{PENDING_BANNER} — Order Log {pending_label}"])
            wt.append(PENDING_COLS)
            for ln in lines:
                wt.append([_md_date(ln[c]) if "Date" in c else ln[c]
                           for c in PENDING_COLS])
        widths(wt, [30, 34, 30, 16, 9, 18, 16, 26, 14, 28])

    # --- Raw (Raf's office rows, untouched) -------------------------------
    wraw = wb.create_sheet(TAB_RAW)
    header(wraw, [x.strip() for x in h])
    for r in raw:
        wraw.append(r)

    style_workbook(wb)
    require_raw(wb, expected_rows=len(raw))
    wb.save(out)

    # --- summary ----------------------------------------------------------
    rev = collections.Counter()
    for d in edited:
        rev[d["Rep Full Name"]] += d["Total $ to ICD"]
    print(f"raw rows {len(raw)}  edited rows {len(edited)}  reps {len(reps)}  "
          f"no-rep rows {len(extras)}  carried lines {len(carried)}"
          + (f" (from {carried_from})" if carried_from else ""))
    print(f"total revenue {sum(rev.values()):,.2f}   DD weeks: "
          f"{sorted({r[ix['cl.DD Week']] for r in raw})}   boards: {board.tabs}"
          f"   held from: {board.held_tab}")
    for kind in ("held", "missing", "leader", "set", "extra"):
        names = [r for r, v in results.items() if v[1] == kind]
        if kind in ("held", "missing", "extra"):
            print(f"  {kind:<8} {len(names):>2}: {names}")
    lost = {r: v[3] for r, v in results.items() if v[3]}
    print(f"  lost leadership {len(lost)}: {lost}")
    print(f"  guarantee: { {r: v[4] for r, v in results.items() if v[4]} }")
    print(f"  base pay: { {r: v[5] for r, v in results.items() if v[5]} }")
    print(f"  gas bonus: { {r: v[7] for r, v in results.items() if v[7]} }")
    print(f"  bonus: { {r: v[6] for r, v in results.items() if v[6] is not None} }")
    print(f"  tabs: {len(tabbed)} (no tab for held / not on the last 2 boards / no-rep)")
    return results


def add_checkboxes(sheet_id):
    """Google Sheets: turn every FALSE/TRUE cell in the payout tab's Lost
    Leadership Pay column into a checkbox (an .xlsx upload can't carry one)."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    ws = sh.worksheet(TAB_PAYOUT)
    col = ws.get_values("F1:F400", value_render_option="UNFORMATTED_VALUE")
    rows = [i for i, r in enumerate(col, 1) if r and isinstance(r[0], bool)]
    reqs = [{"setDataValidation": {
        "range": {"sheetId": ws.id, "startRowIndex": r - 1, "endRowIndex": r,
                  "startColumnIndex": 5, "endColumnIndex": 6},
        "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}}
        for r in rows]
    if reqs:
        sh.batch_update({"requests": reqs})
    return len(reqs)


def cli(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dd-file", help="already-downloaded ORG DD Detail crosstab")
    ap.add_argument("--restyle", help="existing workbook to rename + restyle only")
    ap.add_argument("--out", required=True, help="where to save the .xlsx")
    ap.add_argument("--no-board", action="store_true",
                    help="don't read Raf's board (every %% left blank)")
    ap.add_argument("--order-log-file", help="already-downloaded Order Log crosstab "
                    "(else it's pulled from Tableau)")
    ap.add_argument("--carry-from", help="last week's RH sheet id: carry its held "
                                         "new starts' sales onto this week")
    a = ap.parse_args(argv)
    if a.restyle:
        restyle(a.restyle, a.out)
        return
    dd = a.dd_file
    if not dd:
        from automations.commission_sheet.sources import fetch_dd
        dd = fetch_dd()
    main(dd, a.out, use_board=not a.no_board, carry_from=a.carry_from,
         pending_file=a.order_log_file)


if __name__ == "__main__":
    cli()
