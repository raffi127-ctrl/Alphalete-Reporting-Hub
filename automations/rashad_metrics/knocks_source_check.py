"""Did each office's metrics knocks board come from their OWN machine?

Megan 2026-09-17: "check the metrics threads in the morning -- add it to the
routines here so I know."

WHAT IT ANSWERS, per ECO office that also has a metrics thread:

  * did their machine CLOSE OUT the last selling day -- re-read it once the
    day was over -- or is the relay still holding whatever its last in-window
    sweep caught;
  * and was this morning's board therefore built from their own relayed rows,
    or did it fall back to a Lucy scraping OwnerVille on their behalf.

IT ASKS AS OF THE MOMENT THE BOARD WAS DRAWN, NOT THE MOMENT IT IS RUN.

The first version read the relay as it stood when the CHECK ran and called
that the board's source, which is only the same question when nothing lands
in between. On 2026-09-24 Aya's iMac closed 09-23 out at 07:37; her metrics
had already drawn and posted at 06:48. That board scraped. Both the
orchestrator's 07:35 copy and a hand run at 09:55 reported her green -- one
because the row had not landed yet, the other because by then it had -- and
the single morning the check existed to catch went unreported.

So the close-out is compared against WHEN THAT OFFICE'S METRICS ACTUALLY RAN,
read from the Hub Activity tab (shared.hub_activity.runs, matched on the
orchestrator's display_name -- most offices share the one `office-metrics`
card id, so the id cannot tell Aya's run from Kash's). A close-out that
landed after its board is its own verdict, LATE: nothing was lost, the scrape
covered it exactly as before, but the office relayed a perfectly good day
that the board never saw.

WHY IT IS A REPORT AND NOT A SLACK POST. Every other report already tells
Megan the same way: the orchestrator posts a FAILED or INCOMPLETE report into
#claudecorrections-and-requests as Lucy, in real time, with the re-run
command. A separate daily "all fine" message into a channel of failures is
the kind of standing noise that teaches people to skim the real ones, so this
says nothing when there is nothing to say.

WHAT FAILS THE CHECK AND WHAT DOES NOT. Three outcomes, two of which fail:

  OURS      the day was closed out BEFORE the board drew and the board still
            fell back to a scrape. A bug on this side -- the data was sitting
            there and we did not use it. FAILS.
  LATE      the machine closed the day out, but after its board had already
            drawn. Nobody's bug, and nothing was lost -- but a machine that
            closes out at all is a machine that was reachable, so this is a
            clock drifting, not hardware missing, and it costs a board every
            morning it happens until somebody moves it. FAILS (Megan,
            2026-09-24).
  ASLEEP    the machine never closed the day out at all. Cyrus's is the only
            laptop in the fleet and a shut laptop sleeps whatever we assert
            [[reference_eco_machine_hardware]], so this is expected, said
            plainly, and NOT a failure.

Nothing is lost in any of the three: the scrape covers the board exactly as
it did before any of this existed. What fails is only ever the thing somebody
can act on.

WHY LATE FAILS AND ASLEEP DOES NOT, given both are the office's machine. A
standing alarm every morning about a laptop doing what laptops do is worth
more damage than the thing it reports -- that is why ASLEEP stays quiet. LATE
is a different shape and, on the week this check watched (09-17..09-24), a
rarer one: the laptop closed out on time or not at all and never once landed
late, while Aya's iMac drifted into the morning twice and read as healthy
both times. Silence is the right default for the noisy case and the wrong one
for the quiet case.

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


def _stamp(when: Optional[dt.datetime]) -> str:
    """'Sep 24 07:37'. Built by hand, never '%-d' — that no-pad flag is a
    glibc extension and a literal '-d' on Windows, and every report here has
    to render the same on both (house rule)."""
    if when is None:
        return "?"
    return "%s %d %02d:%02d" % (when.strftime("%b"), when.day,
                                when.hour, when.minute)


def board_display_name(office_key: str) -> Optional[str]:
    """The Hub row an office's metrics run writes, i.e. its board's clock.

    The orchestrator's job key is `<office key>_metrics` and its display_name
    is what lands in Hub Activity's "Report Name" verbatim. Derived rather
    than listed: an office joining the metrics block needs no edit here, and
    an office that has no such job simply has no board time (None), which the
    caller reports as unknown instead of guessing.
    """
    import json
    from pathlib import Path

    path = (Path(__file__).resolve().parents[1]
            / "day_orchestrator" / "schedule_config.json")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception:           # noqa: BLE001
        return None
    job = (cfg.get("reports") or {}).get("%s_metrics" % office_key)
    name = (job or {}).get("display_name")
    return name or None


def board_time(office_key: str, day: dt.date, hub_values=None):
    """(first draw, last draw) of the board for `day`, or (None, None).

    The board for a finished day is drawn the next morning, so anything from
    midnight after `day` onward is a candidate and the EARLIEST is the board
    that actually went out. A later run the same morning is a redraw -- it
    matters only for saying that a close-out which missed the first board was
    picked up by the second.

    `hub_values` is the already-read Hub Activity tab and is NOT fetched here
    when it is missing. run() reads it once for the whole run (the Sheets read
    cap is per user and the Lucys share a login), and an unreadable tab has to
    degrade to "board time unknown" for everyone rather than turn one check
    into one read per office.
    """
    from automations.shared import hub_activity as HA

    if hub_values is None:
        return None, None
    name = board_display_name(office_key)
    if not name:
        return None, None
    floor = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min)
    got = HA.runs(name, since=floor, until=floor + dt.timedelta(days=1),
                  values=hub_values)
    if not got:
        return None, None
    return got[0][0], got[-1][0]


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


def check_office(eco, metrics_row, day: dt.date, values=None,
                 hub_values=None) -> Dict:
    """One office's verdict for `day`, as of when its board was drawn."""
    from automations.icd_alerts import post as P
    from automations.rashad_metrics import knocks_relay as KR

    drew, redrew = board_time(eco.key, day, hub_values=hub_values)
    out = {"key": eco.key, "owner": eco.owner, "day": day,
           "closed_out": False, "relayed": False, "received": None,
           "why": "", "fault": False, "late": False,
           "drew": drew, "redrew": redrew}

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
    out["reps"] = len(rows or [])

    # THE CLOSE-OUT HAS TO BEAT THE BOARD, not merely exist. Reading the relay
    # now and calling that the board's source is how 2026-09-24 passed clean:
    # the row was real, the board was drawn 49 minutes before it landed.
    if drew is not None and received is not None and received > drew:
        out["late"] = True
        out["why"] = ("closed out %s, after the board drew at %s"
                      % (_stamp(received), _stamp(drew)))
        if redrew is not None and redrew > received:
            out["why"] += (" — the %s redraw picked it up"
                           % redrew.strftime("%H:%M"))
        return out

    out["relayed"] = bool(rows)
    if not rows:
        # THE DAY WAS THERE AND WE DID NOT USE IT. Ours to fix. Only once the
        # close-out is known to have beaten the board: data that arrived after
        # the board drew was never ours to miss.
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

    # ONE read of Hub Activity for the whole run, not one per office: the
    # Sheets read cap is per USER and the Lucys share a login
    # [[reference_sheets_per_user_read_cap]].
    from automations.shared import hub_activity as HA
    try:
        from automations.recruiting_report.fill import open_by_key
        hub_values = open_by_key(HA.SHEET_ID).worksheet(HA.TAB).get_all_values()
    except Exception:           # noqa: BLE001
        hub_values = None

    log("Knocks source for %s (%s) — %d office(s) on both sides\n"
        % (day.isoformat(), day.strftime("%a"), len(pairs)))
    results = [check_office(eco, m, day, values, hub_values=hub_values)
               for eco, m in pairs]

    own = [r for r in results if r["relayed"]]
    faults = [r for r in results if r["fault"]]
    late = [r for r in results if r["late"]]
    asleep = [r for r in results if not r["relayed"] and not r["fault"]
              and not r["late"]]
    # Only where it would have changed the answer. An office that relayed
    # nothing is scraping whatever the board's clock says, and naming it here
    # too is the padding that makes the real line easy to skip.
    blind = [r for r in results if r["drew"] is None and r["closed_out"]]

    for r in sorted(results, key=lambda x: x["key"]):
        drew = (r["drew"].strftime("%H:%M") if r["drew"] else "time unknown")
        if r["relayed"]:
            log("  ✅ %-10s own machine — %d rep(s), closed out %s, board "
                "drew %s" % (r["key"], r.get("reps", 0),
                             _stamp(r["received"]), drew))
        elif r["fault"]:
            log("  ❌ %-10s %s" % (r["key"], r["why"]))
        elif r["late"]:
            log("  ⏰ %-10s scraped — %s" % (r["key"], r["why"]))
        else:
            log("  ·  %-10s scraped — %s" % (r["key"], r["why"]))

    log("\n%d of %d board(s) came from the office's own machine."
        % (len(own), len(results)))
    if asleep:
        log("Scraped (no failure — the machine simply did not close the day "
            "out): %s" % ", ".join(r["key"] for r in asleep))
    if blind:
        log("Board time unknown (no Hub Activity row for that morning) — "
            "judged on the relay alone: %s"
            % ", ".join(r["key"] for r in blind))

    # THE TWO FAILING KINDS ARE REPORTED SEPARATELY, because the thing to do
    # about them is different and a single blended line sends whoever reads
    # the alert to the wrong place. A fault is a code change here; a late
    # close-out is that office's machine waking up too late to matter.
    if faults:
        log("\nFAULT (ours — the data was there and the board scraped "
            "anyway): %s" % "; ".join("%s — %s" % (r["key"], r["why"])
                                      for r in faults))
    if late:
        log("\nLATE CLOSE-OUT (that office's machine — nothing was lost, the "
            "scrape covered the board): %s"
            % "; ".join("%s — %s" % (r["key"], r["why"]) for r in late))
        log("A machine that closes out at all was reachable, so this is a "
            "clock to move, not hardware to replace. It costs a board every "
            "morning until it is moved — which is why it fails rather than "
            "sitting in the log (Megan, 2026-09-24).")
    return 1 if (faults or late) else 0


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
