"""Reps who knock on somebody ELSE'S ownerville — off the host's board, onto
their own.

CARLOS'S B2B REPS ARE DISPOSITIONING IN RAF'S OWNERVILLE (office 11280).
Carlos, #l10 2026-09-25: "raf my guys are using telemapper under you… can i get
his disposition screenshot sent to my Aplayers and leaders chats as well? is
there a way to separate my team?" They started that same day, so from 9/25 on
every board built off Raf's office silently carries fourteen reps who are not
his — inflating his TOTAL, his Talk To's per Rep and his Avg Knocks/Hr, and
burying Carlos's people in a list of seventy-odd names they have no business
being ranked against.

TWO BOARDS, ONE PULL. `split()` is called on the rows the host's pull already
returned — no second ownerville session, no second login (standing rule: same
content to N surfaces = one pull, N posts). The host's board renders from
`host_rows` and every aggregate on it (TOTAL, Reps Knocking, the rate columns,
the team bands) recomputes from the rows that are actually drawn, so nothing
has to be told these reps are gone. The guest's board renders from
`guest_rows[guest]` through the SAME renderer, so it arrives with the office
TOTAL and Chan Park's teal comparison line like every other knock board.

THE ROSTER IS SPELLED THE WAY OWNERVILLE SPELLS IT — Carlos typed the list off
his own screen ("Names spelled exactly how they are on his ownerville"). It is
still matched loosely, three passes, because ownerville does NOT hand back the
name a human typed:

    exact          'Christian Perez'      -> 'christian perez'
    middle name    'Jose Pimentel Lugo'   -> row 'Jose Manuel Pimentel Lugo'
    status suffix  'Yariel Caban'         -> row 'Yariel Caban Roadtrip'

AN AMBIGUOUS MATCH IS NO MATCH. A rep left on Raf's board is visible — Carlos
or Raf says "he's ours" and the roster gains a line. A rep moved off it by a
guess is invisible in both directions: Raf's total silently drops and Carlos's
silently gains somebody else's numbers. So every pass accepts a unique hit only,
and anything the roster names but the grid doesn't have is printed by
`report()` — which the runs call, so a rep who leaves, gets re-spelled, or was
typed wrong shows up in the log instead of quietly staying on Raf's board.

THREE WAYS ONTO THE GUEST'S BOARD (Raf, 2026-11-14), checked in this order:
the hand roster below, a NAME TAG at the end of the OwnerVille name ('… GP',
'… Carlos Road Trip' — GUEST_TAGS), and the guest's own SALES BOARD
(GUEST_SALES_BOARDS). Raf's own road trips ('RT', 'Road Trip', 'Roadtrip'
with no guest tag) stay on his board on purpose.

ADDING AN OFFICE IS ONE ENTRY in GUEST_REPS. Everything below is written
host-agnostic; nothing in it knows Raf's or Carlos's name.
"""
from __future__ import annotations

from automations.total_knocks.pull import COL_REP
# The SAME normalisation the team split matches names with, so a rep who
# matches for teams matches here — two different answers about who a person is,
# on one board, is the bug this avoids.
from automations.weekly_knock_dispositions.teams import _norm, _plain, _short

# host ownerville office -> guest office -> that guest's reps, as ownerville
# spells them. The guest key is the name that goes in the board's title and in
# the log; it does NOT have to be an office this repo pulls (Carlos's own
# office 11580 is B2B and has its own reports — these reps are on Raf's fiber
# campaign, and only here).
GUEST_REPS: dict = {
    "Rafael Hidalgo": {
        # Carlos Hidalgo, in #l10-alphalete 2026-09-25 at 2:25 PM, when Megan
        # asked for the list: "these are all the reps currently dispositioning.
        # Names spelled exactly how they are on his ownerville". Fourteen.
        "Carlos Hidalgo": [
            "Jorge Gramajo",
            "Rodolfo Bazan",
            "Christian Perez",
            "Jose Pimentel Lugo",
            "Nicholas Smedra",
            "Aaron De La Torre",
            "Diego Del Pozo Borres",
            "Yariel Caban",
            "Eduardo Alvarez",
            "Fernando Salazar",
            "Gavin Natividad",
            "Andrew De La Torre",
            "Danniel Alvarenga",
            "Luis Servellon",
            "Jacob Ortega",             # Carlos 2026-09-30: "add jacob ortega"
            "Sebastian Avellaneda",     # Carlos 2026-10-03: "missing sebastians sale"
        ],
    },
}


# NAME TAGS — the OwnerVille name itself says whose rep it is (Raf, #lucy-projects
# 2026-11-14: "Maybe Carlos can tag their name as 'Carlos Road Trip', and if
# their name is called 'Carlos Road Trip' or 'GP Road Trip', it'll
# automatically not mark them"). Carlos's people already show up as
# 'Anette Climaco GP' / 'Brianna Belen GP'. A tag is matched as the LAST
# words of the name, so Raf's own road trips ('Jon Road Trip', 'Roman Albert
# RT', 'Andrew Sanborn Roadtrip') never read as Carlos's — Raf wants those ON
# his board, to coach them.
GUEST_TAGS: dict = {
    "Rafael Hidalgo": {
        "Carlos Hidalgo": ("gp", "gp rt", "gp road trip", "gp roadtrip",
                           "carlos rt", "carlos road trip",
                           "carlos roadtrip"),
    },
}

# SALES-BOARD CROSS-CHECK — anybody on the guest's own sales board is the
# guest's, so a new rep of Carlos's comes off Raf's board the day Carlos puts
# them on his, with nobody typing a roster line (Raf, same thread: "get
# connected to his sales board and then cross-reference the knocks … and
# remove any reps from our knocking report that are on his sales board").
# Value = the Google Sheet holding that board (the Vantura Master Sales Board:
# the NDS / BOX / Verizon tabs, read through vantura_boards.all_reps).
GUEST_SALES_BOARDS: dict = {
    "Rafael Hidalgo": {
        "Carlos Hidalgo": "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY",
    },
}

# One read of a board per process per half hour — gap_alerts runs all day in
# one process and the Sheets read cap is per user. A failed read keeps the
# last good list; with none, the split runs on the roster + tags alone and
# says so in the log (a dead sheet must never stop the knock board).
_BOARD_TTL_S = 30 * 60
_BOARD_CACHE: dict = {}


def _read_board(sheet_id: str) -> list:
    """Every rep name on that workbook's sales-board tabs. Tests replace this."""
    from automations.recruiting_report.fill import open_by_key
    from automations.vantura_boards import all_reps
    return [r["name"] for r in all_reps(open_by_key(sheet_id))]


_LIVE_READ = _read_board


def _lookup(table: dict, host: str, guest: str):
    for h, guests in table.items():
        if _norm(h) != _norm(host):
            continue
        for g, v in guests.items():
            if _norm(g) == _norm(guest):
                return v
    return None


def tags(host: str, guest: str) -> tuple:
    return tuple(_lookup(GUEST_TAGS, host, guest) or ())


def tagged(host: str, guest: str, name: str) -> bool:
    """Does the OwnerVille name END in one of the guest's tags?"""
    n = _plain(name)
    return any(n.endswith(" " + t) for t in tags(host, guest))


def board_names(host: str, guest: str, *, logfn=None) -> list:
    """Names on the guest's own sales board ([] when the guest has none, or
    the sheet can't be read and nothing was read before)."""
    import os
    import sys
    import time
    sheet_id = _lookup(GUEST_SALES_BOARDS, host, guest)
    if not sheet_id or os.environ.get("GUESTS_SALES_BOARD", "1") == "0":
        return []
    # A unit test never reads the live sheet — only a test that swapped in
    # its own reader gets board names. (No live runner imports unittest.)
    if "unittest" in sys.modules and _read_board is _LIVE_READ:
        return []
    now = time.time()
    hit = _BOARD_CACHE.get(sheet_id)
    if hit and now - hit[0] < _BOARD_TTL_S:
        return list(hit[1])
    try:
        names = [n for n in _read_board(sheet_id) if str(n or "").strip()]
    except Exception as e:  # noqa: BLE001 — never let the sheet stop a board
        if logfn:
            logfn(f"[guests] couldn't read {guest}'s sales board "
                  f"({type(e).__name__}: {e}) — "
                  + ("using the last good copy" if hit else
                     "splitting on the roster + name tags only"))
        return list(hit[1]) if hit else []
    _BOARD_CACHE[sheet_id] = (now, names)
    return list(names)


def guests_of(host: str) -> list:
    """The guest offices knocking under `host`, or []. Case-insensitive —
    callers spell the host off whatever registry they hold."""
    for name, guests in GUEST_REPS.items():
        if _norm(name) == _norm(host):
            return list(guests)
    return []


def roster(host: str, guest: str) -> list:
    """`guest`'s reps under `host`, as the roster spells them."""
    for name, guests in GUEST_REPS.items():
        if _norm(name) != _norm(host):
            continue
        for g, reps in guests.items():
            if _norm(g) == _norm(guest):
                return list(reps)
    return []


def has_guests(host: str) -> bool:
    """Cheap enough to call on every office in a loop — no Sheets, no I/O."""
    return bool(guests_of(host))


def _rep(row) -> str:
    return str((row or {}).get(COL_REP, "") or "").strip()


def _claim(rows, taken: set, keyfn, want: str):
    """The index of the ONE unclaimed row whose `keyfn` equals `want`.

    None for no hit and None for two — see the module docstring: a guess is
    worse than a miss, and a miss is visible in `report()`."""
    if not want:
        return None
    hits = [i for i, r in enumerate(rows)
            if i not in taken and keyfn(_rep(r)) == want]
    return hits[0] if len(hits) == 1 else None


def _tokens(name: str) -> list:
    return _plain(name).split()


def _subseq(short: list, long: list) -> bool:
    """Is `short` the same names, in order, with words missing? The first
    token must match outright — a middle name or a status word can go, a
    FIRST name never does, and without that anchor 'Aaron De La Torre' and
    'Andrew De La Torre' are one edit apart."""
    if not short or not long or short[0] != long[0]:
        return False
    it = iter(long)
    return all(any(t == w for w in it) for t in short)


def _loose_claim(rows, taken: set, want: str):
    """Ownerville does not hand back the name a human typed. It carries a
    MIDDLE name the roster leaves out ('Jose Manuel Pimentel Lugo' for 'Jose
    Pimentel Lugo') and a rep's STATUS in the same cell ('Yariel Caban
    Roadtrip'), often both at once — which is past what first+last can reach.

    So the last pass is a token subsequence, either direction, anchored on the
    first name. Unique hits only: two rows that both read as one roster name
    tell us nothing about either, and a wrong claim moves a rep between two
    owners' boards where neither can see it happen."""
    w = _plain(want).split()
    if not w:
        return None
    hits = [i for i, r in enumerate(rows)
            if i not in taken
            and (_subseq(w, _tokens(_rep(r))) or _subseq(_tokens(_rep(r)), w))]
    return hits[0] if len(hits) == 1 else None


def match_rows(rows, names) -> tuple:
    """({row index: roster name}, [roster names with no row]).

    Pass order is strictest first and each pass runs over ALL the names before
    the next one starts, so a loose key can never steal a row an exact name
    was going to take."""
    rows = list(rows or [])
    want = [n for n in (names or []) if str(n or "").strip()]
    claimed: dict = {}
    taken: set = set()
    left = list(want)

    # (how a ROW is keyed, how a ROSTER NAME is keyed). They differ on the
    # third pass on purpose: a two-token roster name has no first+last key of
    # its own ('Jorge Gramajo' -> ''), and it is exactly the name that needs
    # this pass, because the ROW is the one carrying the middle name.
    for keyfn, key_of in ((_norm, _norm),
                          (_plain, _plain),
                          (_short, lambda n: _short(n) or _plain(n))):
        still = []
        for name in left:
            k = key_of(name)
            i = _claim(rows, taken, keyfn, k) if k else None
            if i is None:
                still.append(name)
                continue
            taken.add(i)
            claimed[i] = name
        left = still

    still = []
    for name in left:
        i = _loose_claim(rows, taken, name)
        if i is None:
            still.append(name)
            continue
        taken.add(i)
        claimed[i] = name

    return claimed, still


def split(host: str, rows, *, logfn=None) -> tuple:
    """(host_rows, {guest: rows}) — the host's own reps, and each guest's.

    Row ORDER is preserved on both sides, and every row lands on exactly one
    board: a rep is the host's until a guest's roster claims them. An office
    with no guests gets its rows back unchanged and pays nothing.
    """
    rows = list(rows or [])
    if not rows or not has_guests(host):
        return rows, {}

    pool = list(range(len(rows)))
    out: dict = {}
    for guest in guests_of(host):
        sub = [rows[i] for i in pool]
        claimed, missing = match_rows(sub, roster(host, guest))
        n_roster = len(claimed)

        # Name tag ('… GP', '… Carlos Road Trip') — no list needed.
        n_tag = 0
        for i, r in enumerate(sub):
            if i not in claimed and tagged(host, guest, _rep(r)):
                claimed[i] = _rep(r)
                n_tag += 1

        # The guest's own sales board. Same unique-hit matcher as the roster;
        # a board name needs a first AND last name (a lone 'Jon' would claim
        # Raf's 'Jon Road Trip'), and a board rep who isn't knocking under the
        # host is simply not there — that's not a miss worth logging.
        have = {_plain(n) for n in roster(host, guest)}
        extra = []
        for n in board_names(host, guest, logfn=logfn):
            p = _plain(n)
            if len(p.split()) >= 2 and p not in have:
                have.add(p)
                extra.append(n)
        n_board = 0
        if extra:
            rest = [i for i in range(len(sub)) if i not in claimed]
            got, _ = match_rows([sub[i] for i in rest], extra)
            for j, name in got.items():
                claimed[rest[j]] = name
            n_board = len(got)

        if not claimed:
            if logfn:
                logfn(f"[guests] {guest}: none of "
                      f"{len(roster(host, guest))} rostered rep(s) are on "
                      f"{host}'s grid — {host}'s board is unchanged")
            continue
        picked = sorted(claimed)                 # positions within `pool`
        out[guest] = [rows[pool[i]] for i in picked]
        if logfn:
            how = ", ".join(f"{k} by {w}" for k, w in
                            ((n_roster, "roster"), (n_tag, "name tag"),
                             (n_board, "sales board")) if k)
            logfn(f"[guests] {guest}: {len(picked)} rep(s) moved off "
                  f"{host}'s board ({how})"
                  + (f", {len(missing)} rostered rep(s) not on the grid: "
                     f"{', '.join(missing)}" if missing else ""))
        pool = [p for n, p in enumerate(pool) if n not in claimed]

    return [rows[i] for i in pool], out


def report(host: str, rows, *, logfn=print) -> None:
    """Log who matched and who didn't, without splitting anything. For a run
    that wants the visibility but draws one board."""
    for guest in guests_of(host):
        claimed, missing = match_rows(rows, roster(host, guest))
        logfn(f"[guests] {host} -> {guest}: {len(claimed)} matched"
              + (f", MISSING {', '.join(missing)}" if missing else ""))


def guest_for(host: str, name: str) -> str:
    """The guest office `name` belongs to under `host`, or "".

    ONE NAME AT A TIME, for the callers that have no grid to split — the
    SaraPlus sales sweep asks "is this seller one of Carlos's?" about a single
    ALL-CAPS name (Raf 2026-09-29: "can we make it where carlos's reps that
    are selling in my code don't get added to my sales board"). Same four
    passes as `match_rows`, so a rep who comes off the knock board comes off
    the sales board too — one roster, one answer, no second list to keep.

    A name claimed by TWO guest offices returns "" — with more than one guest
    under a host that is genuinely ambiguous, and a sale credited to the wrong
    office is worse than one left where it is. A sale dropped in error is
    invisible to everybody; a sale left on the host's board is visible and
    gets corrected out loud.
    """
    n = (name or "").strip()
    if not n or not has_guests(host):
        return ""
    keys = {_norm(n), _plain(n)}
    short = _short(n)
    toks = _plain(n).split()
    hits = set()
    for guest in guests_of(host):
        for r in roster(host, guest):
            rk = {_norm(r), _plain(r)}
            if keys & rk:
                hits.add(guest)
                break
            rs = _short(r) or _plain(r)
            if rs and rs in (short or _plain(n)):
                hits.add(guest)
                break
            if short and rs == short:
                hits.add(guest)
                break
            rt = _plain(r).split()
            if _subseq(rt, toks) or _subseq(toks, rt):
                hits.add(guest)
                break
    return hits.pop() if len(hits) == 1 else ""
