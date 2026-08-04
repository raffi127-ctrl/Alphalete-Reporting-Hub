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


def _delta(val: object) -> str:
    """Signed change text: 0 -> '+0', -9 -> '-9'. Non-numeric -> em dash."""
    if isinstance(val, int):
        return f"+{val}" if val >= 0 else str(val)
    return "—"


def _ol(rows, unit: str, since: str = "") -> str:
    """rows: [(rank, name, value)] high→low, or [(rank, name, delta, headcount)]
    for the rep-count board. value '' renders as an em dash.
    Lists EVERY owner (Raf 2026-08-01: whole field on the flyer, not just top 10).

    4-tuples render BOTH numbers (Megan 2026-08-03): the headcount as the main
    figure and the change since the baseline underneath — "26 heads · +0 since
    Aug 2". Showing the delta alone made the whole board read as zeros, because
    on the baseline Sunday every owner's change is 0 by definition."""
    out = []
    for row in rows:
        if len(row) == 4:
            # Megan 2026-08-03: the CHANGE is the headline number and the
            # baseline headcount is the sub-line — this board is a growth race,
            # so "+4" is the story and "started with 26" is the context.
            rank, name, val, heads = row
            main = (f"{_delta(val)} <span class=\"u\">{unit}</span>"
                    if isinstance(val, int) else "—")
            # the count itself is bolded gold inside the sub-line (Raf 8/3)
            sub = (f"started with <b>{heads}</b>" if heads not in ("", None)
                   else "")
            vtxt = main + (f"<span class=\"delta\">{sub}</span>" if sub else "")
        else:
            rank, name, val = row
            vtxt = (f"{val} <span class=\"u\">{unit}</span>"
                    if val not in ("", None) else "—")
        lead = " lead" if rank == 1 else ""
        out.append(
            f"<li class=\"{lead.strip()}\"><span class=\"rank\">{rank}</span>"
            f"<span class=\"who\">{_medal(rank)}{name}</span>"
            f"<span class=\"val\">{vtxt}</span></li>")
    return "\n".join(out)


def fill_standings(sales_rows, rep_rows, days_left=None) -> str:
    """Return standings HTML with the two full-field lists swapped in.
    days_left (Raf 2026-08-01): if given, the timeline rail's middle becomes a
    live countdown ("N Days Left") instead of the static "31 Days"."""
    html = STANDINGS_TPL.read_text(encoding="utf-8")
    # Each board's <ol>…</ol> is replaced by generated rows. There are exactly
    # two <ol> blocks (personal, then rep) in template order.
    import re
    ols = list(re.finditer(r"<ol>.*?</ol>", html, flags=re.S))
    if len(ols) != 2:
        return html  # template changed; leave sample rows rather than corrupt
    new_personal = f"<ol>\n{_ol(sales_rows, 'new int')}\n</ol>"
    new_rep = f"<ol>\n{_ol(rep_rows, 'heads', since='since Aug 2')}\n</ol>"
    # replace right-to-left so spans stay valid
    html = html[:ols[1].start()] + new_rep + html[ols[1].end():]
    html = html[:ols[0].start()] + new_personal + html[ols[0].end():]
    if days_left is not None:
        n = max(0, int(days_left))
        unit = "Day" if n == 1 else "Days"
        # no-op if the template's rail text changed
        html = html.replace("→ 31 Days →", f"→ {n} {unit} Left →")
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


def render_pdf(html: str, out_pdf: Path, width: int = 880) -> Path:
    """Render HTML to a ONE-PAGE PDF (Megan 2026-08-03: the daily email carries
    the flyer as a PDF). The flyer is a poster, not a document — so the page is
    sized to the measured content height instead of letter, or the full 28/30-name
    field would break mid-board across pages. emulate_media('screen') keeps the
    dark gradient + gold (print media would drop the backgrounds)."""
    from patchright.sync_api import sync_playwright
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.emulate_media(media="screen")
        page.set_content(html, wait_until="networkidle")
        # Same content-fit measurement as render_png — body is display:flex and
        # won't grow past the viewport, so measure .flyer and pin the body to it
        # plus a bottom margin, else the footer sits flush on the cut edge.
        bottom_margin = 56
        content_h = page.evaluate("document.documentElement.scrollHeight")
        total_h = content_h + bottom_margin
        page.set_viewport_size({"width": width, "height": total_h})
        page.add_style_tag(
            content=f"body{{min-height:{total_h}px!important;"
                    f"align-items:flex-start!important}}")
        page.pdf(path=str(out_pdf), width=f"{width}px", height=f"{total_h}px",
                 print_background=True,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    return out_pdf


def render_png(html: str, out_png: Path, width: int = 880) -> Path:
    """Render HTML string to a PNG via headless Chromium (patchright)."""
    from patchright.sync_api import sync_playwright
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900},
                                device_scale_factor=2)
        page.set_content(html, wait_until="networkidle")
        # The body is display:flex and won't grow past the viewport, so full_page
        # would clip the footer flush to the bottom edge. Measure the real content
        # height (.flyer), then size the canvas to it PLUS a bottom margin and pin
        # the body to that height so its gradient fills the breathing room below
        # the footer (Raf 2026-08-01: full field looked cut off).
        bottom_margin = 56
        content_h = page.evaluate("document.documentElement.scrollHeight")
        total_h = content_h + bottom_margin
        page.set_viewport_size({"width": width, "height": total_h})
        page.add_style_tag(
            content=f"body{{min-height:{total_h}px!important;"
                    f"align-items:flex-start!important}}")
        page.screenshot(path=str(out_png), full_page=True)
        browser.close()
    return out_png
