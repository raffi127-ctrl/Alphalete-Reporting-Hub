"""Read what their website actually SAYS (Megan 2026-11-11: "looking at the
actual content on their website? we should also be scanning for grammar /
verbiage / incorrect info").

Lucy reads the homepage plus up to 4 key pages (about, contact, careers,
services...), and the AI lists only real mistakes, each with the EXACT text
from the page and the fix. A quote that isn't really on the page is thrown
out, so the card never shows a made-up problem.

Three checklist rows come out of it (consistency.checks):
    spelling + grammar · the info on the site is correct · hiring wording
    follows the rules (no age / gender / "who we hire")

Cached per office: the AI only runs again when the site's text changes.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

MODEL = "claude-opus-5-5"
MAX_PAGES = 5
PAGE_CHARS = 6000
KEY_PAGES = re.compile(r"about|contact|career|join|jobs|hiring|team|service|what-we-do|faq|location",
                       re.I)

ROWS = (
    ("no spelling or grammar mistakes", ("spelling", "grammar")),
    ("info on the site is correct", ("wrong_info", "outdated", "placeholder")),
    ("hiring wording follows the rules", ("rules",)),
)

_SCHEMA = {
    "type": "object",
    "properties": {"issues": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["spelling", "grammar", "wrong_info", "outdated",
                                                "placeholder", "rules"]},
            "page": {"type": "string"},
            "quote": {"type": "string"},
            "fix": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["kind", "page", "quote", "fix", "why"],
        "additionalProperties": False}}},
    "required": ["issues"],
    "additionalProperties": False,
}

_SYSTEM = """You proofread small business websites for door-to-door sales offices. You list only REAL mistakes a customer or applicant would notice. You are not a copywriter: never flag style, tone, length or word choice you would merely write differently.

Report, per issue, one of these kinds:
- spelling: a misspelled word.
- grammar: a clearly broken sentence (wrong word, missing word, its/it's, their/there, subject-verb).
- wrong_info: a phone number, address, business name or city that doesn't match the facts given.
- outdated: an old copyright year (older than the current year given) or dates/events clearly in the past presented as upcoming.
- placeholder: template text left in ("Lorem ipsum", "Your Company", "123 Main St", "example@email.com").
- rules: hiring wording that names an age, gender or who they want to hire ("young", "guys", "20-somethings", "men", "girls", "recent grads only"). "No experience needed", "we're hiring", "fast promotion" are fine.

Rules:
- quote: copy the exact text from the page, character for character, 3 to 15 words, enough to find it.
- fix: the corrected version of that same text, changing as little as possible. For rules, a neutral rewrite.
- why: one short plain sentence, no jargon.
- Brand names, product names, slang used on purpose, ALL CAPS headings, and missing periods in headings/buttons are NOT mistakes.
- Menu items and footer links repeated on every page: report once.
- If there are no real mistakes, return an empty list. An empty list is a good answer.
- At most 12 issues, most important first (rules, wrong_info, placeholder, then the rest)."""


def _get(url: str) -> Optional[str]:
    from automations.online_presence.consistency import _get as get
    return get(url)


def _text(html: str) -> str:
    from automations.online_presence.consistency import _text as text
    return text(html).strip()


def pages(site: str) -> List[Dict]:
    """[{"url", "text"}]: the homepage + up to 4 key pages on the same site."""
    if not site:
        return []
    home = site if site.startswith("http") else f"https://{site}"
    html = _get(home)
    if not html:
        return []
    out = [{"url": home, "text": _text(html)[:PAGE_CHARS]}]
    base = urlparse(home).netloc.lower().removeprefix("www.")
    seen = {home.rstrip("/")}
    for href in re.findall(r'href=["\']([^"\'#]+)["\']', html, re.I):
        u = urljoin(home, href).split("?")[0].rstrip("/")
        if (u in seen or urlparse(u).netloc.lower().removeprefix("www.") != base
                or re.search(r"\.(jpg|jpeg|png|gif|pdf|svg|webp|css|js|xml)$", u, re.I)
                or not KEY_PAGES.search(u)):
            continue
        seen.add(u)
        h = _get(u)
        if h:
            out.append({"url": u, "text": _text(h)[:PAGE_CHARS]})
        if len(out) >= MAX_PAGES:
            break
    return out


def _facts(p) -> str:
    from automations.online_presence.google_description import SELLS
    import datetime as dt
    return "\n".join(x for x in (
        f"Business name: {p.business_name}",
        f"Phone: {p.phone}" if p.phone else "",
        f"Address: {p.address}" if p.address else "",
        f"What they sell: {SELLS.get((p.campaign or '').lower(), '')}" if getattr(p, "campaign", "") else "",
        f"Current year: {dt.date.today().year}",
    ) if x)


def _ask(p, got: List[Dict]) -> List[Dict]:
    import anthropic
    from automations.brand_audit import credentials
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    body = "\n\n".join(f"=== PAGE: {x['url']} ===\n{x['text']}" for x in got)
    resp = client.messages.create(
        model=MODEL, max_tokens=3000, system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": f"Facts on file:\n{_facts(p)}\n\n{body}"}])
    text = next(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text).get("issues") or []


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def real(issues: List[Dict], got: List[Dict]) -> List[Dict]:
    """Keep only issues whose quote is really on a page Lucy read, and whose
    fix actually changes something."""
    texts = {x["url"]: _squash(x["text"]) for x in got}
    every = " ".join(texts.values())
    out = []
    for i in issues:
        q = _squash(i.get("quote"))
        if not q or q == _squash(i.get("fix")) or q not in every:
            continue
        if i.get("page") not in texts:          # point at the page it's really on
            i = dict(i, page=next((u for u, t in texts.items() if q in t), got[0]["url"]))
        out.append(i)
    return out


def check(p) -> Optional[Dict]:
    """{"pages": [urls], "issues": [...]} or None when the site can't be read."""
    got = pages(p.website)
    if not got:
        return None
    key = hashlib.sha1(json.dumps([got, _facts(p)], sort_keys=True).encode()).hexdigest()
    cache = p.path("website_content.json")
    try:
        saved = json.loads(cache.read_text())
        if saved.get("key") == key:
            return saved["result"]
    except Exception:
        pass
    try:
        issues = real(_ask(p, got), got)
    except Exception:
        return {"pages": [x["url"] for x in got], "issues": None}
    result = {"pages": [x["url"] for x in got], "issues": issues}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "result": result}))
    except Exception:
        pass
    return result


def rows(p) -> List[Dict]:
    """The 3 checklist rows, in consistency.py's row shape (+ "issues")."""
    from automations.online_presence.consistency import _row
    res = check(p)
    if res is None:
        return []                         # site loads row already says it's down
    out = []
    for item, kinds in ROWS:
        if res["issues"] is None:
            out.append(dict(_row("Website", item, None, "", "Lucy couldn't read it this week", ""),
                            issues=[]))
            continue
        mine = [i for i in res["issues"] if i["kind"] in kinds]
        first = mine[0] if mine else {}
        out.append(dict(_row("Website", item, not mine, first.get("fix", ""),
                             (f'"{first["quote"]}"' + (f" (+{len(mine) - 1} more)" if len(mine) > 1 else ""))
                             if mine else "", first.get("page", "")), issues=mine))
    return out
