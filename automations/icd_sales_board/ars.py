"""ARS — the interviewer's star rating on every first-round applicant.

SUPERSEDED, and kept only until the AppStream harvest replaces it
(2026-08-31). AppStream's Retention Details report — the popup behind "Total
Daily Bob" — carries a **Rating** column on the SAME ROW as **Ad (Subject
Line)**, per applicant, per day, per office. That is the same judgement this
workbook holds, in the system it was typed from, already joined to the ad.

CHECKED, not assumed: the nine BOB rows on AppStream for Mon 2026-08-31 were
looked up in this workbook. Eight carried the identical rating (3,4,5,3,2,3,3,3);
the ninth — Jayla Callier — is present here with a BLANK rating where AppStream
has a 3. Not one disagreed on a value. So it is the same judgement on the same
scale, and this copy is simply lossier: 864 of Raf's 2,253 rows are unrated.
(Nine people on one day is a small check — widen it before relying on it for
anything bigger than choosing a source.)

So this module is reading a hand-typed copy: the same mistake as pulling the
Focus Report. Tableau / SaraPlus / Sterling / AppStream are truth (Megan
2026-08-31). Ad quality should come from AppStream, where nothing has to be
matched up by name and the office and date come for free.

What is still worth taking from here when that lands: nothing about the data,
only the shape — norm_ad (people type one ad three ways, 305 spellings folded
to 230), the unrated-is-not-zero rule, and the thin-sample floor that keeps an
ad with one 5-star applicant off the top of the table. Those apply to the
AppStream rows unchanged.

Five workbooks, split alphabetically by the owner's FIRST name, one tab per
ICD. Reads THREE columns only — Full Name, Ad Title, Star Rating — plus Date
1st Rd purely to place a row in a week. Its funnel columns are hand-typed and
every one has a system-side source we trust more.
"""
from __future__ import annotations

import collections
import datetime as dt
import re

# Alphabetical by the owner's FIRST name — 'Rafael Hidalgo' is in R to Z.
WORKBOOKS = [
    ("1BltgRTW_tm-Y0AlUIVxqHHqh3cpSUwWc5F1Ako01gVw", "A to C", "ABC"),
    ("1U5GZyzuXmzeNRKDL8V_lvCpzEtpjxuy4LLCDT3gDKcQ", "D to I", "DEFGHI"),
    ("1sq_0VY-y1kzcQ8SAOmqs4VLE_2bPSJpCLTFufcUtQW4", "J to L", "JKL"),
    ("12zye9tduziss1w-EdZKkPJ2DE-dg-xB0aqvC2H3cLao", "M to Q", "MNOPQ"),
    ("16UruNs3bHGJ_pBvmD6T9KEqMAtDNNyuKArA_es6f0LE", "R to Z", "RSTUVWXYZ"),
]

# Found by HEADER, never by index — these sheets are hand-kept and a new
# column in the middle would silently shift every read.
COLUMNS = {
    "name": "Full Name",
    "ad": "Ad Title",
    "star": "Star Rating",
    # Hand-entered like the rest, and read for ONE purpose: putting a row in a
    # week so the page can show a window instead of all time (Megan
    # 2026-08-31). That is a much smaller thing to trust than an outcome —
    # a wrong date moves somebody between weeks, where a wrong "BOB" invents a
    # hire. It is never reported as a number, only used to filter.
    "date": "Date 1st Rd",
}

_STAR = re.compile(r"^\s*([1-5])\s*star", re.I)


def parse_date(value):
    """'7/20/2026' -> date. None when it is missing or unreadable, and those
    rows are DROPPED from a windowed view rather than swept into it: a row
    with no date belongs to no week, and defaulting it into the current one
    would quietly pad whichever window is on screen."""
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def in_window(rows: list, start=None, end=None) -> tuple:
    """(rows inside the window, how many were dropped for having no date).

    The count comes back so the page can own up to it — a quality table that
    silently drops a third of its rows is worse than one that says so."""
    if start is None and end is None:
        return list(rows), 0
    kept, undated = [], 0
    for r in rows:
        d = r.get("on")
        if d is None:
            undated += 1
            continue
        if (start is None or d >= start) and (end is None or d <= end):
            kept.append(r)
    return kept, undated


def star(value) -> int | None:
    """'4 Star' -> 4. Anything else -> None, which means UNRATED, not zero:
    864 of Raf's 2,253 rows have no rating and counting those as a 0 would
    invent the worst possible score for an applicant nobody scored."""
    m = _STAR.match(str(value or ""))
    return int(m.group(1)) if m else None


def norm_ad(title: str) -> str:
    """A matching key for an ad title, which people type inconsistently.

    The same ad appears as 'Client Solutions Specialist - AT&T Services,
    Frisco, TX,' / '... Frisco TX' / '... Frisco, TX'. Left raw, one ad splits
    into three and each fragment gets its own average off a third of the
    sample. Normalising collapsed 305 spellings to 230 on Raf's tab.

    Folds '?', en-dash and '·' to the same separator — see display_ad for
    where the '?' comes from."""
    t = re.sub(r"[?–—·|]+", " - ", str(title or ""))
    t = re.sub(r"\s+at Alphalete Marketing.*$", "", t, flags=re.I)
    t = t.replace(",", " ")
    t = re.sub(r"\s*-\s*", " - ", t)
    return re.sub(r"\s+", " ", t).strip(" -,").lower()


def display_ad(title: str) -> str:
    """Tidy a title for the screen, without changing which ad it is.

    The '?' is a separator that did not survive being typed in: the job boards
    write 'AT&T Sales Associate (Spanish Required) – Balch Springs TX' with an
    en-dash (some rows still carry a real '·'), and when the interviewer pastes
    it through something that cannot encode that character it lands as a
    literal question mark. The same ad reaches us from the 2R tab as
    '…(Spanish Required), Balch Springs, TX' — plain ASCII, comma — which is
    how we know what the '?' replaced.

    Grouping never cared, since norm_ad folds ?, – and · to one key. This is
    only so the table does not show a row that looks like a typo."""
    t = re.sub(r"\s*\?\s*", " - ", str(title or ""))
    t = re.sub(r"\s*[·|]\s*", " - ", t)
    t = re.sub(r"\s*,\s*(?=,|$)", "", t)
    return re.sub(r"\s+", " ", t).strip(" -,")


def load(owner: str) -> list:
    """Every ARS row for one ICD as {name, ad, star, stars}.

    Routed to a workbook by first letter, then falling back to a scan of the
    rest: the split is by first name today, but nothing enforces that, and a
    quiet miss here would read as 'this office has no ratings'."""
    from automations.recruiting_report.fill import open_by_key
    from automations.focus_office_att import aliases as _al

    try:
        names = _al.get_search_candidates(owner, _al.load_aliases())
    except Exception:
        names = [owner]
    wanted = {n.strip().lower() for n in names if n}

    first = (owner or " ").strip()[:1].upper()
    ordered = ([w for w in WORKBOOKS if first in w[2]]
               + [w for w in WORKBOOKS if first not in w[2]])

    for sheet_id, _label, _letters in ordered:
        try:
            sh = open_by_key(sheet_id)
            ws = next((w for w in sh.worksheets()
                       if w.title.strip().lower() in wanted), None)
        except Exception:
            continue
        if ws is None:
            continue
        return _parse(ws.get("A1:M4000"))
    return []


def _parse(grid: list) -> list:
    if not grid:
        return []
    header = [str(h).strip() for h in grid[0]]
    idx = {}
    for key, label in COLUMNS.items():
        want = label.strip().lower()
        idx[key] = next((i for i, h in enumerate(header)
                         if h.lower() == want), None)

    out = []
    name_i = idx.get("name")
    for row in grid[1:]:
        if name_i is None or len(row) <= name_i or not row[name_i].strip():
            continue
        rec = {k: (row[i].strip() if i is not None and len(row) > i else "")
               for k, i in idx.items()}
        rec["stars"] = star(rec.get("star"))
        rec["on"] = parse_date(rec.get("date"))
        out.append(rec)
    return out


def distribution(rows: list) -> dict:
    """{1..5: count, 'unrated': count} — the shape of the scale for an office."""
    c = collections.Counter(r["stars"] for r in rows)
    out = {n: c.get(n, 0) for n in range(1, 6)}
    out["unrated"] = c.get(None, 0)
    return out


def by_ad(rows: list, min_rated: int = 8) -> list:
    """Ad quality, best first: average star, and the share at each end.

    `min_rated` keeps ads nobody has rated more than a handful of times off a
    ranking that would otherwise be topped by an ad with one 5-star applicant.
    Ads below the floor are still returned, flagged `thin`, so a real ad is
    never silently dropped — it just cannot win.

    Display name is the spelling used most often for that ad, so the table
    reads the way the sheet does rather than showing a normalised key."""
    per = collections.defaultdict(list)
    spellings = collections.defaultdict(collections.Counter)
    for r in rows:
        key = norm_ad(r.get("ad"))
        if not key:
            continue
        spellings[key][str(r.get("ad")).strip()] += 1
        if r["stars"]:
            per[key].append(r["stars"])

    out = []
    for key, stars in per.items():
        n = len(stars)
        out.append({
            "Ad": display_ad(spellings[key].most_common(1)[0][0]),
            "Rated": n,
            "Avg star": round(sum(stars) / n, 2),
            # All THREE bands, so the row adds to 100%. Showing only the two
            # ends hid the largest group — 3 star is 47% of Raf's ratings —
            # and left the percentages looking like they did not sum.
            "1-2 star": f"{sum(1 for s in stars if s <= 2) / n:.0%}",
            "3 star": f"{sum(1 for s in stars if s == 3) / n:.0%}",
            "4-5 star": f"{sum(1 for s in stars if s >= 4) / n:.0%}",
            "thin": n < min_rated,
        })
    out.sort(key=lambda r: (r["thin"], -r["Avg star"], -r["Rated"]))
    return out
