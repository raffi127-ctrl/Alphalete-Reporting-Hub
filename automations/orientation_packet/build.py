"""Render the Orientation Manual to a branded PDF.

    python -m automations.orientation_packet.build \
        --company "Alphalete Marketing" --owner "Raf & JD" \
        --location "Irving, TX" --logo resources/alphalete-logo-hq.png \
        -o output/orientation_alphalete.pdf

All branding is swappable: --company, --owner, --location, --primary (hex),
--accent (hex), --dark (hex), --logo. With no branding flags it renders the
Alphalete baseline. Uses only reportlab built-in fonts, so it runs identically
on macOS and Windows.
"""
from __future__ import annotations

import argparse
import io
import re
from dataclasses import dataclass
from pathlib import Path

import segno
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from . import content as C

PAGE_W, PAGE_H = letter          # 612 x 792 pt
MARGIN = 46
SIDEBAR_W = 30                   # accent strip on the right edge
BODY_L = MARGIN
BODY_R = PAGE_W - MARGIN - SIDEBAR_W - 8
BODY_W = BODY_R - BODY_L

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FONT_I = "Helvetica-Oblique"


# --------------------------------------------------------------------------
# Branding
# --------------------------------------------------------------------------
def _hex(v: str):
    v = v.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    r, g, b = (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (r, g, b)


def _mix(a, b, t):
    """Blend colour a toward b by fraction t (0 = a, 1 = b)."""
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


@dataclass
class Brand:
    primary: tuple = _hex("#9E1B2E")   # maroon / red
    accent: tuple = _hex("#B8965A")    # gold
    dark: tuple = _hex("#17130F")      # warm near-black panel
    cream: tuple = _hex("#F4EFE4")     # light background
    ink: tuple = _hex("#222222")       # body text
    muted: tuple = _hex("#6B6157")

    @classmethod
    def from_args(cls, primary=None, accent=None, dark=None):
        b = cls()
        if primary:
            b.primary = _hex(primary)
        if accent:
            b.accent = _hex(accent)
        if dark:
            b.dark = _hex(dark)
        return b


def build_context(company, owner, location, upline=None, backend=None):
    """Derive every token the content uses from the inputs."""
    company = company.strip()
    owner = owner.strip()
    # owner_short = first name / first token before &, comma, "and"
    owner_short = re.split(r"[&,]| and ", owner, flags=re.I)[0].strip()
    company_short = company.split()[0] if company.split() else company
    upline = (upline or "").strip() or owner   # the office's upline leadership
    backend = (backend or "").strip()          # backend support name(s)
    # If there's backend support, name it; otherwise it's just the one leader.
    base = ("UPLINE — Your Leadership Chain. This includes all of your upline "
            "leadership to {u}")
    if backend:
        upline_line = base.format(u=upline) + \
            f" as well as {backend} for backend support."
    else:
        upline_line = base.format(u=upline) + "."
    return {
        "company": company,
        "company_upper": company.upper(),
        "company_short": company_short,
        "owner": owner,
        "owner_upper": owner.upper(),
        "owner_short": owner_short,
        "location": location.strip(),
        "upline": upline,
        "upline_line": upline_line,
    }


def _week_table_from(schedule):
    """Build the schedule page's week_table from per-day ICD inputs:
    office_mon..office_sun, field_mon..field_sun. Blank or 'OFF' → OFF."""
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    def cell(prefix, d):
        v = (schedule.get(f"{prefix}_{d.lower()}") or "").strip()
        return "OFF" if (not v or v.upper() == "OFF") else v

    return {
        "days": days,
        "rows": [
            ["OFFICE"] + [cell("office", d) for d in days],
            ["FIELD"] + [cell("field", d) for d in days],
        ],
    }


def _fill(obj, ctx):
    """Recursively substitute {tokens} through the page spec."""
    if isinstance(obj, str):
        try:
            return obj.format(**ctx)
        except (KeyError, IndexError):
            return obj
    if isinstance(obj, list):
        return [_fill(x, ctx) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_fill(x, ctx) for x in obj)
    if isinstance(obj, dict):
        return {k: _fill(v, ctx) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------
# Low-level drawing helpers
# --------------------------------------------------------------------------
def _wrap(text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _vcenter(box_top, avail, block_h, size, min_gap=8, lead=None):
    """First baseline that vertically centers a text block in an area of height
    `avail` starting at box_top. block_h is the measured drawn height (leading
    per line + trailing gaps); the true visual block runs from the first line's
    cap to the last baseline, so subtract one leading and add the cap height.
    """
    lead = lead or size * 1.4
    cap = size * 0.72
    visual = max(cap, block_h - lead + cap)
    gap = max(min_gap, (avail - visual) / 2)
    return box_top - gap - cap


def draw_paragraph(c, text, x, y, width, size=10, leading=None, font=FONT,
                   color=(0, 0, 0), align="left"):
    """Draw wrapped text top-down from y. Returns the y below the last line."""
    leading = leading or size * 1.35
    c.setFillColorRGB(*color)
    c.setFont(font, size)
    for line in _wrap(text, font, size, width):
        if align == "center":
            c.drawCentredString(x + width / 2, y, line)
        elif align == "right":
            c.drawRightString(x + width, y, line)
        else:
            c.drawString(x, y, line)
        y -= leading
    return y


def hl_text(c, x, y, text, size, hi, txt=(1, 1, 1), font=FONT_B, pad=4):
    """Draw text on a highlighter block (Hormozi-style). Returns end x."""
    w = stringWidth(text, font, size)
    c.setFillColorRGB(*hi)
    c.roundRect(x - pad, y - size * 0.26, w + 2 * pad, size * 1.04, 2,
                stroke=0, fill=1)
    c.setFillColorRGB(*txt)
    c.setFont(font, size)
    c.drawString(x, y, text)
    return x + w + pad


def checkbox(c, x, y, brand, size=9):
    c.setStrokeColorRGB(*brand.accent)
    c.setLineWidth(1.1)
    c.rect(x, y, size, size, stroke=1, fill=0)


_QR_CACHE = {}


def qr_image(url):
    """Real scannable QR as a black-on-white ImageReader (cached)."""
    if url not in _QR_CACHE:
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="png", scale=12, border=1,
                                        dark="#000000", light="#ffffff")
        buf.seek(0)
        _QR_CACHE[url] = ImageReader(buf)
    return _QR_CACHE[url]


def sidebar(c, brand, word):
    """Rotated section word down the right edge with thin accent ticks.

    Print-friendly: no filled strip — just a hairline rule and rotated text.
    """
    if not word:
        return
    cx = PAGE_W - SIDEBAR_W / 2 + 3
    spaced = "  ".join(word.upper())
    tw = stringWidth(spaced, FONT_B, 10.5)
    c.setStrokeColorRGB(*brand.accent)
    c.setLineWidth(1.5)
    c.line(cx, PAGE_H / 2 + tw / 2 + 12, cx, PAGE_H - 62)
    c.line(cx, 62, cx, PAGE_H / 2 - tw / 2 - 12)
    c.saveState()
    c.translate(cx, PAGE_H / 2)
    c.rotate(90)
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 10.5)
    c.drawCentredString(0, -3.5, spaced)
    c.restoreState()


def footer(c, brand, ctx, page_no, logo):
    # no footer logo — the logo lives top-right on content pages
    y = 26
    c.setStrokeColorRGB(*brand.accent)
    c.setLineWidth(0.8)
    c.line(BODY_L, y + 20, BODY_R, y + 20)
    c.setFillColorRGB(*brand.muted)
    c.setFont(FONT, 7.5)
    c.drawCentredString((BODY_L + BODY_R) / 2, y,
                        f"{ctx['company'].upper()}  ·  ORIENTATION MANUAL")
    c.setFont(FONT_B, 8)
    c.setFillColorRGB(*brand.primary)
    c.drawRightString(BODY_R, y, str(page_no))


def header_logo(c, logo):
    """Logo in the top-right, sitting just left of the sidebar strip."""
    if logo is not None:
        _place_logo(c, logo, PAGE_W - 40, PAGE_H - 64, max_w=110,
                    max_h=52, align="right")


def _tri(c, pts, color):
    c.setFillColorRGB(*color)
    path = c.beginPath()
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)
    path.close()
    c.drawPath(path, fill=1, stroke=0)


def top_accents(c, brand):
    """Small angular brand accents in the top corners (interior pages)."""
    _tri(c, [(0, PAGE_H), (150, PAGE_H), (0, PAGE_H - 66)], brand.primary)
    _tri(c, [(0, PAGE_H), (88, PAGE_H), (0, PAGE_H - 40)], brand.accent)
    _tri(c, [(PAGE_W, PAGE_H), (PAGE_W - 150, PAGE_H),
             (PAGE_W, PAGE_H - 66)], brand.accent)
    _tri(c, [(PAGE_W, PAGE_H), (PAGE_W - 88, PAGE_H),
             (PAGE_W, PAGE_H - 40)], brand.primary)


def _place_logo(c, logo, x, y, max_w, max_h, align="left"):
    iw, ih = logo.getSize()
    scale = min(max_w / iw, max_h / ih)
    w, h = iw * scale, ih * scale
    if align == "center":
        x = x - w / 2
    elif align == "right":
        x = x - w
    c.drawImage(logo, x, y, width=w, height=h, mask="auto",
                preserveAspectRatio=True)
    return w, h


def section_title(c, brand, title, subtitle=None, y=PAGE_H - 92):
    """Standard page header: primary rule + bold title (+ optional subtitle)."""
    c.setFillColorRGB(*brand.primary)
    c.rect(BODY_L, y + 20, 46, 5, stroke=0, fill=1)          # short accent tab
    c.setFillColorRGB(*brand.ink)
    c.setFont(FONT_B, 22)
    c.drawString(BODY_L, y - 8, title)
    below = y - 8
    if subtitle:
        c.setFillColorRGB(*brand.accent)
        c.setFont(FONT_B, 11)
        c.drawString(BODY_L, y - 26, subtitle.upper())
        below = y - 26
    return below - 20


# --------------------------------------------------------------------------
# Page renderers (one per content "type")
# --------------------------------------------------------------------------
def render_cover(c, brand, ctx, p, logo):
    # bold header block
    if logo is not None:
        _place_logo(c, logo, PAGE_W / 2, PAGE_H - 128, max_w=240, max_h=108,
                    align="center")
    block_top = PAGE_H - 142
    block_h = 90
    c.setFillColorRGB(*brand.primary)
    c.rect(0, block_top - block_h, PAGE_W, block_h, stroke=0, fill=1)
    c.setFillColorRGB(*brand.accent)
    c.rect(0, block_top - block_h - 7, PAGE_W, 7, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(FONT_B, 39)
    c.drawCentredString(PAGE_W / 2, block_top - block_h / 2 - 11, p["title"])

    # welcome letter — single flowing column, vertically centered in the
    # space below the header so the whitespace balances top and bottom
    x = BODY_L + 10
    w = BODY_W - 20
    size, leading = 12, 19
    para_gap = leading * 0.72
    # start at a fixed, clear gap below the header's gold stripe
    header_gap = 42
    y = (block_top - block_h - 7) - header_gap

    for pi, para in enumerate(p["letter"]):
        font = FONT_B if pi == 0 else FONT
        y = draw_paragraph(c, para, x, y, w, size=size, leading=leading,
                           font=font, color=brand.ink)
        y -= para_gap

    # signature block
    y -= 10
    c.setStrokeColorRGB(*brand.primary)
    c.setLineWidth(3)
    c.line(x, y + 18, x + 70, y + 18)
    c.setFillColorRGB(*brand.muted)
    c.setFont(FONT_I, 11)
    c.drawString(x, y, p["signoff"])
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 14)
    c.drawString(x, y - 20, p["signoff_team"])


def render_splash(c, brand, ctx, p, logo):
    if logo is not None:
        _place_logo(c, logo, PAGE_W / 2, PAGE_H - 122, max_w=200, max_h=92,
                    align="center")
    cxm = PAGE_W / 2
    # huge headline
    c.setFillColorRGB(*brand.ink)
    hy = PAGE_H - 178
    for line in _wrap(p["headline"].upper(), FONT_B, 37, PAGE_W - 96):
        c.setFont(FONT_B, 37)
        c.drawCentredString(cxm, hy, line)
        hy -= 43
    # kicker (plain maroon, no highlight)
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 12.5)
    c.drawCentredString(cxm, hy - 8, p["kicker"].upper())
    ky = hy - 8
    c.setStrokeColorRGB(*brand.accent)
    c.setLineWidth(2.5)
    c.line(cxm - 55, ky - 12, cxm + 55, ky - 12)

    # pin
    y = ky - 30
    pin = p.get("pin_image")
    if pin and Path(pin).exists():
        _place_logo(c, ImageReader(str(pin)), cxm, y - 120, max_w=196,
                    max_h=124, align="center")
        y -= 144

    # HUGE stat numbers — number, gold bar, and label all vertically centered
    y -= 4
    card_h = 92
    numx, barx, labx = 80, 238, 258
    for s in p["stats"]:
        rc = y - card_h / 2                       # row center
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 58)
        c.drawString(numx, rc - 20, s["big"])
        lines = _wrap(s["label"], FONT_B, 13.5, PAGE_W - labx - 56)
        # bar height matches the label block; both centered on the row center
        half = max(24, (len(lines) - 1) * 9 + 12)
        c.setStrokeColorRGB(*brand.accent)
        c.setLineWidth(2)
        c.line(barx, rc - half, barx, rc + half)
        ly = rc + (len(lines) - 1) * 9 - 3     # first baseline (block centered)
        c.setFillColorRGB(*brand.ink)
        c.setFont(FONT_B, 13.5)
        for line in lines:
            c.drawString(labx, ly, line)
            ly -= 18
        y -= card_h
    draw_paragraph(c, p["closer"], 80, y - 6, PAGE_W - 160, size=12.5,
                   leading=18, font=FONT_B, color=brand.muted, align="center")


def render_schedule(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, "SCHEDULE")

    # weekly calendar — day columns with colored Office / Field session blocks
    t = p["week_table"]
    days = t["days"]
    office = t["rows"][0][1:]
    field = t["rows"][1][1:]
    n = len(days)
    label_w = 78
    colw = (BODY_W - label_w) / n
    top = y - 6
    hh = 30
    rh = 66
    gridx = BODY_L + label_w
    lt_gold = _mix(brand.accent, (1, 1, 1), 0.82)     # very light gold tint
    lt_red = _mix(brand.primary, (1, 1, 1), 0.90)     # whisper of maroon

    def _sched_icon(c, color, kind, cx, cy, s=13):
        c.saveState()
        c.setStrokeColorRGB(*color)
        c.setFillColorRGB(*color)
        c.setLineWidth(1.2)
        c.setLineCap(1)
        c.setLineJoin(1)
        r = s / 2
        if kind == "office":                       # building + windows
            c.rect(cx - r * 0.85, cy - r, r * 1.7, r * 1.95, stroke=1, fill=0)
            for wx in (-0.38, 0.38):
                for wy in (0.42, -0.15):
                    c.rect(cx + wx * r - 1.4, cy + wy * r - 1.4, 2.8, 2.8,
                           stroke=0, fill=1)
        elif kind == "calendar":                   # calendar grid
            c.rect(cx - r * 0.9, cy - r * 0.85, r * 1.8, r * 1.6, stroke=1,
                   fill=0)
            c.line(cx - r * 0.9, cy + r * 0.35, cx + r * 0.9, cy + r * 0.35)
            c.line(cx - r * 0.45, cy + r * 0.75, cx - r * 0.45, cy + r * 0.55)
            c.line(cx + r * 0.45, cy + r * 0.75, cx + r * 0.45, cy + r * 0.55)
            for dx in (-0.45, 0.15):
                c.rect(cx + dx * r, cy - r * 0.35, 2.4, 2.4, stroke=0, fill=1)
        elif kind == "dollar":                     # coin with $
            c.circle(cx, cy, r * 0.92, stroke=1, fill=0)
            c.setFont(FONT_B, s * 0.9)
            c.drawCentredString(cx, cy - s * 0.32, "$")
        else:                                      # house / doors
            path = c.beginPath()
            path.moveTo(cx - r, cy + r * 0.15)
            path.lineTo(cx, cy + r)
            path.lineTo(cx + r, cy + r * 0.15)
            c.drawPath(path, stroke=1, fill=0)
            c.rect(cx - r * 0.72, cy - r, r * 1.44, r * 1.2, stroke=1, fill=0)
            c.rect(cx - r * 0.2, cy - r, r * 0.4, r * 0.62, stroke=0, fill=1)
        c.restoreState()

    body_top = top - hh
    grid_bot = body_top - 2 * rh
    # a column is a full "rest day" only when BOTH office and field are OFF
    both_off = [str(office[i]).upper() == "OFF" and
                str(field[i]).upper() == "OFF" for i in range(n)]

    # alternating day-column tint for rhythm (rest-day columns get their own)
    for i in range(n):
        if both_off[i]:
            continue
        if i % 2 == 1:
            c.setFillColorRGB(*brand.cream)
            c.rect(gridx + i * colw, grid_bot, colw, 2 * rh, stroke=0, fill=1)

    # header row (maroon) with a small calendar mark in the corner cell
    c.setFillColorRGB(*brand.dark)
    c.rect(BODY_L, top - hh, label_w, hh, stroke=0, fill=1)
    c.setFillColorRGB(*brand.accent)
    c.setFont(FONT_B, 8)
    c.drawCentredString(BODY_L + label_w / 2, top - hh / 2 - 3, "WEEK")
    c.setFillColorRGB(*brand.primary)
    c.rect(gridx, top - hh, BODY_W - label_w, hh, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    for i, d in enumerate(days):
        c.setFont(FONT_B, 9.5)
        c.drawCentredString(gridx + i * colw + colw / 2, top - hh / 2 - 3, d)

    # Office (gold) / Field (maroon) label cells with icons
    rows = (("Office", office, brand.accent, brand.ink, "office"),
            ("Field", field, brand.primary, (1, 1, 1), "house"))
    for ri, (lab, times, fill, tcol, ikind) in enumerate(rows):
        ry = body_top - ri * rh
        c.setFillColorRGB(*fill)
        c.rect(BODY_L, ry - rh, label_w, rh, stroke=0, fill=1)
        _sched_icon(c, tcol, ikind, BODY_L + label_w / 2, ry - rh / 2 + 10)
        c.setFillColorRGB(*tcol)
        c.setFont(FONT_B, 12)
        c.drawCentredString(BODY_L + label_w / 2, ry - rh / 2 - 15, lab)
        for i, tm in enumerate(times):
            cx = gridx + i * colw
            if str(tm).upper() == "OFF":
                if not both_off[i]:            # single-row off → small "OFF"
                    c.setFillColorRGB(*brand.muted)
                    c.setFont(FONT_B, 9)
                    c.drawCentredString(cx + colw / 2, ry - rh / 2 - 2.5,
                                        "OFF")
                continue
            c.setFillColorRGB(*brand.ink)
            fsz = 8.6
            # split start/end at the dash so times never break mid-clock
            dash = "–" if "–" in tm else (" - " if " - " in tm else
                                          ("-" if "-" in tm else None))
            if stringWidth(tm, FONT_B, fsz) <= colw - 6:
                tlines = [tm]
            elif dash:
                a, b = tm.split(dash, 1)
                tlines = [a.strip() + " –", b.strip()]
            else:
                tlines = _wrap(tm, FONT_B, fsz, colw - 6)
            c.setFont(FONT_B, fsz)
            tyv = ry - rh / 2 + (len(tlines) - 1) * 11.5 / 2 - 2.5
            for ln in tlines:
                c.drawCentredString(cx + colw / 2, tyv, ln)
                tyv -= 11.5

    # rest-day columns (both rows off) — soft maroon tint + "OFF / rest day"
    for i in range(n):
        if not both_off[i]:
            continue
        sx = gridx + i * colw
        c.setFillColorRGB(*lt_red)
        c.rect(sx, grid_bot, colw, 2 * rh, stroke=0, fill=1)
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 12)
        c.drawCentredString(sx + colw / 2, body_top - rh + 2, "OFF")
        c.setFillColorRGB(*brand.muted)
        c.setFont(FONT_I, 7.5)
        c.drawCentredString(sx + colw / 2, body_top - rh - 12, "rest day")

    # thin grid
    c.setStrokeColorRGB(*brand.muted)
    c.setLineWidth(0.5)
    c.rect(BODY_L, grid_bot, BODY_W, top - grid_bot, stroke=1, fill=0)
    c.line(BODY_L, body_top, BODY_R, body_top)      # under the day headers
    # mid divider (office / field) — skip columns that are a merged rest day
    c.line(BODY_L, body_top - rh, gridx, body_top - rh)   # label cell
    for i in range(n):
        if both_off[i]:
            continue
        x0 = gridx + i * colw
        c.line(x0, body_top - rh, x0 + colw, body_top - rh)
    for i in range(n + 1):
        c.line(gridx + i * colw, grid_bot, gridx + i * colw, top)
    # two full-width info panels (colored header + icon) filling the page
    blocks = p["blocks"]
    y = grid_bot - 28
    bottom = 72
    gutp = 16
    ph = (y - bottom - gutp * (len(blocks) - 1)) / len(blocks)
    hdr_h = 30
    hdr_colors = [brand.primary, brand.dark]
    icons = ["calendar", "dollar"]
    tints = [_mix(brand.primary, (1, 1, 1), 0.93),
             _mix(brand.dark, (1, 1, 1), 0.94)]
    for bi, blk in enumerate(blocks):
        pt = y - bi * (ph + gutp)
        col = hdr_colors[bi % len(hdr_colors)]
        c.setFillColorRGB(*tints[bi % len(tints)])
        c.rect(BODY_L, pt - ph, BODY_W, ph, stroke=0, fill=1)
        c.setFillColorRGB(*col)
        c.rect(BODY_L, pt - hdr_h, BODY_W, hdr_h, stroke=0, fill=1)
        _sched_icon(c, (1, 1, 1), icons[bi % len(icons)], BODY_L + 20,
                    pt - hdr_h / 2, s=15)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 13)
        c.drawString(BODY_L + 40, pt - hdr_h / 2 - 4.5, blk["heading"])
        # measure body, then vertically center it in the panel body area.
        # draw_paragraph places the BASELINE, so compensate with the cap height
        bsz, blead = 13.5, 21
        cap = bsz * 0.72
        # body_bullets: render each body line as a bullet, and the "bullets"
        # list as indented sub-bullets under it
        body_bul = blk.get("body_bullets")
        body_w = BODY_W - 60 if body_bul else BODY_W - 40
        bh = 0
        for line in blk["body"]:
            bh += len(_wrap(line, FONT, bsz, body_w)) * blead + 7
        sub_w = BODY_W - 76 if body_bul else BODY_W - 60
        for b in blk["bullets"]:
            bh += len(_wrap(b, FONT, bsz, sub_w)) * blead + 6
        yy = _vcenter(pt - hdr_h, ph - hdr_h, bh, bsz, min_gap=12,
                      lead=blead)
        for line in blk["body"]:
            if body_bul:
                c.setFillColorRGB(*brand.accent)
                c.setFont(FONT_B, bsz)
                c.drawString(BODY_L + 26, yy, "•")
                yy = draw_paragraph(c, line, BODY_L + 42, yy, body_w,
                                    size=bsz, leading=blead, color=brand.ink)
            else:
                yy = draw_paragraph(c, line, BODY_L + 20, yy, body_w,
                                    size=bsz, leading=blead, color=brand.ink)
            yy -= 7
        for b in blk["bullets"]:
            c.setFillColorRGB(*brand.accent)
            c.setFont(FONT_B, bsz)
            bx = BODY_L + (42 if body_bul else 26)
            c.drawString(bx, yy, "–" if body_bul else "•")
            yy = draw_paragraph(c, b, bx + 16, yy, sub_w, size=bsz,
                                leading=blead, color=brand.ink)
            yy -= 6
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.5)
        c.rect(BODY_L, pt - ph, BODY_W, ph, stroke=1, fill=0)


def render_concept(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"])
    if p.get("intro"):
        c.setFillColorRGB(*brand.muted)
        c.setFont(FONT_I, 11)
        c.drawString(BODY_L, y, p["intro"])
        y -= 20

    # pre-measure the definitions + "Good to know" panel so the image can be
    # capped to leave room — never overlapping the footer
    pad = 14
    defs_h = 0
    for term, definition in p["terms"]:
        tw = stringWidth(term, FONT_B, 10.5)
        nl = len(_wrap("— " + definition, FONT, 9.5, BODY_W - 14 - tw - 8))
        defs_h += max(nl * 12.5, 13) + 9
    lines_h = 0
    for note in p["notes"]:
        lines_h += len(_wrap(note, FONT, 10.5, BODY_W - 2 * pad - 12)) * 14 + 6
    panel_h = lines_h + 40

    # example image — as large as fits (height-capped, centered)
    footer_margin = 76
    panel_top = footer_margin + panel_h            # anchor panel at the bottom
    img_path = p.get("image")
    if img_path and Path(img_path).exists():
        img = ImageReader(str(img_path))
        iw, ih = img.getSize()
        avail_img = y - 44 - defs_h - panel_h - footer_margin
        natural_h = (PAGE_W - 2 * MARGIN) * ih / iw
        h = min(natural_h, max(150, avail_img))
        w = h * iw / ih
        ix = (PAGE_W - w) / 2
        c.drawImage(img, ix, y - h, w, h, mask="auto",
                    preserveAspectRatio=True)
        c.setStrokeColorRGB(*brand.accent)
        c.setLineWidth(0.8)
        c.rect(ix, y - h, w, h, stroke=1, fill=0)
        # center the definitions block between the image and the panel
        img_bottom = y - h
        gap = max(14, (img_bottom - panel_top - defs_h) / 2)
        y = img_bottom - gap - 8

    # plain-English definitions (gold tick aligned to the text cap-height)
    for term, definition in p["terms"]:
        c.setFillColorRGB(*brand.accent)
        c.rect(BODY_L, y - 1, 5, 10, stroke=0, fill=1)
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 10.5)
        c.drawString(BODY_L + 14, y, term)
        tw = stringWidth(term, FONT_B, 10.5)
        end_y = draw_paragraph(c, "— " + definition,
                               BODY_L + 14 + tw + 8, y,
                               BODY_W - 14 - tw - 8, size=9.5,
                               leading=12.5, color=brand.ink)
        y = min(end_y, y - 13) - 9

    # "Good to know" panel — anchored at the bottom (even gap above/below defs)
    y = panel_top
    c.setFillColorRGB(*brand.cream)
    c.roundRect(BODY_L, y - panel_h, BODY_W, panel_h, 8, stroke=0, fill=1)
    c.setFillColorRGB(*brand.primary)
    c.rect(BODY_L, y - panel_h, 5, panel_h, stroke=0, fill=1)
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 9)
    c.drawString(BODY_L + pad, y - 18, "GOOD TO KNOW")
    ny = y - 36
    for note in p["notes"]:
        c.setFillColorRGB(*brand.accent)
        c.setFont(FONT_B, 11)
        c.drawString(BODY_L + pad, ny, "•")
        ny = draw_paragraph(c, note, BODY_L + pad + 12, ny,
                            BODY_W - 2 * pad - 12, size=10.5, leading=14,
                            color=brand.ink)
        ny -= 6


def _draw_checklist_items(c, brand, items, x, y, width, size=9.5,
                          gap=6, box=9):
    for it in items:
        # center the box on the first text line's cap height
        checkbox(c, x, y + size * 0.34 - box / 2, brand, size=box)
        end_y = draw_paragraph(c, it, x + box + 8, y, width - box - 8,
                               size=size, leading=size * 1.25, color=brand.ink)
        y = end_y - gap
    return y


def _promo_row(c, brand, text, x, y, width, size=8.7, box=8.5, bold=False):
    checkbox(c, x, y - 1, brand, size=box)
    font = FONT_B if bold else FONT
    end_y = draw_paragraph(c, text, x + box + 8, y, width - box - 8,
                           size=size, leading=size * 1.3, font=font,
                           color=brand.ink)
    return end_y - 6


def render_promotion(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    for lvl in p["levels"]:
        # level header (primary tab + primary text + hairline — no fill bar)
        c.setFillColorRGB(*brand.primary)
        c.rect(BODY_L, y - 3, 5, 13, stroke=0, fill=1)
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 11)
        c.drawString(BODY_L + 13, y, lvl["name"])
        c.setStrokeColorRGB(*brand.accent)
        c.setLineWidth(0.8)
        c.line(BODY_L, y - 7, BODY_R, y - 7)
        y -= 19
        for it in lvl["items"]:
            if isinstance(it, dict):
                y = _promo_row(c, brand, it["head"], BODY_L + 6, y,
                               BODY_W - 12, bold=True)
                for sub in it["sub"]:
                    y = _promo_row(c, brand, sub, BODY_L + 28, y, BODY_W - 34)
            else:
                y = _promo_row(c, brand, it, BODY_L + 6, y, BODY_W - 12)
        y -= 7


def render_checklist(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"])
    # single column, larger type, spacing distributed to fill the page
    items = p["items"]
    box = 12
    bottom = 96
    step = (y - bottom) / len(items)
    yy = y
    for it in items:
        checkbox(c, BODY_L, yy - 2, brand, size=box)
        draw_paragraph(c, it, BODY_L + box + 12, yy, BODY_W - box - 12,
                       size=13, leading=16, color=brand.ink)
        yy -= step


def _split_book(s):
    for sep in (" by ", " – ", " — ", " - "):
        if sep in s:
            t, a = s.split(sep, 1)
            return t.strip(), a.strip()
    return s.strip(), ""


# spine colours matched to the real book covers (bg, text)
BOOK_COLORS = {
    "10x": ("#F2C200", "#141414"),                 # yellow
    "be obsessed": ("#C6D9EA", "#C0202E"),         # sky blue / red
    "extreme ownership": ("#141414", "#FFFFFF"),   # black
    "millionaire": ("#333F4E", "#FFFFFF"),         # navy
    "sell or be sold": ("#D42030", "#FFFFFF"),     # red
    "slight edge": ("#F1F4F8", "#1C3A5E"),         # white / navy text
    "can't hurt me": ("#0E0E0E", "#C79A3E"),       # black / gold text
    "bringing out the best": ("#24406A", "#FFFFFF"),  # navy
    "win friends": ("#F0EEE9", "#C8202E"),         # white / red text
    "skills with people": ("#3B2C6B", "#FFFFFF"),  # purple
    "talk to yourself": ("#F2F0EC", "#C8202E"),    # white / red text
    "raised myself": ("#F5D000", "#141414"),       # yellow
    "irrefutable laws": ("#BE1622", "#FFFFFF"),    # red
    "crucial conversations": ("#EE4A2B", "#FFFFFF"),  # red-orange
    "positive team": ("#1C4E8A", "#FFFFFF"),       # blue
}


def _book_color(title, fallback):
    t = title.lower()
    for key, (bg, tx) in BOOK_COLORS.items():
        if key in t:
            return _hex(bg), _hex(tx)
    return fallback


def _spine(c, brand, x, base_y, w, h, title, author, fill, txt):
    c.setFillColorRGB(*fill)
    c.rect(x, base_y, w, h, stroke=0, fill=1)
    if sum(fill) / 3 > 0.72:                     # outline light spines
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.8)
        c.rect(x, base_y, w, h, stroke=1, fill=0)
    # rotated title up the spine — bigger, wrapping long titles to 2 lines
    avail = h - 26
    tu = title.upper()
    if stringWidth(tu, FONT_B, 9) > avail:
        words = tu.split()
        cut = max(1, round(len(words) / 2))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
        size = 10
        while size > 6.5 and max(stringWidth(ln, FONT_B, size)
                                 for ln in lines) > avail:
            size -= 0.5
    else:
        size = 13
        while size > 8 and stringWidth(tu, FONT_B, size) > avail:
            size -= 0.5
        lines = [tu]
    nlines = len(lines)
    # author sits directly beside the title (its own spine column), larger
    asize = 8.0 if author else 0
    au = author.upper() if author else ""
    while author and asize > 5.5 and stringWidth(au, FONT_B, asize) > avail:
        asize -= 0.5
    total_cols = nlines + (1 if author else 0)
    # title + author group centered on the spine
    base_col = x + w / 2 - (total_cols - 1) * (size + 1) / 2 + 1
    c.setFillColorRGB(*txt)
    c.setFont(FONT_B, size)
    for li, line in enumerate(lines):
        c.saveState()
        c.translate(base_col + li * (size + 1) + size / 2 - 1, base_y + 13)
        c.rotate(90)
        c.drawString(0, 0, line)
        c.restoreState()
    if author:
        c.saveState()
        c.translate(base_col + nlines * (size + 1) + size / 2 - 1,
                    base_y + 13)
        c.rotate(90)
        c.setFillColorRGB(*txt)
        c.setFont(FONT_B, asize)
        c.drawString(0, 0, au)
        c.restoreState()


def render_bookshelf(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    # stacked title (logo sits top-right via header_logo)
    c.setFillColorRGB(*brand.muted)
    c.setFont(FONT_B, 11)
    c.drawString(BODY_L, PAGE_H - 74, p["kicker"].upper())
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 40)
    c.drawString(BODY_L, PAGE_H - 116, p["title"].upper())
    c.setStrokeColorRGB(*brand.accent)
    c.setLineWidth(2)
    c.line(BODY_L, PAGE_H - 126, BODY_R, PAGE_H - 126)
    y = PAGE_H - 150
    if p.get("intro"):
        y = draw_paragraph(c, p["intro"], BODY_L, y, BODY_W, size=10.5,
                           leading=15, color=brand.ink)
    y -= 24

    books = [_split_book(it) for it in p["items"]]
    palette = [(brand.primary, (1, 1, 1)), (brand.accent, brand.ink),
               (brand.dark, (1, 1, 1)), (brand.cream, brand.ink),
               (brand.muted, (1, 1, 1))]
    heights = [188, 168, 200, 176, 158, 192, 172]
    mid = (len(books) + 1) // 2
    shelves = [books[:mid], books[mid:]]
    shelf_top = y
    tallest = max(heights)
    ns = len(shelves)
    # top shelf near the title, last shelf near the bottom, evenly spread
    top_base = shelf_top - tallest
    bottom_base = 94
    bases = [top_base - i * (top_base - bottom_base) / (ns - 1)
             for i in range(ns)] if ns > 1 else [top_base]
    for si, shelf in enumerate(shelves):
        base = bases[si]
        n = len(shelf)
        gap = 3
        sw = (BODY_W - gap * (n - 1)) / n
        x = BODY_L
        for bi, (title, author) in enumerate(shelf):
            fb = palette[(si * mid + bi) % len(palette)]
            fill, txt = _book_color(title, fb)
            h = heights[(si * 3 + bi) % len(heights)]
            _spine(c, brand, x, base, sw, h, title, author, fill, txt)
            x += sw + gap
        # shelf board
        c.setFillColorRGB(*brand.accent)
        c.rect(BODY_L - 4, base - 7, BODY_W + 8, 7, stroke=0, fill=1)


def _runs_wrap(runs, width):
    """Wrap a list of (text, font, size, color) runs into lines. Returns a list
    of lines, each a list of (word, font, size, color) tokens."""
    lines, cur, curw = [], [], 0
    for text, font, size, color in runs:
        for w in text.split():
            ww = stringWidth(w, font, size)
            sp = stringWidth(" ", font, size) if cur else 0
            if cur and curw + sp + ww > width:
                lines.append(cur)
                cur, curw = [], 0
                sp = 0
            cur.append((w, font, size, color))
            curw += sp + ww
    if cur:
        lines.append(cur)
    return lines


def _draw_runs(c, lines, x, y, lead):
    for ln in lines:
        cx = x
        for w, font, size, color in ln:
            c.setFillColorRGB(*color)
            c.setFont(font, size)
            c.drawString(cx, y, w)
            cx += stringWidth(w + " ", font, size)
        y -= lead
    return y


def render_booklist(c, brand, ctx, p, logo):
    """Plain two-column alphabetical reading list: gold tick + bold title +
    muted author, auto-fit to fill the page."""
    sidebar(c, brand, p.get("sidebar"))
    if p.get("kicker"):
        c.setFillColorRGB(*brand.muted)
        c.setFont(FONT_B, 11)
        c.drawString(BODY_L, PAGE_H - 74, p["kicker"].upper())
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 40)
    c.drawString(BODY_L, PAGE_H - 116, p["title"].upper())
    c.setStrokeColorRGB(*brand.accent)
    c.setLineWidth(2)
    c.line(BODY_L, PAGE_H - 126, BODY_R, PAGE_H - 126)
    y = PAGE_H - 148
    if p.get("intro"):
        y = draw_paragraph(c, p["intro"], BODY_L, y, BODY_W, size=10.5,
                           leading=15, color=brand.ink)
    y -= 16

    books = p["books"]
    gut = 26
    colw = (BODY_W - gut) / 2
    tickw = 14
    txtw = colw - tickw
    bottom = 54
    avail = y - bottom

    def runs_for(t, a, size):
        return [(t + "  —", FONT_B, size, brand.ink),
                (a, FONT, size, brand.muted)]

    def balanced_split(size):
        """Split so the two columns are as close to equal height as possible,
        keeping column 1 >= column 2 and alphabetical order intact."""
        lead = size * 1.3
        gap = size * 0.85
        hs = [len(_runs_wrap(runs_for(t, a, size), txtw)) * lead + gap
              for t, a in books]
        total = sum(hs)
        run, i = 0, 0
        while i < len(hs) and run + hs[i] <= total / 2:
            run += hs[i]
            i += 1
        i = max(1, i)
        return i, max(run, total - run)

    # largest font where the taller (balanced) column fits
    size = 11
    while size > 7.5:
        _, taller = balanced_split(size)
        if taller <= avail:
            break
        size -= 0.25
    mid, _ = balanced_split(size)
    cols = [books[:mid], books[mid:]]
    gap = size * 0.85
    lead = size * 1.3
    for ci, col in enumerate(cols):
        x = BODY_L + ci * (colw + gut)
        yy = y
        for t, a in col:
            c.setFillColorRGB(*brand.accent)
            c.setFont(FONT_B, size + 1)
            c.drawString(x, yy, "▪")
            lines = _runs_wrap(runs_for(t, a, size), txtw)
            yy = _draw_runs(c, lines, x + tickw, yy, lead)
            yy -= gap


def render_media(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"])
    # one combined grid — big cover + name + QR, 2 columns, filling the page
    items = [it for sec in p["sections"] for it in sec["items"]]
    gut = 18
    cw = (BODY_W - gut) / 2
    rows = (len(items) + 1) // 2
    grid_bottom = 108
    ch = (y - grid_bottom - gut * (rows - 1)) / rows
    art = 92
    qr = 66
    pad = 16
    for i, (title, url, cover) in enumerate(items):
        cx = BODY_L + (i % 2) * (cw + gut)
        cyt = y - (i // 2) * (ch + gut)
        c.setStrokeColorRGB(*brand.accent)
        c.setLineWidth(1)
        c.roundRect(cx, cyt - ch, cw, ch, 8, stroke=1, fill=0)
        # cover art left + QR right on the top row
        top = cyt - pad - art
        if cover and Path(cover).exists():
            c.drawImage(ImageReader(cover), cx + pad, top, art, art,
                        mask="auto")
        if url:
            c.drawImage(qr_image(url), cx + cw - pad - qr,
                        top + (art - qr) / 2, qr, qr, mask="auto")
        # name + host centered in the space between the art and card bottom
        sep = "—" if "—" in title else "–"
        name, _, host = title.partition(sep)
        name, host = name.strip(), host.strip()
        name_lines = _wrap(name, FONT_B, 12, cw - 2 * pad)
        block_h = len(name_lines) * 15 + (14 if host else 0)
        art_bottom = top
        card_bottom = cyt - ch
        ty = (art_bottom + card_bottom) / 2 + block_h / 2 - 6
        c.setFillColorRGB(*brand.ink)
        for wl in name_lines:
            c.setFont(FONT_B, 12)
            c.drawCentredString(cx + cw / 2, ty, wl)
            ty -= 15
        if host:
            c.setFillColorRGB(*brand.muted)
            c.setFont(FONT_I, 10)
            c.drawCentredString(cx + cw / 2, ty - 1, host)
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 18)
    # centered in the gap between the card grid and the footer
    c.drawCentredString((BODY_L + BODY_R) / 2, (grid_bottom + 46) / 2 - 6,
                        p.get("footnote", ""))


def _core_icon(c, color, i, ix, iy, s=11):
    """Small monoline icon for each of the 9 Core Steps (drawn centered at
    ix, iy). Purely decorative — brand-colored, print-light line art."""
    c.saveState()
    c.setStrokeColorRGB(*color)
    c.setFillColorRGB(*color)
    c.setLineWidth(1.3)
    c.setLineCap(1)
    c.setLineJoin(1)
    r = s / 2
    if i == 0:            # networking — two people
        c.circle(ix - r * 0.55, iy + r * 0.15, r * 0.34, stroke=1, fill=0)
        c.circle(ix + r * 0.55, iy + r * 0.15, r * 0.34, stroke=1, fill=0)
        c.arc(ix - r, iy - r, ix, iy - r * 0.1, startAng=20, extent=140)
        c.arc(ix, iy - r, ix + r, iy - r * 0.1, startAng=20, extent=140)
    elif i == 1:          # personal sales — up arrow
        c.line(ix, iy - r, ix, iy + r)
        c.line(ix, iy + r, ix - r * 0.55, iy + r * 0.35)
        c.line(ix, iy + r, ix + r * 0.55, iy + r * 0.35)
    elif i == 2:          # reading — open book
        c.line(ix, iy - r * 0.7, ix, iy + r * 0.7)
        c.lines([(ix, iy + r * 0.6, ix - r, iy + r * 0.3),
                 (ix - r, iy + r * 0.3, ix - r, iy - r * 0.6),
                 (ix - r, iy - r * 0.6, ix, iy - r * 0.35),
                 (ix, iy + r * 0.6, ix + r, iy + r * 0.3),
                 (ix + r, iy + r * 0.3, ix + r, iy - r * 0.6),
                 (ix + r, iy - r * 0.6, ix, iy - r * 0.35)])
    elif i == 3:          # listening — headphones
        c.arc(ix - r * 0.85, iy - r * 0.2, ix + r * 0.85, iy + r * 1.2,
              startAng=20, extent=140)
        c.roundRect(ix - r * 0.95, iy - r * 0.55, r * 0.5, r * 0.8, 1.2,
                    stroke=0, fill=1)
        c.roundRect(ix + r * 0.45, iy - r * 0.55, r * 0.5, r * 0.8, 1.2,
                    stroke=0, fill=1)
    elif i == 4:          # association — connected cluster
        pts = [(ix, iy + r * 0.75), (ix - r * 0.8, iy - r * 0.5),
               (ix + r * 0.8, iy - r * 0.5)]
        for a in range(3):
            for b in range(a + 1, 3):
                c.line(*pts[a], *pts[b])
        for px, py in pts:
            c.circle(px, py, r * 0.28, stroke=0, fill=1)
    elif i == 5:          # accountability — check
        c.lines([(ix - r * 0.7, iy, ix - r * 0.15, iy - r * 0.55),
                 (ix - r * 0.15, iy - r * 0.55, ix + r * 0.8, iy + r * 0.6)])
    elif i == 6:          # mentorship — star
        import math
        path = c.beginPath()
        for k in range(10):
            rad = r if k % 2 == 0 else r * 0.42
            ang = math.pi / 2 + k * math.pi / 5
            xx = ix + rad * math.cos(ang)
            yy = iy + rad * math.sin(ang)
            (path.moveTo if k == 0 else path.lineTo)(xx, yy)
        path.close()
        c.drawPath(path, stroke=0, fill=1)
    elif i == 7:          # communication — speech bubble
        c.roundRect(ix - r, iy - r * 0.35, 2 * r, r * 1.25, 2, stroke=1,
                    fill=0)
        c.lines([(ix - r * 0.35, iy - r * 0.35, ix - r * 0.55, iy - r),
                 (ix - r * 0.55, iy - r, ix + r * 0.05, iy - r * 0.35)])
    else:                 # dress professional — tie
        c.lines([(ix - r * 0.5, iy + r, ix, iy + r * 0.5),
                 (ix, iy + r * 0.5, ix + r * 0.5, iy + r)])
        path = c.beginPath()
        path.moveTo(ix, iy + r * 0.5)
        path.lineTo(ix - r * 0.4, iy - r * 0.35)
        path.lineTo(ix, iy - r)
        path.lineTo(ix + r * 0.4, iy - r * 0.35)
        path.close()
        c.drawPath(path, stroke=0, fill=1)
    c.restoreState()


def render_framework(c, brand, ctx, p, logo):
    """Each Core Step is a card: colored header strip (number + icon + title)
    over a bordered bullet body. Uniform card size, clean aligned 2-column
    grid, spread to fill, with a footer note band."""
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    steps = p["steps"]
    gut = 15
    cw = (BODY_W - gut) / 2
    hdr_h = 26
    tsize = 9
    tlead = tsize * 1.42
    foot_h = 42
    bottom = 70 + foot_h + 8
    band = [brand.primary, brand.accent, brand.dark]

    def _draw_card(i, x, w, top, ch, tsize, tlead):
        name, bullets = steps[i]
        num, _, title = name.partition(". ")
        hdr = band[i % 3]
        tcol = brand.ink if (i % 3 == 1) else (1, 1, 1)
        c.setFillColorRGB(*hdr)
        c.rect(x, top - hdr_h, w, hdr_h, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.circle(x + 15, top - hdr_h / 2, 8.5, stroke=0, fill=1)
        c.setFillColorRGB(*hdr)
        c.setFont(FONT_B, 9.5)
        c.drawCentredString(x + 15, top - hdr_h / 2 - 3.3, num)
        c.setFillColorRGB(*tcol)
        tf = 10.5
        while tf > 7.5 and stringWidth(title, FONT_B, tf) > w - 48:
            tf -= 0.5
        c.setFont(FONT_B, tf)
        c.drawString(x + 29, top - hdr_h / 2 - 3.3, title)
        _core_icon(c, tcol, i, x + w - 14, top - hdr_h / 2, s=12)
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.7)
        c.rect(x, top - ch, w, ch - hdr_h, stroke=1, fill=0)
        # vertically center the bullets in the card body
        bh = _bullet_block_h(bullets, w - 22, tsize, lead=tlead,
                             bold_parent=False)
        y0 = _vcenter(top - hdr_h, ch - hdr_h, bh, tsize, lead=tlead)
        _bullet_block(c, brand, bullets, x + 11, y0, w - 22,
                      size=tsize, lead=tlead, bold_parent=False)

    def _draw_finale(i, top, ch):
        """The lone last step — light full-width closer with maroon accents."""
        name, bullets = steps[i]
        num, _, title = name.partition(". ")
        tagline = bullets[0] if bullets else ""
        cyc = top - ch / 2
        # soft cream card with a maroon left accent bar
        c.setFillColorRGB(*brand.cream)
        c.roundRect(BODY_L, top - ch, BODY_W, ch, 8, stroke=0, fill=1)
        c.setFillColorRGB(*brand.primary)
        c.roundRect(BODY_L, top - ch, 6, ch, 3, stroke=0, fill=1)
        c.rect(BODY_L + 3, top - ch, 3, ch, stroke=0, fill=1)
        # maroon number disc
        c.setFillColorRGB(*brand.primary)
        c.circle(BODY_L + 40, cyc, 18, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 19)
        c.drawCentredString(BODY_L + 40, cyc - 7, num)
        # title + playful tagline
        tx = BODY_L + 74
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 17)
        c.drawString(tx, cyc + 4, title.upper())
        c.setFillColorRGB(*brand.ink)
        c.setFont(FONT_I, 12)
        c.drawString(tx, cyc - 15, tagline)
        # oversized gold tie icon on the right
        _core_icon(c, brand.accent, 8, BODY_R - 34, cyc, s=36)

    # per-row heights (each row sized to its taller card); pick the largest
    # font where all rows + the finale still fit the page
    n = len(steps)
    nrows = (n + 1) // 2
    avail = y - bottom
    fin_h = 56

    def _row_heights(ts):
        tl = ts * 1.42
        rhs = []
        for r in range(nrows):
            idxs = [i for i in (r * 2, r * 2 + 1) if i < n]
            if len(idxs) == 1:                 # finale row
                rhs.append(fin_h)
            else:
                bh = max(_bullet_block_h(steps[i][1], cw - 22, ts, lead=tl,
                                         bold_parent=False) for i in idxs)
                rhs.append(hdr_h + bh + 14)
        return rhs

    tsize = 9.5
    while tsize > 7:
        rhs = _row_heights(tsize)
        if sum(rhs) + 8 * (nrows - 1) <= avail:
            break
        tsize -= 0.25
    tlead = tsize * 1.42
    rhs = _row_heights(tsize)
    gap = max(8, min((avail - sum(rhs)) / (nrows - 1), 20)) if nrows > 1 else 8
    cyt = y - max(0, (avail - sum(rhs) - gap * (nrows - 1)) / 2)
    for r in range(nrows):
        ch = rhs[r]
        row = [i for i in (r * 2, r * 2 + 1) if i < n]
        if len(row) == 1:                     # lone last step → fun banner
            _draw_finale(row[0], cyt, ch)
        else:
            for cidx, i in enumerate(row):
                _draw_card(i, BODY_L + cidx * (cw + gut), cw, cyt, ch,
                           tsize, tlead)
        cyt -= ch + gap

    # footer note band
    band_y = 70
    c.setFillColorRGB(*brand.cream)
    c.rect(BODY_L, band_y, BODY_W, foot_h, stroke=0, fill=1)
    c.setFillColorRGB(*brand.primary)
    c.rect(BODY_L, band_y, 4, foot_h, stroke=0, fill=1)
    draw_paragraph(c, p["footer"], BODY_L + 14, band_y + foot_h - 13,
                   BODY_W - 24, size=8.5, leading=12, color=brand.ink)


def render_steps(c, brand, ctx, p, logo):
    """Big-step list (e.g. 8 Steps to Success) as a 2-column tile grid — a
    colored number chip + bold step, on a soft alternating tint."""
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"])
    steps = p["steps"]
    lt_gold = _mix(brand.accent, (1, 1, 1), 0.84)
    lt_red = _mix(brand.primary, (1, 1, 1), 0.90)
    cols = 2
    gut = 16
    tw = (BODY_W - gut) / cols
    nrows = (len(steps) + cols - 1) // cols
    top = y - 2
    bottom = 84
    th = (top - bottom - gut * (nrows - 1)) / nrows
    for i, s in enumerate(steps):
        r, cidx = divmod(i, cols)
        tx = BODY_L + cidx * (tw + gut)
        tyt = top - r * (th + gut)
        accent = brand.primary if i % 2 == 0 else brand.accent
        tint = lt_red if i % 2 == 0 else lt_gold
        c.setFillColorRGB(*tint)
        c.roundRect(tx, tyt - th, tw, th, 7, stroke=0, fill=1)
        # number chip
        chip = 30
        c.setFillColorRGB(*accent)
        c.roundRect(tx + 12, tyt - th / 2 - chip / 2, chip, chip, 6,
                    stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 16)
        c.drawCentredString(tx + 12 + chip / 2, tyt - th / 2 - 6, str(i + 1))
        # step text
        c.setFillColorRGB(*brand.ink)
        c.setFont(FONT_B, 13)
        stext = s.upper()
        sf = 13
        while sf > 9 and stringWidth(stext, FONT_B, sf) > tw - chip - 40:
            sf -= 0.5
        c.setFont(FONT_B, sf)
        c.drawString(tx + 12 + chip + 12, tyt - th / 2 - 5, stext)


def _card_lines(c, brand, lines, x, y, w, size=8.4, extra_gap=0):
    """Render a card's content lines (bullet/sub/label/labelhead/note/head).
    extra_gap adds even spacing after each line so content can fill a card."""
    lead = size * 1.28
    for ln in lines:
        t = ln.get("t", "bullet")
        if t == "head":
            c.setFillColorRGB(*brand.muted)
            c.setFont(FONT_B, size + 0.5)
            for w_line in _wrap(ln["x"], FONT_B, size + 0.5, w):
                c.drawCentredString(x + w / 2, y, w_line)
                y -= lead
            y -= 3
        elif t == "labelhead":
            c.setFillColorRGB(*brand.primary)
            c.setFont(FONT_B, size)
            c.drawString(x, y, ln["x"])
            y -= lead
        elif t == "note":
            y = draw_paragraph(c, ln["x"], x, y, w, size=size,
                               leading=lead, font=FONT_I, color=brand.muted)
            y -= 2
        elif t in ("bullet", "sub"):
            ix = x + (14 if t == "sub" else 2)
            c.setFillColorRGB(*brand.accent)
            c.setFont(FONT_B, size)
            c.drawString(ix, y, "•")
            tx = ix + 11
            if ln.get("lead"):        # bold label leading the bullet
                c.setFillColorRGB(*brand.primary)
                c.setFont(FONT_B, size)
                c.drawString(tx, y, ln["lead"])
                tx += stringWidth(ln["lead"] + " ", FONT_B, size)
            y = draw_paragraph(c, ln["x"], tx, y, w - (tx - x),
                               size=size, leading=lead, color=brand.ink)
            y -= 2
        elif t == "label":
            c.setFillColorRGB(*brand.primary)
            c.setFont(FONT_B, size)
            lead_w = stringWidth(ln["lead"] + " ", FONT_B, size)
            c.drawString(x, y, ln["lead"])
            y = draw_paragraph(c, ln["x"], x + lead_w, y, w - lead_w,
                               size=size, leading=lead, color=brand.ink)
            y -= 3
        y -= extra_gap
    return y


def _card_lines_h(lines, w, size):
    """Estimate the drawn height of a card's content lines (mirror of
    _card_lines) so cards can be sized to their content."""
    lead = size * 1.32
    h = 0
    for ln in lines:
        t = ln.get("t", "bullet")
        if t == "head":
            h += len(_wrap(ln["x"], FONT_B, size + 0.5, w)) * lead + 3
        elif t == "labelhead":
            h += lead
        elif t == "note":
            h += len(_wrap(ln["x"], FONT_I, size, w)) * lead + 2
        elif t in ("bullet", "sub"):
            ix = 14 if t == "sub" else 2
            h += len(_wrap(ln["x"], FONT, size, w - ix - 11)) * lead + 2
        elif t == "label":
            lead_w = stringWidth(ln["lead"] + " ", FONT_B, size)
            h += len(_wrap(ln["x"], FONT, size, w - lead_w)) * lead + 3
    return h


def render_cards(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    if p.get("intro"):
        y = draw_paragraph(c, p["intro"], BODY_L, y, BODY_W, size=10.5,
                           leading=15, color=brand.muted, align="center")
        y -= 16
    cards = p["cards"]
    cols = p.get("cols", 2)
    gut = 16
    card_w = (BODY_W - gut * (cols - 1)) / cols
    pad = 13
    size = 13 if cols == 1 else 10.5
    decor_h = 96 if p.get("decor") == "stop" else 0
    spread = bool(decor_h or p.get("fill_cards"))
    hdr_h = 26
    band = [brand.primary, brand.dark, brand.accent]
    # per-row height = tallest card content in that row (+ header + padding)
    n_rows = (len(cards) + cols - 1) // cols
    row_h = []
    for r in range(n_rows):
        hmax = 0
        for card in cards[r * cols:(r + 1) * cols]:
            sub = 0
            if card.get("sub"):
                sub = len(_wrap(card["sub"], FONT_I, 9.5,
                                card_w - 2 * pad)) * 12 + 6
            body = _card_lines_h(card["lines"], card_w - 2 * pad, size)
            hmax = max(hmax, hdr_h + sub + body + 22)
        row_h.append(hmax)
    top = y
    avail = top - 74 - decor_h
    # stop-sign / fill mode: stretch cards to fill the page evenly
    if decor_h or p.get("fill_cards"):
        eq = (avail - gut * (n_rows - 1)) / n_rows
        row_h = [max(h, eq) for h in row_h]
    # spread rows to fill the page (capped), then center any remainder
    total_content = sum(row_h)
    if n_rows > 1:
        gap = max(gut, min((avail - total_content) / (n_rows - 1), gut + 80))
    else:
        gap = gut
    used = total_content + gap * (n_rows - 1)
    cyt = top - max(0, (avail - used) / 2)
    for r in range(n_rows):
        ch = row_h[r]
        for cidx, card in enumerate(cards[r * cols:(r + 1) * cols]):
            idx = r * cols + cidx
            cx = BODY_L + cidx * (card_w + gut)
            hdr = band[idx % 3]
            tint = _mix(hdr, (1, 1, 1), 0.93)
            tcol = brand.ink if hdr == brand.accent else (1, 1, 1)
            # tinted body + colored header strip
            c.setFillColorRGB(*tint)
            c.rect(cx, cyt - ch, card_w, ch, stroke=0, fill=1)
            c.setFillColorRGB(*hdr)
            c.rect(cx, cyt - hdr_h, card_w, hdr_h, stroke=0, fill=1)
            c.setFillColorRGB(*tcol)
            c.setFont(FONT_B, 13)
            c.drawCentredString(cx + card_w / 2, cyt - hdr_h / 2 - 4.5,
                                card["heading"])
            sub_lines = (_wrap(card["sub"], FONT_I, 9.5, card_w - 2 * pad)
                         if card.get("sub") else [])
            sub_h = len(sub_lines) * 12 + (4 if sub_lines else 0)
            body_h = _card_lines_h(card["lines"], card_w - 2 * pad, size)
            if spread:
                # top-align sub, then spread the bullets to fill the square
                top_pad = 20
                yy = cyt - hdr_h - top_pad
                if sub_lines:
                    c.setFillColorRGB(*brand.muted)
                    c.setFont(FONT_I, 9.5)
                    for wl in sub_lines:
                        c.drawCentredString(cx + card_w / 2, yy, wl)
                        yy -= 12
                    yy -= 6
                nlines = max(1, len(card["lines"]))
                room = (yy - (cyt - ch + 16)) - body_h
                eg = max(0, room / nlines)
                _card_lines(c, brand, card["lines"], cx + pad, yy - eg,
                            card_w - 2 * pad, size=size, extra_gap=eg)
            else:
                # vertically center the sub + body block in the card
                yy = _vcenter(cyt - hdr_h, ch - hdr_h, sub_h + body_h, size,
                              min_gap=12, lead=size * 1.32)
                if sub_lines:
                    c.setFillColorRGB(*brand.muted)
                    c.setFont(FONT_I, 9.5)
                    for wl in sub_lines:
                        c.drawCentredString(cx + card_w / 2, yy, wl)
                        yy -= 12
                    yy -= 4
                _card_lines(c, brand, card["lines"], cx + pad, yy,
                            card_w - 2 * pad, size=size)
            c.setStrokeColorRGB(*brand.muted)
            c.setLineWidth(0.5)
            c.rect(cx, cyt - ch, card_w, ch, stroke=1, fill=0)
        cyt -= ch + gap

    # decorative STOP sign + grass strip (Stop Signs page)
    if p.get("decor") == "stop":
        _draw_grass_stop(c, brand)


def _draw_grass_stop(c, brand):
    """A tidy grass strip with a large STOP sign standing on it."""
    import math
    # --- grass: solid turf band with an even row of tapered blades ---------
    turf = 12
    gy = 46                       # top of the solid turf band
    c.setFillColorRGB(*_hex("#4E9E3A"))
    c.rect(BODY_L, gy - turf, BODY_W, turf, stroke=0, fill=1)
    c.setStrokeColorRGB(*_hex("#3C8A2E"))
    c.setLineWidth(1.3)
    c.setLineCap(1)
    # alternating tall/short blades, gently leaning, evenly spaced
    heights = [15, 10, 13, 9, 16, 11]
    leans = [-3, 2, 0, 3, -2, 1]
    j = 0
    gx = BODY_L + 3
    while gx < BODY_R - 2:
        h = heights[j % len(heights)]
        lean = leans[j % len(leans)]
        c.setStrokeColorRGB(*_hex("#5BB043" if j % 2 else "#3C8A2E"))
        c.line(gx, gy, gx + lean, gy + h)
        gx += 7
        j += 1
    # --- big STOP sign standing on the turf --------------------------------
    r = 46
    sx = BODY_R - r - 10
    sy = gy + 8 + r               # centre height so it rests on the grass
    c.setStrokeColorRGB(*_hex("#8f9296"))         # metal post
    c.setLineWidth(6)
    c.line(sx, gy + 4, sx, sy - r * 0.55)
    path = c.beginPath()
    for k in range(8):
        ang = math.pi / 8 + k * math.pi / 4
        xx = sx + r * math.cos(ang)
        yy2 = sy + r * math.sin(ang)
        (path.moveTo if k == 0 else path.lineTo)(xx, yy2)
    path.close()
    c.setFillColorRGB(*_hex("#C1121F"))           # red octagon
    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(3)
    c.drawPath(path, stroke=1, fill=1)
    # inner white ring
    ring = c.beginPath()
    r2 = r - 7
    for k in range(8):
        ang = math.pi / 8 + k * math.pi / 4
        (ring.moveTo if k == 0 else ring.lineTo)(sx + r2 * math.cos(ang),
                                                 sy + r2 * math.sin(ang))
    ring.close()
    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(1.6)
    c.drawPath(ring, stroke=1, fill=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(FONT_B, 23)
    c.drawCentredString(sx, sy - 8, "STOP")


def render_fugi(c, brand, ctx, p, logo):
    """FUGI factor page: four full-width rows, each led by a big acronym letter
    tile (F · U · G · I) with the factor name + tactics beside it."""
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    if p.get("intro"):
        # keep each sentence on its own line
        for sentence in re.split(r"(?<=\.)\s+", p["intro"].strip()):
            y = draw_paragraph(c, sentence, BODY_L, y, BODY_W, size=13,
                               leading=18, font=FONT_B, color=brand.muted,
                               align="center")
        y -= 16
    cards = p["cards"]
    band = [brand.primary, brand.dark, brand.accent, brand.primary]
    tile_w = 62
    pad = 13
    bodyw = BODY_W - tile_w - 2 * pad
    gap = 14
    bottom = 70
    avail = y - bottom

    def row_h(card, size):
        sub = (len(_wrap(card["sub"], FONT_I, 10, bodyw)) * 13 + 6
               if card.get("sub") else 0)
        body = _card_lines_h(card["lines"], bodyw, size)
        return 24 + sub + body + 20     # heading + content + padding

    # largest body font where all four rows fit the page
    size = 11
    while size > 8.5:
        if sum(row_h(cd, size) for cd in cards) + gap * (len(cards) - 1) \
                <= avail:
            break
        size -= 0.25
    heights = [row_h(cd, size) for cd in cards]
    slack = max(0, avail - sum(heights) - gap * (len(cards) - 1))
    heights = [h + slack / len(cards) for h in heights]     # fill the page
    cyt = y
    for i, card in enumerate(cards):
        ch = heights[i]
        hdr = band[i % len(band)]
        letter = card["heading"].strip()[0]
        tint = _mix(hdr, (1, 1, 1), 0.93)
        tcol = brand.ink if hdr == brand.accent else (1, 1, 1)
        # tinted body panel
        c.setFillColorRGB(*tint)
        c.rect(BODY_L, cyt - ch, BODY_W, ch, stroke=0, fill=1)
        # big letter tile on the left
        c.setFillColorRGB(*hdr)
        c.rect(BODY_L, cyt - ch, tile_w, ch, stroke=0, fill=1)
        c.setFillColorRGB(*tcol)
        c.setFont(FONT_B, 46)
        c.drawCentredString(BODY_L + tile_w / 2, cyt - ch / 2 - 15, letter)
        # heading + sub + tactics, vertically centered in the panel body
        bx = BODY_L + tile_w + pad
        sub_lines = (_wrap(card["sub"], FONT_I, 10, bodyw)
                     if card.get("sub") else [])
        sub_h = len(sub_lines) * 13 + (4 if sub_lines else 0)
        head_h = 22
        body_h = _card_lines_h(card["lines"], bodyw, size)
        blk = head_h + sub_h + body_h
        yy = cyt - max(14, (ch - blk) / 2) - 13
        c.setFillColorRGB(*hdr)
        c.setFont(FONT_B, 14.5)
        c.drawString(bx, yy, card["heading"])
        yy -= head_h
        if sub_lines:
            c.setFillColorRGB(*brand.muted)
            c.setFont(FONT_I, 10)
            for wl in sub_lines:
                c.drawString(bx, yy, wl)
                yy -= 13
            yy -= 4
        _card_lines_left(c, brand, card["lines"], bx, yy, bodyw, size=size)
        # thin accent seam between the tile and body
        c.setStrokeColorRGB(*_mix(hdr, (1, 1, 1), 0.4))
        c.setLineWidth(0.6)
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.5)
        c.rect(BODY_L, cyt - ch, BODY_W, ch, stroke=1, fill=0)
        cyt -= ch + gap


def _card_lines_left(c, brand, lines, x, y, w, size=8.4, extra_gap=0):
    """Left-aligned variant of _card_lines (bullets flush left, no centering).
    extra_gap adds even spacing after each item so content can fill a card."""
    lead = size * 1.32
    for ln in lines:
        t = ln.get("t", "bullet")
        if t == "labelhead":
            c.setFillColorRGB(*brand.primary)
            c.setFont(FONT_B, size)
            c.drawString(x, y, ln["x"])
            y -= lead
        elif t == "note":
            y = draw_paragraph(c, ln["x"], x, y, w, size=size,
                               leading=lead, font=FONT_I, color=brand.muted)
            y -= 2
        elif t in ("bullet", "sub"):
            ix = x + (14 if t == "sub" else 2)
            c.setFillColorRGB(*brand.accent)
            c.setFont(FONT_B, size)
            c.drawString(ix, y, "•")
            tx = ix + 11
            if ln.get("lead"):        # bold label leading the bullet
                c.setFillColorRGB(*brand.primary)
                c.setFont(FONT_B, size)
                c.drawString(tx, y, ln["lead"])
                tx += stringWidth(ln["lead"] + " ", FONT_B, size)
            y = draw_paragraph(c, ln["x"], tx, y, w - (tx - x),
                               size=size, leading=lead, color=brand.ink)
            y -= 2
        elif t == "label":
            c.setFillColorRGB(*brand.primary)
            c.setFont(FONT_B, size)
            lead_w = stringWidth(ln["lead"] + " ", FONT_B, size)
            c.drawString(x, y, ln["lead"])
            y = draw_paragraph(c, ln["x"], x + lead_w, y, w - lead_w,
                               size=size, leading=lead, color=brand.ink)
            y -= 3
        y -= extra_gap
    return y


_IMG_CACHE = {}


def _img_reader(path):
    rp = Path(path)
    if not rp.is_absolute():
        rp = Path(__file__).resolve().parents[2] / path
    key = str(rp)
    if key not in _IMG_CACHE:
        _IMG_CACHE[key] = ImageReader(key) if rp.exists() else None
    return _IMG_CACHE[key]


def _draw_photo(c, brand, path, x, y, w, h):
    """Draw a photo fit inside the box (top-left x, y; width w, height h),
    cover-cropped to fill, with a thin frame."""
    img = _img_reader(path)
    if img is None:
        c.setFillColorRGB(*_mix(brand.muted, (1, 1, 1), 0.6))
        c.rect(x, y - h, w, h, stroke=0, fill=1)
        return
    iw, ih = img.getSize()
    # cover: scale so the box is filled, then center-crop via a clip path
    scale = max(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    c.saveState()
    pth = c.beginPath()
    pth.rect(x, y - h, w, h)
    c.clipPath(pth, stroke=0, fill=0)
    c.drawImage(img, x + (w - dw) / 2, y - h + (h - dh) / 2, dw, dh,
                mask="auto")
    c.restoreState()
    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(2.5)
    c.rect(x, y - h, w, h, stroke=1, fill=0)
    c.setStrokeColorRGB(*brand.muted)
    c.setLineWidth(0.6)
    c.rect(x, y - h, w, h, stroke=1, fill=0)


def _draw_uniform_card(c, brand, card, cx, cyt, cw, ch, hdr_h, hdr, pad, size):
    """One colored-header uniform card with its content spread to fill."""
    tint = _mix(hdr, (1, 1, 1), 0.93)
    tcol = brand.ink if hdr == brand.accent else (1, 1, 1)
    c.setFillColorRGB(*tint)
    c.rect(cx, cyt - ch, cw, ch, stroke=0, fill=1)
    c.setFillColorRGB(*hdr)
    c.rect(cx, cyt - hdr_h, cw, hdr_h, stroke=0, fill=1)
    c.setFillColorRGB(*tcol)
    c.setFont(FONT_B, 13)
    c.drawCentredString(cx + cw / 2, cyt - hdr_h / 2 - 4.6, card["heading"])
    body_top = cyt - hdr_h - 16
    sub = card.get("sub")
    if sub:
        c.setFillColorRGB(*brand.muted)
        c.setFont(FONT_I, 11)
        c.drawCentredString(cx + cw / 2, body_top, sub)
        body_top -= 20
    lines = card["lines"]
    content_h = _card_lines_h(lines, cw - 2 * pad, size)
    body_bot = cyt - ch + 18
    extra = max(0, (body_top - body_bot) - content_h)
    eg = extra / (len(lines) + 1)
    _card_lines_left(c, brand, lines, cx + pad + 4, body_top - eg,
                     cw - 2 * pad, size=size, extra_gap=eg)
    c.setStrokeColorRGB(*brand.muted)
    c.setLineWidth(0.5)
    c.rect(cx, cyt - ch, cw, ch, stroke=1, fill=0)


def render_dresscode(c, brand, ctx, p, logo):
    """Dress-code page: an APPEARANCE band, uniform card(s), optional photo
    examples, an optional NOT ALLOWED strip, and an optional bottom banner."""
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    pad = 13
    bottom = 66

    # --- APPEARANCE band (dark header + tinted body) -----------------------
    app = p.get("appearance")
    if app:
        lt_dark = _mix(brand.dark, (1, 1, 1), 0.93)
        ahdr = 22
        aw = BODY_W - 2 * pad
        alines = _wrap(app, FONT, 10.5, aw)
        abody = len(alines) * 15 + 14
        ah = ahdr + abody
        c.setFillColorRGB(*lt_dark)
        c.rect(BODY_L, y - ah, BODY_W, ah, stroke=0, fill=1)
        c.setFillColorRGB(*brand.dark)
        c.rect(BODY_L, y - ahdr, BODY_W, ahdr, stroke=0, fill=1)
        c.setFillColorRGB(*brand.accent)
        c.rect(BODY_L, y - ahdr, BODY_W, 3, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 11)
        c.drawString(BODY_L + pad, y - ahdr / 2 - 3.8, "APPEARANCE")
        ty = y - ahdr - 15
        for ln in alines:
            c.setFillColorRGB(*brand.ink)
            c.setFont(FONT, 10.5)
            c.drawString(BODY_L + pad, ty, ln)
            ty -= 15
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.5)
        c.rect(BODY_L, y - ah, BODY_W, ah, stroke=1, fill=0)
        y = y - ah - 18

    # --- reserve space for the NOT ALLOWED strip + banner at the bottom ----
    na = p.get("not_allowed")
    banner = p.get("banner")
    reserve = 0
    if banner:
        reserve += 46
    na_h = 0
    if na:
        na_items = max(len(col.get("items", [])) for col in na)
        na_h = 22 + na_items * 15 + 16          # header + bullets + padding
        reserve += na_h + 34                    # + "NOT ALLOWED" label + gaps
    cards_bottom = bottom + reserve

    # --- uniform cards (+ optional photo examples), stretched to fill ------
    cards = p["cards"]
    images = p.get("images")
    band = [brand.primary, brand.dark, brand.accent]
    size = 12.5
    hdr_h = 28
    avail = y - cards_bottom

    # when photos are supplied, split the region: cards left, 2xN grid right
    if images:
        gut = 18
        left_w = BODY_W * 0.50
        right_w = BODY_W - left_w - gut
        # card column (stacked) on the left
        n = len(cards)
        crow = (avail - 14 * (n - 1)) / n
        cyt = y
        for card in cards:
            _draw_uniform_card(c, brand, card, BODY_L, cyt, left_w, crow,
                               hdr_h, band[0] if card["heading"][0] in "MTS"
                               else band[1], pad, size)
            cyt -= crow + 14
        # photo grid on the right (2 columns)
        pg = 8
        pcols = 2
        prows = (len(images) + pcols - 1) // pcols
        pcw = (right_w - pg * (pcols - 1)) / pcols
        pch = (avail - pg * (prows - 1)) / prows
        gx0 = BODY_L + left_w + gut
        for k, img in enumerate(images):
            rr, cc = divmod(k, pcols)
            px = gx0 + cc * (pcw + pg)
            py = y - rr * (pch + pg)
            _draw_photo(c, brand, img, px, py, pcw, pch)
    else:
        cols = min(2, len(cards))
        gut = 16
        cw = (BODY_W - gut * (cols - 1)) / cols
        n_rows = (len(cards) + cols - 1) // cols
        row_h = (avail - gut * (n_rows - 1)) / n_rows      # fill the region
        cyt = y
        for r in range(n_rows):
            ch = row_h
            for cidx, card in enumerate(cards[r * cols:(r + 1) * cols]):
                idx = r * cols + cidx
                cx = BODY_L + cidx * (cw + gut)
                _draw_uniform_card(c, brand, card, cx, cyt, cw, ch, hdr_h,
                                   band[idx % 3], pad, size)
            cyt -= ch + gut

    # --- NOT ALLOWED strip (3 dark-header columns, bulleted) ---------------
    if na:
        # sit just above the banner (or the footer if no banner)
        y2 = bottom + (46 if banner else 0) + na_h
        n = len(na)
        nw = (BODY_W - gut * (n - 1)) / n
        nhdr = 22
        lt_dark = _mix(brand.dark, (1, 1, 1), 0.93)
        # "NOT ALLOWED" heading above the strip
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 13)
        c.drawCentredString((BODY_L + BODY_R) / 2, y2 + 14, "NOT ALLOWED")
        c.setStrokeColorRGB(*brand.primary)
        c.setLineWidth(1)
        tw3 = stringWidth("NOT ALLOWED", FONT_B, 13)
        c.line((BODY_L + BODY_R) / 2 - tw3 / 2, y2 + 10,
               (BODY_L + BODY_R) / 2 + tw3 / 2, y2 + 10)
        for i, col in enumerate(na):
            nx = BODY_L + i * (nw + gut)
            c.setFillColorRGB(*lt_dark)
            c.rect(nx, y2 - na_h, nw, na_h, stroke=0, fill=1)
            c.setFillColorRGB(*brand.primary)
            c.rect(nx, y2 - nhdr, nw, nhdr, stroke=0, fill=1)
            c.setFillColorRGB(1, 1, 1)
            c.setFont(FONT_B, 10.5)
            c.drawCentredString(nx + nw / 2, y2 - nhdr / 2 - 3.6,
                                col["head"].upper())
            ty = y2 - nhdr - 17
            for it in col.get("items", []):
                c.setFillColorRGB(*brand.accent)
                c.setFont(FONT_B, 10)
                c.drawString(nx + 12, ty, "•")
                c.setFillColorRGB(*brand.ink)
                c.setFont(FONT, 10)
                c.drawString(nx + 22, ty, it)
                ty -= 15
            c.setStrokeColorRGB(*brand.muted)
            c.setLineWidth(0.5)
            c.rect(nx, y2 - na_h, nw, na_h, stroke=1, fill=0)

    # --- bottom banner -----------------------------------------------------
    if banner:
        bh = 34
        c.setFillColorRGB(*brand.primary)
        c.rect(BODY_L, bottom - 4, BODY_W, bh, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 15)
        c.drawCentredString((BODY_L + BODY_R) / 2, bottom - 4 + bh / 2 - 5.5,
                            "  ".join(banner.split()) if len(banner) < 30
                            else banner)


def _sun_icon(c, cx, cy, r, color):
    import math
    c.setStrokeColorRGB(*color)
    c.setLineWidth(2)
    c.setLineCap(1)
    for k in range(8):
        a = k * math.pi / 4
        c.line(cx + math.cos(a) * (r + 3), cy + math.sin(a) * (r + 3),
               cx + math.cos(a) * (r + 8), cy + math.sin(a) * (r + 8))
    c.setFillColorRGB(*color)
    c.circle(cx, cy, r, stroke=0, fill=1)


def _snowflake_icon(c, cx, cy, r, color):
    import math
    c.setStrokeColorRGB(*color)
    c.setLineWidth(2)
    c.setLineCap(1)
    for k in range(6):
        a = k * math.pi / 3
        ex, ey = cx + math.cos(a) * r, cy + math.sin(a) * r
        c.line(cx, cy, ex, ey)
        # little branches
        for s in (0.5, 0.72):
            bx, by = cx + math.cos(a) * r * s, cy + math.sin(a) * r * s
            for da in (math.pi / 4, -math.pi / 4):
                c.line(bx, by, bx + math.cos(a + da) * r * 0.22,
                       by + math.sin(a + da) * r * 0.22)


def render_seasonal(c, brand, ctx, p, logo):
    """An ALWAYS-BRING essentials band over two seasonal cards (SUMMER left,
    WINTER right) with sun / snowflake graphics and warm / cool theming."""
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    gut = 18
    cw = (BODY_W - gut) / 2
    pad = 14
    size = 12.5
    hdr_h = 40
    bottom = 66

    # --- ALWAYS BRING band (full width, 2-column bullets) ------------------
    always = p.get("always")
    if always:
        items = always["items"]
        ahdr = 24
        half = (len(items) + 1) // 2
        acolw = (BODY_W - 2 * pad - 20) / 2
        rows = max(half, len(items) - half)
        abody = rows * 16 + 16
        ah = ahdr + abody
        lt = _mix(brand.accent, (1, 1, 1), 0.86)
        c.setFillColorRGB(*lt)
        c.rect(BODY_L, y - ah, BODY_W, ah, stroke=0, fill=1)
        c.setFillColorRGB(*brand.dark)
        c.rect(BODY_L, y - ahdr, BODY_W, ahdr, stroke=0, fill=1)
        c.setFillColorRGB(*brand.accent)
        c.rect(BODY_L, y - ahdr, BODY_W, 3, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 12)
        c.drawCentredString((BODY_L + BODY_R) / 2, y - ahdr / 2 - 4,
                            always["heading"])
        for ci, chunk in enumerate([items[:half], items[half:]]):
            ax = BODY_L + pad + ci * (acolw + 20)
            ty = y - ahdr - 16
            for it in chunk:
                c.setFillColorRGB(*brand.primary)
                c.setFont(FONT_B, 10.5)
                c.drawString(ax, ty, "•")
                c.setFillColorRGB(*brand.ink)
                c.setFont(FONT, 10.5)
                c.drawString(ax + 11, ty, it)
                ty -= 16
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.5)
        c.rect(BODY_L, y - ah, BODY_W, ah, stroke=1, fill=0)
        y = y - ah - 16

    cards = p["cards"]
    avail = y - bottom
    ch = avail
    warm = _hex("#E08A2E")       # summer orange
    cool = _hex("#3E7CA6")       # winter blue
    themes = [
        {"hdr": warm, "tint": _mix(warm, (1, 1, 1), 0.9), "icon": "sun"},
        {"hdr": cool, "tint": _mix(cool, (1, 1, 1), 0.9), "icon": "snow"},
    ]
    for i, card in enumerate(cards):
        th = themes[i % 2]
        cx = BODY_L + i * (cw + gut)
        c.setFillColorRGB(*th["tint"])
        c.rect(cx, y - ch, cw, ch, stroke=0, fill=1)
        # big faint watermark graphic in the card body
        if th["icon"] == "sun":
            _sun_icon(c, cx + cw / 2, y - ch * 0.30,
                      26, _mix(warm, (1, 1, 1), 0.72))
        else:
            _snowflake_icon(c, cx + cw / 2, y - ch * 0.30,
                            34, _mix(cool, (1, 1, 1), 0.72))
        # header with icon + title
        c.setFillColorRGB(*th["hdr"])
        c.rect(cx, y - hdr_h, cw, hdr_h, stroke=0, fill=1)
        if th["icon"] == "sun":
            _sun_icon(c, cx + 26, y - hdr_h / 2, 8, (1, 1, 1))
        else:
            _snowflake_icon(c, cx + 26, y - hdr_h / 2, 11, (1, 1, 1))
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 18)
        c.drawCentredString(cx + cw / 2 + 14, y - hdr_h / 2 - 6,
                            card["heading"])
        # sub-label + spread gear list
        body_top = y - hdr_h - 18
        sub = card.get("sub")
        if sub:
            c.setFillColorRGB(*brand.muted)
            c.setFont(FONT_I, 11)
            c.drawCentredString(cx + cw / 2, body_top, sub)
            body_top -= 22
        lines = card["lines"]
        content_h = _card_lines_h(lines, cw - 2 * pad, size)
        body_bot = y - ch + 18
        extra = max(0, (body_top - body_bot) - content_h)
        eg = extra / (len(lines) + 1)
        _card_lines_left(c, brand, lines, cx + pad + 4, body_top - eg,
                         cw - 2 * pad, size=size, extra_gap=eg)
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.5)
        c.rect(cx, y - ch, cw, ch, stroke=1, fill=0)


def _col_weights(n):
    return {
        1: [1.0],
        2: [0.62, 0.38],
        3: [0.50, 0.28, 0.22],
        4: [0.40, 0.20, 0.20, 0.20],
        5: [0.34, 0.165, 0.165, 0.165, 0.165],
    }.get(n, [1.0 / n] * n)


def _draw_table(c, brand, x, y, w, headers, rows, size=8.2, header_fill=None,
                min_row_h=0, first_left=True, all_bold=False):
    """Draw a bordered table top-down from y. First column left-aligned, the
    rest centered (set first_left=False to center every column). A row with
    fewer cells than headers spans its last cell across the remaining columns.
    `min_row_h` stretches body rows to fill. Returns the y below the table."""
    header_fill = header_fill or brand.primary
    n = len(headers)
    weights = _col_weights(n)
    cw = [w * wt for wt in weights]
    cx = [x + sum(cw[:i]) for i in range(n)]
    lead = size * 1.25
    pad = 5

    def _row_h(cells):
        maxlines = 1
        for ci, cell in enumerate(cells):
            span = n - ci if len(cells) < n and ci == len(cells) - 1 else 1
            cwid = sum(cw[ci:ci + span]) - 2 * pad
            maxlines = max(maxlines, len(_wrap(str(cell), FONT, size, cwid)))
        return maxlines * lead + 2 * pad

    # header row
    hh = _row_h(headers) + 1
    c.setFillColorRGB(*header_fill)
    c.rect(x, y - hh, w, hh, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    for ci, cell in enumerate(headers):
        c.setFont(FONT_B, size)
        left = ci == 0 and first_left
        tx = cx[ci] + pad if left else cx[ci] + cw[ci] / 2
        clines = _wrap(str(cell), FONT_B, size, cw[ci] - 2 * pad)
        yy = y - (hh - len(clines) * lead) / 2 - size * 0.8   # v-centered
        for line in clines:
            (c.drawString if left else c.drawCentredString)(tx, yy, line)
            yy -= lead
    yb = y - hh

    # body rows (remember each row's top and which column borders it spans)
    row_tops = [yb]
    row_skip = []          # per row: set of column-boundary indices to omit
    for r, cells in enumerate(rows):
        rh = max(_row_h(cells), min_row_h)
        if r % 2 == 1:
            c.setFillColorRGB(*brand.cream)
            c.rect(x, yb - rh, w, rh, stroke=0, fill=1)
        c.setFillColorRGB(*brand.ink)
        for ci, cell in enumerate(cells):
            span = n - ci if len(cells) < n and ci == len(cells) - 1 else 1
            cwid = sum(cw[ci:ci + span])
            left = ci == 0 and first_left
            font = FONT_B if (all_bold or ci == 0) else FONT
            tx = cx[ci] + pad if left else cx[ci] + cwid / 2
            c.setFont(font, size)
            clines = _wrap(str(cell), font, size, cwid - 2 * pad)
            yy = yb - (rh - len(clines) * lead) / 2 - size * 0.8  # v-centered
            for line in clines:
                (c.drawString if left else c.drawCentredString)(tx, yy, line)
                yy -= lead
        yb -= rh
        row_tops.append(yb)
        # a short row spans its last cell; skip the interior borders there
        row_skip.append(set(range(len(cells), n)) if len(cells) < n
                        else set())

    # grid: outer border, header underline, row rules, per-row column borders
    c.setStrokeColorRGB(*brand.muted)
    c.setLineWidth(0.5)
    c.rect(x, yb, w, y - yb, stroke=1, fill=0)
    c.line(x, y - hh, x + w, y - hh)
    for r in range(1, len(rows)):
        c.line(x, row_tops[r], x + w, row_tops[r])
    for b in range(1, n):
        c.line(cx[b], y - hh, cx[b], y)          # header column border
        for r in range(len(rows)):
            if b not in row_skip[r]:
                c.line(cx[b], row_tops[r + 1], cx[b], row_tops[r])
    return yb


def render_paytable(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    if p.get("banner"):
        bh = 30
        c.setFillColorRGB(*brand.dark)
        c.rect(BODY_L, y - bh, BODY_W, bh, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, 12)
        c.drawCentredString((BODY_L + BODY_R) / 2, y - bh / 2 - 4, p["banner"])
        y -= bh + 24

    for blk in p["blocks"]:
        y -= blk.get("space_before", 0)
        kind = blk.get("kind", "tables")
        if kind == "checks":
            c.setFillColorRGB(*brand.primary)
            c.setFont(FONT_B, 11)
            c.drawString(BODY_L, y, blk["heading"])
            c.setStrokeColorRGB(*brand.accent)
            c.setLineWidth(0.8)
            c.line(BODY_L, y - 6, BODY_R, y - 6)
            y -= 20
            y = _draw_checklist_items(c, brand, blk["items"], BODY_L + 4, y,
                                      BODY_W - 8, size=9, gap=5, box=9)
            y -= 12
        else:  # tables
            if blk.get("heading"):
                c.setFillColorRGB(*brand.dark)
                c.rect(BODY_L, y - 18, BODY_W, 20, stroke=0, fill=1)
                c.setFillColorRGB(1, 1, 1)
                c.setFont(FONT_B, 11)
                c.drawCentredString((BODY_L + BODY_R) / 2, y - 12,
                                    blk["heading"])
                y -= 30
            tables = blk["tables"]
            mrh = p.get("row_h", 0)
            if blk.get("side_by_side") and len(tables) == 2:
                gut = 18
                tw = (BODY_W - gut) / 2
                y0 = y
                yb1 = _table_block(c, brand, tables[0], BODY_L, y0, tw,
                                   min_row_h=mrh)
                yb2 = _table_block(c, brand, tables[1], BODY_L + tw + gut,
                                   y0, tw, min_row_h=mrh)
                y = min(yb1, yb2) - 14
            else:
                mrh = p.get("row_h", 0)
                for t in tables:
                    y = _table_block(c, brand, t, BODY_L, y, BODY_W,
                                     min_row_h=mrh) - 18


def _table_block(c, brand, t, x, y, w, min_row_h=0):
    if t.get("label"):
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 9.5)
        c.drawCentredString(x + w / 2, y, t["label"])
        y -= 14
    return _draw_table(c, brand, x, y, w, t["headers"], t["rows"],
                       size=t.get("size", 8.2), min_row_h=min_row_h,
                       first_left=t.get("first_left", True),
                       all_bold=t.get("all_bold", False))


def render_tracker(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    if p.get("intro"):
        c.setFillColorRGB(*brand.muted)
        c.setFont(FONT_I, 10)
        c.drawString(BODY_L, y, p["intro"])
        y -= 18
    headers = p["columns"]
    n = len(headers)
    weights = _col_weights(n) if n <= 5 else [1.0 / n] * n
    cw = [BODY_W * wt for wt in weights]
    cx = [BODY_L + sum(cw[:i]) for i in range(n)]
    size = 7.5 if n >= 8 else 8.5
    # header
    hh = 22
    c.setFillColorRGB(*brand.primary)
    c.rect(BODY_L, y - hh, BODY_W, hh, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    for ci, h in enumerate(headers):
        c.setFont(FONT_B, size)
        yy = y - 9
        for line in _wrap(h, FONT_B, size, cw[ci] - 6):
            c.drawCentredString(cx[ci] + cw[ci] / 2, yy, line)
            yy -= size + 1
    yb = y - hh
    # empty rows filling to the legend
    rows = p.get("rows", 16)
    row_h = (yb - 92) / rows
    for r in range(rows):
        ry = yb - r * row_h
        if r % 2 == 1:
            c.setFillColorRGB(*brand.cream)
            c.rect(BODY_L, ry - row_h, BODY_W, row_h, stroke=0, fill=1)
    # grid
    c.setStrokeColorRGB(*brand.muted)
    c.setLineWidth(0.5)
    grid_bottom = yb - rows * row_h
    c.rect(BODY_L, grid_bottom, BODY_W, yb - grid_bottom, stroke=1, fill=0)
    for ci in range(1, n):
        c.line(cx[ci], grid_bottom, cx[ci], yb)
    for r in range(1, rows):
        ry = yb - r * row_h
        c.line(BODY_L, ry, BODY_R, ry)
    # status legend
    if p.get("legend"):
        ly = grid_bottom - 20
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 8.5)
        c.drawString(BODY_L, ly, "STATUS KEY:")
        lx = BODY_L + stringWidth("STATUS KEY:  ", FONT_B, 8.5)
        for label, hexc in p["legend"]:
            c.setFillColorRGB(*_hex(hexc))
            c.rect(lx, ly - 1, 9, 9, stroke=0, fill=1)
            c.setFillColorRGB(*brand.ink)
            c.setFont(FONT, 8.5)
            c.drawString(lx + 13, ly, label)
            lx += 13 + stringWidth(label, FONT, 8.5) + 16


def render_worksheet(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    # right-side block — summary chart pushed to the right edge, with the
    # title / subtitle / logo centered above it
    box_w = 214
    right_edge = PAGE_W - MARGIN - 6
    rx = right_edge - box_w
    cxr = rx + box_w / 2
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 32)
    c.drawCentredString(cxr, PAGE_H - 96, p["title"])
    c.setFillColorRGB(*brand.ink)
    c.setFont(FONT_B, 16)
    ty = PAGE_H - 132
    for line in _wrap(p["subtitle"], FONT_B, 16, box_w):
        c.drawCentredString(cxr, ty, line)
        ty -= 20
    if logo is not None:
        _place_logo(c, logo, cxr, ty - 100, max_w=160, max_h=96,
                    align="center")
        ty -= 116
    # summary mini-table on the right
    sy = ty - 12
    labels = p["summary"]
    rh = 38
    hdr_h = 28
    c.setFillColorRGB(*brand.dark)
    c.rect(rx, sy - hdr_h, box_w, hdr_h, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(FONT_B, 10)
    hlines = _wrap(p.get("summary_title", "Weekly / Monthly Expenses"),
                   FONT_B, 10, box_w - 8)
    hy = sy - (hdr_h - len(hlines) * 11) / 2 - 8       # vertically centered
    for line in hlines:
        c.drawCentredString(cxr, hy, line)
        hy -= 11
    yb = sy - hdr_h
    div = 0.66                         # wider label cell so labels center
    lsz = 9
    for lab in labels:
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.6)
        c.rect(rx, yb - rh, box_w, rh, stroke=1, fill=0)
        c.line(rx + box_w * div, yb - rh, rx + box_w * div, yb)
        c.setFillColorRGB(*brand.ink)
        c.setFont(FONT_B, lsz)
        llines = _wrap(lab, FONT_B, lsz, box_w * div - 10)
        tyl = yb - rh / 2 + (len(llines) - 1) * 5.5 - 3   # v-centered
        for ln in llines:
            c.drawCentredString(rx + box_w * div / 2, tyl, ln)
            tyl -= 11
        yb -= rh

    # left bills / debt table — larger text, centered in each cell
    lw = BODY_W * 0.54
    lx = BODY_L
    headers = p["table_headers"]
    ncol = len(headers)
    cw = [lw * 0.60] + [lw * 0.40 / (ncol - 1)] * (ncol - 1)
    cxs = [lx + sum(cw[:i]) for i in range(ncol)]
    top = PAGE_H - 80
    rows = p["rows_list"]
    rh2 = (top - 66) / (len(rows) + 1)
    # header row
    c.setFillColorRGB(*brand.primary)
    c.rect(lx, top - rh2, lw, rh2, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    for ci, h in enumerate(headers):
        c.setFont(FONT_B, 11)
        c.drawCentredString(cxs[ci] + cw[ci] / 2, top - rh2 / 2 - 4, h)
    yb2 = top - rh2
    for r, label in enumerate(rows):
        if r % 2 == 1:
            c.setFillColorRGB(*brand.cream)
            c.rect(lx, yb2 - rh2, lw, rh2, stroke=0, fill=1)
        c.setFillColorRGB(*brand.ink)
        c.setFont(FONT_B, 10)
        c.drawCentredString(lx + cw[0] / 2, yb2 - rh2 / 2 - 4, label)
        yb2 -= rh2
    # grid
    c.setStrokeColorRGB(*brand.primary)
    c.setLineWidth(0.8)
    c.rect(lx, yb2, lw, top - yb2, stroke=1, fill=0)
    for ci in range(1, ncol):
        c.line(cxs[ci], yb2, cxs[ci], top)
    for r in range(1, len(rows) + 1):
        ry = top - r * rh2
        c.line(lx, ry, lx + lw, ry)


def render_qrpage(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    cxm = PAGE_W / 2
    if logo is not None:
        _place_logo(c, logo, cxm, PAGE_H - 150, max_w=210, max_h=98,
                    align="center")
    # big script-style title (two-tone). Keep generous vertical gaps between
    # these elements: Canva's PDF importer pads each text box, so tightly
    # stacked lines collide (and drop spaces) when a packet is imported to edit.
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 46)
    c.drawCentredString(cxm, PAGE_H - 205, p["title"])
    if p.get("title2"):
        c.setFillColorRGB(*brand.accent)
        c.setFont(FONT_B, 54)
        c.drawCentredString(cxm, PAGE_H - 268, p["title2"])
    if p.get("subtitle"):
        c.setFillColorRGB(*brand.muted)
        c.setFont(FONT_I, 13)
        c.drawCentredString(cxm, PAGE_H - 315, p["subtitle"])
    # big QR centered
    qr = 240
    qy = 210
    if p.get("url"):
        c.drawImage(qr_image(p["url"]), cxm - qr / 2, qy, qr, qr, mask="auto")
        c.setStrokeColorRGB(*brand.accent)
        c.setLineWidth(1.2)
        c.rect(cxm - qr / 2 - 8, qy - 8, qr + 16, qr + 16, stroke=1, fill=0)
    c.setFillColorRGB(*brand.primary)
    c.setFont(FONT_B, 16)
    c.drawCentredString(cxm, qy - 40, p.get("caption", "SCAN ME"))


def _num_badge(c, brand, x, y, num, size=30):
    c.setFillColorRGB(*brand.dark)
    c.rect(x, y, size, size, stroke=0, fill=1)
    c.setStrokeColorRGB(*brand.primary)
    c.setLineWidth(1.6)
    c.rect(x, y, size, size, stroke=1, fill=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(FONT_B, size * 0.62)
    c.drawCentredString(x + size / 2, y + size / 2 - size * 0.22, num)


def _bullet_block(c, brand, bullets, x, y, w, size=8, lead=None,
                  bold_parent=True):
    lead = lead or size * 1.3
    pfont = FONT_B if bold_parent else FONT
    for b in bullets:
        if isinstance(b, dict):
            c.setFillColorRGB(*brand.accent)
            c.setFont(FONT_B, size)
            c.drawString(x, y, "•")
            y = draw_paragraph(c, b["b"], x + 9, y, w - 9, size=size,
                               leading=lead, font=pfont, color=brand.ink)
            for s in b.get("sub", []):
                c.setFillColorRGB(*brand.accent)
                c.setFont(FONT, size)
                c.drawString(x + 12, y, "–")
                y = draw_paragraph(c, s, x + 22, y, w - 22, size=size,
                                   leading=lead, color=brand.muted)
                y -= 1
        else:
            c.setFillColorRGB(*brand.accent)
            c.setFont(FONT_B, size)
            c.drawString(x, y, "•")
            y = draw_paragraph(c, b, x + 9, y, w - 9, size=size,
                               leading=lead, color=brand.ink)
        y -= 3
    return y


def _bullet_block_h(bullets, w, size, lead=None, bold_parent=True):
    """Height of a bullet block (mirror of _bullet_block) for content sizing."""
    lead = lead or size * 1.3
    pfont = FONT_B if bold_parent else FONT
    h = 0
    for b in bullets:
        if isinstance(b, dict):
            h += len(_wrap(b["b"], pfont, size, w - 9)) * lead
            for s in b.get("sub", []):
                h += len(_wrap(s, FONT, size, w - 22)) * lead + 1
        else:
            h += len(_wrap(b, FONT, size, w - 9)) * lead
        h += 3
    return h


def _wrap_nl(text, font, size, w):
    """Like _wrap, but an explicit '\\n' forces a hard line break."""
    lines = []
    for seg in text.split("\n"):
        lines.extend(_wrap(seg, font, size, w))
    return lines


def _centered_col_h(items, w, size, lead=None):
    """Height of a centered column (mirror of _draw_centered_col)."""
    lead = lead or size * 1.32
    h = 0
    for it in items:
        if isinstance(it, dict):
            h += len(_wrap_nl(it["b"], FONT_B, size, w)) * lead
            for s in it.get("sub", []):
                h += len(_wrap_nl(s, FONT, size - 0.5, w)) * (lead * 0.92)
        else:
            h += len(_wrap_nl(it, FONT, size, w)) * lead
        h += 8
    return h


def _draw_centered_col(c, brand, items, cx, y, w, size, lead=None):
    """Draw a column of items centered horizontally at cx, top-down from y."""
    lead = lead or size * 1.32
    for it in items:
        if isinstance(it, dict):
            c.setFillColorRGB(*brand.primary)
            c.setFont(FONT_B, size)
            for ln in _wrap_nl(it["b"], FONT_B, size, w):
                c.drawCentredString(cx, y, ln)
                y -= lead
            for s in it.get("sub", []):
                c.setFillColorRGB(*brand.muted)
                c.setFont(FONT, size - 0.5)
                for ln in _wrap_nl(s, FONT, size - 0.5, w):
                    c.drawCentredString(cx, y, ln)
                    y -= lead * 0.92
        else:
            c.setFillColorRGB(*brand.ink)
            c.setFont(FONT, size)
            for ln in _wrap_nl(it, FONT, size, w):
                c.drawCentredString(cx, y, ln)
                y -= lead
        y -= 8
    return y


def render_numbered(c, brand, ctx, p, logo):
    """Full-width step cards: colored header strip (number chip + section name)
    over a two-column body with all text centered in its box."""
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    steps = p["steps"]
    band = [brand.primary, brand.dark, brand.accent]
    hdr_h = 27
    colw = (BODY_W - 24 - 16) / 2      # two body columns
    cxs = [BODY_L + 14 + colw / 2, BODY_L + 14 + colw + 16 + colw / 2]
    top = y - 2
    bottom = 68

    def _cols(s):
        if "left" in s or "right" in s:
            return s.get("left", []), s.get("right", [])
        b = s.get("bullets", [])
        half = (len(b) + 1) // 2
        return b[:half], b[half:]

    def card_h(s, size):
        l, r = _cols(s)
        body = max(_centered_col_h(l, colw, size),
                   _centered_col_h(r, colw, size), 20)
        return hdr_h + body + 22

    # pick the largest font that still fits all cards on the page
    size = 11.5
    while size > 8.5:
        if sum(card_h(s, size) for s in steps) <= (top - bottom):
            break
        size -= 0.25
    tlead = size * 1.32
    heights = [card_h(s, size) for s in steps]
    slack = max(0, (top - bottom) - sum(heights))
    gap = min(slack / max(1, len(steps) - 1), 20)
    cy = top - max(0, (slack - gap * (len(steps) - 1)) / 2)
    for si, s in enumerate(steps):
        ch = heights[si]
        hdr = band[si % 3]
        tcol = brand.ink if hdr == brand.accent else (1, 1, 1)
        # header strip
        c.setFillColorRGB(*hdr)
        c.rect(BODY_L, cy - hdr_h, BODY_W, hdr_h, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.circle(BODY_L + 18, cy - hdr_h / 2, 9, stroke=0, fill=1)
        c.setFillColorRGB(*hdr)
        c.setFont(FONT_B, 11)
        c.drawCentredString(BODY_L + 18, cy - hdr_h / 2 - 3.6, s["n"])
        c.setFillColorRGB(*tcol)
        c.setFont(FONT_B, 14)
        c.drawString(BODY_L + 36, cy - hdr_h / 2 - 4.8, s["name"])
        # subtle divider between the two columns
        c.setStrokeColorRGB(*_mix(brand.muted, (1, 1, 1), 0.55))
        c.setLineWidth(0.6)
        c.line(BODY_L + BODY_W / 2, cy - hdr_h - 8, BODY_L + BODY_W / 2,
               cy - ch + 8)
        # body box + two centered columns (each v-centered in the body)
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.7)
        c.rect(BODY_L, cy - ch, BODY_W, ch - hdr_h, stroke=1, fill=0)
        body_top = cy - hdr_h
        # both columns start at the same baseline, vertically centered in the
        # body (based on the taller column) so the text sits in the middle
        colhs = [_centered_col_h(chunk, colw, size) for chunk in _cols(s)]
        y0 = _vcenter(body_top, ch - hdr_h, max(colhs) if colhs else 0,
                      size, min_gap=14, lead=tlead)
        for ci, chunk in enumerate(_cols(s)):
            if chunk:
                _draw_centered_col(c, brand, chunk, cxs[ci], y0, colw, size)
        cy -= ch + gap


def render_garden(c, brand, ctx, p, logo):
    """Two lap panels (gold / maroon headers) over three info panels with dark
    headers — colored-header cards on light tints, no plain outlined boxes."""
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    gut = 16
    lw = (BODY_W - gut) / 2
    lap_top = y - 4
    lt_gold = _mix(brand.accent, (1, 1, 1), 0.85)
    lt_red = _mix(brand.primary, (1, 1, 1), 0.91)
    lt_dark = _mix(brand.dark, (1, 1, 1), 0.92)
    lap_hdr = 36
    hdrs = [brand.accent, brand.primary]
    htc = [brand.ink, (1, 1, 1)]
    tints = [lt_gold, lt_red]

    def _lap_body_h(lap):
        h = 10
        h += len(_wrap(lap["title"], FONT_B, 13.5, lw - 24)) * 16.5 + 5
        h += len(_wrap(lap["note"], FONT_I, 10, lw - 26)) * 12.5 + 10
        h += 16 + _bullet_block_h(lap["bullets"], lw - 30, 10.5) + 8
        return h

    lap_h = lap_hdr + max(_lap_body_h(l) for l in p["laps"])
    for i, lap in enumerate(p["laps"]):
        lx = BODY_L + i * (lw + gut)
        c.setFillColorRGB(*tints[i])
        c.rect(lx, lap_top - lap_h, lw, lap_h, stroke=0, fill=1)
        c.setFillColorRGB(*hdrs[i])
        c.rect(lx, lap_top - lap_hdr, lw, lap_hdr, stroke=0, fill=1)
        # big lap number badge
        c.setFillColorRGB(1, 1, 1)
        c.circle(lx + 22, lap_top - lap_hdr / 2, 13, stroke=0, fill=1)
        c.setFillColorRGB(*hdrs[i])
        c.setFont(FONT_B, 15)
        c.drawCentredString(lx + 22, lap_top - lap_hdr / 2 - 5.3, str(i + 1))
        c.setFillColorRGB(*htc[i])
        c.setFont(FONT_B, 12.5)
        c.drawCentredString(lx + lw / 2 + 16, lap_top - lap_hdr / 2 - 4.5,
                            lap["tag"])
        yy = lap_top - lap_hdr - 18
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_B, 13.5)
        for line in _wrap(lap["title"], FONT_B, 13.5, lw - 24):
            c.drawCentredString(lx + lw / 2, yy, line)
            yy -= 16.5
        c.setFillColorRGB(*brand.muted)
        c.setFont(FONT_I, 10)
        for line in _wrap(lap["note"], FONT_I, 10, lw - 26):
            c.drawCentredString(lx + lw / 2, yy - 2, line)
            yy -= 12.5
        yy -= 8
        c.setFillColorRGB(*(hdrs[i] if i == 1 else brand.primary))
        c.setFont(FONT_B, 10.5)
        c.drawString(lx + 15, yy, lap["list_head"])
        yy -= 16
        _bullet_block(c, brand, lap["bullets"], lx + 17, yy, lw - 32,
                      size=10.5)
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.5)
        c.rect(lx, lap_top - lap_h, lw, lap_h, stroke=1, fill=0)
    y = lap_top - lap_h - 22

    # three info panels — dark header (dynamic height), content v-centered,
    # filling the space to the footer
    n = len(p["boxes"])
    bw = (BODY_W - gut * (n - 1)) / n
    bhsz = 12.5
    maxtl = max(len(_wrap(b["title"], FONT_B, bhsz, bw - 12))
                for b in p["boxes"])
    bhdr = 20 + maxtl * 15

    def _box_body_h(box, bsz2, bld2):
        h = 0
        for ln in box["lines"]:
            if ln.get("lead"):
                lw2 = stringWidth(ln["lead"] + " ", FONT_B, bsz2)
                h += len(_wrap(ln["x"], FONT, bsz2, bw - 22 - lw2)) * bld2 + 8
            else:
                h += len(_wrap(ln["x"], FONT, bsz2, bw - 22)) * bld2 + 8
        return h

    region = y - 70
    box_h = min(region, 250)
    band_top = y - max(0, (region - box_h) / 2)
    # largest info-panel body font whose tallest box still fits in the box
    bsz2 = 12
    while bsz2 > 9:
        bld2 = bsz2 * 1.4
        if max(_box_body_h(b, bsz2, bld2) for b in p["boxes"]) \
                <= box_h - bhdr - 24:
            break
        bsz2 -= 0.25
    bld2 = bsz2 * 1.4
    for i, box in enumerate(p["boxes"]):
        bx = BODY_L + i * (bw + gut)
        c.setFillColorRGB(*lt_dark)
        c.rect(bx, band_top - box_h, bw, box_h, stroke=0, fill=1)
        c.setFillColorRGB(*brand.dark)
        c.rect(bx, band_top - bhdr, bw, bhdr, stroke=0, fill=1)
        c.setFillColorRGB(*brand.accent)          # gold accent under header
        c.rect(bx, band_top - bhdr, bw, 3, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(FONT_B, bhsz)
        tlines = _wrap(box["title"], FONT_B, bhsz, bw - 12)
        hty = band_top - (bhdr - len(tlines) * 14) / 2 - 9
        for line in tlines:
            c.drawCentredString(bx + bw / 2, hty, line)
            hty -= 14
        yy = (band_top - bhdr) - max(16, (box_h - bhdr -
                                          _box_body_h(box, bsz2, bld2)) / 2)
        for ln in box["lines"]:
            if ln.get("lead"):
                c.setFillColorRGB(*brand.primary)
                c.setFont(FONT_B, bsz2)
                lw2 = stringWidth(ln["lead"] + " ", FONT_B, bsz2)
                c.drawString(bx + 11, yy, ln["lead"])
                yy = draw_paragraph(c, ln["x"], bx + 11 + lw2, yy,
                                    bw - 22 - lw2, size=bsz2, leading=bld2,
                                    color=brand.ink)
            else:
                yy = draw_paragraph(c, ln["x"], bx + 11, yy, bw - 22,
                                    size=bsz2, leading=bld2, color=brand.ink)
            yy -= 8
        c.setStrokeColorRGB(*brand.muted)
        c.setLineWidth(0.5)
        c.rect(bx, band_top - box_h, bw, box_h, stroke=1, fill=0)


def render_objections(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"])
    terms = p.get("terms", [])
    pad = 12
    sz = 11
    lead = sz * 1.36
    half = (len(terms) + 1) // 2
    colw = (BODY_W - 2 * pad - 24) / 2
    lt = _mix(brand.primary, (1, 1, 1), 0.94)

    def _term_h(items):
        # term name line + centered wrapped definition
        h = 0
        for term, d in items:
            h += lead + len(_wrap(d, FONT, sz, colw)) * lead + 10
        return h

    hdr_t = 24
    box_h = hdr_t + max(_term_h(terms[:half]), _term_h(terms[half:])) + 16
    # KEY TERMS: tinted box with a dark header strip (white title)
    c.setFillColorRGB(*lt)
    c.rect(BODY_L, y - box_h, BODY_W, box_h, stroke=0, fill=1)
    c.setFillColorRGB(*brand.dark)
    c.rect(BODY_L, y - hdr_t, BODY_W, hdr_t, stroke=0, fill=1)
    c.setFillColorRGB(*brand.accent)
    c.rect(BODY_L, y - hdr_t, BODY_W, 3, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(FONT_B, 11)
    c.drawCentredString((BODY_L + BODY_R) / 2, y - hdr_t / 2 - 3.5,
                        "KEY TERMS")
    for ci, chunk in enumerate([terms[:half], terms[half:]]):
        cx = BODY_L + pad + ci * (colw + 24) + colw / 2
        ty = y - hdr_t - 16
        for term, d in chunk:
            c.setFillColorRGB(*brand.primary)
            c.setFont(FONT_B, sz)
            c.drawCentredString(cx, ty, term)
            ty -= lead
            c.setFillColorRGB(*brand.ink)
            c.setFont(FONT, sz)
            for ln in _wrap(d, FONT, sz, colw):
                c.drawCentredString(cx, ty, ln)
                ty -= lead
            ty -= 10
    c.setStrokeColorRGB(*brand.muted)
    c.setLineWidth(0.5)
    c.rect(BODY_L, y - box_h, BODY_W, box_h, stroke=1, fill=0)
    y = y - box_h - 16

    if p.get("objections"):
        items = p["objections"]
        gut = 16
        cw = (BODY_W - gut) / 2
        ohdr = 22
        band = [brand.primary, brand.dark]
        rows_of = [items[r * 2:r * 2 + 2] for r in range((len(items) + 1)
                                                          // 2)]
        tw = cw - 24        # text wrap width inside a card
        nr = len(rows_of)
        avail = y - 72

        # each entry = a centered label line + centered wrapped value;
        # pick the largest font whose rows all fit the page
        def _ob_body_h(ob, osize):
            rlead = osize * 1.34
            h = 0
            for key in ("agree", "bullet", "close"):
                h += rlead + len(_wrap(ob[key], FONT, osize, tw)) * rlead + 5
            return h + 4

        osize = 10.5
        while osize > 8.5:
            rhs = [ohdr + max(_ob_body_h(ob, osize) for ob in row)
                   for row in rows_of]
            if sum(rhs) + 10 * (nr - 1) <= avail:
                break
            osize -= 0.25
        rlead = osize * 1.34
        rhs = [ohdr + max(_ob_body_h(ob, osize) for ob in row)
               for row in rows_of]
        gap = max(10, min((avail - sum(rhs)) / (nr - 1), 40)) if nr > 1 else 10
        oy = y
        for ri, row in enumerate(rows_of):
            ch = rhs[ri]
            for k, ob in enumerate(row):
                ox = BODY_L + k * (cw + gut)
                hdr = band[(ri * 2 + k) % 2]
                tint = _mix(hdr, (1, 1, 1), 0.94)
                c.setFillColorRGB(*tint)
                c.rect(ox, oy - ch, cw, ch, stroke=0, fill=1)
                c.setFillColorRGB(*hdr)
                c.rect(ox, oy - ohdr, cw, ohdr, stroke=0, fill=1)
                c.setFillColorRGB(1, 1, 1)
                c.setFont(FONT_B, 11)
                c.drawCentredString(ox + cw / 2, oy - ohdr / 2 - 3.8,
                                    ob["name"])
                rows3 = (("AGREE", ob["agree"], brand.ink),
                         ("BULLET", ob["bullet"], brand.ink),
                         ("CLOSE", ob["close"], brand.muted))
                body_h = 0
                for lbl, txt, col in rows3:
                    body_h += rlead + len(_wrap(txt, FONT, osize, tw)) \
                        * rlead + 5
                yy = _vcenter(oy - ohdr, ch - ohdr, body_h, osize, min_gap=11,
                              lead=rlead)
                cx = ox + cw / 2
                for lbl, txt, col in rows3:
                    c.setFillColorRGB(*brand.accent)
                    c.setFont(FONT_B, osize - 1)
                    c.drawCentredString(cx, yy, lbl)
                    yy -= rlead
                    c.setFillColorRGB(*col)
                    c.setFont(FONT, osize)
                    for ln in _wrap(txt, FONT, osize, tw):
                        c.drawCentredString(cx, yy, ln)
                        yy -= rlead
                    yy -= 5
                c.setStrokeColorRGB(*brand.muted)
                c.setLineWidth(0.5)
                c.rect(ox, oy - ch, cw, ch, stroke=1, fill=0)
            oy -= ch + gap
    elif p.get("panels"):
        panels = p["panels"]
        gut = 20
        pw = (BODY_W - gut) / 2
        bottom = 72
        isz = 11
        band = [brand.primary, brand.dark]
        maxtl = max(len(_wrap(pan["title"], FONT_B, 11, pw - 16))
                    for pan in panels)
        hdr_p = 18 + maxtl * 12
        ph = y - bottom
        for i, pan in enumerate(panels):
            px = BODY_L + i * (pw + gut)
            hdr = band[i % 2]
            tint = _mix(hdr, (1, 1, 1), 0.94)
            c.setFillColorRGB(*tint)
            c.rect(px, y - ph, pw, ph, stroke=0, fill=1)
            c.setFillColorRGB(*hdr)
            c.rect(px, y - hdr_p, pw, hdr_p, stroke=0, fill=1)
            c.setFillColorRGB(*brand.accent)
            c.rect(px, y - hdr_p, pw, 3, stroke=0, fill=1)
            c.setFillColorRGB(1, 1, 1)
            c.setFont(FONT_B, 11)
            tlines = _wrap(pan["title"], FONT_B, 11, pw - 16)
            hty = y - (hdr_p - len(tlines) * 12) / 2 - 8
            for ln in tlines:
                c.drawCentredString(px + pw / 2, hty, ln)
                hty -= 12
            items = pan["items"]
            body_top = y - hdr_p
            body_bot = y - ph
            inner = pw - 24
            if pan.get("numbered"):
                # numbered SOLUTION steps: circular badge + text, spread to fill
                iheights = [max(24, len(_wrap(it, FONT, isz, inner - 34))
                                * (isz * 1.34) + 6) for it in items]
                slack = max(0, (body_top - body_bot - 20) - sum(iheights))
                # gap before the first item too, so the block sits centered
                sgap = slack / (len(items) + 1)
                yy = body_top - 14 - sgap
                lead_it = isz * 1.34
                for j, it in enumerate(items, 1):
                    ih = iheights[j - 1]
                    nlines = len(_wrap(it, FONT, isz, inner - 34))
                    # center the badge on the item's whole text block
                    bcx = px + 24
                    bcy = yy + isz * 0.30 - (nlines - 1) * lead_it / 2
                    c.setFillColorRGB(*brand.primary)
                    c.circle(bcx, bcy, 10, stroke=0, fill=1)
                    c.setFillColorRGB(1, 1, 1)
                    c.setFont(FONT_B, 10.5)
                    c.drawCentredString(bcx, bcy - 3.6, str(j))
                    draw_paragraph(c, it, px + 42, yy, inner - 34, size=isz,
                                   leading=lead_it, color=brand.ink)
                    yy -= ih + sgap
            else:
                # LATE OBJECTIONS: each quote as a rounded pill, spread to fill
                pill_h = [len(_wrap(it, FONT_B, isz, inner - 20))
                          * (isz * 1.28) + 14 for it in items]
                slack = max(0, (body_top - body_bot - 20) - sum(pill_h))
                sgap = slack / (len(items) + 1)
                yy = body_top - 12 - sgap
                for j, it in enumerate(items):
                    h = pill_h[j]
                    c.setFillColorRGB(1, 1, 1)
                    c.setStrokeColorRGB(*_mix(hdr, (1, 1, 1), 0.55))
                    c.setLineWidth(1)
                    c.roundRect(px + 12, yy - h, inner, h, 6, stroke=1, fill=1)
                    ty2 = yy - (h - len(_wrap(it, FONT_B, isz, inner - 20))
                                * (isz * 1.28)) / 2 - isz * 0.75
                    c.setFillColorRGB(*brand.ink)
                    c.setFont(FONT_B, isz)
                    for ln in _wrap(it, FONT_B, isz, inner - 20):
                        c.drawCentredString(px + 12 + inner / 2, ty2, ln)
                        ty2 -= isz * 1.28
                    yy -= h + sgap
            c.setStrokeColorRGB(*brand.muted)
            c.setLineWidth(0.5)
            c.rect(px, y - ph, pw, ph, stroke=1, fill=0)


def render_bands(c, brand, ctx, p, logo):
    sidebar(c, brand, p.get("sidebar"))
    y = section_title(c, brand, p["title"], subtitle=p.get("subtitle"))
    if p.get("intro"):
        y = draw_paragraph(c, p["intro"], BODY_L, y, BODY_W, size=15,
                           leading=20, font=FONT_B, color=brand.muted,
                           align="center")
        y -= 20
    band_color = {"dark": brand.dark, "accent": brand.accent,
                  "primary": brand.primary}
    bands = p["bands"]
    bottom = 62
    seg = (y - bottom) / len(bands)
    bh = 50
    for b in bands:
        col = band_color.get(b.get("color"), brand.dark)
        c.setFillColorRGB(*col)
        c.rect(BODY_L, y - bh, BODY_W, bh, stroke=0, fill=1)
        tcol = brand.ink if col == brand.accent else (1, 1, 1)
        c.setFillColorRGB(*tcol)
        c.setFont(FONT_B, 31)
        c.drawCentredString((BODY_L + BODY_R) / 2, y - bh + 15, b["name"])
        # subhead + bullets, vertically centered in the region below the band
        content_top = y - bh - 10          # extra breathing room under band
        content_bot = y - seg
        bsz, blead = 14, 20
        blk_h = 26 + _bullet_block_h(b["bullets"], BODY_W - 24, bsz,
                                     lead=blead)
        start = content_top - max(12, (content_top - content_bot - blk_h) / 2)
        c.setFillColorRGB(*brand.primary)
        c.setFont(FONT_I, 14.5)
        c.drawString(BODY_L + 2, start, b["sub"].upper())
        _bullet_block(c, brand, b["bullets"], BODY_L + 10, start - 26,
                      BODY_W - 24, size=bsz, lead=blead)
        y -= seg


RENDERERS = {
    "cover": render_cover,
    "splash": render_splash,
    "schedule": render_schedule,
    "concept": render_concept,
    "promotion": render_promotion,
    "checklist": render_checklist,
    "media": render_media,
    "framework": render_framework,
    "booklist": render_booklist,
    "steps": render_steps,
    "cards": render_cards,
    "fugi": render_fugi,
    "dresscode": render_dresscode,
    "seasonal": render_seasonal,
    "bookshelf": render_bookshelf,
    "paytable": render_paytable,
    "tracker": render_tracker,
    "worksheet": render_worksheet,
    "qrpage": render_qrpage,
    "numbered": render_numbered,
    "garden": render_garden,
    "objections": render_objections,
    "bands": render_bands,
}

# the cover is self-contained => skip the standard footer there only
FULL_BLEED = {"cover"}


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def build_pdf(out_path, company=None, owner=None, location=None,
              brand=None, logo_path=None, pages=None, use_default_logo=True,
              upline=None, schedule=None, backend=None):
    company = company or C.ORIGINAL["company"]
    owner = owner or C.ORIGINAL["owner"]
    location = location or C.ORIGINAL["location"]
    brand = brand or Brand()
    ctx = build_context(company, owner, location, upline=upline,
                        backend=backend)
    pages = pages if pages is not None else C.PAGES

    # per-ICD schedule: swap the schedule page's table for their hours
    if schedule and any(v for k, v in schedule.items()
                        if k.startswith(("office_", "field_"))):
        table = _week_table_from(schedule)
        pages = [dict(p) if p.get("type") == "schedule" else p for p in pages]
        for p in pages:
            if p.get("type") == "schedule":
                p["week_table"] = table

    # Default to the Alphalete logo when none is supplied, so the baseline
    # render is fully branded. Callers generating for OTHER companies pass
    # use_default_logo=False so a missing logo stays blank instead of showing
    # Alphalete's mark.
    if not logo_path and use_default_logo:
        default = Path(__file__).resolve().parents[2] / \
            "resources" / "alphalete-logo-hq.png"
        if default.exists():
            logo_path = str(default)
    logo = None
    if logo_path and Path(logo_path).exists():
        logo = ImageReader(str(logo_path))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.setTitle(f"{company} — Orientation Manual")

    for i, page in enumerate(pages, start=1):
        spec = _fill(page, ctx)
        renderer = RENDERERS.get(spec["type"])
        if renderer is None:
            continue
        renderer(c, brand, ctx, spec, logo)
        if spec["type"] not in ("cover", "splash", "qrpage", "worksheet"):
            header_logo(c, logo)          # logo top-right on content pages
        if spec["type"] not in FULL_BLEED:
            footer(c, brand, ctx, i, logo)
        c.showPage()

    c.save()
    return str(out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a branded Orientation "
                                             "Manual PDF.")
    ap.add_argument("--company", default=None, help="Company name")
    ap.add_argument("--owner", default=None, help="Owner / upline name(s)")
    ap.add_argument("--location", default=None, help="City, ST")
    ap.add_argument("--primary", default=None, help="Primary brand hex")
    ap.add_argument("--accent", default=None, help="Accent brand hex")
    ap.add_argument("--dark", default=None, help="Dark panel hex")
    ap.add_argument("--logo", default=None, help="Path to a logo PNG")
    ap.add_argument("-o", "--out", required=True, help="Output PDF path")
    a = ap.parse_args(argv)

    brand = Brand.from_args(a.primary, a.accent, a.dark)
    path = build_pdf(a.out, company=a.company, owner=a.owner,
                     location=a.location, brand=brand, logo_path=a.logo)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
