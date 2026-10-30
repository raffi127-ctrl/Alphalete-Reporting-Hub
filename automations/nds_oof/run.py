"""NDS (RES AT&T OOF) -- knocks board, 15-min gaps, call-outs, for Carlos's crew.

    python -m automations.nds_oof.run                 # dry run: pull, render, print
    python -m automations.nds_oof.run --send          # post + queue the texts
    python -m automations.nds_oof.run --send --force  # ignore the clock (hand run)
    python -m automations.nds_oof.run --board         # force the board this tick

ONE TICK, EVERY 15 MINUTES (the LaunchAgent). Each tick opens ONE Ownerville
session as Carlos (this machine's login), pins the RES AT&T OOF campaign,
reads the Time Tracker feed for the gaps, and -- once an hour -- the
Disposition by Rep grid for the board. Then:

  * NDS 15 min gaps (typed, longest-dark first) -> the day's "NDS 15 Min
    Gaps" thread in #alphalete-gp-sales + a text to NEW A Players and
    ATT B2B Leaders. Never an empty list [[feedback_never_post_blank]].
  * NDS Knocks Board (picture, the same renderer every knocks board uses)
    -> the day's "NDS Knocks Board" thread + the same two texts. Hourly.
  * NDS call-out -> loose in #alphalete-gp-sales, once an hour: reps over
    the line whose SaraPlus credit-check count has not moved (the relay's
    records for carlos-b2batt), through icd_alerts.gap_callouts' own lines.

TEXTS ARE HANDED TO THE POLLER (text_dispositions manifests), exactly as the
Box gaps are: this job's identity has no Messages consent, the poller's does.

Replaces the Fiber reports off Raf's login (Carlos 2026-10-19). Raf's own
rooms are not touched by anything here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.nds_oof import config as C
from automations.shared.day_override import weekday as _wd

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "nds_oof"


def _log(msg: str = "") -> None:
    print("[nds] " + msg, flush=True)


# --- clock -------------------------------------------------------------------
def _window(now: dt.datetime):
    wd = _wd(now)
    if wd == 6:
        return None
    start, stop = (C.SATURDAY_START, C.SATURDAY_STOP) if wd == 5 else (C.WEEKDAY_START, C.WEEKDAY_STOP)
    start = getattr(C, "START_OVERRIDES", {}).get(now.date().isoformat(), start)
    return start, stop


def in_window(now: dt.datetime) -> bool:
    win = _window(now)
    if not win:
        return False
    (sh, sm), (eh, em) = win
    return (sh, sm) <= (now.hour, now.minute) <= (eh, em)


def _clock(now: dt.datetime) -> str:
    hour = now.hour % 12 or 12
    return "%d:%02d %s" % (hour, now.minute, "AM" if now.hour < 12 else "PM")


def _state() -> Dict:
    try:
        return json.loads(C.STATE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(state: Dict) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = C.STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(C.STATE_PATH)


def _due(state: Dict, key: str, every_min: int, now: dt.datetime) -> bool:
    last = state.get(key)
    if not last:
        return True
    try:
        last_at = dt.datetime.fromisoformat(last)
    except ValueError:
        return True
    # A minute of slack so a 15-minute tick that fires at :14:30 still counts.
    return (now - last_at) >= dt.timedelta(minutes=every_min - 1)


def _board_due(state: Dict, now: dt.datetime) -> bool:
    """ONE BOARD PER CLOCK HOUR, not one per 60 elapsed minutes. The first
    board on 2026-10-21 went at 2:02, every later one at :02, and the 9:00
    pass saw '58 minutes since the last board' and skipped -- 9:15 was past
    the window, so the day's last board was 8:02 (Carlos: 'this is the last
    one i got texted'). Keyed on the hour, the 9:00 pass always draws."""
    last = state.get("board_at")
    if not last:
        return True
    try:
        last_at = dt.datetime.fromisoformat(last)
    except ValueError:
        return True
    return _board_slot(last_at) != _board_slot(now)


def _board_slot(t: dt.datetime):
    """The board slot `t` falls in: every BOARD_EVERY_MIN of the clock (:00
    and :30), or the named slots of an hour that has them (Saturday 10:15 /
    10:30 / 10:45). One board per slot, however late the tick runs."""
    extras = [m for (h, m) in (C.SAT_EXTRA_BOARD_SLOTS if _wd(t) == 5
                               else C.EXTRA_BOARD_SLOTS) if h == t.hour]
    if extras:                       # an hour with its own named slots
        sub = sum(1 for m in extras if t.minute >= m)
    else:                            # otherwise one board per BOARD_EVERY_MIN
        sub = t.minute // C.BOARD_EVERY_MIN
    return (t.date(), t.hour, sub)


# --- text --------------------------------------------------------------------
def gaps_text(over: List[Dict], now: dt.datetime) -> str:
    """'NDS 15 min gaps — 3:15 PM' + 'Name - N min', longest first."""
    from automations.b2b_dispositions import capture as cap
    lines = []
    for r in sorted(over, key=lambda r: (-cap._int(r.get("minutesSinceLastKnock")),
                                         (r.get("name") or "").strip().lower())):
        name = (r.get("name") or "").strip()
        if name:
            lines.append("%s - %d min" % (name, cap._int(r.get("minutesSinceLastKnock"))))
    if not lines:
        return ""
    return "%s 15 min gaps — %s\n\n%s" % (C.TEAM, _clock(now).replace(":00", ""), "\n".join(lines))


# --- pull --------------------------------------------------------------------
def pull(today: dt.date, *, want_board: bool, headless: bool = True):
    """ONE session: campaign pinned, gaps feed, and (hourly) the board rows."""
    from automations.shared.tableau_patchright import ownerville_session
    from automations.total_knocks import pull as knocks
    from automations.rashad_metrics import knocks_pull as KP
    from automations.b2b_dispositions import capture as cap
    mdy = today.strftime("%m/%d/%Y")
    rows: List[Dict] = []
    with ownerville_session(headless=headless, profile_dir=str(C.PROFILE_DIR)) as page:
        rqst = knocks._capture_rqst(page)
        if not rqst:
            raise RuntimeError("couldn't capture the ownerville rqst token")
        KP._pin_campaign(page, rqst, C.CAMPAIGN_ID, verbose=True)
        raw = cap.fetch_time_tracking(page, rqst, mdy)
        over = [r for r in raw
                if cap._int(r.get("minutesSinceLastKnock")) > C.GAP_THRESHOLD_MIN]
        if want_board:
            rows = KP._scrape_day_on_page(page, rqst, today, verbose=True)
    _log("gaps feed: %d rep(s), %d over %d min%s"
         % (len(raw), len(over), C.GAP_THRESHOLD_MIN,
            ("; board rows: %d" % len(rows)) if want_board else ""))
    return over, rows


def board_kpis() -> Dict:
    """Raf's KPI scales with THIS crew's First Knock (2:00 start, see config)."""
    from automations.shared import knock_kpis
    (gh, gm), (rh, rm) = C.FIRST_KNOCK_GREEN_AT, C.FIRST_KNOCK_RED_AT
    return {**knock_kpis.load(logfn=_log),
            "first_knock": knock_kpis.Scale(gh * 60 + gm, rh * 60 + rm)}


def render_board(rows: List[Dict], today: dt.date, now: dt.datetime, out_dir: Path) -> List[Path]:
    from automations.total_knocks import render as knocks_render
    pngs, shape = knocks_render.render_knocks_boards(
        today, rows=rows, out_dir=out_dir,
        title_suffix="%s — Carlos" % C.TEAM,
        date_text="%s — %s" % (today.strftime("%a %m/%d"), _clock(now)),
        rate_columns=True, sort_by="knocks", kpis=board_kpis())
    _log("board: %s (%s)" % (", ".join(p.name for p in pngs), shape))
    return list(pngs)


# --- post --------------------------------------------------------------------
def _thread_ts(title: str, today: dt.date) -> Optional[str]:
    """The day's NDS METRICS thread first (Carlos 2026-10-22: 'remove the
    NDS knocks board and NDS 15 min gaps thread and just post that stuff
    into the NDS metrics thread' — the Box pattern). nds_metrics runs on
    THIS machine, so its state file is the authority; the old named thread
    is the fallback when the metrics thread hasn't opened yet (pre-7:30)."""
    import json
    from pathlib import Path
    state = (Path(__file__).resolve().parents[2] / "output" / "nds_metrics"
             / f"thread_{today.isoformat()}.json")
    try:
        ts = json.loads(state.read_text()).get("ts")
        if ts:
            return ts
    except Exception:  # noqa: BLE001 — no metrics thread yet
        pass
    from automations.shared import slack_metrics_post as smp
    return smp.ensure_named_thread(title, today, channel_id=C.SLACK_CHANNEL).get("thread_ts")


def _post_board(pngs: List[Path], today: dt.date, now: dt.datetime) -> None:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    ts = _thread_ts(C.THREAD_BOARD, today)
    for i, p in enumerate(pngs):
        client.files_upload_v2(channel=C.SLACK_CHANNEL, file=str(p), filename=p.name,
                               initial_comment=("*%s Knocks Board — %s*" % (C.TEAM, _clock(now))) if i == 0 else None,
                               thread_ts=ts)
    _log("slack: board -> %s thread" % C.THREAD_BOARD)


def _post_gaps(body: str, today: dt.date) -> None:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    ts = _thread_ts(C.THREAD_GAPS, today)
    client.chat_postMessage(channel=C.SLACK_CHANNEL, text=body, thread_ts=ts)
    _log("slack: gaps -> %s thread" % C.THREAD_GAPS)


def _queue_text(kind: str, title: str, today: dt.date, now: dt.datetime, *,
                paths: List[Path] = (), text: str = "") -> None:
    """Hand the text to the poller through the b2b_dispositions manifest path
    (the identity with Messages consent) via the local text outbox. TEXT_ROUTES
    in b2b config route (CAMPAIGN_LABEL, kind) to Carlos's two groups."""
    from automations.b2b_dispositions import text_post as tp
    from automations.b2b_dispositions import run as bd_run
    from automations.day_orchestrator import text_outbox as tob
    spec = {"kind": kind, "title": title, "text": text,
            "by_campaign": {C.CAMPAIGN_LABEL: [str(p) for p in paths]}}
    if not tp.spec_has_routes(spec):
        _log("text: no route for %s -- not queued" % kind)
        return
    out_dir = bd_run.OUTPUT_DIR / today.strftime("%Y-%m-%d")
    mp = tp.write_manifest(spec, out_dir, "%s-%s" % (kind, _clock(now)))
    # Local outbox, NOT the Mini Control sheet: on 2026-10-26 the sheet stopped
    # answering and each enqueue hung ~9 min, so the boards posted 20-40 min
    # late and the texts never left. The poller drains the outbox every loop.
    tob.drop(mp, by="nds_oof", day=today.isoformat())
    _log("text: outbox %s" % mp.name)


def _callout(over: List[Dict], today: dt.date, now: dt.datetime, *, send: bool) -> str:
    """Once an hour: reps over the line with no new credit check. Credit
    checks = the relay's records for carlos-b2batt (his own SaraPlus)."""
    from automations.icd_alerts import gap_callouts as GC
    from automations.icd_alerts import post as P
    key = "nds:carlos"
    st = GC._state().get(key) or {}
    if not GC.due(st, now, C.CALLOUT_EVERY_MIN):
        return ""
    records: Dict[str, int] = {}
    try:
        tab = P._relay_tab()
        for _rownum, row in P._rows_for(today, tab):
            if (row[P.COL_OFFICE] or "").strip().lower() == C.RELAY_OFFICE_KEY:
                records = P._loads(row[P.COL_RECORDS]) or {}
    except Exception as e:  # noqa: BLE001
        _log("call-out: relay records unavailable (%s) -- gaps only" % type(e).__name__)
    prev = (st.get("records") or {}) if st.get("day") == today.isoformat() else dict(records)
    text = GC.line(key, GC.pick_from_gaps(over, records, prev), now)
    if text:
        text = "%s — %s" % (C.TEAM, text)
    if send:
        GC._remember(key, {"day": today.isoformat(),
                           "last_at": now.isoformat(timespec="seconds"),
                           "records": dict(records)})
    return text


# --- the Saturday Mon–Sat board ---------------------------------------------
def _week_due(state: Dict, now: dt.datetime) -> bool:
    if _wd(now) != 5 or (now.hour, now.minute) < C.WEEK_AFTER:
        return False
    return state.get("week_at") != now.date().isoformat()


def weekly_board(saturday: dt.date, *, send: bool,
                 thread_prefix: str = "") -> int:
    """Run weekly_knock_dispositions for the NDS row (it posts the picture
    into Saturday's "NDS Knocks Board" thread), then text the same picture to
    the two chats. Dry by default: renders, posts nothing.

    `thread_prefix` (a hand run, Carlos 2026-10-26: "have last weeks totals
    post on the nds metrics tab. just today"): render only, then put the
    picture as a reply under TODAY's thread whose text starts with that
    prefix (e.g. "NDS Metrics —"). No texts."""
    from automations.weekly_knock_dispositions import run as W
    argv = ["--office", C.WEEK_ROW_KEY, saturday.isoformat()]
    argv += ["--live"] if (send and not thread_prefix) else ["--dry-run"]
    _log("weekly board: weekly_knock_dispositions %s" % " ".join(argv))
    rc = W.main(argv)
    if rc:
        _log("weekly board: module returned %s" % rc)
        return rc
    png = (Path(W.OUT_DIR) / W._slug(C.WEEK_ROW_KEY)
           / ("weekly_knock_dispositions_%s.png" % saturday.isoformat()))
    if not png.exists():
        _log("weekly board: no picture at %s" % png)
        return 1
    monday = saturday - dt.timedelta(days=5)
    title = "%s Knocks Board — Mon–Sat %s–%s" % (
        C.TEAM, monday.strftime("%-m/%-d"), saturday.strftime("%-m/%-d"))
    if thread_prefix:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        today = dt.date.today()
        oldest = dt.datetime.combine(today, dt.time.min).timestamp()
        hist = client.conversations_history(channel=C.SLACK_CHANNEL, oldest=str(oldest), limit=300)
        ts = next((m.get("thread_ts") or m.get("ts") for m in hist.get("messages", [])
                   if (m.get("text") or "").replace("*", "").startswith(thread_prefix)), None)
        if not ts:
            _log("no thread today starting with %r" % thread_prefix)
            return 1
        if not send:
            _log("DRY RUN -- would post %s into thread %s (%r)" % (png, ts, thread_prefix))
            return 0
        client.files_upload_v2(channel=C.SLACK_CHANNEL, file=str(png), filename=png.name,
                               initial_comment="*%s*" % title, thread_ts=ts)
        _log("posted %s into today's %r thread" % (title, thread_prefix))
        return 0
    if send:
        _queue_text(C.KIND_WEEK, title, saturday, dt.datetime.now(), paths=[png])
    else:
        _log("DRY RUN -- would text %s: %s" % (title, png))
    return 0


# --- tick --------------------------------------------------------------------
def tick(*, send: bool, force: bool, board: bool, headless: bool = True,
         no_gaps: bool = False) -> int:
    now = dt.datetime.now()
    today = now.date()
    state = _state()
    if _week_due(state, now):
        # After the 5:30 board on a Saturday: the Mon–Sat combined board. Done
        # here, before the window check, so a missed 5:30 tick still gets it
        # on the next one. Marked only on a real send.
        rc = weekly_board(today, send=send)
        if send and rc == 0:
            state["week_at"] = today.isoformat()
            _save(state)
    if C.CAMPAIGN_ID == "__FILL__":
        _log("CAMPAIGN_ID not set -- run `rerun b2b_dispositions --probe-campaigns` and fill config.py")
        return 1
    if not force and not in_window(now):
        _log("outside the window (%s) -- nothing to do" % now.strftime("%a %H:%M"))
        return 0
    want_board = board or force or _board_due(state, now)
    want_gaps = (not no_gaps) and (force or _due(state, "gaps_at", C.GAPS_EVERY_MIN, now))
    if not want_board and not want_gaps:
        _log("nothing due at %s" % _clock(now))
        return 0
    out_dir = OUTPUT_DIR / today.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    over, rows = pull(today, want_board=want_board, headless=headless)
    if send and want_board and rows:
        # Carlos's NDS crew on the owners' hourly knocks board (Eve
        # 2026-10-29) -- that board runs on Lucy 1 and cannot see this disk.
        from automations.owner_knocks_hourly import config as OK, share
        share.share(OK.CARLOS_NDS_KEY, OK.CARLOS_NAME, today, rows, log=_log)

    body = gaps_text(over, now) if want_gaps else ""
    pngs = render_board(rows, today, now, out_dir) if (want_board and rows) else []
    if want_board and not rows:
        _log("board: no rows on the grid -- not drawn (never post blank)")
    callout = "" if no_gaps else _callout(over, today, now, send=send)

    if not send:
        _log("DRY RUN -- would post:")
        _log("  board: %s" % (", ".join(p.name for p in pngs) or "(none)"))
        _log("  gaps:\n%s" % (body or "(nobody over 15 min)"))
        _log("  call-out: %s" % (callout or "(none)"))
        return 0

    from automations.icd_alerts import post as P
    if pngs:
        _post_board(pngs, today, now)
        _queue_text(C.KIND_BOARD, "%s Knocks Board — %s" % (C.TEAM, _clock(now)), today, now, paths=pngs)
        state["board_at"] = now.isoformat(timespec="seconds")
    if body:
        _post_gaps(body, today)
        _queue_text(C.KIND_GAPS, body.splitlines()[0], today, now, text=body)
    else:
        _log("gaps: nobody over 15 min -- nothing posted")
    if want_gaps:
        state["gaps_at"] = now.isoformat(timespec="seconds")
    if callout:
        P._slack(C.SLACK_CHANNEL, callout)
        _log("slack: call-out posted")
    _save(state)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true", help="post to Slack and queue the texts")
    ap.add_argument("--force", action="store_true", help="ignore the window and the cadences")
    ap.add_argument("--board", action="store_true", help="draw the board this tick")
    ap.add_argument("--week", metavar="SATURDAY",
                    help="run the Mon–Sat combined board for that Saturday "
                         "(YYYY-MM-DD) and exit; --send posts and texts it")
    ap.add_argument("--week-thread", metavar="PREFIX", default="",
                    help="with --week: post the picture into TODAY's thread whose "
                         "text starts with PREFIX, Slack only (no texts)")
    ap.add_argument("--no-gaps", action="store_true",
                    help="board only: no gap list, no call-out (a hand run after hours)")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)
    if args.week:
        return weekly_board(dt.date.fromisoformat(args.week), send=args.send,
                            thread_prefix=args.week_thread)
    return tick(send=args.send, force=args.force, board=args.board,
                headless=not args.headed, no_gaps=args.no_gaps)


if __name__ == "__main__":
    sys.exit(main())
