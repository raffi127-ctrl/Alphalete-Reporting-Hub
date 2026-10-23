"""Last-30-days Quantum metrics table for the Lumen Owners mail.

WHY (Eve, 2026-10-23): the mail now goes to Chan + the Quantum owners and
should read like a captainship mail, which carries activation and cancel
numbers. The Quantum tracker only has them as a ROLLING 30-day window
(workbook `AT&T Quantum Fiber Sales Tracker` -> view `RES-Quantum Fiber
30-Day ICD Metrics` -> sheet `30-Day ICD Metrics`, one row per
"ICD Owner [Office] (Nest)"). So the table is labelled "last 30 days" and
never sits under a week header (Eve 2026-09-15: a rolling number in a week
column reads as that week's).

Columns are found by header words, never by position — the view's column
order is Tableau's to change.
"""
from __future__ import annotations

import html
from typing import Dict, List, Optional

VIEW = "RES-Quantum Fiber 30-Day ICD Metrics"
SHEET = "30-Day ICD Metrics"

# (key, label in the mail, test on the folded header)
COLUMNS = (
    ("sales", "Sales", lambda h: "sales" in h),
    ("act", "Activated", lambda h: "activation" in h and "%" not in h),
    ("act_pct", "Activation %", lambda h: "activation" in h and "%" in h),
    ("cancels", "Cancels", lambda h: "cancel" in h and "%" not in h),
    ("cancel_pct", "Cancel %", lambda h: "cancel" in h and "%" in h),
)


def _fold(s) -> str:
    return " ".join(str(s or "").casefold().split())


def column_map(header: List[str]) -> Dict[str, int]:
    """{key: column index} for the COLUMNS found in `header`. Pure."""
    out: Dict[str, int] = {}
    for i, h in enumerate(header):
        f = _fold(h)
        for key, _label, test in COLUMNS:
            if key not in out and test(f):
                out[key] = i
                break
    return out


def by_owner(grid: List[List[str]]) -> Dict[str, dict]:
    """{folded owner name: {key: cell text}}. Total rows dropped. Pure."""
    from automations.lumen_owners.run import split_sales_key
    if not grid:
        return {}
    cols = column_map(grid[0])
    out: Dict[str, dict] = {}
    for r in grid[1:]:
        key = (r[0] if r else "").strip()
        if not key or "total" in _fold(key):
            continue
        owner, _office = split_sales_key(key)
        out[_fold(owner)] = {k: (r[i].strip() if i < len(r) else "")
                             for k, i in cols.items()}
    return out


def _pct(v: str) -> Optional[float]:
    try:
        x = float(str(v).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None
    return x * 100 if "%" not in str(v) and x <= 1 else x


def _show(key: str, v: str) -> str:
    if not str(v or "").strip():
        return "&ndash;"
    if key.endswith("_pct"):
        p = _pct(v)
        return "&ndash;" if p is None else "%d%%" % round(p)
    return html.escape(str(v))


def table_html(owners: List[dict], metrics: Dict[str, dict]) -> str:
    """One row per owner of the mail (same order as the owner table). An
    owner the view doesn't list gets dashes, not zeros. '' when the view gave
    nothing at all. Pure."""
    if not metrics:
        return ""
    from automations.lumen_owners.run import pretty_name
    th = ('style="padding:6px 10px;border:1px solid #ccc;background:#1f3864;'
          'color:#fff;font-size:13px;text-align:center"')
    td = 'style="padding:6px 10px;border:1px solid #ccc;font-size:13px;text-align:center"'
    tdl = 'style="padding:6px 10px;border:1px solid #ccc;font-size:13px;text-align:left"'
    head = "<tr><th %s>Owner</th>%s</tr>" % (th, "".join(
        "<th %s>%s</th>" % (th, label) for _k, label, _t in COLUMNS))
    body = []
    for o in owners:
        m = metrics.get(_fold(o["owner"]), {})
        body.append("<tr><td %s>%s</td>%s</tr>" % (
            tdl, html.escape(pretty_name(o["owner"])),
            "".join("<td %s>%s</td>" % (td, _show(k, m.get(k, "")))
                    for k, _l, _t in COLUMNS)))
    return ('<p style="font-size:15px;font-weight:bold;margin:18px 0 6px">'
            "Quantum Fiber &mdash; last 30 days</p>"
            '<table style="border-collapse:collapse">' + head + "".join(body)
            + "</table>"
            '<p style="color:#777;font-size:11px">Rolling 30 days, not a week '
            "(AT&amp;T Quantum Fiber Sales Tracker &rarr; RES-Quantum Fiber "
            "30-Day ICD Metrics &rarr; 30-Day ICD Metrics).</p>")
