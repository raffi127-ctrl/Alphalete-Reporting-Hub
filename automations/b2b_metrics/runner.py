"""Generic B2B Metrics runner — ONE ordered run per office.

  python -m automations.b2b_metrics.runner --office carlos            # plan
  python -m automations.b2b_metrics.runner --office carlos --dry-run  # capture, no post
  python -m automations.b2b_metrics.runner --office carlos --post     # capture + post
  python -m automations.b2b_metrics.runner --office carlos --check    # validate table
  python -m automations.b2b_metrics.runner --office carlos --only order_log

Replaces the SCATTER (Megan 2026-07-20): today the thread is fed by b2b_quality
(Activation/Churn) + vantura_churn (Customer Churn / Activation-by-rep) racing
into one thread with no guaranteed order. This runs the whole ordered set in one
pass, so Carlos's "these in order" holds and there's one schedule + one failure
surface — the same win office_metrics.runner gave the D2D side.

MUST RUN ON LUCY 2: the Tableau captures ride Carlos's login (his custom views),
and a laptop pull would evict the mini's ownerville session holder.

TRANSITION (do NOT skip): b2b_quality + vantura_churn STILL post today. This
runner is --dry-run until it's verified to post every item into the SAME thread,
then their posting is retired so the thread doesn't double up. Until then this
opens NOTHING new — dry-run captures to output/ only.

CONTINUE-ON-FAILURE: one item that fails to capture is logged and skipped; the
rest still post. A blank Out-of-Bounds is NOT a failure — it posts (Carlos's
Loom: "if it shows nothing, we still want the screenshot").
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
import traceback
from pathlib import Path

from automations.b2b_metrics import offices as _off
from automations.b2b_metrics.offices import B2BOffice, THREAD_TITLE

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- the ordered items ------------------------------------------------------
# Each: id, emoji, title, kind, capture(office, out_dir) -> Path|None. #7
# (Activation report) is intentionally ABSENT until Carlos maps it. Order IS
# Carlos's order (offices.py docstring).
def _tableau_shot(view_key: str, owner_filter: bool = False):
    def cap(o: B2BOffice, out_dir: Path, log):
        from automations.b2b_metrics import capture
        return capture.tableau_image(o, view_key, out_dir,
                                     owner_filter=owner_filter, log=log)
    return cap


def _sheet_shot(which: str):
    def cap(o: B2BOffice, out_dir: Path, log):
        from automations.b2b_metrics import capture
        return capture.churn_tab_image(o, which, out_dir, log=log)
    return cap


def _order_log(o: B2BOffice, out_dir: Path, log):
    from automations.b2b_metrics import capture
    return capture.order_log_workbook(o, out_dir, log=log)


def _payout(o: B2BOffice, out_dir: Path, log):
    from automations.b2b_metrics import capture
    return capture.payout_image(o, out_dir, log=log)


ITEMS = [
    dict(id="sales_metrics", emoji="\U0001F4CA", title="Sales Metrics",
         capture=_tableau_shot("sales_metrics", owner_filter=True)),
    dict(id="activation_rate", emoji="\U000026A1", title="Activation Rate",
         capture=_tableau_shot("activation_rate")),
    dict(id="churn_rate", emoji="\U0001F4C9", title="Churn Rate",
         capture=_tableau_shot("churn_rate")),
    dict(id="customer_churn", emoji="\U0001F43A", title="Churn & Activations Board",
         capture=_sheet_shot("customer_churn")),
    dict(id="activation_by_rep", emoji="\U0001F4C8", title="Activation Rate by Rep",
         capture=_sheet_shot("activation_by_rep")),
    dict(id="order_log", emoji="\U0001F4C4", title="Order Log", is_file=True,
         capture=_order_log),
    dict(id="activation_overview", emoji="\U0001F4B5",
         title="Activation Report Overview", capture=_payout),
    dict(id="out_of_bounds", emoji="\U0001F6A7", title="Out of Bounds",
         capture=_tableau_shot("out_of_bounds"), post_when_blank=True),
]


def header_title(o: B2BOffice, day: dt.date) -> str:
    return "{} {:02d}/{:02d}/{}".format(THREAD_TITLE, day.month, day.day, day.year)


def header_text(o: B2BOffice, day: dt.date) -> str:
    lines = ["*{}*".format(header_title(o, day))]
    lines += ["{} {}".format(i["emoji"], i["title"]) for i in ITEMS]
    return "\n".join(lines)


def _out_dir(o: B2BOffice) -> Path:
    d = REPO_ROOT / "output" / "b2b_metrics" / o.key
    d.mkdir(parents=True, exist_ok=True)
    return d


def run(o: B2BOffice, *, post: bool, only: str = None,
        today: dt.date = None, log=print) -> dict:
    today = today or dt.date.today()
    out_dir = _out_dir(o)
    items = [i for i in ITEMS if not only or i["id"] == only]

    log("B2B Metrics — {} — {}  ({})".format(
        o.label, today, "POST" if post else "DRY-RUN"))
    log("  header: {}".format(header_title(o, today)))

    # 1) capture everything first (so a capture crash never leaves a
    #    half-posted thread), continue-on-failure.
    captured = {}
    for item in items:
        try:
            path = item["capture"](o, out_dir, log)
            captured[item["id"]] = path
            log("  [{}] {}".format(item["id"],
                                   path.name if path else "no artifact"))
        except Exception:  # noqa: BLE001 — one item must not kill the rest
            log("  [{}] FAILED:".format(item["id"]))
            for ln in traceback.format_exc().splitlines()[-6:]:
                log("      " + ln[:180])
            captured[item["id"]] = None

    if not post:
        ready = [k for k, v in captured.items() if v]
        log("")
        log("  DRY-RUN — captured {}/{}: {}".format(
            len(ready), len(items), ", ".join(ready)))
        return {"captured": ready, "posted": []}

    # 2) post — reuse b2b_quality's thread_state so we join the SAME thread and
    #    survive this channel's no-history-read limitation.
    from automations.shared import slack_metrics_post as smp
    import automations.b2b_quality.run as bq
    client = smp._client()
    cid = o.channel_id
    state = bq._load_state(today, cid)
    already = list(state.get("posted") or [])
    ts = state.get("thread_ts") or bq.find_thread_ts(client, cid, today)
    if not ts:
        ts = client.chat_postMessage(
            channel=cid, text=header_text(o, today)).get("ts")
        bq._save_state(today, cid, ts, already)
        log("  opened thread ts={}".format(ts))

    posted = []
    for item in items:
        path = captured.get(item["id"])
        if not path:
            continue
        if item["id"] in already:
            log("  [{}] already in thread — skip".format(item["id"]))
            continue
        caption = "{} *{}*".format(item["emoji"], item["title"])
        client.files_upload_v2(channel=cid, thread_ts=ts, file=str(path),
                               filename=path.name, initial_comment=caption)
        posted.append(item["id"])
        already.append(item["id"])
        bq._save_state(today, cid, ts, already)   # after EACH, crash-safe
        time.sleep(1)
        log("  [{}] posted".format(item["id"]))
    return {"thread_ts": ts, "posted": posted}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="b2b_metrics.runner")
    ap.add_argument("--office", default=None)
    ap.add_argument("--post", action="store_true",
                    help="capture AND post (default: capture only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture to output/, no post (explicit form of default)")
    ap.add_argument("--only", default=None, help="run a single item by id")
    ap.add_argument("--check", action="store_true",
                    help="validate the office table and exit")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)

    if args.check:
        problems = _off.validate()
        print("office table:", "CLEAN" if not problems else "PROBLEMS")
        for p in problems:
            print("  - " + p)
        return 1 if problems else 0

    _off.assert_valid()
    if not args.office:
        print("items (in order):")
        for i in ITEMS:
            print("  {} {}".format(i["emoji"], i["title"]))
        print("\noffices:", ", ".join(_off.ORDER))
        return 0

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    o = _off.get(args.office)
    res = run(o, post=args.post, only=args.only, today=today)
    print("\nresult:", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
