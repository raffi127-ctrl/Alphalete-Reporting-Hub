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

# Letter LANDSCAPE at 150 dpi. Landscape because these boards are wide — 17
# columns on the per-owner ones — and portrait would shrink them to the point
# where the numbers stop being readable on a phone, which is where a captain
# opens this.
DPI = 150
PAGE_W, PAGE_H = int(11 * DPI), int(8.5 * DPI)
MARGIN = int(0.35 * DPI)


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
    """One board per page, scaled to fit a Letter-landscape page and centred on
    white. Scaled DOWN only — a small board is left at its own size rather than
    blown up into a blurry one."""
    from PIL import Image
    canvases = []
    for _label, png in pages:
        img = Image.open(png).convert("RGB")
        room_w, room_h = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN
        scale = min(room_w / img.width, room_h / img.height, 1.0)
        if scale < 1.0:
            img = img.resize((max(1, int(img.width * scale)),
                              max(1, int(img.height * scale))),
                             Image.LANCZOS)
        page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
        page.paste(img, ((PAGE_W - img.width) // 2, (PAGE_H - img.height) // 2))
        canvases.append(page)
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
