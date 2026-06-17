"""Reddit mentions collector.

Reddit's public .json endpoints now return 403 to non-OAuth traffic (the same
crackdown behind the API registration wall), so we discover Reddit threads via
Google's index using SerpAPI (`site:reddit.com "<brand>"`) — a reliable keyless
path that reuses the SerpAPI key we already have.

What we get: which subreddits mention the brand, thread titles + links, and a
rough negative-sentiment flag (risky-subreddit + keyword heuristic).
What we DON'T get this way: live comment counts / upvotes / subscriber counts,
and posting. Those need the authenticated Reddit API (Phase 3). We say so in a
flag so the picture isn't mistaken for complete.
"""
from __future__ import annotations

from urllib.parse import urlparse

from automations.brand_audit import credentials
from automations.brand_audit.collectors.base import (
    CollectorResult, get_json, NEGATIVE, INFO,
)

SOURCE = "reddit"
_SERP_URL = "https://serpapi.com/search.json"

RISKY_SUBREDDITS = {"devilcorp", "antimlm", "scams", "scam", "mlm"}
NEGATIVE_WORDS = (
    "scam", "pyramid", "mlm", "cult", "avoid", "ripoff", "rip off", "predatory",
    "warning", "fraud", "lawsuit", "exposed", "terrible", "worst", "sketchy",
    "exploit", "commission only", "100% commission",
)


def _subreddit_name(url: str) -> str:
    """Pull 'Devilcorp' from .../r/Devilcorp/comments/... or /r/<sub>/."""
    try:
        parts = [p for p in urlparse(url).path.split("/") if p]
    except Exception:
        return ""
    if len(parts) >= 2 and parts[0].lower() == "r":
        return parts[1]
    return ""


def _looks_negative(subreddit: str, title: str, snippet: str) -> bool:
    if subreddit.lower() in RISKY_SUBREDDITS:
        return True
    blob = f"{title} {snippet}".lower()
    return any(w in blob for w in NEGATIVE_WORDS)


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    if not company.name:
        return CollectorResult.failed(SOURCE, "no company name to search")

    params = {
        "engine": "google",
        "q": f'site:reddit.com "{company.name}"',
        "hl": "en",
        "gl": "us",
        "num": "20",
        "api_key": credentials.serpapi_api_key(),
    }
    try:
        data = get_json(_SERP_URL, params=params)
    except Exception as e:
        return CollectorResult.failed(SOURCE, f"reddit-via-serpapi failed: {e}")
    if data.get("error"):
        # SerpAPI returns an "error" when a query has no results — treat as zero.
        res.metrics = {"mentions_found": 0, "negative_mentions": 0,
                       "subreddits": []}
        res.flag(INFO, "No Reddit mentions found via Google index.")
        return res

    mentions = []
    subs = set()
    for r in (data.get("organic_results") or []):
        link = r.get("link", "")
        if "reddit.com" not in link:
            continue
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        sub = _subreddit_name(link)
        if sub:
            subs.add(sub)
        mentions.append({
            "subreddit": sub,
            "title": title,
            "link": link,
            "snippet": snippet,
            "negative": _looks_negative(sub, title, snippet),
        })

    negatives = [m for m in mentions if m["negative"]]
    res.metrics = {
        "mentions_found": len(mentions),
        "negative_mentions": len(negatives),
        "subreddits": sorted(subs),
        # Needs authenticated Reddit API (Phase 3):
        "own_subreddit_subscribers": None,
    }
    res.evidence["mentions"] = mentions

    for m in negatives:
        where = f"r/{m['subreddit']}" if m["subreddit"] else "a Reddit thread"
        res.flag(NEGATIVE, f"Negative Reddit thread in {where}",
                 url=m["link"], detail=m["title"])

    if not mentions:
        res.flag(INFO, "No Reddit mentions found via Google index.")
    else:
        res.flag(INFO, "Reddit discovered via Google; live comment counts / "
                       "posting need the authenticated Reddit API (Phase 3).")
    return res
