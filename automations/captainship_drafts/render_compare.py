"""Old-vs-new side-by-side for the captainship draft images.

Run this ON A MACHINE WHERE THE SHEETS PROFILE IS SIGNED IN (Lucy 1). It builds
BOTH versions of a captain's images —
  • OLD: the legacy Google-login screenshot (sheet_shot)
  • NEW: the login-free API render (sheet_render)
— and stacks each pair (OLD on top, NEW below) into one PNG so the difference
is obvious at a glance. This is the fidelity check for the login-free renderer
before it replaces the screenshot path in run.py.

    python -m automations.captainship_drafts.render_compare rafael

Output: output/render_compare/<captain>_<section>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

from automations.captainship_drafts import sheet_render, sheet_shot
from automations.captainship_drafts.config import BY_KEY

_LABEL_H = 34
_GAP = 18


def _labeled(img_path: Path, label: str) -> Image.Image:
    im = Image.open(img_path).convert("RGB")
    strip = Image.new("RGB", (im.width, _LABEL_H), (24, 24, 24))
    ImageDraw.Draw(strip).text((10, 9), label, fill=(255, 255, 255))
    out = Image.new("RGB", (im.width, im.height + _LABEL_H), (255, 255, 255))
    out.paste(strip, (0, 0))
    out.paste(im, (0, _LABEL_H))
    return out


def _stack(old_path: Path, new_path: Path, out_path: Path) -> Path:
    top = _labeled(old_path, "OLD  — Google-login screenshot (sheet_shot)")
    bot = _labeled(new_path, "NEW  — login-free API render (sheet_render)")
    w = max(top.width, bot.width)
    canvas = Image.new("RGB", (w, top.height + _GAP + bot.height),
                       (255, 255, 255))
    canvas.paste(top, (0, 0))
    canvas.paste(bot, (0, top.height + _GAP))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def compare(captain_key: str) -> list[Path]:
    flavor = BY_KEY[captain_key].flavor
    old_dir = Path("output") / "render_compare" / "_old"
    new_dir = Path("output") / "render_compare" / "_new"
    out_dir = Path("output") / "render_compare"

    old = sheet_shot.captain_shots(captain_key, flavor, old_dir)
    new = sheet_render.captain_shots(captain_key, flavor, new_dir)

    made: list[Path] = []
    made.append(_stack(old["product_summary"], new["product_summary"],
                       out_dir / f"{captain_key}_product_summary.png"))
    for i, ((cap_o, p_old), (cap_n, p_new)) in enumerate(
            zip(old["units"], new["units"])):
        made.append(_stack(p_old, p_new,
                           out_dir / f"{captain_key}_units{i}.png"))
    return made


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "rafael"
    for p in compare(key):
        print(f"comparison: {p}")
