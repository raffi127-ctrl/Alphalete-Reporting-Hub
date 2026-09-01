"""The captainship half: a new face under a captain in Tableau gets announced.

There is no bank here, and there shouldn't be — a captain adding a rep is not
something anyone tells us in advance. The signal is the Tableau workbooks
themselves: every captainship report already pulls its captain's team and, when
an owner comes back that has no row on the tab, appends one (`insert_missing_
reps` in the churn/cancel-rate/activation-rate/ABP fills, `insert_missing` in
the Raf metrics boxes, the roster reconcile in the two bonus reports). So the
ADD is solved, report by report. What was missing is that it happened silently,
in five different logs, with nobody able to answer "who is new this week?".

`observe()` is that answer. A report calls it with the names it just added; the
FIRST report to see a rep announces them and writes the line in the log tab, and
every later report that day recognises the name and says nothing. One rep, one
bullet, no matter how many reports pick them up.

It also answers the one thing the reports can't: whether that rep exists on the
Org Sales Board's boxes for that captainship. The board's copy tab mirrors the
VA's board structurally (`roster_sync` clones a VA row to build a copy row), so
a rep the VA hasn't added yet CANNOT be given a copy row from here — the notice
says so plainly instead of pretending.

Advisory everywhere: a report's own work is done by the time it calls this, so
every call site swallows exceptions.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import List, Optional

from automations.new_owners import bank, notify

# Captain -> the family of reports that carry per-rep rows for that captainship.
# Used for the notice text only ("the rest pick them up on their next run"), so
# a captain missing here still gets announced — the list just reads generic.
FIBER_CAPTAINS = {"wayne", "starr", "chan", "tony", "sahil", "raf", "rafael"}
B2B_CAPTAINS = {"carlos", "eveliz", "luis"}
NDS_CAPTAINS = {"khalil", "colten", "jairo"}

FAMILY_REPORTS = {
    "fiber": ["Captainship Cancel Rate", "Captainship Activation Rate",
              "Captainship ABP & 6 days out", "Captainship Churn",
              "Captainship Activations"],
    "b2b": ["Captainship Churn", "Carlos Captainship Bonus"],
    "nds": ["Captainship Churn"],
    "": [],
}


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


# A captain who answers to two names. The board says 'Raf', the Tableau team
# filter and the metrics tabs say 'Rafael' — without this the log would treat
# them as two captainships and announce the same rep twice.
CANONICAL = {"rafael": "Raf"}


def captain_name(title: str) -> str:
    """'Starr's Captainship Team' / \"LUIS' CAPTAIN TEAM\" / 'wayne' -> 'Starr'
    / 'Luis' / 'Wayne'.

    The board, the Tableau team filters and the per-captain tabs all spell the
    same captainship differently; everything here keys on the bare first name so
    they line up. Callers pass a captain identifier (a slug, a team filter value
    or a board block title) — never a report tab title, which starts with the
    report's own name."""
    t = re.sub(r"\(.*?\)", " ", title or "")
    t = re.sub(r"\bcaptain(?:ship)?\b|\bteam\b", " ", t, flags=re.I)
    toks = [w for w in re.split(r"[\s\-–—/]+", t) if w]
    if not toks:
        return (title or "").strip()
    # Possessive stripped at TOKEN level: a trailing apostrophe with nothing
    # after it ("LUIS' CAPTAIN TEAM") has no word boundary for a \b pattern to
    # catch, and left in place it makes "Luis'" a different captain from "Luis".
    first = re.sub(r"['’]s?$", "", toks[0], flags=re.I)
    return CANONICAL.get(first.lower(), first.title())


def family_for(captain: str) -> str:
    key = _norm(captain).split()[0] if captain else ""
    if key in FIBER_CAPTAINS:
        return "fiber"
    if key in B2B_CAPTAINS:
        return "b2b"
    if key in NDS_CAPTAINS:
        return "nds"
    return ""


def sibling_reports(captain: str, exclude: str = "") -> List[str]:
    return [r for r in FAMILY_REPORTS.get(family_for(captain), [])
            if _norm(r) != _norm(exclude)]


def board_names(captain: str, *, ss=None, aliases=None):
    """(aliases, [every rep name in that captainship's boxes]) — ONE read of the
    copy tab. Raises on any lookup problem; the two callers below decide what a
    failure means for them."""
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
    from automations.org_sales_board import captainship as cap
    from automations.focus_office_att.aliases import load_aliases
    aliases = aliases if aliases is not None else load_aliases()
    ss = ss if ss is not None else open_by_key(SHEET_ID)
    grid = _retry(ss.worksheet(SANDBOX_TAB).get_all_values)
    short = _norm(captain_name(captain))
    out = []
    for title, _hint in cap.discover_captainships(grid):
        if _norm(captain_name(title)) != short:
            continue
        for _variant, anc in cap.find_captainship_boxes(grid, title):
            out += [nm for _r, nm in anc.daily + anc.leaderboard]
    return aliases, out


def on_org_board(captain: str, name: str, *, ss=None, aliases=None) -> bool:
    """Does this rep have a row in that captainship's boxes on the board's copy
    tab? Read-only; False on any lookup problem (the notice then says 'check
    it', which is the safe direction)."""
    try:
        from automations.org_sales_board import fill_section as fs
        aliases, have = board_names(captain, ss=ss, aliases=aliases)
        want = fs._candidates_for(name, aliases)
        return any(fs._candidates_for(nm, aliases) & want for nm in have)
    except Exception:  # noqa: BLE001 — read-only probe, never fails a caller
        return False


def already_on_board(captain: str, names, *, ss=None, aliases=None) -> set:
    """Which of `names` ALREADY have a row in that captainship's boxes.

    Alias-aware (the board says 'Jeff Starr', Tableau says 'Jeffrey Starr') and
    one tab read for the whole list, because its caller is the ✅ gate and a
    per-name probe would re-read the board once per rep.

    Empty set on any lookup problem: not knowing must fall back to ASKING, never
    to swallowing a genuinely new rep."""
    try:
        from automations.org_sales_board import fill_section as fs
        aliases, have = board_names(captain, ss=ss, aliases=aliases)
    except Exception:  # noqa: BLE001
        return set()
    on_board = [fs._candidates_for(nm, aliases) for nm in have]
    return {n for n in (names or [])
            if any(c & fs._candidates_for(n, aliases) for c in on_board)}


def observe(names: List[str], *, captain: str, source: str,
            today: Optional[dt.date] = None, ss=None, dry_run: bool = False,
            check_board: bool = True, did: str = "", logfn=print) -> List[dict]:
    """Announce reps that are new to this captainship. Returns the new ones.

    `names`  — reps the calling report just added (or just saw for the first
               time) under `captain`.
    `source` — the report's own name, for the log line.

    Names already in the log for this captainship are dropped silently: that is
    what keeps five reports from posting five bullets about the same person, and
    what keeps a re-run from posting anything at all."""
    today = today or dt.date.today()
    names = [n for n in dict.fromkeys(n.strip() for n in names or []) if n]
    if not names:
        return []
    capt = captain_name(captain)
    try:
        from automations.recruiting_report.fill import open_by_key
        from automations.org_sales_board.run import SHEET_ID
        ss = ss if ss is not None else open_by_key(SHEET_ID)
        lws = bank.open_log(ss, logfn=logfn)
        seen = bank.log_entries(lws)
    except Exception as e:  # noqa: BLE001 — never break the calling report
        logfn(f"  ⚠ new-owner watch skipped ({type(e).__name__}: "
              f"{str(e)[:80]})")
        return []

    fresh = [n for n in names
             if not bank.already_logged(seen, bank.KIND_CAPTAINSHIP, n, capt)]
    if not fresh:
        return []

    adds, log_rows = [], []
    siblings = sibling_reports(capt, exclude=source)
    for n in fresh:
        board = on_org_board(capt, n, ss=ss) if check_board else None
        adds.append({"name": n, "captain": capt, "board": board,
                     "where": did or f"seen in {source}"})
        board_txt = ("on the Org Sales Board" if board is True else
                     "NOT on the Org Sales Board yet" if board is False else "")
        log_rows.append([today.strftime("%m/%d/%Y"), bank.KIND_CAPTAINSHIP, n,
                         capt, did or f"added by {source}", board_txt])
        logfn(f"  ✚ new rep under {capt}: {n} (via {source})")

    try:
        bank.append_log(lws, log_rows, dry_run=dry_run, logfn=logfn)
        notify.post(lws, bank.KIND_CAPTAINSHIP,
                    notify.captainship_message(adds, today, siblings=siblings),
                    today, dry_run=dry_run, logfn=logfn)
    except Exception as e:  # noqa: BLE001 — the report's own add already stands
        logfn(f"  ⚠ captainship new-rep notice failed ({type(e).__name__}: "
              f"{str(e)[:100]})")
    return adds


def names_on_tab(sections) -> set:
    """Every rep that already had a row somewhere on a report tab.

    Takes the {section/box: {'rep_rows': {name: row}}} map every captainship
    fill builds (`find_sections` / `find_boxes`) and flattens it to one set of
    normalized names. Snapshot it BEFORE the fill's insert step — those maps are
    updated in place once rows are added.

    Read-only and total: a shape it doesn't recognise contributes nothing rather
    than raising, because its only caller is an advisory notice."""
    out: set = set()
    try:
        for sect in (sections or {}).values():
            for n in ((sect or {}).get("rep_rows") or {}):
                out.add(_norm(n))
    except Exception:  # noqa: BLE001 — advisory input, never fail the fill
        pass
    return out


def observe_added(added, *, captain: str, source: str, today=None, ss=None,
                  dry_run: bool = False, known=(), logfn=print) -> List[dict]:
    """The entry point every captainship report calls after its own fill.

    They all return `added` as {box/period: [names]} from `insert_missing_reps`
    — the same rep usually appears in every box, so the names are flattened and
    de-duped first.

    `known` — the reps the tab ALREADY carried before this run (see
    `names_on_tab`). A new row in ONE section of a tab that already knows the
    person is not a new rep: these tabs carry a 0-30 section and a 30-60 one,
    and the 30-60 metric is a 30-60-DAYS-AGO COHORT, so someone who joined ~45
    days ago debuts in that section long after their 0-30 row was filled. Read
    as "new", it asks Evelyn for a ✅ that can only resolve to "already had a
    row" — noise on a channel whose whole value is that a ✅ means something.
    (Audrey/Blue Mendoza under Starr, 2026-08-13: on the board since WE 7.19 and
    on the 0-30 rows since 7/23, proposed as new the day her 30-60 cohort
    matured.) Left empty, nothing is filtered and the old behaviour stands.

    This does NOT add anyone to the Org Sales Board. It opens the GATE: one line
    per rep in #revision-emails asking Evelyn for a ✅, and the board
    rows only appear once she ticks it (Eve, 2026-08-10 — the VA board
    that used to decide captainship membership is no longer maintained, so the
    decision is a person's again). See `captain_gate`."""
    from automations.new_owners import captain_gate
    if isinstance(added, dict):
        names = [n for v in added.values() for n in (v or [])]
    else:
        names = list(added or [])
    names = list(dict.fromkeys(names))   # a rep added in every box, listed once
    on_tab = {_norm(k) for k in (known or ())}
    if on_tab:
        matured = [n for n in names if _norm(n) in on_tab]
        names = [n for n in names if _norm(n) not in on_tab]
        if matured:
            logfn(f"  (not new to {captain_name(captain)} — already on this tab "
                  f"before the run, a maturing cohort: "
                  f"{', '.join(dict.fromkeys(matured))})")
    return captain_gate.propose(names, captain=captain, source=source,
                                today=today, ss=ss, dry_run=dry_run,
                                logfn=logfn)


def observe_org_board(auto_added: List[dict], *, today=None, ss=None,
                      dry_run: bool = False, logfn=print) -> List[dict]:
    """The Org Sales Board's own roster self-heal, as a source.

    `auto_added` is what `roster_sync.auto_insert_missing` returns:
    [{'captain': title, 'name': rep}]. Grouped per captain so each captainship
    gets one bullet list."""
    out: List[dict] = []
    by_cap: dict = {}
    for a in auto_added or []:
        by_cap.setdefault(captain_name(a.get("captain", "")), []).append(
            a.get("name", ""))
    for capt, names in by_cap.items():
        out += observe(names, captain=capt, source="Org Sales Board",
                       today=today, ss=ss, dry_run=dry_run, check_board=False,
                       did="added to the captainship's boxes on the Org Sales "
                           "Board", logfn=logfn)
    return out
