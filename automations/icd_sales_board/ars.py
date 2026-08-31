"""ARS — the interviewer's star rating on every first-round applicant.

Five workbooks, split alphabetically by the owner's FIRST name, one tab per
ICD, owned by camilahornosk@gmail.com and edited live by the interviewers.

THREE COLUMNS ONLY: Full Name, Ad Title, Star Rating (Megan 2026-08-31).
The tab also carries Qualify / Answer Call / Booked to 2nd Rd / Showed Up to
2nd Round / Offered Positon / BOB, and this module deliberately does not read
them. They are typed by hand into a sheet nobody reconciles, and every one of
them already has a system-side source we trust more — the Focus Report for the
funnel, the 2R tab for BOB, the 3am harvest for first sale. Pulling them here
would quietly create a second, worse version of numbers we already publish.

WHY THE RATING IS WORTH HAVING. Everything else we hold about a job ad counts
people — applies, BOB, who lasted. This is the only source that says whether
the people an ad sent were any GOOD, judged by the person who sat across from
them. An ad can flood the call list and send nobody worth hiring; that ad
looks fine on every other report and bad only on this one.

HOW FAR IT CAN BE PUSHED. The rating is a human judgement and nothing more:
treat a low average as "the interviewers did not rate the people this ad
sent", which is exactly the question being asked, and not as "these people
would not have signed".

An earlier version of this file claimed 1 star predicted worse outcomes. That
came from the sheet's OWN outcome columns — the untrusted ones — so it has
been removed rather than left standing on data we do not rely on. Re-running
the same test against sources we do trust (the 2R tab's start dates and the
first-sale map) was inconclusive: only 142 of Raf's 2,253 ARS rows match
either by name, which leaves single-digit numerators per star and no signal
in any direction. So there is currently NO evidence here that the scale
predicts who comes on board. If that matters later, the way to settle it is a
real name join, not more of this sheet.
"""
from __future__ import annotations

import collections
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
}

_STAR = re.compile(r"^\s*([1-5])\s*star", re.I)


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

    The '?' is not a typo: an en-dash lost its encoding somewhere upstream and
    lands in the cell as a literal question mark."""
    t = re.sub(r"[?–—·|]+", " - ", str(title or ""))
    t = re.sub(r"\s+at Alphalete Marketing.*$", "", t, flags=re.I)
    t = t.replace(",", " ")
    t = re.sub(r"\s*-\s*", " - ", t)
    return re.sub(r"\s+", " ", t).strip(" -,").lower()


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
            "Ad": spellings[key].most_common(1)[0][0],
            "Rated": n,
            "Avg star": round(sum(stars) / n, 2),
            "1-2 star": f"{sum(1 for s in stars if s <= 2) / n:.0%}",
            "4-5 star": f"{sum(1 for s in stars if s >= 4) / n:.0%}",
            "thin": n < min_rated,
        })
    out.sort(key=lambda r: (r["thin"], -r["Avg star"], -r["Rated"]))
    return out
