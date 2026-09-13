"""Which team each rep is on — read off the office's own SALES BOARD.

Raf 2026-09-13: break the Weekly Knock Dispositions board up by team. The
team assignment already exists and is already maintained by hand every week —
it is a per-rep column, literally headed "Team", on the sales board
("Alphalete SALES BOARD 2025" for Raf). So this reads that column instead of
asking anybody to keep a second list in sync. Counted live 2026-09-13 on
'Sales Board WE 9.13': 77 reps, 5 teams (Se7en Sins 24, Ceaseless 18,
Alphaletes 14, Hashiras 12, Mindset Engine 7), exactly one blank.

EVERYTHING IS FOUND BY LABEL. That Team column is col 123 on WE 9.13 and col
87 on WE 9.6 — the same column, two tabs, 36 columns apart — so an index
would be wrong the first week somebody inserts a column. The week tab comes
from its 'WE m.d' name, the header row from its product labels, the Team
column from its banner-row title, and the rep block ends at 'TOTALS'. All of
that already lives in icd_sales_board.board_read, which parses this exact
template; nothing here re-derives it.

NAME MATCHING is three passes, each of which only accepts a UNIQUE hit —
OwnerVille and the board do not spell people the same way:

    exact        'Hank Tran'                 -> 'hank tran'
    nickname off 'Noemi (Ivette) Ontiveros'  -> 'noemi ontiveros'
                 'Terrance "Dior" Dandy'     -> 'terrance dandy'
    first+last   'Ibukunoluwa Olapade Ogunlola' -> 'ibukunoluwa ogunlola'

An ambiguous key is dropped rather than guessed — a rep filed under the wrong
team is worse than a rep filed under none, and one filed under none is
VISIBLE: they land in the UNASSIGNED block at the bottom of the board, where
the fix is one cell on the sales board.

FAIL-SOFT BY DESIGN. No board for this office, no Team column, no Sheets
access, a bad tab — every one of those returns None and the board renders
exactly as it did before, ungrouped. A team split is an improvement to the
board, never a reason for an office not to get its Sunday post.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

# Office name (as weekly_knock_dispositions.offices spells it) -> the sales
# board workbook that carries that office's Team column.
#
# Raf's is the only one today: his board IS the template every per-office ICD
# board is being copied from, and his is the office that asked. An office
# whose board exists is one line here — the parsing below is the template's,
# not his, so a copy of it reads with no other change. An office NOT in this
# map simply keeps the ungrouped board.
SALES_BOARDS: dict[str, str] = {
    "Rafael Hidalgo": "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc",
}

# The board's own label for a rep whose Team cell is empty, and for a rep on
# the knock board the sales board has never heard of (a brand-new start, or a
# name too ambiguous to match). Sorts last — see team_order().
UNASSIGNED = "Unassigned"

_PAREN = re.compile(r"\([^)]*\)")
_QUOTED = re.compile(r'"[^"]*"')


def _norm(s: str) -> str:
    """Lowercased, punctuation-flattened. Same rule board._norm_name uses, so
    a name that matches for apps matches for teams."""
    return re.sub(r"\s+", " ",
                  re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def _plain(name: str) -> str:
    """Nickname stripped: 'Noemi (Ivette) Ontiveros' -> 'noemi ontiveros'.

    Only bracketed and double-quoted asides go. Apostrophes stay — Ja'vanna
    and La'mya are spellings, not asides, and eating them would merge people.
    """
    return _norm(_QUOTED.sub(" ", _PAREN.sub(" ", name or "")))


def _short(name: str) -> str:
    """First + last token, so a middle name on one side only still matches."""
    parts = _plain(name).split()
    return f"{parts[0]} {parts[-1]}" if len(parts) > 2 else ""


def _unique(pairs: list) -> dict:
    """{key: team} for keys that appear ONCE. A key two reps share tells us
    nothing about either of them, so it is dropped, not guessed."""
    seen: dict[str, int] = {}
    for k, _t in pairs:
        seen[k] = seen.get(k, 0) + 1
    return {k: t for k, t in pairs if k and seen[k] == 1}


@dataclass
class TeamBook:
    """One office's rep -> team map, read from one week tab."""
    tab: str = ""
    source: str = ""                 # workbook -> tab -> column, for the log
    teams: list = field(default_factory=list)      # board spelling, sorted
    counts: dict = field(default_factory=dict)     # team -> reps ON THE BOARD
    blanks: int = 0                  # board rows with an empty Team cell
    _exact: dict = field(default_factory=dict)
    _plain: dict = field(default_factory=dict)
    _short: dict = field(default_factory=dict)

    def team_for(self, rep: str) -> str:
        """The rep's team, or '' when the board can't place them."""
        n = _norm(rep)
        if n in self._exact:
            return self._exact[n]
        p = _plain(rep)
        if p in self._plain:
            return self._plain[p]
        s = _short(rep) or p
        if s in self._short:
            return self._short[s]
        # Last pass: one name is the other plus trailing words. OwnerVille
        # carries a rep's status in the name cell — 'Andrew Sanborn Roadtrip'
        # is the board's 'Andrew Sanborn' — which is the same shape
        # board.match_apps already matches for the apps column, so the two
        # columns agree about who a rep is. Unique hits only.
        hits = {t for k, t in self._plain.items()
                if k.startswith(p + " ") or p.startswith(k + " ")}
        return hits.pop() if len(hits) == 1 else ""


def team_order(names) -> list:
    """Team sections in the order they draw: alphabetical, UNASSIGNED last.

    Alphabetical because it is STABLE — a team keeps its place on the board
    week to week, so a reader looking for their own block looks in the same
    spot every Sunday. (Ranking the sections by production instead is one
    sort key here; the rep rows inside each block follow the board's existing
    alphabetical order either way.)"""
    real = sorted({n for n in names if n and n != UNASSIGNED},
                  key=lambda s: s.lower())
    return real + ([UNASSIGNED] if UNASSIGNED in set(names) else [])


def load(office: str, saturday: dt.date, *, verbose: bool = True):
    """The office's TeamBook for the week ending `saturday`, or None.

    The tab wanted is the one whose 'WE m.d' date is that week's SUNDAY
    (saturday + 1) — the board names a week by the day it ends. If that tab
    doesn't exist yet the NEWEST one is used instead: the Team column is a
    roster fact, not a weekly measurement, so last week's answer is right for
    everyone who didn't change teams and is the only answer available for
    everyone else. Never raises — see the module docstring."""
    sheet_id = SALES_BOARDS.get(office)
    if not sheet_id:
        return None
    try:
        from automations.icd_sales_board import board_read as BR
        from automations.recruiting_report.fill import open_by_key

        sh = open_by_key(sheet_id)
        dated = BR.week_tab_dates([ws.title for ws in sh.worksheets()])
        if not dated:
            raise ValueError("no 'Sales Board WE m.d' tabs")
        want = saturday + dt.timedelta(days=1)
        tab = next((t for t, d in dated if d == want), dated[0][0])

        g = sh.worksheet(tab).get_all_values()
        hr = BR.header_row(g)
        tcol = BR._attr_cols(g, hr).get(BR.ATTR_TEAM)
        if not tcol:
            raise ValueError(f"no '{BR.ATTR_TEAM}' column on {tab}")

        pairs, counts, blanks = [], {}, 0
        for r in range(hr + 1, len(g) + 1):
            name, _tags = BR.clean_name(BR._c(g, r, BR.LABEL_COL))
            if not name:
                continue
            if name.strip().lower() == BR.TOTALS_LABEL:
                break                       # the rep block ends here
            team = " ".join((BR._c(g, r, tcol) or "").split()).strip()
            if not team:
                blanks += 1
                continue
            counts[team] = counts.get(team, 0) + 1
            pairs.append((name, team))

        if not counts:
            raise ValueError(f"'{BR.ATTR_TEAM}' column on {tab} is empty")

        book = TeamBook(
            tab=tab,
            source=(f"Alphalete SALES BOARD 2025 -> {tab} -> column "
                    f"'{BR.ATTR_TEAM}' (col {tcol}), rows {hr + 1}+"),
            teams=team_order(counts),
            counts=counts,
            blanks=blanks,
            _exact=_unique([(_norm(n), t) for n, t in pairs]),
            _plain=_unique([(_plain(n), t) for n, t in pairs]),
            _short=_unique([(_short(n), t) for n, t in pairs if _short(n)]),
        )
        if verbose:
            print(f"[wkd] teams: {office} -> {book.source}", flush=True)
            print("[wkd]   " + ", ".join(
                f"{t} {counts[t]}" for t in book.teams if t in counts)
                + (f", blank {blanks}" if blanks else ""), flush=True)
            # A one-rep team is usually a typo — somebody typed a person's
            # name into the Team cell. It still draws (dropping a rep is
            # worse), and saying so here is what gets the cell fixed.
            for t in book.teams:
                if counts.get(t) == 1:
                    print(f"[wkd]   ⚠ '{t}' has ONE rep — typo in the "
                          "board's Team cell?", flush=True)
        return book
    except Exception as e:                              # noqa: BLE001
        if verbose:
            print(f"[wkd] ⚠ teams: {office} — {type(e).__name__}: "
                  f"{str(e)[:160]} — board stays ungrouped.", flush=True)
        return None


# One read per office per week per process. The daily boards call this for
# every interval slot and for every office in the run; without the cache
# Raf's sales board would be re-read a dozen times a day for an answer that
# changes at most once a week.
_CACHE: dict = {}


def for_office(office: str, day: dt.date, *, verbose: bool = False):
    """The TeamBook covering `day`'s week, or None.

    Takes ANY day rather than the week's Saturday, because the daily boards
    know the day they are drawing and the weekly board knows the Saturday —
    one entry point, so the two can never end up reading different tabs for
    the same week. Mon–Sun weeks, matching the board's own 'WE <Sunday>' tabs.

    A negative (no sales board for this office) is cached too: an office
    without one is every office but Raf's, and they must not pay a lookup per
    board."""
    if office not in SALES_BOARDS:
        return None                      # no Sheets call at all
    saturday = day + dt.timedelta(days=(5 - day.weekday()) % 7)
    if day.weekday() == 6:               # Sunday closes the week behind it
        saturday = day - dt.timedelta(days=1)
    key = (office, saturday)
    if key not in _CACHE:
        _CACHE[key] = load(office, saturday, verbose=verbose)
    return _CACHE[key]
