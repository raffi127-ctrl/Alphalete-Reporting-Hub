"""Social media branding from the office's chosen logo (BIS's "Social Media
Account Set Up and Branding", done by Lucy). Every image sized for its site:

    profile.png          1080×1080  profile picture (every site; crops to a circle cleanly)
    facebook-cover.png   1640×624   Facebook cover
    linkedin-cover.png   1128×191   LinkedIn company cover
    x-header.png         1500×500   X (Twitter) header
    youtube-banner.png   2560×1440  YouTube banner (safe area centered)

Covers use the brand color, the white logo and (when they sent launch photos)
one of their own photos behind a dark wash, so every office's look is its own.

    python -m automations.online_presence.brand_kit <office>
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path
from typing import Dict, List, Optional

SIZES = {"profile.png": (1080, 1080), "facebook-cover.png": (1640, 624),
         "linkedin-cover.png": (1128, 191), "x-header.png": (1500, 500),
         "youtube-banner.png": (2560, 1440)}
USE = {"profile.png": "Profile picture on every site",
       "facebook-cover.png": "Facebook cover photo",
       "linkedin-cover.png": "LinkedIn company cover",
       "x-header.png": "X (Twitter) header",
       "youtube-banner.png": "YouTube banner"}


def _data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _cover(w: int, h: int, accent: str, logo_white: Path, photo: Optional[Path], tagline: str) -> str:
    bg = (f"background:linear-gradient(90deg,rgba(0,0,0,.78),rgba(0,0,0,.35)),url('{_data_uri(photo)}') center/cover"
          if photo else f"background:radial-gradient(circle at 20% 30%,{accent},#0d0d0f 75%)")
    logo_h = int(h * (0.34 if h > 400 else 0.5))
    tag = (f'<div style="color:#fff;font:700 {max(14, int(h*0.06))}px Arial;margin-top:{int(h*0.04)}px;'
           f'letter-spacing:.04em;opacity:.92">{tagline}</div>') if tagline and h > 300 else ""
    bar = f'<div style="position:absolute;left:0;right:0;bottom:0;height:{max(4, int(h*0.025))}px;background:{accent}"></div>'
    return (f'<div id="c" style="position:relative;width:{w}px;height:{h}px;{bg};display:flex;'
            f'align-items:center;justify-content:center;flex-direction:column">'
            f'<img src="{_data_uri(logo_white)}" style="max-height:{logo_h}px;max-width:{int(w*0.6)}px">{tag}{bar}</div>')


def _profile(accent: str, icon: Path) -> str:
    return (f'<div id="c" style="width:1080px;height:1080px;background:{accent};display:flex;align-items:center;'
            f'justify-content:center"><div style="width:760px;height:760px;border-radius:50%;background:#fff;'
            f'display:flex;align-items:center;justify-content:center">'
            f'<img src="{_data_uri(icon)}" style="max-width:560px;max-height:560px"></div></div>')


def make(brand: Path, accent: str, photos: List[str] = (), tagline: str = "Now hiring · No experience needed",
         out: Optional[Path] = None) -> Dict[str, str]:
    """Render the kit from a brand/ folder (logo.png, logo-white.png, icon.png)."""
    from automations.online_presence import logo_maker as LM
    out = out or brand / "social"
    out.mkdir(parents=True, exist_ok=True)
    photo = Path(photos[0]) if photos and Path(photos[0]).exists() else None
    made = {}
    with LM._one_browser():
        for name, (w, h) in SIZES.items():
            body = (_profile(accent, brand / "icon.png") if name == "profile.png"
                    else _cover(w, h, accent, brand / "logo-white.png", photo, tagline))
            html = f'<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">{body}</body></html>'
            tmp = out / f"_{name}.png"
            # 1x pixels are exactly the size each site asks for
            pg_html = out / f"_{name}.html"
            pg_html.write_text(html)
            b = LM._BROWSER["b"]
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            try:
                pg.goto(pg_html.resolve().as_uri(), wait_until="load")
                pg.locator("#c").screenshot(path=str(out / name))
            finally:
                pg.close()
                pg_html.unlink(missing_ok=True)
                tmp.unlink(missing_ok=True)
            made[name] = str(out / name)
    return made


def for_office(p) -> Dict[str, str]:
    from automations.online_presence import site_builder as SB
    x = SB.extras(p)
    brand = p.path("brand")
    if not (brand / "logo-white.png").exists():
        raise SystemExit("✗ no logo yet: pick or upload one first")
    accent = (x.get("colors") or {}).get("accent") or "#C8A24B"
    return make(brand, accent, x.get("photos") or [])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="online_presence.brand_kit")
    ap.add_argument("office")
    a = ap.parse_args(argv)
    from automations.online_presence import launch as L
    made = for_office(L._office(a.office))
    for k, v in made.items():
        print(f"✓ {USE[k]}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
