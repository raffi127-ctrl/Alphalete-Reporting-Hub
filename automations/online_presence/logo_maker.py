"""Logo options for a new office (Megan 2026-11-12: "we should start every
launch by asking their company name and making them a logo - then we build
from the logo they choose").

    python -m automations.online_presence.logo_maker "Palace Acquisitions"     # -> output/logos/<slug>/

Six clearly different options from the company name: each its own font,
shape and colors. For each one Lucy makes:
  * logo.png   -- full logo (mark + name), transparent, for the website + docs
  * icon.png   -- square mark only, for social profile pictures + the site header
and one numbered sheet (options.png) to show the owner. The pick then sets the
website's colors + look (site_extras_for), so the site is built FROM the logo.

Rendered by the same headless browser the weekly card uses; fonts from
Google Fonts. No AI images: clean type + simple shapes print well, scale to a
favicon, and never come out garbled.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "logos"

# Words that make a poor monogram ("Palace Acquisitions LLC" -> "PA").
_SKIP = {"llc", "inc", "co", "the", "and", "&", "of", "group", "marketing", "sales", "solutions",
         "consulting", "enterprises", "company", "corp", "agency", "team"}

# (font, weight, mark shape, ink, accent, light-or-dark, site look)
STYLES = [
    {"font": "Oswald", "w": 700, "shape": "circle", "ink": "#111111", "accent": "#C8A24B", "bg": "#0C0C0D",
     "dark": True, "theme": "bold", "case": "upper", "label": "Black + gold, strong"},
    {"font": "Playfair Display", "w": 800, "shape": "none", "ink": "#1F2A44", "accent": "#1F4D7A", "bg": "#FBFAF7",
     "dark": False, "theme": "clean", "case": "title", "label": "Navy, classic"},
    {"font": "Archivo Black", "w": 400, "shape": "square", "ink": "#111418", "accent": "#36C2B4", "bg": "#111418",
     "dark": True, "theme": "mosaic", "case": "upper", "label": "Teal, modern"},
    {"font": "DM Serif Display", "w": 400, "shape": "arch", "ink": "#2E2A26", "accent": "#B4532A", "bg": "#F6EFE6",
     "dark": False, "theme": "warm", "case": "title", "label": "Rust, warm"},
    {"font": "Montserrat", "w": 800, "shape": "hex", "ink": "#14151A", "accent": "#C0392B", "bg": "#0F1012",
     "dark": True, "theme": "bold", "case": "upper", "label": "Red + black, bold"},
    {"font": "Poppins", "w": 700, "shape": "bar", "ink": "#16302B", "accent": "#2F8F5B", "bg": "#F5F8F6",
     "dark": False, "theme": "clean", "case": "title", "label": "Green, fresh"},
]

# Alphalete-org offices: shields are the house style (Megan 2026-11-12: "our
# logos usually include shields if you're in the alphalete org"). Four shield
# options + two others, so there's still a real choice.
SHIELD_STYLES = [
    {"font": "Oswald", "w": 700, "shape": "shield", "ink": "#111111", "accent": "#C8A24B", "bg": "#0C0C0D",
     "dark": True, "theme": "bold", "case": "upper", "label": "Gold shield, strong"},
    {"font": "Cinzel", "w": 700, "shape": "shield-ring", "ink": "#1F2A44", "accent": "#1F4D7A", "bg": "#FBFAF7",
     "dark": False, "theme": "clean", "case": "upper", "label": "Navy crest, classic"},
    {"font": "Montserrat", "w": 800, "shape": "shield-split", "ink": "#14151A", "accent": "#C0392B", "bg": "#0F1012",
     "dark": True, "theme": "bold", "case": "upper", "label": "Red split shield, bold"},
    {"font": "Bebas Neue", "w": 400, "shape": "shield-chevron", "ink": "#16302B", "accent": "#2F8F5B", "bg": "#F5F8F6",
     "dark": False, "theme": "mosaic", "case": "upper", "label": "Green chevron shield"},
]

e = html.escape

# Typed ideas ("red fire and a wolf") -> 3 drawn emblem marks (Megan
# 2026-11-12: "we need a box where they can type in their ideas"). Drawn as
# flat SVG by the AI, so they stay sharp at every size and every format.
AI_MODEL = "claude-opus-5-5"
_AI_SYSTEM = ("You are a logo designer. Draw bold, flat emblem marks as SVG for a small sales company. "
              "Rules: viewBox='0 0 200 200'; no text or letters; no gradients, filters, images, scripts or links; "
              "at most 3 solid colors; thick simple shapes that still read at 32px; centered. "
              "Each mark must clearly show what the owner asked for. {shield}"
              "Return 3 clearly different marks, each with its main color as accent (#RRGGBB) and a dark ink "
              "color (#RRGGBB) for the company name.")
_AI_FONTS = [("Oswald", 700, "upper"), ("Montserrat", 800, "upper"), ("Cinzel", 700, "upper")]


def _safe_svg(svg: str) -> str:
    bad = ("<script", "foreignobject", "href=", "<image", "onload", "onclick", "@import", "url(")
    if not svg.strip().lower().startswith("<svg") or any(b in svg.lower() for b in bad):
        raise ValueError("unsafe or broken SVG")
    return svg


def ai_styles(name: str, ideas: str, shields: bool = True) -> List[Dict]:
    """3 drawn-emblem styles from the owner's own words."""
    import json
    import anthropic
    from automations.brand_audit import credentials
    schema = {"type": "object", "properties": {"marks": {"type": "array", "items": {"type": "object", "properties": {
        "label": {"type": "string"}, "accent": {"type": "string"}, "ink": {"type": "string"},
        "svg": {"type": "string"}}, "required": ["label", "accent", "ink", "svg"], "additionalProperties": False}}},
        "required": ["marks"], "additionalProperties": False}
    sysmsg = _AI_SYSTEM.format(shield="The company's org usually puts its mark on a shield; use a shield in at "
                                      "least two of the three. " if shields else "")
    resp = anthropic.Anthropic(api_key=credentials.anthropic_api_key()).messages.create(
        model=AI_MODEL, max_tokens=8000, system=sysmsg,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": f"Company: {name}. Owner's idea: {ideas}"}])
    marks = json.loads(next(b.text for b in resp.content if getattr(b, "type", "") == "text"))["marks"]
    out = []
    for m, (font, w, case) in zip(marks[:3], _AI_FONTS):
        try:
            svg = _safe_svg(m["svg"])
        except ValueError:
            continue
        hexok = lambda c, d: c if re.match(r"^#[0-9a-fA-F]{6}$", c or "") else d
        out.append({"font": font, "w": w, "shape": "custom", "svg": svg, "ink": hexok(m["ink"], "#111111"),
                    "accent": hexok(m["accent"], "#C0392B"), "bg": "#0F1012", "dark": True, "theme": "bold",
                    "case": case, "label": m["label"][:40]})
    return out


def initials(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name)]
    keep = [w for w in words if w.lower() not in _SKIP] or words
    return "".join(w[0] for w in keep[:2]).upper() or "?"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "office"


def _mark(st: Dict, mono: str, size: int) -> str:
    """The shape + initials as inline SVG (size = px)."""
    a, s = st["accent"], size
    if st["shape"] == "custom":           # an AI-drawn emblem, sized to fit
        return re.sub(r"<svg\b", f'<svg width="{s}" height="{s}"', st["svg"], count=1)
    fs = s * (0.42 if len(mono) > 1 else 0.55)
    text = (f'<text x="50%" y="53%" dominant-baseline="middle" text-anchor="middle" '
            f'font-family="{st["font"]}" font-weight="{st["w"]}" font-size="{fs}" fill="#fff">{e(mono)}</text>')
    sh = lambda: (f"M{s*.1:.1f} {s*.04:.1f} H{s*.9:.1f} V{s*.46:.1f} C{s*.9:.1f} {s*.74:.1f} {s*.7:.1f} {s*.88:.1f} "
                  f"{s*.5:.1f} {s*.98:.1f} C{s*.3:.1f} {s*.88:.1f} {s*.1:.1f} {s*.74:.1f} {s*.1:.1f} {s*.46:.1f} Z")
    if st["shape"].startswith("shield"):
        text = text.replace('y="53%"', 'y="47%"')
    shape = {
        "shield": f'<path d="{sh()}" fill="{a}"/>',
        "shield-ring": (f'<path d="{sh()}" fill="{a}"/><path d="{sh()}" fill="none" stroke="#fff" stroke-width="{s*.035:.1f}" '
                        f'transform="translate({s*.07:.1f} {s*.07:.1f}) scale(.86)"/>'),
        "shield-split": (f'<clipPath id="c"><path d="{sh()}"/></clipPath><g clip-path="url(#c)">'
                         f'<rect width="{s/2}" height="{s}" fill="{a}"/><rect x="{s/2}" width="{s/2}" height="{s}" fill="#14151A"/></g>'),
        "shield-chevron": (f'<path d="{sh()}" fill="{a}"/><path d="M{s*.1:.1f} {s*.62:.1f} L{s*.5:.1f} {s*.8:.1f} L{s*.9:.1f} {s*.62:.1f}" '
                           f'fill="none" stroke="#fff" stroke-width="{s*.05:.1f}" stroke-linejoin="round"/>'),
        "circle": f'<circle cx="{s/2}" cy="{s/2}" r="{s/2}" fill="{a}"/>',
        "square": f'<rect width="{s}" height="{s}" rx="{s*0.18}" fill="{a}"/>',
        "hex": '<polygon points="{}" fill="{}"/>'.format(
            " ".join(f"{s/2 + s/2*__import__('math').cos(__import__('math').radians(60*i-90)):.1f},"
                     f"{s/2 + s/2*__import__('math').sin(__import__('math').radians(60*i-90)):.1f}" for i in range(6)), a),
        "arch": f'<path d="M0 {s} V{s*0.45} A{s/2} {s*0.45} 0 0 1 {s} {s*0.45} V{s} Z" fill="{a}"/>',
        "bar": f'<rect width="{s}" height="{s}" rx="{s/2}" fill="{a}"/>',
        "none": f'<circle cx="{s/2}" cy="{s/2}" r="{s/2}" fill="{a}"/>',
    }[st["shape"]]
    return f'<svg width="{s}" height="{s}" viewBox="0 0 {s} {s}" xmlns="http://www.w3.org/2000/svg">{shape}{text}</svg>'


def _word(st: Dict, name: str) -> str:
    return name.upper() if st["case"] == "upper" else name


def _logo_html(st: Dict, name: str, mono: str) -> str:
    word = e(_word(st, name))
    if st["shape"] == "none":            # pure wordmark with an accent rule
        inner = (f'<div style="text-align:center"><div class="wm" style="font-size:64px">{word}</div>'
                 f'<div style="height:5px;width:120px;background:{st["accent"]};margin:10px auto 0"></div></div>')
    elif st["shape"] == "bar":
        inner = (f'<div style="display:flex;align-items:center;gap:18px">{_mark(st, mono, 96)}'
                 f'<div style="border-left:5px solid {st["accent"]};padding-left:16px" class="wm">{word}</div></div>')
    else:
        inner = f'<div style="display:flex;align-items:center;gap:22px">{_mark(st, mono, 110)}<div class="wm">{word}</div></div>'
    return inner


def _page(body: str, fonts: List[str], bg: str = "transparent") -> str:
    wt = {st["font"]: st["w"] for st in STYLES + SHIELD_STYLES}
    fam = "&".join(f"family={f.replace(' ', '+')}" + (f":wght@{wt[f]}" if wt.get(f, 400) != 400 else "")
                   for f in dict.fromkeys(fonts))
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<link href="https://fonts.googleapis.com/css2?{fam}&display=block" rel="stylesheet">'
            f'<style>body{{margin:0;background:{bg}}}.wm{{font-size:58px;line-height:1.05;letter-spacing:.01em}}'
            f'.box{{display:inline-block;padding:28px 34px}}</style></head><body>{body}</body></html>')


_BROWSER = {}


class _one_browser:
    """Reuse ONE headless browser for a whole set of shots (31 per office --
    one launch each took about a minute)."""
    def __enter__(self):
        from patchright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        _BROWSER["b"] = self.pw.chromium.launch(headless=True)
        return self

    def __exit__(self, *exc):
        try:
            _BROWSER.pop("b").close()
        finally:
            self.pw.stop()


def _shot(page_html: str, out: Path, selector: str, transparent: bool = True, pdf: Path = None) -> None:
    tmp = out.with_suffix(".html")
    tmp.write_text(page_html)
    own = "b" not in _BROWSER
    ctx = _one_browser() if own else None
    if ctx:
        ctx.__enter__()
    try:
        pg = _BROWSER["b"].new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
        try:
            pg.goto(tmp.resolve().as_uri(), wait_until="networkidle", timeout=30000)
            pg.evaluate("document.fonts.ready")
            if out.suffix == ".jpg":
                pg.locator(selector).screenshot(path=str(out), type="jpeg", quality=95)
            else:
                pg.locator(selector).screenshot(path=str(out), omit_background=transparent)
            if pdf:                       # vector, fonts embedded: prints sharp at any size
                box = pg.locator(selector).bounding_box()
                pg.pdf(path=str(pdf), width=f"{int(box['width']) + 2}px", height=f"{int(box['height']) + 2}px",
                       print_background=False, page_ranges="1")
        finally:
            pg.close()
    finally:
        if ctx:
            ctx.__exit__(None, None, None)
    tmp.unlink(missing_ok=True)


FORMATS = {
    "logo.png": "no background, dark text (for light backgrounds)",
    "logo-white.png": "no background, white text (for dark backgrounds)",
    "logo.jpg": "on white (email, documents)",
    "logo.pdf": "print-ready, sharp at any size (signs, shirts, cards)",
    "icon.png": "square mark, no background (profile pictures)",
    "icon.jpg": "square mark on white",
}


def styles_for(shields: bool, drawn: List[Dict] = None) -> List[Dict]:
    base = (SHIELD_STYLES + [STYLES[1], STYLES[3]]) if shields else STYLES
    return (drawn + base)[:6] if drawn else base


def make_options(name: str, out: Path = None, shields: bool = True, ideas: str = "") -> Dict:
    """Render all 6 options for `name` (shields first for Alphalete-org
    offices). Returns {"sheet", "options": [{n, logo, icon, ...}]}."""
    out = out or OUT / slug(name)
    drawn = ai_styles(name, ideas, shields) if ideas.strip() else []
    styles = styles_for(shields, drawn)
    import json as _json
    out.mkdir(parents=True, exist_ok=True)
    (out / "styles.json").write_text(_json.dumps(styles, indent=1))   # the pick reads THIS set
    out.mkdir(parents=True, exist_ok=True)
    mono = initials(name)
    opts = []
    with _one_browser():
        return _make_all(name, out, mono, opts, styles)


def _make_all(name, out, mono, opts, styles) -> Dict:
    for n, st in enumerate(styles, 1):
        d = out / f"option-{n}"
        d.mkdir(exist_ok=True)
        font = f"font-family:'{st['font']}';font-weight:{st['w']}"
        dark = _page(f'<div class="box" id="l" style="color:{st["ink"]};{font}">{_logo_html(st, name, mono)}</div>', [st["font"]])
        white = _page(f'<div class="box" id="l" style="color:#fff;{font}">{_logo_html(st, name, mono)}</div>', [st["font"]])
        on_white = _page(f'<div class="box" id="l" style="color:{st["ink"]};{font};background:#fff">'
                         f'{_logo_html(st, name, mono)}</div>', [st["font"]], bg="#fff")
        _shot(dark, d / "logo.png", "#l", pdf=d / "logo.pdf")
        _shot(white, d / "logo-white.png", "#l")
        _shot(on_white, d / "logo.jpg", "#l", transparent=False)
        icon = f'<div id="i" style="display:inline-block">{_mark(st, mono, 400)}</div>'
        _shot(_page(icon, [st["font"]]), d / "icon.png", "#i")
        _shot(_page(f'<div id="i" style="display:inline-block;background:#fff;padding:40px">{_mark(st, mono, 400)}</div>',
                    [st["font"]], bg="#fff"), d / "icon.jpg", "#i", transparent=False)
        opts.append({"n": n, "logo": str(d / "logo.png"), "icon": str(d / "icon.png"), **st})
    cards = "".join(
        f'<div class="c" style="background:#FFFFFF">'
        f'<div class="n">{o["n"]}</div><img src="{Path(o["logo"]).resolve().as_uri()}">'
        f'<div class="lab" style="color:#555">{e(o["label"])}</div></div>' for o in opts)
    sheet = (f'<div id="s" style="width:1200px;padding:30px;background:#EDEBE6;font-family:Arial">'
             f'<div style="font-size:30px;font-weight:800;margin-bottom:18px">{e(name)}: pick a logo (reply with its number)</div>'
             f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">{cards}</div></div>'
             '<style>.c{position:relative;border-radius:16px;height:220px;display:flex;flex-direction:column;'
             'align-items:center;justify-content:center}.c img{max-width:86%;max-height:140px}'
             '.n{position:absolute;top:12px;left:14px;width:38px;height:38px;border-radius:50%;background:#111;'
             'color:#fff;font:800 20px Arial;display:flex;align-items:center;justify-content:center}'
             '.lab{font-size:15px;margin-top:10px}</style>')
    _shot(_page(sheet, [o["font"] for o in opts], bg="#EDEBE6"), out / "options.png", "#s", transparent=False)
    return {"sheet": str(out / "options.png"), "options": opts, "folder": str(out)}


def site_extras_for(option: Dict) -> Dict:
    """What the chosen logo sets on the website: its colors, its look, the logo."""
    return {"logo": option["icon"], "logo_full": option["logo"], "theme": option["theme"],
            "colors": {"accent": option["accent"], "bg": option["bg"]}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="online_presence.logo_maker")
    ap.add_argument("name")
    ap.add_argument("--no-shields", action="store_true", help="office outside the Alphalete org")
    ap.add_argument("--ideas", default="", help="what the owner wants, e.g. 'red fire and a wolf'")
    a = ap.parse_args(argv)
    r = make_options(a.name, shields=not a.no_shields, ideas=a.ideas)
    print(f"✓ {len(r['options'])} logo options for {a.name}: {r['sheet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
