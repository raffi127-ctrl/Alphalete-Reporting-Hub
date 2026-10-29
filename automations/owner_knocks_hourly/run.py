"""Text every org owner's knocks so far today into the "Alphalete Owners" chat.

RUNS ON LUCY 1 — Messages there is signed in as alphaletereporting@gmail.com
and is already in the owners chat (owner_sales_hourly texts it every hour).
Raf's 2026-10-29 ask: once an hour, the owners' knocking numbers, laid out like
his Total Knocks board (CHAN PARK TOTAL over OFFICE TOTAL) but one line per
owner in the org.

    TOTAL KNOCKS — ALPHALETE OWNERS — Thu 10/29 · 5:20 PM
    # Reps | Rep            | Leads | Knocks | ... | Sale | ...
    18 of 20 KASH RAI         ...
    15 of 16 HAYTHAM NAGI     ...
    ...
    60 of 70 EASTERN TOTAL    ...   (one per time zone, Raf 2026-10-29)
    100 of 120 CENTRAL TOTAL  ...
    160 of 190 ORG TOTAL      ...

Numbers are each office's Lucy ECO knocks relay for today ('ICD Knocks'), the
same rows its own knocks board is drawn from, pooled per OWNER (Khalil's NDS +
ATT, Carlos's two campaigns = one line each) and drawn by the SAME renderer as
every knocks board, so the columns match Raf's to the letter.

ONLY OUR ORG: the owners on the Org Sales Board's top boxes, the same filter
(and the same code) as owner_sales_hourly. Captains' downline owners are left
off; the run log names who.

Usage
  # dry-run (DEFAULT): draw the board, resolve the chat on a Mac, send nothing
  python -m automations.owner_knocks_hourly.run

  # live (what the LaunchAgent runs)
  python -m automations.owner_knocks_hourly.run --send

  --force       ignore the time window, stale relays and the unchanged skip
  --day DATE    draw another day (YYYY-MM-DD), for a preview

--send is the ONLY thing that texts anyone. Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Dict, List, Optional, Tuple

from automations.owner_knocks_hourly import config as cfg
from automations.owner_sales_hourly import run as OSH


def owner_rows(values: List[List[str]], offices: Dict, day: dt.date, *,
               skip_stale: bool = True, log=print) -> Dict[str, List[Dict]]:
    """{owner: today's rep rows, every office of theirs pooled}.

    `values` is the 'ICD Knocks' tab as read. A row whose relay stopped (the
    office's Mac is off) is left off instead of drawn with frozen numbers —
    the same rule the office's own board follows."""
    from automations.icd_alerts import knocks_map as KM, knocks_post as KP
    from automations.icd_alerts import post as P

    out: Dict[str, List[Dict]] = {}
    for row in values[1:]:
        row = list(row) + [""] * (KP.KN_POSTED + 1 - len(row))
        key = (row[KP.KN_OFFICE] or "").strip().lower()
        if not key or P._day_key(row[KP.KN_DAY]) != day.isoformat():
            continue
        if skip_stale and KP._too_old(row[KP.KN_RECEIVED]):
            log("%-14s last relayed %s — too old, left off"
                % (key, row[KP.KN_RECEIVED] or "?"))
            continue
        try:
            raw = json.loads(row[KP.KN_ROWS] or "[]")
            tracker = json.loads(row[KP.KN_TRACKER] or "[]")
        except ValueError:
            log("%-14s knocks JSON unreadable — left off" % key)
            continue
        rows = KM.to_rows(raw, tracker)
        if not rows:
            continue
        name = OSH.owner_name(key, offices.get(key))
        out.setdefault(name, []).extend(rows)
    return out


def _knocks(rows: List[Dict]) -> int:
    from automations.icd_alerts import knocks_map as KM
    from automations.total_knocks import pull as TP
    return sum(KM._int(r.get(TP.COL_TOTAL_KNOCKS)) for r in rows)


def ranked(by_owner: Dict[str, List[Dict]]) -> List[Tuple[str, List[Dict]]]:
    """Most knocks first — the board is read as a leaderboard."""
    return sorted(by_owner.items(), key=lambda kv: (-_knocks(kv[1]), kv[0]))


def owner_zones(offices: Dict) -> Dict[str, str]:
    """{owner name: IANA zone} from the offices' own settings."""
    out: Dict[str, str] = {}
    for key, office in offices.items():
        tz = (getattr(office, "timezone", "") or "").strip()
        if tz:
            out.setdefault(OSH.owner_name(key, office), tz)
    return out


def zone_totals(by_owner: Dict[str, List[Dict]],
                zones: Dict[str, str]) -> List[Tuple[str, List[Dict]]]:
    """[(EASTERN TOTAL, their rows), ...] east to west; [] if one zone."""
    known = dict(cfg.ZONE_LABELS)
    pooled: Dict[str, List[Dict]] = {}
    for name, rows in by_owner.items():
        tz = zones.get(name) or cfg.DEFAULT_ZONE
        if tz not in known:
            tz = cfg.DEFAULT_ZONE
        pooled.setdefault(tz, []).extend(rows)
    if len(pooled) < 2:
        return []
    return [(label, pooled[tz]) for tz, label in cfg.ZONE_LABELS
            if tz in pooled]


def render(by_owner: Dict[str, List[Dict]], day: dt.date, now: dt.datetime,
           zones: Optional[Dict[str, str]] = None):
    """One PNG: a line per owner, a total per time zone, ORG TOTAL under."""
    from automations.total_knocks import render as R

    out_dir = cfg.OUT_DIR / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    everyone = [r for rows in by_owner.values() for r in rows]
    subtotals = zone_totals(by_owner, zones or {})
    return R.render_total_knocks(
        day, rows=everyone, out_dir=out_dir,
        title_suffix=cfg.BOARD_TITLE,
        extra_totals=ranked(by_owner) + subtotals,
        summary_only=True, total_label=cfg.TOTAL_LABEL,
        extra_label_suffix="", summary_tail=len(subtotals),
        date_text="%s · %s" % (day.strftime("%a %m/%d"), OSH._clock(now)))


def signature(by_owner: Dict[str, List[Dict]]) -> str:
    """What 'nothing changed' compares: each owner's knocks."""
    return "\n".join("%s %d" % (n, _knocks(rows)) for n, rows in ranked(by_owner))


def in_window(now: dt.datetime) -> bool:
    span = cfg.WINDOW.get(now.weekday())
    return bool(span) and span[0] <= now.hour <= span[1]


def _last_path(day: dt.date):
    return cfg.OUT_DIR / day.isoformat() / "last_sent.txt"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true",
                    help="actually text the owners chat (default: dry run)")
    ap.add_argument("--force", action="store_true",
                    help="ignore the window, stale relays and the unchanged skip")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today, Central)")
    args = ap.parse_args(argv)

    now = OSH._now()
    day = dt.date.fromisoformat(args.day) if args.day else now.date()
    if not args.force and not in_window(now):
        print("outside the window (%s %s) — nothing to do"
              % (now.strftime("%a"), OSH._clock(now)))
        return 0

    from automations.icd_alerts import knocks_post as KP, offices as O
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key

    book = open_by_key(P.RELAY_SPREADSHEET_ID)
    values = book.worksheet(KP.KNOCKS_TAB).get_all_values()
    offices = O.all_offices()
    everyone = owner_rows(values, offices, day,
                          skip_stale=not args.force and not args.day)
    # Offices a Lucy pulls (Raf's) -- only for owners ECO did not already
    # bring, so nobody is counted twice.
    from automations.owner_knocks_hourly import share
    fresh = not args.force and not args.day
    for name, rows in share.read(
            book, day, log=print,
            stale_minutes=cfg.LUCY_STALE_MINUTES if fresh else 0).items():
        everyone.setdefault(name, rows)
    if not everyone:
        print("no office has relayed knocks for %s yet — not texting" % day)
        return 0

    # No board = no way to tell who is ours; fail loud, try again next hour.
    org = OSH.read_org_owners()
    if not org:
        print("Org Sales Board top boxes read empty — not texting")
        return 1
    by_owner = {n: rows for n, rows in everyone.items() if OSH._norm(n) in org}
    dropped = sorted(n for n in everyone if n not in by_owner)
    if dropped:
        print("not on the Org board's top boxes (left off): %s"
              % ", ".join(dropped))
    if not by_owner:
        print("no org owner has relayed knocks yet — not texting")
        return 0

    sig = signature(by_owner)
    print(sig)
    last = _last_path(day)
    if (not args.force and last.exists()
            and last.read_text(encoding="utf-8") == sig):
        print("same knocks as the last text — skipped")
        return 0

    png = render(by_owner, day, now, owner_zones(offices))
    print("board: %s" % png)

    dry = not args.send
    if sys.platform != "darwin":
        if not dry:
            print("--send only works on a Mac with Messages (Lucy 1)")
            return 1
        print("[dry-run] not a Mac — chat resolution skipped, nothing sent")
        return 0

    from automations.b2b_dispositions import text_post as T
    try:
        # The picture alone (Megan 2026-09-15: "just the chart photo is
        # fine") — its title already says whose board and what time.
        res = T.send_to_group(cfg.TEXT_GROUP, "", [png], dry_run=dry)
    except Exception as e:  # noqa: BLE001
        print("text failed: %s" % e)
        return 1
    print("%s -> %s (%s people)" % ("[dry-run] would text" if dry else "texted",
                                    res.get("resolved_name"),
                                    res.get("participants") or "?"))
    if not dry:
        last.parent.mkdir(parents=True, exist_ok=True)
        last.write_text(sig, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
