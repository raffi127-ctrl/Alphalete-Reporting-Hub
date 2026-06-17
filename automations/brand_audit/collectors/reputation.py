"""Employer-reputation collector — Indeed + Glassdoor overall rating + review
count.

Neither has a public API, so we scrape the overview page for an embedded
aggregateRating (JSON-LD / inline JSON / visible text). Both sites block hard
(Glassdoor especially, via Cloudflare), so this FAILS SOFT and flags itself as
brittle — a miss means "couldn't read today", not "no reviews".
"""
from __future__ import annotations

import re

from automations.brand_audit.collectors.base import (
    CollectorResult, http_get, WARN, INFO,
)

SOURCE = "reputation"

# Patterns that tend to survive across Indeed/Glassdoor markup changes.
_RATING_PATS = [
    r'"ratingValue"\s*:\s*"?([0-9.]+)"?',
    r'"aggregateRating"[^}]*?"ratingValue"\s*:\s*"?([0-9.]+)"?',
    r'([0-9](?:\.[0-9])?)\s*out of 5',
]
_COUNT_PATS = [
    r'"ratingCount"\s*:\s*"?([0-9,]+)"?',
    r'"reviewCount"\s*:\s*"?([0-9,]+)"?',
    r'([0-9,]{1,7})\s*reviews',
]


def _first(pats, text):
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    return None


def _scrape(url: str) -> dict:
    """Return {ok, rating, count, status} for one employer-review URL."""
    out = {"ok": False, "rating": None, "count": None, "status": None}
    if not url:
        return out
    try:
        r = http_get(url, browser=True, allow_redirects=True)
        out["status"] = r.status_code
        if not r.ok:
            return out
        text = r.text
        rating = _first(_RATING_PATS, text)
        count = _first(_COUNT_PATS, text)
        out["rating"] = float(rating) if rating else None
        out["count"] = int(count.replace(",", "")) if count else None
        out["ok"] = out["rating"] is not None or out["count"] is not None
    except Exception as e:
        out["error"] = str(e)
    return out


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    indeed = _scrape(company.indeed)
    glassdoor = _scrape(company.glassdoor)

    res.metrics = {
        "indeed_rating": indeed["rating"],
        "indeed_review_count": indeed["count"],
        "glassdoor_rating": glassdoor["rating"],
        "glassdoor_review_count": glassdoor["count"],
    }
    res.evidence["indeed"] = indeed
    res.evidence["glassdoor"] = glassdoor

    for name, data, url in (("Indeed", indeed, company.indeed),
                            ("Glassdoor", glassdoor, company.glassdoor)):
        if url and not data["ok"]:
            res.flag(INFO, f"Couldn't read {name} today (blocked/changed markup "
                           f"— status {data['status']}). Brittle source.",
                     url=url)
        elif data["ok"] and data["rating"] is not None and data["rating"] < 3.0:
            res.flag(WARN, f"{name} employer rating is low ({data['rating']}★).",
                     url=url)
    return res
