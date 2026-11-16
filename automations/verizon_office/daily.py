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
# The 'Verizon Order Log' tab (order_log_tab.py): True = the Vantura Master
# (Carlos approved the sandbox preview 2026-11-14, 727 lines); False = the
# Sales Board SANDBOX copy.
ORDER_LOG_PROD = True
# The 'VERIZON CHURN' tab (churn_tab.py): True = the Vantura Master (Carlos
# approved the preview 2026-11-15, "Yes, go live"); False = the Sales Board
# SANDBOX copy.
CHURN_TAB_PROD = True
# The comp grid leads the thread each morning through this date (Carlos 2026-11-15).
PAYOUT_IN_THREAD_UNTIL = dt.date(2026, 11, 22)


def plan(office: OF.VerizonOffice, today: dt.date, sv_path: Path, cf_path=None):
    """[(kind, payload)] in thread order. kind = "image" / "file" (path,
    caption) or "text"."""
    sv = parse.read_sales_verification(sv_path)
    if parse.file_date(sv_path) != today:
        raise RuntimeError(f"newest Sales Verification is {parse.file_date(sv_path)}, not today — stale, nothing posts")
    # BLANK = NO REP IN ANY WEEK. The newest block is the week in progress:
    # Monday's file runs through Sunday, and a Sunday nobody sold leaves it
    # empty while last week holds everything (11/9: WE 11/14 0 reps, WE 11/7
    # 14 reps / 149 lines -- the old weeks[0] check posted nothing).
    if not any(w.reps for w in sv.weeks):
        raise RuntimeError("no reps in any week — not posting a blank board")
    out = ROOT / "output" / "verizon_office" / office.key
    out.mkdir(parents=True, exist_ok=True)
    # NO SALES BOARD FROM HERE (Carlos 2026-11-07): his vantura_verizon_credico
    # fills the Vantura 'Verizon Sales Board' tab from the same Credico file
    # and posts its day + week pictures into this same thread (Lucy 2).
    steps = []
    # THE COMP GRID FIRST, every morning through PAYOUT_IN_THREAD_UNTIL (Carlos
    # 2026-11-15: "post it on there every morning this week and make it the
    # first screenshot"). Its failure never costs the rest of the thread.
    if today <= PAYOUT_IN_THREAD_UNTIL:
        try:
            from automations.verizon_office import payout as PO
            png = PO.render_png(out / "boards" / f"verizon_payout_{today.isoformat()}.png", status=[], today=today)
            steps.append(("image", (png, ":clipboard: *Verizon Wireless Comp Grid*")))
        except Exception as e:  # noqa: BLE001
            print("⚠ comp grid picture skipped: %s" % e)
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
    # THE VERIZON CHURN TAB PICTURE, every day (Carlos 2026-11-15: "The Verizon
    # churn screenshot: let's add that one every day"): refresh the tab off
    # this same file, then shoot it, right after Churn Rates by Rep. Its
    # failure never costs the thread.
    if office.key == "nicolas":
        try:
            from automations.verizon_office import churn_tab as CH
            CH.refresh(Path(sv), today=today, prod=CHURN_TAB_PROD)
            out = ROOT / "output" / "verizon_office" / office.key / "boards"
            png = CH.screenshot(out / f"verizon_churn_tab_{today.isoformat()}.png",
                                sheet_id=CH.PROD_SHEET_ID if CHURN_TAB_PROD else CH.SANDBOX_SHEET_ID)
            item = ("image", (png, f":wolf: *VERIZON CHURN* — {today.month}/{today.day}"))
            at = next((i + 1 for i, (k, pl) in enumerate(steps) if k == "image" and "Churn Rates by Rep" in pl[1]), len(steps))
            steps.insert(at, item)
        except Exception as e:  # noqa: BLE001
            print("⚠ Verizon Churn tab picture skipped: %s" % e)
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
        # THE VERIZON ORDER LOG TAB rides the same pull too (Carlos 2026-11-13:
        # "make an order log like the one we had for the NDS"): every wireless
        # line of Credico's Order Detail merged into the 'Verizon Order Log' tab
        # (verizon_office.order_log_tab). SANDBOX copy until Carlos says "use the
        # real sheet" -- then ORDER_LOG_PROD = True. Its failure never undoes the post.
        try:
            from automations.verizon_office import order_log_tab as OL
            OL.refresh(Path(sv), today=today, prod=ORDER_LOG_PROD)
        except Exception as e:  # noqa: BLE001
            print("⚠ Verizon Order Log tab failed (the thread posted fine): %s" % e)
        # (the VERIZON CHURN tab is refreshed + pictured BEFORE the post, above)
    return 0


if __name__ == "__main__":
    sys.exit(main())
