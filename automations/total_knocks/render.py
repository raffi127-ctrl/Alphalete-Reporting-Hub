"""Render — draw the report's two PNGs from the freshly-filled tab.

  1. Total Knocks  — columns A–N, in the tab's order (First Knock asc),
     amber theme. Posted to Slack as 'Total Knocks' (🚪).
  2. Time Gaps     — columns ID, Rep, First Knock, Last Knock, Gaps,
     Total Gaps (min), sorted by Total Gaps (min) DESC, teal theme (a
     different header colour so it reads as a separate metric). Posted as
     'Time Gaps' (🕐).

Both read straight from the Sheet so they're faithful screenshots of the tab.
Cross-platform font lookup (Windows + macOS + Linux) — no hard-coded Mac paths.

Standalone:
    .venv/Scripts/python.exe -m automations.total_knocks.render 2026-05-28 [--test-tab]
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from automations.recruiting_report.fill import open_by_key
from automations.total_knocks.aggregate import (
    COL_HRS_KNOCKING,
    hours_between,
    knock_time_key as _knock_time_key,
)
from automations.total_knocks.fill import SHEET_ID, TAB_TEST, TAB_PROD, HEADER_ROW
from automations.total_knocks.pull import (
    COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_GAPS, COL_TOTAL_GAPS,
    COL_TT_BREAKS, COL_TT_SALES_TIME, COL_TT_SALES,
    COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS, COL_TOTAL_TALK_TO,
    COL_NO_ANSWER, COL_TALK_TO_NI, COL_PRES_NI, COL_SALE,
    COL_NOT_INTERESTED, COL_COME_BACK, COL_INACCESSIBLE, COL_DO_NOT_KNOCK,
    COL_VL, COL_PRESENTATION,
    SHEET_COLUMNS,
    _norm,
)

# ---- themes (title bar / header row / alternating stripe) ----
THEME_AMBER = {        # Total Knocks (matches the Hub card #B45309)
    "title_bg": (180, 83, 9),
    "header_bg": (60, 47, 36),
    "stripe": (248, 244, 239),
    # TOTAL row pops against the dark header + white rows (Megan 2026-08-22:
    # "more of a contrasting color") — the title bar's burnt orange.
    "total_bg": (180, 83, 9),
}
THEME_TEAL = {         # Time Gaps — distinct colour (🕐)
    "title_bg": (13, 110, 139),
    "header_bg": (15, 52, 67),
    "stripe": (234, 243, 246),
    "total_bg": (13, 110, 139),
}
TITLE_FG  = (255, 255, 255)
HEADER_FG = (255, 255, 255)
ROW_BG_A  = (255, 255, 255)
GRID      = (224, 214, 204)
TEXT      = (38, 34, 30)
NAME_FG   = (20, 18, 16)

# Total Knocks shows columns A–N (the first 14); Gaps / Total Gaps are excluded.
TOTAL_KNOCKS_NCOL = 14
# The COMBINED fiber Total Knocks board (Raf's Loom 2026-08-22): no ID, Gaps +
# Total Gaps folded in ahead of Last Knock — it replaces the separate Time
# Gaps post for fiber offices. Alphabetical by rep, headers wrapped tight.
COMBINED_KNOCKS_COLUMNS = [
    COL_REP, COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS, COL_TOTAL_TALK_TO,
    # First + Last Knock side by side (Raf 2026-08-22), gaps right after.
    COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_GAPS, COL_TOTAL_GAPS,
    COL_NO_ANSWER, COL_TALK_TO_NI, COL_PRES_NI, COL_COME_BACK, COL_SALE,
    COL_INACCESSIBLE, COL_DO_NOT_KNOCK,
]
# Display-only header shortening on the combined board — the two Not
# Interested labels each carry a long word that alone held their columns
# open (Megan 2026-08-22). Data keys stay the full canonical names.
COMBINED_KNOCKS_DISPLAY = {
    COL_TALK_TO_NI: "Talk To - Not Int",
    COL_PRES_NI: "Pres - Not Int",
}
# Derived at render time (Raf 2026-08-23: "AVG Hrs knocking per day"):
# (last knock − first knock) − total gaps, the same formula his weekly
# dispositions board uses. Rep rows show that day's hours; the TOTAL rows
# show the office average. The column name and the formula live in
# `total_knocks.aggregate` (imported above) so a multi-day fold, which has to
# average the per-day figure rather than re-derive it, shares both.
# "Talk To's per Rep" (Raf 2026-08-25) sits right after the Total Talk To it
# divides. On THIS board it is filled on the summary rows only — the office
# TOTAL and any comparison office's line — because those are the rows that
# aggregate a roster; every other row is already one rep, where the per-rep
# number and Total Talk To are the same figure. It is the comparable one: Raf's
# office and Chan's carry different headcounts, so a raw total says as much
# about roster size as about the day. Same column, same name and same 1-decimal
# format as the DAILY KNOCKS SUMMARY board (captainship_drafts), because the
# two land in front of the same reader.
COL_TALK_TO_PER_REP = "Talk To's per Rep"
# "Total Apps" (Raf, 2026-08-26) — the rep's apps for the board's day, the
# SAME high-level count his weekly dispositions board carries (every product
# type, from the Tableau PRODUCT SALES SUMMARY), so the daily and the weekly
# board can be read against each other without asking which products count.
# It is NOT a knock disposition: ownerville's "Sale" column counts a sale
# logged on a door, the app count comes from the sales system. Only the
# Captainship Report's daily boards ask for it, so it rides an OPTIONAL
# `apps` argument rather than the headers — same reason as title_prefix and
# hide_columns: this renderer also draws Raf's metrics threads, the intraday
# slots and /knocks, and none of those asked for the column.
COL_TOTAL_APPS = "Total Apps"
# "Average App per Rep" (Eve, 2026-08-27) — the same column, the same name and
# the same 1-decimal format the DAILY KNOCKS SUMMARY board above these carries,
# because the two land in front of the same reader on the same email. It rides
# the `apps` argument for the same reason Total Apps does (nobody else asked
# for it), and it sits right after the Total Apps it divides.
#
# Like Talk To's per Rep, it is filled on the SUMMARY rows only — this office's
# TOTAL and any comparison office's line. A rep row IS one rep, where the
# average and Total Apps are the same figure. Divisor: the reps KNOCKING
# (`_knockers`), which is what Talk To's per Rep divides by, what the summary
# board divides by, and the very count Total # of Reps Knocking prints — one
# denominator behind all three, sitting in plain sight on the same row.
COL_AVG_APP_PER_REP = "Average App per Rep"
# "Avg Talk To's per App" (Megan 2026-08-31, "we need it added asap") — the
# column the WEEKLY board has carried since 2026-08-22 and the daily/knock
# boards never got, so the two read differently in front of the same person.
#
# TOTAL talk-tos ÷ apps, Raf's definition, settled on his own worked example:
# "should have been Total Too's / Total apps, my bad" — 83 ÷ 6 = 13.83, the
# how-many-talk-tos-does-an-app-cost read. Two decimals, as the weekly board
# prints it.
#
# Filled on EVERY row that has both numbers, rep rows included: a rep's own
# talk-tos-per-app is a different figure from the office's and is exactly what
# a reader compares down the column. Blank — never 0.00 — when the row has no
# apps, since dividing by nothing is not a zero.
COL_TALK_TO_PER_APP = "Avg Talk To's per App"
# "% Talk To's per Knocks" (Eve, 2026-08-28) — Total Talk To ÷ Total Knocks,
# one decimal (Chan 2026-08-27: 1043 / 5466 = 19.1%). It sits immediately after
# the Total Talk To it divides, ahead of Talk To's per Rep, so the funnel reads
# knocks → talk-tos → the rate between them.
#
# Unlike Talk To's per Rep this one IS filled on every rep row: a rep row is one
# rep, so a per-rep count there would only repeat Total Talk to, but a rep's own
# conversion rate is a different number from the office's and is exactly what a
# reader compares down the column. Blank — never "0.0%" — when the row knocked
# no doors, so a sales-only row carried in for Total Apps shows nothing rather
# than a rate it never earned.
COL_TALK_TO_PCT = "% Talk To's per Knocks"
# "Total # of Reps Knocking" (Eve, 2026-08-28) — how many reps on that row
# knocked at least KNOCKING_MIN_KNOCKS doors. Filled on the SUMMARY rows only
# (this office's TOTAL and any comparison office's line), like Talk To's per
# Rep: a rep row is one rep, where the count is always 1.
COL_REPS_KNOCKING = "Total # of Reps Knocking"
# A rep with 20 knocks or fewer did not work a day of doors (Eve, 2026-08-28) —
# they're a walk-on, a half-hour, or a rep who logged in and left. They still
# count in every total on the board; they just don't count as a rep KNOCKING.
#
# It is also the divisor of Talk To's per Rep and Average App per Rep (Rafael
# approved 2026-08-28: "it kind of raises the bar"). Those two used to divide
# by every rep with any knock at all, which on Rafael's 8/27 board meant 41
# instead of 38 and put a rep who knocked twice in the same denominator as one
# who worked the whole day. Moving the bar moves both averages UP a little
# (12.9 → 13.9 talk-to's per rep that day) and moves no total at all.
KNOCKING_MIN_KNOCKS = 21

# The fill for a rep who has hit the doors target (Raf 2026-08-29). Bright
# enough to find at a glance down a column of forty, dark enough that the
# black number stays readable on it.
GREEN_HIT = (74, 222, 128)

# ---- Rafael's targets (Loom, 2026-08-30) -----------------------------------
# He states these as the numbers he manages his office to, and none of them
# were on any board — the boards showed actuals with no goal line, so a reader
# had to hold the target in their head. Megan 2026-08-30: "we should turn their
# cell green if these are met."
#
#   "If a rep knocks 23 doors an hour on a seven-hour shift, 1:30 to 8:30,
#    that's 160 doors … I'm gonna hammer on 23 doors a freaking hour, it is my
#    number." Saturday is a SIX-hour day: "everyone should be able to knock
#    140. It's 23 doors an hour."
#
# So the doors target is DAY-DEPENDENT and the rate target is not — 23/hr is
# the constant, and 160 / 140 are just that rate times the length of the shift.
# Keeping all four here means the daily and weekly boards cannot drift on what
# "hit the target" means.
KNOCKS_PER_HR_TARGET = 23
DOORS_TARGET_WEEKDAY = 160          # 23/hr x 7h (1:30–8:30)
DOORS_TARGET_SATURDAY = 140         # 23/hr x 6h
# "I need them to have the seven hours" — the 1:30 first knock is what makes
# the 160 reachable, which is why he is cutting atmo to 12:00.
FIRST_KNOCK_TARGET_MIN = 13 * 60 + 30      # 1:30 PM, minutes since midnight


def doors_target(day) -> int:
    """The doors goal for `day` — Saturday is a shorter shift, so a rep who
    hits 140 on a Saturday has met the target and must read green, while the
    same 140 on a Tuesday has not."""
    return (DOORS_TARGET_SATURDAY if getattr(day, "weekday", lambda: 0)() == 5
            else DOORS_TARGET_WEEKDAY)


def _hhmm_to_min(v) -> "int | None":
    """'1:24 PM' → minutes since midnight; None when unreadable/blank."""
    import datetime as _dt
    try:
        t = _dt.datetime.strptime(str(v).strip(), "%I:%M %p")
    except ValueError:
        return None
    return t.hour * 60 + t.minute

# "Avg Knocks / Hr" (Raf 2026-08-28) — a rep's knocks divided by the hours from
# their FIRST knock to their LAST. His words were "calculated from their 1st
# knock time", and Megan settled it as exactly that: the RAW span, NOT
# Avg. Hrs Knocking, which is the same span minus gaps. The two are different
# numbers and the gap-adjusted one flatters a rep who took long breaks — the
# raw span answers "over the stretch you were out, how fast did you knock".
#
# Filled on every rep row (a rep's own rate is what a reader compares down the
# column) and on the summary rows from their own totals. Blank when the span
# cannot be read or is zero, never "0.0" — a rep with one knock has no rate.
COL_KNOCKS_PER_HR = "Avg Knocks / Hr"

# "Avg Doors / Rep" (Raf 2026-08-28, defined by Megan) — total knocks divided
# by the number of reps LISTED on the board.
#
# NOTE THE DENOMINATOR. Its two neighbours, Talk To's per Rep and Average App
# per Rep, divide by the reps KNOCKING (KNOCKING_MIN_KNOCKS+, `_knockers`) —
# the bar Rafael approved on 2026-08-28 because a rep who knocked twice
# shouldn't sit in the same denominator as one who worked the day. This column
# was specified as every rep listed, so on a board with 47 rows and 41 knockers
# it divides by 47 and reads LOWER than the same figure would beside it.
# Deliberate, and flagged: if the three should agree, switch this to
# len(_knockers(sub)) and they do.
#
# Summary rows only — a rep row IS one rep, where it would just repeat Total
# Knocks.
COL_DOORS_PER_REP = "Avg Doors / Rep"

# ON EVERYWHERE (Megan 2026-08-28: "we need to roll that out to everyone
# including what jiriya pulls and what goes in the emails"). They went in
# opt-in and off, so Raf's 15-minute board could be looked at first without
# moving anyone else's; once it read right the answer was every board — the
# metrics threads, the captainship emails, the intraday slots and /knocks.
#
# Still a PARAMETER rather than a bare header entry, so a board that shouldn't
# carry them can say so (rate_columns=False) without a header edit. A shape
# with no Total Knocks column — Time Gaps, TeleMapper — is skipped on its own.
RATE_COLUMNS = (COL_KNOCKS_PER_HR, COL_DOORS_PER_REP)


def _with_derived(cols: list) -> list:
    """The board's OUTPUT columns: the scraped ones plus the ones we compute —
    Reps Knocking after Rep, Talk To % and Talk To's per Rep after Total Talk
    to, Avg. Hrs Knocking after Total Gaps."""
    out = list(cols)
    # COL_REPS_KNOCKING is NOT inserted any more — its number moved into the
    # "#" column on the left (Raf 2026-08-30). The constant stays because the
    # aggregate helpers still write the value under that name.
    out.insert(out.index(COL_TOTAL_TALK_TO) + 1, COL_TALK_TO_PER_REP)
    out.insert(out.index(COL_TOTAL_TALK_TO) + 1, COL_TALK_TO_PCT)
    out.insert(out.index(COL_TOTAL_GAPS) + 1, COL_HRS_KNOCKING)
    return out


# The GOALS row's fill — a muted slate, deliberately NOT green. Green on this
# board means "this rep hit the number"; a green goals row would read as the
# office having hit it (Megan 2026-08-30 asked for the row "between chan and
# the total", i.e. inside the summary block, where that misread is easy).
def _reps_cell(knocking: int, listed: int) -> str:
    """"0 of 3" — reps at the knocking bar, of reps in the field.

    Megan 2026-08-30, on Calvin's board: "the total reps aren't correct, calvin
    has 3 in the field but 0 in his totals". The bare count was right by its own
    rule and useless as printed: at 1pm nobody has 21 knocks yet, so an intraday
    board read 0 all afternoon under a header promising a rep count. Showing
    both numbers keeps the divisor visible (the first one, which Talk To's per
    Rep and Average App per Rep divide by) AND answers "how many are out".
    Same shape the weekly board uses for the same reason."""
    return f"{knocking} of {listed}"


def _is_num(v) -> bool:
    try:
        float(str(v).strip())
        return True
    except (TypeError, ValueError):
        return False


def _pct(part, whole) -> str:
    """'19.1%' — part/whole to one decimal. Blank when there is nothing to
    divide, so a row that never knocked shows an empty cell, not a 0.0%."""
    try:
        part, whole = int(part), int(whole)
    except (TypeError, ValueError):
        return ""
    return f"{part / whole * 100:.1f}%" if whole else ""


COMBINED_KNOCKS_HEADERS = _with_derived(COMBINED_KNOCKS_COLUMNS)
# The cells this board computes rather than reads — blank on a rep row unless
# stated otherwise, so `_combined_sub` never looks for them in the scrape.
DERIVED_COLUMNS = (COL_TALK_TO_PER_REP, COL_TALK_TO_PCT, COL_REPS_KNOCKING,
                   COL_HRS_KNOCKING)
# Time Gaps shows just these, in this order.
TIME_GAPS_COLUMNS = [COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK,
                     COL_GAPS, COL_TOTAL_GAPS]
# TeleMapper Knocks (the gaps-only/NDS stand-in for Total Knocks): mirrors the
# ownerville Time Tracker table itself — Raf's reference screen (2026-08-22) —
# since a wireless office has no Disposition page to count knocks from.
TELEMAPPER_KNOCKS_COLUMNS = [COL_ID, COL_REP, COL_FIRST_KNOCK, COL_LAST_KNOCK,
                             COL_TT_BREAKS, COL_GAPS, COL_TOTAL_GAPS,
                             COL_TT_SALES_TIME, COL_TT_SALES]
# Energy Wells (RES-ENERGYWELL): the wireless shape plus Presentation and VL,
# and it DOES carry Total Talk to — Raf asked for talk-tos on this board and
# knocks_pull computes them over the Energy Wells parts (VL included).
# Gaps + Total Gaps are IN this list on purpose: needs_time_gaps() asks the
# COLUMN LIST whether a separate Time Gaps image is still owed, so carrying
# them here retires that second post and the office gets ONE board — the same
# merge Raf's fiber board got (Megan 2026-08-30: "these 2 should be combined
# just like we have for Raf's").
ENERGYWELL_KNOCKS_COLUMNS = [COL_REP, COL_TOTAL_LEADS_KNOCKED,
                             COL_TOTAL_KNOCKS, COL_TOTAL_TALK_TO,
                             COL_FIRST_KNOCK, COL_LAST_KNOCK,
                             COL_GAPS, COL_TOTAL_GAPS, COL_NO_ANSWER,
                             COL_NOT_INTERESTED, COL_PRESENTATION,
                             COL_COME_BACK, COL_DO_NOT_KNOCK]
# NO INACCESSIBLE COLUMN either (Megan 2026-08-30: "is inaccessible even an
# option for EW?"). It EXISTS in the grid but came through empty for all four
# reps on a full day, so it reads as a disposition these reps never pick. It is
# still scraped, and it changes no arithmetic — talk-tos exclude Inaccessible on
# every shape — so restoring it is one line if it ever gets used.
#
# NO VL COLUMN (Megan 2026-08-30: "drop the VL line"). VL is still SCRAPED and
# still counted in Total Talk to — Raf: "consider VL a talk too" — it just does
# not get a column of its own. The scrape keeping it is also what identifies
# the shape: knocks_shape() tests the ROW KEYS for VL, not this display list.
# Energy Wells gets the SAME derived columns fiber does — Reps Knocking, Talk
# To %, Talk To's per Rep, Avg Hrs Knocking — because it now goes through the
# same renderer. _with_derived needs Rep, Total Talk to and Total Gaps as
# anchors and the Energy Wells set has all three.
ENERGYWELL_KNOCKS_HEADERS = _with_derived(ENERGYWELL_KNOCKS_COLUMNS)

# Wireless (NDS) Total Knocks: the house board's shape, with the wireless
# disposition set — one Not Interested bucket, no Talk-To split, no Sale.
# GAPS + TOTAL GAPS ARE IN THIS LIST for the same reason they are in the
# Energy Wells one: needs_time_gaps() asks the COLUMN LIST whether a separate
# Time Gaps image is still owed, so carrying them here retires that second post
# and the office gets ONE board (Megan 2026-09-01: "get calvin on 1 chart",
# after his grid came back wireless-shaped and split into two images — the same
# merge she asked for on the Energy Wells board on 2026-08-30, "these 2 should
# be combined just like we have for Raf's").
WIRELESS_KNOCKS_COLUMNS = [COL_ID, COL_REP, COL_TOTAL_LEADS_KNOCKED,
                           COL_TOTAL_KNOCKS, COL_FIRST_KNOCK, COL_LAST_KNOCK,
                           COL_GAPS, COL_TOTAL_GAPS,
                           COL_NO_ANSWER, COL_NOT_INTERESTED, COL_COME_BACK,
                           COL_INACCESSIBLE, COL_DO_NOT_KNOCK]

# ---- layout ----
# EVERY BOARD IS DRAWN AT 2x DENSITY (Megan's standing rule, 2026-08-30:
# "everything we give him or anyone as fit to screen as possible WITHOUT losing
# sharpness"). Nothing about the LAYOUT changes — every length and every font
# below is multiplied by the same number, so the board is the identical picture
# with twice the pixels in each direction.
#
# WHY IT IS THE ANSWER TO "BLURRY". These boards are always shown smaller than
# they are drawn: a 48-rep weekly board is ~1750px wide and Gmail's pane is
# 600-1000, so the reader is looking at a 2-3x downscale no matter what we do.
# Drawn at 1x that downscale had barely more source pixels than destination and
# 13px glyph strokes disintegrated; drawn at 2x the same final image is
# resampled from four times the information, and a reader who zooms in finds
# real detail instead of enlarged pixels. It is the retina-asset trick, and it
# is the only lever that adds sharpness — cropping white space (weekly_pdf) and
# resampling well (board_email_html.inline_image_bytes) can only avoid LOSING
# it.
#
# COST: ~2-3x the PNG bytes. That is why the email path pre-shrinks — at 2x the
# wide boards now cross INLINE_MAX_PX, so our one clean Lanczos pass fires and
# the client is left a gentle final shrink instead of a brutal one.
#
# ON since 2026-08-30 (Megan approved the rollout after seeing the 1x/2x
# comparison). SCALE = 1 restores the previous output pixel for pixel.
#
# It is not free, and the two delivery paths are what keep it affordable: a
# 48-rep weekly board goes 1753x2628 -> 3466x5232, so the EMAIL copy is
# pre-shrunk once by us (board_email_html.inline_image_bytes) and the PDF's
# pages are capped (weekly_pdf.PAGE_MAX_PX). Without those two an oversized
# mail would FAIL to send rather than arrive degraded. If either is ever
# loosened, re-measure a built .eml before trusting it.
SCALE      = 2
PAD        = 16 * SCALE
TITLE_H    = 52 * SCALE
HEADER_H   = 40 * SCALE
ROW_H      = 28 * SCALE
# 6, down from 10 (Megan 2026-08-30: "make sure every cell is fit to the text
# it holds — remember Raf doesn't like blank space"). It went 4 -> 10 on
# 2026-08-06 for breathing room, back when every cell was LEFT-aligned and the
# padding was the only thing keeping text off the grid line. Cells centre now,
# so the text sits away from both edges on its own and the padding is pure
# width: at 10 it was 1,080px of a 3,114px board. 6 keeps a visible gutter and
# takes 220px off. Not lower — at 4 the columns start reading as one block.
CELL_PAD_X = 6 * SCALE
MIN_COL_W  = 26 * SCALE
MAX_COL_W  = 640 * SCALE  # was 320 — the old cap truncated wide headers
                  # ("Presentation – Not Interested") and long rep names; widen
                  # so every cell fits its text (Megan 2026-08-06: "all cells
                  # fit to text").
OUT_DIR_DEFAULT = Path("output")


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _read_table(sheet_id: str, tab: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, data_rows) from the tab — only non-empty data rows."""
    sh = open_by_key(sheet_id)
    ws = sh.worksheet(tab)
    vals = ws.get_all_values()
    if not vals:
        return [], []
    header = vals[HEADER_ROW - 1]
    last_col = max((i for i, c in enumerate(header) if c.strip()), default=-1)
    header = header[:last_col + 1]
    rows = []
    for r in vals[HEADER_ROW:]:
        cells = (r + [""] * len(header))[:len(header)]
        if any(c.strip() for c in cells):
            rows.append(cells)
    return header, rows


def _table_from_rows(
    records: list[dict],
) -> tuple[list[str], list[list[str]]]:
    """Build the same (header, data_rows) shape `_read_table` returns, but from
    in-memory records keyed by SHEET_COLUMNS — no Sheet read.

    Used to render directly from a fresh pull (e.g. an impersonated single
    office) without writing a production tab. The header order and stringified
    cells mirror exactly what the filled tab would show, so the rendered image
    is identical to the Sheet-backed one.
    """
    header = list(SHEET_COLUMNS)
    # A multi-day fold carries Avg. Hrs Knocking as DATA (averaged per knocking
    # day) instead of leaving the board to derive it from folded times — see
    # total_knocks.aggregate. Only then does the column join the header.
    if any(COL_HRS_KNOCKING in rec for rec in records):
        header.append(COL_HRS_KNOCKING)
    # ANY OTHER KEY THE RECORDS CARRY. SHEET_COLUMNS is fiber's set, so a
    # campaign with its own dispositions — Energy Wells has Not Interested,
    # Presentation and VL — had those columns dropped here and arrived at the
    # board BLANK, with the totals row reading 0 under each. Appended in first
    # -seen order; a board only draws the columns it asks for, so this cannot
    # widen an existing one.
    for rec in records:
        for k in rec:
            if k not in header:
                header.append(k)
    rows: list[list[str]] = []
    for rec in records:
        cells = ["" if rec.get(c, "") is None else str(rec.get(c, ""))
                 for c in header]
        if any(c.strip() for c in cells):
            rows.append(cells)
    return header, rows


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text or "", font=font))


def _split_word(probe, word: str, fit_w: int, font) -> list[str]:
    """Hyphenate a single too-wide word into chunks that fit fit_w — the
    only way a long word ("Inaccessible") stops dictating its column width."""
    out: list[str] = []
    cur = ""
    for ch in word:
        if cur and _text_w(probe, cur + ch + "-", font) > fit_w:
            out.append(cur + "-")
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out or [word]


def _wrap_header(probe, text: str, fit_w: int, font) -> list[str]:
    """Wrap a header into lines no wider than fit_w; a word wider than fit_w
    hyphenates rather than widening the column."""
    words: list[str] = []
    for w in text.split():
        if _text_w(probe, w, font) > fit_w:
            words.extend(_split_word(probe, w, fit_w, font))
        else:
            words.append(w)
    lines: list[str] = []
    cur = ""
    for w in words:
        joined = w if (cur.endswith("-") or not cur) else f" {w}"
        cand = cur + joined
        if cur and _text_w(probe, cand, font) > fit_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw(header: list[str], rows: list[list[str]], title: str, theme: dict,
          out_path: Path, name_col: int = 1,
          wrap_headers: bool = False,
          highlight_last_row: "bool | int" = False,
          highlight_first_row: "bool | int" = False,
          repeat_header_before: int = 0,
          top_row_colors: "list | None" = None,
          total_row_bgs: "list | None" = None,
          cell_bgs: "dict | None" = None,
          col_min_w: "dict | None" = None) -> Path:
    """Generic table → PNG. `name_col` (0-based) is left-aligned + bold.

    wrap_headers=False (default): every existing board unchanged — column
    width fits the one-line header.
    wrap_headers=True (Raf's Loom 2026-08-22, fiber Total Knocks): columns are
    sized to the DATA, and the header words wrap onto extra lines instead of
    stretching the box — "shorten up these boxes … make the number fit".
    highlight_last_row (Megan 2026-08-22, Weekly Knock Dispositions): the
    last N rows (totals rows) draw on the theme's header colour in bold
    white, so they read apart from the rep rows — True/1 = just the last
    row, an int = that many trailing rows (a host board carrying another
    office's comparison totals). Default False = every existing board
    byte-identical.
    repeat_header_before (Raf 2026-08-23, "add the heads to the bottom"):
    N > 0 re-draws the header band directly above the last N rows, so a
    long board's totals block is readable without scrolling to the top.
    The bottom band uses theme["repeat_header_bg"] when present (Megan
    2026-08-23: lighter purple) — else the header colour.
    cell_bgs (Raf 2026-08-29, "turn the total doors knocked bright green once
    the rep hits 140"): {(row_index, col_index): fill} — paints INDIVIDUAL
    cells over whatever the row already draws. Row indexes are into `rows` as
    passed, so the caller counts the same rows it built. None = every existing
    board byte-identical.
    col_min_w (2026-08-30): {column_index: minimum width in px} — a floor for
    a column whose HEADER carries a long word its data can never justify. The
    oversize-word rule below deliberately hyphenates rather than let
    "Inaccessible" hold a narrow column open (Megan 2026-08-22), which is right
    for a disposition name and wrong for a label naming a number's SOURCE:
    "# Reps (TeleMapper)" over a column of two-digit counts came out
    "TeleM-apper". This is the opt-in exception, per column, so no other board
    moves.
    total_row_bgs (Megan 2026-08-23, "make Chan's row teal"): per-row fills
    for the trailing highlighted rows, in order — e.g. [plum, teal] paints
    the host OFFICE TOTALS plum and the comparison row teal. None = the
    theme default for all. Default None/0 = every existing board
    byte-identical."""
    f_title = _font(26 * SCALE, bold=True)
    f_head  = _font(13 * SCALE, bold=True)
    f_cell  = _font(13 * SCALE)
    f_name  = _font(13 * SCALE, bold=True)
    # Wrapped headers draw smaller (11px, line height 14) — the header is a
    # label, the number is the data, so the label never dictates the box
    # (Megan 2026-08-22: "still too much extra space in these columns").
    f_head_w = _font(11 * SCALE, bold=True)
    head_font = f_head_w if wrap_headers else f_head
    head_lh = (14 if wrap_headers else 16) * SCALE
    head_pad = 4 * SCALE if wrap_headers else CELL_PAD_X

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    ncol = len(header)
    col_w = []
    head_lines: list[list[str]] = []
    for ci in range(ncol):
        w_cells = 0
        cell_font = f_name if ci == name_col else f_cell  # names draw bold
        for r in rows:
            w_cells = max(w_cells,
                          _text_w(probe, r[ci] if ci < len(r) else "", cell_font))
        if wrap_headers:
            # Floor: widest cell — the DATA sets the box. A header word only a
            # little wider than the data widens the box to stay whole ("Gaps",
            # "Knocks"); a truly oversize word ("Inaccessible") hyphenates
            # instead of holding the column open (Megan 2026-08-22).
            fit = max(w_cells, MIN_COL_W, (col_min_w or {}).get(ci, 0))
            for wd in header[ci].split():
                ww = _text_w(probe, wd, head_font)
                if fit < ww <= int(fit * 1.8) + 8:
                    fit = ww
            lines = _wrap_header(probe, header[ci], fit, head_font)
            while len(lines) > 3:      # cap the stack — widen a touch instead
                fit += 6
                lines = _wrap_header(probe, header[ci], fit, head_font)
            w_head = max(_text_w(probe, ln, head_font) for ln in lines)
            head_lines.append(lines)
            # The header gets its own tighter padding, so a long label only
            # widens the box by what the label truly needs.
            col_w.append(min(MAX_COL_W,
                             max(w_cells + 2 * CELL_PAD_X,
                                 w_head + 2 * head_pad,
                                 MIN_COL_W)))
        else:
            w = max(_text_w(probe, header[ci], head_font), w_cells)
            head_lines.append([header[ci]])
            col_w.append(min(MAX_COL_W, max(MIN_COL_W, w + 2 * CELL_PAD_X)))

    n_head_lines = max(len(ls) for ls in head_lines) if head_lines else 1
    header_h = (HEADER_H if n_head_lines == 1
                else 12 + head_lh * n_head_lines)

    table_w = sum(col_w)

    # FIT THE TITLE. The banner is only as wide as the table, and the text was
    # drawn at a fixed 26px with no wrap — so a title longer than the table was
    # silently CLIPPED at the image edge. Harmless while every title was
    # 'TIME GAPS — August 17, 2026'; the moment an office name went in
    # ('TIME GAPS — SAHIL MULTANI — …', 6 narrow columns) the year fell off.
    # Shrink to the largest size that fits (floor 14, still clearly readable);
    # only if even 14 overflows does the canvas widen to hold it, so every
    # existing image whose title already fit is byte-identical.
    title_size = 26 * SCALE
    for size in (s_ * SCALE for s_ in (26, 24, 22, 20, 18, 16, 14)):
        f_title = _font(size, bold=True)
        title_size = size
        if _text_w(probe, title, f_title) + 2 * CELL_PAD_X <= table_w:
            break
    banner_w = max(table_w,
                   _text_w(probe, title, f_title) + 2 * CELL_PAD_X)

    _rep_at = (len(rows) - repeat_header_before
               if 0 < repeat_header_before < len(rows) else -1)
    img_h = (PAD + TITLE_H + header_h + ROW_H * len(rows) + PAD
             + (header_h if _rep_at >= 0 else 0))
    img = Image.new("RGB", (banner_w + 2 * PAD, img_h), (255, 255, 255))
    d = ImageDraw.Draw(img)

    d.rectangle([PAD, PAD, PAD + banner_w, PAD + TITLE_H], fill=theme["title_bg"])
    d.text((PAD + CELL_PAD_X, PAD + (TITLE_H - title_size) // 2), title,
           font=f_title, fill=TITLE_FG)

    def _header_band(y0: int, band_bg=None) -> int:
        x0 = PAD
        for ci in range(ncol):
            d.rectangle([x0, y0, x0 + col_w[ci], y0 + header_h],
                        fill=band_bg or theme["header_bg"])
            lines = head_lines[ci]
            block_h = head_lh * len(lines)
            ty = y0 + (header_h - block_h) // 2 + 1
            for ln in lines:
                # Center each header line in its cell (Megan 2026-08-22).
                tx = x0 + max((col_w[ci] - _text_w(d, ln, head_font)) // 2,
                              head_pad if wrap_headers else CELL_PAD_X)
                d.text((tx, ty), ln, font=head_font, fill=HEADER_FG)
                ty += head_lh
            x0 += col_w[ci]
        return y0 + header_h

    y = _header_band(PAD + TITLE_H)
    _n_hl = int(highlight_last_row or 0)   # True==1; int N = last N rows
    for ri, r in enumerate(rows):
        if ri == _rep_at:
            # The bottom header band — lighter shade when the theme has one
            # (Megan 2026-08-23).
            y = _header_band(y, theme.get("repeat_header_bg"))
        # highlight_first_row mirrors highlight_last_row: True==1; int N =
        # the first N rows (a board carrying other offices' totals above its
        # own, Raf 2026-08-23).
        _n_top = int(highlight_first_row or 0)
        is_total = (_n_hl and ri >= len(rows) - _n_hl) or ri < _n_top
        bg = (theme.get("total_bg", theme["header_bg"]) if is_total
              else ROW_BG_A if ri % 2 == 0 else theme["stripe"])
        # Per-row override for the top block (another office's totals line
        # draws in its own colour — Megan 2026-08-23).
        if ri < _n_top and top_row_colors and ri < len(top_row_colors) \
                and top_row_colors[ri]:
            bg = top_row_colors[ri]
        # …and for the trailing block: total_row_bgs in order — e.g.
        # [plum, teal] = host OFFICE TOTALS plum, comparison row teal
        # (Megan 2026-08-23).
        _blk = ri - (len(rows) - _n_hl) if _n_hl else -1
        if (is_total and total_row_bgs and 0 <= _blk < len(total_row_bgs)
                and total_row_bgs[_blk]):
            bg = total_row_bgs[_blk]
        d.rectangle([PAD, y, PAD + table_w, y + ROW_H], fill=bg)
        x = PAD
        for ci in range(ncol):
            # One cell's own fill, painted over the row band. Drawn before the
            # text so the number sits on top of it.
            _cbg = (cell_bgs or {}).get((ri, ci))
            if _cbg:
                d.rectangle([x, y, x + col_w[ci], y + ROW_H], fill=_cbg)
            val = r[ci] if ci < len(r) else ""
            font = f_name if (ci == name_col or is_total) else f_cell
            # A highlighted row normally draws reversed (white on a dark
            # fill). Pick by LUMINANCE instead of assuming: the GOAL row is
            # deliberately light, and white on it is unreadable. Every
            # existing dark totals fill stays above the threshold, so nothing
            # else changes.
            _rev = (0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]) < 150
            fg = ((HEADER_FG if _rev else TEXT) if is_total
                  else NAME_FG if ci == name_col else TEXT)
            # EVERY cell centres (Megan 2026-08-30, "let's center all text to
            # cell"), which is the house standard these boards are supposed to
            # follow — centred both ways. It used to centre only cells that
            # were entirely digits and never column 0, so a rep name, a time
            # like "2:38 PM", an "8h 49m" gap and the "#" column's own row
            # numbers all sat left while the counts beside them sat centred.
            tx = x + max(CELL_PAD_X, (col_w[ci] - _text_w(d, val, font)) // 2)
            d.text((tx, y + (ROW_H - 13 * SCALE) // 2), val, font=font, fill=fg)
            x += col_w[ci]
        y += ROW_H

    x = PAD
    for ci in range(ncol + 1):
        d.line([x, PAD + TITLE_H, x, img_h - PAD], fill=GRID, width=SCALE)
        if ci < ncol:
            x += col_w[ci]
    yy = PAD + TITLE_H
    d.line([PAD, yy, PAD + table_w, yy], fill=GRID, width=SCALE)
    yy += header_h
    for ri in range(len(rows) + 1):
        if ri == _rep_at and ri:
            yy += header_h                 # jump the bottom header band
        d.line([PAD, yy, PAD + table_w, yy], fill=GRID, width=SCALE)
        yy += ROW_H

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _title_date(target: dt.date, weekday: bool = True) -> str:
    """'Thursday, August 27, 2026'.

    The weekday leads (Eve, 2026-08-28): these boards are read the morning
    after, and forwarded for days after that — "August 27" makes a reader work
    out which day of the week they're looking at before they can judge the
    numbers, and a Saturday's knocks mean something different from a Tuesday's.
    weekday=False drops it for the ends of a multi-day span, where two weekday
    names in one title bar read as clutter, not context."""
    day = f"{target.strftime('%B')} {target.day}, {target.year}"
    return f"{target.strftime('%A')}, {day}" if weekday else day


def _title_span(target: dt.date, end: "dt.date | None" = None) -> str:
    """The board's date line: one day, or a range when `end` is a later day.

    'August 18–23, 2026' inside a month, 'August 30 – September 2, 2026'
    across one, both years spelled out across a year boundary. `end` None or
    equal to `target` returns EXACTLY what the single-day board always said —
    the range feature must be invisible to a one-day request."""
    if end is None or end == target:
        return _title_date(target)
    if (target.year, target.month) == (end.year, end.month):
        return f"{target.strftime('%B')} {target.day}–{end.day}, {end.year}"
    if target.year == end.year:
        return (f"{target.strftime('%B')} {target.day} – "
                f"{end.strftime('%B')} {end.day}, {end.year}")
    return (f"{_title_date(target, weekday=False)} – "
            f"{_title_date(end, weekday=False)}")


def _date_text(target: dt.date, end: "dt.date | None" = None,
               override: str = "") -> str:
    """The date as it appears in a board's title bar.

    `override` (default '') lets ONE caller print it its own way without
    changing every knocks board in the fleet — the 9 PM post wants a compact
    '8/25' where the morning boards keep 'August 25, 2026'. Empty means the
    house format, so every existing caller is untouched."""
    return override or _title_span(target, end)


def _file_span(target: dt.date, end: "dt.date | None" = None) -> str:
    """Filename stem for the span — unchanged for a single day, so nothing
    that globs for an existing board's name stops finding it."""
    if end is None or end == target:
        return target.isoformat()
    return f"{target.isoformat()}_{end.isoformat()}"


def render_total_knocks(target: dt.date, *, tab: str = TAB_PROD,
                        sheet_id: str = SHEET_ID,
                        out_dir: Path = OUT_DIR_DEFAULT,
                        rows: list[dict] | None = None,
                        title_suffix: str = "",
                        end: "dt.date | None" = None,
                        date_text: str = "",
                        title_prefix: str = "",
                        hide_columns: "tuple[str, ...]" = (),
                        extra_totals: "list[tuple] | None" = None,
                        apps: "dict[str, int] | None" = None,
                        rate_columns: bool = True,
                        knocks_green_at: "int | None" = None,
                        sort_by: str = "knocks",
                        base_cols: "list | None" = None,
                        out_cols: "list | None" = None) -> Path:
    """THE fiber knocks board — combined per Raf's Loom (2026-08-22): every
    disposition count PLUS Gaps + Total Gaps (in front of Last Knock), no ID
    column, alphabetical by rep, wrapped headers so the boxes hug the numbers.
    Replaces the separate Time Gaps post for fiber offices. Amber theme.

    `rows` (optional): in-memory records keyed by SHEET_COLUMNS. When given,
    render straight from them instead of reading the Sheet, so callers can
    render a fresh pull without writing a production tab.

    `title_suffix` (optional): office name added to the title —
    'TOTAL KNOCKS — SAHIL MULTANI — August 17, 2026'. Needed when SEVERAL
    offices' images land in the SAME Slack thread, so an image read on its own
    still says whose office it is. Default ('') keeps the original title.

    `end` (optional): the last day of a multi-day board, for the title and the
    filename. The ROWS must already be folded (total_knocks.aggregate) — this
    only labels them. None / same-as-target renders exactly as it always did.

    `apps` (optional): {rep: apps} — forwarded to the house board, which is
    where Total Apps / Average App per Rep / Avg Talk To's per App live. THIS
    ROUTER accepts it because callers reach the boards through here; passing it
    to render_total_knocks only meant /knocks raised
    "render_knocks_boards() got an unexpected keyword argument 'apps'" the
    moment it was wired (2026-08-31). Wireless and gaps-only shapes have no
    talk-to block to divide, so they ignore it.

    `sort_by`: "knocks" (DEFAULT since 2026-08-31) puts the highest Total
    Knocks first; "rep" is alphabetical. These boards are read as
    leaderboards — Raf asked for the ranking on his, and Megan pointed at
    Cody's still coming out A-Z ("shouldn't this be ordered by total knocks
    high to low?"), so it is now the default everywhere rather than something
    each caller opts into and most forget.

    It has to live HERE: this function re-sorts the rows it is given, so a
    caller that pre-sorts its own list silently has that order discarded.

    `hide_columns` (optional): columns to leave OFF this board. For a derived
    column that only carries a number on the TOTAL row — Talk To's per Rep is
    one: a rep row IS one rep, so per-rep there would just repeat Total Talk to
    — the cost of keeping it is a blank stripe down the whole board. Eve
    2026-08-25 asked for it off the Captainship Report's per-owner boards,
    where the same figure per ICD already sits on the DAILY KNOCKS SUMMARY
    right above. A PARAMETER, not a header edit, for the same reason as
    title_prefix: this renderer also draws the metrics threads, the intraday
    slots and /knocks, and Raf asked for that column — dropping it from the
    header would take it off his boards too. Default () = unchanged.

    `title_prefix` (optional): words in front of "TOTAL KNOCKS" — e.g.
    "DAILY " for the per-owner boards inside a Captainship Report (Eve
    2026-08-25). It is a PARAMETER rather than a new title because this one
    renderer draws the same board for the metrics threads, the intraday slots
    and the on-demand /knocks replies; renaming it in place would relabel all
    of them. Default "" keeps every existing board byte-identical.

    `apps` (optional): {rep name: apps that day} — adds the "Total Apps"
    column right after Talk To's per Rep (Raf 2026-08-26), so the funnel reads
    knocks -> talk-tos -> apps. The caller does the NAME MATCHING (the apps
    come from Tableau, the rows from ownerville, and the two spell reps
    differently): keys must be the rep names as they appear in `rows`, which
    is what weekly_knock_dispositions.board.match_apps returns. A rep absent
    from the dict shows 0; the TOTAL and any comparison office's line sum the
    column exactly as drawn, so a rep who sold without knocking has to be in
    `rows` too — otherwise the total silently disagrees with the column above
    it. An extra_totals entry may carry that office's own apps dict as a third
    element. Default None leaves the column OFF entirely, so every other board
    this renderer draws stays byte-identical. Since 2026-08-28 it also brings
    "Average App per Rep" right behind it (Eve) — the per-rep figure the DAILY
    KNOCKS SUMMARY board above already shows per ICD, on the summary rows only,
    over the reps who knocked. Same argument, so the same boards that never
    asked for Total Apps still don't get either column.
    """
    if rows is not None:
        header, rows = _table_from_rows(rows)
    else:
        header, rows = _read_table(sheet_id, tab)
    if not rows:
        raise RuntimeError(f"No data rows in tab {tab!r} to render.")
    _base = list(base_cols or COMBINED_KNOCKS_COLUMNS)
    _out = list(out_cols or COMBINED_KNOCKS_HEADERS)
    sub = _combined_sub(header, rows, sort_by=sort_by, where=f"tab {tab!r}",
                        base_cols=_base, out_cols=_out)
    totals = _combined_totals("TOTAL", sub, _out)

    # Extra offices' totals rows ABOVE ours (Raf 2026-08-23: "add Chan's
    # totals above ours daily") — each is (office name, records keyed by
    # SHEET_COLUMNS); only their TOTAL line shows, not their reps.
    extra_rows: list[list[str]] = []
    extra_apps: list = []
    extra_knockers: list = []
    extra_listed: list = []
    extra_rates: list = []
    for item in (extra_totals or []):
        # (name, rows) or (name, rows, apps) — the third element is that
        # office's own {rep: apps}; only its SUM shows, as its reps never do.
        name, recs = item[0], item[1]
        x_apps = item[2] if len(item) > 2 else None
        x_header, x_rows = _table_from_rows(recs)
        if not x_rows:
            continue
        # The comparison office is scraped in ITS shape; rendered in OURS, so
        # a column it does not have blanks instead of failing the board.
        x_sub = _combined_sub(x_header, x_rows, where=f"extra office {name!r}",
                              base_cols=_base, out_cols=_out)
        extra_rows.append(_combined_totals(f"{name.upper()} TOTAL", x_sub, _out))
        extra_apps.append(sum(x_apps.values()) if x_apps else None)
        # Its Average App per Rep divisor, taken here while its rep rows still
        # exist — only its TOTAL line survives into the drawn table.
        extra_knockers.append(len(_knockers(x_sub, _out)))
        # Its LISTED rep count, taken while its rep rows still exist — only
        # its TOTAL line survives into the drawn table.
        extra_listed.append(len(x_sub))
        # Its average rep rate, taken here for the same reason — only its
        # TOTAL line survives into the drawn table.
        extra_rates.append(_mean_rate(x_sub))

    hrs_pos = _out.index(COL_HRS_KNOCKING)
    tg_pos = _out.index(COL_TOTAL_GAPS)
    for r in sub:
        r[tg_pos] = _fmt_hm(r[tg_pos])
        r[hrs_pos] = _fmt_hm(r[hrs_pos])
    for t in extra_rows + [totals]:
        t[tg_pos] = _fmt_hm(t[tg_pos])
        t[hrs_pos] = _fmt_hm(t[hrs_pos])
    # Office rows at the TOP, right under the header (Raf 2026-08-22). An
    # extra office's line draws teal so it can't be misread as ours
    # (Megan 2026-08-23).
    table = extra_rows + [totals] + sub
    _colors = ([THEME_TEAL["title_bg"]] * len(extra_rows)
               + [THEME_AMBER["total_bg"]])
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    cols = list(_out)
    disp = [COMBINED_KNOCKS_DISPLAY.get(c, c) for c in cols]
    if hide_columns:
        # Drop by NAME, then take the same positions out of every row — the
        # totals and comparison rows included, so nothing shifts under a header.
        keep = [i for i, c in enumerate(cols)
                if c not in hide_columns]
        cols = [cols[i] for i in keep]
        disp = [disp[i] for i in keep]
        table = [[r[i] for i in keep] for r in table]
    # This office's reps-knocking count. Taken once: it is both the Average App
    # per Rep divisor and the number the "#" column prints on the TOTAL row,
    # and the two must not drift.
    n_knockers = len(_knockers(sub, _out))
    if apps is not None:
        # AFTER the hide pass, and by NAME on what survived it, so the column
        # lands next to the talk-to block on a board that hid Talk To's per Rep
        # just as it does on one that kept it.
        _insert_apps_column(cols, disp, table, apps,
                            n_extra=len(extra_rows), extra_apps=extra_apps,
                            n_knockers=n_knockers,
                            extra_knockers=extra_knockers)
    _cell_bgs: dict = {}
    if rate_columns:
        # After the hide and apps passes, by NAME on what survived, same as
        # the apps column — so it lands correctly on a board that hid others.
        _insert_rate_columns(cols, disp, table, n_extra=len(extra_rows),
                             extra_listed=extra_listed,
                             extra_rates=extra_rates)
    # Raf 2026-08-29 ("turn the total doors knocked bright green once the rep
    # hits 140"), widened 2026-08-30 to the other two targets he states in the
    # same breath. REP ROWS ONLY throughout — a green office total would be a
    # different claim, and the reps are who the targets are for.
    #
    # The doors goal defaults to the DAY's target (160 weekday / 140 Saturday)
    # rather than a flat 140: on a Tuesday the old flat number greened a rep
    # who was 20 doors short of what Rafael actually asks for. An explicit
    # knocks_green_at still wins, so a caller that wants its own bar keeps it.
    _goal = knocks_green_at or doors_target(target)
    _green = [(COL_TOTAL_KNOCKS,
               lambda v: v.replace(",", "").isdigit()
               and int(v.replace(",", "")) >= _goal),
              (COL_KNOCKS_PER_HR,
               lambda v: _is_num(v) and float(v) >= KNOCKS_PER_HR_TARGET),
              # EARLIER is better here, unlike the other two.
              (COL_FIRST_KNOCK,
               lambda v: (_hhmm_to_min(v) or 10 ** 6)
               <= FIRST_KNOCK_TARGET_MIN)]
    for _col, _hit in _green:
        if _col not in cols:
            continue
        _ci = cols.index(_col)
        for _ri, _row in enumerate(table):
            if _ri <= len(extra_rows):      # comparison rows + our TOTAL
                continue
            _v = str(_row[_ci]).strip()
            if _v and _hit(_v):
                _cell_bgs[(_ri, _ci)] = GREEN_HIT

    # NO goals row (Raf, 2026-08-30 — added and removed the same day). The
    # TARGETS live on: they are what turns a cell green, they just aren't
    # printed as a row of their own any more.
    _n_summary = len(extra_rows) + 1      # comparison rows + our TOTAL
    # The reps-knocking count for each summary line, in the order those rows
    # are drawn (comparison offices first, then this office's TOTAL), so they
    # land in the "#" column instead of a column of their own.
    # summary_values covers the rows OUTSIDE the numbering window, in order:
    # the comparison offices, then GOALS (its bar, not a count), then ours.
    number_rows(cols, disp, table, first=_n_summary,
                summary_values=[_reps_cell(k, n) for k, n in
                                zip(extra_knockers, extra_listed)]
                + [_reps_cell(n_knockers, len(sub))])
    if _cell_bgs:
        # number_rows inserted a "#" column at 0, so every recorded column
        # index shifts one right. Done here rather than at record time so the
        # rule above reads against the columns it actually tested.
        _cell_bgs = {(r, c + 1): v for (r, c), v in _cell_bgs.items()}
    # The "#" column's header names where its count comes from, and
    # "(TeleMapper)" is wider than two-digit counts will ever justify — so it
    # gets an explicit floor rather than hyphenating mid-word.
    _min_w = {}
    if disp and disp[0] == COL_NUM_HEADER:
        _probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        _min_w[0] = max(_text_w(_probe, w, _font(11 * SCALE, bold=True))
                        for w in COL_NUM_HEADER.split())
    return _draw(disp, table,
                 f"{title_prefix}TOTAL KNOCKS — {_office}"
                 f"{_date_text(target, end, date_text)}",
                 THEME_AMBER,
                 out_dir / f"total_knocks_{_file_span(target, end)}.png",
                 name_col=1, wrap_headers=True,
                 highlight_first_row=_n_summary,
                 top_row_colors=_colors, cell_bgs=_cell_bgs or None,
                 col_min_w=_min_w or None)


# The "#" column's header. It numbers the rep rows AND carries each summary
# row's rep count, so it says where that count comes from (Raf 2026-08-30:
# "move the total reps being counted via telemapper to the left side, the way
# that you just made the weekly report … can we just label it, though, so that
# people know where that number is coming from?"). Wrapped headers put it on
# three short lines, so it costs the column almost no width.
COL_NUM_HEADER = "# Reps (TeleMapper)"


def number_rows(cols: list, disp: list, table: list, *,
                first: int = 0, count: "int | None" = None,
                summary_values: "list | None" = None) -> None:
    """Put a "#" column in front of the board IN PLACE, numbering the LISTED
    rows 1..N in the order they are drawn (Eve, 2026-08-28).

    These boards are read off a phone screenshot and talked through out loud —
    "the fourth one down" needs a number on the row, and a roster of forty is
    where a reader loses their line between the name and the far-right columns.

    `first` is the index of the first row to number and `count` how many
    (None = to the end of the table). The window is a parameter because the two
    boards put their summary rows at opposite ends: an owner's board leads with
    them, the captainship summary trails.

    `summary_values` fills the rows OUTSIDE that window, in order — the reps
    knocking on each TOTAL / comparison line (Raf 2026-08-30, moving that count
    out of its own column and over to the left). Those rows used to stay blank,
    on the reasoning that a number there reads as a row index; a count on a
    reversed-bold totals row does not, and the header now names what it is.
    Omit it and they stay blank, exactly as before."""
    stop = len(table) if count is None else first + count
    cols.insert(0, COL_NUM_HEADER)
    disp.insert(0, COL_NUM_HEADER)
    pending = list(summary_values or [])
    for i, row in enumerate(table):
        if first <= i < stop:
            row.insert(0, str(i - first + 1))
        else:
            row.insert(0, str(pending.pop(0)) if pending else "")


def _apps_key(name: str) -> str:
    """Rep-name key for the apps lookup — collapsed whitespace, case-folded.
    The caller already matched Tableau's spelling to ownerville's; this only
    keeps a stray double space or a capital from losing a matched rep."""
    return " ".join(str(name or "").split()).lower()


def _sub_rate(row: list) -> "float | None":
    """One COMBINED_KNOCKS_HEADERS-shaped row's knocks-per-hour, or None.

    The same arithmetic _insert_rate_columns does on the drawn table, but
    against the full header order — used for a COMPARISON office, whose rep
    rows exist only before the table is assembled.
    """
    tk = COMBINED_KNOCKS_HEADERS.index(COL_TOTAL_KNOCKS)
    fk = COMBINED_KNOCKS_HEADERS.index(COL_FIRST_KNOCK)
    lk = COMBINED_KNOCKS_HEADERS.index(COL_LAST_KNOCK)
    first, last = _knock_time_key(str(row[fk])), _knock_time_key(str(row[lk]))
    if first >= 24 * 60 or last >= 24 * 60 or last <= first:
        return None
    v = str(row[tk]).strip().replace(",", "")
    if not v.isdigit() or not int(v):
        return None
    return int(v) / ((last - first) / 60.0)


def _mean_rate(sub: list) -> str:
    """A roster's average rep rate, one decimal — '' when nobody has one."""
    rates = [r for r in (_sub_rate(row) for row in sub) if r]
    return "%.1f" % (sum(rates) / len(rates)) if rates else ""


def _insert_rate_columns(cols: list, disp: list, table: list, *,
                         n_extra: int, extra_listed: "list | None" = None,
                         extra_rates: "list | None" = None) -> None:
    """Put "Avg Knocks / Hr" and "Avg Doors / Rep" in IN PLACE, after Total
    Knocks — the column both divide, so the board reads knocks → how fast →
    how many each.

    `table` is extra-office TOTAL rows, then this office's TOTAL, then the rep
    rows, the order render_total_knocks builds.

    Knocks/Hr uses the RAW span, first knock to last, per Raf and Megan — not
    Avg. Hrs Knocking, which is that span minus gaps. On the TOTAL rows the
    times are already the office's AVERAGE first and last, so the rate is the
    office's day on the same definition.

    Doors/Rep is summary-only and divides by the reps LISTED. This office's
    listed count is the rep rows right here; an extra office's rep rows never
    reach this table, so its count comes from `extra_listed` — blank when the
    caller didn't pass one, because blank is honest for "not counted" where a
    0 would read as an office that knocked nothing.

    Blank, never 0.0, wherever the span or the divisor is missing: a rep with
    one knock has no rate and did not earn a zero.
    """
    at = (cols.index(COL_TOTAL_KNOCKS) + 1 if COL_TOTAL_KNOCKS in cols
          else len(cols))
    tk_at = cols.index(COL_TOTAL_KNOCKS) if COL_TOTAL_KNOCKS in cols else None
    f_at = cols.index(COL_FIRST_KNOCK) if COL_FIRST_KNOCK in cols else None
    l_at = cols.index(COL_LAST_KNOCK) if COL_LAST_KNOCK in cols else None
    if tk_at is None:
        return

    def _n(v) -> int:
        v = str(v).strip().replace(",", "")
        return int(v) if v.isdigit() else 0

    def _rate(row) -> str:
        if f_at is None or l_at is None:
            return ""
        first = _knock_time_key(str(row[f_at]))
        last = _knock_time_key(str(row[l_at]))
        if first >= 24 * 60 or last >= 24 * 60 or last <= first:
            return ""
        hours = (last - first) / 60.0
        knocks = _n(row[tk_at])
        return f"{knocks / hours:.1f}" if hours and knocks else ""

    n_listed = max(0, len(table) - n_extra - 1)
    per_hr, per_rep = [], []
    for i, row in enumerate(table):
        if i < n_extra:
            # A comparison office's own average rep rate, computed by the
            # caller while its rep rows still existed (Raf 2026-08-29: "can we
            # get chans averages doors knocked per hr?"). Blank stays blank
            # when it could not be worked out — never a number we didn't earn.
            x = (extra_rates[i] if extra_rates and i < len(extra_rates)
                 else "")
            per_hr.append(x or None)
        elif i == n_extra:
            # SUMMARY ROWS DO NOT GET total ÷ span, and this is a real bug that
            # shipped: those rows carry the AVERAGE of the reps' first and last
            # knock, so early in the day the span is a minute or two and the
            # office "rate" explodes — Raf's 10:45 board read 480.0 against
            # reps of 40 and blank (Megan 2026-08-29: "not adding correctly").
            # The office's own figure is the AVERAGE OF THE REP RATES, filled
            # in below once they exist; a comparison office has no rep rows
            # here at all, so it gets a blank rather than a fabricated number.
            per_hr.append(None)
        else:
            per_hr.append(_rate(row))
        if i < n_extra:
            x = (extra_listed[i] if extra_listed and i < len(extra_listed)
                 else None)
            per_rep.append(f"{_n(row[tk_at]) / x:.1f}" if x else "")
        elif i == n_extra:
            per_rep.append(f"{_n(row[tk_at]) / n_listed:.1f}"
                           if n_listed else "")
        else:
            per_rep.append("")          # a rep row IS one rep
    # The office TOTAL's rate = the mean of its reps' rates, over the reps that
    # HAVE one. Comparison rows stay blank: their reps never reach this table.
    _rates = [float(v) for v in per_hr[n_extra + 1:] if v]
    per_hr[n_extra] = ("%.1f" % (sum(_rates) / len(_rates))) if _rates else ""
    # (comparison rows above were filled from extra_rates and are left alone)
    per_hr = ["" if v is None else v for v in per_hr]

    for name, vals in ((COL_DOORS_PER_REP, per_rep),
                       (COL_KNOCKS_PER_HR, per_hr)):
        cols.insert(at, name)
        disp.insert(at, COMBINED_KNOCKS_DISPLAY.get(name, name))
        for row, v in zip(table, vals):
            row.insert(at, v)


def _insert_apps_column(cols: list, disp: list, table: list,
                        apps: dict, *, n_extra: int, extra_apps: list,
                        n_knockers: int = 0,
                        extra_knockers: "list | None" = None) -> None:
    """Put "Total Apps" — and the "Average App per Rep" that divides it — into
    `cols`/`disp`/`table` IN PLACE, right after Talk To's per Rep (or after
    Total Talk to when that column was hidden).

    `table` is laid out extra-office TOTAL rows, then this office's TOTAL,
    then the rep rows — the order render_total_knocks builds. Rep rows read
    `apps`; the TOTAL row sums THE COLUMN as drawn (never the dict), so the
    number under the header is always the sum of the numbers above it; an
    extra office shows its own total, or blank when the caller didn't pass
    one — blank being the honest cell for "not pulled", where 0 would read as
    an office that sold nothing.

    `n_knockers` / `extra_knockers` are the per-rep DIVISORS: how many reps
    actually knocked, for this office and for each extra office in the same
    order as `extra_apps`. They come from the caller because the rep rows of
    an extra office never reach this table — only its TOTAL line does. A row
    whose apps cell is blank, or whose divisor is 0, gets a BLANK average and
    never a 0: the office didn't earn that zero, we just couldn't divide."""
    if COL_TALK_TO_PER_REP in cols:
        at = cols.index(COL_TALK_TO_PER_REP) + 1
    elif COL_TOTAL_TALK_TO in cols:
        at = cols.index(COL_TOTAL_TALK_TO) + 1
    else:                                   # no talk-to block at all
        at = len(cols)
    rep_at = cols.index(COL_REP)
    by_key = {_apps_key(k): v for k, v in apps.items()}
    values: list = []
    for i, row in enumerate(table):
        if i < n_extra:
            x = extra_apps[i] if i < len(extra_apps) else None
            values.append("" if x is None else str(x))
        elif i == n_extra:
            values.append(None)             # this office's TOTAL — filled below
        else:
            values.append(str(by_key.get(_apps_key(row[rep_at]), 0)))
    if n_extra < len(values):
        reps = values[n_extra + 1:]
        values[n_extra] = str(sum(int(v) for v in reps if str(v).isdigit()))
    # Per-rep averages, computed off the column AS DRAWN (same rule as the
    # total above): whatever the reader sees in Total Apps is what this
    # divides. Rep rows stay blank — a rep row is already one rep.
    divisors = list(extra_knockers or [])
    avgs: list = []
    for i, v in enumerate(values):
        if i > n_extra:
            avgs.append("")                 # a rep row
            continue
        n = n_knockers if i == n_extra else (divisors[i] if i < len(divisors)
                                             else 0)
        avgs.append(f"{int(v) / n:.1f}" if str(v).isdigit() and n else "")
    # Talk-tos per app, from the Total Talk to already on the row and the apps
    # column as drawn — so it can never disagree with the two numbers beside it.
    tt_at = cols.index(COL_TOTAL_TALK_TO) if COL_TOTAL_TALK_TO in cols else None
    per_app: list = []
    for row, v in zip(table, values):
        tt = str(row[tt_at]).strip() if tt_at is not None else ""
        per_app.append(f"{int(tt) / int(v):.2f}"
                       if tt.isdigit() and str(v).isdigit() and int(v)
                       else "")

    cols.insert(at, COL_TOTAL_APPS)
    disp.insert(at, COL_TOTAL_APPS)
    cols.insert(at + 1, COL_AVG_APP_PER_REP)
    disp.insert(at + 1, COL_AVG_APP_PER_REP)
    cols.insert(at + 2, COL_TALK_TO_PER_APP)
    disp.insert(at + 2, COL_TALK_TO_PER_APP)
    for row, v, a, pa in zip(table, values, avgs, per_app):
        row.insert(at, v)
        row.insert(at + 1, a)
        row.insert(at + 2, pa)


def _gap_min(v: str) -> int:
    v = (v or "").strip()
    return int(v) if v.isdigit() else -1


def _fmt_hm(v: str) -> str:
    """Minutes int → 'Xh Ym' (matching how Ownerville displays it, e.g. 79 ->
    '1h 19m', 180 -> '3h 0m'). Blank / non-numeric passes through unchanged."""
    v = (v or "").strip()
    if not v.isdigit():
        return v
    m = int(v)
    return f"{m // 60}h {m % 60}m"


def render_time_gaps(target: dt.date, *, tab: str = TAB_PROD,
                     sheet_id: str = SHEET_ID,
                     out_dir: Path = OUT_DIR_DEFAULT,
                     rows: list[dict] | None = None,
                     title_suffix: str = "",
                     end: "dt.date | None" = None,
                     date_text: str = "") -> Path:
    """PNG 2 — ID, Rep, First/Last Knock, Gaps, Total Gaps (min), sorted by
    Total Gaps (min) desc, teal theme. Total Gaps is shown as 'Xh Ym' (like
    Ownerville); the Sheet column itself stays in plain minutes.

    `rows` (optional): in-memory records keyed by SHEET_COLUMNS. When given,
    render straight from them instead of reading the Sheet (this function does
    its own Total-Gaps-desc sort, so no pre-sort is needed). Default (None)
    preserves the exact Sheet-reading behaviour.

    `title_suffix` (optional): office name added to the title, same as
    render_total_knocks — needed when several offices' images land in the SAME
    Slack thread. Default ('') keeps the original title.
    """
    if rows is not None:
        header, rows = _table_from_rows(rows)
    else:
        header, rows = _read_table(sheet_id, tab)
    if not rows:
        raise RuntimeError(f"No data rows in tab {tab!r} to render.")
    idx = {}
    for i, h in enumerate(header):
        k = _norm(h)
        if k and k not in idx:
            idx[k] = i
    missing = [c for c in TIME_GAPS_COLUMNS if _norm(c) not in idx]
    if missing:
        raise RuntimeError(f"Tab {tab!r} missing column(s) for Time Gaps: "
                           f"{missing}. Header: {header}")
    sel = [idx[_norm(c)] for c in TIME_GAPS_COLUMNS]
    sub = [[(r[i] if i < len(r) else "") for i in sel] for r in rows]
    tg_pos = TIME_GAPS_COLUMNS.index(COL_TOTAL_GAPS)
    # Sort by numeric minutes (desc) BEFORE formatting to 'Xh Ym'.
    sub.sort(key=lambda r: _gap_min(r[tg_pos]), reverse=True)
    for r in sub:
        r[tg_pos] = _fmt_hm(r[tg_pos])
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    return _draw(list(TIME_GAPS_COLUMNS), sub,
                 f"TIME GAPS — {_office}{_date_text(target, end, date_text)}",
                 THEME_TEAL,
                 out_dir / f"time_gaps_{_file_span(target, end)}.png")


def _combined_sub(header: list[str], rows: list[list[str]],
                  sort_by: str = "rep",
                  where: str = "",
                  base_cols: "list | None" = None,
                  out_cols: "list | None" = None) -> list[list[str]]:
    """Select + order one office's rows into the combined-board shape:
    `out_cols` order (Hrs Knocking computed), alphabetical by rep unless
    sort_by="knocks". Gap/hour cells stay raw minutes — the caller formats them.

    `base_cols`/`out_cols` default to fiber's, so every existing board is
    unchanged. Energy Wells passes its own pair, which is what lets that office
    have the SAME board as Raf — totals row, derived averages, the lot —
    instead of the flat table it started with.

    A column the source genuinely lacks comes through BLANK rather than
    raising. That is what lets a comparison office of a different shape (Chan
    is fiber; Calvin's board is Energy Wells) show the columns the two share
    and leave the rest empty, which is honest, where a hard failure would mean
    no board at all."""
    idx = {}
    for i, h in enumerate(header):
        k = _norm(h)
        if k and k not in idx:
            idx[k] = i
    base_cols = list(base_cols or COMBINED_KNOCKS_COLUMNS)
    out_cols = list(out_cols or COMBINED_KNOCKS_HEADERS)
    # The identity columns are non-negotiable — without them there is no row.
    # The rest may be absent (a cross-shape comparison office) and blank out.
    required = [COL_REP, COL_TOTAL_KNOCKS]
    missing = [c for c in required if _norm(c) not in idx]
    if missing:
        raise RuntimeError(f"{where or 'data'} missing column(s) for Total "
                           f"Knocks: {missing}. Header: {header}")
    src = {c: i for i, c in enumerate(base_cols)}
    fk, lk, tg = src[COL_FIRST_KNOCK], src[COL_LAST_KNOCK], src[COL_TOTAL_GAPS]
    # Hrs Knocking is (last − first) − total gaps… UNLESS the caller already
    # computed it. A multi-day fold must AVERAGE the per-day figure; re-deriving
    # it from folded cells would subtract a week of gaps from one day's span and
    # quietly print a wrong number. See total_knocks.aggregate.
    pre = idx.get(_norm(COL_HRS_KNOCKING))
    sel = [idx.get(_norm(c)) for c in base_cols]

    def _cell(r: list[str], i) -> str:
        return "" if i is None else (r[i] if i < len(r) else "")

    sub = []
    for r in rows:
        base = [_cell(r, i) for i in sel]
        if pre is None:
            hrs = hours_between(base[fk], base[lk], base[tg])
            hrs = "" if hrs is None else str(hrs)
        else:
            hrs = str(_cell(r, pre))
        # Talk To's per Rep is blank here on purpose: this row IS one rep, so
        # the number would only repeat Total Talk to. `_combined_totals` fills
        # it on the rows that actually aggregate a roster.
        # Talk To % is the one derived cell a REP row carries: it's that rep's
        # own conversion rate, not a repeat of a count next to it.
        derived = {COL_HRS_KNOCKING: hrs, COL_TALK_TO_PER_REP: "",
                   COL_REPS_KNOCKING: "",
                   COL_TALK_TO_PCT: _pct(base[src[COL_TOTAL_TALK_TO]],
                                         base[src[COL_TOTAL_KNOCKS]])}
        # Built whole, BEFORE the sort — assembling by header name keeps every
        # derived cell tied to its own rep no matter how the table is ordered.
        sub.append([derived[c] if c in derived
                    else (base[src[c]] if c in src else "")
                    for c in out_cols])
    rep_pos = out_cols.index(COL_REP)
    if sort_by == "knocks":
        # Highest total knocks first — a leaderboard, not a roster (Raf
        # 2026-08-29). THIS is the sort that decides the board: a caller that
        # pre-sorts its rows has that order thrown away here, which is exactly
        # what happened when gap_alerts sorted its rows and the board still
        # came out A-Z. Ties fall back to name so reps who are level don't
        # shuffle between ticks.
        tk_pos = out_cols.index(COL_TOTAL_KNOCKS)

        def _tk(r):
            v = str(r[tk_pos]).strip().replace(",", "")
            return int(v) if v.isdigit() else 0

        sub.sort(key=lambda r: (-_tk(r), str(r[rep_pos]).strip().lower()))
    else:
        sub.sort(key=lambda r: str(r[rep_pos]).strip().lower())
    return sub


def _knockers(sub: list[list[str]],
              out_cols: "list | None" = None) -> list[list[str]]:
    """The rows that count as a rep KNOCKING — KNOCKING_MIN_KNOCKS doors or
    more. This is both the Total # of Reps Knocking count and the divisor of
    the two per-rep columns, deliberately the SAME function so the head count
    a reader sees and the number the averages divided by can never drift.

    Rafael approved the stricter line 2026-08-28: it was every rep with any
    knock at all, which put a rep who knocked twice in the same denominator as
    one who worked a full day and pulled the average down for a reason that
    isn't performance. Their knocks, talk-to's and apps still count in every
    total on the board — they just aren't a head.

    A sales-only row (no knocks, carried in for the Total Apps column) fails
    the same test, as it always did."""
    tk = (out_cols or COMBINED_KNOCKS_HEADERS).index(COL_TOTAL_KNOCKS)
    return [r for r in sub
            if _to_int_or_zero(r[tk]) >= KNOCKING_MIN_KNOCKS]


def _to_int_or_zero(v) -> int:
    v = str(v).strip()
    return int(v) if v.isdigit() else 0


def _combined_totals(label: str, sub: list[list[str]],
                     out_cols: "list | None" = None) -> list[str]:
    """One office's TOTAL line for the combined board: counts sum, the knock
    times average (reps with a parsable time only), Total Gaps sums, Hrs
    Knocking averages, and Talk To's per Rep divides. Gap/hour cells stay raw
    minutes for the caller."""
    def _int0(v) -> int:
        v = str(v).strip()
        return int(v) if v.isdigit() else 0

    def _avg_time(pos: int) -> str:
        mins = [m for m in (_knock_time_key(str(r[pos])) for r in sub)
                if m < 24 * 60]
        if not mins:
            return ""
        m = round(sum(mins) / len(mins))
        h, mm = divmod(m, 60)
        return f"{h % 12 or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"

    out_cols = list(out_cols or COMBINED_KNOCKS_HEADERS)
    tt_at = out_cols.index(COL_TOTAL_TALK_TO)
    tk_at = out_cols.index(COL_TOTAL_KNOCKS)
    totals: list[str] = []
    for ci, c in enumerate(out_cols):
        if c == COL_REP:
            totals.append(label)
        elif c in (COL_FIRST_KNOCK, COL_LAST_KNOCK):
            totals.append(_avg_time(ci))
        elif c == COL_HRS_KNOCKING:
            vals = [_int0(r[ci]) for r in sub if str(r[ci]).strip() != ""]
            totals.append(str(round(sum(vals) / len(vals))) if vals else "")
        elif c == COL_TALK_TO_PER_REP:
            # Per rep KNOCKING — the head count in COL_REPS_KNOCKING, same
            # denominator the DAILY KNOCKS SUMMARY board uses (Rafael
            # 2026-08-28). See _knockers.
            #
            # BLANK, not "0", when nobody cleared the bar: on a washed-out day
            # the office still has talk-to's, and printing 0.0 next to them
            # says the reps had none. Nothing to divide by is not a zero.
            talk = sum(_int0(r[tt_at]) for r in sub)
            n = len(_knockers(sub, out_cols))
            totals.append(f"{talk / n:.1f}" if n else "")
        elif c == COL_TALK_TO_PCT:
            # The office rate: talk-tos over knocks, both summed off the SAME
            # rows the counts above come from — never an average of the reps'
            # rates, which would weigh a 30-knock day like a 300-knock one.
            totals.append(_pct(sum(_int0(r[tt_at]) for r in sub),
                               sum(_int0(r[tk_at]) for r in sub)))
        elif c == COL_REPS_KNOCKING:
            totals.append(str(len(_knockers(sub, out_cols))))
        else:
            totals.append(str(sum(_int0(r[ci]) for r in sub)))
    return totals


def _knock_time_key(v: str) -> int:
    """'2:31 PM' -> minutes since midnight for sorting; blank/unparsable last.
    strptime %I (not %-I) so it runs on Windows too."""
    v = (v or "").strip()
    try:
        t = dt.datetime.strptime(v, "%I:%M %p")
        return t.hour * 60 + t.minute
    except ValueError:
        return 24 * 60 + 1


def render_telemapper_knocks(target: dt.date, *, rows: list[dict],
                             out_dir: Path = OUT_DIR_DEFAULT,
                             title_suffix: str = "",
                             end: "dt.date | None" = None,
                             date_text: str = "") -> Path:
    """The gaps-only (NDS/wireless) office's stand-in for the Total Knocks
    board: the ownerville Time Tracker table itself, amber theme (it fills the
    Total Knocks slot in the thread). A wireless office has no Disposition
    page, so there are no knock COUNTS anywhere — what TeleMapper records for
    them is knock activity: first/last knock, breaks, gaps, sales time, sales
    (Raf's reference screenshot, 2026-08-22). Rows sorted First Knock asc,
    matching the live page; Total Gaps shown as 'Xh Ym'."""
    recs = sorted(rows, key=lambda r: _knock_time_key(str(r.get(COL_FIRST_KNOCK, ""))))
    table = []
    for rec in recs:
        row = ["" if rec.get(c, "") is None else str(rec.get(c, ""))
               for c in TELEMAPPER_KNOCKS_COLUMNS]
        if any(c.strip() for c in row):
            table.append(row)
    if not table:
        raise RuntimeError("No Time Tracker rows to render.")
    # Blank the zero gap cells like the live page does, then 'Xh Ym' the rest.
    g_pos = TELEMAPPER_KNOCKS_COLUMNS.index(COL_GAPS)
    tg_pos = TELEMAPPER_KNOCKS_COLUMNS.index(COL_TOTAL_GAPS)
    for r in table:
        if r[g_pos].strip() == "0":
            r[g_pos] = ""
        r[tg_pos] = "" if r[tg_pos].strip() == "0" else _fmt_hm(r[tg_pos])
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    return _draw(list(TELEMAPPER_KNOCKS_COLUMNS), table,
                 f"TELEMAPPER KNOCKS — {_office}{_date_text(target, end, date_text)}",
                 THEME_AMBER,
                 out_dir / f"telemapper_knocks_{_file_span(target, end)}.png")


def render_energywell_total_knocks(target: dt.date, *, rows: list[dict],
                                   out_dir: Path = OUT_DIR_DEFAULT,
                                   title_suffix: str = "",
                                   end: "dt.date | None" = None,
                                   date_text: str = "",
                                   sort_by: str = "knocks",
                                   knocks_green_at: "int | None" = None) -> Path:
    """TOTAL KNOCKS for an Energy Wells office — the wireless board with
    Presentation, VL and a Total Talk to column."""
    return render_wireless_total_knocks(
        target, rows=rows, out_dir=out_dir, title_suffix=title_suffix,
        end=end, date_text=date_text, columns=ENERGYWELL_KNOCKS_COLUMNS,
        sort_by=sort_by, knocks_green_at=knocks_green_at)


def render_wireless_total_knocks(target: dt.date, *, rows: list[dict],
                                 out_dir: Path = OUT_DIR_DEFAULT,
                                 title_suffix: str = "",
                                 end: "dt.date | None" = None,
                                 date_text: str = "",
                                 columns: "list | None" = None,
                                 sort_by: str = "knocks",
                                 knocks_green_at: "int | None" = None) -> Path:
    """TOTAL KNOCKS for a WIRELESS (NDS) office — same amber board as the
    house one, but the wireless disposition column set (one Not Interested
    bucket, no Talk-To split, no Sale). Rows come from the wireless-shaped
    Disposition by Rep table (rashad_metrics.knocks_pull scrapes it when the
    house columns aren't there). Sorted First Knock asc like the house board."""
    cols = list(columns or WIRELESS_KNOCKS_COLUMNS)

    def _tk(r):
        v = str(r.get(COL_TOTAL_KNOCKS, "")).strip().replace(",", "")
        return int(v) if v.isdigit() else 0

    if sort_by == "knocks":
        recs = sorted(rows, key=lambda r: (-_tk(r),
                                           str(r.get(COL_REP, "")).lower()))
    else:
        recs = sorted(rows,
                      key=lambda r: _knock_time_key(str(r.get(COL_FIRST_KNOCK, ""))))
    table = []
    for rec in recs:
        row = ["" if rec.get(c, "") is None else str(rec.get(c, ""))
               for c in cols]
        if any(c.strip() for c in row):
            table.append(row)
    if not table:
        raise RuntimeError("No disposition rows to render.")
    _cells = {}
    if knocks_green_at and COL_TOTAL_KNOCKS in cols:
        _tki = cols.index(COL_TOTAL_KNOCKS)
        for _ri, _row in enumerate(table):
            _v = str(_row[_tki]).strip().replace(",", "")
            if _v.isdigit() and int(_v) >= knocks_green_at:
                _cells[(_ri, _tki)] = GREEN_HIT
    _office = f"{title_suffix.upper()} — " if title_suffix else ""
    return _draw(cols, table,
                 f"TOTAL KNOCKS — {_office}{_date_text(target, end, date_text)}",
                 THEME_AMBER,
                 out_dir / f"total_knocks_{_file_span(target, end)}.png",
                 cell_bgs=_cells or None)


# ---------------------------------------------------------------- shapes ---
# Ownerville hands back THREE row shapes and each gets a different board (Raf
# 2026-08-22, "telemapper knocks … should be on there for the NDS guys"). The
# test is which COLUMNS the scrape found, not which office asked — an office's
# campaign can change without anyone editing config.
SHAPE_ENERGYWELL = "energywell"  # RES-ENERGYWELL: wireless + Presentation + VL
SHAPE_HOUSE = "house"          # fiber: full disposition columns
SHAPE_WIRELESS = "wireless"    # NDS disposition shape: counts, no Talk-To split
SHAPE_GAPS_ONLY = "gaps_only"  # no disposition page at all: Time Tracker only


def knocks_shape(rows: "list[dict]") -> str:
    """Which of the three board shapes `rows` is.

    Reads the first record's KEYS — a gaps-only office has no Total Knocks key
    at all (not a blank value), because those rows come from the Time Tracker
    JSON rather than the Disposition table. Lived as two inline booleans in
    rashad_metrics.knocks_run until on-demand /knocks needed the same routing.
    """
    if not rows:
        raise ValueError("knocks_shape() needs at least one row")
    first = rows[0]
    if COL_TOTAL_KNOCKS not in first:
        return SHAPE_GAPS_ONLY
    # Energy Wells FIRST: it has no Talk-To split either, so the wireless test
    # below would claim it and its board would lose VL and Presentation.
    if COL_VL in first:
        return SHAPE_ENERGYWELL
    return SHAPE_WIRELESS if COL_TALK_TO_NI not in first else SHAPE_HOUSE


_SHAPE_COLUMNS = {
    SHAPE_ENERGYWELL: ENERGYWELL_KNOCKS_HEADERS,
    SHAPE_HOUSE: COMBINED_KNOCKS_HEADERS,
    SHAPE_WIRELESS: WIRELESS_KNOCKS_COLUMNS,
    SHAPE_GAPS_ONLY: TELEMAPPER_KNOCKS_COLUMNS,
}


def needs_time_gaps(shape: str) -> bool:
    """Does `shape`'s main board still need a separate Time Gaps image?

    Only when that board does NOT already show Gaps + Total Gaps. Asked of the
    column list rather than hardcoded per shape, so giving a board those
    columns is all it takes to retire its duplicate post.
    """
    cols = _SHAPE_COLUMNS.get(shape) or ()
    return not (COL_GAPS in cols and COL_TOTAL_GAPS in cols)


def render_knocks_boards(target: dt.date, *, rows: "list[dict]",
                         out_dir: Path = OUT_DIR_DEFAULT,
                         title_suffix: str = "",
                         end: "dt.date | None" = None,
                         date_text: str = "",
                         extra_totals=None,
                         rate_columns: bool = True,
                         knocks_green_at: "int | None" = None,
                         sort_by: str = "knocks",
                         apps: "dict | None" = None
                         ) -> "tuple[list[Path], str]":
    """Every board this row shape deserves, in post order: ([paths], shape).

    Time Gaps rides along ONLY when the main board doesn't already carry Gaps
    + Total Gaps. That was Raf's rule for the fiber board (Loom 2026-08-22:
    the combined board absorbed the gap columns, so the separate Time Gaps
    post went away), and it is a property of the COLUMNS, not of the office —
    so it holds wherever it's true. The TeleMapper board carries both, so a
    gaps-only office gets ONE image too (Megan 2026-08-25: "his boards should
    be merged, that should have been universal"). The wireless disposition
    board genuinely lacks them, so that shape keeps its pair.

    `extra_totals` (a comparison office's TOTAL line) applies to the house
    board ONLY — the comparison office is fiber, so its totals have no column
    to sit under on an NDS board.

    `end` (optional): last day of a multi-day board. It only labels the title
    and filename — `rows` must already be folded by total_knocks.aggregate —
    and it reaches BOTH boards of an NDS pair, so a gaps-only office's Time
    Gaps image carries the same span as the one above it.
    """
    shape = knocks_shape(rows)
    if shape == SHAPE_GAPS_ONLY:
        first = render_telemapper_knocks(target, rows=rows, out_dir=out_dir,
                                         title_suffix=title_suffix, end=end,
                                         date_text=date_text)
    elif shape == SHAPE_ENERGYWELL:
        # THE SAME BOARD RAF GETS, on the Energy Wells column set: totals row,
        # Reps Knocking, Talk To %, Talk To's per Rep, Avg Hrs Knocking, the
        # rate columns, the 140 green, the knocks ranking and a comparison
        # office's line. It started on the flat wireless renderer and was
        # missing all of it (Megan 2026-08-30: "it seems it's missing like the
        # averages and Chan's comparison"). Going through one renderer means a
        # column Raf asks for next lands on both offices at once.
        return ([render_total_knocks(
            target, rows=rows, out_dir=out_dir, rate_columns=rate_columns,
            knocks_green_at=knocks_green_at, sort_by=sort_by,
            title_suffix=title_suffix, end=end, date_text=date_text,
            extra_totals=extra_totals,
            base_cols=ENERGYWELL_KNOCKS_COLUMNS,
            out_cols=ENERGYWELL_KNOCKS_HEADERS)], shape)
    elif shape == SHAPE_WIRELESS:
        first = render_wireless_total_knocks(target, rows=rows,
                                             out_dir=out_dir,
                                             title_suffix=title_suffix,
                                             end=end, date_text=date_text)
    else:
        return ([render_total_knocks(target, rows=rows, out_dir=out_dir,
                                     rate_columns=rate_columns,
                                     knocks_green_at=knocks_green_at,
                                     sort_by=sort_by, apps=apps,
                                     title_suffix=title_suffix, end=end,
                                     date_text=date_text,
                                     extra_totals=extra_totals)], shape)
    if not needs_time_gaps(shape):
        return ([first], shape)
    gaps = render_time_gaps(target, rows=rows, out_dir=out_dir,
                            title_suffix=title_suffix, end=end,
                            date_text=date_text)
    return ([first, gaps], shape)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (title)")
    ap.add_argument("--test-tab", action="store_true",
                    help="read the '… - TEST' sandbox tab instead of prod")
    args = ap.parse_args()
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else dt.date.today() - dt.timedelta(days=1))
    tab = TAB_TEST if args.test_tab else TAB_PROD
    p1 = render_total_knocks(target, tab=tab)
    p2 = render_time_gaps(target, tab=tab)
    print(f"[total_knocks.render] wrote {p1}")
    print(f"[total_knocks.render] wrote {p2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
