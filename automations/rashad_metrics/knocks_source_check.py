"""Did each office's metrics knocks board come from their OWN machine?

Megan 2026-09-17: "check the metrics threads in the morning -- add it to the
routines here so I know."

WHAT IT ANSWERS, per ECO office that also has a metrics thread:

  * did their machine CLOSE OUT the last selling day -- re-read it once the
    day was over -- or is the relay still holding whatever its last in-window
    sweep caught;
  * and would this morning's board therefore be built from their own relayed
    rows, or fall back to a Lucy scraping OwnerVille on their behalf.

WHY IT IS A REPORT AND NOT A SLACK POST. Every other report already tells
Megan the same way: the orchestrator posts a FAILED or INCOMPLETE report into
#claudecorrections-and-requests as Lucy, in real time, with the re-run
command. A separate daily "all fine" message into a channel of failures is
the kind of standing noise that teaches people to skim the real ones, so this
says nothing when there is nothing to say.

WHAT COUNTS AS A FAULT, AND WHAT DOES NOT. These are different failures with
different owners and only one of them is ours:

  OURS      the day WAS closed out and the board still fell back to a scrape.
            That is a bug on this side -- the data was sitting there and we
            did not use it -- and it fails the report.
  THEIRS    the machine never closed the day out. Cyrus's is the only laptop
            in the fleet and a shut laptop sleeps whatever we assert
            [[reference_eco_machine_hardware]], so this is expected, said
            plainly, and NOT a failure. Nothing was lost: the scrape covered
            it, exactly as it did before any of this existed.

A standing false alarm every morning about a laptop doing what laptops do is
worth more damage than the thing it reports.

    python -m automations.rashad_metrics.knocks_source_check
    python -m automations.rashad_metrics.knocks_source_check 2026-09-17
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# How far back "the day prior" may be. A Monday is looking at Saturday, and a
# Tuesday after a holiday Monday at the Saturday before it.
LOOK_BACK_DAYS = 3


def _last_selling_day(today: dt.date) -> dt.date:
    """The most recent day anybody was out. Sunday is nobody's selling day."""
    day = today - dt.timedelta(days=1)
    while day.weekday() == 6:
        day -= dt.timedelta(days=1)
    return day


def offices_to_check() -> List:
    """Offices on BOTH sides: relaying their own knocks AND getting metrics.

    An office with no metrics thread has no board for this to be about, and an
    office not enrolled in ECO has nothing to relay.
    """
    from automations.icd_alerts import offices as O
    try:
        from automations.office_metrics import offices as OM
    except Exception:  # noqa: BLE001
        return []
    metrics = dict(OM.OFFICES)
    return [(o, metrics[o.key]) for o in O.active() if o.key in metrics]


def check_office(eco, metrics_row, day: dt.date, values=None) -> Dict:
    """One office's verdict for `day`."""
    from automations.icd_alerts import post as P
    from automations.rashad_metrics import knocks_relay as KR

    out = {"key": eco.key, "owner": eco.owner, "day": day,
           "closed_out": False, "relayed": False, "received": None,
           "why": "", "fault": False}

    row = None
    for r in (values or [])[1:]:
        r = list(r) + [""] * (P.KN_MACHINES + 1 - len(r))
        if (r[0] or "").strip().lower() == eco.key \
                and P._day_key(r[1]) == day.isoformat():
            row = r
    if row is None:
        out["why"] = "relayed nothing for that day"
        return out

    received = KR._received_at(row[5])
    out["received"] = received
    ok, why = KR.day_is_complete(eco, day, received)
    out["closed_out"] = ok
    if not ok:
        out["why"] = why
        return out

    rows = KR.relayed_rows(eco.key, metrics_row.knocks_office, day,
                           log=lambda *a: None, values=values)
    out["relayed"] = bool(rows)
    out["reps"] = len(rows or [])
    if not rows:
        # THE DAY WAS THERE AND WE DID NOT USE IT. Ours to fix.
        out["fault"] = True
        out["why"] = ("the day was closed out but the board still fell back "
                      "to a scrape")
    return out


def run(day: Optional[dt.date] = None, log=print) -> int:
    from automations.rashad_metrics import knocks_relay as KR

    day = day or _last_selling_day(dt.date.today())
    pairs = offices_to_check()
    if not pairs:
        log("no office is both ECO-enrolled and on a metrics thread — "
            "nothing to check.")
        return 0

    values = KR._knocks_values()
    if values is None:
        log("could not read the relay workbook — cannot tell where this "
            "morning's boards came from.")
        return 1

    log("Knocks source for %s (%s) — %d office(s) on both sides\n"
        % (day.isoformat(), day.strftime("%a"), len(pairs)))
    results = [check_office(eco, m, day, values) for eco, m in pairs]

    own = [r for r in results if r["relayed"]]
    faults = [r for r in results if r["fault"]]
    asleep = [r for r in results if not r["relayed"] and not r["fault"]]

    for r in sorted(results, key=lambda x: x["key"]):
        if r["relayed"]:
            log("  ✅ %-10s own machine — %d rep(s), closed out %s"
                % (r["key"], r.get("reps", 0),
                   r["received"].strftime("%b %-d %H:%M")
                   if r["received"] else "?"))
        elif r["fault"]:
            log("  ❌ %-10s %s" % (r["key"], r["why"]))
        else:
            log("  ·  %-10s scraped — %s" % (r["key"], r["why"]))

    log("\n%d of %d board(s) came from the office's own machine."
        % (len(own), len(results)))
    if asleep:
        log("Scraped (no fault — the machine simply did not close the day "
            "out): %s" % ", ".join(r["key"] for r in asleep))
    if faults:
        log("\nFAULT: %s" % "; ".join("%s — %s" % (r["key"], r["why"])
                                      for r in faults))
        return 1
    return 0


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="rashad_metrics.knocks_source_check",
        description="Where this morning's metrics knocks boards came from. "
                    "Reads only — posts nothing, scrapes nothing.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: the last selling day)")
    args = ap.parse_args(argv)
    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else None)
    return run(day)


if __name__ == "__main__":
    raise SystemExit(main())
