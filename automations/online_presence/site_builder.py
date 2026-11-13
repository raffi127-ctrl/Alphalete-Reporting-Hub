"""Build an office's website from its sign-up (Megan 2026-11-11: BIS's $300
setup -> "A, we host it" -> "EVERY site needs to be different. we would ask
them for 10-15 photos to launch the website and their social media").

    python -m automations.online_presence.site_builder kash            # -> output/sites/kash/
    python -m automations.online_presence.site_builder kash --open     # + open the preview

What makes each site its own:
  * DESIGN: one of 4 looks (THEMES: layout, fonts, light/dark, section order),
    picked by the office or spread by its key, in the office's own colors/logo.
  * PHOTOS: their 10-15 launch photos run through every page + a gallery.
  * WORDS: written for that office from the owner's answers (site_copy.py),
    so no two sites share text (duplicate text hurts every site on Google).

What every site shares -- built to pass Lucy's own weekly audit from day one:
  the business name in every page title; address + phone on every page;
  links to exactly the social accounts from sign-up; LocalBusiness schema;
  sitemap.xml + robots.txt; nothing that reads as a placeholder; pay numbers
  only when the office gives its OWN (feedback_house_rules_per_office); no
  age / gender / "who we hire" wording (feedback_recruiting_copy_compliance).

Office extras that aren't on the sign-up live in the office's `site.json`
(all optional): theme, colors, logo, photos (paths), careers_email,
apply_url, pay [{stage, time, pay}], areas, answers {started, different,
culture, anything}.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "sites"
MIN_PHOTOS, ASK_PHOTOS = 6, "10-15"

BRAND = {"att": "AT&T", "nds": "AT&T", "b2b_att": "AT&T Business", "verizon": "Verizon",
         "b2b_box": "Box Energy"}
PAGES = (("index.html", "Home"), ("about/index.html", "About"),
         ("contact/index.html", "Contact"), ("apply/index.html", "Apply"))
SOCIAL_NAME = {"instagram": "Instagram", "facebook": "Facebook", "linkedin": "LinkedIn",
               "x": "X", "tiktok": "TikTok", "youtube": "YouTube"}

# Four genuinely different looks. "home" is the section order on the homepage.
THEMES = {
    "bold": {"label": "Bold", "dark": True, "head": "Oswald", "body": "Inter", "hero": "full",
             "home": ["what", "path", "gallery", "why", "faq", "where", "band"],
             "colors": {"bg": "#0C0C0D", "accent": "#C8A24B", "accent2": "#B22733"}},
    "clean": {"label": "Clean", "dark": False, "head": "Playfair Display", "body": "Source Sans 3", "hero": "split",
              "home": ["what", "why", "path", "faq", "gallery", "where", "band"],
              "colors": {"bg": "#FBFAF7", "accent": "#1F4D7A", "accent2": "#C8A24B"}},
    "mosaic": {"label": "Mosaic", "dark": True, "head": "Archivo Black", "body": "Archivo", "hero": "mosaic",
               "home": ["gallery", "what", "path", "why", "where", "faq", "band"],
               "colors": {"bg": "#111418", "accent": "#36C2B4", "accent2": "#F2A541"}},
    # six more (Megan 2026-11-12: "lock down like 10 different formats")
    "night": {"label": "Night", "dark": True, "head": "Montserrat", "body": "Inter", "hero": "split",
              "home": ["what", "path", "why", "gallery", "faq", "where", "band"],
              "colors": {"bg": "#0E1116", "accent": "#C0392B", "accent2": "#F2F0EC"}},
    "sunrise": {"label": "Sunrise", "dark": False, "head": "Poppins", "body": "Inter", "hero": "full",
                "home": ["why", "what", "gallery", "path", "where", "faq", "band"],
                "colors": {"bg": "#FFFFFF", "accent": "#E07A1F", "accent2": "#1F2A44"}},
    "studio": {"label": "Studio", "dark": False, "head": "Archivo Black", "body": "Archivo", "hero": "mosaic",
               "home": ["what", "gallery", "faq", "path", "why", "where", "band"],
               "colors": {"bg": "#F4F4F2", "accent": "#2F6FEB", "accent2": "#111111"}},
    "classic": {"label": "Classic", "dark": False, "head": "Playfair Display", "body": "Inter", "hero": "framed",
                "home": ["what", "path", "gallery", "why", "where", "faq", "band"],
                "colors": {"bg": "#FFFDF8", "accent": "#7A1F2B", "accent2": "#C8A24B"}},
    "pro": {"label": "Pro", "dark": True, "head": "Cinzel", "body": "Source Sans 3", "hero": "framed",
            "home": ["why", "path", "what", "faq", "gallery", "where", "band"],
            "colors": {"bg": "#101418", "accent": "#C8A24B", "accent2": "#4A6FA5"}},
    "bright": {"label": "Bright", "dark": False, "head": "Bebas Neue", "body": "DM Sans", "hero": "split",
               "home": ["what", "why", "gallery", "faq", "path", "where", "band"],
               "colors": {"bg": "#FAFAFA", "accent": "#2F8F5B", "accent2": "#14151A"}},
    "warm": {"label": "Warm", "dark": False, "head": "DM Serif Display", "body": "DM Sans", "hero": "framed",
             "home": ["what", "why", "path", "gallery", "faq", "where", "band"],
             "colors": {"bg": "#F6EFE6", "accent": "#B4532A", "accent2": "#2E4A3F"}},
}

e = html.escape

# Google Fonts refuses the WHOLE request if a weight doesn't exist for a font.
FONT_WEIGHTS = {"Oswald": ":wght@400;600;700", "Inter": ":wght@400;600;700",
                "Playfair Display": ":wght@600;800", "Source Sans 3": ":wght@400;600;700",
                "Archivo Black": "", "Archivo": ":wght@400;600;700",
                "DM Serif Display": "", "DM Sans": ":wght@400;600;700",
                "Montserrat": ":wght@400;600;800", "Poppins": ":wght@400;600;700", "Cinzel": ":wght@700",
                "Bebas Neue": ""}


# ---- facts ------------------------------------------------------------------
def split_address(addr: str) -> Dict[str, str]:
    m = re.match(r"^\s*(.+?),\s*([^,]+?),\s*([A-Z]{2})\s*,?\s*(\d{5})(?:-\d{4})?\s*$", addr or "")
    if not m:
        return {"street": addr or "", "city": "", "state": "", "zip": ""}
    return {"street": m.group(1), "city": m.group(2), "state": m.group(3), "zip": m.group(4)}


def extras(p) -> Dict:
    try:
        return json.loads(p.path("site.json").read_text())
    except Exception:
        return {}


def pick_theme(p, x: Dict) -> str:
    if x.get("theme") in THEMES:
        return x["theme"]
    keys = sorted(THEMES)
    return keys[int(hashlib.sha1(p.key.encode()).hexdigest(), 16) % len(keys)]


def facts(p, x: Dict) -> Dict:
    from automations.online_presence.google_description import SELLS
    a = split_address(p.address)
    camp = (getattr(p, "campaign", "") or "att").lower()
    domain = re.sub(r"^https?://", "", (p.website or "").strip()).strip("/")
    theme = pick_theme(p, x)
    return {
        "name": p.business_name, "addr": a, "address": p.address, "phone": p.phone,
        "tel": re.sub(r"\D", "", p.phone or ""),
        "email": x.get("careers_email") or getattr(p, "contact_email", "") or "",
        "apply_url": x.get("apply_url") or "",
        "domain": domain, "url": f"https://{domain}" if domain else "",
        "socials": {k: v for k, v in p.social_links.items() if v},
        "google_link": getattr(p, "google_link", ""),
        "brand": BRAND.get(camp, ""), "sells": SELLS.get(camp, ""), "b2b": camp.startswith("b2b"),
        "city": a["city"], "state": a["state"], "areas": x.get("areas") or [],
        "pay": x.get("pay") or [], "logo": x.get("logo") or "",
        "photos": [ph for ph in (x.get("photos") or []) if Path(ph).exists()],
        "theme": theme, "t": THEMES[theme],
        "colors": {**THEMES[theme]["colors"], **(x.get("colors") or {})},
        "year": dt.date.today().year,
        "noindex": bool(x.get("noindex")),   # test sites: Google must not list them
    }


# ---- pieces -----------------------------------------------------------------
def _where(f) -> str:
    return ", ".join(x for x in (f["city"], f["state"]) if x)


def _img(f, i: int, depth: str, cls: str = "") -> str:
    """The i-th photo (wrapping), or a brand-colored panel -- never a 'photo here' box."""
    if not f["photos"]:
        return f'<div class="ph {cls}"></div>'
    name = f"img/{i % len(f['photos']) + 1}{Path(f['photos'][i % len(f['photos'])]).suffix.lower()}"
    return f'<img class="{cls}" src="{depth}{name}" alt="{e(f["name"])} team" loading="lazy">'


def _schema(f) -> str:
    a = f["addr"]
    data = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": f["name"],
            "telephone": f["phone"] or None, "url": f["url"] or None,
            "address": {"@type": "PostalAddress", "streetAddress": a["street"], "addressLocality": a["city"],
                        "addressRegion": a["state"], "postalCode": a["zip"], "addressCountry": "US"},
            "sameAs": list(f["socials"].values()) or None, "areaServed": f["areas"] or None}
    return f'<script type="application/ld+json">{json.dumps({k: v for k, v in data.items() if v})}</script>'


def _head(f, page: str, depth: str, desc: str) -> str:
    where = _where(f)
    title = f'{f["name"]} | {page}' + (f" | {where}" if where else "")
    canon = (f'{f["url"]}/' + ("" if page == "Home" else f"{page.lower()}/")) if f["url"] else ""
    t, c = f["t"], f["colors"]
    fonts = "&".join(f"family={x.replace(' ', '+')}" + FONT_WEIGHTS.get(x, ":wght@400;700")
                     for x in dict.fromkeys((t["head"], t["body"])))
    ink, soft, panel, line = (("#F2F0EC", "#A6A39D", "rgba(255,255,255,.05)", "rgba(255,255,255,.10)")
                              if t["dark"] else ("#1E1C19", "#5E5A54", "rgba(0,0,0,.035)", "rgba(0,0,0,.10)"))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>'
            f'<meta name="description" content="{e(desc)}">'
            + ('<meta name="robots" content="noindex,nofollow">' if f.get("noindex") else "")
            + (f'<link rel="canonical" href="{e(canon)}">' if canon else "")
            + f'<link rel="icon" href="{depth}favicon.svg">'
            f'<link rel="preconnect" href="https://fonts.googleapis.com">'
            f'<link href="https://fonts.googleapis.com/css2?{fonts}&display=swap" rel="stylesheet">'
            f'<link rel="stylesheet" href="{depth}site.css?v={CSS_VERSION}">'
            f'<style>:root{{--bg:{c["bg"]};--gold:{c["accent"]};--red:{c["accent2"]};--ink:{ink};--soft:{soft};'
            f'--panel:{panel};--line:{line};--hf:"{t["head"]}",Georgia,serif;--bf:"{t["body"]}",Arial,sans-serif}}</style>'
            + _schema(f) + f'</head><body class="t-{f["theme"]}">')


def _logo(f, depth: str) -> str:
    if f["logo"] and Path(f["logo"]).exists():
        return f'<img class="logo" src="{depth}logo{Path(f["logo"]).suffix.lower()}" alt="{e(f["name"])} logo">'
    return f'<span class="mono">{e(f["name"][:1].upper())}</span>'


def _nav(f, depth: str, on: str) -> str:
    links = "".join(
        f'<a href="{depth}{"" if path == "index.html" else path.split("/")[0] + "/"}"'
        + (' class="navcta"' if name == "Apply" else (' class="on"' if name == on else "")) + f">{name}</a>"
        for path, name in PAGES)
    return (f'<header class="top"><div class="wrap navbar"><a class="brand" href="{depth or "./"}">'
            f'{_logo(f, depth)}<span>{e(f["name"])}</span></a>'
            f'<button class="burger" aria-label="Menu" onclick="document.querySelector(\'.nav\').classList.toggle(\'open\')">&#9776;</button>'
            f'<nav class="nav">{links}</nav></div></header>')


def _footer(f) -> str:
    soc = _socials(f, "socials small")
    nap = " · ".join(x for x in (
        e(f["address"]),
        f'<a href="tel:+1{f["tel"]}">{e(f["phone"])}</a>' if f["phone"] else "",
        f'<a href="mailto:{e(f["email"])}">{e(f["email"])}</a>' if f["email"] else "") if x)
    return (f'<footer><div class="wrap"><b>{e(f["name"])}</b><p class="muted">{nap}</p>'
            f'{soc}<p class="muted small">© {f["year"]} {e(f["name"])} · '
            f'<a href="{f.get("_depth", "")}privacy/">Privacy policy</a></p>'
            f'</div></footer></body></html>')


def _h1(text: str) -> str:
    parts = [e(x.strip()) for x in (text or "").split("\n") if x.strip()]
    return parts[0] + (f'<br><span class="g">{" ".join(parts[1:])}</span>' if len(parts) > 1 else "")


def _apply_href(f, depth: str) -> str:
    return f["apply_url"] or f"{depth}apply/"


def _hero(f, depth: str, eyebrow: str, h1: str, sub: str, cta: str, n: int = 0) -> str:
    style = f["t"]["hero"]
    text = (f'<div class="htext"><span class="ey">{eyebrow}</span><h1>{h1}</h1>'
            f'<p class="sub">{sub}</p>{cta}</div>')
    if style == "full":
        return f'<div class="hero full">{_img(f, n, depth, "hbg")}<div class="wrap">{text}</div></div>'
    if style == "split":
        return f'<div class="hero split"><div class="wrap two">{text}{_img(f, n, depth, "hpic")}</div></div>'
    if style == "mosaic":
        tiles = "".join(_img(f, n + i, depth, "tile") for i in range(3))
        return f'<div class="hero mosaic"><div class="wrap">{text}<div class="tiles">{tiles}</div></div></div>'
    return f'<div class="hero framed"><div class="wrap two">{_img(f, n, depth, "hpic")}{text}</div></div>'


def _path(f) -> str:
    if f["pay"]:
        rungs = "".join(f'<div class="card"><div class="k">{e(r.get("time", ""))}</div>'
                        f'<div class="t">{e(r.get("stage", ""))}</div>'
                        + (f'<div class="pay">{e(r["pay"])}</div>' if r.get("pay") else "") + "</div>"
                        for r in f["pay"])
        note = ('<p class="muted small">All pay is performance-based: figures show what committed '
                'team members earn, not a guaranteed salary.</p>')
    else:
        rungs = "".join(f'<div class="card"><div class="k">Step {i}</div><div class="t">{t}</div>'
                        f'<div class="d">{d}</div></div>' for i, (t, d) in enumerate((
                            ("Start", "Hands-on training from your first day."),
                            ("Lead", "Coach and train the people who come in after you."),
                            ("Manage", "Run the business side: people, numbers and clients.")), 1))
        note = ""
    return (f'<section><div class="wrap"><span class="ey">The path</span>'
            f'<h2>Promoted on performance</h2><div class="grid">{rungs}</div>{note}</div></section>')


_ICON = {  # simple brand marks, drawn inline so nothing loads from elsewhere
    "instagram": '<svg viewBox="0 0 24 24" width="16" height="16"><rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1.3" fill="currentColor"/></svg>',
    "facebook": '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M14 8h3V4h-3c-2.8 0-4 1.7-4 4.2V10H7v4h3v7h4v-7h3l.5-4H14V8.6c0-.4.3-.6.6-.6z"/></svg>',
    "linkedin": '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M4 9h4v11H4zM6 3a2 2 0 110 4 2 2 0 010-4zm5 6h3.8v1.6h.1c.5-1 1.8-1.9 3.6-1.9 3.9 0 4.5 2.5 4.5 5.8V20h-4v-4.8c0-1.2 0-2.7-1.6-2.7s-1.9 1.3-1.9 2.6V20h-4z"/></svg>',
    "tiktok": '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M16 3c.4 2.2 1.8 3.6 4 3.9v3.3c-1.5 0-2.9-.4-4-1.1V15a6 6 0 11-6-6v3.3a2.7 2.7 0 102.7 2.7V3z"/></svg>',
    "x": '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M4 3h4.5l4 5.6L17.3 3H20l-6.2 7.2L21 21h-4.5l-4.4-6.1L6.8 21H4l6.8-7.8z"/></svg>',
    "youtube": '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M22 8.2s-.2-1.5-.9-2.2c-.8-.9-1.8-.9-2.2-1C15.8 4.8 12 4.8 12 4.8s-3.8 0-6.9.2c-.4.1-1.4.1-2.2 1-.7.7-.9 2.2-.9 2.2S2 10 2 11.8v1.6C2 15.2 2.2 17 2.2 17s.2 1.5.9 2.2c.8.9 1.9.8 2.4.9 1.7.2 6.5.2 6.5.2s3.8 0 6.9-.2c.4-.1 1.4-.1 2.2-1 .7-.7.9-2.2.9-2.2s.2-1.8.2-3.6v-1.6c0-1.8-.2-3.5-.2-3.5zM10 15V9l5 3z"/></svg>',
}


def _socials(f, cls: str = "socials") -> str:
    if not f["socials"]:
        return ""
    return f'<div class="{cls}">' + "".join(
        f'<a href="{e(u)}" aria-label="{SOCIAL_NAME.get(k, k.title())}" title="{SOCIAL_NAME.get(k, k.title())}">'
        f'{_ICON.get(k, "")}</a>' for k, u in f["socials"].items()) + "</div>"


def _faq(f, c: Dict) -> str:
    """Applicant questions, answered only from facts we have."""
    where = _where(f) or "our office"
    qa = [("Do I need experience?", "No. We train you from your first day."),
          ("Is there training?", "Yes. You learn the sales system hands-on, with a leader beside you."),
          ("How do I move up?", "Promotions come from performance, not seniority."),
          ("Where is the office?", f"{f['address']}." if f["address"] else f"In {where}."),
          ("How do I apply?", "Tap Apply. It takes about 2 minutes, and we read every application.")]
    if f["sells"]:
        qa.insert(1, ("What will I be doing?", f"Talking with people face to face about {f['sells']}."))
    items = "".join(f"<details class=\"qa\"><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in qa)
    return (f'<section><div class="wrap"><span class="ey">Questions</span><h2>Before you apply</h2>'
            f'<div class="faq">{items}</div></div></section>')


def _where_section(f, depth: str) -> str:
    if not f["address"]:
        return ""
    from urllib.parse import quote
    q = quote(f["address"])
    areas = f'<p class="body">We work across {e(", ".join(f["areas"]))}.</p>' if f["areas"] else ""
    return (f'<section><div class="wrap two"><div><span class="ey">Location</span>'
            f'<h2>Where you\'ll work</h2><p class="body"><b>{e(f["name"])}</b><br>{e(f["address"])}</p>{areas}'
            + (f'<p class="body"><a href="tel:+1{f["tel"]}">{e(f["phone"])}</a></p>' if f["phone"] else "")
            + f'<div class="ctarow left"><a class="cta" href="{e(_apply_href(f, depth))}">Apply now</a>'
              f'<a class="cta ghost" href="https://www.google.com/maps/search/?api=1&query={q}">Directions</a></div></div>'
              f'<iframe class="map" title="Map to {e(f["name"])}" loading="lazy" '
              f'src="https://www.google.com/maps?q={q}&output=embed"></iframe></div></section>')


def _sections(f, c: Dict, depth: str) -> Dict[str, str]:
    areas = f'<p class="body">Serving {e(", ".join(f["areas"]))}.</p>' if f["areas"] else ""
    gal = "".join(_img(f, i, depth, "g") for i in range(1, min(len(f["photos"]), 9) + 1)) if f["photos"] else ""
    return {
        "what": (f'<section><div class="wrap two"><div><span class="ey">The job</span>'
                 f'<h2>{e(c["what_title"])}</h2><p class="body">{e(c["what_body"])}</p>{areas}</div>'
                 f'{_img(f, 1, depth, "pic")}</div></section>'),
        "why": (f'<section><div class="wrap two rev">{_img(f, 2, depth, "pic")}<div><span class="ey">Why join</span>'
                f'<h2>{e(c["why_title"])}</h2><p class="body">{e(c["why_body"])}</p></div></div></section>'),
        "faq": _faq(f, c),
        "where": _where_section(f, depth),
        "follow": (f'<section><div class="wrap"><span class="ey">Follow us</span><h2>See the team in action</h2>'
                   f'{_socials(f, "socials big")}</div></section>') if f["socials"] else "",
        "gallery": (f'<section class="gal"><div class="wrap"><span class="ey">Life on the team</span>'
                    f'<div class="gallery">{gal}</div></div></section>') if gal else "",
        "path": _path(f),
        "band": (f'<div class="band"><div class="wrap"><h3>{e(c["apply_title"])}</h3>'
                 f'<a class="cta" href="{e(_apply_href(f, depth))}">Apply now</a></div></div>'),
    }


# ---- pages ------------------------------------------------------------------
def page_home(f, c) -> str:
    d, where = "", _where(f)
    cta = (f'<div class="ctarow"><a class="cta" href="{e(_apply_href(f, d))}">Apply in 2 minutes</a>'
           f'<a class="cta ghost" href="about/">Our story</a></div>')
    s = _sections(f, c, d)
    return (_head(f, "Home", d, c["meta_description"]) + _nav(f, d, "Home")
            + _hero(f, d, e(f["name"]) + (f" · {e(where)}" if where else ""), _h1(c["hero_h1"]),
                    e(c["hero_sub"]), cta, 0)
            + "".join(s[k] for k in f["t"]["home"]) + _footer(f))


def page_about(f, c) -> str:
    d = "../"
    vals = "".join(f'<div class="card"><div class="t">{e(c[f"value_{i}_title"])}</div>'
                   f'<div class="d">{e(c[f"value_{i}_body"])}</div></div>' for i in (1, 2, 3))
    return (_head(f, "About", d, c["meta_description"]) + _nav(f, d, "About")
            + _hero(f, d, "About us", e(c["about_title"]), e(c["about_story"]), "", 3)
            + f'<section><div class="wrap"><span class="ey">What we\'re about</span><div class="grid">{vals}</div></div></section>'
            + _sections(f, c, d)["gallery"] + _footer(f))


def page_contact(f, c) -> str:
    d = "../"
    soc = _socials(f, "socials small")
    maps = f'<br><a href="{e(f["google_link"])}">Find us on Google</a>' if f["google_link"] else ""
    rows = "".join(f'<div><div class="ey">{k}</div><p>{v}</p></div>' for k, v in (
        ("Address", e(f["address"]) + maps),
        ("Phone", f'<a href="tel:+1{f["tel"]}">{e(f["phone"])}</a>' if f["phone"] else ""),
        ("Email", f'<a href="mailto:{e(f["email"])}">{e(f["email"])}</a>' if f["email"] else ""),
        ("Follow us", soc)) if v)
    return (_head(f, "Contact", d, f"Contact {f['name']}: {f['address']} · {f['phone']}") + _nav(f, d, "Contact")
            + f'<section class="first"><div class="wrap"><span class="ey">Contact</span><h2>Get in touch</h2>'
              f'<div class="info">{rows}</div><div class="ctarow left"><a class="cta" href="{e(_apply_href(f, d))}">'
              f'Apply in 2 minutes</a></div></div></section>' + _where_section(f, d) + _footer(f))


def page_privacy(f, c) -> str:
    """Plain privacy policy: Indeed and text-message consent both expect one
    (Megan 2026-11-12). Facts only from the office's own details."""
    d = "../"
    who = e(f["name"])
    contact = " or ".join(x for x in (
        f'<a href="mailto:{e(f["email"])}">{e(f["email"])}</a>' if f["email"] else "",
        f'<a href="tel:+1{f["tel"]}">{e(f["phone"])}</a>' if f["phone"] else "") if x)
    body = "".join(f"<h3>{t}</h3><p class=\"body\">{p}</p>" for t, p in (
        ("What we collect", f"When you apply or contact {who}, we collect what you give us: your name, "
                            "phone number, email, resume and anything you write to us."),
        ("How we use it", "Only to review your application, contact you about jobs with us, and schedule "
                          "interviews. If you agree to texts, we text you about your application."),
        ("Who we share it with", "We don't sell your information. We share it only with the tools we use to "
                                 "manage applications and messages, and only to do those things."),
        ("Texts and calls", "You can ask us to stop texting or calling you at any time, and we will."),
        ("Your choices", "You can ask us to see, fix or delete your information" +
                         (f" by contacting us at {contact}." if contact else ".")),
        ("Where we are", e(f["address"])),
    ))
    return (_head(f, "Privacy", d, f"Privacy policy for {f['name']}.") + _nav(f, d, "")
            + f'<section class="first"><div class="wrap"><span class="ey">Privacy</span>'
              f'<h2>Privacy policy</h2><p class="muted small">Last updated {dt.date.today():%B} {dt.date.today().day}, '
              f'{dt.date.today().year}</p>{body}</div></section>' + _footer(f))


def page_apply(f, c) -> str:
    d = "../"
    if f["apply_url"]:
        go = f'<a class="cta big" href="{e(f["apply_url"])}">Start your application</a>'
    elif f["email"]:
        go = (f'<a class="cta big" href="mailto:{e(f["email"])}?subject=Application">Email us to apply</a>'
              '<p class="muted small">Send your name, phone number and a line about why you\'re a fit.</p>')
    else:
        go = f'<a class="cta big" href="tel:+1{f["tel"]}">Call us to apply</a>'
    return (_head(f, "Apply", d, c["meta_description"]) + _nav(f, d, "Apply")
            + _hero(f, d, f"Join {e(f['name'])}", e(c["apply_title"]), e(c["apply_sub"]), go, 4)
            + _path(f) + _faq(f, c) + _where_section(f, d) + _footer(f))


CSS = """*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--bf);line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1100px;margin:0 auto;padding:0 20px}a{color:inherit}img{display:block;max-width:100%}
h1,h2,h3{font-family:var(--hf);margin:0;line-height:1.08;text-wrap:balance}h1{font-size:clamp(36px,6vw,66px)}h2{font-size:clamp(26px,3.4vw,38px);margin-top:10px}h3{font-size:clamp(22px,2.6vw,30px)}
.ey{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.body{font-size:17px;color:var(--soft);margin-top:14px;max-width:60ch}.muted{color:var(--soft)}.small{font-size:13px}.g{color:var(--gold)}
header.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.navbar{display:flex;align-items:center;justify-content:space-between;height:64px;gap:14px}.brand{display:flex;align-items:center;gap:10px;font-family:var(--hf);font-size:19px;text-decoration:none}
.mono{width:36px;height:36px;border-radius:50%;background:var(--gold);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:900}.logo{height:40px;width:auto}
.nav{display:flex;gap:24px;align-items:center}.nav a{font-size:14px;font-weight:600;color:var(--soft);text-decoration:none}.nav a.on{color:var(--ink)}
.nav a.navcta{background:var(--gold);color:#fff;padding:9px 18px;border-radius:6px}.burger{display:none;background:none;border:1px solid var(--line);color:var(--ink);font-size:20px;padding:5px 11px;border-radius:6px}
.cta{display:inline-block;background:var(--gold);color:#fff;font-weight:700;padding:14px 28px;border-radius:7px;text-decoration:none}.cta.ghost{background:transparent;color:var(--ink);border:1.5px solid var(--line)}.cta.big{margin-top:24px}
.ctarow{display:flex;gap:12px;flex-wrap:wrap;margin-top:26px}
.sub{font-size:18px;color:var(--soft);margin-top:18px;max-width:58ch}
.ph{background:linear-gradient(135deg,var(--gold),var(--red));opacity:.85}
.hero{position:relative;overflow:hidden}.hero .htext{position:relative;padding:90px 0 80px}
.hero.full{min-height:78vh;display:flex;align-items:flex-end}.hero.full .hbg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.hero.full::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.25),var(--bg) 96%)}.hero.full .wrap{position:relative;z-index:1;width:100%}.hero.full h1{text-transform:uppercase}
.two{display:grid;grid-template-columns:1.05fr .95fr;gap:44px;align-items:center}.two.rev{grid-template-columns:.95fr 1.05fr}
.hero.split .hpic,.hero.framed .hpic{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:18px;min-height:340px}
.hero.framed .hpic{border:10px solid #fff;box-shadow:0 18px 40px rgba(0,0,0,.18);transform:rotate(-1.5deg)}
.hero.mosaic .htext{text-align:center;padding-bottom:30px}.hero.mosaic .sub{margin-left:auto;margin-right:auto}.hero.mosaic .ctarow{justify-content:center}
.tiles{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:10px;padding-bottom:70px}.tile{width:100%;height:300px;object-fit:cover;border-radius:12px}
section{padding:72px 0;border-top:1px solid var(--line)}section.first{border-top:0;padding-top:90px}
.pic{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:14px;min-height:260px}
.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:20px}.gallery .g{width:100%;aspect-ratio:1;object-fit:cover;border-radius:10px}
.t-mosaic .gallery{grid-template-columns:repeat(4,1fr)}.t-mosaic .gallery .g:first-child{grid-column:span 2;grid-row:span 2;aspect-ratio:auto;height:100%}
.t-warm .gallery .g{border-radius:50% 50% 12px 12px}.t-clean .pic,.t-clean .gallery .g{border-radius:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:26px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}.card .k{font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:var(--gold)}
.card .t{font-family:var(--hf);font-size:21px;margin-top:6px}.card .pay{color:var(--gold);font-weight:800;margin-top:6px}.card .d{color:var(--soft);font-size:15px;margin-top:6px}
.band{background:var(--gold);color:#fff}.band .wrap{padding:44px 20px;display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}.band .cta{background:#fff;color:#111}
.info{display:flex;flex-wrap:wrap;gap:24px 56px;margin-top:26px}.info p{margin:6px 0 0;font-size:17px}
footer{border-top:1px solid var(--line);padding:34px 0}footer p{margin:6px 0 0}
.socials{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}.socials a{display:inline-flex;align-items:center;gap:8px;padding:9px 14px;border:1.5px solid var(--line);border-radius:999px;text-decoration:none;font-weight:600;font-size:14px;color:var(--ink);background:var(--panel)}
.socials a:hover{border-color:var(--gold);color:var(--gold)}.socials svg{width:20px;height:20px;flex:none}
.socials.big a{padding:14px 22px;font-size:16px}.socials.big svg{width:28px;height:28px}
.socials.small{margin-top:12px;gap:8px}.socials.small a{width:34px;height:34px;padding:0;justify-content:center;border-radius:50%}.socials.small svg{width:16px;height:16px}
.hero.mosaic .socials,.hero.full .socials{justify-content:flex-start}.hero.mosaic .socials{justify-content:center}
.map{width:100%;height:340px;border:0;border-radius:14px}
.faq{margin-top:20px;display:grid;gap:10px;max-width:760px}.qa{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px}
.qa summary{cursor:pointer;font-weight:700;font-size:17px}.qa p{margin:8px 0 0;color:var(--soft)}
.ctarow.left{justify-content:flex-start}
@media(max-width:800px){.two,.two.rev{grid-template-columns:1fr}.tiles{grid-template-columns:1fr 1fr}.tiles .tile:first-child{grid-column:span 2}.tile{height:200px}
.gallery,.t-mosaic .gallery{grid-template-columns:1fr 1fr}.burger{display:block}.nav{position:absolute;top:64px;left:0;right:0;flex-direction:column;align-items:stretch;gap:0;background:var(--bg);border-bottom:1px solid var(--line);display:none;padding:8px 0}.nav.open{display:flex}.nav a{padding:12px 20px}.nav a.navcta{margin:8px 20px;text-align:center}
.hero .htext{padding:60px 0 50px}}
"""


CSS_VERSION = __import__("hashlib").sha1(CSS.encode()).hexdigest()[:8]   # new CSS -> browsers re-download it


def build(p, out: Optional[Path] = None, extra: Optional[Dict] = None, copy: Optional[Dict] = None) -> Path:
    from automations.online_presence import site_copy
    x = extras(p) if extra is None else extra
    f = facts(p, x)
    c = dict(copy or site_copy.copy_for(p, f, x.get("answers") or {}))
    c.update({k: v for k, v in (x.get("copy_edits") or {}).items() if k in c and str(v).strip()})
    out = out or OUT / p.key
    if out.exists():
        shutil.rmtree(out)
    for (path, _), fn in list(zip(PAGES, (page_home, page_about, page_contact, page_apply))) + \
            [(("privacy/index.html", "Privacy"), page_privacy)]:
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        f["_depth"] = "" if path == "index.html" else "../"
        target.write_text(fn(f, c))
    (out / "site.css").write_text(CSS)
    if f["photos"]:
        (out / "img").mkdir(exist_ok=True)
        for i, ph in enumerate(f["photos"], 1):
            shutil.copy(ph, out / "img" / f"{i}{Path(ph).suffix.lower()}")
    if f["logo"] and Path(f["logo"]).exists():
        shutil.copy(f["logo"], out / f"logo{Path(f['logo']).suffix.lower()}")
    (out / "favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="32" '
        f'fill="{f["colors"]["accent"]}"/><text x="32" y="43" font-size="34" font-family="Arial" '
        f'font-weight="900" text-anchor="middle" fill="#fff">{e(f["name"][:1].upper())}</text></svg>')
    if f["noindex"]:
        (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    elif f["url"]:
        urls = "".join(f"<url><loc>{f['url']}/{'' if pth == 'index.html' else pth.split('/')[0] + '/'}</loc></url>"
                       for pth, _ in PAGES + (("privacy/index.html", "Privacy"),))
        (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset '
                                         f'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
        (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {f['url']}/sitemap.xml\n")
    if f["domain"]:
        (out / "CNAME").write_text(f["domain"] + "\n")
    return out


def readiness(p) -> List[str]:
    """What's still missing before this office's site can launch."""
    x, miss = extras(p), []
    n = len([ph for ph in (x.get("photos") or []) if Path(ph).exists()])
    if n < MIN_PHOTOS:
        miss.append(f"photos: {n} so far, ask for {ASK_PHOTOS}")
    for need, ok in (("address", p.address), ("phone", p.phone), ("domain", p.website),
                     ("owner answers (story)", x.get("answers"))):
        if not ok:
            miss.append(need)
    return miss


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="online_presence.site_builder")
    ap.add_argument("office")
    ap.add_argument("--theme", choices=sorted(THEMES))
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)
    from automations.online_presence import offices
    rows = {"alphalete": offices.alphalete(), **offices.load()}
    p = rows.get(a.office.lower())
    if not p:
        print(f"✗ no online-presence office {a.office!r}")
        return 1
    x = extras(p)
    if a.theme:
        x["theme"] = a.theme
    out = build(p, extra=x)
    print(f"✓ built {out} ({THEMES[pick_theme(p, x)]['label']} look)")
    for m in readiness(p):
        print(f"  · still needed: {m}")
    if a.open:
        import webbrowser
        webbrowser.open((out / "index.html").as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
