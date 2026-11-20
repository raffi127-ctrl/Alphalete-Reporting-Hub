"""Week-table texts -- AT&T (NDS) + Verizon Sales Boards to NEW A Players,
Monday-Friday (Carlos 2026-11-19). See config.py for his words.

    lucy rerun week_one_text                        # DRY RUN: 10:45 shot, both boards
    lucy rerun week_one_text --shot weeks           # DRY RUN: the 11:30 shot
    lucy rerun week_one_text --send                 # queue the 10:45 texts (once per day)
    lucy rerun week_one_text --shot weeks --send    # queue the 11:30 texts
    lucy rerun week_one_text --shot all --dm U046G04P5LG   # Slack DM preview, texts nothing
    ... --board nds|verizon   one board only;   --force   resend today's

Shots: "week1" = the WEEK 1 table, title row to last rep, Roll Call across to
TODAY's day column; "weeks" = WEEK 1's title down to WEEK 4's last rep, the
whole width (through Trainer). Tables are found by their labels in column B
(never by row number: the block moves when the board above it grows, and
each table is as tall as its reps).

Safety: the tables follow the boards' week cell (NDS B2; Verizon's B2 mirrors
it), which people can point at an old week. If WEEK 1's dates don't cover
today, that board FAILS and sends nothing -- a stale week in the group chat is
worse than no text. A board with nobody in the shot sends nothing (logged).
Each board is its own text, so one board failing never blocks the other.

Same text handoff as daily_plan_text: a b2b_dispositions manifest in the local
text outbox, drained by the Lucy 2 poller through Messages. Routes:
config.ROUTES -> b2b_dispositions.config.TEXT_ROUTES. Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.week_one_text import config as C


def _log(msg: str) -> None:
    print("[week1] " + msg, flush=True)


# ---------------------------------------------------------------- pure -----

def _norm(v) -> str:
    return " ".join(str(v or "").split()).lower()


def _letter(c: int) -> str:
    out = ""
    while c:
        c, r = divmod(c - 1, 26)
        out = chr(65 + r) + out
    return out


_ANY_TITLE = re.compile(r"^(week\s*(\d+)|terminated)")


def parse_tables(g: List[List[str]]) -> List[Dict]:
    """Every week table in grid `g`, top to bottom: {num (1..n, or 0 for
    TERMINATED), title, last (1-based rows), reps, text}. A table = a column-B
    title ('WEEK 1 · ...' / 'TERMINATED · ...'), the 'Roll Call' header under
    it, then reps down to a blank or the next title."""
    col = C.LABEL_COL - 1
    out = []
    r = 1
    while r <= len(g):
        row = g[r - 1]
        v = _norm(row[col]) if len(row) > col else ""
        m = _ANY_TITLE.match(v)
        hdr = g[r] if len(g) > r else []
        if m and len(hdr) > col and _norm(hdr[col]) == "roll call":
            num = int(m.group(2)) if m.group(2) else 0
            last = r + 1
            k = r + 2
            while k <= len(g):
                rk = g[k - 1]
                vk = _norm(rk[col]) if len(rk) > col else ""
                if not vk or _ANY_TITLE.match(vk):
                    break
                last = k
                k += 1
            out.append({"num": num, "title": r, "last": last,
                        "reps": last - (r + 1), "text": str(row[col])})
            r = last + 1
        else:
            r += 1
    return out


def _week_one(tables: List[Dict]) -> Dict:
    t = next((t for t in tables if t["num"] == 1), None)
    if t is None:
        raise RuntimeError("no 'WEEK 1' table in column B")
    return t


def find_week_one(g: List[List[str]], day: dt.date) -> Tuple[int, int, int, int, str]:
    """(title row, last rep row, today's day column, rep count, title text) of
    the WEEK 1 table -- the 10:45 crop. The day column is found by its header
    ('Thu'), so a moved column can't shift the crop."""
    t = _week_one(parse_tables(g))
    hdr = g[t["title"]]
    want = C.DAY_ABBR[day.weekday()].lower()
    day_col = next((i for i, v in enumerate(hdr, start=1) if _norm(v) == want), None)
    if day_col is None:
        raise RuntimeError("the WEEK 1 header has no %r column" % C.DAY_ABBR[day.weekday()])
    return t["title"], t["last"], day_col, t["reps"], t["text"]


def find_weeks(g: List[List[str]], upto: int = C.WEEKS_SHOWN) -> Tuple[int, int, int, int, str]:
    """(WEEK 1 title row, last rep row of the last WEEK n<=upto table, last
    header column, reps across them, WEEK 1 title text) -- the 11:30 crop.
    Stops before TERMINATED and anything after it."""
    tables = parse_tables(g)
    w1 = _week_one(tables)
    weeks = []
    for t in tables:
        if t["title"] < w1["title"]:
            continue
        if t["num"] == 0 or t["num"] > upto:
            break
        weeks.append(t)
    hdr = g[w1["title"]]
    last_col = max(i for i, v in enumerate(hdr, start=1) if _norm(v))
    return (w1["title"], weeks[-1]["last"], last_col,
            sum(t["reps"] for t in weeks), w1["text"])


_RANGE = re.compile(r"(\d{1,2})/(\d{1,2})\s*[–—-]\s*(\d{1,2})/(\d{1,2})")


def title_covers(title_text: str, day: dt.date) -> bool:
    """True when the title's 'm/d – m/d' week (no year) contains `day`.
    Tries the years around `day`, so a Dec->Jan week still matches."""
    m = _RANGE.search(title_text or "")
    if not m:
        return False
    m1, d1, m2, d2 = (int(x) for x in m.groups())
    for y in (day.year - 1, day.year, day.year + 1):
        try:
            lo = dt.date(y, m1, d1)
            hi = dt.date(y + (1 if m2 < m1 else 0), m2, d2)
        except ValueError:
            continue
        if lo <= day <= hi:
            return True
    return False


def text_title(board: str, shot: str, day: dt.date) -> str:
    what = "Week 1s" if shot == "week1" else "Weeks 1–4"
    return "%s %s — %s %d/%d" % (C.BOARDS[board]["label"], what,
                                     C.DAY_NAMES[day.weekday()], day.month, day.day)


def _key(shot: str, board: str) -> str:
    return "%s:%s" % (shot, board)


def _load_state() -> dict:
    try:
        return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def already_sent(day: dt.date, shot: str = "week1", board: str = "nds",
                 state: Optional[dict] = None) -> bool:
    st = _load_state() if state is None else state
    if st.get("day") == day.isoformat():
        return _key(shot, board) in (st.get("sent") or [])
    # the first version (11/19) kept only {"sent_day": ...} for the NDS week 1 text
    return st.get("sent_day") == day.isoformat() and (shot, board) == ("week1", "nds")


def remember_sent(day: dt.date, shot: str, board: str, now: dt.datetime) -> None:
    st = _load_state()
    sent = list(st.get("sent") or []) if st.get("day") == day.isoformat() else []
    if _key(shot, board) not in sent:
        sent.append(_key(shot, board))
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_PATH.write_text(json.dumps({
        "day": day.isoformat(), "sent": sent,
        "last_sent_at": now.isoformat(timespec="seconds")}, indent=1), encoding="utf-8")


@contextlib.contextmanager
def _send_lock():
    """One sender at a time (a launchd tick and a hand rerun could overlap):
    the already-sent check and the send happen under this lock."""
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(str(C.STATE_PATH) + ".lock", "w")
    try:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:   # no flock off macOS/Linux; nothing else sends there
            pass
        yield
    finally:
        f.close()


# --------------------------------------------------------------- render -----

def render(board: str, shot: str, day: dt.date, out_path: Path) -> Tuple[Path, int, str]:
    """Shoot one board's shot off the live tab. (png, reps, range)."""
    from automations.pnl_office.run import _token
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.sales_boards import render as R

    ws = open_by_key(C.SHEET_ID).worksheet(C.BOARDS[board]["tab"])
    g = _retry(lambda: ws.get(C.READ_RANGE))
    if shot == "week1":
        top, last, last_col, reps, title_text = find_week_one(g, day)
    else:
        top, last, last_col, reps, title_text = find_weeks(g)
    if not title_covers(title_text, day):
        raise RuntimeError(
            "WEEK 1 is %r, which doesn't cover %s -- the board's week cell (B2) "
            "is on another week; not sending a stale table" % (title_text.strip(), day))
    rng = "%s%d:%s%d" % (_letter(C.LABEL_COL), top, _letter(last_col), last)
    if reps == 0:
        return out_path, 0, rng
    img = R.export(C.SHEET_ID, ws.id, rng, _token())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path, reps, rng


# ---------------------------------------------------------------- send -----

def queue_picture(png: Path, board: str, shot: str, day: dt.date, now: dt.datetime) -> bool:
    """Same handoff as daily_plan_text: manifest -> local outbox -> poller."""
    from automations.b2b_dispositions import text_post as tp
    from automations.b2b_dispositions import run as bd_run
    from automations.day_orchestrator import text_outbox as tob
    campaign, kind = C.ROUTES[(board, shot)]
    spec = {"kind": kind, "title": text_title(board, shot, day),
            "by_campaign": {campaign: [str(png)]}}
    if not tp.spec_has_routes(spec):
        _log("no route for %s/%s in TEXT_ROUTES -- not queued" % (campaign, kind))
        return False
    out_dir = bd_run.OUTPUT_DIR / day.strftime("%Y-%m-%d")
    mp = tp.write_manifest(spec, out_dir, "%s-%s" % (kind, now.strftime("%H%M")))
    tob.drop(mp, by="week_one_text", day=day.isoformat())
    _log("%s %s: text queued (outbox %s)" % (board, shot, mp.name))
    return True


def dm_preview(png: Path, board: str, shot: str, day: dt.date, user: str) -> None:
    from automations.shared import slack_metrics_post as smp
    hh, mm = C.SEND_TIMES[shot]
    when = "%d:%02d AM" % (hh, mm) if hh < 12 else "%d:%02d PM" % (hh - 12 if hh > 12 else 12, mm)
    smp.dm_user_with_file(
        png, user=user, file_name=png.name,
        comment="PREVIEW (not texted) — the %s text to NEW A Players, Mon–Fri: *%s*"
                % (when, text_title(board, shot, day)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shot", choices=C.SHOTS + ["all"], default="week1",
                    help="week1 = the 10:45 WEEK 1 cut at today; weeks = the 11:30 WEEK 1-4")
    ap.add_argument("--board", choices=C.BOARD_ORDER + ["all"], default="all")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--send", action="store_true", help="queue the text(s) (default: dry run)")
    ap.add_argument("--force", action="store_true", help="send even if already sent today")
    ap.add_argument("--dm", default=None, metavar="U...",
                    help="Slack-DM the pictures as a PREVIEW to this user; texts nothing")
    ap.add_argument("--out-dir", help="where to save the pictures (default: the text output folder)")
    a = ap.parse_args(argv)
    if a.dm and a.send:
        ap.error("--dm is a preview; it can't be combined with --send")

    now = dt.datetime.now()
    day = dt.date.fromisoformat(a.date) if a.date else now.date()
    name = C.DAY_NAMES[day.weekday()]
    allowed = C.WEEKDAYS if not a.dm else C.WEEKDAYS + [5]   # a preview may run on a Saturday
    if day.weekday() not in allowed:
        _log("%s %s: Monday-Friday only -- nothing to do" % (name, day.isoformat()))
        return 0
    shots = C.SHOTS if a.shot == "all" else [a.shot]
    boards = C.BOARD_ORDER if a.board == "all" else [a.board]
    if a.out_dir:
        out_dir = Path(a.out_dir)
    else:
        from automations.b2b_dispositions import run as bd_run
        out_dir = bd_run.OUTPUT_DIR / day.strftime("%Y-%m-%d")

    lock = _send_lock() if a.send else contextlib.nullcontext()
    errors = 0
    with lock:
        for shot in shots:
            for board in boards:
                tag = "%s %s" % (board, shot)
                if a.send and already_sent(day, shot, board) and not a.force:
                    _log("%s: already sent today -- not again (use --force)" % tag)
                    continue
                png = out_dir / ("%s_%s_%s.png" % (board, shot, day.isoformat()))
                try:
                    png, reps, rng = render(board, shot, day, png)
                except Exception as e:  # noqa: BLE001 -- one board never blocks the other
                    errors += 1
                    _log("%s: FAILED -- %s: %s" % (tag, type(e).__name__, str(e)[:300]))
                    continue
                if reps == 0:
                    _log("%s %s %s: nobody in the shot (%s) -- nothing to send"
                         % (name, day.isoformat(), tag, rng))
                    continue
                _log("%s %s %s: %s, %d rep(s) -> %s" % (name, day.isoformat(), tag, rng, reps, png))
                if a.dm:
                    try:
                        dm_preview(png, board, shot, day, a.dm)
                        _log("%s: preview DM'd to %s" % (tag, a.dm))
                    except Exception as e:  # noqa: BLE001
                        errors += 1
                        _log("%s: DM FAILED -- %s: %s" % (tag, type(e).__name__, str(e)[:300]))
                    continue
                if not a.send:
                    _log("%s: dry run -- pass --send to queue it" % tag)
                    continue
                if queue_picture(png, board, shot, day, now):
                    remember_sent(day, shot, board, now)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
