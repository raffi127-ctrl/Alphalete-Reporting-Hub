"""Website freshness + blog collector.

Fetches the homepage and the sitemap to answer: is the site up, does it have a
blog, and how FRESH is the content (newest lastmod date)? Freshness + blog
cadence are the website metrics that matter — a stale site or an empty blog is
the real signal, not "does a website exist".

No bs4 dependency — light regex for links + stdlib XML for the sitemap. Fails
soft: an unreachable site or missing sitemap degrades gracefully.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

from automations.brand_audit.collectors.base import (
    CollectorResult, http_get, WARN, INFO,
)

SOURCE = "website"
_BLOG_HINTS = ("/blog", "/news", "/articles", "/insights", "/resources", "/post")


def _norm_root(url: str) -> str:
    if not url:
        return ""
    if not urlparse(url).scheme:
        url = "https://" + url
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _parse_date(s: str):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s.replace("Z", "+0000")
                                   if fmt.endswith("%z") else s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _sitemap_lastmods(root: str):
    """Return (newest_datetime, total_urls, has_blog_url, recent_90d_count,
    blog_url_count). Follows one level of sitemap-index nesting."""
    newest = None
    total = 0
    blog = False
    blog_urls = 0
    recent_90d = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    to_fetch = [urljoin(root + "/", "sitemap.xml")]
    seen = set()
    while to_fetch and len(seen) < 8:
        sm = to_fetch.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = http_get(sm, browser=True)
            if not r.ok:
                continue
            rootxml = ET.fromstring(r.content)
        except Exception:
            continue
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        # nested sitemap index?
        for sub in rootxml.findall(".//s:sitemap/s:loc", ns):
            if sub.text:
                to_fetch.append(sub.text.strip())
        for urlel in rootxml.findall(".//s:url", ns):
            loc = urlel.findtext("s:loc", default="", namespaces=ns)
            lm = urlel.findtext("s:lastmod", default="", namespaces=ns)
            total += 1
            if any(h in (loc or "").lower() for h in _BLOG_HINTS):
                blog = True
                blog_urls += 1
            dt = _parse_date(lm)
            if dt:
                if newest is None or dt > newest:
                    newest = dt
                if dt >= cutoff:
                    recent_90d += 1
    return newest, total, blog, recent_90d, blog_urls


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    root = _norm_root(company.website)
    if not root:
        return CollectorResult.failed(SOURCE, "no website URL")

    reachable = False
    status = None
    last_modified_header = None
    has_blog_link = False
    title = None
    secure = None
    try:
        r = http_get(root, browser=True, allow_redirects=True)
        status = r.status_code
        reachable = r.ok
        secure = str(r.url).lower().startswith("https://")
        last_modified_header = r.headers.get("Last-Modified")
        html = r.text if r.ok else ""
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
        for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
            if any(h in href.lower() for h in _BLOG_HINTS):
                has_blog_link = True
                break
    except Exception as e:
        res.error = f"homepage fetch failed: {e}"

    newest, total_urls, blog_in_sitemap, recent_90d, blog_urls = _sitemap_lastmods(root)
    newest_age = (datetime.now(timezone.utc) - newest).days if newest else None

    res.metrics = {
        "reachable": reachable,
        "secure_https": secure,
        "http_status": status,
        "has_blog": has_blog_link or blog_in_sitemap,
        "blog_post_count": blog_urls or None,
        "sitemap_url_count": total_urls or None,
        "pages_updated_90d": recent_90d,
        "newest_content_age_days": newest_age,
        "last_modified_header": last_modified_header,
    }
    res.evidence["root"] = root
    res.evidence["title"] = title
    res.evidence["newest_content_date"] = newest.isoformat() if newest else None

    if not reachable:
        res.flag(WARN, f"Website not reachable (status {status})", url=root)
    if reachable and not (has_blog_link or blog_in_sitemap):
        res.flag(INFO, "No blog detected — blogging helps you outrank negative "
                       "results for your name.", url=root)
    if newest_age is not None and newest_age > 90:
        res.flag(WARN, f"Site content looks stale (newest page ~{newest_age} "
                       "days old).", url=root)
    return res
