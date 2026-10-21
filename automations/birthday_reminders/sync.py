"""Keep 'DOB LUCY' up to date on its own, every run, before anything is sent.

WHY (2026-10-21). Algemar Kennel's birthday and 1-year anniversary went by with
nothing from Lucy. The tab had been filled ONCE, on 9/13 -- 53 names -- and the
backfill docstring assumed new hires would arrive through apex_new_starts. They
never did: nothing called store.append after that day, so every rep who started
since was invisible.

What this does, append-only like the rest of the report:
  1. Everyone working on this week's sales board who isn't on the tab yet ->
     looked up in Blue Ink and added. No DOB found -> added anyway with the
     birthday blank (and a note), so the anniversary still works and a person
     can type the birthday in. Each person is looked up ONCE, not every day.
  2. A blank 'Start Date' on the tab -> filled from the board's own 'Start
     Date' column. A date already there (typed by hand) is never overwritten.

Staff (Algemar, leadership) are not on the sales board, so they are added by
hand with 'Staff' marked. This module never touches their rows.

A failure here is logged and the run carries on with the tab as it stands --
a sync problem must never cost somebody a reminder for a birthday we DO have.
"""
from __future__ import annotations

import datetime as dt
import re

from automations.birthday_reminders import config as C
from automations.birthday_reminders import store as S

# Raf's people tag new reps '(Wk 3)'; that is a label, not part of the name.
_WK_TAG = re.compile(r"\s*\(\s*wk\s*\d{1,2}\s*\)\s*", re.I)


def clean_name(name: str) -> str:
    return " ".join(_WK_TAG.sub(" ", str(name or "")).split())


def _md_y(d: dt.date) -> str:
    """'10/21/2025' -- by hand, never '%-m': a no-op on Windows."""
    return "%d/%d/%d" % (d.month, d.day, d.year)


def _is_rank(value) -> bool:
    """1, 2.0, '3' -> True; '', 'Teams', None -> False."""
    try:
        return float(str(value).strip()) > 0
    except (TypeError, ValueError):
        return False


def name_variants(name: str) -> list:
    """Other spellings someone may have signed their Blue Ink packet with.

    Ortencia Denice Martinez (10/21) is on the board under all three names;
    her packet is very likely 'Denice Martinez', which the first-name|surname
    match never tries. So: each middle name + surname, and a nickname in
    parentheses + surname ('Amjad (MJ) Malhas' -> 'MJ Malhas').
    """
    s = clean_name(name)
    nick = re.findall(r"\(([^)]*)\)", s)
    plain = " ".join(re.sub(r"\([^)]*\)", " ", s).replace("-", " ").split())
    parts = plain.split()
    out = []
    if len(parts) >= 2:
        last = parts[-1]
        out += ["%s %s" % (p, last) for p in parts[1:-1]]
        out += ["%s %s" % (n.strip(), last) for n in nick if n.strip()]
        if len(parts) > 2:
            out.append("%s %s" % (parts[0], last))
    seen, uniq = {s.lower()}, []
    for v in out:
        if v.lower() not in seen:
            seen.add(v.lower())
            uniq.append(v)
    return uniq


def _retry_birthdays(gaps, *, logfn=print) -> dict:
    """{sheet row: 'MM/DD'} for the people we can now find, trying their own
    name first and then every variant. Blue Ink failures -> {} (logged)."""
    from automations.birthday_reminders import backfill as BF
    asks = {}
    for e in gaps:
        for n in [clean_name(e.name)] + name_variants(e.name):
            asks.setdefault(n, e.row)
    try:
        hits = BF.gather(list(asks), logfn=lambda *a: None)
    except Exception as ex:  # noqa: BLE001
        logfn("  sync: ⚠ Blue Ink retry failed (%s)" % str(ex)[:120])
        return {}
    out = {}
    for h in hits:
        row = asks.get(h.name)
        if row and h.mmdd and row not in out:
            out[row] = h.mmdd
    return out


def board_people(today: dt.date, *, logfn=print) -> dict:
    """{name as on the board: start date or None} for everyone WORKING this
    week -- unmarked rows only, the same 'still here' test liveness uses."""
    from automations.birthday_reminders import backfill as BF
    from automations.recruiting_report.fill import open_by_key
    from automations.terminated_reps import board as B
    sh = open_by_key(B.SHEET_ID)
    title = B.pick_tab(sh, today)
    grid = sh.worksheet(title).get_values(value_render_option="UNFORMATTED_VALUE")
    lay = B.find_layout(grid)
    working = {B.base_name(n) for n in B._unmarked_names(grid)}
    out = {}
    for r in lay.roster_rows:
        raw = str(B._cell(grid, r, lay.name_col) or "").strip()
        name = clean_name(raw)
        # A real rep carries a rank number in the '#' column just left of the
        # names. The labels further down ('WE 1/12 - 1/18', 'Se7en Sins',
        # 'App per Rep AVG') don't -- and is_person() alone let 77 of them
        # through on 10/21, each looked up in Blue Ink as if it were a person.
        if not _is_rank(B._cell(grid, r, lay.name_col - 1)):
            continue
        if not BF.is_person(name) or B.base_name(raw) not in working:
            continue
        out[name] = B.to_date(B._cell(grid, r, lay.start_col))
    logfn("  sync: %d working rep(s) on %r" % (len(out), title))
    return out


def run(today: dt.date, *, dry_run: bool = True, logfn=print) -> dict:
    from automations.birthday_reminders import backfill as BF
    from automations.terminated_reps.board import base_name

    people = board_people(today, logfn=logfn)
    entries = S.load()
    have = S.index(entries)
    start_by_key = {base_name(n): d for n, d in people.items() if d}

    added_cols = S.ensure_columns(dry_run=dry_run)
    if added_cols:
        logfn("  sync: %s column(s) %s" % ("added" if not dry_run else "would add",
                                         ", ".join(added_cols)))

    # 1. new people
    new_names = [n for n in people if base_name(n) not in have]
    new = []
    if new_names:
        logfn("  sync: %d rep(s) not on the tab yet -- looking them up in Blue Ink"
              % len(new_names))
        try:
            found = {e.name: e for e in BF.gather(new_names, logfn=logfn)}
        except Exception as e:  # noqa: BLE001
            # Don't add them birthday-less: a row on the tab is never looked up
            # again, so a Blue Ink outage would cost them their birthday for good.
            logfn("  sync: ⚠ Blue Ink lookup failed (%s) -- not adding new reps "
                  "this run" % str(e)[:120])
            found, new_names = {}, []
        stamp = today.isoformat()
        for n in new_names:
            e = found.get(n) or S.Entry(
                name=n, mmdd="", source="sales board", added=stamp,
                notes="no birthday in Blue Ink -- type it in")
            d = people.get(n)
            e.start = _md_y(d) if d else ""
            new.append(e)
    res = S.append(new, dry_run=dry_run)
    for n in res["added"]:
        logfn("  sync: %s %s" % ("ADD " if not dry_run else "would add", n))
    for n, why in res["skipped"]:
        if why != "already on the tab":
            logfn("  sync: --   %s -- %s" % (n, why))

    # 2. blank birthdays on rows we already had, for reps still on the board --
    # retried every run, under every spelling they might have signed with.
    working_keys = {base_name(n) for n in people}
    gaps = [e for e in entries if not e.mmdd.strip() and not e.is_staff
            and e.key in working_keys]
    if gaps:
        found = _retry_birthdays(gaps, logfn=logfn)
        wrote_b = S.fill_blank(C.COL_MMDD, found, dry_run=dry_run)
        for e in gaps:
            if e.row in wrote_b:
                logfn("  sync: %s %s's birthday -- %s"
                      % ("filled" if not dry_run else "would fill", e.name,
                         found[e.row]))

    # 3. blank start dates on rows we already had
    fills = {e.row: _md_y(start_by_key[e.key]) for e in entries
             if not e.start.strip() and not e.is_staff and e.key in start_by_key}
    wrote = S.fill_blank(C.COL_START, fills, dry_run=dry_run)
    if wrote:
        logfn("  sync: %s %d start date(s) from the board"
              % ("filled" if not dry_run else "would fill", len(wrote)))
    return {"added": res["added"], "start_filled": wrote, "columns": added_cols}
