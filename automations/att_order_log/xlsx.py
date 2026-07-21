"""The daily ATT B2B Order Log workbook: an overall tab + one tab per rep,
grouped by paycheck (week-ending) weeks — the AT&T counterpart of
box_order_log.xlsx (Megan 2026-07-20: "per rep breakdown with the paycheck
weeks like we did for Box").

Same house look as the BOX + Fiber logs (Georgia 12pt, dark header band, blue
week banners, status-coloured rows), so Carlos's two logs read identically.
Built off the un-pivoted AT&T sales lines (att_order_log.clean), the same data
the sheet + the Slack thread use — one source, no second pull.

Tabs, in order:
  1. "All Reps"      — every sale, newest week first, one banner per week ending.
  2. "Posted by Week"— reps down, week-endings across, POSTED sales per week
                       (Posted is AT&T's countable status, the pay driver — the
                       structural twin of BOX's "Accepted by Supplier"). Flagged
                       for Carlos to confirm what actually drives AT&T pay.
  3. one tab per rep — that rep's sales, same week grouping.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import colors
from .sheet import DISPLAY_HEADERS, DISPLAY_LABELS, _parse_date

FONT_NAME = "Georgia"
FONT_SIZE = 12
HEADER_BG = "434343"
WEEK_BG = "2563EB"
POSTED = "posted"                       # the pay-driver status (lowercased)

CENTER = Alignment(horizontal="center", vertical="center", wrap_text=False)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=False)

# Log columns: Rep first on the summary; the per-rep tabs drop it.
_REP_LABEL = DISPLAY_LABELS[0]
_LOG_LABELS = DISPLAY_LABELS            # 17 friendly names
_LABEL_TO_HEADER = dict(zip(DISPLAY_LABELS, DISPLAY_HEADERS))

_BAD_TITLE = re.compile(r"[:\\/?*\[\]]")


def week_ending(d: dt.date) -> dt.date:
    """Saturday of the Sun-Sat week containing d — same convention as
    box_order_log.clean.week_ending, so the two logs' weeks line up."""
    sunday = d - dt.timedelta(days=(d.weekday() + 1) % 7)
    return sunday + dt.timedelta(days=6)


def _font(color: str = "000000", *, bold: bool = False,
          italic: bool = False) -> Font:
    return Font(name=FONT_NAME, size=FONT_SIZE, bold=bold, italic=italic,
                color=color)


def _border() -> Border:
    side = Side(style="thin", color="D9D9D9")
    return Border(left=side, right=side, top=side, bottom=side)


def _safe_title(name: str, used: set) -> str:
    title = (_BAD_TITLE.sub("-", name).strip() or "Rep")[:31]
    base, n = title, 2
    while title.lower() in used:
        sfx = " ({})".format(n)
        title = base[:31 - len(sfx)] + sfx
        n += 1
    used.add(title.lower())
    return title


def _line_week(ln: dict) -> Optional[dt.date]:
    d = _parse_date(ln.get("sp.Order Date (copy)"))
    return week_ending(d) if d else None


def by_week(lines: Sequence[dict]) -> "collections.OrderedDict":
    """Lines grouped by week ending, NEWEST first."""
    out: Dict[Optional[dt.date], list] = collections.defaultdict(list)
    for ln in lines:
        out[_line_week(ln)].append(ln)
    ordered = collections.OrderedDict()
    for wk in sorted((w for w in out if w), reverse=True):
        ordered[wk] = out[wk]
    if None in out:                     # undated last
        ordered[None] = out[None]
    return ordered


def _cell(ln: dict, label: str):
    raw = str(ln.get(_LABEL_TO_HEADER[label], "") or "").strip()
    if label in ("Order Date", "Status Date", "Install Date"):
        return _parse_date(raw) or raw
    return raw


def _write_header(sh, row: int, labels: Sequence[str]) -> None:
    b = _border()
    for c, label in enumerate(labels, start=1):
        cell = sh.cell(row=row, column=c, value=label)
        cell.font = _font("FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor=HEADER_BG)
        cell.alignment, cell.border = CENTER, b


def _write_row(sh, row: int, ln: dict, labels: Sequence[str]) -> None:
    b = _border()
    hexfill = colors.fill_for(ln.get("DTR Status (enriched)", ""))
    fill = PatternFill("solid", fgColor=hexfill.lstrip("#")) if hexfill else None
    for c, label in enumerate(labels, start=1):
        cell = sh.cell(row=row, column=c, value=_cell(ln, label))
        cell.font = _font()
        cell.alignment = LEFT if label in ("Rep", "Customer Name",
                                           "Package") else CENTER
        cell.border = b
        if fill is not None:
            cell.fill = fill
        if label in ("Order Date", "Status Date", "Install Date"):
            cell.number_format = "mm/dd/yyyy"


def _banner(sh, row: int, text: str, span: int) -> None:
    sh.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = sh.cell(row=row, column=1, value=text)
    cell.font = _font("FFFFFF", bold=True)
    cell.fill = PatternFill("solid", fgColor=WEEK_BG)
    cell.alignment = LEFT


def _write_log(sh, lines, labels, *, freeze=True) -> None:
    row = 1
    for wk, group in by_week(lines).items():
        label = wk.strftime("%m/%d/%Y") if wk else "No order date"
        _banner(sh, row, "Week Ending {}  •  {} order{}".format(
            label, len(group), "" if len(group) == 1 else "s"), len(labels))
        row += 1
        _write_header(sh, row, labels)
        row += 1
        for ln in group:
            _write_row(sh, row, ln, labels)
            row += 1
        row += 2
    _autosize(sh, labels)
    if freeze:
        sh.freeze_panes = "A3"


def _autosize(sh, labels: Sequence[str]) -> None:
    for c, label in enumerate(labels, start=1):
        width = max(len(str(label)) + 2, 12)
        for r in range(1, min(sh.max_row, 400) + 1):
            v = sh.cell(row=r, column=c).value
            if v is not None:
                width = max(width, min(len(str(v)) + 2, 40))
        sh.column_dimensions[get_column_letter(c)].width = width * 1.05


def build(lines: Sequence[dict], out_path: Path, *,
          today: Optional[dt.date] = None) -> Path:
    """Write the workbook: All Reps summary, Posted-by-Week, then a tab per rep."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    today = today or dt.date.today()
    wb = Workbook()
    used: set = set()

    # ---- 1. All Reps ----------------------------------------------------
    sh = wb.active
    sh.title = _safe_title("All Reps", used)
    _write_log(sh, lines, _LOG_LABELS)

    # ---- 2. Posted by Week (the pay-driver matrix) ----------------------
    _write_posted_matrix(wb, lines, used)

    # ---- 3. one tab per rep --------------------------------------------
    by_rep: Dict[str, list] = collections.defaultdict(list)
    for ln in lines:
        rep = str(ln.get("Rep", "") or "").strip()
        if rep:
            by_rep[rep].append(ln)
    # Per-rep tab drops the Rep column (redundant).
    rep_labels = [l for l in _LOG_LABELS if l != _REP_LABEL]
    for rep in sorted(by_rep):
        rsh = wb.create_sheet(_safe_title(rep, used))
        _write_log(rsh, by_rep[rep], rep_labels)

    wb.save(out_path)
    return out_path


def _write_posted_matrix(wb, lines, used) -> None:
    """Reps down, week-endings across, POSTED orders per week — AT&T's twin of
    BOX's Accepted-by-Supplier payout. Posted is the countable status; whether
    it is the true pay driver is a Carlos question, flagged in the subtitle."""
    weeks = collections.Counter()
    posted = collections.defaultdict(int)     # (rep, week) -> count
    reps = set()
    for ln in lines:
        rep = str(ln.get("Rep", "") or "").strip()
        wk = _line_week(ln)
        if not rep or not wk:
            continue
        reps.add(rep)
        if str(ln.get("DTR Status (enriched)", "")).strip().lower() == POSTED:
            posted[(rep, wk)] += 1
            weeks[wk] += 1
    if not reps:
        return
    weeks_desc = sorted(weeks, reverse=True)
    psh = wb.create_sheet(_safe_title("Posted by Week", used))
    psh.cell(row=1, column=1,
             value="Posted orders by week ending").font = _font(bold=True)
    psh.cell(row=2, column=1,
             value=("Each column is the week's POSTED orders (AT&T's countable "
                    "status). Confirm with Carlos whether Posted is what pay is "
                    "based on, or another status.")).font = _font(italic=True)
    headers = ["Rep"] + [w.strftime("%m/%d") for w in weeks_desc] + ["Total"]
    _write_header(psh, 4, headers)
    r = 5
    for rep in sorted(reps,
                      key=lambda x: -sum(posted.get((x, w), 0)
                                         for w in weeks_desc)):
        vals = [rep]
        tot = 0
        for w in weeks_desc:
            n = posted.get((rep, w), 0)
            tot += n
            vals.append(n)
        vals.append(tot)
        for c, v in enumerate(vals, start=1):
            cell = psh.cell(row=r, column=c, value=v)
            cell.font = _font(bold=(c == len(headers)))
            cell.alignment = LEFT if c == 1 else CENTER
            cell.border = _border()
        r += 1
    psh.freeze_panes = "B5"
    _autosize(psh, headers)
