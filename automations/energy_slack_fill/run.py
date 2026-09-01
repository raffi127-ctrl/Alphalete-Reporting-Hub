"""Energy sales -> the Alphalete SALES BOARD 2025 'EN' column, from Slack.

The Energy reps (col CH = 'Energy') are hand-typed onto the board every morning
before the Daily Production post goes out. Nothing feeds them — the only record
of an Energy sale is the running board the office re-posts all evening in
#alphalete-sales, whose last message of the night is the finished day
(parse.py has the shape and the traps). This reads that message and fills the
EN cell for each rep, so the fill is done before alphalete_production renders
the board at ~4am.

THE FILL ONLY EVER RAISES A NUMBER, same rule as the Vantura board (Megan
2026-07-23): a sale that reached the board by some other route stands, and a
rep is written only when Slack says MORE than the cell already holds. Re-running
a day is safe by construction and the number can never regress.

WHAT IS SURE GETS FILLED; ONLY THE DOUBT IS LEFT BLANK (Eve 2026-08-07). The
doubt is always the same question — WHICH REP is this line? So:
  * a name that matches no rep, or matches TWO — that ONE LINE is skipped and
    named in the log. Never guessed, and never a reason to drop the other reps
    on the post, who are not in doubt.
  * the "N/goal" tally disagreeing with our count, or never being posted at
    all, means the READ may be off, not that anyone is unidentified: it fills
    and shouts. A human re-checks the board every morning before it goes out.
  * no Energy block posted for the day is the one thing that writes nothing —
    there is nothing to read.
Exit 75 (the boards' hold code) now means THIS DAY IS INCOMPLETE — no post, a
skipped rep, or a tally that didn't line up — whether or not part of it was
written. Re-running only ever raises a number, so a retry after an alias is
added just fills in the rest. Exit 0 means the day went in whole and checked.

This used to hold the ENTIRE day on any of those, on the theory that a
half-filled board reads like real zeros. It cost more than it caught: one
unplaceable nickname ("Zoey", "Charlie") was throwing away every other rep's
sales for that day.

  python -m automations.energy_slack_fill.run                 # preview yesterday
  python -m automations.energy_slack_fill.run --date 2026-08-04
  python -m automations.energy_slack_fill.run --week          # Mon..yesterday
  python -m automations.energy_slack_fill.run --apply         # write
  python -m automations.energy_slack_fill.run --sheet-id <id> # a sandbox copy
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import ssl
import sys
from pathlib import Path

from automations.energy_slack_fill import parse as P
from automations.energy_slack_fill.parse import TZ

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CHANNEL = ("#alphalete-sales", "C068PH3RFSM")
PROD_SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"
SHEET_ID = os.environ.get("ENERGY_FILL_SHEET_ID", PROD_SHEET_ID)

CAMPAIGN = "Energy"                 # the col-CH value that selects the roster
DAY_ROW, WEEKDAY_ROW, SUB_ROW = 1, 2, 3
DAY_LABELS = {"MON": 0, "TUES": 1, "WED": 2, "THU": 3,
              "FRI": 4, "SAT": 5, "SUN": 6}
METRIC = "EN"                       # the per-day sub-column Energy sales land in


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def _md(d: dt.date) -> str:
    """'Thursday 8/6' — built by hand; %-m is glibc-only and this runs on
    Windows too."""
    return f"{d.strftime('%A')} {d.month}/{d.day}"


# --------------------------------------------------------------- slack ---
def fetch_blocks(lo: dt.datetime, hi: dt.datetime) -> list[P.EnergyBlock]:
    """Every Energy board posted in the window, oldest first."""
    import certifi
    from slack_sdk import WebClient
    from automations.shared.slack_metrics_post import _load_token

    client = WebClient(token=_load_token(),
                       ssl=ssl.create_default_context(cafile=certifi.where()))
    raw, cursor = [], None
    while True:
        resp = client.conversations_history(
            channel=CHANNEL[1], oldest=str(lo.timestamp()),
            latest=str(hi.timestamp()), limit=200, cursor=cursor)
        raw.extend(resp["messages"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    blocks = []
    for m in raw:
        when = dt.datetime.fromtimestamp(float(m["ts"]), tz=dt.timezone.utc)
        # Slack escapes &, < and > in message text.
        blk = P.read_block(m["ts"], when, m.get("user", ""),
                           html.unescape(m.get("text", "")))
        if blk:
            blocks.append(blk)
    blocks.sort(key=lambda b: float(b.ts))
    return blocks


# --------------------------------------------------------------- sheet ---
def _cell(g, r, c):
    return g[r - 1][c - 1] if r - 1 < len(g) and c - 1 < len(g[r - 1]) else ""


def _norm(name: str) -> str:
    """Lowercase, drop the board's '(Wk 2)' / '(NC)' tenure tags, punctuation
    and the Sr/Jr suffixes."""
    n = re.sub(r"\([^)]*\)", " ", str(name).lower())
    n = re.sub(r"[^a-z ]", " ", n)
    n = re.sub(r"\b(sr|jr|iii|ii)\b", " ", n)
    return " ".join(n.split())


def name_col(g) -> int:
    """The rep-name column: the one right of the '#' header in row 3. The
    header above the names is the week's date range, not a label, so '#' is
    what there is to anchor on."""
    for c in range(1, 12):
        if _cell(g, SUB_ROW, c).strip() == "#":
            return c + 1
    raise SystemExit("no '#' header in row 3 — the tab layout changed")


def campaign_col(g) -> int:
    """The 'Campaign' column, found by its row-1 header (col CH today)."""
    for c in range(1, 120):
        if _cell(g, DAY_ROW, c).strip().lower() == "campaign":
            return c
    raise SystemExit("no 'Campaign' header in row 1 — the tab layout changed")


def metric_col(g, day: dt.date) -> int | None:
    """The EN column of `day`'s block: find the weekday's group in row 1, then
    its 'EN' sub-header in row 3. Never a hardcoded index — the blocks move."""
    want = DAY_LABELS
    for c in range(1, 120):
        lab = _cell(g, DAY_ROW, c).strip().upper()
        if lab in want and want[lab] == day.weekday():
            for cc in range(c, c + 10):
                if _cell(g, SUB_ROW, cc).strip().upper() == METRIC:
                    return cc
            return None
    return None


def last_rep_row(g) -> int:
    """Last row of the rep list — the leaderboard/summary blocks below it are
    formula-driven and must never be written."""
    for r in range(SUB_ROW + 1, len(g) + 1):
        if _cell(g, r, 3).strip().upper() == "TOTALS":
            return r - 1
    return len(g)


def roster(g) -> dict[int, str]:
    """{row: board name} for every rep whose Campaign is Energy."""
    nc, cc, last = name_col(g), campaign_col(g), last_rep_row(g)
    return {r: _cell(g, r, nc).strip()
            for r in range(SUB_ROW + 1, last + 1)
            if _cell(g, r, cc).strip().lower() == CAMPAIGN.lower()
            and _cell(g, r, nc).strip()}


def week_of(g, day: dt.date) -> bool:
    """Does this tab's week actually contain `day`? The tab is picked by name,
    so this is a belt-and-braces read of the C3 date range ('WE 8/3- 8/9')."""
    hdr = _cell(g, SUB_ROW, 3)
    nums = re.findall(r"(\d{1,2})\s*/\s*(\d{1,2})", hdr)
    if len(nums) < 2:
        return True                                  # no range to check
    m1, d1 = int(nums[0][0]), int(nums[0][1])
    m2, d2 = int(nums[1][0]), int(nums[1][1])
    lo = dt.date(day.year, m1, d1)
    hi = dt.date(day.year if m2 >= m1 else day.year + 1, m2, d2)
    return lo <= day <= hi


# --------------------------------------------------------------- match ---
def match_rep(slack_name: str, rows: dict[int, str]) -> tuple[int | None, str]:
    """A name off an Energy line -> a board row. (row, note); row None = no
    single confident match, and the note says which of the two problems it is.

    Two names on one line ("Pranish/ Abdallah") is one sale credited to whoever
    is on the roster; if BOTH are, that's a real question for a human and it
    comes back ambiguous rather than guessed.
    """
    norm_rows = {r: _norm(n) for r, n in rows.items()}
    hits: dict[int, str] = {}
    parts = [p.strip() for p in re.split(r"[/&+]| and ", slack_name) if p.strip()]
    for part in parts or [slack_name]:
        key = part.strip().lower()
        if key in P.ALIASES:
            key = _norm(P.ALIASES[key])
        else:
            key = _norm(part)
        if not key:
            continue
        exact = [r for r, n in norm_rows.items() if n == key]
        if len(exact) == 1:
            hits[exact[0]] = part
            continue
        if len(exact) > 1:
            return None, f"{part!r} matches {len(exact)} reps on the roster"
        toks = set(key.split())
        tok = [r for r, n in norm_rows.items() if toks & set(n.split())]
        if len(tok) == 1:
            hits[tok[0]] = part
        elif len(tok) > 1:
            names = ", ".join(sorted(rows[r] for r in tok))
            return None, f"{part!r} could be any of: {names}"
    if len(hits) == 1:
        return next(iter(hits)), ""
    if not hits:
        return None, f"{slack_name!r} is on no Energy row of the board"
    names = ", ".join(sorted(rows[r] for r in hits))
    return None, (f"{slack_name!r} names TWO reps who are both on the roster "
                  f"({names}) — can't tell who gets the sale")


# -------------------------------------------------------------- report ---
def run_day(blocks, ws, g, day: dt.date, rows: dict[int, str]):
    """Read one day, print it against the board.

    -> (write plan, day is incomplete, lines left off). The plan holds every
    rep we could place; `skipped` is the doubt, and it never blocks the plan.
    """
    from gspread.utils import rowcol_to_a1

    _log("")
    _log(f"--- Energy — {_md(day)} ---")
    blk = P.last_block_for(blocks, day)
    if blk is None:
        _log(f"  NO Energy board posted in {CHANNEL[0]} for {_md(day)} — "
             "nothing to read, nothing written")
        return None, True, []

    when = blk.when.astimezone(TZ)
    _log(f"  source: last board of the night, posted {when.strftime('%H:%M')} "
         f"({sum(1 for b in blocks if b.sales_day == day)} re-post(s) that day)")
    col = metric_col(g, day)
    if col is None:
        _log(f"  no '{METRIC}' column under {day.strftime('%A')} on this tab — "
             "nowhere to write, holding")
        return None, True, []

    incomplete, plan, seen, skipped = False, [], [], []
    for line in blk.lines:
        row, note = match_rep(line.name, rows)
        if row is None:
            # This line only. Whoever else is on the post is not in doubt and
            # still gets filled — see the module docstring.
            _log(f"  !! {line.raw!r} — {note}")
            _log(f"     NOT FILLED ({line.count} sale(s) left off). Add them to "
                 "the board's Energy rows, or to ALIASES in parse.py if it's a "
                 "spelling, then re-run the day")
            skipped.append((line.raw, line.count, note))
            incomplete = True
            continue
        seen.append(row)
        cur = str(_cell(g, row, col)).strip()
        a1 = rowcol_to_a1(row, col)
        if cur.isdigit() and line.count <= int(cur):
            tail = "" if cur == str(line.count) else \
                f"   <- board has {cur}, KEPT (we only raise)"
            _log(f"  {rows[row]:<32} {line.count:>2}  {a1}{tail}")
        else:
            marker = f"  (replaces {cur!r})" if cur and not cur.isdigit() else ""
            _log(f"  {rows[row]:<32} {line.count:>2}  {a1}  "
                 f"{cur or '(blank)'} -> {line.count}{marker}")
            plan.append((rows[row], a1, cur or "(blank)", line.count))
        for f in line.flags:
            _log(f"      ! {f}")

    total = blk.total
    _log(f"  {'TOTAL':<32} {total:>2}"
         + (f"   ({sum(c for _r, c, _n in skipped)} of them NOT filled)"
            if skipped else ""))

    # The office's own tally line — the ONLY independent check on the read, and
    # the thing that catches a line whose sale emoji we couldn't count. Both
    # failures below FILL ANYWAY and shout (Eve 2026-08-07): they say the count
    # may be off, not that a rep is unidentified, and a human re-checks the
    # board every morning before it goes out. Revisit if that check ever stops.
    if blk.tally is None:
        _log(f"  !! the block never posted its 'N/goal' tally line — nothing "
             f"confirms these {total} sale(s). FILLING ANYWAY, eyeball this day")
        _log("     ask the office to close the Energy block with made/goal "
             "(e.g. '3/15') so there is something to check against")
        incomplete = True
    elif blk.tally != total:
        _log(f"  !! the board's own tally says {blk.tally}/{blk.goal or '?'} but "
             f"the lines add to {total} — one of the two is wrong. FILLING "
             "ANYWAY, eyeball this day")
        incomplete = True
    else:
        _log(f"  tally line {blk.tally}/{blk.goal or '?'} — matches")

    # The other direction: a rep the board credits who isn't on tonight's post.
    # Sales do reach the board by other routes, so these STAND — listed only so
    # the day can be traced.
    kept = [rows[r] for r in sorted(rows)
            if r not in seen and str(_cell(g, r, col)).strip().isdigit()
            and int(str(_cell(g, r, col)).strip()) > 0]
    if kept:
        _log(f"  kept as-is (on the board, not on the post): {', '.join(kept)}")
    return plan, incomplete, skipped


def main(argv=None) -> int:
    # STOOD DOWN 2026-09-01 — Base Power Energy ended (Rafael), and the column
    # this fills stopped existing on 2026-08-31 when the per-day 'EN' sub-header
    # was renamed to 'TK'. Without the marker every run takes the "nowhere to
    # write, holding" path and returns 75, i.e. closes as FAILED every morning
    # for a report with nothing to do. Delete DISABLED to bring it back.
    marker = Path(__file__).resolve().parent / "DISABLED"
    if marker.exists():
        _log("[energy_slack_fill] DISABLED — the Base Power Energy program ended "
             "2026-09-01 and the board's 'EN' column is now 'TK' (knocks). "
             f"Exiting without reading Slack or the Sheet. ({marker})")
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="sales day (YYYY-MM-DD); default yesterday")
    ap.add_argument("--week", action="store_true",
                    help="every day from Monday through the target day")
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default is a preview)")
    ap.add_argument("--sheet-id", default=SHEET_ID,
                    help="override the workbook (point at a sandbox copy)")
    a = ap.parse_args(argv)

    now = dt.datetime.now(TZ)
    end = dt.date.fromisoformat(a.date) if a.date else now.date() - dt.timedelta(days=1)
    days = [end]
    if a.week:
        monday = end - dt.timedelta(days=end.weekday())
        days = [monday + dt.timedelta(days=i) for i in range((end - monday).days + 1)]

    lo = dt.datetime.combine(days[0], dt.time(0), tzinfo=TZ)
    hi = dt.datetime.combine(days[-1] + dt.timedelta(days=1), dt.time(12), tzinfo=TZ)
    _log(f"reading {CHANNEL[0]}  {lo.date()} .. {hi.date()}")
    blocks = fetch_blocks(lo, hi)
    _log(f"{len(blocks)} Energy board post(s) in the window")

    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.alphalete_production.capture import find_week_tab
    ss = open_by_key(a.sheet_id)
    ws = find_week_tab(ss, end)     # the tab whose Mon-Sun week CONTAINS `end`
    g = ws.get_all_values()
    _log(f"sheet: {ss.title!r}  tab: {ws.title!r}"
         f"{'' if a.sheet_id == PROD_SHEET_ID else '   (NOT the prod workbook)'}")

    rows = roster(g)
    _log(f"Energy roster on the tab: {len(rows)} rep(s) — "
         + ", ".join(rows[r] for r in sorted(rows)))

    plans, incomplete, left_off = [], False, []
    for d in days:
        if not week_of(g, d):
            _log("")
            _log(f"--- Energy — {_md(d)} ---")
            _log(f"  {_md(d)} is not in {ws.title!r}'s week — holding "
                 "(run it with --date so the right tab is picked)")
            incomplete = True
            continue
        plan, day_incomplete, skipped = run_day(blocks, ws, g, d, rows)
        incomplete = incomplete or day_incomplete
        left_off += [(d, *s) for s in skipped]
        if plan:
            # Written even when the day is incomplete: the reps on this plan are
            # the ones we're sure of, and the doubt is listed separately below.
            plans.append((d, plan))

    _log("")
    writes = sum(len(p) for _d, p in plans)
    if not writes:
        _log("nothing to write — the board already matches Slack")
    for d, plan in plans:
        _log(f"{_md(d)}: {len(plan)} cell(s) would change")
        for rep, a1, cur, new in plan:
            _log(f"  {a1}  {rep:<32} {cur} -> {new}")
    if left_off:
        _log("")
        _log(f"LEFT BLANK — {len(left_off)} line(s) nobody could be matched to. "
             "Everything else on those days went in:")
        for d, raw, count, note in left_off:
            _log(f"  {_md(d)}: {raw!r} ({count} sale(s)) — {note}")
        _log("  fix: add the rep to the board's Energy rows, or the nickname to "
             "ALIASES in parse.py, then re-run that day (only ever raises)")
    if writes and a.apply:
        _retry(ws.batch_update,
               [{"range": a1, "values": [[new]]}
                for _d, plan in plans for _rep, a1, _cur, new in plan])
        _log(f"wrote {writes} cell(s) to {ws.title!r}")
    elif writes:
        _log("PREVIEW — re-run with --apply to write")
    # 75 = EX_TEMPFAIL, the hold code the sales boards use. Here it means the
    # day is INCOMPLETE — no post, a line nobody could be matched to, or a tally
    # that didn't line up — and NOT that nothing was written: what was sure went
    # in. Re-running only raises numbers, so the next pass just fills the rest.
    return 75 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
