"""Nico's daily Verizon metrics -> the room's "Verizon Metrics" thread.

    python -m automations.verizon_office.daily --office nicolas            # preview
    python -m automations.verizon_office.daily --office nicolas --send     # post (LIVE offices only)

ONE PULL, ONE THREAD: the newest Sales Verification in the Hub inbox (Credico
-> the office's Outlook redirect rule, ~10:45am CT, previous-day numbers like
every program) feeds, in order:

  1. (the sales board is Carlos's vantura_verizon_credico, same thread)
  2. the NDS wireless thread, same renderers (thread_boards.py): Rep
     Activations, Pending Orders, Activation Rate by Rep, Order Log (.xlsx,
     a tab per rep), Canceled Orders, Disconnected Orders
  + Wednesdays: the compliance board, when its file is in

They go INTO the day's existing "Verizon Metrics MM/DD/YYYY" thread in
#alphalete-gp-sales (sales_boards/run.py opens it at 5:10 for Carlos's Vantura
Verizon board; open_verizon_metrics_thread finds it, or opens it only if it
is missing). No weather / trackers: that room already has them (Megan
2026-11-07).

NOTHING LIVE UNTIL ECO (Megan 2026-11-06): --send posts only for offices in
LIVE_OFFICES ("nicolas" since 11/7, the day he went on ECO). Stale (not dated today) or blank -> nothing posts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.verizon_office import board_image, offices as OF, parse, run as RUN, thread_boards

ROOT = Path(__file__).resolve().parents[2]
LIVE_OFFICES: tuple = ("nicolas",)   # Nico on ECO 2026-11-07


def plan(office: OF.VerizonOffice, today: dt.date, sv_path: Path, cf_path=None):
    """[(kind, payload)] in thread order. kind = "image" / "file" (path,
    caption) or "text"."""
    sv = parse.read_sales_verification(sv_path)
    if parse.file_date(sv_path) != today:
        raise RuntimeError(f"newest Sales Verification is {parse.file_date(sv_path)}, not today — stale, nothing posts")
    if not sv.weeks or not sv.weeks[0].reps:
        raise RuntimeError("no reps this week — not posting a blank board")
    out = ROOT / "output" / "verizon_office" / office.key
    out.mkdir(parents=True, exist_ok=True)
    # NO SALES BOARD FROM HERE (Carlos 2026-11-07): his vantura_verizon_credico
    # fills the Vantura 'Verizon Sales Board' tab from the same Credico file
    # and posts its day + week pictures into this same thread (Lucy 2).
    steps = []
    for it in thread_boards.build(office.owner, sv_path, today, out / "boards"):
        if it["kind"] == "text":
            steps.append(("text", it["comment"]))
            continue
        for k, path in enumerate(it["paths"], 1):
            part = f" ({k} of {len(it['paths'])})" if len(it["paths"]) > 1 else ""
            steps.append((it["kind"], (path, it["comment"] + part)))
    if cf_path and today.weekday() == 2:                       # Wednesday
        cf = parse.read_compliance(cf_path)
        png = board_image.compliance_image(cf_path, out / f"compliance_{today:%Y-%m-%d}.png")
        we = f" · WE {cf.week_end.month}/{cf.week_end.day}" if cf.week_end else ""
        steps.append(("image", (png, f":shield: *Verizon Compliance Flags*{we}")))
    return steps


def post(office: OF.VerizonOffice, today: dt.date, steps, log=print) -> None:
    from automations.shared import slack_metrics_post as S
    from automations.sales_boards import run as SB
    client = S._client()
    ts = SB.open_verizon_metrics_thread(client, office.sales_channel, today)
    for kind, payload in steps:
        if kind in ("image", "file"):
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
    if a.send and (ROOT / "output" / f".verizon_daily_posted_{office.key}_{today:%Y-%m-%d}").exists():
        print("already posted today — nothing to do")
        return 0
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
        md.append(f"\n[{kind}] {payload[1]}  ({payload[0]})\n" if kind != "text" else f"\n{payload}\n")
    prev = ROOT / "output" / f"verizon_daily_preview_{office.key}_{today:%Y-%m-%d}.md"
    prev.write_text("\n".join(md), encoding="utf-8")
    print("%d item(s) planned → %s" % (len(steps), prev))
    if not a.send:
        print("preview — nothing posted")
        return 0
    if office.key not in LIVE_OFFICES:
        print("✗ %s is not live (LIVE_OFFICES) — nothing posted" % office.key)
        return 1
    # ONCE A DAY. The timer tries several times until Credico's email is in
    # (deploy/com.alphalete.verizon-daily.plist); the first post wins.
    marker = ROOT / "output" / f".verizon_daily_posted_{office.key}_{today:%Y-%m-%d}"
    if marker.exists():
        print("already posted today (%s) — nothing to do" % marker.name)
        return 0
    post(office, today, steps)
    marker.write_text(dt.datetime.now().isoformat())
    # THE OPT TAB rides the same pull (Megan 2026-11-08: "wire the weekly
    # fill"): the last six weeks into 'Nicolas Murrugarra - Verizon' on the
    # Alphalete Org sheet, so the current week's column is never stale. Its
    # own failure never undoes the post above.
    if office.key == "nicolas":
        try:
            from automations.alphalete_org_report import opt_verizon as OV
            OV.fill(Path(sv), compliance=cf)
        except Exception as e:  # noqa: BLE001
            print("⚠ OPT tab fill failed (the thread posted fine): %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
