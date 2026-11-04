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
pass without opening AppStream again; "" = looked, nothing usable.

Eve 10/29: a "" is looked at again on the next evenings, up to MAX_TRIES
evenings in all (state[channel]["appstream_ads_tries"], {key: [ISO days
tried]}) -- people are sometimes sent to the call list late. Only after that
does unthreaded.py move them to the channel's pinned "no ad" thread.
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
MAX_TRIES = 3                          # evenings a "" is looked up before giving up
# Eve 11/4, what was still missed: the interview's own row carries the ad too
# (Natahja Quinn, Nannerl Nanga), some sat on the call list longer than 3 weeks
# (Jamea Robinson: 5), and spellings differ (Hyacinthe/Hyacinthie).
L_INTERVIEWS = "Total First Interviews"
INTERVIEW_DAYS = 3                     # the sheet's date can be off from AppStream's
FAR_DAYS_BACK = 45                     # second pass, only for who is still missing
CLOSE_RATIO = 0.85                     # one name part spelled a little differently


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", s.lower())).strip()


def key(day: dt.date, name: str) -> str:
    return f"{day.isoformat()}|{name.strip().lower()}"


def tries(ch_state: dict, k: str) -> int:
    """Evenings `k` was looked up. A "" from before the count was kept
    (10/29) counts as one."""
    got = len((ch_state.get("appstream_ads_tries") or {}).get(k) or [])
    return max(got, 1) if k in (ch_state.get("appstream_ads") or {}) else got


def gave_up(ch_state: dict, k: str) -> bool:
    """Looked up MAX_TRIES evenings and nothing found."""
    found = (ch_state.get("appstream_ads") or {}).get(k)
    return found == "" and tries(ch_state, k) >= MAX_TRIES


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
        # Valeria 10/27: "Carmelo Alduen Arias" -- a second last name on
        # either side (sheet or AppStream) still matches.
        if first[0] == parts[0] and (last[-1] == parts[-1] or last[-1] in parts[1:]
                                     or parts[-1] in last):
            ad = strip_wrapper(r[N_CALL_COLS - 1]).strip()
            if ad and ad not in out:
                out.append(ad)
    return out


def ad_of_close(rows: List[List[str]], name: str) -> List[str]:
    """Like ad_of with one name part spelled a little differently (the other
    exact). Only for who nothing exact was found for."""
    import difflib
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
        a = difflib.SequenceMatcher(None, first[0], parts[0]).ratio()
        b = difflib.SequenceMatcher(None, last[-1], parts[-1]).ratio()
        if (a == 1 and b >= CLOSE_RATIO) or (b == 1 and a >= CLOSE_RATIO):
            ad = strip_wrapper(r[N_CALL_COLS - 1]).strip()
            if ad and ad not in out:
                out.append(ad)
    return out


def near(rows: List[List[str]], name: str) -> List[str]:
    """"First Last" of the rows sharing the first OR the last name -- printed
    when nothing matched, to see how AppStream spells the person."""
    parts = _fold(name).split()
    out = []
    for r in rows:
        first, last = (_fold(r[0]).split(), _fold(r[1]).split()) if len(r) >= 2 else ([], [])
        if parts and (first[:1] == parts[:1] or last[-1:] == parts[-1:]):
            who = f"{r[0]} {r[1]}".strip()
            if who not in out:
                out.append(who)
    return out


def sunday_of(d: dt.date) -> dt.date:
    """The Sunday that starts the report's Sun-Sat week holding `d`."""
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def open_week(app, sunday: dt.date) -> None:
    """Load the retention report (p=701) on the week starting `sunday`.

    Eve 10/27: the report opens on the CURRENT week only, so every lookup saw
    3 of ~28 days (10/25-10/27) and found nobody -- people are sent to the call
    list days or weeks before their 1st round. The week is picked the way
    find_ad.py / funnel_board do it: the hidden startDate2 (MM/DD/YYYY) is
    what selects it, and the form's "submit" input shadows form.submit()."""
    page = app.page
    m = re.search(r"rqst=([A-Za-z0-9\-]+)", page.url)
    if not m:                         # land on a page that carries it first
        app.open_retention_details()
        m = re.search(r"rqst=([A-Za-z0-9\-]+)", page.url)
    if not m:
        raise RuntimeError("no rqst token in %s" % page.url[:80])
    page.goto("https://applicantstream.com/index.cfm?rqst=%s&p=701" % m.group(1),
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("form[name=frmRR] input[name=weekStart]", timeout=30000)
    page.evaluate("""([slash, dash]) => { const f = document.forms['frmRR'];
        f.startDate2.value = slash; f.weekStart.removeAttribute('readonly');
        f.weekStart.value = dash; HTMLFormElement.prototype.submit.call(f); }""",
                  [sunday.strftime("%m/%d/%Y"), sunday.strftime("%m-%d-%Y")])
    page.wait_for_load_state("domcontentloaded")
    # The grid renders slowly on big offices (find_ad: poll for the row).
    want = header(sunday).lower()
    # No body yet while the submit is still navigating (Valeria 10/27).
    for _ in range(60):
        page.wait_for_timeout(2000)
        try:
            if page.evaluate("(w) => !!document.body && "
                             "document.body.innerText.toLowerCase().includes(w)", want):
                return
        except Exception:                     # noqa: BLE001 -- mid-navigation; poll again
            pass


def sent_rows(app, office_id: str, days: List[dt.date], debug: bool = False) -> List[List[str]]:
    """Every "Sent to Call List" detail row of `office_id` on `days`, one
    report week at a time."""
    app.select_office(office_id)
    hrefs = []
    for sunday in sorted({sunday_of(d) for d in days}):
        open_week(app, sunday)
        hrefs += [(d, app.detail_href(L_CALL_LIST, header(d)))
                  for d in days if sunday_of(d) == sunday]
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


def interview_cols(head: List[str]) -> Optional[Tuple[int, int, int]]:
    """(first, last, ad) columns of an interview table. Its ad column is headed
    "Ad (Subject Line)", not "Ad" (11/4: the first run read none of them)."""
    names = [(x or "").strip().lower() for x in head]
    ad = next((i for i, x in enumerate(names) if x == "ad" or x.startswith("ad (")), None)
    if "first name" not in names or "last name" not in names or ad is None:
        return None
    return names.index("first name"), names.index("last name"), ad


def interview_rows(app, office_id: str, days: List[dt.date]) -> List[List[str]]:
    """The "Total First Interviews" detail rows of `days`, shaped like
    sent_rows' (First, Last .. Ad). This table's columns are read by header."""
    from automations.applicant_tracker.find_ad import JS_TABLE
    app.select_office(office_id)
    hrefs = []
    for sunday in sorted({sunday_of(d) for d in days}):
        open_week(app, sunday)
        hrefs += [app.detail_href(L_INTERVIEWS, header(d)) for d in days if sunday_of(d) == sunday]
    rows: List[List[str]] = []
    for h in filter(None, hrefs):
        url = h if h.startswith("http") else "https://applicantstream.com/" + h.lstrip("/")
        app.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            app.page.wait_for_selector("table tr", timeout=20000)
        except Exception:                     # noqa: BLE001 -- an empty page reads as no rows
            pass
        t = app.page.evaluate(JS_TABLE)
        cols = interview_cols(t["head"])
        if cols is None:
            print(f"  interview table without the expected columns: {t['head']}")
            continue
        fi, li, ai = cols
        for r in t["rows"]:
            if len(r) > max(fi, li, ai):
                rows.append([r[fi], r[li], "", "", "", "", "", r[ai]])
    return rows


def run(office_key: str, day: dt.date, *, names: Optional[List[str]] = None,
        apply: bool = False, limit: Optional[int] = None, debug: bool = True,
        lookback: Optional[int] = None, cache: Optional[dict] = None,
        redo: bool = False) -> Dict[str, object]:
    """Look up the office's blank-title interviews still on no thread
    (unthreaded.find). Prints what it finds; with `apply` keeps it. `redo`
    looks again at the ones kept as "" (looked, nothing found)."""
    from automations.ad_photo_threads import collect, config, post, unthreaded
    from automations.applicant_tracker.applicantstream import session

    o = config.office(office_key)
    config.use(o)
    if lookback:
        unthreaded.LOOKBACK_DAYS = lookback
    cache = {} if cache is None else cache
    todo = [(d, c) for d, c in unthreaded.find(day, cache=cache)
            if collect.lookup_ok(c)]
    if names:
        want = {n.strip().lower() for n in names}
        todo = [(d, c) for d, c in todo if c.name.strip().lower() in want]
    channel = o["live_channel"]
    ch_state = post._load_state().get(channel) or {}
    done = ch_state.get("appstream_ads") or {}
    tried = ch_state.get("appstream_ads_tries") or {}

    def due(k: str) -> bool:
        if k not in done:
            return True
        if done[k]:
            return False
        # Once per evening: the nightly ticks every 30 min until the day is done.
        return redo or (tries(ch_state, k) < MAX_TRIES
                        and day.isoformat() not in (tried.get(k) or []))
    todo = [(d, c) for d, c in todo if due(key(d, c.name))]
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
    interviews: List[List[str]] = []
    around = sorted({d + dt.timedelta(days=n) for d, _ in todo
                     for n in range(-INTERVIEW_DAYS, INTERVIEW_DAYS + 1)
                     if d + dt.timedelta(days=n) <= day})
    with session() as app:
        for oid in oids:
            rows += sent_rows(app, oid, days, debug=debug)
            try:
                interviews += interview_rows(app, oid, around)
            except Exception as e:            # noqa: BLE001 -- the call list still counts
                print(f"  interview rows failed: {type(e).__name__}: {str(e)[:160]}")
        # Not on the call list in 3 weeks: further back, only if anyone is left.
        if any(not ad_of(interviews, c.name) and not ad_of(rows, c.name) for _, c in todo):
            far = [first - dt.timedelta(days=n)
                   for n in range(1, FAR_DAYS_BACK - SENT_DAYS_BACK + 1)]
            for oid in oids:
                try:
                    rows += sent_rows(app, oid, far, debug=debug)
                except Exception as e:        # noqa: BLE001 -- keep what was found
                    print(f"  far call list failed: {type(e).__name__}: {str(e)[:160]}")
    if debug:
        print(f"  {len(rows)} sent-to-call-list row(s) over {days[0]:%m/%d}-{days[-1]:%m/%d}")
    got: Dict[str, str] = {}
    for d, c in todo:
        # The interview's own row first: it's this interview, not any application.
        ads = (ad_of(interviews, c.name) or ad_of(rows, c.name)
               or ad_of_close(interviews, c.name) or ad_of_close(rows, c.name))
        got[key(d, c.name)] = ads[0] if len(ads) == 1 else ""
        print(f"  {c.name} ({d:%m/%d}): {ads or '-'}"
              + ("  -> 2+ ads, left for the channel" if len(ads) > 1 else ""))
        if not ads and debug:
            print(f"    near: {near(rows, c.name)[:8] or 'nobody with that first or last name'}")
    if apply and got:
        state = post._load_state()
        ch = state.setdefault(channel, {})
        old = dict(ch.get("appstream_ads") or {})
        ch.setdefault("appstream_ads", {}).update(got)
        log = ch.setdefault("appstream_ads_tries", {})
        for k in got:
            days = log.get(k) or (["?"] if k in old else [])   # the uncounted first try
            log[k] = sorted(set(days) | {day.isoformat()})
        post._save_state(state)
    return {"looked": len(got), "found": sum(1 for v in got.values() if v)}
