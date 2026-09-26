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
        ],
    },
}


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
        claimed, missing = match_rows([rows[i] for i in pool],
                                      roster(host, guest))
        if not claimed:
            if logfn:
                logfn(f"[guests] {guest}: none of "
                      f"{len(roster(host, guest))} rostered rep(s) are on "
                      f"{host}'s grid — {host}'s board is unchanged")
            continue
        picked = sorted(claimed)                 # positions within `pool`
        out[guest] = [rows[pool[i]] for i in picked]
        if logfn:
            logfn(f"[guests] {guest}: {len(picked)} rep(s) moved off "
                  f"{host}'s board" + (f", {len(missing)} rostered rep(s) "
                                       f"not on the grid: "
                                       f"{', '.join(missing)}"
                                       if missing else ""))
        pool = [p for n, p in enumerate(pool) if n not in claimed]

    return [rows[i] for i in pool], out


def report(host: str, rows, *, logfn=print) -> None:
    """Log who matched and who didn't, without splitting anything. For a run
    that wants the visibility but draws one board."""
    for guest in guests_of(host):
        claimed, missing = match_rows(rows, roster(host, guest))
        logfn(f"[guests] {host} -> {guest}: {len(claimed)} matched"
              + (f", MISSING {', '.join(missing)}" if missing else ""))
