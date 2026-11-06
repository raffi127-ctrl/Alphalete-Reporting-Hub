"""Verizon office boards — PREVIEW ONLY (no Slack post wired yet).

    python -m automations.verizon_office.run --sv <Sales Verification.xlsx> --cf <Compliance Flags.xlsx>

Writes the parent + thread text to output/verizon_office_preview_<date>.md and prints it.
Target room once approved: #alphalete-gp-sales (C07J46MQNUX), shared with Carlos.
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from automations.verizon_office import board, parse

ROOT = Path(__file__).resolve().parents[2]
GP_SALES = "C07J46MQNUX"   # #alphalete-gp-sales — Nico 2026-11-06: "its the gp sales with carlos"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sv", type=Path, help="Sales Verification xlsx")
    ap.add_argument("--cf", type=Path, help="Compliance Flags xlsx")
    a = ap.parse_args(argv)
    if not (a.sv or a.cf):
        ap.error("give --sv and/or --cf")
    parts = []
    if a.sv:
        p, th = board.sales_board(parse.read_sales_verification(a.sv))
        parts.append(("Sales board", p, th))
    if a.cf:
        p, th = board.compliance_board(parse.read_compliance(a.cf))
        parts.append(("Compliance flags", p, th))
    md = [f"# Verizon office boards — PREVIEW (not posted) · {dt.date.today()}\n",
          f"Would post to #alphalete-gp-sales ({GP_SALES}).\n"]
    for title, parent, thread in parts:
        md.append(f"\n## {title}\n\n**Parent post:**\n\n{parent}\n\n**Thread:**\n")
        md += [f"\n{t}\n" for t in thread]
    text = "\n".join(md)
    out = ROOT / "output" / f"verizon_office_preview_{dt.date.today():%Y-%m-%d}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n(saved {out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
