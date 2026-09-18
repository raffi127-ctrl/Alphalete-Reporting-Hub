"""Read the per-owner ARS REPORT workbooks in Camila's Drive folder.

Folder: https://drive.google.com/drive/u/1/folders/1wIZv_HzdSqx2PpoqOJut_av7fqymPMSj
Six workbooks, split alphabetically by the owner's FIRST name, except Colten's
whole org which sits together in 'SOUTH SHORE | PROFITS - Report (New)'. One TAB
per owner inside each workbook.

The file ids are pinned below rather than looked up: the Hub's Google token has
the `spreadsheets` scope only, so it can open a workbook by key but cannot list
a Drive folder. Re-run `--refresh-index` after someone adds a workbook and paste
the new id here.

Inside an owner's tab there are three side-by-side blocks, each banner-labelled
on row 1: 'QUALIFIED RETENTION', 'ANSWERED / BOOKED RETENTION' and a third we do
not read. Their starting columns differ from tab to tab, so every block is found
by its banner text, never by a column index.

A block is a STACK of weekly boxes going down, 6 rows apart:
    row w+0   <week label>   Monday .. Friday   (day name every 5 columns)
    row w+1   'Interviewer'  Q | Di | De | QR | DR     (per day, 5 columns)
    row w+2   <interviewer>  the numbers
    row w+3   <interviewer>  a second interviewer, or zeros
The ANSWERED / BOOKED block has the same shape with Q | B | NC | BR | NCR.

THE TWO WEEK LABELS ARE SEVEN DAYS APART, on purpose, and mixing them up shifts
the whole report by a week:
    'Interviewers Retention (Interviewer)' labels a week by the Sunday that
    STARTS it            -> 9/13 means Mon 9/14 .. Fri 9/18
    these ARS REPORT files label the SAME week by the Sunday that ENDS it
                         -> 9/20 means Mon 9/14 .. Fri 9/18
The tabs' own formulas settle it: the Wednesday column of the 9/20 box reads
`=COUNTIFS(..., $B:$B, ($BZ$51-4), ...)`, i.e. the box anchor minus four days.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill

# Workbook title -> file id, as the Drive folder holds them.
ARS_WORKBOOKS: Dict[str, str] = {
    "ARS REPORT (1) - A to C": "1BltgRTW_tm-Y0AlUIVxqHHqh3cpSUwWc5F1Ako01gVw",
    "ARS REPORT (2) - D to I": "1U5GZyzuXmzeNRKDL8V_lvCpzEtpjxuy4LLCDT3gDKcQ",
    "ARS REPORT (3) - J to L": "1sq_0VY-y1kzcQ8SAOmqs4VLE_2bPSJpCLTFufcUtQW4",
    "ARS REPORT (4) - M to Q": "12zye9tduziss1w-EdZKkPJ2DE-dg-xB0aqvC2H3cLao",
    "ARS REPORT (5) - R to Z": "16UruNs3bHGJ_pBvmD6T9KEqMAtDNNyuKArA_es6f0LE",
    "SOUTH SHORE | PROFITS - Report (New)": "13a1ACbG_F_r1g5D9Zny7fSixuolobwyEL1YQXu1WgJk",
}

QUALIFIED_BANNER = "QUALIFIED RETENTION"
ANSWERED_BANNER = "ANSWERED / BOOKED RETENTION"
INTERVIEWER_LABEL = "Interviewer"
TEMPLATE_TAB = "NEW TEMPLATE"          # every workbook carries one; not an owner

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY_STRIDE = 5                          # columns per day inside a block
BOX_STRIDE = 6                          # rows from one weekly box to the next
DATA_ROWS = 2                           # interviewer rows under a box header

# Owner name (as the ARS Management retention tab writes it) -> tab title in the
# ARS REPORT workbook, for the pairs the fuzzy matcher cannot reach on its own.
# Keep this SHORT: it is a list of genuinely different spellings, not a dumping
# ground for anything that failed to match once.
TAB_ALIASES = Path(__file__).resolve().parent / "owner-tab-aliases.json"
# Cached {normalised tab title: [workbook, tab]} so a run does not have to open
# all six workbooks just to find out where an owner lives.
TAB_INDEX = Path(__file__).resolve().parent / "owner-tab-index.json"

_INDEX_CACHE: Optional[Dict[str, Tuple[str, str]]] = None


# --------------------------------------------------------------- name matching
def norm_name(s: str) -> str:
    """'José  Velazques' -> 'jose velazques'. Accents and punctuation go; the
    word order does not, because that is what distinguishes two people."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s.lower())).strip()


def _key(s: str) -> str:
    return norm_name(s).replace(" ", "")


def _tokens(s: str) -> List[str]:
    return [t for t in norm_name(s).split() if t]


def load_aliases() -> Dict[str, str]:
    if not TAB_ALIASES.exists():
        return {}
    data = json.loads(TAB_ALIASES.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}   # '_note' is documentation


def save_alias(owner: str, tab: str) -> None:
    # Read the file RAW, not through load_aliases(): that one strips the
    # underscore keys, so writing its result back deleted the '_note' that tells
    # the next person what belongs in here (happened 2026-09-17).
    data = (json.loads(TAB_ALIASES.read_text(encoding="utf-8"))
            if TAB_ALIASES.exists() else {})
    data[owner] = tab
    TAB_ALIASES.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")


def build_index(logfn=print) -> Dict[str, Tuple[str, str]]:
    """{normalised tab title: (workbook title, tab title)} across all six files."""
    index: Dict[str, Tuple[str, str]] = {}
    for title, key in ARS_WORKBOOKS.items():
        sh = fill.open_by_key(key)
        tabs = sh.worksheets()
        for ws in tabs:
            name = ws.title.strip()
            if TEMPLATE_TAB.lower() in name.lower():
                continue
            index.setdefault(_key(name), (title, ws.title))
        logfn(f"    {title}: {len(tabs) - 1} owner tabs")
    return index


def save_index(index: Dict[str, Tuple[str, str]]) -> None:
    TAB_INDEX.write_text(
        json.dumps({k: list(v) for k, v in sorted(index.items())},
                   indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _index(logfn=print, refresh: bool = False) -> Dict[str, Tuple[str, str]]:
    """The owner-tab index, read from the committed cache.

    Opening all six workbooks costs about a minute, and this report runs twice a
    day, so the index is cached on disk. It only changes when someone adds or
    renames an owner tab -- refresh it with `--refresh-index`, and the run says
    so out loud when an owner is missing, which is the signal to refresh."""
    global _INDEX_CACHE
    if refresh:
        _INDEX_CACHE = build_index(logfn=logfn)
        save_index(_INDEX_CACHE)
        return _INDEX_CACHE
    if _INDEX_CACHE is None:
        if TAB_INDEX.exists():
            raw = json.loads(TAB_INDEX.read_text(encoding="utf-8"))
            _INDEX_CACHE = {k: tuple(v) for k, v in raw.items()}
        else:
            _INDEX_CACHE = build_index(logfn=logfn)
            save_index(_INDEX_CACHE)
    return _INDEX_CACHE


def find_tab(owner: str, index: Dict[str, Tuple[str, str]],
             aliases: Optional[Dict[str, str]] = None) -> Optional[Tuple[str, str]]:
    """Locate an owner's tab. Exact spelling first, then the alias file, then a
    deliberately narrow fuzzy pass -- an owner matched to the WRONG tab would
    put another office's numbers under their name, so 'no match' is the safer
    answer and the run reports it."""
    aliases = load_aliases() if aliases is None else aliases
    # The alias file wins over an exact hit, on purpose: 'Drew Tepper' names a
    # real tab that stopped being filled, and the live one is ' Drew Tepper New'.
    # An alias is somebody's explicit decision, so it outranks a name collision.
    alias = aliases.get(owner) or aliases.get(norm_name(owner))
    if alias:
        hit = index.get(_key(alias))
        if hit:
            return hit
    hit = index.get(_key(owner))
    if hit:
        return hit
    want = _tokens(owner)
    if not want:
        return None
    # Every word of one name appears in the other, e.g.
    # 'Juan Botero Berrio' <-> 'Juan Botero', 'Jamis Garay' <-> 'Jamis Garay new'.
    candidates = []
    for k, (wb, tab) in index.items():
        have = _tokens(tab)
        if not have:
            continue
        if have[0] != want[0]:
            continue                    # first names must agree; surnames drift
        if set(want).issubset(have) or set(have).issubset(want):
            candidates.append((wb, tab))
    if len(candidates) == 1:
        return candidates[0]
    return None


# ------------------------------------------------------------- box geometry
@dataclass
class DayCells:
    """One day's cells inside one weekly box, for one interviewer, keyed by the
    sub-header label ('Q', 'Di', 'De', 'QR', 'DR' / 'Q', 'A', 'B', 'NC', ...).

    Keyed, not positional, because the two blocks do NOT have the same number of
    columns per day and it varies by workbook: SOUTH SHORE's ANSWERED block is
    Q | B | NC | BR | NCR (five) while ARS REPORT (1)-(5) is
    Q | A | B | NC | AR | BR | NCR (seven). Reading by position put the wrong
    number under 'Booked' -- or nothing at all."""
    interviewer: str
    cells: Dict[str, str] = field(default_factory=dict)

    def get(self, label: str) -> str:
        return self.cells.get(label.strip().lower(), "")

    def is_empty(self, counts=("q", "di", "de", "b", "nc")) -> bool:
        vals = [_as_number(v) for k, v in self.cells.items() if k in counts]
        return all(v in (None, 0) for v in vals)


def _as_number(raw: str):
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    pct = s.endswith("%")
    if pct:
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100.0 if pct else v


class Window:
    """A rectangle of cells read out of a tab, addressed by the tab's OWN
    1-indexed row/column numbers.

    These tabs are enormous (one is 3,440 x 234) and the report opens 41 of them
    twice a day, so nothing here ever calls get_all_values -- every read is a
    named range and every helper below indexes through this."""

    def __init__(self, values: List[List[str]], row0: int = 1, col0: int = 1):
        self.values, self.row0, self.col0 = values, row0, col0

    @property
    def last_row(self) -> int:
        return self.row0 + len(self.values) - 1

    @property
    def last_col(self) -> int:
        return self.col0 + (max((len(r) for r in self.values), default=0)) - 1

    def cell(self, r: int, c: int) -> str:
        i, j = r - self.row0, c - self.col0
        if i < 0 or i >= len(self.values):
            return ""
        row = self.values[i]
        return (row[j] if 0 <= j < len(row) else "") or ""


def _cell(win: "Window", r: int, c: int) -> str:
    return win.cell(r, c)


def _label_key(s: str) -> str:
    """'9/20' and '09/20/2026' and a serial-rendered date all compare equal."""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*\d{2,4})?$", s)
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    return s.lower()


def find_block_column(row1: List[str], banner: str) -> Optional[int]:
    """1-indexed column of a block's banner on row 1."""
    want = banner.upper().replace(" ", "")
    for j, cell in enumerate(row1, 1):
        if (cell or "").upper().replace(" ", "") == want:
            return j
    return None


def block_columns(row1: List[str]) -> List[int]:
    """Every banner column on row 1, left to right.

    A block's right-hand edge is the NEXT banner, which is how a read of one
    block is stopped from bleeding into its neighbour -- the blocks sit side by
    side and are not all the same width."""
    return [j for j, cell in enumerate(row1, 1) if (cell or "").strip().isupper()
            and len((cell or "").strip()) > 8]


def block_end(row1: List[str], block_col: int) -> Optional[int]:
    later = [c for c in block_columns(row1) if c > block_col]
    return min(later) if later else None


def find_week_box(values: "Window", label_col: int,
                  week_label: str) -> Optional[int]:
    """1-indexed row of the weekly box whose label cell reads `week_label`.

    Boxes are 6 rows apart but we scan for the label rather than stepping, so an
    inserted spacer row cannot shift the read."""
    want = _label_key(week_label)
    for r in range(values.row0, values.last_row + 1):
        if _label_key(_cell(values, r, label_col)) != want:
            continue
        if _cell(values, r + 1, label_col).strip().lower() == INTERVIEWER_LABEL.lower():
            return r
    return None


def week_labels(values: "Window", label_col: int) -> List[str]:
    """Every weekly box label in a block, top to bottom."""
    out = []
    for r in range(values.row0, values.last_row + 1):
        lab = _cell(values, r, label_col).strip()
        if lab and _cell(values, r + 1, label_col).strip().lower() == INTERVIEWER_LABEL.lower():
            out.append(lab)
    return out


def day_columns(values: "Window", block_col: int, box_row: int,
                day: str, end_col: Optional[int] = None) -> Dict[str, int]:
    """{sub-header label: column} for one day of one box.

    The day's span runs from its name on the box header row to the next day's
    name (or the block's end), and the labels inside it are read off row+1. That
    is what lets the same code read a five-column day and a seven-column one."""
    limit = end_col or (values.last_col + 1)
    starts = []
    for c in range(block_col + 1, limit):
        name = _cell(values, box_row, c).strip().lower()
        if name in {d.lower() for d in DAYS}:
            starts.append((c, name))
    want = day.strip().lower()
    for i, (c, name) in enumerate(starts):
        if name != want:
            continue
        stop = starts[i + 1][0] if i + 1 < len(starts) else limit
        out: Dict[str, int] = {}
        for cc in range(c, stop):
            label = _cell(values, box_row + 1, cc).strip().lower()
            if label:
                out.setdefault(label, cc)
        return out
    return {}


def data_rows(values: "Window", block_col: int, box_row: int) -> List[int]:
    """Rows of the box that name an interviewer.

    Counted, not assumed: a box can carry one interviewer, three, or an extra
    'Owner' row for the owner interviewing themselves."""
    out = []
    for r in range(box_row + 2, box_row + BOX_STRIDE + 3):
        label = _cell(values, r, block_col).strip()
        if not label:
            break
        if label.lower() == INTERVIEWER_LABEL.lower():
            break
        if _label_key(label) != label.lower():
            break                       # a date: the next box's header row
        out.append(r)
    return out


def read_day(values: "Window", block_col: int, box_row: int, day: str,
             end_col: Optional[int] = None) -> List[DayCells]:
    """The interviewer rows of one day inside one weekly box."""
    by_label = day_columns(values, block_col, box_row, day, end_col)
    if not by_label:
        return []
    return [DayCells(interviewer=_cell(values, r, block_col).strip(),
                     cells={lab: _cell(values, r, c) for lab, c in by_label.items()})
            for r in data_rows(values, block_col, box_row)]


@dataclass
class OwnerDay:
    """Everything one owner's tab has for one day."""
    owner: str
    workbook: str
    tab: str
    week_label: str
    day: str
    interviewers: List[str] = field(default_factory=list)
    qualified: Optional[float] = None       # QUALIFIED RETENTION -> Q
    disqualified: Optional[float] = None    #                        Di
    declined: Optional[float] = None        #                        De
    qualified_ret: Optional[float] = None   #                        QR
    declined_ret: Optional[float] = None    #                        DR
    ab_qualified: Optional[float] = None    # ANSWERED / BOOKED    -> Q
    booked: Optional[float] = None          #                        B
    not_contacted: Optional[float] = None   #                        NC
    booked_ret: Optional[float] = None      #                        BR
    not_contacted_ret: Optional[float] = None  #                     NCR

    @property
    def interviewer_label(self) -> str:
        return ", ".join(self.interviewers)


def a1col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# How far down a tab a weekly box can sit. One box every 6 rows since the file
# was created, so this is years of headroom and still a bounded read.
SCAN_ROWS = 2000
# Columns a block spans: the label column plus five days of five columns.
BLOCK_WIDTH = 1 + len(DAYS) * DAY_STRIDE


def _batch_get(ws, ranges: List[str]) -> List[List[List[str]]]:
    """values_batch_get on one tab, returned in the order asked."""
    quoted = [f"'{ws.title}'!{r}" for r in ranges]
    res = ws.spreadsheet.values_batch_get(quoted)
    return [vr.get("values", []) for vr in res.get("valueRanges", [])]


def read_owner_day(sh, tab: str, owner: str, workbook: str,
                   week_label: str, day: str) -> OwnerDay:
    """Pull one owner's numbers for one day out of their tab's two blocks.

    Three bounded reads, never the whole tab: row 1 to find where the blocks
    start and end, the two label columns to find the week's box, then the two
    small windows that box occupies."""
    ws = fill.worksheet_ci(sh, tab)
    out = OwnerDay(owner=owner, workbook=workbook, tab=tab,
                   week_label=week_label, day=day)

    row1 = (_batch_get(ws, ["1:1"]) or [[]])
    row1 = row1[0][0] if row1 and row1[0] else []
    q_col = find_block_column(row1, QUALIFIED_BANNER)
    a_col = find_block_column(row1, ANSWERED_BANNER)
    if q_col is None:
        raise LookupError(f"{tab!r}: no {QUALIFIED_BANNER!r} block on row 1")
    q_end = block_end(row1, q_col)
    a_end = block_end(row1, a_col) if a_col else None

    label_ranges = [f"{a1col(q_col)}1:{a1col(q_col)}{SCAN_ROWS}"]
    if a_col is not None:
        label_ranges.append(f"{a1col(a_col)}1:{a1col(a_col)}{SCAN_ROWS}")
    labels = _batch_get(ws, label_ranges)

    q_box = find_week_box(Window(labels[0], row0=1, col0=q_col), q_col, week_label)
    if q_box is None:
        have = ", ".join(week_labels(Window(labels[0], row0=1, col0=q_col), q_col)[-6:]) or "none"
        raise LookupError(f"{tab!r}: no {week_label!r} box; last boxes: {have}")
    a_box = None
    if a_col is not None and len(labels) > 1:
        a_box = find_week_box(Window(labels[1], row0=1, col0=a_col), a_col, week_label)

    def box_range(col, end, row):
        stop = (end - 1) if end else (col + BLOCK_WIDTH)
        return f"{a1col(col)}{row}:{a1col(stop)}{row + BOX_STRIDE + 2}"

    box_ranges = [box_range(q_col, q_end, q_box)]
    if a_box is not None:
        box_ranges.append(box_range(a_col, a_end, a_box))
    boxes = _batch_get(ws, box_ranges)

    q_win = Window(boxes[0], row0=q_box, col0=q_col)
    q_rows = read_day(q_win, q_col, q_box, day, q_end)
    live = [r for r in q_rows if not r.is_empty()]
    # The interviewer "assigned that day" is whoever actually has numbers in the
    # day's columns; a box can list two or three and only one working.
    src_rows = live or q_rows
    out.interviewers = [r.interviewer for r in src_rows if r.interviewer]

    def total(rows, label):
        vals = [_as_number(r.get(label)) for r in rows]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    out.qualified = total(src_rows, "q")
    out.disqualified = total(src_rows, "di")
    out.declined = total(src_rows, "de")
    # The percentages are the box's own, taken straight rather than recomputed,
    # so the report agrees cell-for-cell with the tab HR already reads. With two
    # live interviewers they cannot simply be added, so we re-derive that case.
    if len(src_rows) == 1:
        out.qualified_ret = _as_number(src_rows[0].get("qr"))
        out.declined_ret = _as_number(src_rows[0].get("dr"))
    else:
        shown = (out.qualified or 0) + (out.disqualified or 0) + (out.declined or 0)
        if shown:
            out.qualified_ret = (out.qualified or 0) / shown
            out.declined_ret = ((out.disqualified or 0) + (out.declined or 0)) / shown

    if a_box is not None and len(boxes) > 1:
        a_win = Window(boxes[1], row0=a_box, col0=a_col)
        a_rows = read_day(a_win, a_col, a_box, day, a_end)
        if a_rows:
            # Match the ANSWERED block's rows to the interviewers we already
            # picked: the two blocks list the same people in a DIFFERENT order.
            wanted = {norm_name(n) for n in out.interviewers}
            keep = [r for r in a_rows if norm_name(r.interviewer) in wanted] or                    [r for r in a_rows if not r.is_empty()]
            out.ab_qualified = total(keep, "q")
            out.booked = total(keep, "b")
            out.not_contacted = total(keep, "nc")
            if len(keep) == 1:
                out.booked_ret = _as_number(keep[0].get("br"))
                out.not_contacted_ret = _as_number(keep[0].get("ncr"))
            elif out.ab_qualified:
                out.booked_ret = (out.booked or 0) / out.ab_qualified
                out.not_contacted_ret = (out.not_contacted or 0) / out.ab_qualified

    # C, D and E are deliberately NOT derived here. They looked derivable --
    # Q+Di+De reproduced the '1st interviews showed up' in Eve's sample row and
    # Booked reproduced '1st showed up booked 2nd' -- but she typed that row by
    # hand as an example, so the agreement was a coincidence, not a rule
    # (Eve, 2026-09-17). Those three come from ApplicantStream; see appstream.py.
    return out


# ------------------------------------------------------------- week labelling
def ars_week_label(retention_week_label: str, year_hint: Optional[int] = None) -> str:
    """'9/13' on the ARS Management tab -> '9/20' in the ARS REPORT files.

    Both are Sundays; the retention tab names the Sunday that STARTS the week
    and the ARS REPORT files name the Sunday that ENDS it, so the label is the
    same week shifted seven days forward."""
    m = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})", (retention_week_label or "").strip())
    if not m:
        raise ValueError(f"cannot read a date out of week label {retention_week_label!r}")
    month, day = int(m.group(1)), int(m.group(2))
    year = year_hint or dt.date.today().year
    try:
        start = dt.date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"bad week label {retention_week_label!r}: {exc}") from exc
    end = start + dt.timedelta(days=7)
    return f"{end.month}/{end.day}"
