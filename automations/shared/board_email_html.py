"""ONE HTML shape for every screenshot-board email.

The board emails used to each build their own `<img>` soup — the Org board in
`org_sales_board.screenshot_email`, the Country board in
`board_emails.email_send`. Two copies of the same layout meant a legibility fix
had to be made twice, and both copies had already had to learn the same two
lessons independently. This is that layout, once.

LESSON 1 — A TABLE, NOT A STACK OF DIVS. An `<img>` is an INLINE element, so
Gmail rescales the screenshots to fit its reading pane and then flows whatever
fits onto the same line: the 7/30 email arrived with the boxes SIDE BY SIDE, two
per row, in an order nobody could follow. It looked right in the on-disk preview
because a browser had the width to give each one its own line, so the browser
preview does NOT catch this. A presentation table with one `<tr><td>` per image
is the layout every client honours — a table row cannot flow beside another one.
[[project_email-images-need-a-table-not-bare-img]]

LESSON 2 — EACH IMAGE AS WIDE AS ITS BLOCK IS ON THE SHEET, not all the same.
Every image arrives from a fit-to-WIDTH PDF export, so they all come back the
same pixel width whatever they contain. Painted at equal widths, a narrow
six-column leaderboard rendered ~1.9x the text size of the twelve-column daily
tables beside it ("la letra casi el doble de grande"). Scaling each against the
WIDEST block puts one sheet pixel at the same size in every image — the
proportions the board actually has in Sheets. Percentages of the wrapper, never
px, so it holds in a narrow reading pane too.

This is why the images carry a third element, `sheet_px`, all the way from the
renderer through the manifest to here. A block whose width could not be measured
comes through as 0, and a set with any 0 in it falls back to the old equal-width
layout rather than mis-scaling something someone already approved.

WHY THE IMAGES MUST BE HI-DPI. The wrapper is 1200px and the widest block fills
it; on a retina screen that is 2400 device pixels. A PNG narrower than that gets
upscaled, and a table of small numbers upscaled is mush. The renderer draws every
block at 2x (`screenshot_email.RENDER_SCALE`) and nothing here ever scales an
image UP — `height:auto` keeps the aspect ratio and the browser only shrinks.
[[project_board-emails-image-legibility]]
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

# The wrapper's ceiling. The widest block fills it and every other block is sized
# as a fraction of it, so this sets the scale of the whole email. 1200 (was 1000)
# because once the blocks are proportional the narrow ones get small fast if the
# wrapper is tight. Gmail still shrinks the lot to fit its pane — the PROPORTIONS
# are what survive, which is the point.
WRAPPER_PX = 1200

# The most pixels any mail client can actually show: 2x the wrapper, i.e. the
# CSS width at retina density.
INLINE_MAX_PX = 2 * WRAPPER_PX

_FONT = "Arial,Helvetica,sans-serif"


def inline_image_bytes(path, max_px: int = 0) -> bytes:
    """One inline board image's payload: pre-shrunk + lightly sharpened when it
    is wider than any client can show, the file's own bytes otherwise.

    WHY PRE-SHRINK AT ALL (Raf 2026-08-23, "comes out kind of blurry"). A board
    that renders 3000-4400px wide and is embedded at max-width:100% gets shrunk
    3x+ by the CLIENT, and mail clients downscale that far with cheap sampling
    that drops half the 1px gridlines and glyph strokes. One clean Lanczos pass
    plus a mild unsharp leaves the client only a gentle final shrink, so the
    strokes survive. An image already inside the cap is passed through
    byte-for-byte — resampling something that doesn't need it is the one way
    this could COST sharpness rather than buy it.

    Lives here, next to WRAPPER_PX, because it is the same answer for every
    board email we send. It was written for the Org Sales Board's blur and then
    not carried to the Captainship Reports, which embedded raw PNGs until
    2026-08-30 — one implementation is what stops that happening again
    (Megan's standing rule: everything we hand anyone is as fit-to-screen as it
    can be without losing sharpness)."""
    import io
    from pathlib import Path
    from PIL import Image, ImageFilter
    path = Path(path)
    cap = max_px or INLINE_MAX_PX
    im = Image.open(path)
    if im.width <= cap:
        return path.read_bytes()
    h = round(im.height * cap / im.width)
    im = im.convert("RGB").resize((cap, h), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    # Probe the ORIGINAL, not what we just resampled — see flatten_palette.
    im = flatten_palette(im, probe=Image.open(path))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# A board that survives quantising has this few colours or fewer. Well above
# what any table reaches (a 14-column weekly board measures ~1,600, nearly all
# of them antialiasing shades of three or four hues) and well below a
# photograph, which is the one thing 256 colours WOULD band.
_PALETTE_SAFE_COLOURS = 20_000


def flatten_palette(im, probe=None):
    """A 256-colour copy of `im` when that is visually free, `im` otherwise.

    `probe` is the image the "is this photographic?" question is asked OF,
    defaulting to `im` itself. Pass the ORIGINAL when `im` has been resampled:
    the question is about the CONTENT, and downscaling invents shades that have
    nothing to do with it. Measured 2026-08-30 on one board — 1,360 colours as
    drawn, 7,484 after Lanczos, 14,303 after the unsharp — so probing the
    processed image made the tallest boards read as photographs and skip the
    pass, and they were the ones costing 1.3MB each.

    These boards are flat fills and text, so a palette costs nothing a reader
    can see and roughly a THIRD of the bytes: measured 2026-08-30 on a 14-board
    captainship email, 15.8MB of inline copies became 5.5MB, with 1% of pixels
    differing at all and none by more than 26/255 — all of it on glyph edges.
    That is the difference between a mail that sends and one that doesn't, now
    that boards render at 2x (total_knocks.render.SCALE).

    The colour count is a real probe, not an assumption: getcolors() returns
    None once an image passes the ceiling, so a photograph — the one input
    where 256 colours would band visibly — is handed back untouched."""
    try:
        src = probe if probe is not None else im
        if src.convert("RGB").getcolors(maxcolors=_PALETTE_SAFE_COLOURS) is None:
            return im
        # dither=NONE: dithering scatters pixels to fake missing colours, which
        # on a flat fill is visible noise AND defeats the compression this is
        # for. With a table's handful of hues there is nothing to fake.
        from PIL import Image as _I
        return im.quantize(colors=256, dither=_I.Dither.NONE)
    except Exception:  # noqa: BLE001 — a size optimisation must never fail a send
        return im


# FULL-BLEED blocks take the whole wrapper and do NOT set the scale for anything
# else. Only the delta chart qualifies: at ~2000 sheet pixels it is half again as
# wide as any other block, so letting it be the reference dragged every normal
# table down to ~63px per column when the All Units board joined the Org email
# (from ~100px). Excluded, the scale is set by the ordinary tables — one
# consistent text size across the whole mail — and the delta simply uses all the
# room there is, which is exactly what it needs. [[project_board-emails-image-legibility]]
FULL_BLEED = ("delta",)


def is_full_bleed(name) -> bool:
    return str(name).endswith(FULL_BLEED)


def sheet_px(entry: Sequence) -> int:
    """The `sheet_px` of an (name, path[, sheet_px]) image entry, or 0."""
    return int(entry[2]) if len(entry) > 2 and entry[2] else 0


def scale_of(images: Sequence[Sequence]) -> int:
    """The sheet width that maps to 100% of the wrapper, or 0 when the set can't
    be scaled.

    0 means "lay them out equal-width": either nothing was measurable, or at
    least one block wasn't, and a half-scaled email is worse than an unscaled
    one — the unmeasured block would be the only one at the wrong size.

    Full-bleed blocks are excluded from the max but still checked for a width, so
    an unmeasured delta chart still trips the fallback."""
    if not images or any(sheet_px(i) <= 0 for i in images):
        return 0
    ordinary = [sheet_px(i) for i in images if not is_full_bleed(i[0])]
    return max(ordinary) if ordinary else max(sheet_px(i) for i in images)


def image_row(cid: str, *, alt: str = "", width_px: int = 0,
              widest_px: int = 0) -> str:
    """One image, one table row.

    `width_px` is this block's width ON THE SHEET and `widest_px` the width that
    maps to 100% (from `scale_of`); the image is painted at that fraction of the
    wrapper. Pass either as 0 to fall back to full width.

    CLAMPED AT 100%: a full-bleed block is wider than the reference by
    construction, and a width over 100% would push the table past the wrapper and
    give the mail a horizontal scrollbar.

    display:block kills the inline baseline gap Gmail otherwise leaves under an
    image, and height:auto stops Outlook stretching it to a stale height."""
    pct = 100 * width_px / widest_px if width_px > 0 and widest_px > 0 else 0
    size = f"width:{min(pct, 100):.2f}%" if pct > 0 else "max-width:100%"
    return ('<tr><td style="padding:0 0 16px">'
            f'<img src="cid:{cid}" alt="{alt}" '
            f'style="display:block;{size};height:auto;border:1px solid #ddd">'
            '</td></tr>')


def banner_row(text: str, *, bg: str = "#d9d9d9", fg: str = "#8a0000") -> str:
    """The board's own title bar — its own row, so it caps the stack."""
    return ('<tr><td style="padding:0 0 16px">'
            f'<div style="background:{bg};color:{fg};font-family:{_FONT};'
            'font-size:22px;font-weight:bold;text-align:center;padding:10px;'
            f'border:1px solid #bbb">{text}</div></td></tr>')


def separator_row(text: str = "") -> str:
    """A divider between two boards inside ONE email (Eve 2026-07-31: the Org
    board email and the All Units board email became a single mail, and "usa
    separadores para que se entienda uno del otro").

    JUST A LINE. It carried the board's name at first and Eve cut it the same
    day: the very next image is the board's own title bar, so the label restated
    what was about to be said — "es muy redundante". `text` is accepted and
    ignored so callers read as intent ("the divider before All Units") rather
    than a bare call, and so re-labelling it later is a one-line change here."""
    return ('<tr><td style="padding:20px 0 24px">'
            '<div style="border-top:3px solid #8a0000;font-size:0;'
            'line-height:0">&nbsp;</div></td></tr>')


def text_row(html: str, *, size: int = 13) -> str:
    """Free-form HTML (the sign-off, the signature block) in its own row."""
    return ('<tr><td style="padding:0">'
            f'<div style="font-family:{_FONT};font-size:{size}px;color:#000">'
            f'{html}</div></td></tr>')


def document(rows: Iterable[str]) -> str:
    """Wrap the rows in the single-column table.

    role="presentation" so screen readers don't announce it as a data table,
    cellpadding/cellspacing/border zeroed because Outlook applies its own
    defaults otherwise, and border-collapse:collapse because Gmail adds a 1px
    gap between rows without it."""
    return ('<div style="font-family:Arial,Helvetica,sans-serif;color:#000">'
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            f'border="0" width="100%" style="max-width:{WRAPPER_PX}px;'
            'border-collapse:collapse">'
            + "".join(rows) +
            '</table></div>')
