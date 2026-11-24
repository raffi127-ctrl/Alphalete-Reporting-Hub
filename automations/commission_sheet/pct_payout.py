"""Raf's %-commission workbook (Raf Loom 2026-11-23; Maud owns the build).

Raf pays his local-office reps a % of the revenue they bring in. From the ORG
DD Detail crosstab this builds an .xlsx with:

  Edited    the columns Raf keeps, sorted by rep, plus a Note column (Sunday
            internet, carried-over new-start sales). cl.Category WEARABLES /
            TABLET copied into the empty cl.Product cell.
  Reps Name & Commission payout
            A Rep | B % (yellow, editable) | C Revenue | D Payout | E Level /
            rule | F Lost Leadership Pay | G Sunday Internet revenue.
  <rep>     one tab per rep: revenue, %, payout (all from the payout tab) +
            that rep's sales.
  Raw       Raf's office rows untouched. ALWAYS present - require_raw()
            refuses to save a workbook without it.

THE % RULES (Maud 2026-11-24, "How You Get Paid" grid). First match wins:

  1  NEW START HELD — in the New Starts box of the board 3 boards back (DD
     week Sunday - 14 days). % blank, purple. Their sales are carried onto
     NEXT week's sheet (pass the previous week's sheet as carry_from).
  2  SPECIAL DEAL — SPECIAL_PCT (Willie Henderson, Chloe Johnson, Bas El
     Hassan, Thomas Crenshaw 70%; Amjad Malhas 85%), every week.
  3  LINKEDIN — 'Linkedin' in the board's "Add applied to" column (DY) on
     either of the last 2 boards -> 70%.
  4  BOARD LEVEL — Leadership Status on the last 2 boards (newest first):
     In Training / Entry 35%, Level 1/2/3 40%, Mastermind 70%.
     LOST LEADERSHIP PAY: a Level 1/2/3 rep who was 'Late' on the Saturday
     roll call of the DD week's board, or 'Late' 2+ times that week, gets 35%.
     Column B is =IF(F="", 40%, 35%), so typing anything in F (the manual
     "lost leadership pay") also drops them to 35%; pink row.
  5  otherwise — not on the last 2 boards, or in the New Starts box with no
     level: % blank, orange.

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
    ("Note", None),                       # filled by the rules, not the DD
]
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
}
LINKEDIN_PCT = 0.70
SUNDAY_INTERNET_PCT = 0.85
SUNDAY_NOTE = "Sunday internet 85%"
#: New internet only — upgrades ('Upgrade Internet 1000') don't qualify.
NEW_INTERNET = re.compile(r"^internet \d+$", re.I)
#: DD lines with no rep that are NOT shown (Maud: Captain Bonus can't be on it).
NO_REP_SKIP = {"captain bonus", "captain's bonus"}
BOARD_COUNT = 2                      # "the last 2 boards"
NEW_START_LAG_DAYS = 14              # box 3 boards back = DD Sunday - 14

KIND_HELD, KIND_EXTRA, KIND_MISSING = "held", "extra", "missing"
NOTE_HELD = "New start — held, paid next week"
NOTE_EXTRA = "No rep on this DD line"

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")       # editable %
MISSING_FILL = PatternFill("solid", fgColor="F8CBAD")     # orange: type a %
HELD_FILL = PatternFill("solid", fgColor="D9D2E9")        # purple: new start held
EXTRA_FILL = PatternFill("solid", fgColor="D9D9D9")       # grey: no rep
LOST_FILL = PatternFill("solid", fgColor="F4B6C2")        # pink: lost leadership
MONEY = '"$"#,##0.00'
LABEL_FILL = PatternFill("solid", fgColor="DDEBF7")       # rep-tab labels, TOTAL
CENTER = Alignment(horizontal="center", vertical="center")
_EDGE = Side(style="thin", color="8EA9C8")
BORDER = Border(left=_EDGE, right=_EDGE, top=_EDGE, bottom=_EDGE)
TAB_EDITED = "Edited"
TAB_PAYOUT = "Reps Name & Commission payout"
TAB_RAW = "Raw"
PAYOUT_HEADERS = ["Rep Name", "Commission %", "Revenue Brought In", "Payout",
                  "Level / rule", "Lost Leadership Pay", "Sunday Internet Revenue"]


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
    if isinstance(s, (dt.date, dt.datetime)):
        return s if isinstance(s, dt.date) else s.date()
    try:
        m, d, y = (int(x) for x in str(s).strip().split("/"))
        return dt.date(y, m, d)
    except ValueError:
        return None


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
        for r in lay.roster_rows:
            key = _name_key(BD._cell(grid, r, lay.name_col))
            if not key:
                continue
            b.on_boards.add(key)
            level = BD._norm(BD._cell(grid, r, lv_col)) if lv_col else ""
            if level and key not in b.levels:
                b.levels[key] = (level, title)
            if li_col and "linkedin" in BD._norm(BD._cell(grid, r, li_col)).replace(" ", ""):
                b.linkedin.setdefault(key, title)
        for r in _box_rows(BD, grid, lay):
            key = _name_key(BD._cell(grid, r, lay.box_name_col))
            b.on_boards.add(key)
            b.in_box.add(key)
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


def rule_for(rep, board):
    """(pct, kind, note in E, lost-leadership reason for F, level pct if leader).

    kind: 'held' | 'missing' | 'leader' | 'set'."""
    key = _name_key(rep)
    if key in board.held:
        return None, KIND_HELD, NOTE_HELD, "", None
    specials = {_name_key(n): p for n, p in SPECIAL_PCT.items()}
    if key in specials:
        return specials[key], "set", "Special deal", "", None
    if key in board.linkedin:
        return LINKEDIN_PCT, "set", f"LinkedIn ({board.linkedin[key].replace('Sales Board ', '')})", "", None
    if key in board.levels:
        level, tab = board.levels[key]
        note = f"{level.title()} ({tab.replace('Sales Board ', '')})"
        if level not in LEVEL_PCT:
            return None, KIND_MISSING, f"{level.title()} — no % for this level", "", None
        pct = LEVEL_PCT[level]
        if level in LEADER_LEVELS:
            return pct, "leader", note, board.late.get(key, ""), pct
        return pct, "set", note, "", None
    if key in board.in_box:
        return None, KIND_MISSING, "New Starts box — no level", "", None
    return None, KIND_MISSING, "Not on the last 2 boards", "", None


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
            prior = rec["Note"]
            rec["Note"] = label + (f" · {prior}" if prior and label not in prior else "")
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
    while wr.cell(1, pcols + 1).value not in (None, "") and pcols < 7:
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
            FormulaRule(formula=['AND($F2<>"",$A2<>"TOTAL")'], fill=LOST_FILL,
                        stopIfTrue=True))

    for ws in wb.worksheets:
        if ws.title in (TAB_EDITED, TAB_PAYOUT, TAB_RAW):
            continue
        for r in range(1, 5):                     # Rep / Revenue / % / Payout
            ws.cell(r, 1).fill = LABEL_FILL
        _box(ws, 1, 4, 1, 2)
        if ws.max_row >= 6:                       # header row 6, sales from 7
            _header_row(ws, 6, 1, ncol - 1)
            _fill_by_product(ws, 7, ws.max_row, ncol - 1, 3, fills)
            _box(ws, 6, ws.max_row, 1, ncol - 1)

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


def main(src, out, use_board=True, carry_from=None, run_date=None):
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
            rec["Note"] = SUNDAY_NOTE
        edited.append(rec)

    carried, carried_from = [], None
    if carry_from:
        carried, carried_from = carried_lines(carry_from)
        edited += carried
    edited.sort(key=lambda d: (d["Rep Full Name"].lower(), d["Product"].lower()))
    extras = sorted(set(extra_labels), key=str.lower)
    reps = sorted({d["Rep Full Name"] for d in edited} - set(extras), key=str.lower)

    sunday = dd_sunday(raw, ix)
    board = Board()
    if use_board and sunday:
        try:
            board = read_board(sunday, run_date)
        except Exception as e:                          # noqa: BLE001
            print(f"!! could not read Raf's board ({type(e).__name__}: {e}) — "
                  "every % left blank")

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
    widths(ws, [24, 12, 14, 30, 16, 9, 18, 16, 26, 14, 28])
    last = ws.max_row
    A, J, K = (f"Edited!${c}$2:${c}${last}" for c in "AJK")

    # --- Reps Name & Commission payout ------------------------------------
    wr = wb.create_sheet(TAB_PAYOUT)
    header(wr, PAYOUT_HEADERS)
    results = {}
    for i, name in enumerate(reps + extras, 2):
        if name in extras:
            pct, kind, note, lost, lvl = None, KIND_EXTRA, NOTE_EXTRA, "", None
        else:
            pct, kind, note, lost, lvl = rule_for(name, board)
        results[name] = (pct if not lost else LOST_LEADERSHIP_PCT, kind, note, lost)
        wr.cell(i, 1, name)
        if kind == "leader":
            # F empty -> level %, anything in F (auto or typed) -> 35%.
            p = wr.cell(i, 2, f'=IF(F{i}="",{lvl},{LOST_LEADERSHIP_PCT})')
        else:
            p = wr.cell(i, 2, pct)
        p.number_format = "0%"
        wr.cell(i, 3, f"=SUMIF({A},A{i},{J})").number_format = MONEY
        wr.cell(i, 4, f'=IF(B{i}="","",(C{i}-G{i})*B{i}'
                      f'+G{i}*MAX(B{i},{SUNDAY_INTERNET_PCT}))').number_format = MONEY
        wr.cell(i, 5, note)
        wr.cell(i, 6, lost or None)
        wr.cell(i, 7, f'=SUMIFS({J},{A},A{i},{K},"*{SUNDAY_NOTE}*")').number_format = MONEY
    n = len(reps) + len(extras) + 1
    t = n + 1
    wr.cell(t, 1, "TOTAL").font = Font(bold=True)
    for col in ("C", "D", "G"):
        c = wr[f"{col}{t}"]
        c.value = f"=SUM({col}2:{col}{n})"
        c.number_format, c.font = MONEY, Font(bold=True)
    wr["I1"] = ("Yellow % can be typed over; each rep's tab follows. Type anything "
                "in Lost Leadership Pay to drop a Level 1-3 rep to 35%. Orange = "
                "no level, type a %. Purple = new start, paid next week. Grey = "
                "DD line with no rep. Pink = lost leadership pay.")
    wr["I1"].font = Font(italic=True)
    widths(wr, [28, 14, 20, 14, 30, 22, 22])

    # --- one tab per rep --------------------------------------------------
    used = {"edited", "reps name & commission payout", "raw"}
    look = "'Reps Name & Commission payout'!"
    for rep in reps:
        wt = wb.create_sheet(safe_title(rep, used))
        wt["A1"], wt["B1"] = "Rep", rep
        wt["A2"] = "Revenue Brought In"
        wt["B2"] = f"=SUMIF({A},B1,{J})"
        wt["A3"] = "Commission %"
        wt["B3"] = f'=IFERROR(INDEX({look}$B:$B,MATCH(B1,{look}$A:$A,0)),"")'
        wt["A4"] = "Payout"
        wt["B4"] = f'=IFERROR(INDEX({look}$D:$D,MATCH(B1,{look}$A:$A,0)),"")'
        for a in ("A1", "A2", "A3", "A4"):
            wt[a].font = Font(bold=True)
        wt["B1"].font = Font(bold=True, size=13)
        wt["B2"].number_format = MONEY
        wt["B3"].number_format = "0%"
        wt["B4"].number_format = MONEY
        wt["B4"].font = Font(bold=True, size=13, color="006100")
        wt.append([])
        wt.append([c for c, _ in EDITED_COLS[1:]])
        for d in edited:
            if d["Rep Full Name"] == rep:
                wt.append([d[c] for c, _ in EDITED_COLS[1:]])
                wt.cell(wt.max_row, 9).number_format = MONEY
        widths(wt, [20, 30, 30, 16, 9, 18, 16, 26, 14, 28])

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
    return results


def cli(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dd-file", help="already-downloaded ORG DD Detail crosstab")
    ap.add_argument("--restyle", help="existing workbook to rename + restyle only")
    ap.add_argument("--out", required=True, help="where to save the .xlsx")
    ap.add_argument("--no-board", action="store_true",
                    help="don't read Raf's board (every %% left blank)")
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
    main(dd, a.out, use_board=not a.no_board, carry_from=a.carry_from)


if __name__ == "__main__":
    cli()
