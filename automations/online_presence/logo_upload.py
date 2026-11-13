"""An office's OWN logo: is it good enough, and if so, every format from it
(Megan 2026-11-12: "they also need to be able to upload their own logo if
they have one and we should judge if it's good enough quality to make all the
files for them or if it needs to be different").

    python -m automations.online_presence.logo_upload path/to/logo.png        # verdict only
    python -m automations.online_presence.logo_upload path/to/logo.png --out output/brand/x

The verdict, in plain words:
  GOOD    -> sharp and big enough: every format, print included
  WEB     -> fine on the website + socials, too small to print big (asks for a bigger file)
  REDO    -> too small, blurry, a screenshot/photo, or mostly empty: use our options instead
Vector files (SVG / PDF) are always GOOD.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Dict, List

PRINT_PX, WEB_PX = 1500, 600        # long side needed to print well / to look sharp on screens


def _load(data: bytes):
    from PIL import Image, ImageOps
    from automations.brand_audit import photo_edit  # noqa: F401  (registers iPhone HEIC)
    return ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")


def _sharpness(im) -> float:
    """Edge strength (variance of a Laplacian): low = blurry."""
    import numpy as np
    g = np.asarray(im.convert("L"), dtype=float)
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
    return float(lap.var())


def _bg_color(im):
    """The corner color when all four corners match (a solid background), else None."""
    px = im.load()
    w, h = im.size
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    if all(c[3] < 10 for c in corners):
        return "transparent"
    ref = corners[0]
    if all(sum(abs(a - b) for a, b in zip(c[:3], ref[:3])) < 30 and c[3] > 200 for c in corners):
        return ref[:3]
    return None


def _colors(im) -> int:
    small = im.copy()
    small.thumbnail((200, 200))
    return len({c for _, c in (small.getcolors(40000) or []) if c[3] > 200})


def check(data: bytes, filename: str) -> Dict:
    """{"verdict": GOOD|WEB|REDO, "why": [...plain words], "background": ...}"""
    ext = Path(filename).suffix.lower()
    if ext in (".svg", ".pdf", ".ai", ".eps"):
        return {"verdict": "GOOD", "why": ["Vector file: sharp at every size, perfect for print."],
                "background": "transparent", "vector": True}
    try:
        im = _load(data)
    except Exception:
        return {"verdict": "REDO", "why": ["We couldn't open that file. Send a PNG, JPG or SVG."]}
    w, h = im.size
    long_side, why = max(w, h), []
    bg = _bg_color(im)
    sharp = _sharpness(im)
    ncol = _colors(im)
    if long_side < 300:
        why.append(f"It's tiny ({w}×{h}). It would look blurry anywhere bigger than a thumbnail.")
    if sharp < 60:
        why.append("It looks blurry or soft.")
    if bg is None and ncol > 3000:
        why.append("It looks like a photo or screenshot, not a logo file (busy background, lots of colors).")
    if why:
        why.append("Send the original logo file (ask whoever made it), or pick one of our options.")
        return {"verdict": "REDO", "why": why, "size": (w, h), "background": bg}
    if long_side < PRINT_PX:
        why.append(f"Sharp enough for the website and social pages ({w}×{h}), but too small to print big "
                   f"(signs, shirts). A file at least {PRINT_PX}px wide would cover print too.")
        verdict = "WEB" if long_side >= WEB_PX else "REDO"
        if verdict == "REDO":
            why.append("At this size it would look soft even on the website.")
    else:
        verdict = "GOOD"
        why.append(f"Sharp and big enough ({w}×{h}) for every format, print included.")
    if bg not in (None, "transparent"):
        why.append("It has a solid background: Lucy will remove it for the no-background versions.")
    return {"verdict": verdict, "why": why, "size": (w, h), "background": bg}


def _remove_bg(im, bg):
    if bg in (None, "transparent"):
        return im
    import numpy as np
    a = np.asarray(im).copy()
    diff = np.abs(a[..., :3].astype(int) - np.array(bg)).sum(axis=2)
    a[..., 3] = np.where(diff < 40, 0, a[..., 3])
    from PIL import Image
    return Image.fromarray(a, "RGBA")


def _trim(im):
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def make_files(data: bytes, filename: str, out: Path) -> List[str]:
    """Every format from their own logo (only call after a GOOD or WEB verdict)."""
    from PIL import Image
    out.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    if ext == ".svg":
        (out / "logo.svg").write_bytes(data)
        # render the SVG once, big, with the same headless browser the options use
        from automations.online_presence import logo_maker as LM
        LM._shot(f'<html><body style="margin:0;background:transparent"><div id="l" style="display:inline-block;'
                 f'width:1600px">{data.decode("utf-8", "ignore").replace("<svg", "<svg width=1600", 1)}</div></body></html>',
                 out / "_render.png", "#l")
        im = _load((out / "_render.png").read_bytes())
        (out / "_render.png").unlink()
    else:
        im = _load(data)
    info = check(data, filename)
    clean = _trim(_remove_bg(im, info.get("background")))
    pad = int(max(clean.size) * 0.06)
    canvas = Image.new("RGBA", (clean.width + 2 * pad, clean.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(clean, (pad, pad), clean)
    canvas.save(out / "logo.png")
    white = canvas.copy()
    px = white.load()
    for y in range(white.height):              # every inked pixel -> white (for dark backgrounds)
        for x in range(white.width):
            r, g, b, a = px[x, y]
            if a:
                px[x, y] = (255, 255, 255, a)
    white.save(out / "logo-white.png")
    on_white = Image.new("RGB", canvas.size, (255, 255, 255))
    on_white.paste(canvas, (0, 0), canvas)
    on_white.save(out / "logo.jpg", quality=95)
    on_white.save(out / "logo.pdf", resolution=300)
    side = max(canvas.size)
    icon = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    icon.paste(canvas, ((side - canvas.width) // 2, (side - canvas.height) // 2), canvas)
    icon = icon.resize((800, 800))
    icon.save(out / "icon.png")
    icon_w = Image.new("RGB", icon.size, (255, 255, 255))
    icon_w.paste(icon, (0, 0), icon)
    icon_w.save(out / "icon.jpg", quality=95)
    return sorted(f.name for f in out.iterdir())


def main_color(path: Path) -> str:
    """The logo's strongest non-gray color, for the website's accent."""
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    im.thumbnail((120, 120))
    best, score = "#C8A24B", 0
    for count, (r, g, b, a) in im.getcolors(20000) or []:
        if a < 200:
            continue
        sat = max(r, g, b) - min(r, g, b)
        if sat > 60 and count * sat > score:
            best, score = f"#{r:02X}{g:02X}{b:02X}", count * sat
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="online_presence.logo_upload")
    ap.add_argument("file")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    data = Path(a.file).read_bytes()
    v = check(data, a.file)
    print(f"{v['verdict']}: " + " ".join(v["why"]))
    if a.out and v["verdict"] in ("GOOD", "WEB"):
        print("✓ made:", ", ".join(make_files(data, a.file, Path(a.out))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
