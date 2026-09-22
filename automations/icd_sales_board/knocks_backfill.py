"""Put relay-only offices' knocks into the history, the same as every other.

THE GAP THIS CLOSES. 'Knocks Daily' is the one accumulating per-rep-per-day
knocks record, and it fills as a side effect of a run that POSTS a board: the
per-office knocks_run logs its rows, and (since 2026-09-22) so does Raf's own
total_knocks run. An office whose knocks arrive by LucyECO relay but whose
board is not posted by us never passes through either, so its days live only
in the 'ICD Knocks' tab — a transport buffer that is upserted in place, not a
history. Khalil is the example: relaying, and absent from every trend.

WHAT IT DOES NOT DO: pull anything. Every row here was already relayed by the
office's own machine. This reads two tabs and writes one.

THE ONE RULE IT MUST NOT BREAK: a PARTIAL day must never be written. append_day
is idempotent — a day already logged is skipped, never rewritten — so a day
written while the office was still knocking would freeze half a day as the
permanent record. So every gate the poster applies is applied here: the office
must be enrolled and active, the day must be FINISHED by the same
`day_is_complete` test, the relayed grid must pass the campaign guard, and the
rows must map. A day that is unfinished today is picked up by a later run, once
the office's own machine has completed it — which is why the window is days.

WHY IT DOES NOT SIMPLY CALL knocks_relay.relayed_rows. That function carries
one more gate, `_key_matches`, which asserts the ECO office key and the
OWNERVILLE office name it was handed agree — because its caller gets those from
two places and a drift there would draw one office's board from another's
numbers. It is the right check THERE and meaningless here, twice over: this
caller derives the name FROM the key, so there is nothing to disagree with, and
the check is satisfied by a lookup in the office_metrics registry, which by
definition does not hold a relay-only office. Applied here it rejects exactly
the offices this exists for — khalil-nds, roshan, ryan and carlos all fail it,
which is how the first run of this came back with nothing. So the gates are
recomposed from the same helpers rather than that one being loosened for
everybody.
"""
from __future__ import annotations

import datetime as dt

# How far back to look. The relay tab holds recent days only, and a day that
# stayed unfinished for a week is not going to finish now.
WINDOW_DAYS = 7


def _relay_days(values: list, window: list) -> dict:
    """{(office key, date): row} present on the relay tab inside the window.

    THE LAST ROW WINS for a repeated office-day, which is what the relay's own
    reader does: the tab is upserted in place and a later sweep's row is the
    more finished one."""
    from automations.icd_alerts import post as P
    out = {}
    for r in values[1:]:
        key = (r[0] or "").strip().lower() if r else ""
        if not key:
            continue
        try:
            day = dt.date.fromisoformat(P._day_key(r[1] if len(r) > 1 else ""))
        except (ValueError, IndexError):
            continue
        if day in window:
            out[(key, day)] = list(r) + [""] * (P.KN_MACHINES + 1 - len(r))
    return out


def rows_for(key: str, day: dt.date, row: list, office, log=print):
    """The board rows this office relayed for `day`, or None with a reason.

    Every gate knocks_relay.relayed_rows applies except the key/ownerville-name
    assertion (see the module docstring), reusing its own helpers so there is
    one implementation of each."""
    import json

    from automations.icd_alerts import campaign_guard, knocks_map as M
    from automations.rashad_metrics import knocks_relay as KR

    if not (office and getattr(office, "active", False)):
        return None, "not an active ECO office"
    ok, why = KR.day_is_complete(office, day, KR._received_at(row[5]))
    if not ok:
        return None, "not a finished day (%s)" % why
    try:
        raw = json.loads(row[2] or "[]")
    except ValueError:
        return None, "relayed unreadable rows"
    try:
        tracker = json.loads(row[3] or "[]")
    except ValueError:
        tracker = []
    # Checked on the RELAYED grid, not the mapped rows: to_rows normalises each
    # campaign's own columns into the shared vocabulary, so by then the very
    # thing that identifies a campaign is gone.
    bad = campaign_guard.check(getattr(office, "campaign", "") or "", raw)
    if bad:
        return None, bad
    rows = M.to_rows(raw, tracker)
    if not rows:
        # A machine that ran and saw nothing yet, an office on a campaign the
        # map does not cover, or a malformed grid. None of those is a quiet
        # day, and none of them belongs in the history as one.
        return None, "no drawable rows"
    return rows, ""


def _logged(grid: list) -> dict:
    """{date: {office cell lowered}} already in the history, from ONE read.

    knocks_log.already_logged re-reads the whole tab per question, which is a
    3,000-row read per office-day and the window can be fifty of those."""
    out: dict = {}
    for r in grid[1:]:
        if len(r) > 1:
            out.setdefault((r[0] or "").strip()[:10], set()).add(
                (r[1] or "").strip().lower())
    return out


def already_have(have: dict, name: str, day: dt.date) -> str:
    """The spelling this day is ALREADY filed under, or ''.

    MATCHED THE WAY THE READERS MATCH, not on the exact string — because a
    duplicate here is not a wasted row, it is a DOUBLED DAY. knocks_log's
    readers gather an office's rows by alias and by substring, so two spellings
    of one office are summed, and writing a day that is already on the tab
    under another name doubles every number on the board for it.

    That is not hypothetical: Kash relays as 'kash' with owner 'Kash Rai', and
    his days were already on the tab as 'Akashdeep Rai' from the scrape. An
    exact-string check saw nothing and would have written all eight of his days
    a second time (caught in a dry run, 2026-09-22)."""
    from automations.icd_sales_board import knocks_log as KL
    wanted = KL._wanted(name)
    for cell in have.get(day.isoformat(), ()):
        if any(w == cell or w in cell or cell in w for w in wanted):
            return cell
    return ""


def _office_name(office, *, sharing: bool = False) -> str:
    """The spelling to file this office's rows under.

    Title-cased when the registry holds it all in lower case ('carlos
    hidalgo'), because the Office column is read by people and the house look
    is title-cased names — and a second casing of one office is one more
    spelling for the reader to reconcile.

    THE CAMPAIGN IS APPENDED WHEN, AND ONLY WHEN, ONE OWNER HAS TWO FEEDS.
    The history is keyed (Date, Office) with no campaign column, so Carlos's
    Box feed and his AT&T B2B feed would land on the same key and collide —
    one silently dropped by append_day's idempotence, the other standing in
    for the whole office. Suffixing keeps them apart while the readers, which
    match by substring, still gather both under 'Carlos Hidalgo'. Every office
    with a single feed keeps its plain name, so nothing changes for anyone
    who does not need it."""
    name = (getattr(office, "owner", "") or "").strip()
    name = name.title() if name and name == name.lower() else name
    if not (name and sharing):
        return name
    from automations.icd_sales_board import eco_feeds as E
    camp = (getattr(office, "campaign", "") or "").strip()
    label = E.CAMPAIGNS.get(camp, (camp, ""))[0] or camp
    return f"{name} — {label}" if label else name


def _names_for_run(keys, offices: dict) -> dict:
    """{office key: the name to file under}, suffixing only shared names."""
    counts: dict = {}
    for k in keys:
        plain = _office_name(offices.get(k))
        if plain:
            counts[plain] = counts.get(plain, 0) + 1
    return {k: _office_name(offices.get(k),
                            sharing=counts.get(_office_name(offices.get(k)),
                                               0) > 1)
            for k in keys}


def run(days: int = WINDOW_DAYS, end: dt.date | None = None,
        dry_run: bool = False, log=print) -> int:
    """Log every finished relayed day that the history does not have yet.

    Returns the number of office-days written. Never raises: this runs beside
    real reporting and a history gap is not worth a failed batch."""
    from automations.icd_alerts import offices as O
    from automations.icd_sales_board import knocks_log as KL
    from automations.rashad_metrics import knocks_relay as KR
    from automations.recruiting_report.fill import open_by_key, _retry

    end = end or dt.date.today()
    window = [end - dt.timedelta(days=i) for i in range(1, max(1, days) + 1)]
    try:
        values = KR._knocks_values()
    except Exception as e:   # noqa: BLE001
        log(f"[knocks-backfill] cannot read the relay tab "
            f"({type(e).__name__}: {e}) — nothing to do.")
        return 0
    if not values:
        log("[knocks-backfill] no office has relayed knocks yet.")
        return 0
    try:
        grid = _retry(open_by_key(KL.SHEET_ID).worksheet(KL.TAB).get_all_values)
    except Exception as e:   # noqa: BLE001
        log(f"[knocks-backfill] cannot read the history "
            f"({type(e).__name__}: {e}) — refusing to write blind.")
        return 0
    have = _logged(grid)

    written = 0
    by_day = _relay_days(values, window)
    offices = {}
    for k in {k for k, _d in by_day}:
        try:
            offices[k] = O.get(k)
        except Exception:   # noqa: BLE001
            offices[k] = None
    names = _names_for_run(offices, offices)
    # WRITTEN THIS RUN counts as already having it: `have` is read once at the
    # start, so without this a second feed for the same day would not see the
    # first one land.
    done: set = set()
    for key, day in sorted(by_day):
        office = offices.get(key)
        name = names.get(key) or ""
        if not name:
            log(f"[knocks-backfill] {key} {day}: no owner on file — skipped.")
            continue
        if (name.lower(), day) in done:
            continue
        under = already_have(have, name, day)
        if under:
            continue          # already on the tab, under this or another spelling
        try:
            rows, why = rows_for(key, day, by_day[(key, day)], office)
        except Exception as e:   # noqa: BLE001
            log(f"[knocks-backfill] {key} {day}: {type(e).__name__}: {e}")
            continue
        if not rows:
            # Every refusal is 'not yet', and says which one — a fallback
            # nobody can see is indistinguishable from a change that never
            # shipped. A later run gets the day once the office's own machine
            # has finished it.
            log(f"[knocks-backfill] {name} {day}: {why} — left for later.")
            continue
        if dry_run:
            log(f"[knocks-backfill] would log {name} {day}: {len(rows)} rep(s)")
            done.add((name.lower(), day))
            written += 1
            continue
        try:
            n = KL.append_day(day, name, rows, verbose=False)
        except Exception as e:   # noqa: BLE001
            log(f"[knocks-backfill] {name} {day}: write failed "
                f"({type(e).__name__}: {e})")
            continue
        if n:
            log(f"[knocks-backfill] {name} {day}: {n} rep(s) kept")
            done.add((name.lower(), day))
            written += 1
    log(f"[knocks-backfill] {written} office-day(s) added to the history.")
    return written


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="icd_knocks_backfill")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS,
                    help="How many days back to look (default %d)."
                         % WINDOW_DAYS)
    ap.add_argument("--dry-run", action="store_true",
                    help="Say what would be logged; write nothing.")
    a = ap.parse_args(argv)
    run(days=a.days, dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
