"""Slack text for the Verizon office boards (preview only until Megan OKs a post).

Raf's standing rule: the parent post is a short title line, every detail lives
in the thread. Each builder returns (parent, [thread replies]).
"""
from __future__ import annotations

import datetime as dt
from typing import List, Tuple

from automations.verizon_office.parse import DAYS, Compliance, SalesVerification, CHURN_KEYS


def _pct(v) -> str:
    try:
        return f"{float(v) * 100:.0f}%"
    except (TypeError, ValueError):
        return "–"


def _md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def _short(name: str, n: int = 24) -> str:
    # Full name, trimmed: initials collide (Jose Ramos / Jose Rojas).
    return name[:n]


FLAG_WORDS = {
    "3X % Increase": "sales jumped 3x vs own average",
    "3X Campaign Avg": "3x the campaign's average sales",
    "Avg 4+ Lines / Order": "4+ lines per order",
    "2X Campaign BYOD %": "own-device (BYOD) 2x the campaign",
    "2X Campaign Shipped Never Activated > 21 Days %": "phones shipped, never activated (21+ days)",
    "0-30 Day % Churn": "0-30 day churn", "30 Day % Churn": "30 day churn",
    "60 Day % Churn": "60 day churn", "90 Day % Churn": "90 day churn",
    "Low Port Sales": "low port-ins", "Insurance >10%": "insurance over 10%",
    "Bill/Ship Addr Match": "billing/shipping address check",
    "SSN On Multiple Orders": "same SSN on multiple orders",
    "Reused Email Address": "reused email address",
}


def sales_board(sv: SalesVerification) -> Tuple[str, List[str]]:
    wk = sv.weeks[0]
    last = sv.weeks[1] if len(sv.weeks) > 1 else None
    start = wk.end - dt.timedelta(days=6)
    shown = [d for k, d in enumerate(DAYS)
             if sv.through is None or start + dt.timedelta(days=k) <= sv.through]
    thru = f" · through {sv.through:%a} {_md(sv.through)}" if sv.through else ""
    office = sv.office or "Office"

    ov = next((o for o in sv.overview if o["Week End Date"] == wk.end), {})
    lw_lines = last.lines if last else None
    vs = ""
    if lw_lines is not None:
        diff = wk.lines - lw_lines
        vs = f" ({'+' if diff >= 0 else ''}{diff} vs last week's {lw_lines})"
    parent = f":bar_chart: *Verizon Wireless Sales Board — {office}* · WE {_md(wk.end)}{thru}"

    head = f"*{wk.lines} lines* · {sum(r.sales for r in wk.reps)} sales · {len(wk.reps)} reps selling{vs}"
    if ov:
        head += (f"\nWhere this week's lines stand: {ov.get('Sub.', 0)} submitted · "
                 f"{ov.get('Actv.', 0)} activated · {ov.get('Appr.', 0)} approved · "
                 f"{ov.get('Canc.', 0)} canceled · {ov.get('Disc.', 0)} disconnected")

    last_by = {r.sso: r.lines for r in last.reps} if last else {}
    w = max([len(_short(r.name)) for r in wk.reps] + [4])
    lines = ["Rep".ljust(w) + " " + " ".join(d[:2] for d in shown) + "  Lines Sales Appr  LW"]
    for r in sorted(wk.reps, key=lambda r: (-r.lines, r.name)):
        days = " ".join(str(r.days[d]).rjust(2) for d in shown)
        lw = last_by.get(r.sso)
        lines.append(f"{_short(r.name).ljust(w)} {days}  {str(r.lines).rjust(5)} "
                     f"{str(r.sales).rjust(5)} {_pct(r.vals.get('Appr. %')).rjust(4)} "
                     f"{('–' if lw is None else str(lw)).rjust(3)}")
    tot_days = " ".join(str(sum(r.days[d] for r in wk.reps)).rjust(2) for d in shown)
    lines.append(f"{'TOTAL'.ljust(w)} {tot_days}  {str(wk.lines).rjust(5)} "
                 f"{str(sum(r.sales for r in wk.reps)).rjust(5)}")
    board = head + "\n```" + "\n".join(lines) + "```"

    gone = [n for s, n in ((r.sso, r.name) for r in (last.reps if last else []))
            if s not in {x.sso for x in wk.reps}]
    replies = [board]
    if gone:
        replies.append(":eyes: Sold last week, nothing yet this week: " + ", ".join(_short(n, 30) for n in gone))
    replies.append(f"_Source: Credico Sales Verification ({sv.path.name}) → 'Sales by Week' + 'Overview'. "
                   f"Lines = Credico 'Valid Lines' (eligible for pay); LW = last week's lines._")
    return parent, replies


def compliance_board(cf: Compliance) -> Tuple[str, List[str]]:
    flagged = [r for r in cf.reps if r.flags > 0]
    we = f"WE {_md(cf.week_end)}" if cf.week_end else ""
    parent = f":triangular_flag_on_post: *Verizon Compliance Flags* · {we} · {len(flagged)} of {len(cf.reps)} reps flagged"
    out = []
    for r in sorted(flagged, key=lambda r: (-r.flags, r.name)):
        churn = " · ".join(f"{k}d {_pct(r.churn[k])}" for k in CHURN_KEYS if r.churn.get(k))
        out.append(f"• *{r.name}* — {r.flags} flag{'s' if r.flags != 1 else ''}: "
                   f"{', '.join(FLAG_WORDS.get(f, f) for f in r.flagged) or 'see sheet'}" + (f"  _(churn {churn})_" if churn else ""))
    camp = next((r.campaign for r in cf.reps if r.campaign), {})
    office_churn = []
    # All-zero churn INCLUDING the campaign = Credico hasn't filled it, not a proven 0.
    churn_blank = not any(r.churn.get(k) for r in cf.reps for k in CHURN_KEYS) and not any(camp.values())
    for k in ([] if churn_blank else CHURN_KEYS):
        tot = sum(r.sales for r in cf.reps)
        if tot:
            office_churn.append(f"{k}d {_pct(sum(r.churn.get(k, 0) * r.sales for r in cf.reps) / tot)}"
                                + (f" (campaign {_pct(camp[k])})" if k in camp else ""))
    replies = ["\n".join(out) or "No rep flagged this week."]
    if office_churn:
        replies.append("*Office churn (sales-weighted):* " + " · ".join(office_churn))
    elif churn_blank:
        replies.append(":warning: Churn columns came back empty for every rep AND the campaign — "
                       "Credico hasn't filled them this week, so no churn is shown.")
    replies.append("_Credico: this is a heads-up, not a complaint. Source: "
                   f"{cf.path.name} → sheet VZWCF._")
    return parent, replies
