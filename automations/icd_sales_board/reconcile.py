"""The morning check: did yesterday's LIVE count match what Tableau settled?

The board shows the ECO relay's numbers while a day is happening (SaraPlus,
read on the office's own machine) and replaces them with Tableau's once the
day settles overnight. That swap used to be silent — nobody could see whether
the live board had been right. This makes it visible (Megan 2026-09-22): one
row per office per day in the 'Board Check' tab, and a one-line verdict on
that office's board.

WHY YESTERDAY. The 2am pull settles the day before; today is still live.

WHO CAN BE CHECKED. Only an office that BOTH relays and appears in the fiber
Tableau view. Offices selling other campaigns (B2B, Box/Service Cloud, NDS)
live in other workbooks and are reported as having no Tableau counterpart
rather than as a mismatch — a missing source is not a wrong number.

APPS is Int + DTV + NL, upgrades left out, the same rule as the board.

    python -m automations.icd_sales_board.reconcile              # yesterday
    python -m automations.icd_sales_board.reconcile --days 7     # the week
    python -m automations.icd_sales_board.reconcile --dry-run
"""
from __future__ import annotations

import datetime as dt

from automations.icd_sales_board import relay_read as RR
from automations.icd_sales_board import tableau_days as TD

MEASURES = ["Int", "Int Up", "DTV", "NL"]
SHEET_ID = TD.SHEET_ID
TAB = "Board Check"
COLUMNS = ["Date", "Office", "ICD", "Live apps", "Tableau apps", "Diff",
           "Match %", "Int (live/tab)", "Int Up (live/tab)",
           "DTV (live/tab)", "NL (live/tab)", "Reps off", "Only live",
           "Only Tableau", "Spelled two ways", "Checked"]
# A day this close is a match: a late-posting order or two is normal, and the
# board swaps in Tableau's number anyway. Below it, somebody should look.
MATCH_AT = 95.0


def _apps(v: dict) -> int:
    return sum(int(v.get(m, 0) or 0) for m in ("Int", "DTV", "NL"))


def pairs(log=print) -> list:
    """[(relay office key, Tableau owner name or '')] for every relaying office.

    Owners come from the ECO feed map (the ICD Signup tab plus the pilots), so
    'ryan' is Ryan McSpadden however either list spells him. Only an AT&T feed
    is paired with the fiber Tableau view: a Box feed compared against fiber
    numbers would report a mismatch that is really two different businesses —
    Carlos runs both."""
    from automations.icd_sales_board import eco_feeds as E
    owners = _owners()
    by_norm = {E.norm(o): o for o in owners}
    feeds = E.feeds()
    out = []
    for key in RR.offices():
        f = feeds.get(key)
        icd = ""
        if f and f.family == "att" and f.campaign not in ("b2b_att",):
            icd = by_norm.get(E.norm(f.owner), "")
        out.append((key, icd))
    return out


def _owners() -> set:
    from automations.recruiting_report.fill import open_by_key, _retry
    g = _retry(open_by_key(SHEET_ID).worksheet(TD.REP_TAB).get_all_values)
    if not g:
        return set()
    i = g[0].index("Owner") if "Owner" in g[0] else 0
    return {r[i].strip() for r in g[1:] if len(r) > i and r[i].strip()}


def _pair_spellings(lv: dict, tv: dict) -> list:
    """Fold a rep spelled two ways into one, and say which. -> [(live, tab)].

    'Callisa Flythe' live and 'Callista Flythe' in Tableau are one person, and
    counting them apart turned a clean day into 32% (Kash, Sep 15). Only a
    name missing from one side is paired, only with the same SURNAME, and only
    when the rest is within a letter or two — close enough to be a typo, far
    enough that two brothers are never merged. Listed so the alias can be
    fixed at the source rather than papered over here."""
    import difflib
    pairs = []
    only_l = [n for n in lv if n not in tv]
    only_t = [n for n in tv if n not in lv]
    for a in only_l:
        best, score = None, 0.0
        for b in only_t:
            if a.split()[-1:] != b.split()[-1:]:
                continue
            r = difflib.SequenceMatcher(None, a, b).ratio()
            if r > score:
                best, score = b, r
        if best and score >= 0.9:
            tv[a] = tv.pop(best)
            only_t.remove(best)
            pairs.append((a, best))
    return pairs


def check(office_key: str, icd: str, day: dt.date, tab_days=None) -> dict:
    """One office, one day: live vs settled, in totals and per rep."""
    live = RR.for_office(office_key, day, day).get(day) or {}
    base = {"Date": day.isoformat(), "Office": office_key, "ICD": icd}
    if not icd:
        return dict(base, status="no Tableau counterpart")
    if not live:
        return dict(base, status="no live reading")
    tab_all = tab_days if tab_days is not None else TD.stored_rep_days(icd)
    tab = {rep: days[day] for rep, days in tab_all.items() if day in days}

    lv = {n.strip().lower(): v for n, v in live.items()}
    tv = {n.strip().lower(): v for n, v in tab.items()}
    spelled = _pair_spellings(lv, tv)
    lt = {m: sum(int(v.get(m, 0) or 0) for v in lv.values()) for m in MEASURES}
    tt = {m: sum(int(v.get(m, 0) or 0) for v in tv.values()) for m in MEASURES}
    live_apps, tab_apps = _apps(lt), _apps(tt)

    off, gap = [], 0
    for rep in sorted(set(lv) | set(tv)):
        a, b = _apps(lv.get(rep, {})), _apps(tv.get(rep, {}))
        if a != b:
            off.append(f"{rep.title()} {a}/{b}")
            gap += abs(a - b)
    # Per REP, not per total: an office whose reps are each off in opposite
    # directions can land on the right total and still have a wrong board.
    match = max(0.0, 100.0 * (1 - gap / max(tab_apps, 1)))
    return dict(
        base, status="checked",
        **{"Live apps": live_apps, "Tableau apps": tab_apps,
           "Diff": live_apps - tab_apps, "Match %": round(match, 1),
           "Int (live/tab)": f"{lt['Int']}/{tt['Int']}",
           "Int Up (live/tab)": f"{lt['Int Up']}/{tt['Int Up']}",
           "DTV (live/tab)": f"{lt['DTV']}/{tt['DTV']}",
           "NL (live/tab)": f"{lt['NL']}/{tt['NL']}",
           "Reps off": "; ".join(off),
           "Only live": ", ".join(r.title() for r in sorted(set(lv) - set(tv))),
           "Only Tableau": ", ".join(r.title()
                                     for r in sorted(set(tv) - set(lv))),
           "Spelled two ways": "; ".join(f"{a.title()} = {b.title()}"
                                         for a, b in spelled)})


def store(results: list, log=print) -> int:
    """Upsert checked rows by (Date, Office). One whole-tab write."""
    from automations.recruiting_report.fill import open_by_key, _retry
    rows = [r for r in results if r.get("status") == "checked"]
    if not rows:
        return 0
    sh = open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(TAB)
    except Exception:   # noqa: BLE001
        ws = sh.add_worksheet(title=TAB, rows=2000, cols=len(COLUMNS))
    grid = _retry(ws.get_all_values) or [COLUMNS]
    head = grid[0] if grid and grid[0] else COLUMNS
    keep = {}
    for r in grid[1:]:
        rec = dict(zip(head, r))
        if rec.get("Date") and rec.get("Office"):
            keep[(rec["Date"], rec["Office"])] = rec
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for r in rows:
        keep[(r["Date"], r["Office"])] = dict(r, Checked=now)
    body = [COLUMNS] + [[str(rec.get(c, "")) for c in COLUMNS]
                        for _k, rec in sorted(keep.items(), reverse=True)]
    _retry(ws.clear)
    _retry(ws.update, values=body, range_name="A1",
           value_input_option="RAW")
    return len(rows)


# How many days back a campaign is fully settled when the 2am job runs. Box's
# extract publishes yesterday's sales DURING the day and the 14:30 catch-up
# fills it, so at 2am its newest settled day is two back — checking yesterday
# would call every Box office "off" every morning.
SETTLE_LAG = {"att": 1, "b2b_att": 1, "b2b_box": 2, "box": 2}
# Which stored office-day series a feed's campaign is compared with.
OFFICE_SERIES = {"b2b_box": "box", "box": "box", "b2b_att": "b2b"}


def _live_total(feed, reps: dict) -> int:
    """A feed's office total for one day, counted the way its Tableau counts.

    Box counts deals, which the agent relays as Sales. B2B counts units."""
    if feed.family == "box":
        return sum(int(v.get("Sales", 0) or 0) for v in reps.values())
    return sum(int(v.get(m, 0) or 0) for v in reps.values()
               for m in ("Int", "Int Up", "DTV", "NL"))


def check_office(feed, day: dt.date, series=None) -> dict:
    """Box / B2B: the office total, live vs settled. Tableau has no per-rep
    view for these campaigns, so this cannot say WHICH rep was off."""
    base = {"Date": day.isoformat(), "Office": feed.key, "ICD": feed.owner}
    live = RR.for_office(feed.key, day, day).get(day) or {}
    if not live:
        return dict(base, status="no live reading")
    from automations.icd_sales_board import eco_feeds as E
    settled = series if series is not None else TD.stored_office_days(
        E.names_for(feed), OFFICE_SERIES[feed.campaign])
    if day not in settled:
        return dict(base, status="not settled in Tableau")
    a, b = _live_total(feed, live), settled[day]
    match = max(0.0, 100.0 * (1 - abs(a - b) / max(b, 1)))
    return dict(base, status="checked",
                **{"Live apps": a, "Tableau apps": b, "Diff": a - b,
                   "Match %": round(match, 1),
                   "Reps off": "office total only — Tableau has no per-rep "
                               "view for this campaign"})


def run(days: int = 1, end: dt.date | None = None, dry_run: bool = False,
        log=print) -> list:
    """Check the last `days` settled days for every relaying office.

    `end` defaults per campaign to its newest SETTLED day (see SETTLE_LAG)."""
    from automations.icd_sales_board import eco_feeds as E
    results = []
    cache: dict = {}

    def _emit(r, key, day, first):
        results.append(r)
        if r["status"] == "checked":
            flag = "OK " if r["Match %"] >= MATCH_AT else "OFF"
            log(f"  {flag} {day} {key:14} live {r['Live apps']:4} "
                f"tableau {r['Tableau apps']:4}  {r['Match %']:5.1f}%"
                + (f"  | {r['Reps off']}" if r.get("Reps off")
                   and "office total" not in r["Reps off"] else ""))
        elif first:
            log(f"  --  {day} {key:14} {r['status']}")

    # AT&T fiber: per rep, against the fiber view
    for key, icd in pairs(log=log):
        if not icd:
            continue
        cache.setdefault(icd, TD.stored_rep_days(icd))
        last = end or dt.date.today() - dt.timedelta(days=SETTLE_LAG["att"])
        for i in range(days):
            day = last - dt.timedelta(days=i)
            _emit(check(key, icd, day, cache[icd]), key, day, i == 0)

    # Box and B2B: office totals, against their own workbooks
    feeds = E.feeds()
    for key in RR.offices():
        f = feeds.get(key)
        if not f or f.campaign not in OFFICE_SERIES:
            continue
        series = TD.stored_office_days(E.names_for(f), OFFICE_SERIES[f.campaign])
        last = end or dt.date.today() - dt.timedelta(
            days=SETTLE_LAG.get(f.campaign, 1))
        for i in range(days):
            day = last - dt.timedelta(days=i)
            _emit(check_office(f, day, series), key, day, i == 0)

    if not dry_run:
        log(f"board check: {store(results)} row(s) stored")
    return results


def latest(office_key: str) -> dict:
    """The newest checked row for one office, for the board's verdict line."""
    from automations.recruiting_report.fill import open_by_key, _retry
    try:
        g = _retry(open_by_key(SHEET_ID).worksheet(TAB).get_all_values)
    except Exception:   # noqa: BLE001 — no checks yet is not an error
        return {}
    if not g:
        return {}
    rows = [dict(zip(g[0], r)) for r in g[1:]]
    rows = [r for r in rows if r.get("Office") == office_key]
    return max(rows, key=lambda r: r.get("Date", ""), default={})


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="board_check")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--date", default="", help="Last day to check, "
                    "YYYY-MM-DD. Default: yesterday.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    end = dt.date.fromisoformat(a.date) if a.date else None
    run(days=a.days, end=end, dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
