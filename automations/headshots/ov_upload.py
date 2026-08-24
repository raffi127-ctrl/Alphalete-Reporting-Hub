"""Upload a finished headshot to the rep's OwnerVille profile.

Megan's click-path (2026-08-23, walked through with screenshots):
  v2.ownerville.com -> Onboard -> View Progress (index.cfm?p=201)
  -> campaign dropdown top-left (a rep lives under ONE campaign, so we try
     each option until the name matches)
  -> search bar top-right, search the name
  -> if no match: flip "Filter by Activation Date" to "Show All", search again
  -> Edit under the rep's name -> "<Name> - Set Status" modal
  -> UPLOAD DOCUMENTS section -> row "Photo / Image / Required: Yes"
  -> Upload (a file chooser; patchright feeds the file directly, no OS dialog)
  -> the Action cell flips to "Uploaded" (+ Remove) = success signal
  -> Save Changes (required — the upload alone isn't saved).

The progress table's "Upload Documents" column already shows a Photo pill:
green "✓ Photo" = a photo is on file (we SKIP those — never overwrite what an
admin uploaded), orange = missing. That pill is also the after-save verify.

Login: the shared ownerville storage_state via ownerville_session() — never a
fresh Turnstile login. Own browser profile so this never collides with the
tracker screenshots on Lucy 3 (separate profiles don't block each other).

    # find the rep, report the pill state, change NOTHING:
    python -m automations.headshots.ov_upload --name "Ahna Vanmeter" --dry-run

    # real upload (one rep, one file):
    python -m automations.headshots.ov_upload --name "First Last" --file out.png
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# View Progress is p=201, but a bare p=<id> BOUNCES TO WELCOME — every OV
# page URL needs the session's rqst token appended (the trap b2b_dispositions/
# total_knocks/car_rides all document). find_rep builds the URL at runtime.
VIEW_PROGRESS_P = 201

# Own profile — never the shared one (profile-lock wedge, 2026-08-19).
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_headshots")


class OVUploadError(RuntimeError):
    pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _campaign_select(page):
    """The campaign dropdown top-left (RES-AT&T, ...). The page also carries
    HIDDEN selects (e.g. an address-form select#state, which the first probe
    run grabbed and hung on) — so only a VISIBLE select counts."""
    sel = page.locator("select:visible").first
    sel.wait_for(state="visible", timeout=20000)
    return sel


def _search_box(page):
    """DataTables' search input top-right of the progress table."""
    box = page.locator("input[type='search']:visible").first
    box.wait_for(state="visible", timeout=20000)
    return box


def _rep_row(page, name: str, *, debug: bool = False):
    """The table row containing `name` (case-insensitive, any cell).

    Probe #5 (2026-08-23) proved reading only the FIRST td misses real reps
    — DataTables likes a hidden control column up front. has_text matches
    the name anywhere in the row instead; whitespace between first/last is
    matched loosely (the cell breaks lines).
    """
    parts = [p for p in name.split() if p]
    if not parts:
        return None
    pat = re.compile(r"\s+".join(re.escape(p) for p in parts), re.I)
    rows = page.locator("tbody tr").filter(has_text=pat)
    if rows.count():
        return rows.first
    if debug:
        allrows = page.locator("tbody tr")
        n = allrows.count()
        print(f"    (no row matched — {n} row(s) on screen; first few: "
              + " | ".join(
                  _norm(allrows.nth(i).inner_text())[:60]
                  for i in range(min(3, n))))
    return None


def _show_all(page) -> None:
    """Flip 'Filter by Activation Date' from Show Last 3 Weeks to Show All.

    The exact-text click missed on the mini (2026-08-23 probe — the label
    text isn't its own exact node), so: the filter is two visible radios,
    Show Last 3 Weeks first and Show All second — check the LAST one.
    Text click stays as the fallback."""
    radios = page.locator("input[type='radio']:visible")
    if radios.count() >= 2:
        target = radios.last
        try:
            target.check(timeout=5000)
        except Exception:
            # The input sits under a styled span — actionability never
            # settles (mini probe #4). Force it, then raw JS as last resort.
            try:
                target.click(force=True, timeout=5000)
            except Exception:
                target.evaluate(
                    "el => { el.checked = true;"
                    " el.dispatchEvent(new Event('click',  {bubbles: true}));"
                    " el.dispatchEvent(new Event('change', {bubbles: true})); }")
    else:
        page.get_by_text("Show All").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass
    page.wait_for_timeout(1500)     # the Show All table is even bigger


def _photo_pill(row) -> str:
    """The row's Upload Documents state: 'uploaded' (green ✓ Photo),
    'missing' (orange Photo), or 'unknown'."""
    try:
        txt = _norm(row.inner_text())
    except Exception:
        return "unknown"
    if "✓ photo" in txt or "✓photo" in txt:
        return "uploaded"
    if "photo" in txt:
        return "missing"
    return "unknown"


def find_rep(page, name: str, *, verbose: bool = True):
    """Locate the rep across campaigns/filters. Returns (row, campaign) or
    (None, tried_campaigns)."""
    from automations.b2b_dispositions.capture import capture_rqst
    rqst = capture_rqst(page)
    # View Progress renders a huge DataTable (every rep + a pill per column)
    # — the default 30s goto timed out on the mini (2026-08-23 probe). Give
    # it 90s and one retry; the second load is usually warm.
    page.set_default_navigation_timeout(90000)
    url = (f"https://v2.ownerville.com/index.cfm?p={VIEW_PROGRESS_P}"
           f"&rqst={rqst}")
    for attempt in (1, 2):
        try:
            page.goto(url, wait_until="domcontentloaded")
            break
        except Exception:
            if attempt == 2:
                raise
            if verbose:
                print("  view-progress load timed out — retrying once")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass                      # the select wait below is the real gate
    sel = _campaign_select(page)
    options = sel.locator("option").all_inner_texts()
    tried = []
    for opt in options:
        label = opt.strip()
        if not label:
            continue
        tried.append(label)
        sel.select_option(label=label)
        page.wait_for_load_state("networkidle")
        for widen in (False, True):
            if widen:
                _show_all(page)
            box = _search_box(page)
            box.fill("")
            # Search the LAST name only (probe #6: the full "First Last"
            # string filtered to zero — the searchable field doesn't hold
            # the display string). _rep_row still verifies the full name.
            # Key-by-key: old DataTables filters on keyup, which a plain
            # fill() never fires.
            box.press_sequentially(name.split()[-1], delay=40)
            page.wait_for_timeout(900)          # DataTables filters client-side
            row = _rep_row(page, name, debug=verbose)
            if row is None and verbose:
                # What does this account actually see? Clear the filter
                # (Backspace fires the keyup) and dump the top rows.
                box.fill("")
                box.press("Backspace")
                page.wait_for_timeout(900)
                allrows = page.locator("tbody tr")
                n = allrows.count()
                print(f"    (unfiltered {label}: {n} row(s); sample: "
                      + " | ".join(
                          _norm(allrows.nth(i).inner_text())[:50]
                          for i in range(min(3, n))))
            if row:
                if verbose:
                    print(f"  found {name!r} under {label}"
                          f"{' (Show All)' if widen else ''}")
                return row, label
    return None, tried


def upload(name: str, photo: Path | None, *, dry_run: bool = True,
           headless: bool = True, verbose: bool = True) -> dict:
    """Find the rep and upload `photo` to their profile. Returns a result
    dict: {status: uploaded|already_uploaded|not_found|dry_run_found, ...}.

    Never overwrites: a rep whose pill is already green is reported and
    SKIPPED. dry_run stops after locating the rep + reading the pill.
    """
    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=headless, verbose=verbose,
                            profile_dir=PROFILE_DIR) as page:
        row, campaign = find_rep(page, name, verbose=verbose)
        if row is None:
            return {"status": "not_found", "name": name, "tried": campaign}

        pill = _photo_pill(row)
        if pill == "uploaded":
            return {"status": "already_uploaded", "name": name,
                    "campaign": campaign}
        if dry_run:
            return {"status": "dry_run_found", "name": name,
                    "campaign": campaign, "pill": pill}
        if photo is None or not Path(photo).exists():
            raise OVUploadError(f"photo file missing: {photo}")

        # Edit -> Set Status modal.
        row.get_by_text("Edit", exact=True).first.click()
        modal = page.locator(".modal, [role='dialog']").filter(
            has_text="Set Status").first
        modal.wait_for(state="visible", timeout=20000)

        # UPLOAD DOCUMENTS section — expand if collapsed (the Photo row's
        # Upload link is hidden until the section opens).
        section = modal.get_by_text("UPLOAD DOCUMENTS", exact=False).first
        photo_row = modal.locator("tr").filter(has_text="Photo").first
        if not photo_row.is_visible():
            section.click()
            photo_row.wait_for(state="visible", timeout=10000)

        # Upload via the file chooser — never the OS dialog.
        with page.expect_file_chooser(timeout=20000) as fc:
            photo_row.get_by_text("Upload", exact=True).click()
        fc.value.set_files(str(photo))

        # Success = the Action cell flips to "Uploaded" (Megan's screenshot).
        photo_row.get_by_text("Uploaded", exact=True).wait_for(timeout=60000)
        if verbose:
            print(f"  {name}: photo uploaded — saving")

        modal.get_by_text("Save Changes", exact=True).click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # Verify: back on the table, the pill should now be green.
        row2, _ = find_rep(page, name, verbose=False)
        verified = row2 is not None and _photo_pill(row2) == "uploaded"
        return {"status": "uploaded", "name": name, "campaign": campaign,
                "verified": verified}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Upload a headshot to OwnerVille.")
    ap.add_argument("--name", required=True, help='rep name, "First Last"')
    ap.add_argument("--file", default=None, help="processed headshot PNG")
    ap.add_argument("--dry-run", action="store_true",
                    help="find the rep + report the photo pill, change nothing")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser (debug)")
    args = ap.parse_args(argv)
    res = upload(args.name, Path(args.file) if args.file else None,
                 dry_run=args.dry_run, headless=not args.headed)
    print(res)
    return 0 if res["status"] in ("uploaded", "already_uploaded",
                                  "dry_run_found") else 1


if __name__ == "__main__":
    sys.exit(main())
