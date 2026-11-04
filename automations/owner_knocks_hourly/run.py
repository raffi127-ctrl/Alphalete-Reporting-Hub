"""Text every org owner's knocks so far today into the "Alphalete Owners" chat.

RUNS ON LUCY 1 — Messages there is signed in as alphaletereporting@gmail.com
and is already in the owners chat (owner_sales_hourly texts it every hour).
Raf's 2026-10-29 ask: once an hour, the owners' knocking numbers, laid out like
his Total Knocks board (CHAN PARK TOTAL over OFFICE TOTAL) but one line per
owner in the org.

    TOTAL KNOCKS — ALPHALETE OWNERS — Thu 10/29 · 5:20 PM
    # Reps | Rep            | Leads | Knocks | ... | Sale | ...
    4 of 5 CHAN PARK          ...   (teal, comparison only, Raf 2026-11-03)
    D2D OWNERS
    18 of 20 KASH RAI         ...
    B2B OWNERS
    15 of 16 RYAN MCSPADDEN   ...
    100 of 120 D2D TOTAL      ...
    60 of 70 B2B TOTAL        ...
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


def segment_of(office) -> str:
    """D2D or B2B, off the office's campaign."""
    campaign = (getattr(office, "campaign", "") or "").strip().lower()
    return cfg.B2B if campaign.startswith("b2b") else cfg.D2D


def owner_rows(values: List[List[str]], offices: Dict, day: dt.date, *,
               skip_stale: bool = True, log=print) -> Dict[str, List[Dict]]:
    """{owner: today's rep rows, every office of theirs pooled}.

    `values` is the 'ICD Knocks' tab as read. A row whose relay stopped (the
    office's Mac is off) is left off instead of drawn with frozen numbers —
    the same rule the office's own board follows.

    Every time is put on the office's own clock (OwnerVille stamps them in the
    login's zone), and every row is tagged with its office's segment."""
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
        office = offices.get(key)
        raw, tracker = KP.shift_ov_clock(office, raw, tracker)
        rows = KM.to_rows(raw, tracker)
        if not rows:
            continue
        name = OSH.owner_name(key, office)
        out.setdefault(name, []).extend(_tagged(rows, segment_of(office)))
    return out


def _tagged(rows: List[Dict], segment: str) -> List[Dict]:
    return [dict(r, **{cfg.SEGMENT_FIELD: segment}) for r in rows]


def add_shared(everyone: Dict[str, List[Dict]],
               shared: Dict[str, List[Dict]]) -> None:
    """Offices a Lucy pulls (D2D) join the ECO rows. Skipped only for an owner
    ECO already brought D2D rows for, so nobody is counted twice: Carlos's B2B
    relay must not cost him his NDS crew."""
    for name, rows in shared.items():
        have = everyone.setdefault(name, [])
        if not any(r.get(cfg.SEGMENT_FIELD) == cfg.D2D for r in have):
            have.extend(_tagged(rows, cfg.D2D))


def chan_rows(day: dt.date, log=print) -> Optional[List[Dict]]:
    """Chan's rows for `day`, or None. No comparison is not a failed board, so
    nothing here may stop the text. The campaign is pinned: it is a sticky
    session setting and an unpinned pull can come back empty."""
    from automations.gap_alerts import config as GA
    from automations.knocks_intraday.run import compare_office
    from automations.rashad_metrics.knocks_pull import (
        campaign_for_office, pull_offices_days)
    try:
        who = compare_office()
        pulled = pull_offices_days(
            [(who, [day], campaign_for_office(who))], verbose=False,
            profile_dir=str(GA.PROFILE_DIR),
            session_wait_s=cfg.CHAN_SESSION_WAIT_S, priority="scheduled")
        _name, days, err = pulled[0]
        if err is not None:
            raise err
    except Exception as e:  # noqa: BLE001
        log("Chan's line left off: %s: %s" % (type(e).__name__, str(e)[:200]))
        return None
    rows = (days or {}).get(day) or []
    if not rows:
        log("Chan's line left off: no rows for %s" % day)
    return rows or None


def _knocks(rows: List[Dict]) -> int:
    from automations.icd_alerts import knocks_map as KM
    from automations.total_knocks import pull as TP
    return sum(KM._int(r.get(TP.COL_TOTAL_KNOCKS)) for r in rows)


def ranked(by_owner: Dict[str, List[Dict]]) -> List[Tuple[str, List[Dict]]]:
    """Most knocks first — the board is read as a leaderboard."""
    return sorted(by_owner.items(), key=lambda kv: (-_knocks(kv[1]), kv[0]))


def by_segment(by_owner: Dict[str, List[Dict]]
               ) -> List[Tuple[str, Dict[str, List[Dict]]]]:
    """[(D2D, {owner: rows}), (B2B, {owner: rows})], leaving off an empty one.
    A row with no tag is D2D."""
    out: Dict[str, Dict[str, List[Dict]]] = {}
    for name, rows in by_owner.items():
        for r in rows:
            seg = r.get(cfg.SEGMENT_FIELD) or cfg.D2D
            out.setdefault(seg, {}).setdefault(name, []).append(r)
    return [(seg, out[seg]) for seg in cfg.SEGMENTS if seg in out]


def render(by_owner: Dict[str, List[Dict]], day: dt.date, now: dt.datetime,
           chan: Optional[List[Dict]] = None):
    """One PNG: Chan's line, the D2D owners, the B2B owners, then a D2D TOTAL,
    a B2B TOTAL and the ORG TOTAL."""
    from automations.total_knocks import render as R

    out_dir = cfg.OUT_DIR / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    everyone = [r for rows in by_owner.values() for r in rows]
    segments = by_segment(by_owner)
    compare = [(cfg.CHAN_NAME, chan)] if chan else []
    lines = [line for _seg, owners in segments for line in ranked(owners)]
    # Only one group on the board: its total would just repeat the ORG TOTAL.
    subtotals = ([("%s TOTAL" % seg,
                   [r for rows in owners.values() for r in rows])
                  for seg, owners in segments] if len(segments) > 1 else [])
    return R.render_total_knocks(
        day, rows=everyone, out_dir=out_dir,
        title_suffix=cfg.BOARD_TITLE,
        extra_totals=compare + lines + subtotals,
        summary_only=True, total_label=cfg.TOTAL_LABEL,
        extra_label_suffix="", summary_tail=len(subtotals),
        summary_compare=len(compare),
        summary_groups=[("%s OWNERS" % seg, len(owners))
                        for seg, owners in segments],
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
    # Offices a Lucy pulls (Carlos's NDS crew).
    from automations.owner_knocks_hourly import share
    fresh = not args.force and not args.day
    add_shared(everyone, share.read(
        book, day, log=print,
        stale_minutes=cfg.LUCY_STALE_MINUTES if fresh else 0))
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

    # Only on the Mac that texts: an OwnerVille login from anywhere else would
    # knock Lucy 1's session off.
    chan = chan_rows(day) if sys.platform == "darwin" else None
    png = render(by_owner, day, now, chan)
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
