"""Render a Showdown flyer (HTML) to a PNG for the email, and fill the
standings/champions templates with live data.

Uses patchright's bundled Chromium (already a repo dependency) headless — no
extra tooling. The templates in flyers/ carry sample rows between the markers
below; we swap the <ol>…</ol> / champion values at render time.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

FLYER_DIR = Path(__file__).resolve().parent / "flyers"
STANDINGS_TPL = FLYER_DIR / "standings_flyer.html"
CHAMPIONS_TPL = FLYER_DIR / "champions_flyer.html"


def _medal(rank: int) -> str:
    return {1: "🥇 ", 2: "🥈 ", 3: "🥉 "}.get(rank, "")


def _ol(rows: List[Tuple[int, str, object]], unit: str) -> str:
    """rows: [(rank, name, value)] high→low. value '' renders as an em dash."""
    out = []
    for rank, name, val in rows[:10]:
        lead = " lead" if rank == 1 else ""
        vtxt = (f"{val} <span class=\"u\">{unit}</span>" if val not in ("", None)
                else "—")
        out.append(
            f"<li class=\"{lead.strip()}\"><span class=\"rank\">{rank}</span>"
            f"<span class=\"who\">{_medal(rank)}{name}</span>"
            f"<span class=\"val\">{vtxt}</span></li>")
    return "\n".join(out)


def fill_standings(sales_rows, rep_rows) -> str:
    """Return standings HTML with the two Top-10 lists swapped in."""
    html = STANDINGS_TPL.read_text(encoding="utf-8")
    # Each board's <ol>…</ol> is replaced by generated rows. There are exactly
    # two <ol> blocks (personal, then rep) in template order.
    import re
    ols = list(re.finditer(r"<ol>.*?</ol>", html, flags=re.S))
    if len(ols) != 2:
        return html  # template changed; leave sample rows rather than corrupt
    new_personal = f"<ol>\n{_ol(sales_rows, 'new int')}\n</ol>"
    new_rep = f"<ol>\n{_ol(rep_rows, 'heads')}\n</ol>"
    # replace right-to-left so spans stay valid
    html = html[:ols[1].start()] + new_rep + html[ols[1].end():]
    html = html[:ols[0].start()] + new_personal + html[ols[0].end():]
    return html


def fill_champions(sales_champ: Tuple[str, object],
                   rep_champ: Tuple[str, object]) -> str:
    """sales_champ / rep_champ = (name, value). Swap names + stats in."""
    html = CHAMPIONS_TPL.read_text(encoding="utf-8")
    import re
    # personal card: name then "<b>N</b> new-internet sales"
    html = re.sub(r"(class=\"cname\">)[^<]*(</div>)",
                  lambda m, it=iter([sales_champ[0], rep_champ[0]]):
                  f"{m.group(1)}{next(it)}{m.group(2)}", html, count=2)
    html = html.replace("<b>142</b> new-internet sales",
                        f"<b>{sales_champ[1]}</b> new-internet sales")
    html = html.replace("grew by <b>+18</b> reps",
                        f"grew by <b>{rep_champ[1]:+d}</b> reps"
                        if isinstance(rep_champ[1], int)
                        else f"grew by <b>{rep_champ[1]}</b> reps")
    return html


def render_png(html: str, out_png: Path, width: int = 880) -> Path:
    """Render HTML string to a PNG via headless Chromium (patchright)."""
    from patchright.sync_api import sync_playwright
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900},
                                device_scale_factor=2)
        page.set_content(html, wait_until="networkidle")
        # Neutralize the min-height:100vh so the page sizes exactly to content:
        # full_page capture then has no empty void below AND can't clip the
        # footer. The gradient background still fills the captured area.
        page.add_style_tag(content="body{min-height:0!important}")
        page.screenshot(path=str(out_png), full_page=True)
        browser.close()
    return out_png
