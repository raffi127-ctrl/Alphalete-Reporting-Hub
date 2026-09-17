"""The knocks board's rows from the office's OWN machine, not our scrape.

WHY THIS EXISTS. The knocks section is the only metric in the whole office
metrics flow that scrapes ownerville -- impersonate the office, read the
Disposition page and the Time Tracker, exit. It is one subprocess carrying
two boards, so when it times out BOTH Knocks and Time Gaps vanish at once and
nothing retries them (2026-07-21: four of seven offices lost both). Meanwhile
every ECO-enrolled office's laptop has already relayed that exact pair of
tables to the 'ICD Knocks' tab. We were paying for the data twice and
publishing the less reliable copy. Megan's direction, 2026-09-13: knocks move
to the ICD machines and the rollups read what they relayed.

THIS NEVER RAISES AND NEVER GUESSES. Every question it cannot answer with
certainty is answered "scrape": a returned None means the caller does exactly
what it did before. The scrape is not going away -- it stays the fallback for
an office whose machine was off, and it is the only path at all for the
offices that are not enrolled yet.

RUN IT DIRECTLY to see what an office's relayed board would be, with no
ownerville session and nothing posted:

    python -m automations.rashad_metrics.knocks_relay --office kash
    python -m automations.rashad_metrics.knocks_relay --office kash 2026-09-16
    python -m automations.rashad_metrics.knocks_relay --all 2026-09-16
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Dict, List, Optional

# WHICH OFFICES READ THE RELAY. One office first, then widen once a full day
# has been watched -- the same canary shape as _HARVEST_ORDER_LOG_OFFICES in
# the office_metrics runner, and for the same reason: this changes where a
# published number comes from, and the way to find out it is wrong is to be
# watching one board, not seven.
#
# Kash is the pilot: he is one of only two metrics offices enrolled in ECO,
# and his machine has relayed a complete day every day this week.
#
# Override with KNOCKS_RELAY_OFFICES:
#     "kash,cyrus"  those offices        "all"  every enrolled office
#     ""            FULL ROLLBACK to the scrape for everyone
ROLLOUT_OFFICES = {"kash"}
ROLLOUT_ENV = "KNOCKS_RELAY_OFFICES"

# HOW LATE THE LAST RELAY MAY BE AND THE DAY STILL COUNT AS FINISHED.
#
# This is a DIFFERENT question from the one knocks_post asks, and answering it
# with knocks_post's STALE_MINUTES would be wrong in both directions. That
# board is drawn intraday and asks "is this reading current?"; this one is
# drawn the next morning about a day that is over, and asks "was the machine
# still running when the day ENDED?". By its own rule every completed day is
# stale, and by this one a machine that died at lunchtime is not merely late
# -- it is missing the whole evening.
#
# Khalil Mansour's agent died at 16:58 on 2026-09-16 and his intraday boards
# went on re-sending 16:58's knocks with a fresh timestamp. The morning
# version of that mistake is quieter and worse: a board of two-thirds of a
# day, published as the day, that nobody can tell from the real thing.
END_GRACE_MIN = 20

# And an upper bound, because a row that was written long after the day it is
# keyed to is a re-push we cannot account for. Scrape instead of guessing.
END_WINDOW_H = 12


def _rollout() -> Optional[set]:
    """The enrolled offices allowed to read the relay. None means 'all'."""
    raw = os.environ.get(ROLLOUT_ENV)
    if raw is None:
        return set(ROLLOUT_OFFICES)
    raw = raw.strip()
    if raw.lower() == "all":
        return None
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _norm_name(s) -> str:
    return " ".join(str(s or "").split()).strip().lower()


def office_key_for(office_name: str) -> Optional[str]:
    """The office_metrics key whose ownerville name is `office_name`.

    THE TWO KEY SPACES ARE NOT THE SAME and must never be assumed to be. The
    relay keys by ECO office key ('kash'); the scrape is targeted by the
    OWNERVILLE name, which for the same office is 'Akashdeep Rai'. Four of the
    thirteen metrics offices differ that way today -- kash, hammad, salik and
    nii -- and 'trang' is a third spelling again. A join that guessed would
    silently draw one office's board from another office's numbers, which is
    the one error nobody reading the board could catch.
    """
    try:
        from automations.office_metrics import offices as OM
    except Exception:  # noqa: BLE001
        return None
    want = _norm_name(office_name)
    for key, off in dict(OM.OFFICES).items():
        if _norm_name(getattr(off, "knocks_office", "")) == want:
            return key
    return None


def _key_matches(office_key: str, office_name: str) -> bool:
    """Does `office_key` really name the office we were asked to pull?

    ASSERTED, not assumed (see office_key_for). The caller hands us both --
    the key from the runner's registry row and the ownerville name from
    KNOCKS_OFFICE -- and they come from the same row, so disagreeing means
    something upstream has drifted. Refuse and scrape.
    """
    try:
        from automations.office_metrics import offices as OM
        off = dict(OM.OFFICES).get((office_key or "").strip().lower())
    except Exception:  # noqa: BLE001
        return False
    if off is None:
        return False
    return _norm_name(getattr(off, "knocks_office", "")) == _norm_name(office_name)


def _received_at(text: str) -> Optional[dt.datetime]:
    """When the relay took this row in. None when it cannot be read.

    TWO FAMILIES OF FORMAT, BECAUSE THE SHEET WRITES ONE AND THE MACHINE THE
    OTHER: 'Received At' comes back from Sheets as 9/16/2026 21:31:53 while
    the machine's own clock column is ISO. A parser that handled only ISO
    would find every row unreadable, which here means every office falls back
    to the scrape and the change looks like it did nothing at all. Same list
    as icd_alerts.knocks_post._received_at, same reason.
    """
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _window_end(office, day: dt.date) -> Optional[str]:
    """When THIS office's field day ends, on the office's own clock.

    Per office and per weekday, from the ECO row -- Kash finishes at 20:30 and
    his Saturday at 17:00, and Cyrus's Saturday is an hour earlier again. A
    shared cutoff would call one office's finished day incomplete and accept
    another's half day.
    """
    if day.weekday() == 6:                       # Sunday: nobody is out
        return None
    if day.weekday() == 5:
        return office.sat_end if getattr(office, "saturday", True) else None
    return office.day_end


def day_is_complete(office, day: dt.date, received: Optional[dt.datetime],
                    ) -> "tuple[bool, str]":
    """Was the machine still relaying when this day finished?

    (True, "") or (False, why). UNREADABLE MEANS NO, which is the opposite of
    what knocks_post does with the same column, and deliberately: there the
    cost of refusing is an office's live board going quiet for a tick, and
    here it is one extra scrape -- exactly what happened before this existed.
    Falling back is cheap, so there is no reason to publish on a maybe.
    """
    end = _window_end(office, day)
    if end is None:
        return False, "%s is not a field day for this office" % day.isoformat()
    if received is None:
        return False, "no readable 'Received At'"
    try:
        h, m = (int(p) for p in str(end).split(":"))
    except Exception:  # noqa: BLE001
        return False, "unreadable day_end %r" % (end,)
    closes = dt.datetime.combine(day, dt.time(h, m))
    if received < closes - dt.timedelta(minutes=END_GRACE_MIN):
        return False, ("machine stopped at %s, before the day ended at %s"
                       % (received.strftime("%H:%M"), end))
    if received > closes + dt.timedelta(hours=END_WINDOW_H):
        return False, ("relayed %s, long after the day ended at %s"
                       % (received.strftime("%Y-%m-%d %H:%M"), end))
    return True, ""


def _knocks_values() -> Optional[List[List[str]]]:
    """The 'ICD Knocks' tab, or None if it cannot be read at all."""
    try:
        from automations.icd_alerts import post as P
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(P.RELAY_SPREADSHEET_ID)
        return book.worksheet(P.KNOCKS_TAB).get_all_values()
    except Exception:  # noqa: BLE001 — a relay we cannot read is a scrape
        return None


def relayed_rows(office_key: str, office_name: str, day: dt.date,
                 *, log=print, values=None) -> Optional[List[Dict]]:
    """The board rows this office's own machine relayed for `day`.

    None means SCRAPE, and every refusal below says out loud which one it was
    -- a fallback nobody can see is indistinguishable from a change that never
    shipped.
    """
    from automations.icd_alerts import offices as O

    key = (office_key or "").strip().lower()
    if not key:
        log("[knocks-relay] no office key given — scraping.")
        return None

    allowed = _rollout()
    if allowed is not None and key not in allowed:
        log("[knocks-relay] %s is not in the relay rollout yet — scraping."
            % key)
        return None

    if not _key_matches(key, office_name):
        derived = office_key_for(office_name) or "?"
        log("[knocks-relay] ⚠ office key %r does not name %r (that ownerville "
            "name is %r) — scraping rather than risk another office's numbers."
            % (key, office_name, derived))
        return None

    try:
        office = O.get(key)
        enrolled = bool(office) and O.is_enrolled(key) and office.active
    except Exception:  # noqa: BLE001
        office, enrolled = None, False
    if not enrolled:
        log("[knocks-relay] %s is not an active ECO office — scraping." % key)
        return None

    if values is None:
        values = _knocks_values()
    if values is None:
        log("[knocks-relay] could not read the relay workbook — scraping.")
        return None

    from automations.icd_alerts import post as P
    want = day.isoformat()
    row = None
    for r in values[1:]:
        r = list(r) + [""] * (P.KN_MACHINES + 1 - len(r))
        if (r[0] or "").strip().lower() == key and P._day_key(r[1]) == want:
            row = r
    if row is None:
        log("[knocks-relay] %s relayed nothing for %s — scraping." % (key, want))
        return None

    received = _received_at(row[5])
    ok, why = day_is_complete(office, day, received)
    if not ok:
        log("[knocks-relay] %s %s is not a finished day (%s) — scraping."
            % (key, want, why))
        return None

    try:
        raw = json.loads(row[2] or "[]")
    except ValueError:
        log("[knocks-relay] %s %s relayed unreadable rows — scraping."
            % (key, want))
        return None
    try:
        tracker = json.loads(row[3] or "[]")
    except ValueError:
        tracker = []

    # THE GRID MUST BE THE CAMPAIGN THIS OFFICE IS ENROLLED AS, checked on the
    # RELAYED grid rather than the mapped rows: to_rows() normalises each
    # campaign's own columns into the shared board vocabulary, so by then the
    # very thing that identifies a campaign is gone. Calvin's Box-shaped board
    # published under an ENERGYWELL heading on 2026-09-02 and read fine.
    from automations.icd_alerts import campaign_guard, knocks_map as M
    bad = campaign_guard.check(getattr(office, "campaign", "") or "", raw)
    if bad:
        log("[knocks-relay] %s %s — %s — scraping." % (key, want, bad))
        return None

    rows = M.to_rows(raw, tracker)
    if not rows:
        # EMPTY IS NOT A QUIET DAY HERE. A relayed row with nothing in it is a
        # machine that ran and saw nothing yet, an office switched to a
        # campaign the map does not cover, or a grid that arrived malformed --
        # and turning any of those into a 'No data available' post is the
        # blank board Megan has a standing rule against. Let the scrape say
        # whether the day was genuinely empty.
        log("[knocks-relay] %s %s relayed no drawable rows — scraping."
            % (key, want))
        return None

    log("[knocks-relay] ✅ %s %s — %d rep(s) from %s's own machine "
        "(relayed %s). No ownerville impersonation needed."
        % (key, want, len(rows), office.owner,
           received.strftime("%H:%M") if received else "?"))
    return rows


# --- preview -----------------------------------------------------------------
def main(argv=None) -> int:
    import argparse

    from automations.total_knocks.pull import _yesterday

    ap = argparse.ArgumentParser(
        prog="rashad_metrics.knocks_relay",
        description="What an office's relayed knocks board would be. "
                    "Reads only; never posts and never opens ownerville.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday, Central)")
    ap.add_argument("--office", default=None,
                    help="office key, e.g. kash")
    ap.add_argument("--all", action="store_true",
                    help="every metrics office, rollout ignored")
    args = ap.parse_args(argv)

    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else _yesterday())
    from automations.office_metrics import offices as OM
    from automations.total_knocks.render import knocks_shape
    registry = dict(OM.OFFICES)
    if args.all:
        os.environ[ROLLOUT_ENV] = "all"
        keys = sorted(registry)
    elif args.office:
        keys = [args.office.strip().lower()]
    else:
        ap.error("give --office KEY or --all")
        return 2

    values = _knocks_values()
    for key in keys:
        off = registry.get(key)
        if off is None:
            print("%-10s not an office_metrics office" % key)
            continue
        rows = relayed_rows(key, off.knocks_office, day, values=values)
        if rows:
            print("%-10s %s  %d rep(s), %s board, %d knocks"
                  % (key, day, len(rows), knocks_shape(rows),
                     sum(int(r.get("Total Knocks") or 0) for r in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
