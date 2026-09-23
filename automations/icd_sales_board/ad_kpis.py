"""Per-ad recruiting KPIs for one office: is this ad worth still running?

WHAT AN AD IS JUDGED ON. Every 1st-round interview is a row on the
interviewers' ARS REPORT sheet carrying the ad the candidate came from, whether
they qualified, and a star rating. Rolled up per ad that gives the two numbers
Megan asked to track (2026-09-23, "track KPIs of the ad to make sure we're
running the correct ones"): what share of the people an ad sends get removed,
and how good the rest are. A high-volume ad that sends 60% removals is costing
more than it brings.

READ FROM THE SHEET, NOT FROM THE SLACK POST. `ad_photo_threads` posts the same
two figures as a thread header, built from its own state file on the mini and
only for the days it has posted. Reading the sheet instead means any range can
be asked for, including ranges older than that state goes back, and the answer
settles as the interviewers finish filling rows in ([[feedback_sources_of_truth]]).
The two agree when they cover the same days — verified ad for ad on
2026-09-23.

IT ALSO REACHES FURTHER. ad_photo_threads posts for the offices switched on in
its config (2 of 19 on 2026-09-23); the sheet has every office that runs 1st
rounds, so every ICD's board can show this whether or not their Slack thread
has been turned on.

WHAT IT BORROWS, deliberately, rather than copying: `ad_photo_threads.config`
for which workbook and tab an office's rows live on and what the columns are
called, and `ad_photo_threads.titles.TitleBook` for folding the interviewers'
190 typed spellings onto ~35 real ads. Those are Eve's and they move — the
import is the point, so a change there lands here rather than drifting.

TWO THINGS HERE LOOK LIKE MISTAKES AND ARE NOT.

1. IT READS `Qualify`, WHICH `ars.py` REFUSES. That module reads the same
   sheet for the same office and takes only Name / Ad Title / Star Rating,
   because Megan ruled on 2026-08-31 that the funnel columns there are
   hand-typed and every one has a system-side source we trust more. That
   ruling stands for the funnel. It cannot stand for THIS number, because the
   metric asked for is Eve's "% Removed" and that figure IS the Qualify
   column — read it anywhere else and the board and the Slack thread would
   print different percentages for the same ad, which is worse than reading a
   hand-typed cell. So it is read here, and only here, and the page says on
   its face where it came from. If a system-side removal ever exists, this is
   the line to repoint.

2. IT USES TitleBook, NOT `ars.norm_ad`. There are two ad-title normalisers in
   the repo; ars.py's is simpler and Eve's LEARNS the running ads from the
   sheet and folds cut-offs and typos onto them. Matching the Slack thread ad
   for ad is the whole point of this section, so it has to fold the spellings
   the same way the thread does. Verified 2026-09-23: with TitleBook, every
   ad in Raf's posted thread reproduces to the percentage point.

AND A TRAP WORTH KNOWING: a thread sitting in Slack may be LAST week's. Raf's
posted headers on 2026-09-23 matched this module's previous-week column
exactly — 13%, 32%, 50%, 22%, 18%, 50% — not its current one. Two surfaces
showing different numbers for one ad is nearly always the week, not a bug.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
import time

# An ad with fewer candidates than this in the week is shown but never
# flagged: 1 of 1 removed is 100% and means nothing.
MIN_FOR_VERDICT = 5
# Above this share removed, an ad is worth a hard look.
BAD_REMOVED = 0.50
# And below this average, the ones who DO qualify are weak.
BAD_STARS = 2.8

_CACHE: dict = {}
_TTL = 600


def _office_for(icd: str):
    """The ad-report office entry whose owner is this ICD, or None."""
    from automations.ad_photo_threads import config as C

    def letters(s):
        return re.sub(r"[^a-z]", "", (s or "").lower())

    want = letters(icd)
    if not want:
        return None
    for o in C.OFFICES:
        if letters(o.get("owner")) == want:
            return o
    # Fall back to the alias sheet: the board spells an ICD the org's way and
    # this config spells them the interviewers' way.
    try:
        from automations.focus_office_att import aliases as A
        raw = A.load_aliases()
        names = {letters(n) for n in A.get_search_candidates(icd, raw) if n}
        for o in C.OFFICES:
            if letters(o.get("owner")) in names:
                return o
    except Exception:   # noqa: BLE001 — a missing alias tab is not an error
        pass
    return None


def _day(text: str):
    for f in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m/%d"):
        try:
            d = dt.datetime.strptime((text or "").strip(), f).date()
        except ValueError:
            continue
        return d.replace(year=dt.date.today().year) if f == "%m/%d" else d
    return None


def _stars(text: str):
    """The digits out of a star cell. Blank and '-' are NOT a zero — a rating
    nobody gave must not drag an ad's average down."""
    m = re.search(r"\d+", text or "")
    if not m:
        return None
    n = int(m.group())
    return n if 1 <= n <= 5 else None


def _removed(qualify: str) -> bool:
    """Anything that is not 'Qualified' is a removal — the same reading
    ad_photo_threads uses, kept identical on purpose."""
    return not (qualify or "").strip().lower().startswith("qualif")


def _rows(office) -> list:
    """[(date, ad title, qualify, stars)] across every funnel this office runs.

    An office can have more than one source tab (Raf has his main funnel and a
    2nd-funnel test); an ad belongs to the office, not to the funnel, so they
    are read together."""
    from automations.ad_photo_threads import config as C
    from automations.recruiting_report.fill import open_by_key, _retry
    out = []
    for src in office.get("sources") or []:
        tab = src.get("tab")
        if not tab:
            continue
        try:
            sh = open_by_key(office["sheet_id"])
            grid = _retry(sh.worksheet(tab).get_all_values)
        except Exception:   # noqa: BLE001 — one funnel missing is not the page
            continue
        if not grid:
            continue
        head = [h.strip() for h in grid[0]]
        # BY HEADER TEXT, never by letter: these workbooks are hand-maintained
        # and the template moves. 'Qualify' appears twice — once per candidate,
        # once in a summary block further right — and the first is the one that
        # belongs to the row.
        try:
            i_d, i_t = head.index(C.COL_DATE), head.index(C.COL_TITLE)
            i_q, i_s = head.index(C.COL_QUALIFY), head.index(C.COL_STARS)
        except ValueError:
            continue
        wide = max(i_d, i_t, i_q, i_s)
        for r in grid[1:]:
            if len(r) <= wide:
                continue
            d = _day(r[i_d])
            if d:
                out.append((d, r[i_t], r[i_q], r[i_s]))
    return out


def _tally(rows, start: dt.date, end: dt.date, book) -> dict:
    """{ad key: {n, removed, stars[]}} for one window."""
    agg: dict = collections.defaultdict(
        lambda: {"n": 0, "removed": 0, "stars": []})
    for d, title, qualify, stars in rows:
        if d < start or d > end:
            continue
        key = book.resolve(title)
        if not key:
            continue                 # a spelling that names no single ad
        a = agg[key]
        a["n"] += 1
        if _removed(qualify):
            a["removed"] += 1
        s = _stars(stars)
        if s is not None:
            a["stars"].append(s)
    return agg


def _shape(key, a, book) -> dict:
    stars = a["stars"]
    return {"Ad": book.display(key), "key": key, "Candidates": a["n"],
            "Removed": a["removed"],
            "% Removed": round(100.0 * a["removed"] / a["n"], 0) if a["n"] else 0,
            "Avg stars": round(sum(stars) / len(stars), 1) if stars else None,
            "Rated": len(stars)}


# The city sits at the end of an ad title, before the state: "AT&T Sales Agent
# – Arlington TX", "Client Solutions Specialist - AT&T Services, Frisco, TX,".
# READ OUT OF THE TITLE, not matched against a list of cities — these offices
# open new markets and a hardcoded list silently drops the newest one, which is
# exactly the market somebody is asking about ([[feedback_no_hardcoded_columns]]
# is the same idea one layer up). Up to three words, because 'Grand Prairie',
# 'Fort Worth' and 'Balch Springs' are cities and a longer run would start
# swallowing the job title.
_CITY = re.compile(r"(?:[–\-,]|\bin\b)\s*"
                   r"([A-Za-z][A-Za-z.'’]*(?:[ \-][A-Za-z][A-Za-z.'’]*){0,2})"
                   r"[,\s]+(?:TX|TEXAS)\b", re.IGNORECASE)
# Titles that name no single city. An ad running in two markets is real and
# must not be filed under whichever one the regex happens to hit.
_MULTI = re.compile(r"\d+\s*locations?|metroplex", re.IGNORECASE)


def city_of(title: str) -> str:
    """The city an ad names, 'Multiple', or '' when it names none."""
    t = (title or "").replace("&amp;", "&")
    if _MULTI.search(t):
        return "Multiple"
    m = _CITY.search(t)
    if not m:
        return ""
    city = re.sub(r"\s+", " ", m.group(1)).strip(" ,.-")
    # A trailing connector swept up from the job title ('Associate Denton') is
    # dropped, so 'Spanish Required Denton' does not become its own city.
    words = city.split()
    if len(words) > 1 and words[0].lower() in {
            "required", "needed", "at", "in", "level", "entry", "associate",
            "representative", "specialist", "manager", "assistant", "agent",
            "services", "spanish", "english", "arabic"}:
        words = words[1:]
    return " ".join(w.capitalize() if w.islower() else w for w in words)


def by_city(ads: list) -> list:
    """The same KPIs rolled up per city, best first.

    'Best' is the lowest removal rate, because that is the number an owner is
    deciding on — but only cities with enough people to mean it are ranked;
    the rest are kept and shown unranked rather than dropped, so a market
    nobody is working still appears."""
    agg: dict = collections.defaultdict(
        lambda: {"Candidates": 0, "Removed": 0, "stars": 0.0, "rated": 0,
                 "Ads": 0})
    for a in ads:
        city = city_of(a["Ad"])
        if not city:
            continue
        c = agg[city]
        c["Candidates"] += a["Candidates"]
        c["Removed"] += a["Removed"]
        c["Ads"] += 1
        if a["Avg stars"] is not None:
            c["stars"] += a["Avg stars"] * a["Rated"]
            c["rated"] += a["Rated"]
    out = []
    for city, c in agg.items():
        out.append({
            "City": city, "Ads": c["Ads"], "Candidates": c["Candidates"],
            "Removed": c["Removed"],
            "% Removed": round(100.0 * c["Removed"] / c["Candidates"], 0)
            if c["Candidates"] else 0,
            "Avg stars": round(c["stars"] / c["rated"], 1) if c["rated"] else None,
            "Ranked": c["Candidates"] >= MIN_FOR_VERDICT,
        })
    out.sort(key=lambda r: (not r["Ranked"], r["% Removed"], -r["Candidates"]))
    return out


def best(ads: list) -> dict:
    """{'cleanest': ad, 'rated': ad} — the two ads worth copying.

    Megan 2026-09-23: "which ad has lowest removal rate / highest star
    rating". The table flags the ads to stop; nothing in it named the ones to
    run MORE of, and that is the other half of the decision.

    THE BAR SCALES WITH THE RANGE, and that is the whole difficulty. A fixed
    floor of MIN_FOR_VERDICT is right for judging one week and absurd over two
    months: Raf's 8-week window has 2,822 first rounds across 51 ads, and a
    flat bar of 5 crowned a 10-person ad the best of them. So the bar is the
    MEDIAN ad's volume — the winner has to be at least a typical-sized ad for
    whatever range is being looked at — with MIN_FOR_VERDICT as the floor for
    short ranges where the median is tiny.

    The two bars measure different things: 'cleanest' counts people SENT,
    'best rated' counts people actually RATED, since an ad with twenty
    candidates and one 5⭐ would otherwise win on a single opinion.

    Ties break toward the bigger ad — the same rate over more people is the
    stronger result."""
    def bar(values):
        vals = sorted(v for v in values if v)
        if not vals:
            return MIN_FOR_VERDICT
        return max(MIN_FOR_VERDICT, vals[len(vals) // 2])

    need = bar([a["Candidates"] for a in ads])
    need_rated = bar([a["Rated"] for a in ads])
    ranked = [a for a in ads if a["Candidates"] >= need]
    rated = [a for a in ads
             if a["Avg stars"] is not None and a["Rated"] >= need_rated]
    return {
        "cleanest": min(ranked, key=lambda a: (a["% Removed"],
                                               -a["Candidates"]))
        if ranked else None,
        "rated": max(rated, key=lambda a: (a["Avg stars"], a["Rated"]))
        if rated else None,
    }


def verdict(row: dict) -> str:
    """'', 'Watch' or 'Stop' — said only where there is enough to say it."""
    if row["Candidates"] < MIN_FOR_VERDICT:
        return ""
    bad_rm = row["% Removed"] >= BAD_REMOVED * 100
    bad_st = row["Avg stars"] is not None and row["Avg stars"] < BAD_STARS
    if bad_rm and bad_st:
        return "Stop"
    return "Watch" if (bad_rm or bad_st) else ""


def for_icd(icd: str, start: dt.date, end: dt.date,
            force: bool = False) -> dict:
    """{ads: [...], office, span, prior} for ANY date range.

    Each ad carries the range's numbers and the PRECEDING RANGE OF THE SAME
    LENGTH beside them, because the figure an owner can act on is the
    DIRECTION: 30% removed is fine after 45% and bad after 12%. Comparing
    like with like matters — a 4-week window against a 1-week one would make
    every ad look busier than it got.

    A RANGE, NOT A WEEK (Megan 2026-09-23, "we should also have a date range
    selector here"). A week is too short to judge a slow ad: three candidates
    and one removal is 33% and means nothing, and the ads that quietly waste
    money are exactly the low-volume ones. Never raises — the page says it has
    nothing instead."""
    now = time.time()
    ck = (icd, start, end)
    if not force and ck in _CACHE and now - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    out = {"ads": [], "office": "", "error": ""}
    try:
        from automations.ad_photo_threads import config as C
        from automations.ad_photo_threads import titles as T
        office = _office_for(icd)
        if not office:
            out["error"] = "no-office"
            _CACHE[ck] = (now, out)
            return out
        out["office"] = office.get("owner") or icd
        rows = _rows(office)
        if not rows:
            out["error"] = "no-rows"
            _CACHE[ck] = (now, out)
            return out
        span = (end - start).days + 1
        prev_end = start - dt.timedelta(days=1)
        prev_start = prev_end - dt.timedelta(days=span - 1)
        # The ads are learned from the SAME lookback the Slack threads use, so
        # both surfaces fold the spellings the same way. Learned from a window
        # ending at the range shown, not at today, or a range read months later
        # would be folded using ads that did not exist yet.
        look = start - dt.timedelta(days=C.TITLE_LOOKBACK_DAYS)
        book = T.TitleBook([t for d, t, _q, _s in rows if look <= d <= end])
        this = _tally(rows, start, end, book)
        last = _tally(rows, prev_start, prev_end, book)
        ads = []
        for key, a in this.items():
            row = _shape(key, a, book)
            b = last.get(key)
            row["Last % Removed"] = (
                round(100.0 * b["removed"] / b["n"], 0) if b and b["n"] else None)
            row["Last candidates"] = b["n"] if b else 0
            row["Verdict"] = verdict(row)
            ads.append(row)
        ads.sort(key=lambda r: (-r["Candidates"], r["Ad"]))
        out["ads"] = ads
        out["cities"] = by_city(ads)
        out["best"] = best(ads)
        out["span"] = (start, end)
        out["prior"] = (prev_start, prev_end)
    except Exception as e:   # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    _CACHE[ck] = (now, out)
    return out


def _office_rows(office) -> list:
    """_rows for one office, cached, so the org view and that office's own
    board share the read instead of pulling the same tab twice."""
    key = ("rows", office.get("key"))
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    rows = _rows(office)
    _CACHE[key] = (now, rows)
    return rows


def org(start: dt.date, end: dt.date, force: bool = False) -> dict:
    """The same KPIs across every office at once — the buying decision.

    An ad is bought for the org, not for one office: the same posting runs in
    six markets, and whether it is worth paying for is a question about all of
    them together. An office's own board answers "is this working HERE"; this
    answers "is this working".

    ONE SHARED TitleBook, not each office's own. The per-office view learns the
    running ads from that office's tab, which is right there and wrong here: two
    offices running the same posting would learn it separately and it would
    appear twice, split, and be judged twice on half its people. Built from
    every office's titles at once, the same spelling folds to one ad wherever
    it was typed — and the extra volume makes the folding surer, not looser.

    It is still a per-office READ, so `Offices` counts how many actually ran
    the ad. An ad in one office at 60% removed is a different problem from one
    failing in six."""
    now = time.time()
    ck = ("org", start, end)
    if not force and ck in _CACHE and now - _CACHE[ck][0] < _TTL:
        return _CACHE[ck][1]
    out = {"ads": [], "cities": [], "offices": 0, "error": ""}
    try:
        from automations.ad_photo_threads import config as C
        from automations.ad_photo_threads import titles as T
        span = (end - start).days + 1
        prev_end = start - dt.timedelta(days=1)
        prev_start = prev_end - dt.timedelta(days=span - 1)
        look = start - dt.timedelta(days=C.TITLE_LOOKBACK_DAYS)

        per_office = []
        every_title = []
        for office in C.OFFICES:
            rows = _office_rows(office)
            if not rows:
                continue
            per_office.append((office, rows))
            every_title += [t for d, t, _q, _s in rows if look <= d <= end]
        if not per_office:
            out["error"] = "no-rows"
            _CACHE[ck] = (now, out)
            return out
        out["offices"] = len(per_office)
        book = T.TitleBook(every_title)

        this: dict = collections.defaultdict(
            lambda: {"n": 0, "removed": 0, "stars": [], "offices": set()})
        last: dict = collections.defaultdict(lambda: {"n": 0, "removed": 0})
        for office, rows in per_office:
            for key, a in _tally(rows, start, end, book).items():
                t = this[key]
                t["n"] += a["n"]
                t["removed"] += a["removed"]
                t["stars"] += a["stars"]
                t["offices"].add(office.get("key"))
            for key, a in _tally(rows, prev_start, prev_end, book).items():
                b = last[key]
                b["n"] += a["n"]
                b["removed"] += a["removed"]

        ads = []
        for key, a in this.items():
            row = _shape(key, a, book)
            row["Offices"] = len(a["offices"])
            b = last.get(key)
            row["Last % Removed"] = (
                round(100.0 * b["removed"] / b["n"], 0) if b and b["n"] else None)
            row["Last candidates"] = b["n"] if b else 0
            row["Verdict"] = verdict(row)
            ads.append(row)
        ads.sort(key=lambda r: (-r["Candidates"], r["Ad"]))
        out["ads"] = ads
        out["cities"] = by_city(ads)
        out["best"] = best(ads)
        out["span"] = (start, end)
        out["prior"] = (prev_start, prev_end)
    except Exception as e:   # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    _CACHE[ck] = (now, out)
    return out


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="icd_ad_kpis")
    ap.add_argument("icd")
    ap.add_argument("--from", dest="start", default="",
                    help="First day, YYYY-MM-DD. Default: 4 weeks back.")
    ap.add_argument("--to", dest="end", default="",
                    help="Last day, YYYY-MM-DD. Default: today.")
    a = ap.parse_args(argv)
    end = dt.date.fromisoformat(a.end) if a.end else dt.date.today()
    start = (dt.date.fromisoformat(a.start) if a.start
             else end - dt.timedelta(days=27))
    d = for_icd(a.icd, start, end)
    if d.get("error"):
        print(f"{a.icd}: {d['error']}")
        return 1
    print(f"{d['office']} — {start} to {end} ({len(d['ads'])} ads)\n")
    print(f"{'Ad':52} {'n':>4} {'%rm':>5} {'last':>5} {'stars':>6}  verdict")
    for r in d["ads"]:
        last = "" if r["Last % Removed"] is None else f"{r['Last % Removed']:.0f}%"
        st = "" if r["Avg stars"] is None else f"{r['Avg stars']:.1f}"
        print(f"{r['Ad'][:52]:52} {r['Candidates']:4} {r['% Removed']:4.0f}% "
              f"{last:>5} {st:>6}  {r['Verdict']}")
    print(f"\n{'City':22} {'ads':>4} {'n':>5} {'%rm':>5} {'stars':>6}")
    for c in d.get("cities") or []:
        st = "" if c["Avg stars"] is None else f"{c['Avg stars']:.1f}"
        print(f"{c['City'][:22]:22} {c['Ads']:4} {c['Candidates']:5} "
              f"{c['% Removed']:4.0f}% {st:>6}"
              + ("" if c["Ranked"] else "   (too few to rank)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
