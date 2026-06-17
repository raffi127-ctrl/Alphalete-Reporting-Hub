"""Google reviews collector (Places API New).

Source path (cite when reporting a number):
  Google Maps / Places API (New) -> places:searchText (resolve the business)
  -> places/{id} Place Details -> rating, userRatingCount, reviews[].

Metrics that matter (vs vanity): overall rating, total review count, and from
the sample Google returns: average sample rating, count of negative reviews,
and age of the newest review (a freshness/velocity proxy).

LIMITATION: the Places API returns at most 5 reviews and can't paginate, so
review *velocity* and full sentiment need the Business Profile API (Phase 3).
We flag this so nobody mistakes the 5-review sample for the whole picture.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from automations.brand_audit import credentials
from automations.brand_audit.collectors.base import CollectorResult, NEGATIVE, WARN

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
SOURCE = "google_reviews"

NEGATIVE_RATING_MAX = 2  # a review at/below this (1-2 stars) is "negative"


def _headers(field_mask: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": credentials.google_places_api_key(),
        "X-Goog-FieldMask": field_mask,
    }


def _resolve_place_id(query: str) -> Optional[dict]:
    import requests
    from automations.brand_audit.config import HTTP_TIMEOUT
    r = requests.post(
        _SEARCH_URL,
        headers=_headers("places.id,places.displayName,places.formattedAddress,"
                         "places.rating,places.userRatingCount"),
        json={"textQuery": query},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    places = (r.json() or {}).get("places") or []
    return places[0] if places else None


def _age_days(publish_time: str) -> Optional[int]:
    """publishTime is RFC3339, e.g. 2026-02-01T12:00:00Z."""
    if not publish_time:
        return None
    try:
        t = publish_time.replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    query = " ".join(p for p in (company.name, company.location) if p).strip()
    if not query:
        return CollectorResult.failed(SOURCE, "no company name to search")

    try:
        place = _resolve_place_id(query)
    except Exception as e:
        return CollectorResult.failed(SOURCE, f"place search failed: {e}")
    if not place:
        res.ok = False
        res.error = f"no Google place matched {query!r}"
        res.flag(WARN, "Couldn't match this business on Google Maps")
        return res

    place_id = place.get("id", "")
    res.evidence["place_id"] = place_id
    res.evidence["matched_name"] = (place.get("displayName") or {}).get("text")
    res.evidence["address"] = place.get("formattedAddress")

    # Pull details + the review sample.
    try:
        import requests
        from automations.brand_audit.config import HTTP_TIMEOUT
        r = requests.get(
            _DETAILS_URL.format(place_id=place_id),
            headers=_headers("rating,userRatingCount,reviews.rating,"
                             "reviews.text,reviews.publishTime,"
                             "reviews.relativePublishTimeDescription,"
                             "reviews.authorAttribution.displayName"),
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        details = r.json() or {}
    except Exception as e:
        return CollectorResult.failed(SOURCE, f"place details failed: {e}")

    rating = details.get("rating")
    count = details.get("userRatingCount")
    reviews = details.get("reviews") or []

    sample = []
    neg = 0
    below5 = 0
    sample_sum = 0.0
    newest_age = None
    for rv in reviews:
        rstar = rv.get("rating")
        text = (rv.get("text") or {}).get("text", "")
        when_rel = rv.get("relativePublishTimeDescription", "")
        when_abs = rv.get("publishTime", "")
        author = (rv.get("authorAttribution") or {}).get("displayName", "")
        age = _age_days(when_abs)
        if age is not None:
            newest_age = age if newest_age is None else min(newest_age, age)
        if isinstance(rstar, (int, float)):
            sample_sum += rstar
            if rstar <= NEGATIVE_RATING_MAX:
                neg += 1
            if rstar < 5:
                below5 += 1
        sample.append({"rating": rstar, "text": text, "when": when_rel,
                       "publish_time": when_abs, "author": author,
                       "age_days": age})

    res.metrics = {
        "rating": rating,
        "review_count": count,
        "sample_size": len(sample),
        "sample_avg_rating": round(sample_sum / len(sample), 2) if sample else None,
        "negative_in_sample": neg,
        "below5_in_sample": below5,
        "newest_review_age_days": newest_age,
        # Only the Business Profile API exposes these — None until Phase 3.
        "response_rate": None,
        "median_response_hours": None,
    }
    res.evidence["reviews"] = sample
    res.evidence["profile_url"] = company.google_profile

    # Flags: each negative review in the sample is an alert candidate.
    for rv in sample:
        if isinstance(rv["rating"], (int, float)) and rv["rating"] <= NEGATIVE_RATING_MAX:
            snippet = (rv["text"] or "").strip().replace("\n", " ")
            res.flag(NEGATIVE,
                     f"{rv['rating']}★ Google review ({rv['when'] or 'recent'})"
                     + (f" from {rv['author']}" if rv["author"] else ""),
                     url=company.google_profile,
                     detail=snippet[:300])

    res.flag("info",
             "Google API returns only a 5-review sample; full review history + "
             "response-rate needs the Business Profile API (Phase 3).")
    return res
