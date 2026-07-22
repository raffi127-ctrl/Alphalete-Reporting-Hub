"""Create the Captainship Report Gmail drafts.

Runs AFTER the churn runs (captainship_churn + owners_metrics_churn) have
filled the sheets — this module only reads the filled tabs, renders the
churn images, assembles each draft, and creates it in Gmail.

  python -m automations.captainship_drafts.run --only wayne --dry-run
  python -m automations.captainship_drafts.run --dry-run     # all 12, no send
  python -m automations.captainship_drafts.run --only wayne  # live: create draft
  python -m ...run --only wayne --dry-run --skip-sheets      # churn-only preview

--dry-run writes each assembled email to output/ as a .eml you can open
in any mail client to preview (images embedded) — nothing touches Gmail.
--skip-sheets skips the Sales Board screenshots (no browser login / no sheet
row-group toggling) — those sections show a 'pending' note.

Sections wired: §1 Product Summary + Captainship Units (Sales Board shots),
churn (§3/§4), fiber Activations PNG. The Tableau §2 (Cancel Rates / Team
Stats Breakout) shows a per-section 'pending' note until the Tableau phase.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.captainship_drafts import (
    config, churn_images, email_build, fiber_png, preview,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _REPO_ROOT / "output"


def _sales_board_shots(captain, today, render_dir, *, logfn):
    """(product_summary, units) from the Sales Board — degrades to (None, [])
    if the screenshot browser isn't logged in / a capture fails, so the rest
    of the draft still builds (that section shows a 'pending' note)."""
    try:
        from automations.captainship_drafts import sheet_shot
        shots = sheet_shot.captain_shots(captain.key, captain.flavor,
                                         render_dir, today=today)
        return shots.get("product_summary"), shots.get("units") or []
    except Exception as e:
        logfn(f"  ⚠ Sales Board screenshots skipped for {captain.key}: {e}")
        return None, []


def _tableau_shots(captain, today, render_dir, *, logfn):
    """(cancel_tableau, teamstats_tableau) for one captain — only the one its
    flavor uses is populated; the other stays None. Degrades to None on any
    failure OR an unconfigured source, so that §2 section shows a 'pending' note
    and the rest of the draft still builds (a failed pull must never post a
    wrong-looking image)."""
    try:
        from automations.captainship_drafts import tableau_shot
        path = tableau_shot.captain_tableau_shot(
            captain.key, captain.flavor, render_dir, today=today, logfn=logfn)
    except Exception as e:
        logfn(f"  ⚠ Tableau §2 shot skipped for {captain.key}: {e}")
        path = None
    if captain.flavor in ("rafael", "fiber"):
        return path, None      # (cancel_tableau, teamstats_tableau)
    return None, path


def _build_one(captain: config.Captain, today: dt.date, render_dir: Path,
               *, skip_sheets: bool = False, skip_tableau: bool = False,
               logfn=print):
    logfn(f"\n--- {captain.key} ({captain.display_name}, {captain.flavor}) ---")
    churn = churn_images.render_captain(captain, today, render_dir, logfn=logfn)
    churn_wireless = [c for c in churn if c[0].lower().startswith("wireless")]
    churn_ni = [c for c in churn if not c[0].lower().startswith("wireless")]

    if skip_sheets:
        logfn("  (‑‑skip-sheets) Sales Board screenshots skipped")
        ps, units = None, []
    else:
        ps, units = _sales_board_shots(captain, today, render_dir, logfn=logfn)

    if skip_tableau:
        logfn("  (‑‑skip-tableau) Tableau §2 shot skipped")
        cancel_tableau, teamstats_tableau = None, None
    else:
        cancel_tableau, teamstats_tableau = _tableau_shots(
            captain, today, render_dir, logfn=logfn)

    bundle = {
        "product_summary": ps,
        "units": units,
        "churn_ni": churn_ni,
        "churn_wireless": churn_wireless,
        # §2 Tableau shots (cancel rates / team stats breakout), filtered to the
        # captain's team. None → email_build shows a per-section 'pending' note.
        "cancel_tableau": cancel_tableau,
        "teamstats_tableau": teamstats_tableau,
        "fiber_activation": (fiber_png.fiber_activation_png(
            captain.key, today, logfn=logfn)
            if captain.flavor == "fiber" else None),
    }
    n_imgs = sum([ps is not None, len(units), len(churn),
                  cancel_tableau is not None, teamstats_tableau is not None,
                  bundle["fiber_activation"] is not None])
    if not n_imgs:
        logfn(f"  ⚠ no images at all for {captain.key} — skipping")
        return None
    msg = email_build.build(captain, bundle, today)
    logfn(f"  built draft: subj={msg['Subject']!r}, {n_imgs} image(s)")
    return msg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_drafts")
    ap.add_argument("--date", default=None,
                    help="Override today's date (YYYY-MM-DD).")
    ap.add_argument("--only", default=None,
                    help="Comma-separated captain keys "
                         f"({', '.join(c.key for c in config.CAPTAINS)}). "
                         "Default: all 12.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Write each draft to output/*.eml for preview; "
                         "do NOT create the Gmail draft.")
    ap.add_argument("--skip-sheets", action="store_true",
                    help="Skip Sales Board screenshots (no browser/sheet "
                         "writes); those sections show a 'pending' note.")
    ap.add_argument("--skip-tableau", action="store_true",
                    help="Skip the §2 Tableau shots (no Tableau session); those "
                         "sections show a 'pending' note.")
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
            msg = _build_one(captain, today, render_dir,
                             skip_sheets=args.skip_sheets,
                             skip_tableau=args.skip_tableau)
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
