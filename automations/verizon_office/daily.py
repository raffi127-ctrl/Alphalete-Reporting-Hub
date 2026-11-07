"""Nico's daily Verizon metrics -> the room's "Verizon Metrics" thread.

    python -m automations.verizon_office.daily --office nicolas            # preview
    python -m automations.verizon_office.daily --office nicolas --send     # post (LIVE offices only)

ONE PULL, ONE THREAD: the newest Sales Verification in the Hub inbox (Credico
-> the office's Outlook redirect rule, ~10:45am CT, previous-day numbers like
every program) feeds, in order:

  1. the sales board image (board_image, the Altura look)
  2. canceled orders · 3. ongoing (not activated) · 4. disconnects
  5. rep activations · 6. activation rate + AutoPay %       (metrics.py)
  + Wednesdays: the compliance board, when its file is in

They go INTO the day's existing "Verizon Metrics MM/DD/YYYY" thread in
#alphalete-gp-sales (sales_boards/run.py opens it at 5:10 for Carlos's Vantura
Verizon board; open_verizon_metrics_thread finds it, or opens it only if it
is missing). No weather / trackers: that room already has them (Megan
2026-11-07).

NOTHING LIVE UNTIL ECO (Megan 2026-11-06): --send posts only for offices in
LIVE_OFFICES, which is empty. Stale (not dated today) or blank -> nothing posts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.verizon_office import board_image, metrics, offices as OF, parse, run as RUN

ROOT = Path(__file__).resolve().parents[2]
LIVE_OFFICES: tuple = ()          # add "nicolas" the day he is on ECO


def plan(office: OF.VerizonOffice, today: dt.date, sv_path: Path, cf_path=None):
    """[(kind, payload)] in thread order. kind = "image" (path, caption) or "text"."""
    sv = parse.read_sales_verification(sv_path)
    if parse.file_date(sv_path) != today:
        raise RuntimeError(f"newest Sales Verification is {parse.file_date(sv_path)}, not today — stale, nothing posts")
    if not sv.weeks or not sv.weeks[0].reps:
        raise RuntimeError("no reps this week — not posting a blank board")
    out = ROOT / "output" / "verizon_office" / office.key
    out.mkdir(parents=True, exist_ok=True)
    png = board_image.render(sv_path, out / f"sales_board_{today:%Y-%m-%d}.png")
    steps = [("image", (png, f":satellite_antenna: *Verizon Sales Board — {sv.office}* · "
                             f"through {sv.through:%a %-m/%-d}" if sv.through else ""))]
    for head, body in metrics.build(sv_path, today):
        steps.append(("text", f"{head}\n{body}"))
    if cf_path and today.weekday() == 2:                       # Wednesday
        from automations.verizon_office import board
        p, th = board.compliance_board(parse.read_compliance(cf_path))
        steps.append(("text", p + "\n" + "\n".join(th)))
    return steps


def post(office: OF.VerizonOffice, today: dt.date, steps, log=print) -> None:
    from automations.shared import slack_metrics_post as S
    from automations.sales_boards import run as SB
    client = S._client()
    ts = SB.open_verizon_metrics_thread(client, office.sales_channel, today)
    for kind, payload in steps:
        if kind == "image":
            path, caption = payload
            client.files_upload_v2(channel=office.sales_channel, thread_ts=ts,
                                   file=str(path), initial_comment=caption)
        else:
            client.chat_postMessage(channel=office.sales_channel, thread_ts=ts, text=payload)
    log("✓ posted %d item(s) into the Verizon Metrics thread (%s)" % (len(steps), office.sales_channel))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="nicolas")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--sv", type=Path, help="local Sales Verification (preview / testing)")
    ap.add_argument("--date", help="YYYY-MM-DD the file should be dated (default today)")
    a = ap.parse_args(argv)
    office = OF.get(a.office)
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    sv = a.sv or RUN.fetch(office, "sales")
    if not sv:
        print("✗ no Sales Verification in the Hub inbox — is the office's Outlook rule delivering?")
        return 1
    cf = RUN.fetch(office, "compliance") if today.weekday() == 2 else None
    try:
        steps = plan(office, today, Path(sv), cf)
    except RuntimeError as e:
        print("✗ %s" % e)
        return 1
    md = [f"# Verizon Metrics thread — {'SENT' if a.send else 'PREVIEW'} · {office.owner} · {today}\n"]
    for kind, payload in steps:
        md.append(f"\n[image] {payload[1]}  ({payload[0]})\n" if kind == "image" else f"\n{payload}\n")
    prev = ROOT / "output" / f"verizon_daily_preview_{office.key}_{today:%Y-%m-%d}.md"
    prev.write_text("\n".join(md), encoding="utf-8")
    print("%d item(s) planned → %s" % (len(steps), prev))
    if not a.send:
        print("preview — nothing posted")
        return 0
    if office.key not in LIVE_OFFICES:
        print("✗ %s is not live (LIVE_OFFICES) — nothing posted" % office.key)
        return 1
    post(office, today, steps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
