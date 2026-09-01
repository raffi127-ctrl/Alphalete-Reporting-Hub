"""Yesterday's Daily Knocks boards as PDFs, attached to the Captainship Report.

Rafael's ask (via Eve, 2026-09-01), on top of the weekly attachment that has
ridden along since 2026-08-27 (see weekly_pdf):

  * the WEEKLY board comes OUT of the email body and stays only as its
    attachment (config.ATTACHMENT_ONLY_KINDS does that half),
  * the DAILY boards get an attachment of the whole captainship — the same
    pages the body's Daily Knocks section shows,
  * and one attachment PER OWNER, so a captain can forward an office its own
    board without cropping a screenshot.

Rafael's report is the worked example he gave: 1 weekly PDF + 1 combined daily
PDF + 13 per-owner daily PDFs = 15 attachments.

WHAT IT DOES NOT DO: pull anything, or re-render anything. It prints the PNGs
the morning's capture already wrote — the very images the body embeds — so the
attachment can never disagree with the section above it, and costs no
ownerville session. An owner whose board failed has no page: they are already
named in the body's pending note, and a blank page in a PDF says less than
their absence from a list of attachments does.

WHY THE FILES ARE KEPT UNDER output/. config.RENDER_DIR is the OS temp dir
("swept by the OS, never by us"). The daily PDF is built and mailed the same
morning, so a sweep is not the hazard it is for the weekly one — but a rebuild
hours later (a gate refresh, a resend) must produce the SAME attachment, and
that is cheaper to guarantee from a file than from a temp dir that may have
been swept in between.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import List, Optional, Tuple

from automations.captainship_drafts.pdf_pages import compose

PDF_DIR = Path(__file__).resolve().parents[2] / "output" / "daily_dispositions"

# How many days of printed PDFs to keep. These are rebuildable from the day's
# PNGs and only matter for the day they are mailed; two weeks is enough to
# re-send a report someone missed without the folder growing without end.
KEEP_DAYS = 14

# The label knock_dispo_images gives the board it inserts at the top of the
# daily list ("Daily Summary — Aug 31", sometimes with an INCOMPLETE suffix).
# It is the captainship's own board, not an owner's, so it belongs in the
# combined PDF and gets no per-owner file of its own.
SUMMARY_PREFIX = "Daily Summary"


def _slug(name: str) -> str:
    """Filesystem-safe piece of a file name — same shape as the render dirs."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "x"


def _clean_label(label: str) -> str:
    """The owner name without the run-time suffixes the section adds.

    A board title can carry ' — ⚠ INCOMPLETE: …' or an apps note; none of that
    belongs in a file name a captain forwards to that office."""
    return re.sub(r"\s+[—-]\s+.*$", "", (label or "").strip()) or "Board"


def _pretty_day(day: dt.date) -> str:
    """'Aug 31, 2026' — ASCII only; this goes in a name a mail client shows."""
    return f"{day.strftime('%b')} {day.day}, {day.year}"


def attachment_name(who: str, day: dt.date) -> str:
    who = re.sub(r"[^A-Za-z0-9' ]+", "", who).strip()
    return f"Daily Knock Dispositions - {who} - {_pretty_day(day)}.pdf"


def pdf_path(captain_key: str, day: dt.date, slug: Optional[str] = None
             ) -> Path:
    """One file per captain per day (plus per owner). A rebuild overwrites in
    place, so the folder never grows a copy per run."""
    tail = f"_{slug}" if slug else ""
    return PDF_DIR / f"daily_knocks_{captain_key}_{day.isoformat()}{tail}.pdf"


def _prune(today: dt.date) -> None:
    """Drop printed PDFs older than KEEP_DAYS. Best-effort: a folder we cannot
    tidy is never a reason to hold a report."""
    cutoff = today - dt.timedelta(days=KEEP_DAYS)
    try:
        for old in PDF_DIR.glob("daily_knocks_*.pdf"):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", old.name)
            if m and dt.date.fromisoformat(m.group(1)) < cutoff:
                old.unlink()
    except Exception:      # noqa: BLE001 — housekeeping, never fatal
        pass


def split_pages(pairs) -> Tuple[List[Tuple[str, Path]], List[Tuple[str, Path]]]:
    """(all printable pages, the owner-only ones) out of a daily_knocks bundle.

    `pairs` is the [(title, png|None)] list the body renders: the captainship
    summary first, then one entry per owner. Entries without an image are
    dropped — a failed pull is reported in the body, not as a blank page."""
    pages = [(lab, Path(p)) for lab, p in (pairs or [])
             if p and Path(p).exists() and Path(p).stat().st_size]
    owners = [(lab, p) for lab, p in pages
              if not _clean_label(lab).startswith(SUMMARY_PREFIX)]
    return pages, owners


def build(captain, today: dt.date, pairs, day: Optional[dt.date] = None,
          out_dir=None, logfn=print) -> List[Tuple[Path, str]]:
    """[(pdf path, attachment file name)] for one captain — the combined
    captainship PDF first, then one per owner, in the body's order.

    An empty list is a normal outcome, not a failure: a captainship with no
    daily boards on disk mails without them. Every exception is swallowed for
    the same reason — an attachment must never be the thing that stops a
    report going out."""
    try:
        day = day or (today - dt.timedelta(days=1))
        pages, owners = split_pages(pairs)
        if not pages:
            logfn(f"  · no daily knock boards for {captain.key} — mailing "
                  "without the daily PDFs")
            return []
        base = Path(out_dir) if out_dir else PDF_DIR
        out: List[Tuple[Path, str]] = []

        combined = base / pdf_path(captain.key, day).name
        compose(pages, combined)
        out.append((combined, attachment_name(
            f"{captain.display_name}'s Captainship", day)))

        seen = set()
        for label, png in owners:
            who = _clean_label(label)
            slug = _slug(who)
            while slug in seen:            # two owners with one name: keep both
                slug += "_2"
            seen.add(slug)
            path = base / pdf_path(captain.key, day, slug).name
            compose([(who, png)], path)
            out.append((path, attachment_name(who, day)))

        kb = sum(p.stat().st_size for p, _n in out) // 1024
        logfn(f"  ✓ daily PDFs: 1 captainship ({len(pages)} page(s)) + "
              f"{len(owners)} owner file(s) for {day.isoformat()} ({kb} KB)")
        _prune(today)
        return out
    except Exception as e:   # noqa: BLE001 — never block a send
        logfn(f"  ⚠ daily PDFs skipped for {captain.key}: "
              f"{type(e).__name__}: {str(e)[:200]}")
        return []
