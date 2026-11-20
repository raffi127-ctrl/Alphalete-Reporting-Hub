"""Team totals for Carlos's sales text, off the Vantura Master's NDS Sales Board.

Carlos 2026-11-19, with a picture of Raf's text ("Ceaseless: 3 / Alphaletes: 1
/ ..."): "raf has team sales ... can we get the same thing attached to our
sales text message ... on [the Vantura Master Sales Board] you can see my team
assignments."

Raf's block reads the Team column of HIS sales board through
weekly_knock_dispositions.teams (icd_sales_board's template). Carlos's board
is a different workbook with a different layout, so this is its own reader
with the SAME two things notify.team_lines asks of a team book: `.teams` and
`.team_for(rep)`.

  * WHO IS ON WHICH TEAM: the 'Team' column of the 'NDS Sales Board' tab,
    found by its header (vantura_boards.parse_board), never by position.
  * WHICH TEAMS ARE LISTED: the board's own 'Teams -- Current Week' box
    (sales_boards.teams_box), so the text names the teams the board names. If
    the box cannot be found, every team a rep row carries.
  * WHOSE SALE IS WHOSE: the SaraPlus -> board match the board's own fill
    uses (vantura_nds_sara.board_key: aliases, legal first names, first +
    paternal surname), so a sale lands under the team of the row it lands on.

FAIL-SOFT: any error returns None and the text goes out exactly as before,
without the team block. Read at most once every CACHE_MIN minutes.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master
CAMPAIGN = "NDS"
CACHE_MIN = 10

# Office keys whose standings text carries THIS book (post._text_teams).
OFFICE_KEYS = frozenset({"carlos-b2batt"})


# THE WEEK BLOCK (Carlos 2026-11-19: "starting at 8:30 p.m. and after, do a
# team section with the total for the week numbers, only for 8:30pm and
# after"). From this local time on, the text also carries each team's week:
# the board's Mon..yesterday day cells + today's live SaraPlus numbers (the
# board's today cell is only filled hourly from Slack, so it is not used).
WEEK_FROM = (20, 30)
TZ = "America/Chicago"


class Book:
    """rep -> team for one read of the board."""

    def __init__(self, by_name: Dict[str, str], teams: List[str], source: str = "",
                 week_before: Optional[Dict[str, int]] = None):
        self._by_name = dict(by_name)      # normalised board name -> team
        self.teams = list(teams)
        self.source = source
        # {team: units on the board's day cells BEFORE today}, this week
        self.week_before = dict(week_before or {})

    def team_for(self, rep: str) -> str:
        """The rep's team, or '' when the board cannot place them."""
        try:
            from automations.vantura_nds_sara.run import board_key
            key = board_key(str(rep or ""), self._by_name)
        except Exception:  # noqa: BLE001 -- unplaced, never a crash
            key = None
        return (self._by_name.get(key) or "") if key else ""


def box_teams(grid) -> List[str]:
    """The team names the board's own Teams box lists, top to bottom; [] when
    the box is not there. Skips the campaign total row under the header and
    stops before 'Unaccounted For'."""
    try:
        from automations.sales_boards import teams_box as TB
        hdr, last, _cols = TB.box_rows(grid)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in range(hdr + 2, last):
        row = grid[r - 1] if r - 1 < len(grid) else []
        name = " ".join(str(row[TB.LABEL_COL - 1] if len(row) >= TB.LABEL_COL else "").split())
        if name and name not in out:
            out.append(name)
    return out


def _units(v) -> int:
    v = str(v or "").replace(",", "").strip()
    return int(v) if v.isdigit() else 0          # T / F / X / blank = 0


def from_grid(grid, tab: str = "", day: Optional[dt.date] = None) -> Book:
    from automations import vantura_boards as VB
    from automations.vantura_slack_sales.run import _norm
    reps = VB.parse_board(grid, tab)
    by_name, week_before = {}, {}
    upto = day.weekday() if day else 0           # Mon=0: day cells before today
    for r in reps:
        team = " ".join(str(r.get("team") or "").split())
        by_name[_norm(r["name"])] = team
        n = sum(_units(c) for c in (r.get("days") or [])[:upto])
        if n:
            k = team or "Unassigned"
            week_before[k] = week_before.get(k, 0) + n
    teams = box_teams(grid) or sorted({t for t in by_name.values() if t}, key=str.lower)
    if not teams:
        raise ValueError("no team on any rep row of %s" % (tab or "the board"))
    return Book(by_name, teams, "%s -> Team column, %d rep(s), %d team(s)"
                % (tab or "NDS Sales Board", len(by_name), len(teams)),
                week_before=week_before)


def week_due(now: Optional[dt.datetime] = None) -> bool:
    """8:30pm or later, office time."""
    from zoneinfo import ZoneInfo
    now = now or dt.datetime.now(ZoneInfo(TZ))
    if now.tzinfo is not None:
        now = now.astimezone(ZoneInfo(TZ))
    return (now.hour, now.minute) >= WEEK_FROM


def week_lines(book: Book, today_units, day: dt.date) -> List[str]:
    """['', 'Week (Mon-Thu):', 'Team: n 🥇', ...] -- the board's days before
    today plus today's live units. `today_units` = [(shown rep name, units)].
    Every team the board lists shows (a zero too); Unassigned only when > 0."""
    from automations.alphalete_sales_board import notify as N
    score = {t: 0 for t in book.teams}
    for t, n in book.week_before.items():
        score[t] = score.get(t, 0) + n
    for name, n in today_units:
        if n <= 0:
            continue
        t = book.team_for(N.short_name(name)) or book.team_for(name) or "Unassigned"
        score[t] = score.get(t, 0) + n
    if not score.get("Unassigned"):
        score.pop("Unassigned", None)
    order = sorted(score, key=lambda t: (t == "Unassigned", -score[t], t.lower()))
    top = max([score[t] for t in score if t != "Unassigned"] or [0])
    days = "Mon" if day.weekday() == 0 else "Mon-%s" % day.strftime("%a")
    return ["", "Week (%s):" % days] + [
        "%s: %d%s" % (t, score[t], " " + N.GOLD if top and score[t] == top
                      and t != "Unassigned" else "")
        for t in order]


_CACHE: Dict[str, tuple] = {}


def for_day(day: dt.date, log=print, now: Optional[dt.datetime] = None) -> Optional[Book]:
    """The live team book, or None (never raises)."""
    now = now or dt.datetime.now()
    hit = _CACHE.get("book")
    if hit and hit[2] == day and (now - hit[0]).total_seconds() < CACHE_MIN * 60:
        return hit[1]
    try:
        from automations import vantura_boards as VB
        from automations.recruiting_report.fill import open_by_key
        ws = VB.board_ws(open_by_key(SHEET_ID), CAMPAIGN)
        book = from_grid(VB._retry_or_call(ws.get, VB.READ_RANGE), ws.title, day)
        log("vantura teams: %s" % book.source)
    except Exception as e:  # noqa: BLE001 -- the block, never the text
        log("vantura teams skipped: %s: %s" % (type(e).__name__, str(e)[:160]))
        book = None
    _CACHE["book"] = (now, book, day)
    return book
