"""Read an office's AppStream Calendar day by day -> one Interview per ARS row.

READ-ONLY on AppStream. Each day's raw rows are cached in
output/interviewer_retention/days_<office>.json, so a re-run only reads the
days it doesn't have yet (pass --refresh to re-read).

How a day becomes ARS rows (rules in from_calendar.py, proven on 11280 11/24):
  * FIRST INTERVIEWS rows -> one Interview each for everyone who showed up,
    under their Done By interviewer, dated that day.
  * SECOND INTERVIEWS rows -> one Interview each (date2 = that day), listed
    under the interviewer who ran that person's 1st round (card step 1.5):
    the person's most recent 1st-round row before that day. Reading a couple
    of weeks before the window gives those matches something to find.
    A person who got a 2nd round was Answered + Booked on their 1st-round row,
    whatever the invite status said ("copy what they type").
  * A Done By name the office's interviewer_names.json doesn't have is kept as
    the full name and reported -- never guessed.

    python -m automations.interviewer_retention.read --office 11280 --from 2026-09-28 --through 2026-11-21
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.interviewer_retention import boxes as bx
from automations.interviewer_retention import from_calendar as fc

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "interviewer_retention"


def cache_path(office: str) -> Path:
    return OUT_DIR / f"days_{office}.json"


def _sel(cell: str) -> str:
    m = re.search(r"SELECT=([^|;]*)", cell or "")
    return m.group(1).strip() if m else (cell or "").strip()


def _show(cell: str) -> str:
    c = cell or ""
    if "SELECT=" in c:
        return "offer"                 # 2nd round: the offer dropdown is showing
    if "(x)2" in c:
        return "radio2"
    if "(x)1" in c:
        return "radio1"
    return c.strip()                   # '2nd On Nov 25', 'First Day of Sales', or ''


def _phone(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-10:]


def parse_day(raw: List[List[str]]) -> Dict[str, List[Dict]]:
    """{'first': [...], 'second': [...]} of {name, phone, done_by, show, action, fus}."""
    heads, out = {}, {"first": [], "second": []}
    for r in raw:
        if r[0] == "SECTION":
            heads[r[1]] = r[2:]
            continue
        sec = r[1]
        kind = "second" if "SECOND" in sec.upper() else "first" if "FIRST INTERVIEW" in sec.upper() else ""
        if not kind:
            continue
        cells = dict(zip(heads.get(sec, []), r[2:]))
        name = f"{cells.get('First Name', '')} {cells.get('Last Name', '')}".strip()
        if not name:
            continue
        out[kind].append({"name": name, "key": fc._key(name),
                          "phone": _phone(cells.get("Phone", "")),
                          "done_by": _sel(cells.get("Done By", "")),
                          "show": _show(cells.get("Show Up", "")),
                          "action": cells.get("Action", ""),
                          "fus": _sel(cells.get("Follow Up Status", ""))})
    return out


def build(days: Dict[dt.date, List[List[str]]], names: Dict[str, str]
          ) -> Tuple[List[bx.Interview], Counter, List[str]]:
    """(interviews, unknown Done By names, 2nd rounds with no 1st round found)."""
    unknown, orphans = Counter(), []
    firsts: Dict[str, List[Tuple[dt.date, Dict]]] = {}
    parsed = {d: parse_day(raw) for d, raw in sorted(days.items())}

    def who(done_by: str) -> str:
        try:
            return fc.interviewer(done_by, names)
        except fc.UnknownInterviewer:
            unknown[done_by] += 1
            return done_by

    rows1: Dict[Tuple[str, dt.date], Dict] = {}
    for d, p in parsed.items():
        for r in p["first"]:
            got = fc.first_round(r["show"], r["action"], r["fus"])
            if got is None:
                continue
            q, a, b = got
            rec = {"interviewer": who(r["done_by"]), "date1": d, "qualify": q, "answer": a, "booked": b}
            rows1[(r["key"], d)] = rec
            firsts.setdefault(r["key"], []).append((d, rec))
    rows2 = []
    for d, p in parsed.items():
        for r in p["second"]:
            before = [x for x in firsts.get(r["key"], []) if x[0] < d]
            if not before:
                orphans.append(f"{d:%m/%d} {r['name']}")
                continue
            first = max(before, key=lambda x: x[0])[1]
            if first["qualify"] == bx.QUALIFY:
                first["answer"], first["booked"] = bx.ANSWERED, bx.BOOKED
            rows2.append(bx.Interview(first["interviewer"], None, booked=bx.BOOKED, date2=d,
                                      show2=fc.second_round(r["show"] == "offer", r["fus"])))
    rows = [bx.Interview(**rec) for rec in rows1.values()] + rows2
    return rows, unknown, orphans


def read_days(office: str, days: List[dt.date], headless: bool = True) -> Dict[dt.date, List[List[str]]]:
    from automations.late_join_audit import probe as lj
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.sms_thread_dump import run as dump
    out = {}
    with appstream_direct_session(headless=headless, verbose=False) as page:
        tok = dump._rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the AppStream console page")
        page.goto(f"https://www.applicantstream.com/index.cfm?p=104&rqst={tok}&newOfficeId={office}")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        for d in days:
            out[d] = lj._day_view(page, tok, d)
            n = sum(1 for r in out[d] if r[0] == "ROW")
            print(f"  {office} {d:%a %m/%d}: {n} rows", flush=True)
    return out


def load_cache(office: str) -> Dict[dt.date, List[List[str]]]:
    p = cache_path(office)
    if not p.exists():
        return {}
    return {dt.date.fromisoformat(k): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


def save_cache(office: str, days: Dict[dt.date, List[List[str]]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(office).write_text(json.dumps({d.isoformat(): v for d, v in sorted(days.items())},
                                             ensure_ascii=False), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="interviewer_retention.read")
    ap.add_argument("--office", required=True)
    ap.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--through", required=True, help="YYYY-MM-DD")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    lo, hi = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.through)
    want = [lo + dt.timedelta(days=i) for i in range((hi - lo).days + 1)]
    want = [d for d in want if d.weekday() != 6]                 # no Sundays
    have = load_cache(a.office)
    todo = want if a.refresh else [d for d in want if d not in have]
    print(f"{a.office}: {len(want)} days wanted, {len(todo)} to read")
    if todo:
        got = read_days(a.office, todo)
        have.update(got)
        save_cache(a.office, have)
    rows, unknown, orphans = build({d: have[d] for d in want if d in have}, fc.load_names(a.office))
    print(f"{len(rows)} ARS rows built | unknown Done By: {dict(unknown)} | "
          f"2nd rounds with no 1st round in range: {len(orphans)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
