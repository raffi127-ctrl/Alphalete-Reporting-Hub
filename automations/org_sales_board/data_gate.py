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
# "frontier" dropped 2026-08-19 with the campaign: the section no longer
# exists on the board, so the exemption had nothing left to exempt.
#
# "box" ADDED 2026-08-25. BOX has been day-behind BY DESIGN since 2026-08-12,
# when Eve dropped 'tableau:box_daily' from the board's data_sources ("que se
# postee a las 7:15 aunque Box esté siempre un día atrasado"): the board now
# fills at 06:35 with whatever Box has — normally the day before — and the
# 14:30 com.alphalete.board-catchup re-pulls it. section_pull.BOX_SPEC carries
# `day_behind=True` for exactly this. The exemption here was never added, so
# every morning the gate read BOX's structurally-blank yesterday column as a
# gap and HELD, e.g. 2026-08-25 07:45: "8/24 INCOMPLETE — 165/172 rep cells;
# BOX row 153: 4/4 blank" with all 24 other sections at 100%. That cost
# owner_chat_texts_board its 07:45 send every day (it exits non-zero on a
# HOLD, so the channel got a FAILED incident) and delayed the org board email
# to the 11:30 fail-open.
#
# KEEP IN SYNC with section_pull.SPECS: any spec flagged `day_behind` belongs
# here, and test_data_gate_lagging.py fails the build if one is missing.
LAGGING_SECTIONS = ("retail je", "box")

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


def _cell_lower(g, r: int, c: int) -> str:
    from automations.org_sales_board import slack_post as sp
    return sp._cell(g, r, c).strip().lower()


def _covers(g, header_row: int, day: dt.date, today: dt.date) -> bool:
    """Is `day` inside this section's OWN 7-day span?

    Sections don't all start on Monday: Frontier runs SUN–SAT, so on a Monday
    its week ends Saturday and Sunday is not on it yet — both roll together on
    Tuesday. Reading every section against the board's Mon–Sun week called that
    a missing column every Monday (Eve 2026-08-10). True when the section has
    no readable weekday header, so an unknown shape still gets checked.
    """
    from automations.org_sales_board import fill_section as fs
    hdr = _cell_lower(g, header_row, 3)
    if hdr not in fs.WEEKDAY_ORDER:
        return True
    anchor = fs.SectionAnchor(
        header_row=header_row, daynum_row=header_row + 1,
        totals_row=header_row + 2, day_col_by_daynum={}, running_total_col=10,
        icd_rows={}, first_weekday=fs.WEEKDAY_ORDER.index(hdr))
    return day in fs.section_week(anchor, today)


def coverage(g=None, yday: Optional[dt.date] = None) -> List[dict]:
    """Per-section fill of YESTERDAY's day column. One dict per daily section:
    {row, name, lagging, col, expected, reps, filled, missing[names]}. `col` is
    None when the section has no column for that date (week not rolled /
    headers moved); `expected` is False when that date isn't on the section's
    own week at all (a Sun–Sat section on a Monday), which is not a gap."""
    from automations.org_sales_board import slack_post as sp   # heavy chain: lazy
    if g is None:
        g = _grid()
    today = dt.date.today()
    if yday is None:
        yday = today - dt.timedelta(days=1)
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
                    "expected": _covers(g, h, yday, today),
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
    return _decide(secs, yday, now=now, send_anyway_after=send_anyway_after)


def _decide(secs: List[dict], yday: dt.date, *, now: dt.datetime,
            send_anyway_after: str = SEND_ANYWAY_AFTER) -> Tuple[bool, str]:
    """The send-or-hold rule itself, over coverage() rows. Split out from gate()
    so the rule can be tested against a hand-built board without a Sheets read
    (test_data_gate_lagging.py) — the 2026-08-25 BOX hold was a bug in THIS
    function's inputs, and it had no test because the only way in was live."""
    if not secs:
        return True, "no daily sections found — not holding (nothing to measure)"

    d = f"{yday.month}/{yday.day}"
    reps = sum(s["reps"] for s in secs if s["expected"])
    filled = sum(s["filled"] for s in secs if s["expected"])
    # `expected` False = the date isn't on that section's own week (a Sun–Sat
    # section on a Monday). Not a gap, and not something a re-run can change.
    no_col = [s for s in secs if s["col"] is None and s["expected"]]
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
           for s in secs if s["col"] is None and s["expected"]]
    out += [f"{s['name']} (row {s['row'] + 1}) — {len(s['missing'])}/{s['reps']} "
            f"rep cells blank for {d}"
            for s in secs if s["col"] and s["missing"] and not s["lagging"]]
    return out
