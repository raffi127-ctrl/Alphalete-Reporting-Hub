"""The daily BOX Order Log workbook: one summary tab + one tab per rep.

The Fiber counterpart of this is `order_log._append_rep_breakdown_tabs`, and
this follows its conventions deliberately — Georgia 12pt, a dark header band,
colored week banners, one tab per rep (not per rep-week) so a rep opens their
single tab and sees everything.

This is the DAILY artifact and is separate from the rolling six-week sheet
(see sheet.py). It covers the full pull, not just the six-week window.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import clean

# Megan's house look for report xlsx — matches the Fiber order log exactly.
FONT_NAME = "Georgia"
FONT_SIZE = 12
WIDTH_FACTOR = 1.3
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=False)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=False)

HEADER_BG = "434343"
WEEK_BG = "2563EB"

COLUMNS = (
    "Sale Date", "Business Name", "Contract ID", "Status", "Contr. Sub-status",
    "Secondary Status", "Accepted Date", "BF Tier", "Term", "Complete Sales",
    "Sales (All) kWH+Therms",
)
# The summary tab names the rep; the per-rep tabs don't need to repeat it.
SUMMARY_COLUMNS = ("Rep Name",) + COLUMNS

# Excel forbids : \ / ? * [ ] in sheet titles, and caps them at 31 chars.
_BAD_TITLE = re.compile(r"[:\\/?*\[\]]")


def _font(color: str = "000000", *, bold: bool = False,
          italic: bool = False) -> Font:
    return Font(name=FONT_NAME, size=FONT_SIZE, bold=bold, italic=italic,
                color=color)


def _border() -> Border:
    side = Side(style="thin", color="D9D9D9")
    return Border(left=side, right=side, top=side, bottom=side)


def _safe_title(name: str, used: set) -> str:
    title = _BAD_TITLE.sub("-", name).strip() or "Rep"
    title = title[:31]
    base, n = title, 2
    while title.lower() in used:
        suffix = " ({})".format(n)
        title = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(title.lower())
    return title


def _fmt(value) -> str:
    return "" if value is None else str(value).strip()


def _cell_value(s, column: str):
    """One cell for a sale, by column label."""
    if column == "Rep Name":
        return _fmt(s.fields.get("Rep Name"))
    if column == "Sale Date":
        return s.sale_date or ""
    if column == "Accepted Date":
        return clean._parse_date(_fmt(s.fields.get("Accepted Date"))) or ""
    if column == "Status":
        return s.status
    if column == "Contr. Sub-status":
        return s.sub_status
    if column == "Secondary Status":
        return s.secondary
    if column == "Sales (All) kWH+Therms":
        raw = _fmt(s.fields.get(column)).replace(",", "")
        try:
            return int(raw)
        except ValueError:
            return raw
    return _fmt(s.fields.get(column))


def _write_header(sh, row: int, columns: Sequence[str]) -> None:
    border = _border()
    for c, label in enumerate(columns, start=1):
        cell = sh.cell(row=row, column=c, value=label)
        cell.font = _font("FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor=HEADER_BG)
        cell.alignment, cell.border = CENTER, border


def _write_row(sh, row: int, s, columns: Sequence[str]) -> None:
    border = _border()
    # History-aware: a Verification sale reads as "waiting" if it was already
    # submitted and "ours to chase" if it wasn't. Same rule as the sheet.
    fill_hex = clean.color_for(s.status, s.history)
    fill = PatternFill("solid", fgColor=fill_hex) if fill_hex else None
    for c, column in enumerate(columns, start=1):
        cell = sh.cell(row=row, column=c, value=_cell_value(s, column))
        cell.font = _font()
        cell.alignment = LEFT if column in ("Business Name", "Rep Name") else CENTER
        cell.border = border
        if fill is not None:
            cell.fill = fill
        if column in ("Sale Date", "Accepted Date"):
            cell.number_format = "mm/dd/yyyy"
        elif column == "Sales (All) kWH+Therms":
            cell.number_format = "#,##0"


def _banner(sh, row: int, text: str, ncol: int) -> None:
    cell = sh.cell(row=row, column=1, value=text)
    cell.font = _font("FFFFFF", bold=True)
    cell.fill = PatternFill("solid", fgColor=WEEK_BG)
    cell.alignment, cell.border = CENTER, _border()
    sh.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncol)


def _autosize(sh, columns: Sequence[str], rows: Sequence) -> None:
    for c, column in enumerate(columns, start=1):
        widest = len(column)
        for s in rows:
            widest = max(widest, len(str(_cell_value(s, column))))
        sh.column_dimensions[get_column_letter(c)].width = min(
            46, max(10, widest * WIDTH_FACTOR))


def _legend(sh, row: int) -> int:
    """A short color key, so a rep opening their tab knows what red means."""
    sh.cell(row=row, column=1, value="What the colors mean").font = _font(bold=True)
    row += 1
    for status in clean.STATUS_PRIORITY:
        meaning = clean.STATUS_MEANING.get(status)
        if not meaning:
            continue
        swatch = sh.cell(row=row, column=1, value=status)
        hex_v = clean.STATUS_COLORS.get(status)
        if hex_v:
            swatch.fill = PatternFill("solid", fgColor=hex_v)
        swatch.font, swatch.alignment, swatch.border = _font(), CENTER, _border()
        note = sh.cell(row=row, column=2, value=meaning)
        note.font, note.alignment = _font(italic=True), LEFT
        row += 1
    return row


def build(sales: Sequence, out_path: Path, *,
          today: Optional[dt.date] = None) -> Path:
    """Write the workbook: 'All Reps' summary, then one tab per rep."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    today = today or dt.date.today()

    wb = Workbook()
    used: set = set()

    # ---- summary tab ----------------------------------------------------
    sh = wb.active
    sh.title = _safe_title("All Reps", used)
    ordered = sorted(
        sales,
        key=lambda s: (-(s.week_ending.toordinal() if s.week_ending else 0),
                       _fmt(s.fields.get("Rep Name")),
                       clean._priority(s.level)))
    row = 1
    for week, group in clean.by_week(ordered).items():
        label = week.strftime("%m/%d/%Y") if week else "No sale date"
        _banner(sh, row, "Week Ending {}  •  {} sale{}".format(
            label, len(group), "" if len(group) == 1 else "s"),
            len(SUMMARY_COLUMNS))
        row += 1
        _write_header(sh, row, SUMMARY_COLUMNS)
        row += 1
        for s in group:
            _write_row(sh, row, s, SUMMARY_COLUMNS)
            row += 1
        row += 2
    _autosize(sh, SUMMARY_COLUMNS, ordered)
    sh.freeze_panes = "A3"

    # ---- payout by week --------------------------------------------------
    # Reps down, weeks across, PAID sales in the cells. "Paid" is Accepted by
    # Supplier counted in the week it was accepted, because that is the week
    # it pays (Carlos, 2026-07-18).
    from . import payout as _payout
    reps_ranked, weeks_desc, posted, pending = _payout.by_week_matrix(ordered)
    if reps_ranked:
        psh = wb.create_sheet(_safe_title("Payout by Week", used))
        headers = (["Rep"] + [w.strftime("%m/%d") for w in weeks_desc]
                   + ["Paid Total", "Pending"])
        psh.cell(row=1, column=1, value="Paid sales by week ending").font = _font(bold=True)
        psh.cell(row=2, column=1,
                 value="A sale counts in the week the supplier ACCEPTED it "
                       "— which is NOT the week it was sold, so these columns "
                       "will not match the log's week totals. Pending = still "
                       "live, not yet accepted.").font = _font(italic=True)
        _write_header(psh, 4, headers)
        r = 5
        for rep in reps_ranked:
            row_vals = [rep]
            paid_total = 0
            for w in weeks_desc:
                n = posted.get((rep, w), 0)
                paid_total += n
                row_vals.append(n)
            row_vals += [paid_total, pending.get(rep, 0)]
            for c, v in enumerate(row_vals, start=1):
                cell = psh.cell(row=r, column=c, value=v)
                cell.font = _font(bold=(c >= len(headers) - 1))
                cell.alignment = LEFT if c == 1 else CENTER
                cell.border = _border()
            r += 1
        # TOTAL strip
        for c in range(1, len(headers) + 1):
            if c == 1:
                v = "TOTAL"
            else:
                col = get_column_letter(c)
                v = "=SUM({c}5:{c}{last})".format(c=col, last=r - 1)
            cell = psh.cell(row=r, column=c, value=v)
            cell.font = _font(bold=True)
            cell.alignment = LEFT if c == 1 else CENTER
            cell.border = _border()
            cell.fill = PatternFill("solid", fgColor="EDEDED")
        psh.column_dimensions["A"].width = 30
        for c in range(2, len(headers) + 1):
            psh.column_dimensions[get_column_letter(c)].width = 12
        psh.freeze_panes = "B5"

    # ---- one tab per rep -------------------------------------------------
    by_rep: Dict[str, List] = {}
    for s in ordered:
        by_rep.setdefault(_fmt(s.fields.get("Rep Name")) or "(no rep)", []).append(s)

    for rep in sorted(by_rep):
        rep_sales = by_rep[rep]
        rsh = wb.create_sheet(_safe_title(rep, used))
        r = 1
        rsh.cell(row=r, column=1, value=rep).font = _font(bold=True)
        r += 1
        rsh.cell(row=r, column=1,
                 value="{} sale{} • BOX Order Log • {}".format(
                     len(rep_sales), "" if len(rep_sales) == 1 else "s",
                     today.strftime("%m/%d/%Y"))).font = _font(italic=True)
        r += 2
        for week, group in clean.by_week(rep_sales).items():
            label = week.strftime("%m/%d/%Y") if week else "No sale date"
            _banner(rsh, r, "Week Ending {}  •  {} sale{}".format(
                label, len(group), "" if len(group) == 1 else "s"), len(COLUMNS))
            r += 1
            _write_header(rsh, r, COLUMNS)
            r += 1
            for s in group:
                _write_row(rsh, r, s, COLUMNS)
                r += 1
            r += 2
        _legend(rsh, r)
        _autosize(rsh, COLUMNS, rep_sales)

    wb.save(out_path)
    return out_path
