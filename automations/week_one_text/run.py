"""NDS Week 1 text -- 10:45 AM Mon-Fri to NEW A Players (Carlos 2026-11-19).

    lucy rerun week_one_text                    # today, DRY RUN (renders the picture)
    lucy rerun week_one_text --send             # queue today's text
    lucy rerun week_one_text --send --force     # resend even if already sent today

The picture is the NDS Sales Board's WEEK 1 table, cut at today's day column
(Mon -> Roll Call..Mon, Fri -> Roll Call..Fri). The table is found by its
label, never by row number: the week block moves whenever the board above it
grows, and the table gets longer or shorter with every new start.

Safety: the table follows the board's week cell (B2), which people can point at
an old week. If WEEK 1's dates don't cover today the run fails loudly and sends
nothing -- a stale week in the group chat is worse than no text. No reps in
WEEK 1 = nothing to show, nothing sent (logged).

Same text handoff as daily_plan_text: a b2b_dispositions manifest dropped in
the local text outbox, drained by the Lucy 2 poller through Messages.
Routing: b2b_dispositions.config.TEXT_ROUTES[("NDS WEEK 1", "nds_week_one")].
Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

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


_TITLE = re.compile(r"^week\s*1(?!\d)")
_ANY_TITLE = re.compile(r"^(week\s*\d|terminated)")


def find_week_one(g: List[List[str]], day: dt.date) -> Tuple[int, int, int, int, str]:
    """(title row, last rep row, today's day column, rep count, title text),
    rows/columns 1-based, of the WEEK 1 table in grid `g`.

    Title = the column-B cell starting 'WEEK 1'; the next row is the header
    ('Roll Call', 'Status', 'Day 0', 'Mon' .. 'Sat', ...); reps run until a
    blank or the next table's title. The day column is found by its header
    ('Thu'), so a moved column can't shift the crop. Raises when the table or
    today's column isn't there."""
    col = C.LABEL_COL - 1
    title = None
    for r, row in enumerate(g, start=1):
        if len(row) > col and _TITLE.match(_norm(row[col])):
            title = r
            break
    if title is None:
        raise RuntimeError("no 'WEEK 1' table in column B")
    hdr = g[title] if len(g) > title else []
    if len(hdr) <= col or _norm(hdr[col]) != "roll call":
        raise RuntimeError("row %d under the WEEK 1 title is not the 'Roll Call' header"
                           % (title + 1))
    want = C.DAY_ABBR[day.weekday()].lower()
    day_col = next((i for i, v in enumerate(hdr, start=1) if _norm(v) == want), None)
    if day_col is None:
        raise RuntimeError("the WEEK 1 header has no %r column" % C.DAY_ABBR[day.weekday()])
    last = title + 1
    for r in range(title + 2, len(g) + 1):
        row = g[r - 1]
        v = _norm(row[col]) if len(row) > col else ""
        if not v or _ANY_TITLE.match(v):
            break
        last = r
    return title, last, day_col, last - (title + 1), str(g[title - 1][col])


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


def text_title(day: dt.date) -> str:
    return "NDS Week 1s — %s %d/%d" % (C.DAY_NAMES[day.weekday()], day.month, day.day)


def _load_state() -> dict:
    try:
        return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def already_sent(day: dt.date, state: Optional[dict] = None) -> bool:
    st = _load_state() if state is None else state
    return st.get("sent_day") == day.isoformat()


def remember_sent(day: dt.date, now: dt.datetime) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_PATH.write_text(json.dumps({
        "sent_day": day.isoformat(),
        "sent_at": now.isoformat(timespec="seconds")}, indent=1), encoding="utf-8")


# --------------------------------------------------------------- render -----

def render(day: dt.date, out_path: Path) -> Tuple[Path, int, str]:
    """Shoot WEEK 1 off the live tab, cut at `day`'s column. (png, reps, range)."""
    from automations.pnl_office.run import _token
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.sales_boards import render as R

    ws = open_by_key(C.SHEET_ID).worksheet(C.TAB)
    g = _retry(lambda: ws.get(C.READ_RANGE))
    title, last, day_col, reps, title_text = find_week_one(g, day)
    if not title_covers(title_text, day):
        raise RuntimeError(
            "WEEK 1 is %r, which doesn't cover %s -- the board's week cell (B2) "
            "is on another week; not sending a stale table" % (title_text.strip(), day))
    rng = "%s%d:%s%d" % (_letter(C.LABEL_COL), title, _letter(day_col), last)
    if reps == 0:
        return out_path, 0, rng
    img = R.export(C.SHEET_ID, ws.id, rng, _token())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path, reps, rng


# ---------------------------------------------------------------- send -----

def queue_picture(png: Path, day: dt.date, now: dt.datetime) -> bool:
    """Same handoff as daily_plan_text: manifest -> local outbox -> poller."""
    from automations.b2b_dispositions import text_post as tp
    from automations.b2b_dispositions import run as bd_run
    from automations.day_orchestrator import text_outbox as tob
    spec = {"kind": C.KIND, "title": text_title(day),
            "by_campaign": {C.CAMPAIGN_LABEL: [str(png)]}}
    if not tp.spec_has_routes(spec):
        _log("no route for %s/%s in TEXT_ROUTES -- not queued" % (C.CAMPAIGN_LABEL, C.KIND))
        return False
    out_dir = bd_run.OUTPUT_DIR / day.strftime("%Y-%m-%d")
    mp = tp.write_manifest(spec, out_dir, "%s-%s" % (C.KIND, now.strftime("%H%M")))
    tob.drop(mp, by="week_one_text", day=day.isoformat())
    _log("text: outbox %s" % mp.name)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--send", action="store_true", help="queue the text (default: dry run)")
    ap.add_argument("--force", action="store_true", help="send even if already sent today")
    ap.add_argument("--out", help="where to save the picture (default: the text output folder)")
    a = ap.parse_args(argv)

    now = dt.datetime.now()
    day = dt.date.fromisoformat(a.date) if a.date else now.date()
    name = C.DAY_NAMES[day.weekday()]
    if day.weekday() not in C.WEEKDAYS:
        _log("%s %s: Monday-Friday only -- nothing to send" % (name, day.isoformat()))
        return 0
    if a.send and already_sent(day) and not a.force:
        _log("already sent today -- not sending again (use --force)")
        return 0
    if a.out:
        png = Path(a.out)
    else:
        from automations.b2b_dispositions import run as bd_run
        png = bd_run.OUTPUT_DIR / day.strftime("%Y-%m-%d") / ("nds_week_one_%s.png" % day.isoformat())
    png, reps, rng = render(day, png)
    if reps == 0:
        _log("%s %s: WEEK 1 has no reps (%s) -- nothing to send" % (name, day.isoformat(), rng))
        return 0
    _log("%s %s: WEEK 1 %s, %d rep(s) -> %s" % (name, day.isoformat(), rng, reps, png))
    if not a.send:
        _log("dry run -- pass --send to queue it")
        return 0
    if queue_picture(png, day, now):
        remember_sent(day, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
