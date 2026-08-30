"""Vantura Sales Board fill — from the ORDER LOGS, not Slack (Carlos, 2026-08-30).

Carlos: "This morning, you would have looked at yesterday's order log and
filled in the proper sales." The two Lucy order-log tabs already live on the
board itself and are refreshed by att_order_log / box_order_log, so the
morning close-out reads THEM instead of counting Slack posts:

  * B2B — "Lucy At&t Data": a rep's day = SUM(`Unit Count`) over rows with
    `sp.Order Date (copy)` = that day, all product types. Same rule
    captainship_boards verified 1:1 against a Sara-finalized board.
    Validated 2026-08-30 against the live week: Wed/Thu/Fri matched the
    board exactly, per rep and per total.
  * BOX — "Lucy Box Data": a rep's day = COUNT of contracts with
    `Sale Date` = that day that pass the sale gate (the TPV rule from
    box_order_log.clean, applied to the cleaned tab: Draft never reaches the
    tab; TPV Failed / Rejected QC / never-reached-TPV cancels don't count;
    Incomplete counts — Megan 2026-07-18). Cutover: Slack stays the BOX
    source through Mon 2026-08-31; this module fills BOX starting Tue
    2026-09-01 (Carlos 2026-08-30). --campaign BOX overrides the gate for a
    manual run.

Base is GONE — the campaign ended (Carlos 2026-08-30); no Base rows remain on
the board and vantura_slack_sales no longer parses it either.

Board mechanics are vantura_slack_sales' own, imported from it: same tab, same
label anchors, same wrong-week gate, and THE FILL ONLY EVER RAISES A NUMBER —
a board cell higher than the log (a hand entry, a sale routed another way)
stands. The log lags the same evening's late sales, which is exactly why the
evening Slack passes stay: this is the authoritative morning close-out, they
are the live intraday ticker.

  python -m automations.vantura_orderlog_sales.run                # yesterday
  python -m automations.vantura_orderlog_sales.run --date 2026-08-29
  python -m automations.vantura_orderlog_sales.run --week         # Mon..target
  python -m automations.vantura_orderlog_sales.run --campaign B2B
  python -m automations.vantura_orderlog_sales.run --fill         # plan writes
  python -m automations.vantura_orderlog_sales.run --fill --yes   # write
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys

from automations.vantura_slack_sales.run import (
    SHEET_ID, TAB, NAME_COL, TZ,
    _cell, _log, _md, _norm,
    board_grid, campaign_rows, day_column, week_ok,
)

DATA_TAB_ATT = "Lucy At&t Data"
DATA_TAB_BOX = "Lucy Box Data"

# BOX comes off Slack and onto the order log Tue 2026-09-01 (Carlos 2026-08-30).
BOX_START = dt.date(2026, 9, 1)

# FRESHNESS, the country-tracker way (Carlos 2026-08-30: "I'm sure the tracker
# post does something to make sure it's updated ... we would probably have to
# do the exact same thing"). tableau_screenshots.freshness gates each board on
# its DATA COVERAGE — does the data actually reach the last completed day —
# circles back while it doesn't, and fail-opens past a floor rather than ever
# skipping. Same rule here, per campaign, read off the log tabs themselves:
# a campaign is filled only when its data tab HAS rows for the target day.
# Not there yet -> exit 75 (HOLD) and the LaunchAgent ladder retries; past the
# campaign's fail-open floor the pass writes whatever the tab holds (raise-only
# makes that harmless — the next covered pass tops it up).
#
# The floors come from each feed's own clock:
#   B2B  06:45 — att_order_log's 4am-batch probe fail-opens at 05:30, so the
#                tab is normally written by ~05:35; 06:45 is well past it.
#   BOX  09:30 — the BOX extract refreshes ~07:00 and box_order_log writes at
#                07:00 + 08:30, so BOX is only ATTEMPTED from 08:40 (earlier
#                passes would hold every single day by design, which is noise,
#                not signal) and fail-opens at 09:30.
B2B_FAILOPEN = dt.time(6, 45)
BOX_ATTEMPT_FROM = dt.time(8, 40)
BOX_FAILOPEN = dt.time(9, 30)
FAILOPEN = {"B2B": B2B_FAILOPEN, "BOX": BOX_FAILOPEN}

# The export writes legal first names; the board keeps the name the rep goes
# by. Alias only the first token — last names match as-is.
FIRST_NAME_ALIASES = {
    "william": "will",
    "nicholas": "nick",
    "jeffrey": "jeff",
}

# ------------------------------------------------------------- BOX gate --
# The cleaned tab has no Drafts, so the remaining question per row is the TPV
# rule (box_order_log.clean): dead unless it reached TPV Passed or beyond.
# `Secondary Status` carries the history levels, comma-joined.
_BOX_COUNT_STATUSES = (
    "ready for booking", "accepted by supplier", "submitted to supplier",
    "incomplete",                       # Megan keeps it (SALE_EXEMPT_STATUSES)
    "rejected",                         # supplier saw it (Carlos 2026-08-27)
)
_BOX_TPV_PROOF = (
    "tpv passed", "submitted to supplier", "accepted by supplier",
    "ready for booking",
)
_BOX_DEAD_SUBS = ("tpv failed", "rejected qc")


def _box_is_sale(status: str, sub: str, secondary: str) -> bool:
    s = (status or "").strip().lower()
    hist = ((sub or "") + "," + (secondary or "")).lower()
    if s in _BOX_COUNT_STATUSES:
        return True
    if s == "verification":
        return not any(d in hist for d in _BOX_DEAD_SUBS) or \
            any(p in hist for p in _BOX_TPV_PROOF)
    # Cancelled by Broker / anything else: only a sale if it provably reached
    # TPV first — "TPV completed and forward is a sale ... it could go to
    # cancelled at any point" (Carlos 2026-07-22).
    return any(p in hist for p in _BOX_TPV_PROOF)


# ------------------------------------------------------------- counting --
def _alias(key: str) -> str:
    parts = key.split()
    if parts and parts[0] in FIRST_NAME_ALIASES:
        parts[0] = FIRST_NAME_ALIASES[parts[0]]
    return " ".join(parts)


def _mdy(day: dt.date) -> str:
    return day.strftime("%m/%d/%Y")


def counts_att(sh, day: dt.date) -> dict[str, float]:
    rows = sh.worksheet(DATA_TAB_ATT).get_all_values()
    h = rows[0]
    i_rep, i_date = h.index("Rep"), h.index("sp.Order Date (copy)")
    i_units = h.index("Unit Count")
    want = _mdy(day)
    out: dict[str, float] = collections.defaultdict(float)
    for r in rows[1:]:
        if r[i_date].strip() != want or not r[i_rep].strip():
            continue
        try:
            u = float(r[i_units] or 0)
        except ValueError:
            u = 0.0
        if u:
            out[_alias(_norm(r[i_rep]))] += u
    return out


def counts_box(sh, day: dt.date) -> dict[str, float]:
    rows = sh.worksheet(DATA_TAB_BOX).get_all_values()
    h = rows[0]
    i_rep, i_date = h.index("Rep Name"), h.index("Sale Date")
    i_st, i_sub = h.index("Status"), h.index("Contr. Sub-status")
    i_sec = h.index("Secondary Status")
    want = _mdy(day)
    out: dict[str, float] = collections.defaultdict(float)
    for r in rows[1:]:
        if r[i_date].strip() != want or not r[i_rep].strip():
            continue
        if _box_is_sale(r[i_st], r[i_sub], r[i_sec]):
            out[_alias(_norm(r[i_rep]))] += 1
    return out


CAMPAIGNS = {"B2B": counts_att, "BOX": counts_box}
COVERAGE_TABS = {"B2B": (DATA_TAB_ATT, "sp.Order Date (copy)"),
                 "BOX": (DATA_TAB_BOX, "Sale Date")}


def covers(sh, campaign: str, day: dt.date) -> bool:
    """Does the campaign's log tab hold ANY row for `day`? The pure-Sheets
    version of the tracker probe's data-coverage question. One blind spot,
    accepted: a genuinely zero-sales day looks exactly like a stale tab, so it
    holds until the fail-open floor and then correctly writes nothing."""
    tab, date_col = COVERAGE_TABS[campaign]
    rows = sh.worksheet(tab).get_all_values()
    i = rows[0].index(date_col)
    want = _mdy(day)
    return any(r[i].strip() == want for r in rows[1:])


def match_rep(log_key: str, rows: dict[str, int]):
    """Order-log name -> board row key. Exact, then first+last token, then a
    first-name-only board row (the board has an 'Esmeralda')."""
    if log_key in rows:
        return log_key
    parts = log_key.split()
    if len(parts) >= 2:
        for cand in rows:
            cp = cand.split()
            if cp and cp[0] == parts[0] and cp[-1] == parts[-1]:
                return cand
        single = [c for c in rows if len(c.split()) == 1 and c == parts[0]]
        if len(single) == 1:
            return single[0]
    return None


# ------------------------------------------------------------------ run --
def run_campaign(sh, g, day: dt.date, campaign: str) -> dict:
    rows = campaign_rows(g, campaign)
    counts = CAMPAIGNS[campaign](sh, day)
    col = day_column(g, day)

    matched, unmatched = {}, []
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        board_key = match_rep(key, rows)
        if board_key:
            matched[board_key] = int(n)
        else:
            unmatched.append((key, int(n)))

    _log("")
    _log(f"--- {campaign} — {_md(day)} (order log) ---")
    if not counts:
        _log("  no order-log rows for the day")
    agree = 0
    for key, n in sorted(matched.items(), key=lambda kv: -kv[1]):
        row = rows[key]
        on_board = str(_cell(g, row, col)).strip() if col else ""
        same = on_board == str(n)
        agree += same
        if same:
            delta = ""
        elif on_board.isdigit() and n <= int(on_board):
            delta = f"   <- board has {on_board}, KEPT (we only raise)"
        else:
            delta = f"   <- board has {on_board or '(blank)'}"
        _log(f"  {_cell(g, row, NAME_COL):<28} {n:>2}{delta}")
    for key, n in unmatched:
        _log(f"  ! IN THE LOG BUT ON NO {campaign} ROW: {key} — {n}. "
             "IN NO TOTAL until the rep is added to the board.")
    total = sum(matched.values()) + sum(n for _k, n in unmatched)
    _log(f"  {'TOTAL':<28} {total:>2}   ({agree}/{len(matched)} reps already "
         "agree with the board)")
    if col:
        kept = [_cell(g, row, NAME_COL) for key, row in
                sorted(rows.items(), key=lambda kv: kv[1])
                if key not in matched
                and str(_cell(g, row, col)).strip().isdigit()
                and int(str(_cell(g, row, col)).strip()) > 0]
        if kept:
            _log("  kept as-is (on the board, not in the log): "
                 + ", ".join(kept))
    return {"day": day, "campaign": campaign, "col": col, "rows": rows,
            "matched": matched, "total": total}


def fill_plan(g, result):
    """Raise-only, same contract as vantura_slack_sales.fill_plan."""
    from gspread.utils import rowcol_to_a1
    col = result["col"]
    if not col:
        return []
    plan = []
    for key, new in result["matched"].items():
        row = result["rows"][key]
        cur = str(_cell(g, row, col)).strip()
        note = ""
        if cur.isdigit():
            if new <= int(cur):
                continue
        elif cur:
            note = f"  (replaces marker {cur!r})"
        plan.append((_cell(g, row, NAME_COL), rowcol_to_a1(row, col),
                     cur or "(blank)", str(new), note))
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="sales day (YYYY-MM-DD); default yesterday")
    ap.add_argument("--week", action="store_true",
                    help="every day from Monday through the target day")
    ap.add_argument("--campaign", choices=sorted(CAMPAIGNS), action="append",
                    help="limit to one campaign (repeatable); default both, "
                         "with BOX gated until its cutover date")
    ap.add_argument("--fill", action="store_true",
                    help="plan the board write (dry-run without --yes)")
    ap.add_argument("--yes", action="store_true", help="actually write")
    a = ap.parse_args(argv)

    today = dt.datetime.now(TZ).date()
    end = dt.date.fromisoformat(a.date) if a.date else today - dt.timedelta(days=1)
    days = [end]
    if a.week:
        monday = end - dt.timedelta(days=end.weekday())
        days = [monday + dt.timedelta(days=i)
                for i in range((end - monday).days + 1)]

    now_t = dt.datetime.now(TZ).time()
    if a.campaign:
        campaigns = a.campaign            # explicit ask overrides the gates
    else:
        campaigns = ["B2B"]
        if today < BOX_START:
            _log(f"BOX stays on Slack until {BOX_START.isoformat()} — skipped "
                 "(pass --campaign BOX to force)")
        elif now_t < BOX_ATTEMPT_FROM:
            _log(f"BOX attempted from {BOX_ATTEMPT_FROM:%H:%M} — its extract "
                 "refreshes ~7am and box_order_log writes 7:00/8:30; skipped "
                 "this pass (the 8:45 pass picks it up)")
        else:
            campaigns.append("BOX")

    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(SHEET_ID)
    ws, g = board_grid()

    # Coverage gate, per campaign (see FRESHNESS above). Gated on the LAST
    # target day — with --week the earlier days are already-covered history.
    held_fresh = False
    ready = []
    for c in campaigns:
        if covers(sh, c, days[-1]):
            ready.append(c)
        elif now_t >= FAILOPEN[c]:
            _log(f"{c}: no {days[-1]} rows in the log tab but past the "
                 f"{FAILOPEN[c]:%H:%M} fail-open floor — proceeding with "
                 "what's there (a gate never skips a report)")
            ready.append(c)
        else:
            held_fresh = True
            _log(f"{c}: log tab has NO rows for {days[-1]} yet — HOLDING "
                 f"(retries until {FAILOPEN[c]:%H:%M}, then fail-open)")
    campaigns = ready

    results = [run_campaign(sh, g, d, c) for d in days for c in campaigns]

    if not a.fill:
        return 75 if held_fresh else 0

    _log("")
    held = False
    for res in results:
        ok, shown, want = week_ok(g, res["day"])
        if not ok:
            held = True
            _log(f"{res['campaign']} {_md(res['day'])}: WRONG WEEK — holding. "
                 f"WE cell reads {shown!r}, {_md(res['day'])} belongs to "
                 f"{want!r}.")
            continue
        if res["col"] is None:
            _log(f"{res['campaign']} {res['day']}: no column for that weekday")
            continue
        plan = fill_plan(g, res)
        _log(f"{res['campaign']} {_md(res['day'])} — {len(plan)} cell(s) "
             "would change:")
        for rep, a1, cur, new, note in plan:
            _log(f"  {a1}  {rep:<28} {cur} -> {new}{note}")
        if a.yes and plan:
            _retry(ws.batch_update,
                   [{"range": a1, "values": [[int(new)]]}
                    for _rep, a1, _cur, new, _note in plan])
            _log(f"  wrote {len(plan)} cell(s)")
    if not a.yes:
        _log("DRY RUN — re-run with --yes to write")
    return 75 if (held or held_fresh) else 0


if __name__ == "__main__":
    sys.exit(main())
