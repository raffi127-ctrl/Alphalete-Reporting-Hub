"""Pull an office's logo (and a brand accent color) straight off their website,
so the Pay Structure editor is fully branded the moment they log in — no upload.

Given a website URL, `fetch_branding()` finds the best logo-ish asset on the
page (apple-touch-icon → og:image → a header <img> whose name says "logo" →
high-res favicon → Clearbit as a last resort), downsizes it to a small base64
data URI, and derives an accent color from its pixels.

This is meant to be run ONCE per office (a script / CLI below) to populate each
office's stored structure, NOT on every page load — so the live editor stays
fast and does no outbound fetch. Re-run it whenever a logo changes.

Uses only urllib + Pillow (regex HTML scan, no BeautifulSoup dep) so it runs the
same on macOS and Windows / Python 3.9.
"""
from __future__ import annotations

import base64
import io
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122 Safari/537.36")


def _get(url: str, timeout: int = 12) -> "Optional[bytes]":
    try:
        req = Request(url, headers={"User-Agent": _UA})
        with urlopen(req, timeout=timeout) as r:
            if r.status and r.status >= 400:
                return None
            return r.read()
    except Exception:
        return None


def _norm(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url):
        url = "https://" + url
    return url


def _candidates(html: str, base: str) -> "List[str]":
    """Ordered logo-asset URLs found in the page — best first."""
    out: List[str] = []

    def add(u):
        if u:
            full = urljoin(base, u.strip())
            if full not in out:
                out.append(full)

    # apple-touch-icon (usually a clean square logo, 152-180px)
    for m in re.finditer(r'<link[^>]+rel=["\'][^"\']*apple-touch-icon[^"\']*'
                         r'["\'][^>]*>', html, re.I):
        hm = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I)
        if hm:
            add(hm.group(1))
    # og:image (often a branded share card)
    for m in re.finditer(r'<meta[^>]+property=["\']og:image["\'][^>]*>', html, re.I):
        hm = re.search(r'content=["\']([^"\']+)["\']', m.group(0), re.I)
        if hm:
            add(hm.group(1))
    # an <img> whose src/class/alt says "logo"
    for m in re.finditer(r'<img[^>]+>', html, re.I):
        tag = m.group(0)
        if re.search(r'logo', tag, re.I):
            hm = re.search(r'src=["\']([^"\']+)["\']', tag, re.I)
            if hm:
                add(hm.group(1))
    # any explicit icon link
    for m in re.finditer(r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]*>',
                         html, re.I):
        hm = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I)
        if hm:
            add(hm.group(1))
    # bare favicon + Clearbit as last resorts
    p = urlparse(base)
    add(f"{p.scheme}://{p.netloc}/favicon.ico")
    if p.netloc:
        out.append(f"https://logo.clearbit.com/{p.netloc}")
    return out


def _to_data_uri(raw: bytes, box: int = 240) -> str:
    """Downsize image bytes to a base64 data URI under Sheets' cell limit."""
    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if min(img.size) < 32:                       # too tiny to be a real logo
        return ""
    img.thumbnail((box, box))
    for fmt, mime, kw in (("PNG", "image/png", {}),
                          ("JPEG", "image/jpeg", {"quality": 78})):
        buf = io.BytesIO()
        img.save(buf, fmt, **kw)
        b64 = base64.b64encode(buf.getvalue()).decode()
        if len(b64) < 46000:
            return f"data:{mime};base64,{b64}"
    return ""


def _accent(raw: bytes) -> str:
    """Pick a brand-y accent color from the logo pixels (skips white/black/grey).
    Same idea as the Document Builder's color extractor."""
    try:
        import colorsys
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img).convert("RGB")
        img.thumbnail((160, 160))
        q = img.quantize(colors=16)
        pal = q.getpalette()
        best, best_cnt = None, 0
        for cnt, idx in (q.getcolors() or []):
            r, g, b = pal[idx * 3:idx * 3 + 3]
            _, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if s > 0.20 and 0.12 < l < 0.85 and cnt > best_cnt:
                best, best_cnt = (r, g, b), cnt
        if best:
            return "#%02X%02X%02X" % best
    except Exception:
        pass
    return ""


def fetch_branding(website: str) -> "Tuple[str, str]":
    """Return (logo_data_uri, accent_hex) for a website. Either may be '' if the
    site has nothing usable."""
    base = _norm(website)
    if not base:
        return "", ""
    html = _get(base)
    html = html.decode("utf-8", "ignore") if html else ""
    for cand in _candidates(html, base):
        raw = _get(cand)
        if not raw:
            continue
        uri = _to_data_uri(raw)
        if uri:
            return uri, _accent(raw)
    return "", ""


def apply_to_office(office_key: str, website: str, set_accent: bool = True) -> bool:
    """Fetch branding and store it on the office's structure (creating a blank
    one if needed). Returns True if a logo was stored."""
    from . import store
    logo, accent = fetch_branding(website)
    if not logo:
        return False
    grid = store.load(office_key) or store.blank_grid(office_key)
    grid.logo = logo
    if set_accent and accent:
        grid.accent = accent            # tolerated by from_dict via getattr
    store.save(grid)
    return True


# Pillow imported lazily-at-top so the module still imports if Pillow is absent
try:
    from PIL import Image
except Exception:                                # pragma: no cover
    Image = None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Pull an office logo off its website")
    ap.add_argument("--office", required=True)
    ap.add_argument("--website", required=True)
    a = ap.parse_args()
    ok = apply_to_office(a.office, a.website)
    print(("stored logo for " if ok else "no usable logo found for ") + a.office)
