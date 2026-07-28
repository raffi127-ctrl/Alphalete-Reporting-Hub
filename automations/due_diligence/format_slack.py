"""Render a RepDD into a Slack reply (mrkdwn)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from .pull import RepDD, TableDD, PERIODS


def _we(d: dt.date) -> str:
    """Week-ending label the way the template writes it: '6.14', '5.03'."""
    return f"{d.month}.{d.day:02d}"


def _num(v: Optional[float]) -> str:
    if v is None:
        return "—"
    # 11.0 -> "11", 11.25 -> "11.25", 10.5 -> "10.5"
    return f"{v:g}"


def _cell(v) -> str:
    return "—" if v is None else str(v)


def _table_block(title: str, t: TableDD, weeks) -> str:
    weekly = " · ".join(
        f"{_we(s)} {('—' if t.weekly.get(s) is None else t.weekly.get(s))}"
        for s in weeks
    )
    churn = " · ".join(f"{p} {t.churn.get(p, '—')}" for p in PERIODS)
    cancel = f"0-30 {t.cancel_0_30 or '—'} · 30-60 {t.cancel_30_60 or '—'}"
    lines = [
        f"*{title}*",
        f"• 8-wk avg *{_num(t.avg_8wk)}*   |   4-wk avg *{_num(t.avg_recent)}*",
        f"• Weekly (newest→oldest): {weekly}",
        f"• Cancel rate: {cancel}",
        f"• Churn: {churn}",
    ]
    return "\n".join(lines)


def render(dd: RepDD) -> str:
    who = dd.matched_rep or dd.rep
    header = f"*Due Diligence — {who}*"
    icd_label = dd.icd or dd.owner
    if icd_label:
        header += f"  _(ICD: {icd_label})_"
    parts = [header, ""]

    if not dd.found:
        parts.append(
            f":warning: Couldn't find *{dd.rep}* in the last "
            f"{len(dd.weeks)} weeks of sales. Check the spelling, or add an "
            f"alias if they go by another name."
        )
        if dd.gaps:
            parts.append("")
            parts.append("_" + "; ".join(dd.gaps[:3]) + "_")
        return "\n".join(parts)

    parts.append(_table_block("New Internet", dd.new_int, dd.weeks))
    parts.append("")
    parts.append(_table_block("Wireless", dd.wireless, dd.weeks))
    parts.append("")
    parts.append(f"• Start date / first day of sales: {dd.start_date or '_(fill manually)_'}")

    if dd.gaps:
        parts.append("")
        parts.append(":information_source: " + " · ".join(dd.gaps))
    return "\n".join(parts)
