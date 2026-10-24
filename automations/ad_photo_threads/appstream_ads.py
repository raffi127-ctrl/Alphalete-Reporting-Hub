"""The ad a 1st-round candidate applied to, read off AppStream.

Eve 10/24 ("si"): the offices applicant_tracker doesn't import (Drew, Jairo,
Valeria, Colten, George...) had ~70 interviews in a week with a blank Ad Title
in the sheet and in Slack, and nobody answered the channel notes.

Where the ad is: AppStream's retention report (p=701) links each day's "Sent
to Call List" count to a detail table -- First, Last, Email, Phone, Rating,
Job Board, Date and Time, Ad -- the same table applicant_tracker imports into
the Call List tab for its 16 offices. Here it is read for the office that's
missing, over the days before the interview, READ-ONLY (nothing is written to
AppStream or to any sheet). Opening a record from the global search was tried
first (10/24) and is a dead end: its row link opens the applicant's history
popup, which has no ad.

What it found is kept in the state file (state[channel]["appstream_ads"],
{"YYYY-MM-DD|name": ad text or ""}) so collect.build uses it on every later
pass without opening AppStream again; "" = looked, nothing usable (not asked
twice).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

# An applicant is sent to the call list before the 1st round: 10/24 Antoinette
# Proveaux went 10/13 -> interview 10/22. Three weeks back covers the slow ones.
SENT_DAYS_BACK = 21
L_CALL_LIST = "Sent to Call List"      # the report row (applicant_tracker's label)
N_CALL_COLS = 8                        # First .. Ad, as applicant_tracker reads it


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", s.lower())).strip()


def key(day: dt.date, name: str) -> str:
    return f"{day.isoformat()}|{name.strip().lower()}"


def header(d: dt.date) -> str:
    """The report's column header for a day, "Oct 13, 2026" (no %-d: Windows)."""
    return f"{d:%b} {d.day}, {d.year}"


def ad_of(rows: List[List[str]], name: str) -> List[str]:
    """The distinct ads the detail rows have for `name` (first + last, as the
    sheet spells them; a middle name on either side still matches)."""
    from automations.ad_sales_board.names import strip_wrapper
    parts = _fold(name).split()
    if len(parts) < 2:
        return []
    out = []
    for r in rows:
        if len(r) < N_CALL_COLS:
            continue
        first, last = _fold(r[0]).split(), _fold(r[1]).split()
        if not first or not last:
            continue
        if first[0] == parts[0] and last[-1] == parts[-1]:
            ad = strip_wrapper(r[N_CALL_COLS - 1]).strip()
            if ad and ad not in out:
                out.append(ad)
    return out


def sent_rows(app, office_id: str, days: List[dt.date], debug: bool = False) -> List[List[str]]:
    """Every "Sent to Call List" detail row of `office_id` on `days`."""
    app.select_office(office_id)
    app.open_retention_details()
    hrefs = [(d, app.detail_href(L_CALL_LIST, header(d))) for d in days]
    if debug:
        print(f"  report columns found: {sum(1 for _, h in hrefs if h)} of {len(days)} days"
              f" ({', '.join(f'{d:%m/%d}' for d, h in hrefs if h) or 'none'})")
    rows: List[List[str]] = []
    for d, h in hrefs:
        if h:
            got = app.scrape_at(h, N_CALL_COLS)
            if debug:
                print(f"    {d:%m/%d}: {len(got)} sent to call list")
            rows += got
    return rows


def run(office_key: str, day: dt.date, *, names: Optional[List[str]] = None,
        apply: bool = False, limit: Optional[int] = None, debug: bool = True,
        lookback: Optional[int] = None, cache: Optional[dict] = None) -> Dict[str, object]:
    """Look up the office's blank-title interviews still on no thread
    (unthreaded.find). Prints what it finds; with `apply` keeps it."""
    from automations.ad_photo_threads import collect, config, post, unthreaded
    from automations.applicant_tracker.applicantstream import session

    o = config.office(office_key)
    config.use(o)
    if lookback:
        unthreaded.LOOKBACK_DAYS = lookback
    cache = {} if cache is None else cache
    todo = [(d, c) for d, c in unthreaded.find(day, cache=cache)
            if collect.blank_title(c.title_raw)]
    if names:
        want = {n.strip().lower() for n in names}
        todo = [(d, c) for d, c in todo if c.name.strip().lower() in want]
    channel = o["live_channel"]
    done = (post._load_state().get(channel) or {}).get("appstream_ads") or {}
    todo = [(d, c) for d, c in todo if key(d, c.name) not in done]
    if limit:
        todo = todo[:limit]
    print(f"[appstream ads] {office_key}: {len(todo)} candidate(s) to look up"
          + ("" if apply else " (dry run: nothing saved)"))
    if not todo:
        return {"looked": 0, "found": 0}
    first = min(d for d, _ in todo) - dt.timedelta(days=SENT_DAYS_BACK)
    days = [first + dt.timedelta(days=n) for n in range((day - first).days + 1)]
    oids = [s["office_id"] for s in config.SOURCES if s.get("office_id")]
    rows: List[List[str]] = []
    with session() as app:
        for oid in oids:
            rows += sent_rows(app, oid, days, debug=debug)
    got: Dict[str, str] = {}
    for d, c in todo:
        ads = ad_of(rows, c.name)
        got[key(d, c.name)] = ads[0] if len(ads) == 1 else ""
        print(f"  {c.name} ({d:%m/%d}): {ads or '-'}"
              + ("  -> 2+ ads, left for the channel" if len(ads) > 1 else ""))
    if apply and got:
        state = post._load_state()
        state.setdefault(channel, {}).setdefault("appstream_ads", {}).update(got)
        post._save_state(state)
    return {"looked": len(got), "found": sum(1 for v in got.values() if v)}
