"""Raf's %-commission workbook (Raf Loom 2026-11-23; Maud owns the build).

Raf pays his local-office reps a % of the revenue they bring in. From the ORG
DD Detail crosstab this builds an .xlsx with:

  Edited    the columns Raf keeps, sorted by rep. Rule notes (Sunday internet,
            carried-over new-start sales) go in Description Detail. cl.Category WEARABLES /
            TABLET copied into the empty cl.Product cell.
  Reps Name & Commission Payout
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

  1  NEW START HELD — in the New Starts box of the DD week's own board
     (DD WE 11.22 -> 'Sales Board WE 11.22'; was 2 boards earlier until
     Maud 11/24). Paid the next week. % blank, purple. Their sales are carried onto
     NEXT week's sheet (pass the previous week's sheet as carry_from).
  2  SPECIAL DEAL — SPECIAL_PCT (Willie Henderson, Chloe Johnson, Bas El
     Hassan, Thomas Crenshaw, Algemar Kennel 70%; Amjad Malhas 85%), every week.
  3  LINKEDIN — 'Linkedin' in the board's "Add applied to" column (DY) on
     either of the last 2 boards -> 70%.
  4  BOARD LEVEL — Leadership Status on the last 2 boards (newest first):
     In Training / Entry 35%, Level 1/2/3 40%, Mastermind 70%.
     LOST LEADERSHIP PAY: a Level 1/2/3 rep who was 'Late' on the Saturday
     roll call of the DD week's board, or 'Late' 2+ times that week, gets 35%
     (reason in E, drop-down set to "Lose 5% + App Tier"). Every Level 1-3
     rep has the drop-down: - = level %, Lose 5% + App Tier = 35%,
     Lose 5% only = level % minus 5 (min 35%). Pink row while it's a Lose. Other levels have none.
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
import json
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
#: "How You Get Paid" grid: a Level 1-3 rep's % goes up with their apps that
#: week (board "Apps", DD week's board): 5+ 45%, 10+ 50%, 15+ 55%; under 5
#: = their level % (40%). Not Entry Level / Mastermind (Maud 2026-11-24).
LEADER_APP_TIERS = ((15, 0.55), (10, 0.50), (5, 0.45))
#: T in the Apps cell all week (or T and X mixed), no day worked = not paid
#: at all. X alone all week is still paid (Maud 2026-11-24).
OFF_MARKS = {"t", "x"}
LOST_LEADERSHIP_PCT = 0.35
#: Lost Leadership Pay is a drop-down on Level 1-3 rows (Maud 2026-11-27):
#:   "-" = their level % | "Lose 5% + App Tier" = 35% (loses the leadership
#:   5% AND the app bump) | "Lose 5% only" = level % minus 5 (not under 35%).
#: Late on the board -> "Lose 5% + App Tier" by default (what the old tick did).
#: Labels per Maud 2026-11-27; the first-day labels are still read (OLD_LOST).
LOST_NO, LOST_ALL, LOST_5 = "-", "Lose 5% + App Tier", "Lose 5% only"
LOST_CHOICES = (LOST_NO, LOST_ALL, LOST_5)          # drop-down order
OLD_LOST = {"no": LOST_NO, "lose 5%": LOST_5, "lose 5% + apps": LOST_ALL}
LEADERSHIP_CUT = 0.05


def lost_val(flag):
    """Built value for a leader's Lost Leadership cell."""
    return LOST_ALL if flag else LOST_NO


def lost_norm(v):
    """Any Lost Leadership cell (old TRUE/FALSE box or drop-down) -> a choice, or None."""
    if v is True or str(v).strip().upper() == "TRUE":
        return LOST_ALL
    if v is False or str(v).strip().upper() == "FALSE":
        return LOST_NO
    v = str(v or "").strip()
    return v if v in LOST_CHOICES else OLD_LOST.get(v.lower())


def is_lost(v):
    return lost_norm(v) in (LOST_5, LOST_ALL)


def lost_formula(cell, lvl):
    """Commission % for a Level 1-3 row, following its drop-down."""
    return (f'=IF({cell}="{LOST_ALL}",{LOST_LEADERSHIP_PCT},'
            f'IF({cell}="{LOST_5}",MAX({lvl}-{LEADERSHIP_CUT},{LOST_LEADERSHIP_PCT}),{lvl}))')
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
NEW_START_LAG_DAYS = 0               # New Starts box on the DD week's own board (Maud 11/24: was -14)

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
TAB_PAYOUT = "Reps Name & Commission Payout"
#: Sheets built before 11/24 spell it with a small "p" (read for carry-over).
OLD_TAB_PAYOUT = "Reps Name & Commission payout"


def _payout_ws(sh):
    try:
        return sh.worksheet(TAB_PAYOUT)
    except Exception:                                   # noqa: BLE001
        return sh.worksheet(OLD_TAB_PAYOUT)
TAB_RAW = "Raw"
TAB_EXTRA = "Extra Payouts"            # Maud types NPA / Clawback / Other here
TAB_CHECK = "Transfers to Check"
NOT_REP_TABS = (TAB_EDITED, TAB_PAYOUT, TAB_RAW, TAB_EXTRA, TAB_CHECK)
EXTRA_TYPES = ("NPA", "Clawback")     # "Other" dropped (Maud 2026-11-24)
EXTRA_ROWS = 150
PAYOUT_HEADERS = ["Rep Name", "Team", "Commission %", "Revenue Brought In", "Total Payout",
                  "Level / Rule", "Lost Leadership Pay", "Sunday Internet Revenue",
                  "Commission", "Guarantee", "Base Pay", "Gas Bonus",
                  "Customer Bonus", "Training Bonus", "Extra Bonus",
                  "Final Pay", "Bonus", "NPA", "Clawback"]
#: Team (B) from the sales board, right after the name (Maud 2026-11-24).
#: Total Payout (E) = MAX(Commission, Guarantee) + Base + Gas + Customer +
#: Training Bonus. Final Pay (P) = Total Payout + Extra Bonus. Bonus (Q, from
#: RAF PNL), NPA and Clawback sit after Final Pay and are NOT in it (Maud
#: 2026-11-24); NPA / Clawback come from the Extra Payouts tab (no "Other"
#: any more). Training Bonus and Extra Bonus are typed straight in (yellow).
#: Hidden column T: what the build / board re-check last put in C and G, so a
#: re-check only overwrites cells nobody has typed over (Maud 2026-11-24).
#: Columns are found by header (PC / PL), never by a fixed letter.
PC = {h: i + 1 for i, h in enumerate(PAYOUT_HEADERS)}          # header -> 1-based
PL = {h: get_column_letter(i) for h, i in PC.items()}          # header -> letter
AUTO_COL, AUTO_HEADER = len(PAYOUT_HEADERS) + 1, "auto (don't edit)"
INPUT_COLS = (PC["Commission %"], PC["Training Bonus"], PC["Extra Bonus"])
FINAL_COL = PC["Final Pay"]
FINAL_FILL = PatternFill("solid", fgColor="E7E6E6")
#: Rep tab: label, payout-tab column, number format. Rows 1..len, sales below.
REP_DETAILS = [
    ("Commission %", PL["Commission %"], "0%"),
    ("Revenue Brought In", PL["Revenue Brought In"], MONEY),
    ("Sunday Internet Revenue (85%)", PL["Sunday Internet Revenue"], MONEY),
    ("Lost Leadership Pay", PL["Lost Leadership Pay"], None),
    ("Commission", PL["Commission"], MONEY),
    ("Guarantee", PL["Guarantee"], MONEY),
    ("Base Pay", PL["Base Pay"], MONEY),
    ("Gas Bonus", PL["Gas Bonus"], MONEY),
    # (customer bonuses go here, one row per customer, from the build)
    ("Training Bonus", PL["Training Bonus"], MONEY),
    ("Total Payout", PL["Total Payout"], MONEY),
    ("Extra Bonus", PL["Extra Bonus"], MONEY),
    ("Final Pay", PL["Final Pay"], MONEY),
    # after Final Pay, not part of it (Maud 2026-11-24)
    ("Bonus", PL["Bonus"], MONEY),
    ("NPA", PL["NPA"], MONEY),
    ("Clawback", PL["Clawback"], MONEY),
]
#: Rep-tab top block (Maud 2026-11-24): rows back to back, only what applies;
#: one row per Extra Payouts entry right under Total Payout, its note in
#: column C (left, no border). Typed-in values appear on the next refresh
#: (refresh_rep_tabs — every 30 min Wed-Fri on the mini, or by hand).
REP_SKIP = {PL["NPA"], PL["Clawback"]}   # shown per entry instead of as totals
STD_LABELS = {lab for lab, _c, _f in REP_DETAILS} | {"Rep"}
NAME_ROW_FONT = ("FFFFFF", 14)
#: Rep tab: detail rows from row 1 down to the first blank row (only the
#: details that apply), one blank row, then the sales header.


#: Extra Payouts rows a later week's build writes in by itself, keyed by the
#: sheet's week-ending Sunday (Maud 2026-11-25: WE 11.22 clawbacks for reps
#: not on that sheet go on next week's). Edit carry_extras.json.
CARRY_EXTRAS = Path(__file__).with_name("carry_extras.json")


def _carry_extras(wx, reps, sunday):
    """Write this week's carried Extra Payouts rows (rep matched to a payout
    name: exact, else the one name containing it, else left as typed)."""
    if not sunday or not CARRY_EXTRAS.exists():
        return
    todo = json.loads(CARRY_EXTRAS.read_text()).get(sunday.isoformat(), [])
    r = 2
    for e in todo:
        want = e["rep"].strip()
        hit = [n for n in reps if _name_key(n) == _name_key(want)] or \
              [n for n in reps if want.lower() in n.lower()]
        name = hit[0] if len(hit) == 1 else want
        if len(hit) != 1:
            print(f"!! carried {e['type']} for '{want}': "
                  f"{'not on this sheet' if not hit else 'more than one match'} — check it")
        while wx.cell(r, 1).value:
            r += 1
        for c, v in enumerate((name, e["type"], e["amount"], e.get("note", "")), 1):
            wx.cell(r, c, v)
        r += 1


def _extra_row(e):
    """'Clawback - Movie': the reason right beside the type (Maud 11/24)."""
    typ, amt, note = e
    return (f"{typ} - {note}" if note else typ,
            -abs(amt) if typ == "Clawback" else amt, "")


def top_spec(rep, show, cb, extras):
    """The rep tab's top block as [(A, B, C)] rows, back to back.
    show = {payout column: bool}; cb = [(label, amount)] customer bonuses;
    extras = [(type, amount, note)] from Extra Payouts, one row each
    (Clawback shown negative). Order: ... Total Payout, Extra Bonus,
    Final Pay, then Bonus, NPA and Clawback (not part of Final Pay)."""
    look = f"'{TAB_PAYOUT}'!"
    rows = [("Rep", rep, "")]
    for label, col, _fmt in REP_DETAILS:
        idx = f"INDEX({look}${col}:${col},MATCH($B$1,{look}$A:$A,0))"
        if col == PL["Training Bonus"]:
            rows += [(cl, ca, "") for cl, ca in cb]
        if col in REP_SKIP or not show.get(col):
            continue
        if col == PL["Lost Leadership Pay"]:
            # the Level / Rule reason, not a plain "Yes" (Maud 11/24)
            lr = PL["Level / Rule"]
            why = idx.replace(f"${col}:${col}", f"${lr}:${lr}")
            rows.append((label, f'=IFERROR(IF(LEFT({idx},4)="Lose",IF({why}="",{idx},{why}&" · "&{idx}),""),"")', ""))
        else:
            rows.append((label, f'=IFERROR({idx},"")', ""))
    # NPA / Clawback are NOT in Final Pay (Maud 11/24) -> listed after it
    for typ in ("NPA", "Clawback"):
        rows += [_extra_row(e) for e in extras if e[0] == typ]
    return rows


def _extra_type(label):
    """'Clawback - Movie' / 'NPA' -> the Extra Payouts type, else None."""
    label = str(label or "")
    return next((t for t in EXTRA_TYPES
                 if label == t or label.startswith(t + " - ")), None)


def _top_kind(r, label):
    if r == 1:
        return "name"
    if label == "Total Payout":
        return "total"
    if label == "Final Pay":
        return "final"
    if _extra_type(label):
        return "extra"
    return "plain"


def _top_fmt(label):
    for lab, _c, fmt in REP_DETAILS:
        if lab == label:
            return fmt
    return None if label == "Rep" else MONEY


#: kind -> (A fill, B fill, font color, size); None = no fill / default.
#: Maud's mock-up 2026-11-24: Total Payout + Final Pay cyan, extra rows grey.
TOP_LOOK = {"name": ("1F4E78", "1F4E78", "FFFFFF", 14),
            "total": ("00FFFF", "00FFFF", "000000", 13),
            "final": ("00FFFF", "00FFFF", "000000", 13),
            "extra": ("D9D9D9", "D9D9D9", None, None),
            "plain": ("DDEBF7", None, None, None)}


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
        self.held = set()      # key: New Starts box on the DD week's board
        self.gas = {}          # key -> (board text, tab)  newest of the last 2 boards
        self.guarantee = {}    # key -> (amount, tab)  newest of the last 2 boards
        self.names = {}        # key -> name as the board spells it
        self.teams = {}        # key -> board "Team"   newest of the last 2 boards
        self.apps = {}         # key -> apps that week (DD week's board "Apps")
        self.off = {}          # key -> why: T / X every day of the DD week
        self.dd_apps = {}      # key -> distinct DD customers (set by the build)
        self.last_week_apps = {}  # key -> next board's "LAST WEEK'S TOTALS" Apps
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
        team_col = titles.get("team")

        def _team(key, r):
            tm = str(BD._cell(grid, r, team_col) or "").strip() if team_col else ""
            if tm and key not in b.teams:
                b.teams[key] = tm

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
            _team(key, r)
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
            _team(key, r)
            b.names.setdefault(key, _display(BD._cell(grid, r, lay.box_name_col)))
            if li_col and "linkedin" in BD._norm(BD._cell(grid, r, li_col)).replace(" ", ""):
                b.linkedin.setdefault(key, title)

    # lost leadership pay: the DD week's board
    title = by_date.get(dd_sunday)
    if title:
        grid = _grid(sh, title)
        lay = BD.find_layout(grid)
        sat = dd_sunday - dt.timedelta(days=1)
        hdr = grid[lay.header_row - 1] if lay.header_row else []
        app_cols = [c for _wd, c1, c2 in lay.day_blocks for c in range(c1, c2 + 1)
                    if c - 1 < len(hdr) and BD._norm(hdr[c - 1]) == "apps"]
        rc = {c for _wd, c1, c2 in lay.day_blocks for c in range(c1, c2 + 1)
              if c - 1 < len(hdr) and BD._norm(hdr[c - 1]) == "roll call"}
        for r in lay.roster_rows:
            key = _name_key(BD._cell(grid, r, lay.name_col))
            if key and app_cols:
                days = [str(BD._cell(grid, r, c) or "").strip().lower() for c in app_cols]
                b.apps[key] = int(sum(money(d) for d in days if d not in OFF_MARKS))
                # a day counts as worked if its Apps isn't T / X and anything
                # (apps, knocks, talk-to's…) is filled in for it
                worked, offs = 0, set()
                for (_wd, c1, c2), d in zip(lay.day_blocks, days):
                    if d in OFF_MARKS:
                        offs.add(d.upper())
                    elif any(str(BD._cell(grid, r, c) or "").strip()
                             for c in range(c1, c2 + 1) if c not in rc):
                        worked += 1
                # T all week, or T and X mixed = not paid; X alone is still
                # paid (Maud 2026-11-24)
                if "T" in offs and not worked:
                    kinds = "/".join(sorted(offs, reverse=True))
                    b.off[key] = f"{kinds} all week — not paid"
            marks = _late_marks(BD, grid, lay, r) if key else []
            if 5 in marks:
                b.late[key] = f"Late Sat {sat.month}/{sat.day}"
            elif len(marks) >= 2:
                b.late[key] = f"Late {len(marks)}x"
    else:
        print(f"!! no board tab for WE {_md(dd_sunday)} — lateness not checked")

    # Reps missing from the DD week's board: the NEXT board's "LAST WEEK'S
    # TOTALS" block has their Apps for the DD week (col P on WE 11.29; Maud
    # 2026-11-24: "usually the totals will be on the correct board").
    title = by_date.get(dd_sunday + dt.timedelta(days=7))
    if title:
        grid = _grid(sh, title)
        lay = BD.find_layout(grid)
        top = grid[0] if grid else []
        start = next((i for i, v in enumerate(top, 1)
                      if "last week" in BD._norm(v)), None)
        hdr = grid[lay.header_row - 1] if lay.header_row else []
        col = next((c for c in range(start or 0, len(hdr) + 1)
                    if start and BD._norm(hdr[c - 1]) == "apps"), None)
        if col:
            for r in lay.roster_rows:
                key = _name_key(BD._cell(grid, r, lay.name_col))
                v = BD._cell(grid, r, col)
                v = "" if v is None else str(v).strip()      # 0 is a real 0
                if key and v and v.lower() not in OFF_MARKS:
                    b.last_week_apps[key] = int(money(v))

    # new starts held: the New Starts box on the DD week's own board
    title = by_date.get(dd_sunday - dt.timedelta(days=NEW_START_LAG_DAYS))
    if title:
        b.held_tab = title
        grid = _grid(sh, title)
        lay = BD.find_layout(grid)
        b.held = {_name_key(BD._cell(grid, r, lay.box_name_col))
                  for r in _box_rows(BD, grid, lay)}
    else:
        print("!! no board tab for the DD week — no new starts held")
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
    if key in board.off:                         # T / X all week: nothing paid
        return None, KIND_MISSING, board.off[key], "", None
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
            # apps from the DD week's board; not on that board -> their DD
            # customers, marked "(DD)" (Maud 2026-11-24: every Level 1-3 shows apps)
            src = ""
            if key in board.apps:
                n = board.apps[key]
            elif key in board.last_week_apps:    # next board's last-week totals
                n = board.last_week_apps[key]
            else:
                n, src = board.dd_apps.get(key, 0), " (DD)"
            pct = next((p for need, p in LEADER_APP_TIERS if n >= need), pct)
            note += f" · {n} app{'s' if n != 1 else ''}{src}"
            return pct, "leader", note, board.late.get(key, ""), pct
        return pct, "set", note, "", None
    if key in board.in_box:
        return None, KIND_MISSING, "New Starts box — no level", "", None
    return None, KIND_MISSING, NOTE_NOT_ON, "", None


#: board spellings of owners' names (the board says "Bas", "MJ"…)
BOARD_NICKNAMES = {"bas el hassan": "bas", "basil elhassan": "bas", "amjad malhas": "mj",
                   "algemar kennel": "algemar"}


def team_for(board, name):
    """Sales-board Team for a payout-tab name ('' if not found)."""
    key = _name_key(name)
    if key in board.teams:
        return board.teams[key]
    nick = BOARD_NICKNAMES.get(key)
    if nick and nick in board.teams:
        return board.teams[nick]
    try:
        from automations.commission_sheet.names import match_person
        m = match_person(name, [board.names[k] for k in board.teams if k in board.names])[0]
    except Exception:                             # noqa: BLE001
        m = None
    return board.teams.get(_name_key(m), "") if m else ""


# --- carry-over -------------------------------------------------------------
def _hcol(head, h):
    """0-based column of header h on a payout tab — sheets made before the
    Team column (11/24) have everything one column to the left."""
    try:
        return [str(x).strip() for x in head].index(h)
    except ValueError:
        return PAYOUT_HEADERS.index(h) - (0 if "Team" in head else 1)


def carried_lines(sheet_id):
    """Last week's held new starts' sales, from last week's RH sheet."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    pay = _payout_ws(sh).get_values(value_render_option="UNFORMATTED_VALUE")
    e = _hcol(pay[0], "Level / Rule") if pay else 4
    held = {r[0] for r in pay[1:] if len(r) > e and str(r[e]).startswith("New start")}
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


def carried_customer_bonus(sheet_id):
    """{rep: $} — held new starts' Customer Bonus on last week's sheet, paid
    with their carried sales this week."""
    from automations.recruiting_report.fill import open_by_key
    pay = _payout_ws(open_by_key(sheet_id)).get_values(
        value_render_option="UNFORMATTED_VALUE")
    if not pay or "Customer Bonus" not in pay[0]:
        return {}
    c = pay[0].index("Customer Bonus")
    e = _hcol(pay[0], "Level / Rule")
    out = {}
    for r in pay[1:]:
        if len(r) > c and str(r[e]).startswith("New start") and money(r[c]):
            out[r[0]] = money(r[c])
    return out


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
    pcols = 5                                   # every titled column in row 1
    while wr.cell(1, pcols + 1).value not in (None, "") and pcols < len(PAYOUT_HEADERS):
        pcols += 1
    _header_row(wr, 1, 1, pcols)
    for r in range(2, last + 1):
        e = str(wr.cell(r, PC["Level / Rule"]).value or "") if pcols >= PC["Level / Rule"] else ""
        row_fill = None
        if str(wr.cell(r, 1).value).strip().upper() == "TOTAL":
            row_fill = LABEL_FILL
        elif e.startswith("New start"):
            row_fill = HELD_FILL
        elif e == NOTE_EXTRA:
            row_fill = EXTRA_FILL
        elif wr.cell(r, PC["Commission %"]).value in (None, ""):
            row_fill = MISSING_FILL             # no % yet — make it obvious
        elif (pcols >= PC["Guarantee"] and wr.cell(r, PC["Guarantee"]).value not in (None, "", 0)
              and not e.startswith("LinkedIn")):
            row_fill = GUARANTEE_FILL           # has a guarantee
        if row_fill:
            for c in range(1, pcols + 1):
                wr.cell(r, c).fill = row_fill
        is_total = str(wr.cell(r, 1).value).strip().upper() == "TOTAL"
        # A colored row (purple / orange / green / grey / TOTAL) keeps its color
        # all the way across; yellow and grey only on plain rows (Maud 11/24).
        if not row_fill:
            for c in INPUT_COLS:                  # typed in: light yellow
                if c <= pcols:
                    wr.cell(r, c).fill = INPUT_FILL
        if pcols >= FINAL_COL:                    # Final Pay stands out
            fc = wr.cell(r, FINAL_COL)
            fc.font = Font(bold=True)
            if not row_fill:
                fc.fill = FINAL_FILL
    _box(wr, 1, last, 1, pcols)
    if pcols >= PC["Lost Leadership Pay"]:
        # Lost leadership pay — auto-filled or typed in — turns the row pink.
        wr.conditional_formatting.add(
            f"A2:{get_column_letter(pcols)}{last}",
            FormulaRule(formula=[f'AND(LEFT(${PL["Lost Leadership Pay"]}2,4)="Lose",$A2<>"TOTAL")'],
                        fill=LOST_FILL,
                        stopIfTrue=True))

    for name in (TAB_EXTRA, TAB_CHECK):
        if name in wb.sheetnames:
            x = wb[name]
            w = sum(1 for c in x[1] if c.value not in (None, ""))
            _header_row(x, 1, 1, w)
            _box(x, 1, x.max_row, 1, w)
            if name == TAB_EXTRA:
                for row in x.iter_rows(min_row=2, max_row=x.max_row, max_col=w):
                    for c in row:
                        c.fill = INPUT_FILL

    for ws in wb.worksheets:
        if ws.title in NOT_REP_TABS:
            continue
        top = 1
        while ws.cell(top + 1, 1).value not in (None, ""):
            top += 1
        hdr = top + 2
        for r in range(1, top + 1):               # the top block, back to back
            label = str(ws.cell(r, 1).value or "")
            kind = _top_kind(r, label)
            fa, fb, color, size = TOP_LOOK[kind]
            for c, fill in ((1, fa), (2, fb)):
                cell = ws.cell(r, c)
                cell.alignment = CENTER
                cell.border = BORDER
                if fill:
                    cell.fill = PatternFill("solid", fgColor=fill)
                cell.font = Font(bold=(c == 1 or kind != "plain" and kind != "extra"),
                                 size=size, color=color)
            fmt = _top_fmt(label)
            if fmt and r > 1:
                ws.cell(r, 2).number_format = fmt
        ws.row_dimensions[1].height = 24
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


def _b_value(kind, pct, lvl, i, paid):
    """What the build puts in Commission % (B) on payout row i."""
    if paid and kind == "leader":
        return lost_formula(f"{PL['Lost Leadership Pay']}{i}", lvl)
    return pct if pct is not None else ""


def _auto_json(rep, lead, pct, f, manual=False):
    """Hidden auto column: what the system put in Commission % / Lost Leadership for THIS rep — no row
    numbers in it, so a sort can't make it point at the wrong row.
    manual = the row was added by hand (add_rep), so a re-make re-adds it."""
    import json
    d = {"rep": rep, "lead": bool(lead), "pct": pct, "f": f}
    if manual:
        d["manual"] = True
    return json.dumps(d)


def _auto_load(cell, rep):
    """The auto record for this row, or {} if missing / for another rep."""
    import json
    try:
        was = json.loads(cell) if cell else {}
    except ValueError:
        return {}
    return was if was.get("rep") == rep else {}


def _auto_b(was, i):
    """What B on row i would hold if nobody had typed over it."""
    if not was:
        return None
    if was.get("lead"):
        return lost_formula(f"{PL['Lost Leadership Pay']}{i}", was["pct"])
    return was["pct"] if was.get("pct") is not None else ""


def _same_cell(cur, want):
    if want in (None, ""):
        return cur in (None, "")
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return abs(float(cur) - want) < 1e-9
        except (TypeError, ValueError):
            return False
    return str(cur) == str(want)


def is_sunday_internet(rec):
    d = _date(rec["Sale Date"])
    return bool(d and d.weekday() == 6 and NEW_INTERNET.match(str(rec["Product"]).strip()))


#: Description Detail note on a DD line moved to another rep by hand (Maud
#: 2026-11-24: Joshua Mascorro's sale should have been a transfer to Amjad
#: Malhas). A re-make reads these back off the old sheet (hand_moves).
MOVED_NOTE = "Moved by hand from "


def main(src, out, use_board=True, carry_from=None, run_date=None,
         pending_file=None, transfers=True, write_transfers=False, moves=None):
    """moves: [{"customer", "to", optional "from" / "product" / "sale_date"}] —
    DD lines moved to another rep by hand (see MOVED_NOTE)."""
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
        rec["_spe"] = r[ix["cl.Production Lookup"]].strip()     # one per line
        rec["_ctype"] = r[ix["cl.Commission Type"]].strip()
        if is_sunday_internet(rec):
            rec[NOTE_COL] = _add_note(rec[NOTE_COL], SUNDAY_NOTE)
        edited.append(rec)

    carried, carried_from, carried_bonus = [], None, {}
    if carry_from:
        carried, carried_from = carried_lines(carry_from)
        carried_bonus = carried_customer_bonus(carry_from)
        edited += carried
    extras = sorted(set(extra_labels), key=str.lower)

    sunday = dd_sunday(raw, ix)
    board = Board()
    if use_board and sunday:
        try:
            board = read_board(sunday, run_date)
        except Exception as e:                          # noqa: BLE001
            print(f"!! could not read Raf's board ({type(e).__name__}: {e}) — "
                  "every % left blank")

    # ATT Sales Transfers: move transferred sales, customer bonuses, splits.
    cust_bonus = collections.defaultdict(list)          # rep key -> [(label, $)]
    for rep_, amt in carried_bonus.items():
        cust_bonus[_name_key(rep_)].append((f"Customer bonus ({carried_from})", amt))
    checks = []
    if transfers and sunday:
        from automations.commission_sheet import pct_transfers as T
        try:
            # one spelling per person — the DD's wins over the board's "(DJ)" form
            by_key = {}
            for nm in (list(board.names.values()) + list(BASE_PAY) + list(SPECIAL_PCT)
                       + [d["Rep Full Name"] for d in edited
                          if d["Rep Full Name"] not in extra_labels]):
                by_key[_name_key(nm)] = re.sub(r"\s*\([^)]*\)", "", nm).strip()
            roster = sorted(by_key.values())
            tws, tvals = T.load()
            tp = T.plan(tvals, edited, roster, f"WE {_md(sunday)}",
                        run_date or dt.date.today())
            for i, dst, why in tp.moves:
                edited[i]["Rep Full Name"] = dst
                edited[i][NOTE_COL] = _add_note(edited[i][NOTE_COL], why)
            for i in tp.split:
                edited[i][NOTE_COL] = _add_note(edited[i][NOTE_COL], T.SPLIT_NOTE)
            for rep_, label, amt in tp.bonuses:
                cust_bonus[_name_key(rep_)].append((label, amt))
            checks = tp.checks
            for line in tp.applied:
                print("   transfer " + line)
            print(f"   transfers: {len(tp.moves)} line(s) moved, {len(tp.bonuses)} "
                  f"customer bonus(es), {len(checks)} to check, "
                  f"{len(tp.updates)} status update(s)")
            if write_transfers:
                print(f"   wrote {T.write(tws, tvals, tp.updates)} status(es) to "
                      f"{T.C.TAB_TRANSFERS!r}")
        except Exception as e:                          # noqa: BLE001
            print(f"!! could not read ATT Sales Transfers ({type(e).__name__}: {e})")
    for mv in moves or []:                       # moved by hand (after transfers)
        hit = 0
        for d in edited:
            if str(d.get("Customer Name") or "").strip().lower() != mv["customer"].strip().lower():
                continue
            if mv.get("from") and _name_key(d["Rep Full Name"]) != _name_key(mv["from"]):
                continue
            if mv.get("product") and str(d["Product"]).strip().lower() != mv["product"].strip().lower():
                continue
            if mv.get("sale_date") and _date(d["Sale Date"]) != _date(mv["sale_date"]):
                continue
            if d["Rep Full Name"] == mv["to"]:
                continue
            d[NOTE_COL] = _add_note(d[NOTE_COL], MOVED_NOTE + d["Rep Full Name"])
            d["Rep Full Name"] = mv["to"]
            hit += 1
        print(f"   moved by hand: {mv['customer']} -> {mv['to']} ({hit} line(s))"
              + ("" if hit else "  !! no DD line matched"))
    edited.sort(key=lambda d: (d["Rep Full Name"].lower(), d["Product"].lower()))
    names_by_key = {_name_key(n): n for n in
                    list(board.names.values()) + [d["Rep Full Name"] for d in edited]}
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
    board.dd_apps = apps
    for key in list(cust_bonus) + list(board.guarantee) + [k for k in board.gas
                                         if gas_for(board.names.get(k, k), board, apps)]:
        if key not in have:
            names.add(names_by_key.get(key) or key.title())
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
    SPLIT = "Split sale"

    # --- Reps Name & Commission Payout ------------------------------------
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
        off = key in board.off                    # T / X all week: nothing at all
        pay = name not in extras and not off
        g_amt = board.guarantee.get(key, (None, ""))[0] if pay else None
        base = base_by_key.get(key) if pay else None
        bonus = bonus_by_key.get(key) if pay else None
        if g_amt:
            note += " · Guarantee"
        gas = gas_for(name, board, apps) if pay else None
        if lost:
            note += f" · {lost}"
        L_ = {hd: f"{c}{i}" for hd, c in PL.items()}   # this row's cells by header
        wr.cell(i, 1, name)
        wr.cell(i, PC["Team"], team_for(board, name) or None)
        paid = pct is not None and key not in no_comm
        leader = paid and kind == "leader"
        if leader:
            # Level 1-3: drop-down - / Lose 5% + App Tier / Lose 5% only (Maud 2026-11-27)
            p = wr.cell(i, PC["Commission %"], lost_formula(L_["Lost Leadership Pay"], lvl))
        else:
            p = wr.cell(i, PC["Commission %"], pct)
        p.number_format = "0%"
        # split sales are paid as customer bonuses, not commission
        wr.cell(i, PC["Revenue Brought In"],
                f'=SUMIF({A},A{i},{J})-SUMIFS({J},{A},A{i},{K},"*{SPLIT}*")'
                ).number_format = MONEY
        if kind != KIND_HELD:
            # Bonus (RAF PNL) is NOT in Total Payout (Maud 2026-11-24)
            hi, ji, ki, li, mi, oi = (L_[h] for h in (
                "Commission", "Guarantee", "Base Pay", "Gas Bonus",
                "Customer Bonus", "Training Bonus"))
            wr.cell(i, PC["Total Payout"],
                    f'=IF(COUNT({hi}:{oi})=0,"",MAX(N({hi}),N({ji}))'
                    f'+N({ki})+N({li})+N({mi})+N({oi}))').number_format = MONEY
        wr.cell(i, PC["Level / Rule"], note)
        wr.cell(i, PC["Lost Leadership Pay"], lost_val(lost) if leader else None)  # -> drop-down
        if name not in extras and kind != KIND_HELD:
            wr.cell(i, AUTO_COL, _auto_json(name, leader, lvl if leader else pct,
                                            lost_val(lost) if leader else None))
        # $0 -> empty (Maud 2026-11-24)
        sun = (f'SUMIFS({J},{A},A{i},{K},"*{SUNDAY_NOTE}*")'
               f'-SUMIFS({J},{A},A{i},{K},"*{SUNDAY_NOTE}*{SPLIT}*")')
        wr.cell(i, PC["Sunday Internet Revenue"], f'=IF({sun}=0,"",{sun})').number_format = MONEY
        if key not in no_comm:
            pb, rv, sg = L_["Commission %"], L_["Revenue Brought In"], L_["Sunday Internet Revenue"]
            wr.cell(i, PC["Commission"], f'=IF({pb}="","",({rv}-N({sg}))*{pb}'
                    f'+N({sg})*MAX({pb},{SUNDAY_INTERNET_PCT}))').number_format = MONEY
        cb = cust_bonus.get(key, []) if pay else []
        cb_amt = round(sum(a for _l, a in cb), 2) or None
        for hd, v in (("Guarantee", g_amt), ("Base Pay", base),
                      ("Bonus", bonus[0] if bonus else None),
                      ("Gas Bonus", gas), ("Customer Bonus", cb_amt)):
            if v is not None:
                wr.cell(i, PC[hd], v).number_format = MONEY
        X = f"'{TAB_EXTRA}'!"
        for typ in ("NPA", "Clawback"):
            sf = f'SUMIFS({X}$C:$C,{X}$A:$A,$A{i},{X}$B:$B,"{typ}")'
            # Clawback always shows negative, typed + or - (Maud 2026-11-25)
            wr.cell(i, PC[typ], f"=-ABS({sf})" if typ == "Clawback" else f"={sf}"
                    ).number_format = MONEY
        wr.cell(i, PC["Training Bonus"]).number_format = MONEY   # typed in, $
        wr.cell(i, PC["Extra Bonus"]).number_format = MONEY      # typed in
        # Final Pay leaves NPA / Clawback out (Maud 2026-11-24)
        tpc, xb = L_["Total Payout"], L_["Extra Bonus"]
        wr.cell(i, PC["Final Pay"], f'=IF(AND({tpc}="",N({xb})=0),"",'
                f'N({tpc})+N({xb}))').number_format = MONEY
        results[name] = (pct if not lost else lpct, kind, note, lost, g_amt, base,
                         bonus[0] if bonus else None, gas, cb)
        if pay and kind != KIND_HELD and not note.startswith(NOTE_NOT_ON):
            tabbed.append(name)
    n = len(reps) + len(extras) + 1
    t = n + 1
    wr.cell(t, 1, "TOTAL").font = Font(bold=True)
    for hd in ("Revenue Brought In", "Total Payout", "Sunday Internet Revenue",
               "Commission", "Guarantee", "Base Pay", "Bonus", "Gas Bonus",
               "Customer Bonus", "Training Bonus", "Extra Bonus",
               "Final Pay", "NPA", "Clawback"):
        col = PL[hd]
        c = wr[f"{col}{t}"]
        c.value = f"=SUM({col}2:{col}{n})"
        c.number_format, c.font = MONEY, Font(bold=True)
    wr.cell(1, AUTO_COL, AUTO_HEADER)
    wr.column_dimensions[get_column_letter(AUTO_COL)].hidden = True
    note_cell = f"{get_column_letter(AUTO_COL + 1)}1"
    wr[note_cell] = ("Yellow % can be typed over; each rep's tab follows. Level 1-3 "
                "reps have a Lost Leadership Pay drop-down: - = their level %, Lose 5% + App Tier = "
                "Entry Level 35% (late reps start on that; the reason is in Level / Rule), "
                "Lose 5% only = level % minus 5. Team = sales board. "
                "Total Payout = higher of Commission or Guarantee, + Base Pay + Gas Bonus + "
                "Customer Bonus + Training Bonus. Final Pay = Total Payout + Extra Bonus. "
                "Bonus (from RAF PNL), NPA and Clawback are listed after Final Pay, not in it "
                "(NPA / Clawback come from the Extra Payouts tab). "
                "Level 1-3: apps = board Apps that week; '(DD)' = not on that board, counted from "
                "their DD customers. Light yellow = type in. "
                "Orange = no level, type a %. Purple = new start, paid next week. "
                "Green = guarantee (not LinkedIn). Grey = DD line with no rep. Pink = lost leadership pay.")
    wr[note_cell].font = Font(italic=True)
    wr.auto_filter.ref = f"A1:{get_column_letter(AUTO_COL)}{n}"   # auto too: a sort must move it
    wr.freeze_panes = "B2"            # rep names (and the header) stay in view
    widths(wr, [28, 18, 14, 20, 14, 40, 22, 22, 14, 14, 14, 14, 16, 16, 14, 14, 14, 12, 12])

    # --- Extra: NPA / Clawback / Extra Bonus, typed in by hand ---------------
    from openpyxl.worksheet.datavalidation import DataValidation
    wx = wb.create_sheet(TAB_EXTRA)
    header(wx, ["Rep Name", "Type", "Amount", "Note"])
    for r in range(2, EXTRA_ROWS + 2):
        wx.cell(r, 3).number_format = MONEY
    # strict: a typed first name ("Pranish") would never be counted
    dv_rep = DataValidation(type="list", allow_blank=True, showErrorMessage=True,
                            errorStyle="stop", errorTitle="Pick a rep from the list",
                            error="Use the full name from the drop-down so it's counted.",
                            formula1=f"='{TAB_PAYOUT}'!$A$2:$A${n}")
    dv_typ = DataValidation(type="list", allow_blank=True,
                            formula1='"' + ",".join(EXTRA_TYPES) + '"')
    wx.add_data_validation(dv_rep)
    wx.add_data_validation(dv_typ)
    dv_rep.add(f"A2:A{EXTRA_ROWS + 1}")
    dv_typ.add(f"B2:B{EXTRA_ROWS + 1}")
    _carry_extras(wx, reps, sunday)
    wx["F1"] = ("Pick the rep and the type (NPA or Clawback). A Clawback shows as a "
                "negative on the payout tab and rep tab, whichever sign you type. Neither "
                "is part of Final Pay or the PNL; each shows as its own line with its "
                "note on the rep's tab.")
    wx["F1"].font = Font(italic=True)
    widths(wx, [28, 16, 14, 40])

    # --- Transfers to Check ---------------------------------------------------
    if checks:                                    # only when there's something
        wc = wb.create_sheet(TAB_CHECK)
        header(wc, ["Row on ATT Sales Transfers", "Submitted", "Your Name",
                    "Name the Sale is Under", "Customer", "Quantity", "Notes", "Why"])
        for row in checks:
            wc.append(row)
        widths(wc, [14, 18, 22, 22, 24, 18, 36, 50])

    # --- one tab per paid rep: every detail, then their sales ---------------
    used = {t.lower() for t in NOT_REP_TABS}
    look = f"'{TAB_PAYOUT}'!"
    for rep in tabbed:
        wt = wb.create_sheet(safe_title(rep, used))
        # Only what applies to this rep — nothing that's 0, blank or "No".
        _p, _k, _n, lost, g_amt, base, bonus, gas, cb = results[rep]
        rev = sum(d["Total $ to ICD"] for d in edited if d["Rep Full Name"] == rep)
        sun = sum(d["Total $ to ICD"] for d in edited if d["Rep Full Name"] == rep
                  and SUNDAY_NOTE in str(d[NOTE_COL] or ""))
        # no commission -> no Commission % row either (Maud 2026-11-24)
        show = {PL["Commission %"]: bool(rev) and _p is not None,
                PL["Revenue Brought In"]: bool(rev), PL["Sunday Internet Revenue"]: bool(sun),
                PL["Lost Leadership Pay"]: bool(lost),
                PL["Commission"]: bool(rev) and _p is not None, PL["Guarantee"]: bool(g_amt),
                PL["Base Pay"]: bool(base), PL["Bonus"]: bool(bonus), PL["Gas Bonus"]: bool(gas),
                PL["Total Payout"]: True}
        show[PL["Final Pay"]] = bool(bonus)      # Bonus sits after Final Pay
        for r, (a, b, c) in enumerate(top_spec(rep, show, cb, []), 1):
            wt.cell(r, 1, a)
            wt.cell(r, 2, b)
            if c:
                wt.cell(r, 3, c)
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


def copy_manual_entries(old_id, new_id):
    """After re-making a week's sheet: bring over what was typed by hand on
    the old one — Extra Payouts rows (first names resolved to the full rep
    name when there's exactly one), Lost Leadership ticks, typed Commission %
    / Training Bonus / Extra Bonus. Returns a short report."""
    from automations.commission_sheet.names import match_person
    from automations.recruiting_report.fill import open_by_key
    old, new = open_by_key(old_id), open_by_key(new_id)
    po = _payout_ws(old).get_values(value_render_option="FORMULA")
    report = []
    have = {r[0] for r in _payout_ws(new).get_values("A:A") if r}
    head_o = [str(x).strip() for x in po[0]]
    ao = head_o.index(AUTO_HEADER) if AUTO_HEADER in head_o else None   # old auto col
    for r in po[1:]:                              # reps added by hand: add again
        r = r + [""] * (len(head_o) + 1)
        if r[0] and r[0] not in have and ao is not None and _auto_load(r[ao], r[0]).get("manual"):
            add_rep(new_id, r[0], log=lambda m: None)
            report.append(f"{r[0]}: added by hand last time — added again")
    pn_ws = _payout_ws(new)
    pn = pn_ws.get_values(value_render_option="FORMULA")
    names = [r[0] for r in pn[1:] if r and r[0] and r[0] != "TOTAL"]
    row_of = {r[0]: i for i, r in enumerate(pn, 1) if r and r[0]}
    import json
    data = []
    c_pct, c_rule, c_lost = PC["Commission %"] - 1, PC["Level / Rule"] - 1, PC["Lost Leadership Pay"] - 1
    for oi, r in enumerate(po[1:], 2):
        if not r or r[0] not in row_of or r[0] == "TOTAL":
            continue
        i = row_of[r[0]]
        cells = dict(zip(head_o, r))
        was = _auto_load(r[ao], r[0]) if ao is not None and len(r) > ao else {}
        f = lost_norm(cells.get("Lost Leadership Pay"))
        new_row = pn[i - 1] + [""] * AUTO_COL
        has_box = lost_norm(new_row[c_lost]) is not None   # Level 1-3 only
        f_typed = has_box and f is not None and (not was or f != lost_norm(was.get("f")))
        if f_typed:                               # changed by hand
            data.append({"range": f"{PL['Lost Leadership Pay']}{i}", "values": [[f]]})
        b = cells.get("Commission %")
        m_old = (re.match(r"^=IF\([A-Z]+\d+=TRUE,[\d.]+,([\d.]+)\)$", b)
                 if isinstance(b, str) else None)
        if m_old:                                 # old tick-box formula -> drop-down one
            b = lost_formula(f"{PL['Lost Leadership Pay']}{i}", float(m_old.group(1)))
        elif isinstance(b, str) and b.startswith("=IF(") and '="Lose' in b:
            # point it at this sheet's Lost Leadership cell
            b = re.sub(r"\b[A-Z]+\d+=\"Lose", f'{PL["Lost Leadership Pay"]}{i}="Lose', b)
        blocked = (str(new_row[c_rule]).startswith("New start")
                   or "not paid" in str(new_row[c_rule]))
        if was:                                   # typed = differs from what was built
            b_typed = not _same_cell(b, _auto_b(was, i))
        else:                                     # older sheet: best guess
            b_typed = (b not in (None, "") and not str(b).startswith("=")
                       and str(new_row[c_pct]) != str(b))
        if b_typed and not blocked:
            data.append({"range": f"{PL['Commission %']}{i}", "values": [[b]]})
            report.append(f"{r[0]}: typed % {b}")
        for label in ("Training Bonus", "Extra Bonus"):
            col = PL[label]
            v = cells.get(label)
            if v not in (None, "") and not str(v).startswith("="):   # typed, not formula
                data.append({"range": f"{col}{i}", "values": [[v]]})
    if data:
        pn_ws.batch_update(data, value_input_option="USER_ENTERED")
    ex_old = next((w for w in old.worksheets() if w.title in (TAB_EXTRA, "Extra")), None)
    rows = []
    for r in (ex_old.get_values("A2:D400") if ex_old else []):
        if not any(r):
            continue
        r = (list(r) + ["", "", "", ""])[:4]
        typ = r[1].strip()
        who = r[0].strip()
        if typ not in EXTRA_TYPES:                # "Other" is gone (Maud 11/24)
            report.append(f"Extra Payouts: {who} {typ} {r[2]} not copied — type "
                          f"{'/'.join(EXTRA_TYPES)} only")
            continue
        if who not in names:
            m, cands = match_person(who, names)
            if not m:   # "Christopher W": first name + surname initial
                t = who.split()
                hits = [n for n in names if len(t) == 2 and n.lower().startswith(t[0].lower() + " ")
                        and n.split()[-1].lower().startswith(t[1].lower().rstrip("."))]
                m = hits[0] if len(hits) == 1 else None
            if not m:   # a typo: one close spelling
                import difflib
                close = difflib.get_close_matches(who, names, n=2, cutoff=0.7) or \
                    [n for n in names if difflib.SequenceMatcher(
                        None, who.lower(), n.split()[0].lower()).ratio() >= 0.8]
                m = close[0] if len(close) == 1 else None
            if m:
                report.append(f"Extra Payouts: {who!r} -> {m}")
                who = m
            else:
                report.append(f"Extra Payouts: {who!r} is not on this sheet — not counted")
        rows.append([who, typ, r[2], r[3]])
    if ex_old:   # the old sheet's list wins over the build's carried rows
        new.worksheet(TAB_EXTRA).batch_clear([f"A2:D{EXTRA_ROWS + 1}"])
    if rows:
        ws = new.worksheet(TAB_EXTRA)
        ws.update(values=rows, range_name=f"A2:D{len(rows) + 1}",
                  value_input_option="USER_ENTERED", raw=False)
    return report


def add_rep(sheet_id, name, log=print):
    """Google Sheets: add a rep who isn't on this week's DD (e.g. someone only
    getting a Training Bonus — Maud 2026-11-24, Brian Sigman) — a payout row
    in alphabetical order with the same formulas as everyone else, the board's
    % / Level / Rule, and their own tab. Type their bonus in afterwards.
    Flagged in the hidden auto record, so a re-make adds them again."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    ws = _payout_ws(sh)
    rows = ws.get_values(value_render_option="FORMULA")
    names = [str(r[0]).strip() if r else "" for r in rows]
    if name in names:
        log(f"{name} is already on the payout tab")
        return None
    raw = sh.worksheet(TAB_RAW).get_values()
    ix = {h.strip(): i for i, h in enumerate(raw[0])}
    dds = dd_sunday(raw[1:], ix)
    board = read_board(dds, run_date=dds + dt.timedelta(days=7))
    pct, kind, note, lost, lvl = rule_for(name, board)
    if kind == KIND_HELD:                         # nothing to hold: no sales
        pct, kind, note = None, KIND_MISSING, "New start (no sales this week)"
    leader = pct is not None and kind == "leader"
    total = names.index("TOTAL") + 1
    c_rule, c_tp, c_g, c_pct = (PC[h] - 1 for h in ("Level / Rule", "Total Payout",
                                                     "Guarantee", "Commission %"))
    reps = [(i, n) for i, n in enumerate(names[:total - 1], 1)
            if i > 1 and n and str((rows[i - 1] + [""] * AUTO_COL)[c_rule]) != NOTE_EXTRA]
    # a plain row of the same sort to copy formulas + look from
    def plain(i):
        r = rows[i - 1] + [""] * AUTO_COL
        return (str(r[c_tp]).startswith("=") and not r[c_g]
                and str(r[c_pct]).startswith("=IF(") == leader and r[c_pct] not in ("", None))
    ref = next((i for i, _n in reps if plain(i)), reps[0][0])
    at = next((i for i, n in reps if n.lower() > name.lower()), reps[-1][0])
    at = max(at, 3)                               # inside the TOTAL sums
    if ref >= at:
        ref += 1
    sid = ws.id
    rng = lambda r: {"sheetId": sid, "startRowIndex": r - 1, "endRowIndex": r,
                     "startColumnIndex": 0, "endColumnIndex": AUTO_COL}
    sh.batch_update({"requests": [
        {"insertDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                       "startIndex": at - 1, "endIndex": at},
                             "inheritFromBefore": True}},
        {"copyPaste": {"source": rng(ref), "destination": rng(at),
                       "pasteType": "PASTE_NORMAL"}}]})
    i = at
    b = _b_value(kind, pct, lvl, i, pct is not None)
    vals = [{"range": f"A{i}", "values": [[name]]},
            {"range": f"{PL['Team']}{i}", "values": [[team_for(board, name)]]},
            {"range": f"{PL['Commission %']}{i}", "values": [[b]]},
            {"range": f"{PL['Level / Rule']}{i}", "values": [[note]]},
            {"range": f"{PL['Lost Leadership Pay']}{i}", "values": [[lost_val(lost) if leader else ""]]},
            {"range": f"{PL['Guarantee']}{i}:{PL['Training Bonus']}{i}",
             "values": [[""] * (PC["Training Bonus"] - PC["Guarantee"] + 1)]},
            {"range": f"{PL['Extra Bonus']}{i}", "values": [[""]]},
            {"range": f"{PL['Bonus']}{i}", "values": [[""]]},
            {"range": f"{get_column_letter(AUTO_COL)}{i}",
             "values": [[_auto_json(name, leader, lvl if leader else pct,
                                    lost_val(lost) if leader else None, manual=True)]]}]
    ws.batch_update(vals, value_input_option="USER_ENTERED")
    if not leader:                                # no drop-down for non-leaders
        sh.batch_update({"requests": [{"setDataValidation": {"range": {
            "sheetId": sid, "startRowIndex": i - 1, "endRowIndex": i,
            "startColumnIndex": PC["Lost Leadership Pay"] - 1,
            "endColumnIndex": PC["Lost Leadership Pay"]}}}]})
    # their tab, in name order among the rep tabs
    tabs = sh.worksheets()
    title = safe_title(name, {w.title.lower() for w in tabs})
    after = [w for w in tabs if w.title not in NOT_REP_TABS and w.title.lower() < title.lower()]
    index = (after[-1].index + 1) if after else len(tabs)
    wt = sh.add_worksheet(title=title, rows=60, cols=12, index=index)
    wt.update(values=[["Rep", name]], range_name="A1:B1")
    sh.batch_update({"requests": [{"updateDimensionProperties": {
        "range": {"sheetId": wt.id, "dimension": "COLUMNS", "startIndex": c,
                  "endIndex": c + 1}, "properties": {"pixelSize": w},
        "fields": "pixelSize"}} for c, w in ((0, 220), (1, 240), (2, 220))]})
    refresh_rep_tabs(sheet_id, log=log)
    log(f"added {name} on row {i} ({note or 'no rule'}) + tab {title!r}")
    return i


def hand_moves(sheet_id):
    """DD lines moved by hand on a sheet (MOVED_NOTE in Description Detail),
    as `moves` for main() — so a re-make keeps them."""
    from automations.recruiting_report.fill import open_by_key
    ed = open_by_key(sheet_id).worksheet(TAB_EDITED).get_values()
    h = {c: i for i, c in enumerate(ed[0])}
    out = []
    for r in ed[1:]:
        r = r + [""] * len(h)
        note = r[h[NOTE_COL]]
        if MOVED_NOTE in note:
            src = note.split(MOVED_NOTE, 1)[1].split(" · ")[0].strip()
            out.append({"customer": r[h["Customer Name"]], "from": src,
                        "to": r[h["Rep Full Name"]], "product": r[h["Product"]],
                        "sale_date": r[h["Sale Date"]]})
    return out


def rebuild(old_id, dd, out, name, order_log=None, carry_from=None,
            moves=(), log=print):
    """Re-make a live sheet from the DD: keeps its hand moves (plus any new
    `moves`), then remake() keeps every other hand entry."""
    mv = hand_moves(old_id) + list(moves)
    main(dd, out, carry_from=carry_from, pending_file=order_log, moves=mv)
    return remake(old_id, out, name, log=log)


def remake(old_id, xlsx, name, log=print):
    """Replace a live RH sheet with a new build and KEEP everything typed or
    changed by hand on the old one (Maud 2026-11-24): upload -> checkboxes ->
    copy_manual_entries -> fit -> groups -> board check -> rep tabs -> trash
    the old one (Drive trash, recoverable). Returns the new sheet id."""
    from automations.commission_sheet import weekly_drop as W
    from automations.commission_sheet.drive_auth import service
    svc = service()
    made = W.upload(svc, Path(xlsx), name)
    new = made["id"]
    log(f"uploaded {name!r}  {made.get('webViewLink', '')}")
    add_checkboxes(new)
    for line in copy_manual_entries(old_id, new):
        log(f"  kept: {line}")
    fit_columns(new)
    group_columns(new)
    sync_from_board(new, log=log)
    refresh_rep_tabs(new, log=log)
    svc.files().update(fileId=old_id, body={"trashed": True},
                       supportsAllDrives=True).execute()
    log(f"old version {old_id} moved to the Drive trash")
    return new


def fit_columns(sheet_id):
    """Google Sheets: fit every payout-tab column (A to the last header) to its
    text (Maud 2026-11-24). Done after upload — an .xlsx can't carry auto-fit."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    ws = _payout_ws(sh)
    sh.batch_update({"requests": [{"autoResizeDimensions": {"dimensions": {
        "sheetId": ws.id, "dimension": "COLUMNS",
        "startIndex": 0, "endIndex": len(PAYOUT_HEADERS)}}}]})
    return len(PAYOUT_HEADERS)


#: Collapsible column groups on the payout tab (Maud 2026-11-24): the pay
#: breakdown (Sunday Internet .. Training Bonus) and Bonus / NPA / Clawback.
#: 0-based, end exclusive.
PAYOUT_GROUPS = ((PC["Sunday Internet Revenue"] - 1, PC["Training Bonus"]),
                 (PC["Bonus"] - 1, PC["Clawback"]))


def group_columns(sheet_id):
    """Google Sheets: add the payout tab's column groups (skips any that are
    already there, so a re-run doesn't nest them)."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    ws = _payout_ws(sh)
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),columnGroups)"})
    have = set()
    for sheet in meta["sheets"]:
        if sheet["properties"]["sheetId"] == ws.id:
            have = {(g["range"]["startIndex"], g["range"]["endIndex"])
                    for g in sheet.get("columnGroups", [])}
    reqs = [{"addDimensionGroup": {"range": {
        "sheetId": ws.id, "dimension": "COLUMNS", "startIndex": a, "endIndex": b}}}
        for a, b in PAYOUT_GROUPS if (a, b) not in have]
    # The +/- sits at the START of each group, over its first column (Maud
    # 2026-11-24: "the other way" — Sheets puts it after the group by default).
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": ws.id,
                       "gridProperties": {"columnGroupControlAfter": False}},
        "fields": "gridProperties.columnGroupControlAfter"}})
    sh.batch_update({"requests": reqs})
    return len(reqs) - 1


def add_checkboxes(sheet_id):
    """Google Sheets: put the - / Lose 5% + App Tier / Lose 5% only drop-down on every
    Level 1-3 row of the payout tab's Lost Leadership Pay column (an .xlsx
    upload can't carry one). Old TRUE/FALSE boxes are turned into the drop-down."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    ws = _payout_ws(sh)
    lc = PL["Lost Leadership Pay"]
    col = ws.get_values(f"{lc}1:{lc}400", value_render_option="UNFORMATTED_VALUE")
    rows = [(i, lost_norm(r[0])) for i, r in enumerate(col[1:], 2)
            if r and lost_norm(r[0]) is not None]
    reqs = [{"setDataValidation": {
        "range": {"sheetId": ws.id, "startRowIndex": r - 1, "endRowIndex": r,
                  "startColumnIndex": PC["Lost Leadership Pay"] - 1,
                  "endColumnIndex": PC["Lost Leadership Pay"]},
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": c} for c in LOST_CHOICES]},
                 "strict": True, "showCustomUi": True}}}
        for r, _v in rows]
    if reqs:
        sh.batch_update({"requests": reqs})
        ws.batch_update([{"range": f"{lc}{r}", "values": [[v]]} for r, v in rows],
                        value_input_option="USER_ENTERED")
    return len(reqs)


def _rgb(hexs):
    return {"red": int(hexs[0:2], 16) / 255, "green": int(hexs[2:4], 16) / 255,
            "blue": int(hexs[4:6], 16) / 255}


def _api_cell(v, *, fmt=None, fill=None, bold=False, italic=False, size=None,
              color=None, left=False, border=True):
    """A Sheets API CellData with the same look style_workbook gives the .xlsx."""
    if v in (None, ""):
        val = None
    elif isinstance(v, bool):
        val = {"boolValue": v}
    elif isinstance(v, (int, float)):
        val = {"numberValue": v}
    elif str(v).startswith("="):
        val = {"formulaValue": str(v)}
    else:
        val = {"stringValue": str(v)}
    font = {"bold": bold, "italic": italic}
    if size:
        font["fontSize"] = size
    if color:
        font["foregroundColor"] = _rgb(color)
    f = {"horizontalAlignment": "LEFT" if left else "CENTER",
         "verticalAlignment": "MIDDLE", "textFormat": font}
    if fill:
        f["backgroundColor"] = _rgb(fill)
    if fmt:
        f["numberFormat"] = ({"type": "PERCENT", "pattern": fmt} if "%" in fmt
                             else {"type": "CURRENCY", "pattern": fmt})
    if border:
        edge = {"style": "SOLID", "color": _rgb("8EA9C8")}
        f["borders"] = {k: edge for k in ("top", "bottom", "left", "right")}
    cell = {"userEnteredFormat": f}
    if val:
        cell["userEnteredValue"] = val
    return cell


def _api_top_row(r, a, b, c):
    kind = _top_kind(r, a)
    fa, fb, color, size = TOP_LOOK[kind]
    strong = kind in ("name", "total", "final")
    fmt = _top_fmt(a) if r > 1 else None
    cells = [_api_cell(a, fill=fa, bold=True, size=size, color=color),
             _api_cell(b, fmt=fmt, fill=fb, bold=strong, size=size, color=color)]
    cells.append({})                        # col C: {} + the fields mask = cleared
    return {"values": cells}


def _nz(v):
    try:
        return float(v or 0) != 0
    except (TypeError, ValueError):
        return False


def _same(x, y):
    try:
        return round(float(x), 2) == round(float(y), 2)
    except (TypeError, ValueError):
        return str(x if x is not None else "").strip() == str(y if y is not None else "").strip()


def sync_from_board(sheet_id, log=print):
    """Google Sheets: re-read Raf's sales board (levels, LinkedIn, apps, T/X,
    lateness, guarantee, gas bonus) and update the payout tab — Level / Rule,
    Guarantee, Gas Bonus, and Commission % / Lost Leadership tick unless typed
    over by hand (Maud 2026-11-24: "always recheck the sales board"). Rows that
    would change between held / not held, or that would need a new rep tab, are
    only reported. Returns the changed rep names."""
    import json
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    ws = _payout_ws(sh)
    rows = ws.get_values(value_render_option="FORMULA")
    head = rows[0] + [""] * AUTO_COL
    if head[AUTO_COL - 1] != AUTO_HEADER:
        log("   board check: sheet has no auto column (made before 11/24) — skipped")
        return []
    raw = sh.worksheet(TAB_RAW).get_values()
    ix = {h.strip(): i for i, h in enumerate(raw[0])}
    dds = dd_sunday(raw[1:], ix)
    board = read_board(dds, run_date=dds + dt.timedelta(days=7))
    ed = sh.worksheet(TAB_EDITED).get_values()
    eh = {h: i for i, h in enumerate(ed[0])}
    custs = collections.defaultdict(set)
    for r in ed[1:]:
        r = r + [""] * len(eh)
        if r[eh["Customer Name"]]:
            custs[_name_key(r[eh["Rep Full Name"]])].add(r[eh["Customer Name"]].strip().lower())
    apps = {k: len(v) for k, v in custs.items()}
    board.dd_apps = apps
    data, changed, notes = [], [], []
    c_rule, c_pct, c_lost = (PC[h] - 1 for h in ("Level / Rule", "Commission %",
                                                  "Lost Leadership Pay"))
    for i, r in enumerate(rows[1:], 2):
        r = r + [""] * AUTO_COL
        name, e_cur, auto = str(r[0]).strip(), str(r[c_rule]), r[AUTO_COL - 1]
        if not name or name == "TOTAL" or e_cur == NOTE_EXTRA:
            continue
        key = _name_key(name)
        pct, kind, note, lost, lvl = rule_for(name, board)
        held_now = e_cur.startswith("New start")
        if held_now != (kind == KIND_HELD) or (not auto and kind != KIND_HELD):
            if held_now != (kind == KIND_HELD):
                notes.append(f"{name}: board now says {'held' if kind == KIND_HELD else 'not held'}"
                             " — re-make the sheet to change that")
            continue
        if held_now:
            continue
        off = key in board.off
        g_amt = None if off else board.guarantee.get(key, (None, ""))[0]
        gas = None if off else gas_for(name, board, apps)
        if g_amt:
            note += " · Guarantee"
        if lost:
            note += f" · {lost}"
        leader = pct is not None and kind == "leader"
        want_b = _b_value(kind, pct, lvl, i, pct is not None)
        want_f = lost_val(lost) if leader else None
        was = _auto_load(auto, name)
        upd = {}
        if e_cur != note:
            upd[PL["Level / Rule"]] = note
        team = team_for(board, name)
        if team and str(r[PC["Team"] - 1]).strip() != team:
            upd[PL["Team"]] = team                # Team follows the board
        for h, v in (("Guarantee", g_amt), ("Gas Bonus", gas)):
            if not _same_cell(r[PC[h] - 1], v):
                upd[PL[h]] = v if v is not None else ""
        b_auto = bool(was) and _same_cell(r[c_pct], _auto_b(was, i))   # not typed over
        if b_auto and not _same_cell(r[c_pct], want_b):
            upd[PL["Commission %"]] = want_b      # follow the board
        f_cur = lost_norm(r[c_lost])
        f_auto = bool(was) and was.get("f") is not None and f_cur == lost_norm(was["f"])
        if f_auto and want_f is not None and f_cur != want_f:
            upd[PL["Lost Leadership Pay"]] = want_f
        if e_cur.startswith(NOTE_NOT_ON) and not note.startswith(NOTE_NOT_ON):
            notes.append(f"{name}: now on the board — re-make the sheet for their tab")
        if not upd:
            continue
        if b_auto or f_auto:
            upd[get_column_letter(AUTO_COL)] = _auto_json(
                name, leader if b_auto else was["lead"],
                (lvl if leader else pct) if b_auto else was["pct"],
                want_f if f_auto and want_f is not None else was["f"],
                manual=was.get("manual", False))
        for col, v in upd.items():
            data.append({"range": f"{col}{i}", "values": [[v]]})
        changed.append(f"{name} ({', '.join(c for c in upd if c != get_column_letter(AUTO_COL))})")
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")
    log(f"   board check: {len(changed)} row(s) updated"
        + (f": {'; '.join(changed)}" if changed else ""))
    for n in notes:
        log(f"   !! {n}")
    return changed


def refresh_rep_tabs(sheet_id, log=print, force=False):
    """Google Sheets: re-lay every rep tab's top block from what's on the sheet
    now — rows back to back, only what applies, one row per Extra Payouts entry
    (NPA / Clawback / Other) with its note in column C (Maud 2026-11-24).
    Rows are inserted / deleted above the sales so nothing below moves out of
    place. A tab that already matches is left alone, so a pass with nothing
    new typed in changes nothing (force=True re-writes every tab, e.g. after
    a look change). Returns the tabs it changed."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    pv = _payout_ws(sh).get_values(value_render_option="UNFORMATTED_VALUE")
    pay = {str(r[0]).strip(): list(r) + [""] * len(PAYOUT_HEADERS)
           for r in pv[1:] if r and r[0]}
    extras = collections.defaultdict(list)
    try:
        ex = sh.worksheet(TAB_EXTRA).get_values(
            f"A2:D{EXTRA_ROWS + 1}", value_render_option="UNFORMATTED_VALUE")
    except Exception:                             # noqa: BLE001 — older sheet
        ex = []
    for r in ex:
        r = (list(r) + ["", "", "", ""])[:4]
        if str(r[0]).strip() and str(r[1]).strip() in EXTRA_TYPES and _nz(r[2]):
            extras[str(r[0]).strip()].append(
                (str(r[1]).strip(), float(r[2]), str(r[3] or "").strip()))

    skip = set(NOT_REP_TABS) | {OLD_TAB_PAYOUT, "Extra"}
    tabs = [w for w in sh.worksheets() if w.title not in skip]
    if not tabs:
        return []
    got = sh.values_batch_get([f"'{w.title}'!A1:C60" for w in tabs],
                              params={"valueRenderOption": "FORMULA"})["valueRanges"]
    reqs, changed = [], []
    # Sheets made before 11/24 had label-fill conditional rules on the rep
    # tabs' top rows; they'd paint over the cyan / grey -> drop them.
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),conditionalFormats)"})
    tab_ids = {w.id for w in tabs}
    for sheet in meta["sheets"]:
        sid = sheet["properties"]["sheetId"]
        if sid in tab_ids:
            for k in reversed(range(len(sheet.get("conditionalFormats", [])))):
                reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": k}})
    for w, vr in zip(tabs, got):
        cur = [(list(r) + ["", "", ""])[:3] for r in vr.get("values", [])]
        if not cur or cur[0][0] != "Rep":
            continue
        rep = str(cur[0][1]).strip()
        top = 0
        while top < len(cur) and str(cur[top][0]).strip():
            top += 1
        row = pay.get(rep)
        if row is None:
            log(f"   refresh: {rep!r} not on the payout tab — tab left alone")
            continue
        v = {h: row[PC[h] - 1] for h in PAYOUT_HEADERS}
        show = {PL["Commission %"]: v["Commission %"] not in (None, "") and _nz(v["Commission"]),
                PL["Lost Leadership Pay"]: is_lost(v["Lost Leadership Pay"]),
                PL["Total Payout"]: True,
                **{PL[h]: _nz(v[h]) for h in (
                    "Revenue Brought In", "Sunday Internet Revenue", "Commission",
                    "Guarantee", "Base Pay", "Bonus", "Gas Bonus", "Training Bonus",
                    "Extra Bonus")},
                # Final Pay shown when something sits around it (Maud 11/24)
                PL["Final Pay"]: (_nz(v["Extra Bonus"]) or _nz(v["Bonus"])
                                  or bool(extras.get(rep)))}
        cb = [(a, b) for a, b, _c in cur[1:top]
              if str(a).strip() and str(a) not in STD_LABELS
              and not _extra_type(a) and not str(a).startswith("=")]
        want = top_spec(rep, show, cb, extras.get(rep, []))
        if not force and len(want) == top and all(
                _same(x, y) for wr, cr in zip(want, cur[:top]) for x, y in zip(wr, cr)):
            continue
        sid = w.id
        if len(want) > top:
            reqs.append({"insertDimension": {"range": {
                "sheetId": sid, "dimension": "ROWS", "startIndex": top,
                "endIndex": len(want)}, "inheritFromBefore": True}})
        elif len(want) < top:
            reqs.append({"deleteDimension": {"range": {
                "sheetId": sid, "dimension": "ROWS", "startIndex": len(want),
                "endIndex": top}}})
        reqs.append({"updateCells": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": len(want),
                      "startColumnIndex": 0, "endColumnIndex": 3},
            "rows": [_api_top_row(i, *t) for i, t in enumerate(want, 1)],
            "fields": "userEnteredValue,userEnteredFormat"}})
        changed.append(w.title)
    if reqs:
        sh.batch_update({"requests": reqs})
    log(f"   refresh: {len(changed)} rep tab(s) re-laid"
        + (f": {', '.join(changed)}" if changed else " (nothing new)"))
    update_rep_pnl(sheet_id, log)
    return changed


def update_rep_pnl(sheet_id, log=print):
    """Same change onto Bas / MJ / OG / Algemar PNL tabs (Brought In, Got Paid,
    new reps on their trainer's tab) — every build / re-make / refresh (Maud's
    Loom 2026-11-24). A failure here is reported, never stops the sheet work."""
    try:
        from automations.commission_sheet.rep_pnl import fill
        fill(sheet_id, write=True, log=log)
    except Exception as e:                          # noqa: BLE001
        log(f"   !! rep PNL not updated ({type(e).__name__}: {e})")


def cli(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dd-file", help="already-downloaded ORG DD Detail crosstab")
    ap.add_argument("--restyle", help="existing workbook to rename + restyle only")
    ap.add_argument("--out", help="where to save the .xlsx")
    ap.add_argument("--no-board", action="store_true",
                    help="don't read Raf's board (every %% left blank)")
    ap.add_argument("--write-transfers", action="store_true",
                    help="write PAID / PARTIALLY / CANCELLED back to ATT Sales Transfers")
    ap.add_argument("--order-log-file", help="already-downloaded Order Log crosstab "
                    "(else it's pulled from Tableau)")
    ap.add_argument("--refresh", metavar="SHEET_ID",
                    help="re-lay the rep tabs' top blocks on this Google Sheet, then stop")
    ap.add_argument("--carry-from", help="last week's RH sheet id: carry its held "
                                         "new starts' sales onto this week")
    a = ap.parse_args(argv)
    if a.refresh:  # noqa: SIM102
        sync_from_board(a.refresh)
        refresh_rep_tabs(a.refresh)
        return
    if not a.out:
        ap.error("--out is required")
    if a.restyle:
        restyle(a.restyle, a.out)
        return
    dd = a.dd_file
    if not dd:
        from automations.commission_sheet.sources import fetch_dd
        dd = fetch_dd()
    main(dd, a.out, use_board=not a.no_board, carry_from=a.carry_from,
         pending_file=a.order_log_file, write_transfers=a.write_transfers)


if __name__ == "__main__":
    cli()
