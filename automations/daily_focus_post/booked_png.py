"""The interviews-booked picture: one column per funnel.

    Interviews booked  |  Tuesday, Nov 24
    Main 11280          AI 24065           LinkedIn 24226
    1st Rounds | 57     1st Rounds | 8     1st Rounds | 4
    8:15 AM   10        8:30 AM   5        10:00 AM  4
    ...                 ...                ...
    2nd Rounds | 50     2nd Rounds | 6     2nd Rounds | 2
    8:45 AM   13        1:00 PM   6        3:00 PM   2

WHY A PICTURE AND NOT THE TEXT IT REPLACES. The funnel numbers went out as
monospace Slack blocks, one reply per funnel -- four posts, each a wall of
right-ragged digits. Megan, 2026-11-24: "we need to make it look better.
I'm thinking similar to the text scheduled that goes out daily", and then
"1 picture for all 4 and it should just have 1 column per funnel".

IT BORROWS `recruiting_day_texts.render` RATHER THAN RESTATING IT. That is
the renderer behind the morning schedule text she was pointing at, so the
two surfaces cannot drift into looking like different systems -- same
fonts, same header bars, same zebra rows, same 2x draw so it stays sharp on
a phone. A second copy of those constants is how they would drift.

EL PASO IS NOT IN THIS PICTURE. Megan, 2026-11-24: "El paso needs to go to
Al's channel only". A combined image cannot be split after the fact, so the
funnels that belong to somebody else's channel are drawn as their OWN
picture and never land in Raf's thread. That is the same rule
`roster.booked_own_channel` already encodes -- this just has to honour it
at draw time rather than at post time.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from automations.recruiting_day_texts.render import S, fmt_day

# THE HOUSE LOOK, NOT THE MORNING PICTURE'S. Megan, 2026-11-24: "I don't
# love how the colors formatting look. I like the layout." The layout stayed;
# everything else here now follows her standing rules for report output
# (feedback_report_formatting_standard, set 2026-07-17, "it's what I want
# everywhere"):
#
#   * GEORGIA, bold, BLACK. Never coloured text -- status is carried by the
#     FILL, which is why the totals sit on gold rather than being printed in
#     gold. The one kept exception is a dark header band, where black would
#     be invisible, so that row stays white.
#   * CENTERED horizontally and vertically, every cell, header and body.
#     "Left-aligned reads sloppy next to other offices' boards."
#   * A THIN BORDER on every filled cell.
#
# The palette is the Altura tracker's, the one board she has volunteered that
# she likes (2026-10-09): warm cream ground with gold accents, not
# white-on-grey.
# BLUE, NOT GOLD (Megan, 2026-11-24: "let's do blue hues"). Same three
# standing rules, a different ramp: one hue, light to dark, so the darkest
# thing on the page is the thing to read first.
BG = "#F7FAFD"            # palest blue ground
INK = "#000000"           # every value, per the standing rule
# NO WHITE TEXT ANYWHERE. Megan, 2026-11-24: "the white is hard to read",
# and then of the round band, "so is the 1st round and 2nd round label". The
# standing rule was always black text with the FILL carrying the status; the
# white-on-dark exception existed only because black is invisible on a deep
# navy. Taking the navy out removes the need for the exception, so the whole
# picture is black on blue and the hierarchy is carried by how dark each
# fill is: round band darkest, then the total chip, then the funnel label,
# then the time column, then the zebra.
BAND_BG = "#7FB0D6"       # round band -- the darkest fill here
BAND_INK = "#000000"
# BLACK ON LIGHT, NOT WHITE ON MID-BLUE. Megan, 2026-11-24: "the white is
# hard to read". White only ever had a licence on a DARK band, where black
# is invisible; #2E6DA4 is not dark enough to earn it, so the label band
# goes light and the text goes black like every other value here. It still
# stands out -- the band is a filled strip, which is what carries it.
FUNNEL_BG = "#BBD6EC"     # the funnel label's own band -- see `_band`
FUNNEL_INK = "#000000"
HEAD_BG = "#DCE8F4"       # sub-header
TOTAL_BG = "#9EC2E2"      # the fill that makes a total read first
ZEBRA = "#EDF3F9"
GRID = "#3D6E99"          # darker blue, so the grid reads as a grid
MUTED = "#415A72"

_GEORGIA = {
    "bold": ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
             "C:/Windows/Fonts/georgiab.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"],
    "reg": ["/System/Library/Fonts/Supplemental/Georgia.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
}


def _font(kind: str, size: int):
    """Georgia at 2x, falling back to a serif that exists on Linux."""
    from PIL import ImageFont
    for path in _GEORGIA[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size * S)
    return ImageFont.load_default(size * S)

COLW = 300
GAP = 24
PAD = 24
ROW_H = 34


def _minutes(label: str) -> int:
    """"1:45 PM" -> minutes past midnight, for sorting the rows.

    Sorting the printed strings puts 10:45 AM before 8:15 AM and 12:00 PM
    before 1:00 PM, which is how a schedule ends up looking shuffled.
    """
    t = str(label or "").strip().upper()
    half = 12 * 60 if t.endswith("PM") else 0
    hm = t.replace("AM", "").replace("PM", "").strip()
    try:
        h, m = (int(x) for x in hm.split(":"))
    except Exception:          # noqa: BLE001 -- an unparseable time sorts last
        return 10 ** 6
    if h == 12:
        h = 0
    return half + h * 60 + m


def _matrix(day_slots):
    """[{label, office, slots:[(time, n)]}] -> (times, rows, totals).

    One row per time that ANY funnel booked, and a count per funnel in it.
    A funnel with nothing at that time gets a dash, not a zero: zero reads
    as a measurement and the dash reads as "not a slot they run", which is
    what it is.
    """
    times = sorted({t for f in day_slots for t, _n in (f.get("slots") or ())},
                   key=_minutes)
    totals = [sum(int(n) for _t, n in (f.get("slots") or ()))
              for f in day_slots]
    rows = []
    for t in times:
        row = [t]
        for f in day_slots:
            at = {tt: n for tt, n in (f.get("slots") or ())}
            row.append(str(at[t]) if t in at else "\u2014")
        rows.append(row)
    return times, rows, totals



def _band(d, x: int, y: int, w: int, title: str, total: int,
          heads: Sequence[tuple], rows, timew: int, colw: int) -> int:
    """One round's table: a title bar, a header row, then the counts.

    DRAWN HERE RATHER THAN THROUGH `render._table` because of one thing --
    the TOTAL. Through the shared helper the total was just more text in the
    header cell, same size, same weight, same ink as the label beside it, and
    Megan, 2026-11-24: "the total number blends in too much". It is the number
    somebody reads first, so it is set large, in the navy the header bars
    already use, with the label small and grey above it.

    Everything else still comes from `render`'s constants, so the colours and
    fonts cannot drift from the morning picture.
    """
    rh = 36 * S
    f_title, f_lab, f_tot, f_row = (_font("bold", 16), _font("bold", 12),
                                    _font("bold", 22), _font("bold", 14))

    def cell(x0, y0, x1, y1, fill, text, font, ink=INK):
        """A filled, thin-bordered, CENTERED cell -- the three standing
        rules in one place so no caller can forget one."""
        d.rectangle([x0, y0, x1, y1], fill=fill, outline=GRID, width=S)
        if text != "":
            d.text(((x0 + x1) / 2, (y0 + y1) / 2), str(text), font=font,
                   fill=ink, anchor="mm")

    edges = [x, x + timew] + [x + timew + (i + 1) * colw
                              for i in range(len(heads))]
    cell(x, y, x + w, y + rh, BAND_BG, title, f_title, BAND_INK)
    y += rh

    # THE FUNNEL NAME GETS ITS OWN BAND. Megan, 2026-11-24: "make the funnel
    # labels a little more stand out". As grey small-caps over the counts it
    # was the quietest thing in a column it names, so it now sits on a filled
    # mid-blue strip of its own -- a header for the column rather than a
    # caption on it. The account number stays beside it, smaller, because it
    # is how the office is looked up and not how it is read.
    lh = 30 * S
    d.rectangle([x, y, edges[1], y + lh], fill=HEAD_BG, outline=GRID, width=S)
    for i, (label, _n) in enumerate(heads):
        x0, x1 = edges[i + 1], edges[i + 2]
        d.rectangle([x0, y, x1, y + lh], fill=FUNNEL_BG, outline=GRID, width=S)
        d.text(((x0 + x1) / 2, y + lh / 2), label, font=_font("bold", 15),
               fill=FUNNEL_INK, anchor="mm")
    y += lh

    hh = 46 * S
    # "Time" is the column heading the whole left side hangs off, so it is
    # set at the funnel labels' size rather than the small label size it
    # inherited (Megan, 2026-11-24: "make the word time larger").
    cell(x, y, edges[1], y + hh, HEAD_BG, "Time", _font("bold", 15))
    for i, (_label, n) in enumerate(heads):
        x0, x1 = edges[i + 1], edges[i + 2]
        # THE TOTAL READS FIRST, and it does it with a FILL rather than a
        # colour on the digits -- Megan's rule, and the reason an earlier
        # version's total "blends in too much" is that it was neither.
        cell(x0, y, x1, y + hh, TOTAL_BG, n, f_tot)
    y += hh

    if not rows:
        rows, muted = [["None booked"] + [""] * len(heads)], True
    else:
        muted = False
    for i, r in enumerate(rows):
        band = ZEBRA if i % 2 else BG
        cell(x, y, edges[1], y + rh, band, r[0], f_row,
             MUTED if muted else INK)
        for j, v in enumerate(r[1:]):
            cell(edges[j + 1], y, edges[j + 2], y + rh, band, v, f_row,
                 MUTED if str(v) == "\u2014" else INK)
        y += rh
    cell(x, y, x + w, y + rh, TOTAL_BG, "Total  %d" % total,
         _font("bold", 15))
    return y + rh + 24 * S


def draw(day: dt.date, owner: str, funnels: Sequence[Dict], out: Path) -> Path:
    """One picture: times down the left, one column per funnel.

    `funnels` = [{"label", "office", "first": [(time, n)], "second": [...]}]
    in the order the columns should appear. Times come in formatted.

    Megan, 2026-11-24: "all the times should be on the left then a column
    per funnel and a count in each time of how many are scheduled and a
    total at the top next to the account number label at the top of the
    column". So the funnels share one time axis instead of each carrying
    its own -- which is what makes two funnels comparable at a glance, and
    what three side-by-side time columns never were.

    1st and 2nd rounds are two tables, because a 9:00 AM first round and a
    9:00 AM second round are different rooms and adding them would be a
    number nobody asked for.
    """
    funnels = list(funnels)
    if not funnels:
        raise ValueError("no funnels to draw")

    bands = []
    # "Interviews", not "rounds" (Megan, 2026-11-24). The data keys stay
    # `first` / `second` -- they are what schedule.py hands over, and
    # renaming those to follow a label would mean touching the reader too.
    for key, title in (("first", "1st Interviews"),
                       ("second", "2nd Interviews")):
        slots = [{"label": f["label"], "office": f.get("office", ""),
                  "slots": f.get(key) or ()} for f in funnels]
        times, rows, totals = _matrix(slots)
        heads = [("%s  \u00b7  %s" % (f["label"], f.get("office", "")), n)
                 for f, n in zip(funnels, totals)]
        bands.append((title, heads, rows, sum(totals)))

    n = len(funnels)
    pad = PAD * S
    timew, colw = 130 * S, 170 * S
    width = max(pad * 2 + timew + colw * n, 560 * S)
    tablew = width - pad * 2
    # GENEROUS, THEN CROPPED. The canvas is sized from the real row heights
    # used below (36 body, 56 header, 36 title, 36 total, 24 gap) plus a
    # whole band of slack -- an undersized canvas does not error, it leaves a
    # BLACK BAND where the drawing ran past the bottom, which is what the
    # first cream version shipped with. The crop at the end trims whatever
    # is left over, so over-allocating costs nothing.
    rowcount = sum(max(len(r), 1) for _t, _c, r, _n in bands)
    height = (pad + 70 * S + rowcount * 36 * S
              + len(bands) * (36 + 30 + 46 + 36 + 24) * S + 200 * S)

    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.text((width / 2, pad + 10 * S), "Interviews Booked  \u2014  %s"
           % fmt_day(day), font=_font("bold", 22), fill=INK, anchor="mm")
    d.text((width / 2, pad + 40 * S), "%s \u00b7 From AppStream" % owner,
           font=_font("bold", 13), fill=MUTED, anchor="mm")

    y = pad + 60 * S
    for title, heads, rows, total in bands:
        y = _band(d, pad, y, tablew, title, total, heads, rows, timew, colw)

    img = img.crop((0, 0, width, y + pad // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
