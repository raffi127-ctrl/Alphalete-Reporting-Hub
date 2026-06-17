"""SERP / SEO collector (SerpAPI).

Source path: SerpAPI engine=google, q="<brand> <city>" -> the real Google
results page (organic, knowledge panel, people-also-ask).

Metrics that matter (vs "are we on page 1"): WHERE the owned site ranks, whether
a knowledge panel exists, and — the reputation killer — whether any NEGATIVE
result (a complaint/scam/"devilcorp" thread) outranks the owned site. That last
one ties SEO to reputation, which is the whole point of this tool.
"""
from __future__ import annotations

from urllib.parse import urlparse

from automations.brand_audit import credentials
from automations.brand_audit.collectors.base import (
    CollectorResult, NEGATIVE, WARN, INFO,
)

_URL = "https://serpapi.com/search.json"
SOURCE = "serp"

# Words/sites that signal a reputation-damaging result. Kept as a named,
# tunable list (no magic strings buried in logic).
NEGATIVE_SIGNALS = (
    "devilcorp", "scam", "ripoff", "rip-off", "ripoffreport", "complaint",
    "complaints", "pyramid", "mlm", "fraud", "lawsuit", "warning", "avoid",
    "is alphalete a", "exposed", "cult",
)

# Domains that REPRESENT the brand — the company's own profiles on someone
# else's platform. These are good page-1 presence (they crowd out negatives),
# so they're "brand profile", not neutral third-party and never negative.
BRAND_PROFILE_DOMAINS = (
    "linkedin.com", "indeed.com", "glassdoor.com", "instagram.com",
    "facebook.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "smartrecruiters.com", "ziprecruiter.com", "crunchbase.com", "yelp.com",
    "bbb.org", "builtin.com", "comparably.com",
)


def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _clean_location(location: str) -> str:
    """Intake locations can be messy ('Irving, Texas - Moving to Frisco'). Take
    the first clean 'City, State' chunk for SerpAPI's location param."""
    if not location:
        return ""
    head = location.split(" - ")[0].strip()
    return head


def _looks_negative(title: str, link: str, snippet: str) -> bool:
    blob = f"{title} {link} {snippet}".lower()
    return any(sig in blob for sig in NEGATIVE_SIGNALS)


def _is_brand_profile(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) or domain.endswith(d)
               for d in BRAND_PROFILE_DOMAINS)


def _categorize(is_own: bool, is_negative: bool, domain: str) -> str:
    if is_negative:
        return "negative"      # reputation threat
    if is_own:
        return "owned"         # your own website
    if _is_brand_profile(domain):
        return "profile"       # your branded profile on another platform
    return "neutral"           # everything else


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    if not company.name:
        return CollectorResult.failed(SOURCE, "no company name to search")

    # Query the BARE brand name — that's what a prospect/applicant actually
    # types, and it's what surfaces reputation threats (a city-qualified query
    # is a different, local-intent search that can hide them). The searcher's
    # location is supplied via the `location` param instead, so we still see
    # results as someone near the business would.
    location = _clean_location(company.location)
    params = {
        "engine": "google",
        "q": company.name,
        "hl": "en",
        "gl": "us",
        "num": "10",
        "api_key": credentials.serpapi_api_key(),
    }
    if location:
        params["location"] = f"{location}, United States"

    try:
        from automations.brand_audit.collectors.base import get_json
        data = get_json(_URL, params=params)
    except Exception as e:
        return CollectorResult.failed(SOURCE, f"serpapi request failed: {e}")
    if data.get("error"):
        return CollectorResult.failed(SOURCE, f"serpapi: {data['error']}")

    own_domain = _domain(company.website)
    organic = data.get("organic_results") or []
    kg = data.get("knowledge_graph") or {}
    paa = data.get("related_questions") or []
    local = data.get("local_results")

    own_position = None
    negatives = []
    page1 = []
    serp_ratings = {}   # site -> {rating, reviews} lifted from Google rich snippets
    _RATING_SITES = {"indeed.com": "indeed", "glassdoor.com": "glassdoor"}
    for r in organic:
        pos = r.get("position")
        title = r.get("title", "")
        link = r.get("link", "")
        snippet = r.get("snippet", "")
        dom = _domain(link)
        rich = ((r.get("rich_snippet") or {}).get("top") or {}).get("detected_extensions") or {}
        for site_dom, key in _RATING_SITES.items():
            if dom.endswith(site_dom) and rich.get("rating") is not None and key not in serp_ratings:
                serp_ratings[key] = {"rating": rich.get("rating"),
                                     "reviews": rich.get("reviews")}
        is_own = bool(own_domain) and dom.endswith(own_domain)
        if is_own and own_position is None:
            own_position = pos
        is_neg = _looks_negative(title, link, snippet)
        category = _categorize(is_own, is_neg, dom)
        entry = {"position": pos, "title": title, "link": link,
                 "domain": dom, "is_own": is_own, "is_negative": is_neg,
                 "category": category}
        page1.append(entry)
        if is_neg:
            negatives.append(entry)

    cat_counts = {"owned": 0, "profile": 0, "negative": 0, "neutral": 0}
    for e in page1:
        cat_counts[e["category"]] = cat_counts.get(e["category"], 0) + 1

    res.metrics = {
        "own_site_position": own_position,         # None = not on page 1
        "own_site_on_page1": own_position is not None,
        "has_knowledge_panel": bool(kg),
        "knowledge_rating": kg.get("rating"),
        "people_also_ask_count": len(paa),
        "has_local_pack": bool(local),
        "negative_results_on_page1": len(negatives),
        "top_negative_position": min((n["position"] for n in negatives),
                                     default=None),
        "organic_count": len(page1),
        "owned_count": cat_counts["owned"],
        "profile_count": cat_counts["profile"],
        "neutral_count": cat_counts["neutral"],
        "brand_controlled_count": cat_counts["owned"] + cat_counts["profile"],
        "serp_ratings": serp_ratings,   # {indeed:{rating,reviews}, glassdoor:{...}}
    }
    res.evidence["page1"] = page1
    res.evidence["knowledge_graph"] = {"title": kg.get("title"),
                                       "type": kg.get("type"),
                                       "rating": kg.get("rating")}
    res.evidence["people_also_ask"] = [q.get("question") for q in paa]

    # Flags — the reputation-critical ones first.
    for n in negatives:
        outranks_own = (own_position is None) or (n["position"] < own_position)
        level = NEGATIVE if outranks_own else WARN
        res.flag(level,
                 f"Negative result ranks #{n['position']} for your name"
                 + (" — ABOVE your own website" if outranks_own else ""),
                 url=n["link"], detail=n["title"])

    if own_position is None:
        res.flag(WARN, "Your own website is not on page 1 for your brand name",
                 url=company.website)
    elif own_position and own_position > 1:
        res.flag(INFO, f"Your website ranks #{own_position} (not #1) for your name",
                 url=company.website)

    return res
