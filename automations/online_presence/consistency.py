"""Does every site say what the office told us on sign-up?

The sign-up answers are the TRUTH: business name, address, phone, website,
the Google listing link, and (optional) their Indeed / Glassdoor pages.
Every audit reads each site and checks it against those answers, so a wrong
city on Indeed or an old phone on the website is caught by name instead of
noticed by an applicant (Megan 2026-11-08: "when you do audits it matches the
info it should").

    checks(p) -> [{"site", "item", "ok", "expected", "found", "where"}]

ok = True (matches), False (wrong / missing), None (couldn't check it
automatically -- never reported as a pass).

INDEED AND GLASSDOOR ARE NEVER READ DIRECTLY. Both put up robot checks, and
we don't get around those -- no browser-pretending, no automated browser.
Their rows are "check by hand" with the link, plus what Google's own results
show about them (the same SerpAPI search the brand card already runs).

We read only the office's OWN website and Google's API, and say who we are
(config.HTTP_USER_AGENT), like every other brand-audit collector.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from automations.brand_audit.config import HTTP_USER_AGENT

_UA = {"User-Agent": HTTP_USER_AGENT}
_STREET = {"parkway": "pkwy", "street": "st", "road": "rd", "avenue": "ave",
           "boulevard": "blvd", "drive": "dr", "suite": "ste", "#": "ste",
           "highway": "hwy", "freeway": "fwy", "lane": "ln", "court": "ct"}
_SOCIAL = {"instagram": r"instagram\.com/", "facebook": r"facebook\.com/",
           "linkedin": r"linkedin\.com/company", "x": r"(twitter|x)\.com/",
           "google": r"(g\.page|maps\.app\.goo\.gl|google\.com/maps)"}


# ---- normalising ----------------------------------------------------------
def digits(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else d


def addr_key(addr: str) -> Dict[str, str]:
    """The parts of an address that must agree: street number, street word,
    ZIP. Suite and spelling ('Pkwy' / 'Parkway') don't count against it."""
    a = (addr or "").lower()
    for k, v in _STREET.items():
        a = re.sub(r"\b%s\b" % re.escape(k) if k != "#" else "#", v, a)
    num = re.search(r"\b(\d{2,6})\s+[a-z]", a)
    zipc = re.search(r"\b(\d{5})(?:-\d{4})?\b(?!.*\b\d{5}\b)", a)
    street = re.search(r"\b\d{2,6}\s+([a-z]+)", a)
    return {"number": num.group(1) if num else "",
            "street": street.group(1) if street else "",
            "zip": zipc.group(1) if zipc else ""}


def same_address(a: str, b: str) -> bool:
    ka, kb = addr_key(a), addr_key(b)
    return bool(ka["number"] and ka["zip"]) and ka == kb


def city_of(addr: str) -> str:
    m = re.search(r",\s*([A-Za-z .'-]+?)\s*,\s*[A-Z]{2}\b", addr or "")
    return m.group(1).strip() if m else ""


def host(url: str) -> str:
    h = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    return h[4:] if h.startswith("www.") else h


# ---- reading the sites -----------------------------------------------------
def _get(url: str) -> Optional[str]:
    import requests
    try:
        r = requests.get(url, headers=_UA, timeout=25, allow_redirects=True)
        return r.text if r.ok else None
    except Exception:
        return None


def _text(html: str) -> str:
    from html import unescape
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", body)))


def _row(site, item, ok, expected, found, where) -> Dict:
    return {"site": site, "item": item, "ok": ok, "expected": expected,
            "found": found, "where": where}


def google_checks(p, aliases: Dict[str, set] | None = None) -> List[Dict]:
    from automations.brand_audit import gbp_api
    if not p.google_link and not p.gbp_location:
        return [_row("Google", "listing", False, "the Google listing link from sign-up",
                     "no link on file", "sign-up")]
    try:
        loc = (gbp_api.location_for_link(p.google_link) if p.google_link else None)
        if loc is None and p.gbp_location:
            loc = next((l for l in gbp_api.all_locations()
                        if l["path"] == p.gbp_location), None)
    except Exception as e:
        return [_row("Google", "listing", None, p.google_link, f"couldn't read ({e})"[:90],
                     "Business Profile API")]
    if loc is None:
        return [_row("Google", "listing", False, p.google_link or p.gbp_location,
                     "not a listing we manage (Manager invite not accepted yet?)",
                     "Business Profile API")]
    w = f"Google Business Profile: {loc['title']}"
    out = [_row("Google", "listing is the one they gave us",
                (not p.gbp_location) or loc["path"] == p.gbp_location,
                p.gbp_location or "(linked from their link)", loc["path"], w)]
    if p.business_name:
        out.append(_row("Google", "business name",
                        loc["title"].strip().lower() == p.business_name.strip().lower(),
                        p.business_name, loc["title"], w))
    if p.address:
        out.append(_row("Google", "address", same_address(p.address, loc["address"]),
                        p.address, loc["address"] or "(none)", w))
    if p.phone:
        out.append(_row("Google", "phone", digits(p.phone) == digits(loc["phone"]),
                        p.phone, loc["phone"] or "(none)", w))
    if p.website:
        out.append(_row("Google", "website", host(p.website) == host(loc["website"]),
                        p.website, loc["website"] or "(none)", w))
        if loc["website"]:
            out.append(_row("Google", "website link is secure (https)",
                            not loc["website"].startswith("http://"),
                            "https://…", loc["website"], w))
    out.append(_row("Google", "listing verified", loc.get("verified") is not False,
                    "verified", "verified" if loc.get("verified") else "NOT verified", w))
    # The social links ON the Google listing must be their accounts too
    # (Megan 2026-11-11: "we're looking at their website and google for links
    # right?"). Same rule as the website's links.
    try:
        on_google = gbp_api.social_links(loc["path"])
    except Exception as e:
        on_google = None
        out.append(_row("Google", "social links", None, "", f"couldn't read ({type(e).__name__})", w))
    if on_google is not None:
        for page, url in p.social_links.items():
            if page == "youtube":
                continue
            got = on_google.get(page, "")
            ok = bool(got) and (social_handle(got) == social_handle(url)
                                or same_account(page, url, got, aliases))
            out.append(_row("Google", f"links to their {page}", ok, url,
                            "links to it" if ok else (f"links to {got} instead" if got
                                                      else f"no {page} link on the listing"), w))
    return out


def website_checks(p, aliases: Dict[str, set] | None = None) -> List[Dict]:
    if not p.website:
        return [_row("Website", "website", False, "their website from sign-up",
                     "no website on file", "sign-up")]
    home = _get(p.website)
    if home is None:
        return [_row("Website", "site loads", False, p.website, "didn't load", p.website)]
    pages = {p.website: home}
    for path in re.findall(r'href=["\']([^"\']*(?:contact|about)[^"\']*)["\']', home, re.I)[:4]:
        from urllib.parse import urljoin
        u = urljoin(p.website, path)
        if host(u) == host(p.website) and u not in pages:
            html = _get(u)
            if html:
                pages[u] = html
    text = " ".join(_text(h) for h in pages.values())
    allhtml = " ".join(pages.values())
    where = ", ".join(pages)
    out = [_row("Website", "site loads", True, p.website, "loads", p.website)]
    # Feeds the card's "Rank higher on Google" ✅ marks, not the info problems.
    m = re.search(r"<title[^>]*>(.*?)</title>", home, re.I | re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    if p.business_name:
        out.append(_row("Website", "name in page title",
                        p.business_name.strip().lower() in title.lower(),
                        p.business_name, title or "no page title", p.website))
    if p.phone:
        found = {digits(x) for x in re.findall(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)}
        found |= {digits(x) for x in re.findall(r'tel:([+\d().\s-]+)', allhtml)}
        out.append(_row("Website", "phone", digits(p.phone) in found, p.phone,
                        ", ".join(sorted(f for f in found if f)) or "no phone on the site", where))
    if p.address:
        k = addr_key(p.address)
        ok = bool(k["number"] and re.search(r"\b%s\b" % k["number"], text)
                  and k["zip"] and k["zip"] in text)
        out.append(_row("Website", "address", ok, p.address,
                        "found" if ok else "address not on the home/contact pages", where))
    linked = re.findall(r'href=["\']([^"\']+)', allhtml)
    for page, url in p.social_links.items():
        want = social_handle(url)
        theirs = [u for u in linked if re.search(_SOCIAL.get(page, "$^"), u, re.I)
                  or (page == "tiktok" and "tiktok.com" in u)
                  or (page == "youtube" and re.search(r"youtu\.?be", u))]
        handles = sorted({social_handle(u) for u in theirs})
        ok = want in handles or any(same_account(page, url, u, aliases) for u in theirs)
        out.append(_row("Website", f"links to their {page}", ok, url,
                        "links to it" if ok else (f"links to {', '.join(handles)} instead"
                                                  if handles else f"no {page} link on the site"),
                        where))
    return out


def social_handle(url: str) -> str:
    """'instagram.com/AlphaleteMarketing/reels' -> 'instagram.com/alphaletemarketing'
    -- the account, not the page of it, so two links to one account agree."""
    u = re.sub(r"^https?://", "", (url or "").strip().lower())
    u = re.sub(r"^(www\.|m\.|mobile\.|[a-z]{2}\.)(?=linkedin\.com)", "", u)
    u = re.sub(r"^(www\.|m\.|mobile\.|web\.)", "", u)
    # facebook.com/profile.php?id=123 IS the account (its number), keep it
    m = re.match(r"(facebook\.com)/profile\.php\?(?:.*&)?id=(\d+)", u)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    u = u.split("?")[0].split("#")[0]
    u = u.replace("twitter.com", "x.com").replace("youtu.be", "youtube.com")
    parts = [x for x in u.split("/") if x]
    if not parts:
        return ""
    keep = 3 if len(parts) > 2 and parts[1] in ("company", "in", "channel", "c", "user") else 2
    return "/".join(parts[:keep]).lstrip("@")


def account_key(url: str) -> str:
    """The account part alone: 'alphaletemarketing', '15255695'."""
    return social_handle(url).split("/")[-1].lower()


def same_account(page: str, a: str, b: str, aliases: Dict[str, set] | None) -> bool:
    """Two links to ONE account, however each is written: the same handle,
    or both among the names that account is known by -- its number and
    username (from Zoho) and the address Google shows for it (Megan
    2026-11-10: "we need to be able to read both versions")."""
    if social_handle(a) == social_handle(b):
        return True
    known = (aliases or {}).get(page) or set()
    return account_key(a) in known and account_key(b) in known


def _directory_checks(site: str, url: str, p) -> List[Dict]:
    """Indeed / Glassdoor: NOT fetched (they block robots, and we don't get
    around that). One "check by hand" row saying exactly what should match."""
    if not url:
        return []
    city = city_of(p.address) or "their city"
    what = f"city = {city}, page claimed"
    if site == "Indeed":
        what += ", open jobs show on the company page"
    return [_row(site, "check by hand", None, what,
                 f"open {url} and confirm", url)]


def checks(p, aliases: Dict[str, set] | None = None) -> List[Dict]:
    """Every check for one office (each site fails soft on its own)."""
    out: List[Dict] = []
    for fn in (google_checks, website_checks):
        try:
            out += fn(p, aliases)
        except Exception as e:
            out.append(_row(fn.__name__.split("_")[0].title(), "check", None, "",
                            f"check crashed: {type(e).__name__}", ""))
    # what the site SAYS: spelling, wrong info, hiring wording (website_content.py)
    if any(r["item"] == "site loads" and r["ok"] for r in out):
        try:
            from automations.online_presence import website_content
            out += website_content.rows(p)
        except Exception as e:
            out.append(_row("Website", "content check", None, "", f"check crashed: {type(e).__name__}", ""))
    for site, url in (("Indeed", p.indeed_url), ("Glassdoor", p.glassdoor_url)):
        try:
            out += _directory_checks(site, url or "", p)
        except Exception as e:
            out.append(_row(site, "check", None, "", f"check crashed: {type(e).__name__}", url))
    return out
