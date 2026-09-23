"""The office P&L, per ICD, off the Focus Report tab.

Megan 2026-09-23: "we should also have a PNL section where finances are broken
down", "pnl would be per ICD like the focus reports breakdown", "it's on the
focus reports". It is — a block near the bottom of each tab, one column per
week ending Sunday like everything else there:

    Direct Deposit · Total Funds Available · Owners Payroll · Total Expenses
    Indeed · Arcadia · Owners Withdrawal · Profit/Loss · Operating %

THREE THINGS MAKE THIS MORE THAN A ROW FILTER.

1. NOT EVERY OFFICE HAS ONE ("we don't have access for them on everyone").
   An office with no P&L must read as ABSENT, never as zeros — a board that
   prints $0.00 profit for an office nobody has the books for is stating
   something false, and somebody will act on it ([[feedback_never_post_blank]],
   [[feedback_dont_explain_away_a_zero]]).

2. THE VOCABULARY DIFFERS BY TAB. Carlos, Cyrus and Aya carry the nine rows
   above. Raf's tab has none of them and instead splits by program — Fiber
   PNL, B2B PNL, JE PNL, each with its own Profit Margin %, Payroll % and
   Total Loss. Both are the office's P&L, so rows are found by MEANING rather
   than from one fixed list, and a new line appears without an edit here.

3. A CELL CAN BE A BROKEN FORMULA. Raf's whole B2B and JE block reads #REF!
   today. Those are not values and never go on a board: they are dropped, and
   an office whose every financial row is an error reads as having no P&L
   rather than as having a page of #REF!.
"""
from __future__ import annotations

import re

# Sheets' own error values. A formula that broke is not a number, and showing
# it to an owner is worse than showing nothing.
ERRORS = {"#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#ERROR!",
          "#NULL!", "#NUM!"}

# The block as it is laid out on the tab, in that order — money in, then what
# it went on, then what was left. Anything matching EXTRA below is appended
# after these in the tab's own order.
CORE = ["Direct Deposit", "Total Funds Available", "Owners Payroll",
        "Total Expenses", "Indeed", "Arcadia", "Owners Withdrawal",
        "Profit/Loss", "Profit / Loss", "Operating %"]

# The per-program rows Raf's tab uses instead, plus anything else financial a
# tab grows later. Deliberately broad: a row that turns out not to be money is
# dropped by the has-a-value check anyway, and missing a real one is worse.
EXTRA = re.compile(
    r"\bpnl\b|p\s*&\s*l|profit|loss|payroll|expense|withdraw|operating\s*%|"
    r"funds available|direct deposit|revenue|margin|\bcost\b|\bspend\b",
    re.IGNORECASE)

# The three an owner reads first, if the tab has them.
HEADLINE = ["Profit/Loss", "Profit / Loss", "Operating %", "Total Expenses"]


def usable(value) -> bool:
    """Is this cell a number somebody could act on?"""
    v = str(value or "").strip()
    return bool(v) and v.upper() not in ERRORS


def is_financial(name: str) -> bool:
    n = (name or "").strip()
    return n in CORE or bool(EXTRA.search(n))


def rows_for(data: dict, weeks: list) -> list:
    """[{'Metric', 'Goal', <week>: value}] — the P&L rows with something in
    them, CORE first in its own order, then everything else in the tab's.

    A row whose every cell in the window is blank or an error is left out, so
    the section shows what an office actually has rather than the shape of the
    template."""
    metrics = (data or {}).get("metrics") or {}
    ordered = [n for n in CORE if n in metrics]
    ordered += [n for n in metrics
                if n not in ordered and is_financial(n)]
    out = []
    for name in ordered:
        m = metrics[name]
        by = m.get("by_week") or {}
        vals = {w: str(by.get(w, "")).strip() for w in weeks}
        if not any(usable(v) for v in vals.values()):
            continue
        row = {"Metric": name, "Goal": m.get("goal", "") or ""}
        for w in weeks:
            # An error cell becomes blank, not '#REF!': the row may still have
            # good weeks either side of it and is worth showing for those.
            row[f"{w:%m/%d}"] = vals[w] if usable(vals[w]) else ""
        out.append(row)
    return out


def headline(data: dict, week) -> list:
    """[(label, value)] for the two or three figures worth a big number."""
    metrics = (data or {}).get("metrics") or {}
    seen, out = set(), []
    for name in HEADLINE:
        m = metrics.get(name)
        if not m:
            continue
        label = name.replace(" / ", "/")
        if label in seen:
            continue
        v = str((m.get("by_week") or {}).get(week, "")).strip()
        if usable(v):
            seen.add(label)
            out.append((label, v))
    return out


def has_pnl(data: dict, weeks: list) -> bool:
    return bool(rows_for(data, weeks))
