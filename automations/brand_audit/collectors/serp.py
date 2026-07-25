"""SERP / SEO collector (SerpAPI).

Source path: SerpAPI engine=google, q="<brand> <city>" -> the real Google
results page (organic, knowledge panel, people-also-ask).

Metrics that matter (vs "are we on page 1"): WHERE the owned site ranks, whether
a knowledge panel exists, and — the reputation killer — whether any NEGATIVE
result (a complaint/scam/"devilcorp" thread) outranks the owned site. That last
one ties SEO to reputation, which is the whole point of this tool.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
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

# Branded search VARIATIONS an applicant/customer actually types — each is its
# own Google query with its own reputation picture ("<brand> scam" surfaces very
# different results than the bare name). {name}=company, {city}=first city.
# (label = short human tag for the card.) Generic on purpose so it works for any
# tenant, not just Alphalete. The bare-name query above runs every day; this
# sweep runs WEEKLY (see _SWEEP_EVERY_DAYS) to stay under SerpAPI's ~100/mo cap.
VARIATIONS = (
    ("{name} reviews", "reviews"),
    ("{name} scam", "scam"),
    ("{name} complaints", "complaints"),
    ("{name} legit", "legit"),
    ("{name} reddit", "reddit"),
    ("working at {name}", "working at"),
    ("is {name} a scam", "is a scam"),
    ("{name} {city}", "{city}"),
)
_SWEEP_EVERY_DAYS = 7
# Cached between runs so the card always shows the latest sweep even on the days
# it doesn't re-query. Local state only (like review_history) — safe every run.
_SWEEP_STATE = Path.home() / ".config" / "brand-audit" / "serp_sweep.json"


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


def _search(query: str, location: str) -> dict:
    """One SerpAPI Google query. Raises on transport or API error."""
    params = {
        "engine": "google",
        "q": query,
        "hl": "en",
        "gl": "us",
        "num": "10",
        "api_key": credentials.serpapi_api_key(),
    }
    if location:
        params["location"] = f"{location}, United States"
    from automations.brand_audit.collectors.base import get_json
    data = get_json(_URL, params=params)
    if data.get("error"):
        raise RuntimeError(f"serpapi: {data['error']}")
    return data


def _page1_negatives(organic: list, own_domain: str) -> list:
    """Reputation-damaging results on a page (excludes the company's own site)."""
    out = []
    for r in organic:
        title, link, snippet = r.get("title", ""), r.get("link", ""), r.get("snippet", "")
        dom = _domain(link)
        if own_domain and dom.endswith(own_domain):
            continue
        if _looks_negative(title, link, snippet):
            out.append({"position": r.get("position"), "title": title,
                        "link": link, "domain": dom})
    return out


def _run_variation_sweep(company, location: str, own_domain: str) -> list:
    """Query each branded variation; record page-1 negatives per variation.
    One SerpAPI call per variation — WEEKLY only (the caller gates cadence)."""
    city = location.split(",")[0].strip() if location else ""
    sweep = []
    for template, label in VARIATIONS:
        if "{city}" in template and not city:
            continue
        query = template.format(name=company.name, city=city)
        lbl = label.format(city=city) if "{city}" in label else label
        try:
            organic = (_search(query, location).get("organic_results") or [])
        except Exception as e:
            sweep.append({"query": query, "label": lbl, "error": str(e),
                          "negatives": [], "top_negative_position": None})
            continue
        negs = _page1_negatives(organic, own_domain)
        sweep.append({
            "query": query, "label": lbl, "negatives": negs,
            "top_negative_position": min(
                (n["position"] for n in negs if n.get("position")), default=None),
        })
    return sweep


def _sweep_state() -> dict:
    try:
        return json.loads(_SWEEP_STATE.read_text())
    except Exception:
        return {}


def _sweep_save(state: dict) -> None:
    _SWEEP_STATE.parent.mkdir(parents=True, exist_ok=True)
    _SWEEP_STATE.write_text(json.dumps(state, indent=2))


def _sweep_due(rec: dict) -> bool:
    ts = (rec or {}).get("ts")
    if not ts:
        return True
    try:
        last = datetime.fromisoformat(ts)
    except Exception:
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() >= _SWEEP_EVERY_DAYS * 86400


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
    try:
        data = _search(company.name, location)
    except Exception as e:
        return CollectorResult.failed(SOURCE, f"serpapi request failed: {e}")

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

    # --- Branded-variation sweep (weekly) -----------------------------------
    # The bare-name query above is only ONE of the searches people run. Sweep
    # "<brand> scam / reviews / reddit / working at ...", each its own SERP, so
    # the card shows the reputation picture per search intent. Runs weekly (cost)
    # and caches the result so the card still reflects it on the off days.
    try:
        state = _sweep_state()
        rec = state.get(company.name) or {}
        if _sweep_due(rec):
            sweep = _run_variation_sweep(company, location, own_domain)
            state[company.name] = {"ts": datetime.now(timezone.utc).isoformat(),
                                   "sweep": sweep}
            _sweep_save(state)
        else:
            sweep = rec.get("sweep") or []
    except Exception as e:
        sweep = []
        res.evidence["variation_sweep_error"] = str(e)

    if sweep:
        res.evidence["variation_sweep"] = sweep
        hits = [s for s in sweep if s.get("negatives")]
        res.metrics["variation_queries"] = len(sweep)
        res.metrics["variation_queries_with_negatives"] = len(hits)
        if hits:
            parts = []
            for s in hits:
                pos = s.get("top_negative_position")
                parts.append(f"'{s['label']}' #{pos}" if pos else f"'{s['label']}'")
            msg = (f"Negative results rank on page 1 for {len(hits)} of "
                   f"{len(sweep)} branded searches — " + ", ".join(parts))
            worst = None
            for s in hits:
                for n in s["negatives"]:
                    if worst is None or (n.get("position") or 99) < (worst.get("position") or 99):
                        worst = n
            res.flag(NEGATIVE, msg, url=(worst or {}).get("link"),
                     detail=(worst or {}).get("title"))

    return res
