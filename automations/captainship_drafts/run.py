"""Create the Captainship Report Gmail drafts.

Runs AFTER the churn runs (captainship_churn + owners_metrics_churn) have
filled the sheets — this module only reads the filled tabs, renders the
churn images, assembles each draft, and creates it in Gmail.

  python -m automations.captainship_drafts.run --only wayne --dry-run
  python -m automations.captainship_drafts.run --dry-run     # all 10, no send
  python -m automations.captainship_drafts.run --only wayne  # live: create draft

--dry-run writes each assembled email to output/ as a .eml you can open
in any mail client to preview (images embedded) — nothing touches Gmail.

PHASE 1: churn section only. Sections 1-2 land in later phases.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.captainship_drafts import (
    config, churn_images, email_build, preview,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _REPO_ROOT / "output"


def _build_one(captain: config.Captain, today: dt.date, render_dir: Path,
               *, logfn=print):
    logfn(f"\n--- {captain.key} ({captain.display_name}, {captain.flavor}) ---")
    images = churn_images.render_captain(captain, today, render_dir, logfn=logfn)
    if not images:
        logfn(f"  ⚠ no churn images rendered for {captain.key} — skipping")
        return None
    msg = email_build.build(captain, images, today)
    logfn(f"  built draft: subj={msg['Subject']!r}, {len(images)} image(s)")
    return msg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_drafts")
    ap.add_argument("--date", default=None,
                    help="Override today's date (YYYY-MM-DD).")
    ap.add_argument("--only", default=None,
                    help="Comma-separated captain keys "
                         f"({', '.join(c.key for c in config.CAPTAINS)}). "
                         "Default: all 10.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Write each draft to output/*.eml for preview; "
                         "do NOT create the Gmail draft.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    keys = ({k.strip() for k in args.only.split(",")} if args.only
            else {c.key for c in config.CAPTAINS})
    selected = [c for c in config.CAPTAINS if c.key in keys]
    unknown = keys - {c.key for c in config.CAPTAINS}
    if unknown:
        print(f"Unknown captain key(s): {sorted(unknown)}. "
              f"Valid: {[c.key for c in config.CAPTAINS]}")
        return 1

    mode = "DRY-RUN (preview .eml)" if args.dry_run else "LIVE (create drafts)"
    print(f"=== Captainship Drafts — {today.isoformat()} ({mode}) ===")
    print(f"Captains: {[c.key for c in selected]}")

    render_dir = Path(tempfile.gettempdir()) / "captainship_drafts_render"
    failures = 0

    for captain in selected:
        try:
            msg = _build_one(captain, today, render_dir)
        except Exception as e:
            failures += 1
            print(f"  ✗ {captain.key}: build failed: {e}")
            continue
        if msg is None:
            failures += 1
            continue

        if args.dry_run:
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            eml = _OUTPUT_DIR / (
                f"captainship_draft_{captain.key}_{today:%Y%m%d}.eml")
            eml.write_bytes(bytes(msg))
            # Also emit a browser-previewable .html (cid images inlined as
            # data URIs) — an .eml shows blank when dragged into Gmail.
            html = preview.eml_to_html(eml)
            print(f"  ✓ preview written: {eml.name} + {html.name}")
        else:
            # LIVE. Idempotency (delete the day's prior draft for this
            # captain before creating) lands in the live phase — flagged
            # so we don't silently accumulate drafts on re-run.
            from automations.shared.gmail_draft import create_draft
            res = create_draft(msg)
            print(f"  ✓ draft created: {res}")

    if failures:
        print(f"\n✗ {failures} captain(s) failed.")
        return 1
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
