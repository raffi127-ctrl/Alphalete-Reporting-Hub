"""Nico's Verizon metrics — the rest of the daily thread, from Credico's
Sales Verification 'Order Detail' (one row per line or plan; LINES only).

    python -m automations.verizon_office.metrics --sv FILE.xlsx      # preview -> output/

Mirrors the other programs' metrics thread (office_onboarding.schema REPORTS):
canceled orders, ongoing cancels, disconnects, rep activations, activation
rate + AutoPay %. Previous-day numbers like every program; they post into the
room's existing "Verizon Metrics MM/DD/YYYY" thread once Credico's email lands
(~10:45am CT). No weather / trackers: #alphalete-gp-sales already gets those
via Carlos (Megan 2026-11-07).

PREVIEW ONLY -- nothing posts until Nico is on ECO (Megan 2026-11-06).
COUNTS PER REP ONLY: Order Detail carries customer names; none leave here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

ROOT = Path(__file__).resolve().parents[2]


def _d(v) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def lines(sv_path: Path) -> List[Dict]:
    """Wireless LINE rows of Order Detail, reduced to what the boards need."""
    ws = openpyxl.load_workbook(sv_path, data_only=True, read_only=True)["Order Detail"]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    hi = next(i for i, r in enumerate(rows) if r and "Sales Agent Name" in r)
    ix = {str(c): i for i, c in enumerate(rows[hi]) if c}
    for need in ("Sales Agent Name", "Week End Date", "Product Category", "Status Code",
                 "Current Line Status", "Cancel Date", "Activation Date", "AutoPay Active"):
        if need not in ix:
            raise ValueError(f"{Path(sv_path).name}: Order Detail has no '{need}' column")
    out = []
    for r in rows[hi + 1:]:
        if str(r[ix["Product Category"]] or "").strip() != "Wireless Line":
            continue
        out.append({
            "rep": str(r[ix["Sales Agent Name"]] or "").strip(),
            "week": _d(r[ix["Week End Date"]]),
            "signed": _d(r[ix.get("Signed Date", ix["Week End Date"])]),
            "code": str(r[ix["Status Code"]] or "").strip(),
            "line": str(r[ix["Current Line Status"]] or "").strip(),
            "canceled": _d(r[ix["Cancel Date"]]),
            "activated": _d(r[ix["Activation Date"]]),
            "autopay": str(r[ix["AutoPay Active"]] or "").strip().upper() in ("Y", "YES", "TRUE"),
        })
    return out


def _table(rows: List[Tuple], head: Tuple) -> str:
    w = [max(len(str(x)) for x in col) for col in zip(head, *rows)] if rows else [len(h) for h in head]
    fmt = "  ".join("{:<%d}" % w[0:1][0] if i == 0 else "{:>%d}" % w[i] for i in range(len(head)))
    return "```" + "\n".join(fmt.format(*map(str, r)) for r in [head] + rows) + "```"


def cancels(L: List[Dict], wk: dt.date) -> Tuple[str, str]:
    """Lines Credico shows CANCELED, by the week they were sold."""
    this = Counter(l["rep"] for l in L if l["code"] == "CAN" and l["week"] == wk)
    four = Counter(l["rep"] for l in L if l["code"] == "CAN" and l["week"] and (wk - l["week"]).days < 28)
    sold4 = Counter(l["rep"] for l in L if l["week"] and (wk - l["week"]).days < 28)
    reps = sorted(set(four), key=lambda r: (-four[r], r))
    rows = [(r, this.get(r, 0), four[r], f"{four[r] / sold4[r] * 100:.0f}%") for r in reps]
    tot = sum(four.values()), sum(sold4.values())
    head = f":no_entry: *Canceled Orders — Verizon* · {sum(this.values())} this week · {tot[0]} of {tot[1]} lines in 4 weeks ({tot[0] / tot[1] * 100:.0f}%)" if tot[1] else ":no_entry: *Canceled Orders — Verizon* · none"
    return head, (_table(rows, ("Rep", "This wk", "4 wks", "of sold")) if rows else "No canceled lines in the last 4 weeks.")


def ongoing(L: List[Dict], today: dt.date) -> Tuple[str, str]:
    """Lines still SUBMITTED / PENDING -- not activated yet, so still at risk."""
    open_ = [l for l in L if l["code"] in ("SUB", "PEND") and not l["activated"]]
    by = defaultdict(list)
    for l in open_:
        by[l["rep"]].append((today - (l["signed"] or l["week"] or today)).days)
    rows = sorted(((r, len(a), max(a), sum(1 for d in a if d > 7)) for r, a in by.items()),
                  key=lambda x: (-x[1], x[0]))
    head = f":hourglass_flowing_sand: *Ongoing — not activated yet* · {len(open_)} lines · {sum(r[3] for r in rows)} older than 7 days"
    return head, (_table(rows, ("Rep", "Open", "Oldest (d)", ">7 days")) if rows else "Every line is activated or closed.")


def disconnects(L: List[Dict], wk: dt.date) -> Tuple[str, str]:
    dis = [l for l in L if l["line"].startswith("Disc") and l["week"] and (wk - l["week"]).days < 28]
    c = Counter(l["rep"] for l in dis)
    pre = Counter(l["rep"] for l in dis if "Pre" in l["line"])
    rows = sorted(((r, n, pre.get(r, 0), n - pre.get(r, 0)) for r, n in c.items()), key=lambda x: (-x[1], x[0]))
    head = f":x: *Disconnects — Verizon* · {len(dis)} lines in 4 weeks"
    return head, (_table(rows, ("Rep", "Disc", "Before pay", "After pay")) if rows else "No disconnects in the last 4 weeks.")


def activations(sv, wk: dt.date) -> Tuple[str, str]:
    """Reps whose FIRST Credico sales week is this one or last one."""
    first: Dict[str, dt.date] = {}
    for w in sorted(sv.weeks, key=lambda w: w.end):
        for r in w.reps:
            first.setdefault(r.name, w.end)
    new = sorted((n, d) for n, d in first.items() if (wk - d).days <= 7)
    head = f":new: *Rep Activations — Verizon* · {len(new)} new rep{'s' if len(new) != 1 else ''}"
    body = "\n".join(f"• *{n}* — first sale week ending {d.month}/{d.day}" for n, d in new) or "No new reps this week or last."
    return head, body


def rates(L: List[Dict], wk: dt.date) -> Tuple[str, str]:
    """Activation % and AutoPay % per rep over the 4 FINISHED weeks (this
    week's lines have not had time to activate)."""
    done = [l for l in L if l["week"] and 7 <= (wk - l["week"]).days < 35]
    by = defaultdict(list)
    for l in done:
        by[l["rep"]].append(l)
    rows = []
    for r, ls in by.items():
        rows.append((r, len(ls), f"{sum(1 for l in ls if l['activated']) / len(ls) * 100:.0f}%",
                     f"{sum(1 for l in ls if l['autopay']) / len(ls) * 100:.0f}%"))
    rows.sort(key=lambda x: (-x[1], x[0]))
    n = len(done)
    act = sum(1 for l in done if l["activated"]) / n * 100 if n else 0
    ap = sum(1 for l in done if l["autopay"]) / n * 100 if n else 0
    head = f":zap: *Activation Rate + AutoPay % — Verizon* · {act:.0f}% activated · {ap:.0f}% AutoPay (4 finished weeks)"
    return head, (_table(rows, ("Rep", "Lines", "Activated", "AutoPay")) if rows else "No finished weeks yet.")


def build(sv_path: Path, today: Optional[dt.date] = None) -> List[Tuple[str, str]]:
    from automations.verizon_office import parse
    sv = parse.read_sales_verification(sv_path)
    L = lines(sv_path)
    if not L:
        raise RuntimeError("Order Detail has no wireless lines — not posting blank boards")
    wk = sv.weeks[0].end
    today = today or (sv.through + dt.timedelta(days=1) if sv.through else dt.date.today())
    return [cancels(L, wk), ongoing(L, today), disconnects(L, wk), activations(sv, wk), rates(L, wk)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sv", type=Path, required=True)
    a = ap.parse_args(argv)
    parts = build(a.sv)
    md = [f"# Verizon metrics — PREVIEW (not posted) · {dt.date.today()}\n",
          "Would post into today's *Verizon Metrics* thread in #alphalete-gp-sales.\n"]
    for head, body in parts:
        md.append(f"\n**{head}**\n\n{body}\n")
    out = ROOT / "output" / f"verizon_metrics_preview_{dt.date.today():%Y-%m-%d}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"(saved {out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
