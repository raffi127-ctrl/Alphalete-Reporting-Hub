"""Org Sales Board — "is yesterday actually ON the board?" gate for the email.

The email used to be gated on the FILL MANIFEST alone (`screenshot_email
.board_fill_ok`): did today's fill run and did every pull succeed. That answers
"did the automation work", not "are yesterday's numbers on the board" — a run
that succeeded having written nothing still passed it. Eve 2026-07-29: delay the
daily send and CHECK the data is complete before it goes out.

What "complete" means here (measured against the live board, 2026-07-29): every
daily section's YESTERDAY column is filled for every rep. On a normal morning
that's 194/199 rep cells, and the only gap is Retail JE — which legitimately
publishes a day behind, exactly as slack_post.fill_gate documents. So the gate
requires 100% of every section EXCEPT the known day-behind ones.

It is a HOLD, not a failure: before `send_anyway_after` an incomplete board means
"not yet, look again next pass"; after it, the gate opens and the email goes out
with whatever the board has. A section that never publishes must not cost us the
whole day's email — the numbers are still the board's own.

Read-only (one `get_all_values` on the copy tab). Used from two places, so the
rule lives in ONE spot:
  - day_orchestrator.readiness → holds the report STILL_TRYING (no failure alert,
    no burnt retries) while the board is short.
  - screenshot_email.main     → the same check right before a send, so a manual
    or off-orchestrator run gets the same protection.

NOT WHAT THE DRAFT WAITS FOR ANY MORE (Eve 2026-08-04). The org board email used
to be gated on this through readiness._probe_org_board_filled; it now waits for
the board to be POSTED in #top-leaders-alphalete-org instead (probe
org_board_posted), because this rule is stricter than the one the public post
itself has to clear and the two disagreed — board out 08:33, draft still not up
at 11:00. The probe and this module stay: this is still the right question for
anything that must not READ a half-filled board, and screenshot_email's own
pre-send check below is untouched. The APPROVED send (--send-reviewed) returns
before that check, so a checkmark is never blocked by a short board.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Tuple

# Sections that legitimately lag a day — allowed to be entirely blank for
# yesterday without holding the email. Matched case-insensitively against the
# section header's col-A label. Retail JE is the standing one (its source
# publishes a day behind; the VAs' own manual board shows the same gap);
# Frontier has historically lagged too.
LAGGING_SECTIONS = ("retail je", "frontier")

# Local clock (the runners are on Central) past which an incomplete board stops
# holding the email — the send goes out with what's on the board. MUST stay before
# the orchestrator's 12:00 backstop (settings.backstop_time): past it the loop
# stops circling back and marks stragglers MISSED, so a deadline of 14:00 would
# never be reached on Tue-Sun and the email would simply never send. Monday's
# afternoon board_catchup run is past this hour by design, so it always sends.
SEND_ANYWAY_AFTER = "11:30"


def _grid():
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(SANDBOX_TAB))
    return _retry(ws.get_all_values)


def _is_lagging(name: str) -> bool:
    n = (name or "").strip().lower()
    return any(n.startswith(s) for s in LAGGING_SECTIONS)


def coverage(g=None, yday: Optional[dt.date] = None) -> List[dict]:
    """Per-section fill of YESTERDAY's day column. One dict per daily section:
    {row, name, lagging, col, reps, filled, missing[names]}. `col` is None when
    the section has no column for that date (week not rolled / headers moved)."""
    from automations.org_sales_board import slack_post as sp   # heavy chain: lazy
    if g is None:
        g = _grid()
    if yday is None:
        yday = dt.date.today() - dt.timedelta(days=1)
    out = []
    for h in sp._header_rows(g):
        name = sp._cell(g, h, 1).strip() or sp._cell(g, h, 2).strip()
        col = sp._yesterday_col(g, h + 1, yday.day)
        reps = sp._rep_rows(g, h)
        missing = ([sp._cell(g, r, 2).strip() or f"row {r}"
                    for r in reps if not sp._cell(g, r, col).strip()]
                   if col else [])
        out.append({"row": h, "name": name, "lagging": _is_lagging(name),
                    "col": col, "reps": len(reps),
                    "filled": len(reps) - len(missing) if col else 0,
                    "missing": missing})
    return out


def _hhmm(s: str, on: dt.date) -> dt.datetime:
    h, m = s.split(":")
    return dt.datetime.combine(on, dt.time(int(h), int(m)))


def gate(g=None, yday: Optional[dt.date] = None, *, now: Optional[dt.datetime] = None,
         send_anyway_after: str = SEND_ANYWAY_AFTER) -> Tuple[bool, str]:
    """(ok, reason). ok=False means HOLD — the board is short of yesterday and it
    is still early enough to wait. Never raises: on a read error it fails OPEN
    (the caller's own manifest guard still stands) rather than silently killing
    the day's email."""
    now = now or dt.datetime.now()
    yday = yday or (dt.date.today() - dt.timedelta(days=1))
    try:
        secs = coverage(g, yday)
    except Exception as e:  # noqa: BLE001 — a Sheets hiccup must not block forever
        return True, (f"board read failed ({type(e).__name__}) — not holding; "
                      "the fill-manifest guard still applies")
    if not secs:
        return True, "no daily sections found — not holding (nothing to measure)"

    d = f"{yday.month}/{yday.day}"
    reps = sum(s["reps"] for s in secs)
    filled = sum(s["filled"] for s in secs)
    no_col = [s for s in secs if s["col"] is None]
    short = [s for s in secs if s["col"] and s["missing"] and not s["lagging"]]
    lagging_blank = [s["name"] for s in secs if s["lagging"] and s["missing"]]

    if not no_col and not short:
        tail = f" (lagging, allowed blank: {', '.join(sorted(set(lagging_blank)))})" if lagging_blank else ""
        return True, f"{d} complete — {filled}/{reps} rep cells{tail}"

    gaps = []
    if no_col:
        gaps.append(f"{len(no_col)} section(s) have no {d} column "
                    f"({', '.join(s['name'] for s in no_col[:3])})")
    for s in short[:4]:
        gaps.append(f"{s['name']} row {s['row']}: {len(s['missing'])}/{s['reps']} blank "
                    f"({', '.join(s['missing'][:4])})")
    if len(short) > 4:
        gaps.append(f"+{len(short) - 4} more section(s)")
    why = f"{d} INCOMPLETE — {filled}/{reps} rep cells; " + "; ".join(gaps)

    if now >= _hhmm(send_anyway_after, now.date()):
        return True, f"past {send_anyway_after} — sending with what the board has. {why}"
    return False, f"{why} (holding until it fills, or {send_anyway_after})"


def missing_sections(g=None, yday: Optional[dt.date] = None) -> List[str]:
    """The gaps behind gate()'s message, as a list a human can act on.

    gate() answers one question — send or hold — and buries WHAT is short in a
    string. Past the send-anyway hour it returns ok=True, so the day's email
    goes out and the gap only ever exists as a line in a log nobody reads: on
    2026-08-09 that line said 'ATT NDS - All Units has no 8/8 column' and it
    sat there unnoticed while the email shipped. Callers pass this to
    section_drop_alert so a board that ships SHORT says so out loud.

    A section that legitimately publishes a day behind (LAGGING_SECTIONS) is
    not a gap. Pass the grid gate() used to avoid a second board read.
    """
    yday = yday or (dt.date.today() - dt.timedelta(days=1))
    d = f"{yday.month}/{yday.day}"
    try:
        secs = coverage(g, yday)
    except Exception:  # noqa: BLE001 — never break a caller over the alarm
        return []
    out = [f"{s['name']} (row {s['row'] + 1}) — no {d} column; its day-number "
           "row is frozen on an older week"
           for s in secs if s["col"] is None]
    out += [f"{s['name']} (row {s['row'] + 1}) — {len(s['missing'])}/{s['reps']} "
            f"rep cells blank for {d}"
            for s in secs if s["col"] and s["missing"] and not s["lagging"]]
    return out
