"""Credico's weekly Verizon bulletin -> page images, ready for Slack. PREVIEW ONLY.

    python -m automations.verizon_office.bulletin              # newest bulletin -> output/
    python -m automations.verizon_office.bulletin --pdf FILE   # a local copy

Nico asked for "the bulletin ... to send to the Slack" (Loom 2026-11-05). In
his Credico Outlook it is "Verizon Fios - Weekly Bulletin" (Mondays, PDF); no
Wireless-only bulletin was found 11/6. It is the SAME bulletin for every
Verizon office, so one read serves all of them -- it reaches the Hub inbox
through any office's redirect rule (workflows/verizon-icd-onboarding.md).

Nothing posts from here: Megan 2026-11-06, "we can't take anything live until
we're ready to get nico on ECO". When it goes live it posts the parent title
+ page images in the thread (Raf's clean-parent rule).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
SENDER = "vzreports@credicousa.com"
# THE VERIZON ONE, by subject: a bare "Weekly Bulletin" also matches the
# Frontier Events bulletin (another office, via Carlos's Gmail) -- the first
# preview grabbed exactly that (2026-11-06).
SUBJECT = "Verizon Fios - Weekly Bulletin"
GLOBS = ["*Weekly Bulletin*.pdf"]


def fetch(since_days: int = 10) -> Optional[Path]:
    from automations.shared import email_ingest
    dest = Path(tempfile.gettempdir()) / "verizon_bulletin"
    found = email_ingest.fetch_by_globs(SENDER, GLOBS, dest, subject=SUBJECT,
                                        since_days=since_days, verbose=False)
    pdf = next(iter(found.values()), None)
    if pdf and "frontier" in pdf.name.lower():
        return None           # belt and braces: never the Frontier bulletin
    return pdf


def render(pdf: Path, out_dir: Path, *, dpi: int = 130) -> List[Path]:
    """Every page -> PNG. A blank page is skipped, never posted."""
    import fitz
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    doc = fitz.open(str(pdf))
    try:
        for i, page in enumerate(doc, 1):
            if not page.get_text("text").strip() and not page.get_images():
                continue
            p = out_dir / f"bulletin_p{i}.png"
            page.get_pixmap(dpi=dpi).save(str(p))
            paths.append(p)
    finally:
        doc.close()
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path)
    a = ap.parse_args(argv)
    pdf = a.pdf or fetch()
    if not pdf:
        print("✗ no Weekly Bulletin in the Hub inbox in the last 10 days "
              "(it arrives Mondays through an office's Credico redirect rule)")
        return 1
    out = ROOT / "output" / "verizon_bulletin" / dt.date.today().isoformat()
    pages = render(pdf, out)
    if not pages:
        print("✗ %s has no readable pages — not posting a blank bulletin" % pdf.name)
        return 1
    print("✓ %s → %d page image(s) in %s (preview — nothing posted)" % (pdf.name, len(pages), out))
    print("  would post: \":newspaper: *Verizon Weekly Bulletin* · %s\" + %d image(s) in the thread"
          % (dt.date.today().strftime("%-m/%-d") if sys.platform != "win32" else dt.date.today().strftime("%#m/%#d"),
             len(pages)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
