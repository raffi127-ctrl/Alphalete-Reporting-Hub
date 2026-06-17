"""Deep design review — screenshots EVERY core page of the website and asks
Claude (vision) for a candid, page-by-page critique, plus a comparison against
the company's Instagram vibe (the site can feel dull while the IG feels fun —
this surfaces and fixes that gap).

Heavier + slower than the weekly card's homepage review (it renders many pages
and makes one large vision call), so it's a separate on-demand command:

  python -m automations.brand_audit.design_review --company "Alphalete Marketing"

Saves an HTML report to output/ and prints the summary. Fails soft per page.
"""
from __future__ import annotations

import base64
import json
import sys
from urllib.parse import urlparse

from automations.brand_audit import credentials, intake
from automations.brand_audit.config import OUTPUT_DIR, DEFAULT_COMPANY
from automations.brand_audit.collectors import website  # sitemap helper reuse

MODEL = "claude-opus-4-8"
_SKIP_PATHS = {"privacy-policy", "terms-and-conditions"}

_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_vibe": {"type": "string"},
        "brand_gap_vs_instagram": {"type": "string"},
        "pages": {"type": "array", "items": {
            "type": "object",
            "properties": {"page": {"type": "string"}, "note": {"type": "string"}},
            "required": ["page", "note"], "additionalProperties": False}},
        "ideas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overall_vibe", "brand_gap_vs_instagram", "pages", "ideas"],
    "additionalProperties": False,
}


def _core_pages(company) -> list[tuple[str, str]]:
    """(label, url) for the main pages, from the sitemap — skip legal pages and
    individual blog posts (keep the blog index)."""
    root = website._norm_root(company.website)
    newest, total, blog, recent, blog_urls = (None, 0, False, 0, 0)
    # reuse the sitemap walker just for URLs
    import xml.etree.ElementTree as ET
    from automations.brand_audit.collectors.base import http_get
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls, to, seen = [], [root + "/sitemap.xml"], set()
    while to and len(seen) < 8:
        sm = to.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = http_get(sm, browser=True)
            x = ET.fromstring(r.content)
        except Exception:
            continue
        for s in x.findall(".//s:sitemap/s:loc", ns):
            if s.text:
                to.append(s.text.strip())
        for u in x.findall(".//s:url/s:loc", ns):
            if u.text:
                urls.append(u.text.strip())

    pages = []
    for u in urls:
        path = urlparse(u).path.strip("/")
        if path in _SKIP_PATHS:
            continue
        if path.startswith("blog/") and path != "blog":   # skip blog posts
            continue
        label = "Home" if path == "" else path.split("/")[-1].replace("-", " ").title()
        pages.append((label, u))
    # de-dup + keep home first, cap to keep the vision call reasonable
    seen_l, ordered = set(), []
    for label, u in sorted(pages, key=lambda p: (p[0] != "Home", p[0])):
        if label not in seen_l:
            seen_l.add(label)
            ordered.append((label, u))
    return ordered[:9]


def _shoot_all(pages: list[tuple[str, str]], ig_url: str):
    """One browser, screenshot each page + the IG profile. Returns
    list[(label, png_bytes)] (skips failures)."""
    shots = []
    try:
        from patchright.sync_api import sync_playwright
    except Exception:
        return shots
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        for label, url in pages:
            try:
                try:
                    pg.goto(url, wait_until="networkidle", timeout=40000)
                except Exception:
                    pg.goto(url, wait_until="load", timeout=40000)
                pg.wait_for_timeout(1200)
                shots.append((label, pg.screenshot()))
            except Exception:
                continue
        if ig_url:
            try:
                pg.goto(ig_url, wait_until="networkidle", timeout=30000)
                pg.wait_for_timeout(1500)
                shots.append(("Instagram", pg.screenshot()))
            except Exception:
                pass
        b.close()
    return shots


def review(company) -> dict:
    pages = _core_pages(company)
    shots = _shoot_all(pages, company.instagram)
    if not shots:
        raise RuntimeError("couldn't render any pages")

    has_ig = any(l == "Instagram" for l, _ in shots)
    content = []
    for label, png in shots:
        content.append({"type": "text", "text": f"--- {label} ---"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/png",
            "data": base64.standard_b64encode(png).decode()}})
    content.append({"type": "text", "text": (
        f"These are screenshots of the website pages for {company.name}, a "
        f"door-to-door sales & marketing company whose target audience skews "
        f"young (20-25). The owner feels the site looks dull and not fun"
        + (", while the Instagram (last image) has a very different, more "
           "energetic vibe. Compare them honestly." if has_ig else
           " — their Instagram is much more energetic and fun (not shown here).")
        + " Give a candid, plain-language design review:\n"
        "- overall_vibe: how the whole site feels\n"
        "- brand_gap_vs_instagram: how the site's energy compares to the IG vibe "
        "and what the site is missing\n"
        "- pages: one honest note per page (use the labels above)\n"
        "- ideas: 4-6 concrete, specific ideas to make the site feel fun, "
        "energetic, and on-brand with the Instagram. Be specific, not vague.")})

    import anthropic
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    resp = client.messages.create(
        model=MODEL, max_tokens=2500,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": content}])
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    data = json.loads(text)
    data["_pages_captured"] = [l for l, _ in shots]
    return data


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    import argparse
    p = argparse.ArgumentParser(prog="brand_audit.design_review")
    p.add_argument("--company", default=DEFAULT_COMPANY)
    args = p.parse_args(argv)
    company = intake.find_company(args.company)
    if not company:
        print(f"!! company {args.company!r} not found", file=sys.stderr)
        return 1
    print(f"reviewing every page of {company.name} (this takes a minute)...")
    data = review(company)
    print("captured:", ", ".join(data["_pages_captured"]))
    print("\nOVERALL VIBE:", data["overall_vibe"])
    print("\nGAP VS INSTAGRAM:", data["brand_gap_vs_instagram"])
    print("\nPER PAGE:")
    for pg in data["pages"]:
        print(f"  [{pg['page']}] {pg['note']}")
    print("\nIDEAS:")
    for i in data["ideas"]:
        print("  -", i)
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
