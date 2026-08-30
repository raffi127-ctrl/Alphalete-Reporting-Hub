"""Last week's Knock Dispositions boards as ONE PDF, attached to every daily
Captainship Report.

Rafael's ask (Slack, 2026-08-27): *"The weekly disposition report that comes out
on Sunday. Can we turn that into a PDF and attach it to all the Captainship
emails that get sent out every day? Reason being is I find myself comparing last
week's disposition to the dispositions from the day prior."*

So the WEEKLY section — which only renders inside the email on Sun/Mon
(config.SECTION_DAYS) — rides along as an attachment the other five days too,
and a captain reading Wednesday's daily boards has last week's numbers in the
same message instead of scrolling back to Sunday's email.

WHAT IT DOES NOT DO: pull anything. The boards it prints are the PNGs Sunday's
run already wrote under `<render_dir>/knock_dispo_<captain>/…`, so the
attachment costs no ownerville session — which matters more here than anywhere
else in this package: the weekly capture impersonates every ICD in single file
and takes ~2 hours (see knock_dispo_images' module docstring). Re-pulling it
daily is exactly the job the 2026-08-24 split existed to remove. If neither the
PNGs nor an already-printed PDF are on disk, the email goes out WITHOUT the
attachment — never late, never blocked.

WHICH WEEK. Not `knock_dispo_images.week_window`: that answers "the week this
morning's run reports on", which from Tuesday to Saturday is the week now IN
PROGRESS (report_week's rule — a daily report shows the week holding the last
completed sales day). The attachment needs the week the last SUNDAY REPORT
covered, which is the Mon–Sat ending the day before the most recent Sunday, on
every weekday alike:

    Sun 8/30 → Sat 8/29   (the boards built this morning)
    Thu 8/27 → Sat 8/22   (the boards 8/23's report went out with)

A missed Sunday would leave nothing at that week, so the search walks back up to
`MAX_WEEKS_BACK` weeks and attaches the newest set that IS on disk. The board
images carry their own week span in the title, and the file name repeats it, so
an older set can never be mistaken for last week's.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import List, Optional, Tuple


# How far back to look for a week that actually rendered. 3 = the last three
# Sundays; past that, an attachment is stale enough that its absence is the
# more honest signal (and the daily boards in the body are unaffected).
MAX_WEEKS_BACK = 3

# WHERE THE PDF LIVES, and why it is not next to the PNGs it is printed from.
# config.RENDER_DIR is the OS temp dir ("swept by the OS, never by us" — its own
# comment). That is fine for an image a run rebuilds every morning, and WRONG
# for this: Sunday's boards have to still be attachable on Friday, and a sweep
# on Wednesday would make the attachment vanish mid-week with nothing in any
# log to explain it. So the printed PDF is kept under output/, and a week whose
# PNGs are gone is still mailable from the PDF already made for it.
PDF_DIR = Path(__file__).resolve().parents[2] / "output" / "weekly_dispositions"

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


def last_report_saturday(today: dt.date) -> dt.date:
    """The Saturday of the week the most recent Sunday report covered.

    weekday(): Mon=0 … Sun=6, so `(weekday + 1) % 7` is days since the last
    Sunday (0 when today IS Sunday — that morning's run has already written
    the new week's boards by the time the drafts build at 06:15)."""
    sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return sunday - dt.timedelta(days=1)


def _weekly_root(render_dir, captain_key: str) -> Path:
    """The dir knock_dispo_images.capture_sections writes weekly boards into."""
    return Path(render_dir) / f"knock_dispo_{captain_key}"


def _from_manifest(render_dir, captain_key: str, saturday: dt.date
                   ) -> List[Tuple[str, Path]]:
    """[(label, png)] for `saturday` out of the capture manifests, in the order
    the email showed them — Captainship Summary first, then the owners in
    roster order.

    The manifest is per captain per DAY, and its name carries the week's
    Saturday, so one week has one or two (Sunday's build and Monday's re-show).
    The NEWEST is the one to trust: a Monday rebuild is the later word on the
    same week. Labels come from it too, which is why this is preferred over
    globbing — a folder name is a slug, and 'Rafael Hidalgo' cannot be
    recovered from 'rafael_hidalgo' with any confidence."""
    out: List[Tuple[str, Path]] = []
    pat = f"knocks_manifest_{captain_key}_*_{saturday.isoformat()}.json"
    for man in sorted(Path(render_dir).glob(pat), reverse=True):
        try:
            data = json.loads(man.read_text(encoding="utf-8"))
        except Exception:       # noqa: BLE001 — an unreadable one is not fatal
            continue
        pairs = (data.get("items") or {}).get("knock_dispo") or []
        got = [(lab, Path(p)) for lab, p in pairs
               if p and Path(p).exists() and Path(p).stat().st_size]
        if got:
            return got
    return out


def _from_disk(render_dir, captain_key: str, saturday: dt.date
               ) -> List[Tuple[str, Path]]:
    """Fallback for a week whose manifest is gone but whose PNGs are not: every
    board named for that Saturday, summary first, then the rest alphabetically.

    Labels are rebuilt from the folder slug (a `_` became any non-alphanumeric,
    so this is a readable approximation, not the owner's exact display name) —
    good enough for a page order, and the board's own title carries the office
    name anyway."""
    root = _weekly_root(render_dir, captain_key)
    stem = f"weekly_knock_dispositions_{saturday.isoformat()}.png"
    summary = root / "summary" / f"knock_dispo_summary_{saturday.isoformat()}.png"
    out: List[Tuple[str, Path]] = []
    if summary.exists() and summary.stat().st_size:
        out.append(("Captainship Summary", summary))
    for png in sorted(root.glob(f"*/{stem}")):
        if png.stat().st_size:
            out.append((re.sub(r"_+", " ", png.parent.name).title(), png))
    return out


def pages_for(render_dir, captain_key: str, saturday: dt.date
              ) -> List[Tuple[str, Path]]:
    """The boards to print for one captain's week, in email order."""
    return (_from_manifest(render_dir, captain_key, saturday)
            or _from_disk(render_dir, captain_key, saturday))


def find_week(render_dir, captain_key: str, today: dt.date,
              max_weeks_back: int = MAX_WEEKS_BACK
              ) -> Tuple[Optional[dt.date], List[Tuple[str, Path]]]:
    """(saturday, pages) — the newest week with boards on disk, walking back
    from the last reported one. (None, []) when there are none."""
    sat = last_report_saturday(today)
    for _ in range(max_weeks_back):
        pages = pages_for(render_dir, captain_key, sat)
        if pages:
            return sat, pages
        sat -= dt.timedelta(days=7)
    return None, []


def _span(saturday: dt.date) -> str:
    """'Aug 17-22, 2026' — the same Mon–Sat span the boards title themselves
    with, ASCII-only because this goes in a file name a mail client shows."""
    monday = saturday - dt.timedelta(days=5)
    if monday.month == saturday.month:
        return (f"{monday.strftime('%b')} {monday.day}-{saturday.day}, "
                f"{saturday.year}")
    return (f"{monday.strftime('%b')} {monday.day} - "
            f"{saturday.strftime('%b')} {saturday.day}, {saturday.year}")


def attachment_name(captain_display: str, saturday: dt.date) -> str:
    """What the captain sees in their mail client. The WEEK is in the name on
    purpose: this file lands in the same inbox seven days running, and a name
    that didn't change would make each day's copy look like the previous
    one — the point is comparing against a specific week."""
    who = re.sub(r"[^A-Za-z0-9 ]+", "", captain_display).strip()
    return f"Weekly Knock Dispositions - {who} - {_span(saturday)}.pdf"


def pdf_path(captain_key: str, saturday: dt.date) -> Path:
    """The kept PDF for one captain's week. One file per captain per week, so
    a rebuild overwrites in place and the folder never grows a copy per day."""
    return PDF_DIR / (f"weekly_knock_dispositions_{captain_key}_"
                      f"{saturday.isoformat()}.pdf")


def _compose(pages: List[Tuple[str, Path]], out: Path) -> Path:
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


def build(captain, today: dt.date, render_dir, out_dir=None,
          logfn=print) -> Optional[Tuple[Path, str]]:
    """(pdf path, attachment file name) for `captain`, or None when there is
    nothing on disk to print.

    None is a normal outcome, not a failure: a captainship whose weekly section
    never ran (or a flavor that doesn't carry one) simply mails without the
    attachment. Every exception is swallowed for the same reason — an
    attachment must never be the thing that stops a report going out."""
    try:
        sat = last_report_saturday(today)
        for _ in range(MAX_WEEKS_BACK):
            out = (Path(out_dir) / pdf_path(captain.key, sat).name
                   if out_dir else pdf_path(captain.key, sat))
            pages = pages_for(render_dir, captain.key, sat)
            if pages:
                # PNGs still there: re-print, so a Monday re-pull of the same
                # week replaces Sunday's file instead of shipping behind it.
                _compose(pages, out)
                logfn(f"  ✓ weekly PDF: {len(pages)} page(s), week ending "
                      f"{sat.isoformat()} → {out.name} "
                      f"({out.stat().st_size // 1024} KB)")
                return out, attachment_name(captain.display_name, sat)
            if out.exists() and out.stat().st_size:
                # The temp dir was swept; the PDF printed earlier this week is
                # the same document, so the attachment survives the sweep.
                logfn(f"  ✓ weekly PDF (kept from an earlier run): {out.name}")
                return out, attachment_name(captain.display_name, sat)
            sat -= dt.timedelta(days=7)
        logfn(f"  · no weekly boards or PDF for {captain.key} in the last "
              f"{MAX_WEEKS_BACK} week(s) — mailing without the weekly PDF")
        return None
    except Exception as e:   # noqa: BLE001 — never block a send
        logfn(f"  ⚠ weekly PDF skipped for {captain.key}: "
              f"{type(e).__name__}: {str(e)[:200]}")
        return None
