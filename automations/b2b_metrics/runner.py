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
from automations.b2b_metrics.capture import OrderLogNotFresh
from automations.b2b_metrics.offices import B2BOffice, THREAD_TITLE

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]

# Seconds to wait after each file post before the next. files_upload_v2 returns
# once the upload completes, but Slack CREATES the in-thread message
# asynchronously when it finishes rendering the image — a wide/heavy screenshot
# (Sales Metrics is the widest) can finalize AFTER a lighter image uploaded
# right after it, flipping their display order (Carlos 2026-07-21: "sales
# metrics should be first then activations"). We can't read this channel back to
# verify order, so a settle delay is the only lever. 1s wasn't enough; 4s gives
# each image time to land before the next uploads. 8 items ≈ +30s, negligible.
POST_SETTLE_SEC = 4


# --- the ordered items ------------------------------------------------------
# Each: id, emoji, title, kind, capture(office, out_dir) -> Path|None. #7
# (Activation report) is intentionally ABSENT until Carlos maps it. Order IS
# Carlos's order (offices.py docstring).
def _tableau_shot(view_key: str):
    def cap(o: B2BOffice, out_dir: Path, log):
        from automations.b2b_metrics import capture
        return capture.tableau_image(o, view_key, out_dir, log=log)
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
         capture=_tableau_shot("sales_metrics")),
    dict(id="activation_rate", emoji="\U000026A1", title="Activation Rate",
         capture=_tableau_shot("activation_rate")),
    dict(id="churn_wireless", emoji="\U0001F4C9", title="Wireless Churn",
         capture=_tableau_shot("churn_wireless")),
    dict(id="churn_int", emoji="\U0001F4C9", title="INT Churn",
         capture=_tableau_shot("churn_int")),
    dict(id="churn_air", emoji="\U0001F4C9", title="AIR Churn",
         capture=_tableau_shot("churn_air")),
    dict(id="customer_churn", emoji="\U0001F43A", title="Customer Churn",
         capture=_sheet_shot("customer_churn")),
    dict(id="activation_by_rep", emoji="\U0001F4C8", title="Activation Rate by Rep",
         capture=_sheet_shot("activation_by_rep")),
    dict(id="order_log", emoji="\U0001F4C4", title="Order Log", is_file=True,
         capture=_order_log),
    dict(id="order_tiered_bonus", emoji="\U0001F3C6",
         title="Order Tiered Bonus - Rep Ranking",
         capture=_tableau_shot("order_tiered_bonus")),
    dict(id="activation_overview", emoji="\U0001F4B5",
         title="Activation Report Overview", capture=_payout),
    dict(id="out_of_bounds", emoji="\U0001F6A7", title="Out of Bounds",
         capture=_tableau_shot("out_of_bounds"), post_when_blank=True),
]


def _publish_hub(status: str) -> None:
    """Record this run on the Hub so the B2B Metrics card pill reflects it.

    Without this, the report posts its whole thread every morning but the card
    stays grey — a silent miss looks identical to a clean run (the bug the
    codebase keeps fixing for standalone LaunchAgents). Best-effort: a publish
    failure must NEVER fail the report. Mirrors b2b_quality/run.py; the
    report_id 'b2b_metrics' resolves to the 'b2b-metrics' card via
    day_orchestrator.hub_publish._HUB_CARD."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(
            "b2b_metrics", "B2B Metrics → office channels", status)
    except Exception:  # noqa: BLE001
        pass


def _publish_running() -> None:
    """Open a live 'running' pill so the B2B Metrics card PULSES while the run
    works; _publish_hub closes that same row into green/red. Best-effort — a
    publish failure must NEVER fail the report (Megan 2026-07-29)."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_running("b2b_metrics", "B2B Metrics → office channels")
    except Exception:  # noqa: BLE001
        pass


def _write_manifest(per_office: list) -> None:
    """Persist section-level completeness so the orchestrator's reconciler can
    turn a silent partial post into an INCOMPLETE alert (the AT&T Order Log went
    missing 2026-07-26 and nothing paged Megan). Additive: the runner already
    KNOWS `present`/`missed` per office — this just records it. No Slack effect.

    `per_office` is a list of dicts: {key, present:[id], missed:[id], failed:bool}
    where `failed` marks an office whose whole run raised (no parent posted).

      succeeded  -> "<office>: <section>" for each present section
      failed     -> "<office>: <section>" for each missed section
      kind       -> "section"
      retry_args -> ["--all", "--post"]  (a re-post skips items already in the
                    thread state, so it backfills ONLY the missing sections)

    Best-effort: a manifest write must NEVER fail the report. `ok` is true only
    when nothing missed across every office; a partial run records failed[] which
    the manifest verifier renders as INCOMPLETE with the named sections."""
    try:
        from automations.shared import run_manifest
        succeeded, failed = [], []
        for po in per_office:
            key = po["key"]
            for sid in po.get("present", []):
                succeeded.append("{}: {}".format(key, sid))
            for sid in po.get("missed", []):
                # Name the office-run crash distinctly from a single dropped section.
                tag = "{}: {} (office run failed)".format(key, sid) if po.get("failed") \
                    else "{}: {}".format(key, sid)
                failed.append(tag)
        n = len(failed)
        note = "" if not n else "{} section(s) missing from the thread".format(n)
        run_manifest.write_manifest(
            "b2b_metrics", failed=failed, succeeded=succeeded,
            retry_args=["--all", "--post"], kind="section", note=note)
    except Exception:  # noqa: BLE001 — never let bookkeeping sink the report
        pass


def header_title(o: B2BOffice, day: dt.date) -> str:
    return "{} {:02d}/{:02d}/{}".format(THREAD_TITLE, day.month, day.day, day.year)


def header_text(o: B2BOffice, day: dt.date) -> str:
    lines = ["*{}*".format(header_title(o, day))]
    lines += ["{} {}".format(i["emoji"], i["title"])
              for i in expected_items(o)]
    return "\n".join(lines)


def expected_items(o: B2BOffice) -> list:
    """The sections this office's parent post ENUMERATES — the completeness
    contract. Used both to build the header and to reconcile expected-vs-actual,
    so the two can never drift. Items that post even when blank
    (`post_when_blank`, e.g. Out of Bounds) ARE expected — an empty-but-posted
    section still lands in the thread, so it's never a miss.

    Order + inclusion come from the office's Thread Builder plan
    (thread_plans.json) when one exists — a saved plan lists exactly the included
    section ids in post order and may even re-add a section skip_views drops. With
    NO plan (the default), this is byte-for-byte the old behavior: every ITEM
    except the ones this office gates out via `skip_views`."""
    from automations.shared import thread_plans as tp
    default = [i for i in ITEMS if i["id"] not in o.skip_views]
    return tp.resolve_sections("b2b", o.key, ITEMS, default, id_key="id")


def expected_ids(o: B2BOffice) -> list:
    return [i["id"] for i in expected_items(o)]


def _out_dir(o: B2BOffice) -> Path:
    d = REPO_ROOT / "output" / "b2b_metrics" / o.key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dm_captures(captured: dict, user: str, o: B2BOffice, day: dt.date,
                 log=print) -> None:
    """DM the captured artifacts to ONE user for review (dry-run only). Rejects
    channel ids so a preview can never become a channel post."""
    from automations.shared import slack_metrics_post as smp
    u = (user or "").strip()
    if not u.upper().startswith("U"):
        raise ValueError("refusing: {!r} is not a user id".format(u))
    for item in expected_items(o):
        path = captured.get(item["id"])
        if not path:
            continue
        smp.dm_user_with_file(
            path, user=u, file_name=path.name,
            comment="{} *{}* — B2B Metrics preview ({}). Not posted.".format(
                item["emoji"], item["title"], o.label))
        log("  DM'd {}".format(item["id"]))


def run(o: B2BOffice, *, post: bool, only: str = None, dm: str = None,
        channel_override: str = None, today: dt.date = None, force: bool = False,
        log=print) -> dict:
    today = today or dt.date.today()
    out_dir = _out_dir(o)
    # Capture/post in the SAME resolved order the header enumerates (plan-aware,
    # or today's ITEMS-minus-skip_views default). --only narrows to one section.
    items = [i for i in expected_items(o) if not only or i["id"] == only]

    log("B2B Metrics — {} — {}  ({})".format(
        o.label, today, "POST" if post else "DRY-RUN"))
    log("  header: {}".format(header_title(o, today)))

    # Pre-capture skip (retry/floor passes): drop any item already in EVERY
    # target thread today, so a later pass re-pulls the ~120MB ORDERLOG export
    # and re-shoots the Tableau images ONLY for the still-missing sections
    # (normally just the deferred order-log), not the whole thread. Cheap: thread
    # state is a Sheet read, no Slack client. Skipped under --force (which exists
    # to re-post) and --channel (a verification post with its own scratch thread).
    if post and not force and not channel_override:
        import automations.b2b_quality.run as _bq
        _tgts = [o.channel_id] + [c for c, _n in o.mirror_channels
                                  if c != o.channel_id]
        _done = [set(_bq._load_state(today, c).get("posted") or []) for c in _tgts]
        _done_all = set.intersection(*_done) if _done else set()
        if _done_all:
            _skip = [i["id"] for i in items if i["id"] in _done_all]
            items = [i for i in items if i["id"] not in _done_all]
            if _skip:
                log("  already in every thread — skip capture: {}".format(
                    ", ".join(_skip)))
        if not items:
            _exp = expected_ids(o)
            log("  nothing new — every expected section already in today's thread")
            return {"thread_ts": None, "posted": [],
                    "present": [i for i in _exp if i in _done_all],
                    "missed": [i for i in _exp if i not in _done_all]}

    # 1) capture everything first (so a capture crash never leaves a
    #    half-posted thread), continue-on-failure.
    captured = {}
    for item in items:
        try:
            path = item["capture"](o, out_dir, log)
            captured[item["id"]] = path
            log("  [{}] {}".format(item["id"],
                                   path.name if path else "no artifact"))
        except OrderLogNotFresh as nf:
            # Not a failure — the extract just hasn't landed. A later floor pass
            # posts it once it's in. Logged as DEFERRED so it doesn't read as a
            # crash (and doesn't spew a traceback).
            log("  [{}] DEFERRED — {}".format(item["id"], nf))
            captured[item["id"]] = None
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
        if dm:
            _dm_captures(captured, dm, o, today, log=log)
        return {"captured": ready, "posted": []}

    # 2) post — reuse b2b_quality's thread_state so we join the SAME thread and
    #    survive this channel's no-history-read limitation.
    from automations.shared import slack_metrics_post as smp
    import automations.b2b_quality.run as bq
    client = smp._client()
    # channel_override lets a VERIFICATION post go to a scratch/DM instead of
    # the office's real channel — proves the full threaded post path without
    # touching Carlos's live thread. A DM user id (U…) is opened into a channel.
    cid = o.channel_id
    if channel_override:
        cid = (client.conversations_open(users=channel_override)["channel"]["id"]
               if channel_override.upper().startswith("U") else channel_override)
        log("  channel OVERRIDE -> {}".format(cid))
        targets = [cid]                 # a verification post goes ONLY there
    else:
        # MIRRORS get the SAME captured set. Slack threads are per-channel, so
        # each target keeps its own daily thread + its own posted-state (dedup is
        # per channel). Captures already happened above, so a mirror costs one
        # upload per item — no extra Tableau work.
        targets = [cid] + [c for c, _name in o.mirror_channels if c != cid]

    posted = []
    per_chan_posted = []      # set of item ids in each target's thread
    first_ts = None
    for chan in targets:
        state = bq._load_state(today, chan)
        already = list(state.get("posted") or [])
        ts = state.get("thread_ts") or bq.find_thread_ts(client, chan, today)
        if not ts:
            ts = client.chat_postMessage(
                channel=chan, text=header_text(o, today)).get("ts")
            bq._save_state(today, chan, ts, already)
            log("  [{}] opened thread ts={}".format(chan, ts))
        if first_ts is None:
            first_ts = ts
        for item in items:
            path = captured.get(item["id"])
            if not path:
                continue
            if item["id"] in already and not force:
                log("  [{}] {} already in thread — skip".format(chan, item["id"]))
                continue
            caption = "{} *{}*".format(item["emoji"], item["title"])
            client.files_upload_v2(channel=chan, thread_ts=ts, file=str(path),
                                   filename=path.name, initial_comment=caption)
            posted.append(item["id"])
            already.append(item["id"])
            bq._save_state(today, chan, ts, already)  # after EACH, crash-safe
            time.sleep(POST_SETTLE_SEC)               # let Slack finalize this
            log("  [{}] {} posted".format(chan, item["id"]))
        per_chan_posted.append(set(already))
    ts = first_ts

    # Completeness across EVERY target (primary + mirrors): an item counts as
    # present only if it's in ALL their threads, so a mirror that missed one still
    # reads as partial rather than green. Drives the card pill: all present ->
    # green, some missed -> orange (partial), none present -> red (failed).
    all_present = (set.intersection(*per_chan_posted) if per_chan_posted else set())
    present = [i["id"] for i in items if i["id"] in all_present]
    missed = [i["id"] for i in items if i["id"] not in all_present]
    if missed:
        log("  MISSED (not in every thread): {}".format(", ".join(missed)))
    return {"thread_ts": ts, "posted": posted, "present": present,
            "missed": missed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="b2b_metrics.runner")
    ap.add_argument("--office", default=None)
    ap.add_argument("--all", dest="all_offices", action="store_true",
                    help="run EVERY office in the table (the morning batch); one "
                         "office failing doesn't stop the rest, and a single Hub "
                         "publish reflects all of them.")
    ap.add_argument("--post", action="store_true",
                    help="capture AND post (default: capture only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture to output/, no post (explicit form of default)")
    ap.add_argument("--only", default=None, help="run a single item by id")
    ap.add_argument("--dm", default=None, metavar="USER_ID",
                    help="DM the captured artifacts to ONE user for review (dry-run)")
    ap.add_argument("--channel", default=None, metavar="ID_OR_USER",
                    help="post to THIS channel/DM instead of the office's real "
                         "channel (verification of the post path)")
    ap.add_argument("--no-crop", action="store_true",
                    help="skip crop-to-last-rep on Churn/Activation (diagnostic — "
                         "shows the full captured image)")
    ap.add_argument("--check", action="store_true",
                    help="validate the office table and exit")
    ap.add_argument("--force", action="store_true",
                    help="re-post even items already in today's thread state "
                         "(backfill a fixed item over a bad one). Pair with "
                         "--only so ONLY that item re-posts, not the whole thread.")
    ap.add_argument("--require-fresh", action="store_true",
                    help="EARLY/scheduled passes: DEFER the order-log sections "
                         "(#8 Order Log, #9 Activation Report Overview) when the "
                         "ORDERLOG extract hasn't reached the prior completed day, "
                         "so a stale log isn't posted. The 8 non-order-log items "
                         "post regardless. A later FLOOR pass (this flag OMITTED) "
                         "posts whatever the extract has, so the sections are "
                         "never permanently absent — mirrors box_order_log's 7:00 "
                         "--require-fresh + 8:30 floor.")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)

    if args.no_crop:
        import os
        os.environ["B2B_SKIP_CROP"] = "1"

    # Pulse the card live while this real posting run works (not on --check /
    # dry-run); the _publish_hub at the end closes it green/red.
    if args.post and not args.check:
        _publish_running()

    if args.require_fresh:
        import os
        os.environ["B2B_REQUIRE_FRESH"] = "1"

    if args.check:
        problems = _off.validate()
        print("office table:", "CLEAN" if not problems else "PROBLEMS")
        for p in problems:
            print("  - " + p)
        return 1 if problems else 0

    _off.assert_valid()
    if not args.office and not args.all_offices:
        print("items (in order):")
        for i in ITEMS:
            print("  {} {}".format(i["emoji"], i["title"]))
        print("\noffices:", ", ".join(_off.ORDER))
        return 0

    # Before a LIVE post, pull the latest Thread Builder edits from the shared
    # sheet into thread_plans.json so today's threads match what the admin set
    # (Megan 2026-07-27 "reference it each morning to make sure it's accurate").
    # Best-effort: no creds / a sheet hiccup just leaves the committed plans in
    # place — it must never block the morning post. Skipped on dry-run/preview.
    if args.post:
        try:
            from automations.thread_builder import sync as _tb_sync
            _tb_sync.sync(verbose=False)
        except Exception:  # noqa: BLE001 — sync must never break the report
            pass

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    office_keys = list(_off.ORDER) if args.all_offices else [args.office]
    # Publish to the Hub only for a REAL post run of the office's own channel —
    # not --dry-run, not a --channel verification post, and not a single-item
    # --only run (which would flip the whole card green off one item). One publish
    # for the batch (the ONE 'b2b-metrics' card covers every office).
    publishable = args.post and not args.channel and not args.only

    statuses = []
    per_office = []     # {key, present, missed, failed} — feeds the run-manifest
    for key in office_keys:
        o = _off.get(key)
        try:
            res = run(o, post=args.post, only=args.only, dm=args.dm,
                      channel_override=args.channel, today=today, force=args.force)
            print("\nresult ({}):".format(key), res)
            missed = res.get("missed") or []
            present = res.get("present") or []
            statuses.append("success" if not missed
                            else ("partial" if present else "failed"))
            per_office.append({"key": key, "present": present, "missed": missed,
                               "failed": False})
        except Exception:
            statuses.append("failed")
            # The whole office run raised BEFORE (or mid) posting — treat every
            # section it was supposed to post as missing, so the manifest names
            # them rather than recording an empty (falsely-clean) office.
            per_office.append({"key": key, "present": [],
                               "missed": expected_ids(o), "failed": True})
            if not args.all_offices:      # single-office: fail loud as before
                if publishable:
                    _write_manifest(per_office)
                    _publish_hub("failed")
                raise
            traceback.print_exc()         # --all: one office must not kill the rest

    if publishable:
        # Record section-level completeness for the orchestrator's reconciler
        # (drives the INCOMPLETE / missing-section alert once verify is wired).
        _write_manifest(per_office)
        # Green only if EVERY office fully posted; orange if some did; red if none.
        if all(s == "success" for s in statuses):
            status = "success"
        elif any(s in ("success", "partial") for s in statuses):
            status = "partial"
        else:
            status = "failed"
        _publish_hub(status)
    # Non-zero ONLY when an office fully failed (no parent / nothing posted) — that
    # routes to the orchestrator's FAILED/retry path. A partial run (some sections
    # missed but the thread exists) stays exit 0; its manifest failed[] drives the
    # INCOMPLETE alert instead, so a single dropped section doesn't trigger a full
    # Tableau re-auth retry of a report that mostly worked.
    return 2 if any(s == "failed" for s in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
