"""Turn a day's captured boards into the ONE email an email-only office gets.

The runner points a metrics run at a capture directory (METRICS_EMAIL_DIR); every
board the office would have posted to Slack lands there instead
(shared.metrics_email_capture). This reads that directory and mails it.

WHAT THE OWNER SEES. One message, subject "Daily Metrics — <office> — <date>",
the same boards in the same order the thread would have had, each under its own
caption. The thread's header checklist becomes the intro list, so a board that
did not render is visible as owed instead of quietly absent — the thread showed
that by having a header line with no reply under it, and a mail has to say it out
loud [[feedback_fill_but_flag]].

    python -m automations.office_metrics.email_digest --office joseph --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

from automations.shared import metrics_email_capture as _mec
from automations.shared import report_email as _mail

REPO_ROOT = Path(__file__).resolve().parents[2]


def capture_dir(office_key: str, day: "dt.date | None" = None) -> Path:
    """Where a run's boards are captured. Per office AND per day, so a re-run
    later the same day adds to the day it belongs to and yesterday's images are
    never picked up by today's mail."""
    day = day or dt.date.today()
    return (REPO_ROOT / "output" / "office_metrics" / "email"
            / office_key / day.isoformat())


def _intro_html(header_text: str, sections: list) -> str:
    """The thread header, as the mail's intro.

    The header's first line is the dated title (already the subject) so it is
    dropped; what is worth carrying is the CHECKLIST — it is the day's promise of
    which boards are coming."""
    lines = [l.strip() for l in (sections or []) if l.strip()]
    if not lines and header_text:
        lines = [l.strip() for l in header_text.splitlines()[1:] if l.strip()]
    if not lines:
        return ""
    # Slack shortcodes (":door:") mean nothing in an inbox — strip them rather
    # than mail ":negative_squared_cross_mark: Disconnected Orders".
    items = "".join(f"<li>{re.sub(r':[a-z0-9_+-]+:', '', l).strip()}</li>"
                    for l in lines)
    return ('<div style="padding:0 0 8px">Today\'s boards:</div>'
            f'<ul style="margin:0 0 16px 18px;padding:0">{items}</ul>')


def _png_width(path: Path) -> int:
    """The image's pixel width, or 0 when it can't be read — 0 makes the whole
    set fall back to equal widths, which is right: a half-scaled email mis-sizes
    exactly one board, which is worse than an unscaled one."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return int(im.width)
    except Exception:                                # noqa: BLE001
        return 0


def blocks_from(d: Path) -> tuple:
    """((label, image path or None) per board in post order, [files to attach]).

    A text-only reply carries its text as the label with no image, so 'nothing
    new today' still reads as a section that ran. A board captured as kind
    "file" — the Order Log's .xlsx — becomes an ATTACHMENT plus a line saying so:
    a spreadsheet is a board the owner opens, not one he looks at.
    """
    out, files = [], []
    for r in _mec.board_rows(d):
        kind = r.get("kind")
        # Classified on the READ side as well as the write side, on the file's
        # own suffix. A capture directory written before this distinction
        # existed calls the Order Log's .xlsx an "image", and that directory is
        # exactly what a recovery re-send has to work from — re-deriving it here
        # means today's boards can go out without re-running Tableau, instead of
        # the spreadsheet being reported as a board that never arrived.
        if kind == "image" and not _mec.is_drawable(r.get("file", "")):
            kind = "file"
        if kind == "file":
            f = d / r["file"]
            label = r.get("label") or f.name
            if f.exists():
                files.append((label, f))
                out.append((label, None, 0, "attached"))
            else:
                out.append((label, None, 0, "missing"))
        elif kind == "image":
            f = d / r["file"]
            # The board's own pixel width is its scale reference. These PNGs are
            # rendered at their natural size (unlike the sheet boards, which all
            # arrive from a fit-to-WIDTH export), so a narrow board painted at
            # 100% would show its text at nearly twice the size of a wide one
            # sitting right under it. Passing the real width makes one board
            # pixel the same size in every image [[project_board-emails-image-legibility]].
            out.append((r.get("label") or "Board", f, _png_width(f), ""))
        elif kind == "text":
            # A board that posted a one-liner instead of an image ("no new orders
            # today"). It RAN — so it is a note, not a hole.
            out.append((r.get("text") or "(no detail)", None, 0, "note"))
        elif kind == "missing":
            out.append((r.get("label") or "Board", None, 0, "missing"))
    return out, files


def send_for_office(o, *, day: "dt.date | None" = None, dry_run: bool = False,
                    to=None, logfn=print) -> dict:
    """Mail `o`'s captured boards. `o` is an office_metrics.offices.Office."""
    day = day or dt.date.today()
    d = capture_dir(o.key, day)
    recipients = list(to or getattr(o, "email_to", ()) or ())
    if not recipients:
        return {"ok": False, "skipped": True,
                "reason": f"{o.key} has no email_to — nothing to send"}
    if not (d / _mec.MANIFEST).exists():
        # No capture at all means no metric ever reached its post step. That is a
        # failed run, not an empty day, and an email saying "here are today's
        # boards" with none in it is worse than none at all
        # [[feedback_never_post_blank]].
        return {"ok": False, "skipped": True, "capture_dir": str(d),
                "reason": "no boards were captured — nothing ran, or the run "
                          "never reached its post step"}
    hdr = _mec.header_row(d)
    blocks, files = blocks_from(d)
    # An attached spreadsheet is a board that arrived, so it counts here: a day
    # whose only output is the Order Log is a thin day, not a blank one.
    if not any(b[1] for b in blocks) and not files:
        return {"ok": False, "skipped": True, "capture_dir": str(d),
                "reason": f"{len(blocks)} section(s) captured but no board "
                          "image among them — not mailing a blank day"}
    # RENDERED IS NOT THE SAME AS HAS CONTENT. The guard above only ever caught
    # a day with no images at all; on 2026-09-14 Joseph's boards all rendered
    # and every one of them was empty ("no reps with data this period", "No
    # data available"), so a mail headed "here are today's boards" went to a
    # client's owner showing nothing. Megan: "this is all empty and looks
    # horrible." An office whose every board is empty has a SOURCE problem, and
    # mailing the evidence to the customer is not how they should find out
    # [[feedback_never_post_blank]].
    n_img = sum(1 for r in _mec.board_rows(d) if r.get("kind") == "image")
    n_empty = sum(1 for r in _mec.board_rows(d)
                  if r.get("kind") == "image" and r.get("empty"))
    if n_img and n_empty == n_img:
        return {"ok": False, "skipped": True, "capture_dir": str(d),
                "empty_boards": n_empty,
                "reason": f"all {n_empty} board(s) rendered EMPTY — this "
                          "office's sources have no rows today, so there is "
                          "nothing to send. Fix the source, then re-send with "
                          f"--office {o.key} --live --resend-email"}
    res = _mail.send_boards(
        # Built from the parts, not '%B %-d' — the no-pad flag is glibc-only and
        # every report here has to run on Windows too
        # [[feedback_cross_platform_reports]].
        subject=f"Daily Metrics — {o.label} — "
                f"{day.strftime('%B')} {day.day}, {day.year}",
        to=recipients,
        title=f"DAILY METRICS — {(o.business_name or o.label).upper()}",
        blocks=blocks,
        intro_html=_intro_html(hdr.get("text", ""), hdr.get("sections") or []),
        files=files,
        dry_run=dry_run, preview_dir=d, logfn=logfn)
    res["capture_dir"] = str(d)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--office", required=True)
    ap.add_argument("--date", default="", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--to", default="", help="override recipients (comma-separated)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)

    from automations.office_metrics.offices import OFFICES
    o = OFFICES.get(args.office)
    if o is None:
        print(f"unknown office '{args.office}'. known: {', '.join(sorted(OFFICES))}")
        return 2
    day = dt.date.fromisoformat(args.date) if args.date else None
    res = send_for_office(
        o, day=day, dry_run=not args.live,
        to=[a for a in args.to.split(",") if a.strip()] or None)
    if res.get("skipped"):
        print(f"[email_digest] SKIPPED — {res.get('reason')}")
        return 1
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
