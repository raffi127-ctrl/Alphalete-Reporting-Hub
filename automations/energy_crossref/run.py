"""Energy Cross-reference — the morning check Evelyn posts by hand today.

Every Energy rep owes ONE Google-Form ('webform') submission per sale, and they
don't get paid on a sale whose form was never filled. So each morning yesterday's
sales are counted three ways — the running board posted in #alphalete-sales, the
'EN' column of the Alphalete SALES BOARD, and the webform responses — and whoever
is short gets tagged in the day's ':wolf: Alphalete Production' thread, together
with Rafael Hidalgo and Dylan Twaddle.

WHY THREE COUNTS AND NOT TWO. The first two are counts of the same thing and
normally agree; when they don't, each rep is asked for the HIGHER of the two, so
a rep is never let off because one source lagged. The webform is the count being
audited. A rep who filed the SAME sale twice is not covered twice — see
webform.py, which is where the duplicate check lives.

    python -m automations.energy_crossref.run                 # preview yesterday
    python -m automations.energy_crossref.run --date 2026-08-13
    python -m automations.energy_crossref.run --images        # + render the PNGs
    python -m automations.energy_crossref.run --post          # render AND post
    python -m automations.energy_crossref.run --post --channel C…  # a sandbox channel

Exit 0 the check ran and the post went out (or previewed clean). Exit 75 the day
is INCOMPLETE — no Energy board was posted, a name matched nobody, or a rep could
not be resolved to a Slack account — and NOTHING was posted, because a post that
silently drops the person who owes the form is worse than no post.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.energy_crossref import crossref as X
from automations.energy_crossref import message as M
from automations.energy_crossref import roster as R_
from automations.energy_crossref import webform as W
from automations.energy_slack_fill import run as EF
from automations.energy_slack_fill.parse import TZ

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "energy_crossref"


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def gather(day: dt.date, *, sheet_id: str, form_sheet_id: str) -> X.Result:
    """Read all three sources for `day` and line them up."""
    from automations.alphalete_production.capture import find_week_tab
    from automations.recruiting_report.fill import open_by_key

    lo = dt.datetime.combine(day, dt.time(0), tzinfo=TZ)
    hi = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(12), tzinfo=TZ)
    _log(f"reading {EF.CHANNEL[0]}  {lo.date()} .. {hi.date()}")
    blocks = EF.fetch_blocks(lo, hi)
    _log(f"  {len(blocks)} Energy board post(s) in the window")

    ss = open_by_key(sheet_id)
    ws = find_week_tab(ss, day)
    grid = ws.get_all_values()
    rows = EF.roster(grid)
    _log(f"sheet: {ss.title!r}  tab: {ws.title!r}  "
         f"({len(rows)} rep(s) on Campaign = Energy)")

    forms_all = W.load(form_sheet_id)
    forms, warn = W.for_day(forms_all, day)
    _log(f"webform: {len(forms_all)} response(s) on the tab, "
         f"{sum(f.count for f in forms.values())} for {day} "
         f"from {len(forms)} rep(s)")

    res = X.build(day, blocks, grid, rows, forms, warn)
    res.board_tab = ws.title
    return res


def report(res: X.Result) -> None:
    """The rep-by-rep table — the audit trail for the numbers in the post."""
    _log("")
    _log(f"--- Energy cross-reference — {res.day:%A} {res.day.month}/{res.day.day} ---")
    if res.post_time:
        _log(f"  Slack source: last board of the night, posted {res.post_time}")
    _log(f"  {'rep':<34}{'slack':>6}{'board':>7}{'forms':>7}{'missing':>9}")
    for r in res.reps:
        if not (r.slack or r.board or r.forms):
            continue
        flag = "  <-- owes" if r.missing else ("  (extra form)" if r.extra else "")
        _log(f"  {r.board_name:<34}{r.slack:>6}{r.board:>7}{r.forms:>7}"
             f"{r.missing:>9}{flag}")
    _log(f"  {'TOTAL':<34}{res.slack_total:>6}{res.board_total:>7}"
         f"{res.forms_total:>7}{res.missing_total:>9}")
    if res.tally is not None:
        _log(f"  the office's own tally line: {res.tally}/{res.goal or '?'}")
    for name, why in res.dupes:
        _log(f"  !! DUPLICATE  {name}: {why}")
    for w in res.warnings:
        _log(f"  !! {w}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="sales day (YYYY-MM-DD); default yesterday")
    ap.add_argument("--post", action="store_true",
                    help="render the images and post to the day's thread")
    ap.add_argument("--images", action="store_true",
                    help="render the images but post nothing")
    ap.add_argument("--channel",
                    help="post to this channel id instead of #alphalete-sales "
                         "(a sandbox channel while testing)")
    ap.add_argument("--dm", metavar="USER",
                    help="DM the whole thing (text + both images) to one person "
                         "instead of posting it — the sandbox. Id, email or name")
    ap.add_argument("--sheet-id", default=EF.SHEET_ID,
                    help="the Sales Board workbook (point at a sandbox copy)")
    ap.add_argument("--form-sheet-id", default=W.SHEET_ID,
                    help="the Base Power Energy webform workbook")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    a = ap.parse_args(argv)

    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.datetime.now(TZ).date() - dt.timedelta(days=1))
    res = gather(day, sheet_id=a.sheet_id, form_sheet_id=a.form_sheet_id)
    report(res)

    # Resolving the tags is part of the CHECK, not of posting — a rep with no
    # Slack account has to show up in a preview too, not only at post time.
    from automations.shared.slack_metrics_post import _client
    client = _client()
    tags = R_.resolve(client, M.tag_names(res))

    _log("")
    _log("--- the post ---")
    _log(M.build(res, tags))
    _log("")
    for name, uid in tags:
        _log(f"  tag  {name:<34}{'<@' + uid + '>' if uid else 'NO SLACK ACCOUNT'}")
    untagged = [n for n, u in tags if not u]
    for n in untagged:
        _log(f"  !! {n} has no Slack account we can find — the post NAMES them "
             "in bold instead of tagging them")
        _log("     fix: add their id to IDS in energy_crossref/roster.py")

    # No sales at all from either source is the one thing worth holding on: it
    # means the evening board never posted AND the Sales Board is still empty,
    # so there is nothing to cross-reference and a '0 sales' post would read as
    # a real zero day. (An actual zero day still has an Energy block posted.)
    if res.slack_total == 0 and res.board_total == 0:
        _log("")
        _log(f"HOLDING — no Energy sales in EITHER source for {res.day}. "
             "Nothing posted; re-run once the evening board is up.")
        return 75

    if not (a.post or a.images or a.dm):
        _log("")
        _log("PREVIEW — re-run with --post to render the images and post it")
        return 0

    from automations.energy_crossref import render as R
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _log("")
    board_png = R.energy_board_png(day, out_dir)
    _log(f"rendered {board_png}")
    form_png = R.webform_png(day, out_dir, sheet_id=a.form_sheet_id)
    _log(f"rendered {form_png}" if form_png else
         "no webform rows for the day — posting the board image only")
    images = [p for p in (board_png, form_png) if p]

    from automations.energy_crossref import post as PO
    if a.dm:
        out = PO.dm(client, a.dm, M.build(res, tags), images)
        _log(f"DMed the preview to {out['dm_to']} ({len(images)} image(s)) — "
             "NOTHING posted to the channel")
        return 75 if (untagged or res.warnings) else 0

    if not a.post:
        _log("")
        _log("IMAGES ONLY — re-run with --post to put it in the thread")
        return 0

    out = PO.post(client, res, M.build(res, tags), images, channel=a.channel)
    _log(f"posted to {out['channel']} in thread {out['thread_ts']} "
         f"({len(images)} image(s))")
    # 75 = the boards' hold code. Here it means the post WENT OUT but the day
    # wasn't clean — a rep who owes a form couldn't be tagged, a Slack line
    # matched nobody, the tally didn't close. Everything sure still posted.
    return 75 if (untagged or res.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
