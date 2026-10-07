"""Daily EOD AppStream — 1st round, booked to 2nd, 2nd round retention by email (Camila, 2026-10-07).

Replaces the 'DAILY EOD APPSTREAM' sheet Perli fills by hand and sends to
Camila every evening as a screenshot plus a list of the offices in red.
One email, ~20:00 Argentina (18:00 CT while the US is on daylight time).

Camila's ask, in her words: "1st round showed, # booked to 2nd porcentaje de
eso y despues 2nd round retention con porcentaje. Arriba de 50% en verde,
abajo de 49% en rojo para 2nd round con un summary que me haga una lista de
las oficinas en rojo con su porcentaje."

WHERE EACH NUMBER COMES FROM — ApplicantStream -> Reports -> Retention Details
(p=701), one office at a time, the current Sun-Sat week, one column per day:
    1st B      'Total First Interviews'
    1st S      'First Interviews Showed Up'
    %          1st S / 1st B
    B to 2nd   'First Showed Up Booked Second'
    %          B to 2nd / 1st S
    2nd B      'Total Second Interviews'
    2nd S      'Second Interviews Showed Up'
    %          2nd S / 2nd B      <- the one Camila grades: >=50% green, <50% red
Checked against Perli's sheet (Andre Burton, Mon W/E 10/04):
43, 21, 49% | 3, 14% | 8, 5, 63%  — every % is computed the same way here.

WHICH OFFICES: the owners in the newest weekly block of
'Interviewers Retention (Interviewer)' (ARS Management 2.0) — the same roster
the Below the Mark board uses — and the same owner -> office id lookup.

THE RED LIST is today's 2nd round % under 50%, alphabetical, the way Perli
writes it. An office with no 2nd rounds booked today has no % and is not red.

    python -m automations.daily_eod_appstream.run --dry-run       # preview only
    python -m automations.daily_eod_appstream.run                 # mail to TEST_TO
    python -m automations.daily_eod_appstream.run --production    # mail to Camila
    python -m automations.daily_eod_appstream.run --date 2026-10-06 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:                                   # accents are safe on the Windows console
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "daily_eod_appstream"

ARS_MGMT_SHEET = "1l4Q0SreuddKZrgXwb9MytF-EdPZH-H1hLsa69epq-n8"   # ARS Management 2.0

PROD_TO = ["camilahk@arsinterviewsservice.com"]
TEST_TO = ["eve@alphaletemarketing.com"]   # Eve, until Camila signs off

GREEN_AT = 50          # 2nd round %, as SHOWN (whole number): >= green, < red

DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]

# fetch_office metric key -> our field. first_showed_booked_2nd is registered by
# first_to_second_below_mark.appstream (it is not in the shared METRICS map).
FIELDS = {
    "first_booked": "b1",
    "first_showed": "s1",
    "first_showed_booked_2nd": "b2nd",
    "second_booked": "b2",
    "second_showed": "s2",
}

# Owners the shared lookup misses, kept HERE so the Below the Mark board does
# not start pulling them as a side effect. Ids per megan-overrides.md ruling 6.
EXTRA_OFFICES = {
    "Raf Hildago 2nd F": "23965",      # sic — the roster tab's spelling
    "Raf Hidalgo 3rd F": "24065",
    "Salik Mallik": "23363",           # Eve 2026-10-07 (Hub had him sales-only)
}

GREEN_BG, RED_BG = "#57bb8a", "#e06666"


# ----------------------------------------------------------------- the math
def pct(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if not den:
        return None
    return (num or 0) / den


def day_row(raw: Dict[str, Dict[str, Optional[float]]], day: str) -> Dict[str, int]:
    return {f: int((raw.get(m) or {}).get(day) or 0) for m, f in FIELDS.items()}


def week_row(raw: Dict[str, Dict[str, Optional[float]]], upto: dt.date) -> Dict[str, int]:
    """Sum Sunday .. `upto` (AppStream's week starts Sunday)."""
    last = (upto.weekday() + 1) % 7               # 0 = Sunday
    tot = {f: 0 for f in FIELDS.values()}
    for day in DAYS[:last + 1]:
        for f, v in day_row(raw, day).items():
            tot[f] += v
    return tot


def red_list(today: Dict[str, Dict[str, int]]) -> List[Tuple[str, float]]:
    """Owners whose 2nd round % today is under GREEN_AT, alphabetical."""
    out = []
    for owner in sorted(today, key=str.lower):
        p = pct(today[owner]["s2"], today[owner]["b2"])
        if p is not None and whole_pct(p) < GREEN_AT:
            out.append((owner, p))
    return out


# ------------------------------------------------------------------- render
def whole_pct(p: float) -> int:
    """62.5% -> 63, the way Sheets shows it (Python's round() would say 62)."""
    return int(p * 100 + 0.5)


def _fmt_pct(p: Optional[float]) -> str:
    return "" if p is None else f"{whole_pct(p)}%"


_TD = ("border:1px solid #999;padding:3px 6px;text-align:center;"
       "font-size:12px;white-space:nowrap")


def _cells(r: Dict[str, int]) -> str:
    p2 = pct(r["s2"], r["b2"])
    bg = "" if p2 is None else (GREEN_BG if whole_pct(p2) >= GREEN_AT else RED_BG)
    vals = [r["b1"], r["s1"], _fmt_pct(pct(r["s1"], r["b1"])),
            r["b2nd"], _fmt_pct(pct(r["b2nd"], r["s1"])),
            r["b2"], r["s2"]]
    out = "".join(f'<td style="{_TD}">{v}</td>' for v in vals)
    out += f'<td style="{_TD};background:{bg or "#fff"};font-weight:bold">{_fmt_pct(p2)}</td>'
    return out


def table_html(today: Dict[str, Dict[str, int]], week: Dict[str, Dict[str, int]],
               day: dt.date) -> str:
    heads = ["1st B", "1st S", "%", "B to 2nd", "%", "2nd B", "2nd S", "%"]
    th = ("border:1px solid #999;padding:3px 6px;background:#d9d9d9;"
          "font-size:12px;white-space:nowrap")
    sub = "".join(f'<th style="{th}">{h}</th>' for h in heads) * 2
    rows = []
    for owner in sorted(today, key=str.lower):
        rows.append(f'<tr><td style="{_TD};text-align:left;font-weight:bold">'
                    f'{html.escape(owner)}</td>{_cells(today[owner])}'
                    f'{_cells(week[owner])}</tr>')
    tot_t = {f: sum(r[f] for r in today.values()) for f in FIELDS.values()}
    tot_w = {f: sum(r[f] for r in week.values()) for f in FIELDS.values()}
    rows.append(f'<tr><td style="{_TD};text-align:left;font-weight:bold;'
                f'background:#eee">TOTAL</td>{_cells(tot_t)}{_cells(tot_w)}</tr>')
    return (
        '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        'font-family:Arial,Helvetica,sans-serif">'
        f'<tr><th style="{th}" rowspan="2">Office</th>'
        f'<th style="{th};background:#00ffff" colspan="8">{day:%A} {day.month}/{day.day}'
        f'</th><th style="{th};background:#00ffff" colspan="8">WEEK SO FAR</th></tr>'
        f'<tr>{sub}</tr>' + "".join(rows) + '</table>')


def red_html(reds: List[Tuple[str, float]]) -> str:
    if not reds:
        return ('<p style="font-size:14px"><b>2nd round under 50% today:</b> '
                'none 🎉</p>')
    items = "".join(f"<li>{html.escape(o)} {whole_pct(p)}%</li>" for o, p in reds)
    return ('<p style="font-size:14px;margin:0 0 4px"><b>2nd round under 50% '
            f'today ({len(reds)}):</b></p><ul style="font-size:14px;margin:0 0 12px">'
            f'{items}</ul>')


def gaps_html(gaps: List[str]) -> str:
    if not gaps:
        return ""
    items = "".join(f"<li>{html.escape(g)}</li>" for g in gaps)
    return ('<p style="font-size:12px;color:#8a0000;margin:12px 0 4px">'
            f'<b>Could not pull ({len(gaps)}):</b></p>'
            f'<ul style="font-size:12px;color:#8a0000">{items}</ul>')


# --------------------------------------------------------------------- pull
def load_owners() -> List[str]:
    from automations.recruiting_report import fill
    from automations.first_to_second_below_mark import source as src
    sh = fill.open_by_key(ARS_MGMT_SHEET)
    weeks = src.parse_blocks(fill.worksheet_ci(sh, src.SOURCE_TAB).get_all_values())
    return [o.name for o in src.pick_week(weeks, None).owners]


def pull(owners: List[str], week_start: dt.date, *, logfn=print
         ) -> Tuple[Dict[str, dict], List[str]]:
    """{owner: raw per-day metrics} for one Sun-Sat week, one AppStream login."""
    from automations.recruiting_report import fetch_office
    from automations.first_to_second_below_mark import appstream as apst
    from automations.shared.tableau_patchright import appstream_direct_session

    apst._register_metric()
    index = apst.build_office_index()
    raw: Dict[str, dict] = {}
    gaps: List[str] = []
    targets = []
    for owner in owners:
        hit = apst.resolve_office(owner, index)
        if hit is None and owner in EXTRA_OFFICES:
            hit = (EXTRA_OFFICES[owner], "")
        if hit is None:
            gaps.append(f"{owner}: no AppStream office id")
        else:
            targets.append((owner, hit[0], hit[1]))
    logfn(f"  AppStream: {len(targets)} offices, week starting {week_start}")
    with appstream_direct_session(verbose=False) as page:
        for owner, office_id, hint in targets:
            try:
                got = fetch_office.fetch_one_daily(page, office_id, hint, week_start)
            except Exception as exc:                      # noqa: BLE001
                gaps.append(f"{owner} (office {office_id}): {type(exc).__name__}: {exc}")
                continue
            if not got:
                gaps.append(f"{owner} (office {office_id}): no AppStream access")
                continue
            raw[owner] = got
            logfn(f"    ok  {owner} ({office_id})")
    return raw, gaps


# --------------------------------------------------------------------- main
def build_and_send(day: dt.date, *, production: bool, dry_run: bool,
                   from_cache: Optional[Path] = None, logfn=print) -> int:
    from automations.shared import report_email

    week_start = day - dt.timedelta(days=(day.weekday() + 1) % 7)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = OUT_DIR / f"raw_{day.isoformat()}.json"
    if from_cache:
        data = json.loads(Path(from_cache).read_text(encoding="utf-8"))
        raw, gaps = data["raw"], data["gaps"]
    else:
        owners = load_owners()
        logfn(f"  roster: {len(owners)} owners")
        raw, gaps = pull(owners, week_start, logfn=logfn)
        cache.write_text(json.dumps({"raw": raw, "gaps": gaps}, indent=1),
                         encoding="utf-8")
    if not raw:
        logfn("  nothing pulled — not sending an empty report")
        return 1

    key = DAYS[(day.weekday() + 1) % 7]
    today = {o: day_row(r, key) for o, r in raw.items()}
    week = {o: week_row(r, day) for o, r in raw.items()}
    reds = red_list(today)

    body = red_html(reds) + table_html(today, week, day) + gaps_html(gaps)
    (OUT_DIR / f"preview_{day.isoformat()}.html").write_text(
        f"<html><body>{body}</body></html>", encoding="utf-8")
    logfn(f"  red today: {', '.join(f'{o} {whole_pct(p)}%' for o, p in reds) or 'none'}")
    if gaps:
        logfn(f"  gaps: {len(gaps)}")

    to = PROD_TO if production else TEST_TO
    res = report_email.send_boards(
        subject=f"Daily EOD AppStream — {day:%A} {day.month}/{day.day}",
        to=to, title="DAILY EOD APPSTREAM", blocks=[], intro_html=body,
        dry_run=dry_run, preview_dir=OUT_DIR, logfn=logfn)
    return 0 if res.get("ok", dry_run) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central time)")
    ap.add_argument("--dry-run", action="store_true", help="build the preview, send nothing")
    ap.add_argument("--production", action="store_true", help="send to Camila")
    ap.add_argument("--from-cache", help="reuse a raw_<date>.json instead of pulling")
    a = ap.parse_args(argv)
    if a.date:
        day = dt.date.fromisoformat(a.date)
    else:
        from zoneinfo import ZoneInfo
        day = dt.datetime.now(ZoneInfo("America/Chicago")).date()
    return build_and_send(day, production=a.production, dry_run=a.dry_run,
                          from_cache=Path(a.from_cache) if a.from_cache else None)


if __name__ == "__main__":
    raise SystemExit(main())
