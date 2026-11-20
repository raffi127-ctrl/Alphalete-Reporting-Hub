# -*- coding: utf-8 -*-
"""Per-rep Order Log as ONE picture (Carlos 2026-11-14: "instead of sending
out the whole file, I want screenshots sent to each individual rep ... It
should just be a screenshot, though, not a file. The screenshot should still
have the activation and pay week").

The retired workbook's rep tab, redrawn as HTML and screenshotted: the rep's
name, one blue band per Sun-Sat pay week ("Activated Week 11.01 to 11.07 •
Paid Friday 11.13", activated lines by their activation-else-install-else-
order date, like the workbook) with a Total row under it, an orange Pending /
Disconnect / Cancel band for everything else, rows coloured by status
(uploaded.order_log.STATUS_COLORS), and the Activation/Pay Week calendar
underneath. Columns (Carlos 2026-11-20: "add the word activated next to the
word week ... get rid of the ported from, SPM number, wireless order number,
and BAN ... to the right of [estimated revenue] add in columns to say 30%
payout, 40%, 45%, and 50%, and then underneath it a total row that adds all
those up"):

  Order Date | Activation Date | Customer Name | Status | Est. Revenue |
  30% Payout | 40% Payout | 45% Payout | 50% Payout |
  Device | Package | Next Up | Phone Number | Zip Code

Est. Revenue = the revenue board's per-line price (sow_rates wireless: port
$213 / BYOD port $188 / new line $25 / upgrade $30 / tablet-wearable $25,
OOF), $0 on a Cancelled line. Each payout column is that share of the line's
Est. Revenue. The Total row sums the five money columns for the ACTIVATED
week above it (what that Friday pays); the Pending / Disconnect / Cancel band
carries no total -- nothing in it is paid. Everything comes off Tableau (the
NDS Order Log tab join went with the Wireless Order # column).

  rerun nds_metrics --rep-shot "Esmeralda" --dm U046G04P5LG
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import html as _html
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PAYOUT_PCTS = (30, 40, 45, 50)
PAYOUT_COLS = tuple("%d%% Payout" % p for p in PAYOUT_PCTS)
MONEY_COLS = ("Est. Revenue",) + PAYOUT_COLS
COLUMNS = (("Order Date", "Activation Date", "Customer Name", "Status") + MONEY_COLS
           + ("Device", "Package", "Next Up", "Phone Number", "Zip Code"))


def payouts(revenue: float) -> Dict[str, float]:
    """{'30% Payout': ..., ...} for one line's Est. Revenue."""
    return {c: round(float(revenue) * p / 100.0, 2) for c, p in zip(PAYOUT_COLS, PAYOUT_PCTS)}


def totals(lines: Sequence[dict]) -> Dict[str, float]:
    """The Total row: each money column summed over `lines`."""
    return {c: round(sum(float(ln.get(c) or 0) for ln in lines), 2) for c in MONEY_COLS}


def price_line_est(ported: bool, byod: bool, wireless_type: str, tn_type: str,
                   rates: Optional[dict] = None) -> float:
    """The revenue board's per-line $ (OOF base comp)."""
    from automations.nds_metrics.run import sow_rates
    sw = (rates or sow_rates())["wireless"]
    wt = (wireless_type or "").strip().lower()
    if wt in ("tablet", "wearable"):
        return float(sw.get("tablet_wearable_nonbyod", 25))
    if (tn_type or "").strip().lower() == "upgrade":
        return float(sw.get("upgrade_voice", 30))
    if ported:
        return float((sw["port_byod"] if byod else sw["port_nonbyod"])["OOF"])
    return float(sw.get("new_line", 25))


def _next_up(wip: str, wireless_type: str) -> str:
    if (wireless_type or "").lower() == "tablet":
        return "-"
    v = (wip or "").strip()
    lv = v.lower()
    if not v:
        return ""
    if "w/o" in lv or "without" in lv or "no next" in lv or lv == "wo":
        return "No Next Up"
    if "next up" in lv or lv in ("w", "with"):
        return "Next Up"
    return v


def _status(dtr: str, spe: str) -> str:
    d = (dtr or "").strip().lower()
    if d == "posted":
        return "Posted"
    s = (spe or dtr or "").strip()
    if s.lower().startswith("cancel"):
        return "Cancelled"
    return s or "Pending"


def rep_lines(cols, crew: Sequence, today: dt.date, log=print) -> Dict[str, List[dict]]:
    """{rep: [line dict, ...]} off the crew's Tableau lines (one row per line,
    as load_crew returns them)."""
    from automations.nds_churn import compute as NCC
    from automations.nds_metrics.run import _c, _parse_date
    i = {
        "od": cols.need("order date", "sp.order date (copy)", "sp.order date", "order date"),
        "rep": cols.need("rep", "rep"),
        "act": cols.find("dtr active date", "activatoin date", "activation date"),
        "cust": cols.find("customer name"),
        "dtr": cols.find("dtr status"),
        "spe": cols.find("spe.status"),
        "dev": cols.find("device description", "spe.phone", "phone model"),
        "pkg": cols.find("package"),
        "wip": cols.find("wireless installment plan"),
        "tn": cols.find("spe.tn"),
        "zip": cols.find("customer zip simple", "customer zip"),
        "carrier": cols.find("spe.port carrier", "port carrier"),
        "tnt": cols.find("spe.tn type", "tn type"),
        "wt": cols.find("spe.wireless type", "wireless type"),
        "prod": cols.find("product type (broken out)", "product type"),
        "inst": cols.find("spe.install date", "install date"),
    }

    def g(r, key):
        return _c(cols, r, i[key]) if i[key] is not None else ""
    out: Dict[str, List[dict]] = {}
    for r in crew:
        rep = g(r, "rep")
        od = _parse_date(g(r, "od"))
        if not rep or od is None:
            continue
        prod = (g(r, "prod") or "").upper()
        if prod and "WIRELESS" not in prod:
            continue                                   # Air / Internet lines are not on the wireless log
        tnt = g(r, "tnt").lower()
        ported = bool(g(r, "carrier")) or tnt == "port"
        rec = {"wireless_ip": g(r, "wip"), "package": g(r, "pkg"), "device": g(r, "dev")}
        byod = NCC.is_byod(rec)
        status = _status(g(r, "dtr"), g(r, "spe"))
        revenue = 0.0 if status == "Cancelled" else price_line_est(ported, byod, g(r, "wt"), tnt)
        line = {
            "Order Date": od,
            "Activation Date": _parse_date(g(r, "act")),
            "Install Date": _parse_date(g(r, "inst")),
            "Customer Name": g(r, "cust"),
            "Status": status,
            "Est. Revenue": revenue,
            "Device": g(r, "dev"),
            "Package": g(r, "pkg"),
            "Next Up": _next_up(g(r, "wip"), g(r, "wt")),
            "Phone Number": g(r, "tn"),
            "Zip Code": g(r, "zip"),
        }
        line.update(payouts(revenue))
        out.setdefault(rep, []).append(line)
    return out


def _eff(line: dict) -> Optional[dt.date]:
    for k in ("Activation Date", "Install Date", "Order Date"):
        if line.get(k):
            return line[k]
    return None


def group_weeks(lines: List[dict]):
    """-> (weeks, pdc): weeks = {(sun, sat, paid): [lines]} for Posted /
    Active lines by their activation-else-install-else-order date; pdc = the
    rest, like the workbook's rep tab."""
    from automations.uploaded.order_log import _pdc_code, _week_bounds
    weeks: dict = {}
    pdc: List[dict] = []
    for ln in lines:
        if _pdc_code(ln["Status"]) is None:
            d = _eff(ln)
            if d is None:
                continue
            weeks.setdefault(_week_bounds(d), []).append(ln)
        else:
            pdc.append(ln)
    for k in weeks:
        weeks[k].sort(key=lambda x: (_eff(x) or dt.date.min, x["Customer Name"]))
    pdc.sort(key=lambda x: (x["Status"], _eff(x) or dt.date.min))
    return weeks, pdc


def _fmt_cell(col: str, v) -> str:
    if v is None or v == "":
        return ""
    if col in ("Order Date", "Activation Date"):
        return f"{v.month}/{v.day}" if hasattr(v, "month") else str(v)
    if col == "Est. Revenue":
        return f"${float(v):,.0f}"
    if col in PAYOUT_COLS:
        return f"${float(v):,.2f}"
    return _html.escape(str(v))


_CSS = """
<style>
 body{margin:0;font-family:Georgia,'Times New Roman',serif;background:#fff}
 .board{display:inline-block;padding:16px 18px;background:#fff}
 .rep{font-size:22px;font-weight:700;margin:0 0 2px;font-family:'Helvetica Neue',Arial,sans-serif}
 .sub{font-size:12px;color:#444;margin:0 0 10px;font-family:'Helvetica Neue',Arial,sans-serif}
 table{border-collapse:collapse;margin-bottom:14px}
 td,th{border:1px solid #8c8c8c;padding:5px 9px;font-size:12px;text-align:center;white-space:nowrap}
 th{background:#434343;color:#fff;font-weight:700}
 td.band{background:#2563EB;color:#fff;font-weight:700;font-size:13px;text-align:center}
 td.pdc{background:#C55A11;color:#fff;font-weight:700;font-size:13px}
 td.tot{background:#D9D9D9;color:#000;font-weight:700;font-size:13px}
 td.tot.lbl{text-align:right}
 .cal{margin-top:6px}
 .cal td.t{background:#6D8FC9;font-weight:700}
 .cal th{background:#1F3864}
 .cal td.alt{background:#C9DAF8}
 .cal td.now{background:#FFE599;font-weight:700}
 .note{font-size:11px;font-style:italic;color:#333;margin-top:-10px}
</style>"""


def total_row(lines: Sequence[dict]) -> str:
    """'Total' under the money columns: label across the columns left of Est.
    Revenue, one sum per money column, one blank cell across the rest."""
    t = totals(lines)
    first = COLUMNS.index(MONEY_COLS[0])
    after = len(COLUMNS) - first - len(MONEY_COLS)
    cells = f'<td class="tot lbl" colspan="{first}">Total</td>'
    cells += "".join(f'<td class="tot">{_fmt_cell(c, t[c])}</td>' for c in MONEY_COLS)
    if after:
        cells += f'<td class="tot" colspan="{after}"></td>'
    return f"<tr>{cells}</tr>"


def html_for(rep: str, lines: List[dict], today: dt.date) -> str:
    """One table so every week's columns line up: a blue band + header per
    pay week with its Total row, the orange Pending / Disconnect / Cancel
    band, then the Activation/Pay Week calendar."""
    from automations.uploaded.order_log import (STATUS_COLORS, STATUS_TEXT_COLORS,
                                                _md, _pay_period_weeks, _week_bounds)
    weeks, pdc = group_weeks(lines)
    ncol = len(COLUMNS)
    head = "<tr>" + "".join(f"<th>{c}</th>" for c in COLUMNS) + "</tr>"

    def row(ln):
        st = ln["Status"]
        bg = STATUS_COLORS.get(st, "FFD666")
        fg = STATUS_TEXT_COLORS.get(st, "000000")
        tds = "".join(f'<td style="background:#{bg};color:#{fg}">{_fmt_cell(c, ln.get(c))}</td>'
                      for c in COLUMNS)
        return f"<tr>{tds}</tr>"

    body = (f'<div class="rep">{_html.escape(rep.upper())}</div>'
            f'<div class="sub">NDS Order Log &nbsp;•&nbsp; as of {today.strftime("%a %-m/%-d/%Y")}</div>')
    body += "<table>"
    for (ws_, we_, paid) in sorted(weeks):
        body += (f'<tr><td class="band" colspan="{ncol}">Activated Week {_md(ws_)} to {_md(we_)}'
                 f'&nbsp;&nbsp;•&nbsp;&nbsp;Paid Friday {_md(paid)}</td></tr>{head}'
                 + "".join(row(ln) for ln in weeks[(ws_, we_, paid)])
                 + total_row(weeks[(ws_, we_, paid)]))
    if pdc:
        body += (f'<tr><td class="pdc" colspan="{ncol}">Pending / Disconnect / Cancel</td></tr>'
                 f'{head}' + "".join(row(ln) for ln in pdc))
    if not weeks and not pdc:
        body += f'<tr><td colspan="{ncol}">No lines on the log for this rep.</td></tr>'
    body += "</table>"
    # the Activation/Pay Week calendar, same as the workbook's
    this_week = _week_bounds(today)
    cal = ('<table class="cal"><tr><td class="t" colspan="3">Activation/Pay Week</td></tr>'
           '<tr><th>Week Start</th><th>Week End</th><th>Pay Date</th></tr>'
           '<tr><th>Sunday</th><th>Saturday</th><th>Friday</th></tr>')
    for n, week in enumerate(_pay_period_weeks(today)):
        cls = "now" if week == this_week else ("alt" if n % 2 else "")
        cal += "<tr>" + "".join(f'<td class="{cls}">{d.month}/{d.day}/{d.year % 100:02d}</td>'
                                for d in week) + "</tr>"
    cal += '</table><div class="note">Highlighted = this week</div>'
    body += cal
    return (f"<html><head><meta charset='utf-8'>{_CSS}</head><body>"
            f'<div class="board">{body}</div></body></html>')


def render_rep_png(rep: str, lines: List[dict], today: dt.date, out: Path) -> Path:
    from automations.b2b_metrics.rep_boards import _capture_board
    return _capture_board(html_for(rep, lines, today), out, width=2300)


def build(cols, crew: Sequence, today: dt.date, out_dir: Path, reps: Optional[Sequence[str]] = None,
          log=print) -> Dict[str, Path]:
    """One PNG per rep (every rep with a wireless line on the log, or only
    `reps` -- case-blind substrings). -> {rep: png}."""
    from automations.uploaded.order_log import _md
    per_rep = rep_lines(cols, crew, today, log=log)
    if reps:
        want = [w.lower() for w in reps]
        per_rep = {r: v for r, v in per_rep.items() if any(w in r.lower() for w in want)}
    out: Dict[str, Path] = {}
    for rep, lines in sorted(per_rep.items()):
        slug = "_".join(rep.lower().split())
        png = out_dir / f"nds_rep_order_log_{slug}_{today.isoformat()}.png"
        render_rep_png(rep, lines, today, png)
        out[rep] = png
        weeks, _pdc = group_weeks(lines)
        wk = "; ".join("wk %s-%s $%s" % (_md(k[0]), _md(k[1]), format(totals(v)["Est. Revenue"], ",.0f"))
                       for k, v in sorted(weeks.items()))
        log(f"[nds] rep order log: {rep}: {len(lines)} line(s) [{wk or 'no activated weeks'}] -> {png.name}")
    return out
