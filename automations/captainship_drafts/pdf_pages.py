"""Turn a list of board PNGs into one printable PDF.

Extracted from weekly_pdf on 2026-09-01, when the DAILY boards got attachments
of their own (daily_pdf) and two modules needed the same page geometry. Nothing
here knows which report it is printing — it takes [(label, png)] and writes a
PDF — so the weekly and the daily attachments can never drift into looking like
two different documents. The geometry and the composer below are Rafael's
2026-08-30 shape, moved verbatim; their reasoning is preserved as written.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


# EVERY PAGE IS ITS OWN BOARD'S SIZE (Rafael's Loom, 2026-08-30). It was a
# fixed Letter LANDSCAPE page with each board scaled down and centred on white,
# and that is what he was looking at when he said "this one's super small,
# there's just a lot of white space on there … Chan's looks way better, it's
# more fit to screen … maybe, I guess, like a PDF of each, it's just a PDF of
# the thing, there's no white space on any of it."
#
# The white space was not a bug in the scaling, it was the fixed page. These
# boards have wildly different aspect ratios — the Captainship Summary is wide
# and short (one row per ICD), a 48-rep office board is nearly square — so
# fitting each into one page shape means whichever dimension runs out first
# decides the scale and the OTHER one pads with white. Rafael's board padded
# top and bottom; Chan's, with a third of the reps, happened to land near the
# page's own ratio and so looked "fit to screen". Same code, different office.
#
# So the page IS the image: no letter box, no margin, no downscale. A viewer's
# fit-to-width then fills the screen with the board on every page, which is
# what he asked for, and the board PNG already carries its own padding
# (render._draw's PAD) so nothing touches the paper edge.
#
# DPI still 150 — it sets the page's physical size (a 1800px board becomes a
# 12in-wide page), and PDF readers fit to the window, so this only decides what
# "100%" means on a desktop.
DPI = 150

# The widest a page's IMAGE is embedded at. The boards are drawn at 2x density
# (total_knocks.render.SCALE) and a 48-rep one is ~3500px, which as raw page
# images would make a 14-board PDF tens of megabytes — attached to a mail that
# already carries every board inline, and an oversized mail FAILS to send.
#
# Capping the pixels costs nothing that matters here: the page's ASPECT is what
# fit-to-screen depends on and that is untouched, so a capped page fills the
# reader's screen exactly as an uncapped one would. All it changes is how far a
# reader can zoom before it softens.
#
# 1800 rather than something larger because of what this rides in. On Sun/Mon
# the captainship mail carries BOTH knock sections inline — ~34 board images —
# and this PDF on top; measured 2026-08-30, a 2400 cap put the message at ~28MB
# base64-encoded, over Gmail's 25MB, where an oversized mail FAILS rather than
# degrades. At 1800 the whole message lands near 20MB.
#
# And 1800 is not a regression in zoom detail: the boards were 1753px NATIVE
# before they rendered at 2x, so a page is still wider than the best that was
# ever available — now arrived at by a clean downscale from ~3500px instead of
# being the raw ceiling. Boards under the cap are embedded untouched.
PAGE_MAX_PX = 1800


def compose(pages: List[Tuple[str, Path]], out: Path) -> Path:
    """One board per page, each page EXACTLY its board's size — no letter box,
    no margin, no scaling (Rafael 2026-08-30; see the DPI note above).

    Pages in one PDF may differ in size, which is what lets a wide-and-short
    summary and a tall office board each fill the screen on their own page.
    The convert("RGB") stays: a PNG with alpha cannot be written to PDF."""
    from PIL import Image
    canvases = []
    for _label, png in pages:
        img = Image.open(png).convert("RGB")
        if img.width > PAGE_MAX_PX:
            # One good Lanczos pass, same reasoning as the email pre-shrink:
            # if the picture has to shrink, we would rather do it well once
            # than hand a reader's viewer a 3x reduction to do cheaply.
            h = max(1, round(img.height * PAGE_MAX_PX / img.width))
            img = img.resize((PAGE_MAX_PX, h), Image.LANCZOS)
        # NO palette pass here, deliberately — unlike the inline copies. PIL
        # flate-encodes PDF images from full RGB either way, so quantising
        # first measured byte-for-byte identical (7.40MB both ways,
        # 2026-08-30) and writing the P-mode image straight out is far WORSE
        # (84MB). The pixel cap above is this path's only real lever.
        canvases.append(img)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvases[0].save(out, "PDF", resolution=DPI, save_all=True,
                     append_images=canvases[1:])
    return out
