"""Create the Captainship Report Gmail drafts.

Runs AFTER the churn runs (captainship_churn + owners_metrics_churn) have
filled the sheets — this module only reads the filled tabs, renders the
churn images, assembles each draft, and creates it in Gmail.

  python -m automations.captainship_drafts.run --only wayne --dry-run
  python -m automations.captainship_drafts.run --dry-run     # all 12, no send
  python -m automations.captainship_drafts.run --only wayne  # live: create draft
  python -m ...run --only wayne --send                       # live: SEND it
  python -m ...run --only wayne --dry-run --skip-sheets      # churn-only preview

!! DO NOT OPEN THESE DRAFTS IN GMAIL TO SEND THEM. !!
Proven 2026-07-27, after Eve got a whole batch of mangled reports: opening an
API-created draft in the Gmail compose window makes Gmail pull the inline
images out of the message into its own attachment store. What then goes out
has NO image parts at all — the recipient gets the body text, broken icons and
nothing attached. Gmail also reorders the parts on the way, which is what made
the first batch look "shuffled and mixed up". The same message sent through the
API arrives perfect, so `--send` is the supported way to deliver these:
review the .html preview in output/, then send with --send. Recipients live in
config.py (Captain.to), NOT in Gmail's To box.

--dry-run writes each assembled email to output/ as a .eml you can open
in any mail client to preview (images embedded) — nothing touches Gmail.
A LIVE run is idempotent: it deletes this captain's existing draft for the
same date before creating the new one, so re-running replaces rather than
piles up 12 more drafts. --no-replace opts out.
--skip-sheets skips the Sales Board screenshots (no browser login / no sheet
row-group toggling) — those sections show a 'pending' note.

Sections wired: Product Summary + Captainship Units (Sales Board shots), the
churn blocks, the fiber Activations PNG, and — since 2026-07-29 — the six
one-column-per-day metric boxes on the fiber drafts (cancel rate 0-30 / 30-60,
ABP %, activation 0-30 / 30-60, 6+ days out). Those read the tabs the daily
cancel-rate / activation-rate / ABP runs fill, so this must run AFTER them;
a box with no data for today shows a per-section 'pending' note.

Rafael / B2B / NDS still take their §2 from Tableau (Cancel Rates / Team Stats
Breakout). Fiber no longer does, so a fiber-only run needs no Tableau session
at all.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.captainship_drafts import (
    config, churn_images, box_images, distro, email_build, fiber_png, preview,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _REPO_ROOT / "output"


def _sales_board_shots(captain, today, render_dir, *, logfn, errors=None):
    """(product_summary, units) from the Sales Board — degrades to (None, [])
    if every path fails, so the rest of the draft still builds (that section
    shows a 'pending' note carrying the LAST path's reason, recorded into
    `errors`).

    LOGIN-FREE FIRST (Eve, 2026-07-30). sheet_render reads the same cells and
    their formatting through the API token and screenshots a local HTML copy, so
    nothing here needs a Chrome profile signed into Google. That profile is the
    reason this report lived on Eve's laptop: the session expires every few weeks
    and the re-login needs 2FA physically at the machine that runs the report,
    and nobody sits at the mini. Replaying an exported session there was tried
    and is a dead end — it cost the source machine its session too (see
    sheet_shot.seed_cookies).

    The old screenshot path stays as the fallback, not out of nostalgia: on a
    machine that IS signed in it is the ground truth this render was verified
    against, so a break in the renderer degrades to the real screenshot instead
    of to a 'pending' note."""
    from automations.captainship_drafts import sheet_render
    _render_err = ""
    try:
        shots = sheet_render.captain_shots(captain.key, captain.flavor,
                                          render_dir, today=today)
        return shots.get("product_summary"), shots.get("units") or []
    except Exception as e:
        _render_err = f"{type(e).__name__}: {e}"
        logfn(f"  ⚠ login-free Sales Board render failed for {captain.key} "
              f"({_render_err}) — trying the screenshot path")
    try:
        from automations.captainship_drafts import sheet_shot
        shots = sheet_shot.captain_shots(captain.key, captain.flavor,
                                         render_dir, today=today)
        return shots.get("product_summary"), shots.get("units") or []
    except Exception as e:
        logfn(f"  ⚠ Sales Board screenshots skipped for {captain.key}: {e}")
        # Both paths are down: name the render's reason in the email itself.
        # The screenshot fallback's own error is the less useful of the two —
        # on an unattended machine it is always "not signed into Google", which
        # is expected there and tells nobody anything.
        if errors is not None:
            errors["product_summary"] = f"{_render_err or e}"
        return None, []


def _tableau_shots(captain, today, render_dir, *, logfn, errors=None):
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
        if errors is not None:
            key = ("cancel_tableau" if captain.flavor in ("rafael", "fiber")
                   else "teamstats_tableau")
            errors[key] = f"{type(e).__name__}: {e}"
        path = None
    if captain.flavor in ("rafael", "fiber"):
        return path, None      # (cancel_tableau, teamstats_tableau)
    return None, path


def _norm_subject(s: str) -> str:
    """Normalize a subject for idempotency matching: drop parentheses and
    collapse whitespace. This is what lets the sweep still recognize drafts
    written under the OLD "(7/26)" subject format as the same day's draft —
    a format change must not orphan the drafts it was meant to replace."""
    return " ".join(s.replace("(", " ").replace(")", " ").split())


def _delete_prior_drafts(captain: config.Captain, today: dt.date,
                         *, logfn=print) -> int:
    """Delete this captain's already-existing draft(s) for `today` so a
    re-run REPLACES rather than accumulates. Matches on the normalized
    subject built by email_build.subject_for, so it can only ever hit this
    captain's draft for this date — never another captain's, never another
    day's, never a non-report mail (drafts only). Never fatal: a sweep that
    fails leaves a duplicate, which is far better than losing the run."""
    from automations.shared.gmail_draft import list_drafts, delete_draft
    want = _norm_subject(email_build.subject_for(captain, today))
    n = 0
    try:
        # Narrow the fetch to this report's drafts; the real check is `want`.
        for d in list_drafts(query='subject:"Captainship Report"'):
            if _norm_subject(d.get("subject") or "") != want:
                continue
            delete_draft(d["draft_id"], logfn=logfn)
            n += 1
    except Exception as e:
        logfn(f"  ⚠ prior-draft sweep failed for {captain.key} "
              f"({type(e).__name__}: {e}) — a duplicate may result")
    return n


def _preview_eml(captain: config.Captain, today: dt.date) -> Path:
    """Where --dry-run parks this captain's built email for review."""
    return _OUTPUT_DIR / f"captainship_draft_{captain.key}_{today:%Y%m%d}.eml"


def _send_reviewed(selected, today: dt.date, *, to_override=None,
                   logfn=print) -> int:
    """Send the .eml files --dry-run already wrote for `today`, untouched.

    This is the approval gate. It deliberately does NOT rebuild: re-reading the
    Sales Board could pick up a number that changed since Eve looked, and the
    whole point is that what lands in people's inboxes is byte-identical to
    what she approved. A captain with no preview on disk is skipped loudly
    rather than silently rebuilt."""
    from email import policy
    from email.parser import BytesParser
    from automations.captainship_drafts.mailer import Mailer

    failures = 0
    # One SMTP login for the whole set (see mailer.py for why SMTP and not the
    # Gmail API). Opened lazily, so a run where every preview is missing never
    # touches the network.
    with Mailer(logfn=logfn) as mailer:
        for captain in selected:
            eml = _preview_eml(captain, today)
            if not eml.exists():
                failures += 1
                logfn(f"  ✗ {captain.key}: no preview for {today} at {eml.name} "
                      f"— run with --dry-run first, then review it")
                continue
            recipient = to_override or captain.recipients(logfn=logfn)
            if not recipient.strip():
                failures += 1
                logfn(f"  ✗ {captain.key}: no recipient — the "
                      f"{distro.group_name(captain.key)!r} contact group is "
                      f"empty/missing AND RECIPIENTS[{captain.key!r}] is blank "
                      f"— skipped")
                continue
            msg = BytesParser(policy=policy.default).parsebytes(eml.read_bytes())
            if msg["To"] is None:
                msg["To"] = recipient
            else:
                msg.replace_header("To", recipient)
            n_to = len([a for a in recipient.split(",") if a.strip()])
            logfn(f"  sending {captain.key}: {msg['Subject']!r} -> {n_to} "
                  f"recipient(s)")
            try:
                mailer.send(msg)
                logfn(f"  ✓ {captain.key}: sent")
            except Exception as e:
                failures += 1
                logfn(f"  ✗ {captain.key}: send failed: {type(e).__name__}: {e}")
    return failures


def _capture_one(captain: config.Captain, today: dt.date, render_dir: Path,
                 *, skip_sheets: bool = False, skip_tableau: bool = False,
                 logfn=print):
    """Capture all of a captain's section images into a bundle, or None if the
    captain yielded no images. Email assembly happens later (in main), AFTER
    cross-captain size normalization, so same-flavor sections share one size."""
    logfn(f"\n--- {captain.key} ({captain.display_name}, {captain.flavor}) ---")
    # bundle key -> why that capture failed. email_build prints it under the
    # section's 'pending' note, so a blank section in a report Eve is reading
    # says what broke instead of sending her back to a log on another machine.
    errors: dict = {}
    churn = churn_images.render_captain(captain, today, render_dir, logfn=logfn)
    # The daily metric boxes (cancel / activation / ABP / 6-days). Never fatal:
    # a box that can't be read is left out of the bundle and its section says
    # so, rather than taking the whole draft down.
    try:
        boxes = box_images.render_captain(captain, today, render_dir, logfn=logfn)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ metric boxes skipped for {captain.key}: "
              f"{type(e).__name__}: {e}")
        errors["boxes"] = f"{type(e).__name__}: {e}"
        boxes = {}
    churn_wireless = [c for c in churn if c[0].lower().startswith("wireless")]
    churn_ni = [c for c in churn if not c[0].lower().startswith("wireless")]

    if skip_sheets:
        logfn("  (‑‑skip-sheets) Sales Board screenshots skipped")
        ps, units = None, []
        errors["product_summary"] = "skipped by --skip-sheets"
    else:
        ps, units = _sales_board_shots(captain, today, render_dir, logfn=logfn,
                                       errors=errors)

    # Only pull a Tableau shot if a section actually renders one. Since
    # 2026-07-29 the fiber drafts read their cancel rates off the sheet boxes
    # instead, so fiber no longer has a cancel_tableau section — capturing it
    # anyway would spend a Tableau session per captain on an image nothing
    # shows.
    kinds = {k for _, k in captain.sections}
    wants_tableau = bool(kinds & {"cancel_tableau", "teamstats_tableau"})
    if skip_tableau or not wants_tableau:
        if skip_tableau:
            logfn("  (‑‑skip-tableau) Tableau §2 shot skipped")
            errors["cancel_tableau"] = "skipped by --skip-tableau"
            errors["teamstats_tableau"] = "skipped by --skip-tableau"
        cancel_tableau, teamstats_tableau = None, None
    else:
        cancel_tableau, teamstats_tableau = _tableau_shots(
            captain, today, render_dir, logfn=logfn, errors=errors)

    bundle = {
        "product_summary": ps,
        "units": units,
        "churn_ni": churn_ni,
        "churn_wireless": churn_wireless,
        # §2 Tableau shots (cancel rates / team stats breakout), filtered to the
        # captain's team. None → email_build shows a per-section 'pending' note.
        "cancel_tableau": cancel_tableau,
        "teamstats_tableau": teamstats_tableau,
        "boxes": boxes,
        "fiber_activation": (fiber_png.fiber_activation_png(
            captain.key, today, render_dir, logfn=logfn)
            if captain.flavor == "fiber" else None),
        # Why anything above is missing (see _pending in email_build).
        "errors": errors,
    }
    # A box that rendered into nothing is a per-slot miss, not a whole-tab
    # failure — say which slot rather than leaving that one section mute.
    for _h, _k in captain.sections:
        if _k.startswith("box:") and _k.split(":", 1)[1] not in boxes:
            errors.setdefault(_k, "no box rendered for this slot on this run")
    n_imgs = sum([ps is not None, len(units), len(churn), len(boxes),
                  cancel_tableau is not None, teamstats_tableau is not None,
                  bundle["fiber_activation"] is not None])
    if not n_imgs:
        logfn(f"  ⚠ no images at all for {captain.key} — skipping")
        return None
    bundle["_n_imgs"] = n_imgs
    return bundle


def _pad_pngs_to_common_width(paths) -> None:
    """Right-pad every PNG in `paths` with white to the group's MAX width, in
    place, so same-flavor same-section shots share one width. Height is left
    alone — it legitimately varies with row count. No-op for <2 images or when
    all are already equal width."""
    from PIL import Image
    ps = [Path(p) for p in paths if p]
    if len(ps) < 2:
        return
    ims = [(p, Image.open(p).convert("RGB")) for p in ps]
    target = max(im.width for _, im in ims)
    for p, im in ims:
        if im.width == target:
            continue
        canvas = Image.new("RGB", (target, im.height), "white")
        canvas.paste(im, (0, 0))          # content left-aligned, white on right
        canvas.save(p)


def _normalize_sizes(built, *, logfn=print) -> None:
    """Pad each SHEET-SCREENSHOT section's PNGs to a common width WITHIN each
    flavor, so every fiber Product Summary is one width, etc. Those vary in
    pixel width because sheet column widths differ per captain.

    The churn images and metric boxes are deliberately left out — see the note
    below. Runs across all captains of a flavor present in THIS run (a
    single-captain run has nothing to match)."""
    from collections import defaultdict
    by_flavor: dict = defaultdict(list)
    for captain, bundle in built:
        by_flavor[captain.flavor].append(bundle)
    for flavor, bundles in by_flavor.items():
        for key in ("product_summary", "cancel_tableau", "teamstats_tableau",
                    "fiber_activation"):
            _pad_pngs_to_common_width([b.get(key) for b in bundles])
        # NOT normalized: the churn images and the metric boxes. Both are OUR
        # renders, and since 2026-07-29 their width is meaningful — it's the
        # number of days that tab actually holds. Padding a 2-day box out to a
        # 7-day one's width would put back exactly the empty strip on the right
        # that Eve asked us to remove. Only the sheet SCREENSHOTS get matched,
        # which is what this step was built for (per-captain column widths).
        #
        # (caption, path) lists — normalize per index so fiber's New-Internet and
        # All-Units unit charts each match their counterpart across captains.
        for key in ("units",):
            depth = max((len(b.get(key) or []) for b in bundles), default=0)
            for i in range(depth):
                _pad_pngs_to_common_width(
                    [b[key][i][1] for b in bundles if len(b.get(key) or []) > i])


def main(argv=None) -> int:
    # Flush every line as it is printed. Under the orchestrator stdout is a pipe,
    # so Python block-buffers it and a run killed by its timeout takes the whole
    # log with it — the first unattended run on the mini hit the 45-minute cap
    # and left 12 lines of venv warnings and no clue where it had got to.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:       # noqa: BLE001 — diagnostics must never break a run
        pass
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
    ap.add_argument("--no-replace", action="store_true",
                    help="Keep any existing draft for the same captain+date "
                         "instead of deleting it first (default: replace).")
    ap.add_argument("--send", action="store_true",
                    help="SEND each report to the captain's configured "
                         "recipient instead of leaving a draft. Use this "
                         "rather than opening the draft in Gmail — opening it "
                         "strips the inline images out of the sent mail.")
    ap.add_argument("--send-reviewed", action="store_true",
                    help="Send the previews already sitting in output/ for "
                         "this date — the EXACT files you reviewed. Builds "
                         "nothing, re-reads no sheet, so what goes out cannot "
                         "differ from what you approved. This is the approval "
                         "gate: --dry-run first, look, then this.")
    ap.add_argument("--to", default=None, metavar="ADDR",
                    help="With --send: send to ADDR instead of the captains' "
                         "real distribution lists. Use this to test a real "
                         "report on yourself before mailing 145 people.")
    ap.add_argument("--distro-check", action="store_true",
                    help="Print where each captain's recipients come from "
                         "(their 'Captainship - <Name>' contact group vs the "
                         "fallback list in config.py) and exit. Builds "
                         "nothing, sends nothing.")
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

    if args.distro_check:
        print("=== Captainship recipients — contact group vs config.py ===")
        drifted = distro.diff_report([c.key for c in selected])
        print(f"\n{drifted} captain(s) whose group differs from config.py."
              if drifted else "\nEvery group matches config.py.")
        return 0

    mode = ("SEND REVIEWED" if args.send_reviewed else
            "DRY-RUN (preview .eml)" if args.dry_run else
            "LIVE SEND" if args.send else "LIVE (create drafts)")
    print(f"=== Captainship Drafts — {today.isoformat()} ({mode}) ===")
    print(f"Captains: {[c.key for c in selected]}")

    if args.send_reviewed:
        # Nothing to capture — this path only mails what's already on disk.
        n = _send_reviewed(selected, today, to_override=args.to)
        if n:
            print(f"\n✗ {n} captain(s) not sent.")
            return 1
        print("\n=== done ===")
        return 0

    render_dir = Path(tempfile.gettempdir()) / "captainship_drafts_render"
    failures = 0

    # Pass 1: capture every captain's images. Pass 2 (below) assembles + emits,
    # with a size-normalization step in between so same-flavor sections match.
    built = []
    for captain in selected:
        try:
            bundle = _capture_one(captain, today, render_dir,
                                  skip_sheets=args.skip_sheets,
                                  skip_tableau=args.skip_tableau)
        except Exception as e:
            failures += 1
            print(f"  ✗ {captain.key}: capture failed: {e}")
            continue
        if bundle is None:
            failures += 1
            continue
        built.append((captain, bundle))

    _normalize_sizes(built)

    # Assemble + emit per captain, ISOLATED: an assembly or Gmail failure on
    # one captain must not abort the other 11 (it did on 2026-07-25 — the run
    # stopped dead after the first draft and 11 captains got nothing).
    for captain, bundle in built:
        try:
            msg = email_build.build(captain, bundle, today)
            # Resolved only for a real send: expanding 12 contact groups on
            # every --dry-run build would be 12 People API calls for nothing.
            recipient = (args.to or captain.recipients()) if args.send else ""
            if args.send:
                msg.replace_header("To", recipient)
            print(f"  built draft: subj={msg['Subject']!r}, "
                  f"{bundle['_n_imgs']} image(s)")

            if args.send and not args.dry_run:
                if not recipient.strip():
                    failures += 1
                    print(f"  ✗ {captain.key}: --send but no recipient — "
                          f"{distro.group_name(captain.key)!r} is empty/missing "
                          f"and the config.py fallback is blank — skipped")
                    continue
                # Always leave the reviewable .html next to the sent mail, so
                # there's a record of exactly what went out.
                _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                eml = _OUTPUT_DIR / (
                    f"captainship_sent_{captain.key}_{today:%Y%m%d}.eml")
                eml.write_bytes(bytes(msg))
                preview.eml_to_html(eml)
                from automations.captainship_drafts.mailer import send_one
                # Sweep any leftover draft for this captain+date first, so a
                # sent report doesn't leave a stale draft someone might open
                # and re-send (which is exactly how the images get stripped).
                # Best-effort: on the mini there is no Gmail token to sweep with
                # (and nothing has created a draft since 2026-07-27).
                if not args.no_replace:
                    _delete_prior_drafts(captain, today)
                send_one(msg)
            elif args.dry_run:
                _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                eml = _OUTPUT_DIR / (
                    f"captainship_draft_{captain.key}_{today:%Y%m%d}.eml")
                eml.write_bytes(bytes(msg))
                # Also emit a browser-previewable .html (cid images inlined as
                # data URIs) — an .eml shows blank when dragged into Gmail.
                html = preview.eml_to_html(eml)
                print(f"  ✓ preview written: {eml.name} + {html.name}")
            else:
                # LIVE. Sweep this captain's prior draft for today FIRST, so
                # a re-run replaces instead of accumulating. Delete-then-
                # create (not update) keeps it simple and self-healing: a
                # draft deleted by hand just means nothing to sweep.
                if not args.no_replace:
                    _delete_prior_drafts(captain, today)
                from automations.shared.gmail_draft import create_draft
                res = create_draft(msg)
                print(f"  ✓ draft created: {res}")
        except Exception as e:
            failures += 1
            import traceback
            print(f"  ✗ {captain.key}: draft not created: "
                  f"{type(e).__name__}: {e}")
            # stdout, not stderr — the orchestrator log tail only keeps stdout,
            # which is why this failure showed up as a bare "exit 1".
            traceback.print_exc(file=sys.stdout)

    if args.dry_run:
        # One page linking today's previews, so review means opening ONE file
        # instead of picking 12 out of a folder full of older dates.
        try:
            from automations.captainship_drafts import review_index
            review_index.build_index(today)
        except Exception as e:
            print(f"  ⚠ review index not written ({type(e).__name__}: {e})")

    if failures:
        print(f"\n✗ {failures} captain(s) failed.")
        return 1
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
