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
        print(f"    (no row matched — {_sample_rows(page)})")
    return None


# --- typo-tolerant name matching ----------------------------------------------
# Admins type these names by hand in Slack, so "Crenshawe" / "Thomes" happen.
# But a WRONG match uploads someone's face onto another rep's profile, and the
# table really does hold near-twins (Ana Gonzalez vs Ana Griffin). So: forgive
# typos, and REFUSE to guess when two candidates are close — an ambiguous case
# is reported for manual handling instead (Megan 2026-08-24).
_MIN_SCORE = 0.86        # below this, not the same person
_MIN_MARGIN = 0.06       # winner must beat the runner-up by this much

_ROW_NAMES_JS = """() => [...document.querySelectorAll('tbody tr')].map(tr => {
    const lines = (tr.innerText || '').split('\\n')
        .map(s => s.trim()).filter(Boolean);
    return lines.length ? lines[0] : '';
})"""


def _name_key(s: str) -> str:
    """Lowercase, drop punctuation/suffixes, collapse spaces."""
    s = re.sub(r"\(.*?\)", " ", s or "")            # strip the (9445955) id
    s = re.sub(r"[^A-Za-z ]", " ", s).lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _name_score(want: str, got: str) -> float:
    """0-1 similarity between a submitted name and a table name."""
    from difflib import SequenceMatcher
    a, b = _name_key(want), _name_key(got)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    at, bt = a.split(), b.split()
    # Every submitted token close to some table token (covers middle names
    # and extra surnames: "Raymond Carriere" vs "Raymond Joseph Carriere Jr").
    if at and all(
            any(SequenceMatcher(None, x, y).ratio() >= 0.88 for y in bt)
            for x in at):
        return 0.95
    # Same tokens in a different order ("Crenshaw Thomas").
    if sorted(at) == sorted(bt):
        return 0.97
    return SequenceMatcher(None, a, b).ratio()


def _fuzzy_row(page, name: str, *, verbose: bool = True):
    """Best typo-tolerant row match, or None. Returns (row, matched_name).

    Refuses to return an ambiguous winner — two near-equal candidates mean
    a human decides, never the bot."""
    try:
        names = page.evaluate(_ROW_NAMES_JS)
    except Exception:
        return None, None
    scored = sorted(
        ((_name_score(name, n), i, n) for i, n in enumerate(names) if n),
        reverse=True)
    if not scored:
        return None, None
    best, idx, got = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0.0
    if best < _MIN_SCORE:
        return None, None
    if best - runner < _MIN_MARGIN:
        if verbose:
            print(f"    AMBIGUOUS {name!r}: {got!r} ({best:.2f}) vs "
                  f"{scored[1][2]!r} ({runner:.2f}) — refusing to guess")
        return None, None
    if verbose and best < 1.0:
        print(f"    fuzzy-matched {name!r} -> {got!r} ({best:.2f})")
    return page.locator("tbody tr").nth(idx), got


def _sample_rows(page, limit: int = 3) -> str:
    """A short, SAFE description of what's in the table right now.

    Debug logging must never break a run: the first retry (2026-08-24) died
    inside the old dump when the table re-rendered and .nth(1) hung for 30s.
    Everything here is short-timeout and exception-swallowing."""
    try:
        rows = page.locator("tbody tr")
        n = rows.count()
    except Exception:
        return "couldn't count rows"
    out = []
    for i in range(min(limit, n)):
        try:
            out.append(_norm(rows.nth(i).inner_text(timeout=2000))[:50])
        except Exception:
            out.append("(unreadable)")
    return f"{n} row(s): " + " | ".join(out)


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
    """The row's Upload Documents state: 'uploaded', 'missing', 'unknown'.

    Text alone is NOT enough (2026-08-24): the green state's checkmark is an
    ICON, so inner_text() reads plain "Photo" for both states — which made
    every rep look like they needed a photo. Decide on the pill element's
    COLOR/CLASS instead (OV uses bootstrap-ish success/green vs
    danger/warning/orange), and only fall back to text."""
    try:
        state = row.evaluate(
            """el => {
                 const pills = [...el.querySelectorAll('span,div,button,td')]
                   .filter(n => /(^|\\s)photo(\\s|$)/i.test(
                       (n.textContent || '').trim()));
                 if (!pills.length) return 'unknown';
                 const p = pills[pills.length - 1];
                 const cls = (p.className || '') + ' ' +
                             ((p.parentElement || {}).className || '');
                 const bg = getComputedStyle(p).backgroundColor || '';
                 const m = bg.match(/\\d+/g) || [];
                 const [r, g, b] = m.map(Number);
                 const greenish = (r !== undefined) &&
                                  (g > r + 20) && (g > (b || 0) + 20);
                 const hasIcon = !!p.querySelector('i,svg,.fa,.fas,.glyphicon');
                 if (/success|green/i.test(cls) || greenish) return 'uploaded';
                 if (/danger|warning|orange|red/i.test(cls)) return 'missing';
                 return hasIcon ? 'uploaded' : 'missing';
               }""")
        if state in ("uploaded", "missing"):
            return state
    except Exception:
        pass
    try:
        txt = _norm(row.inner_text(timeout=3000))
    except Exception:
        return "unknown"
    if "✓ photo" in txt or "✓photo" in txt:
        return "uploaded"
    return "missing" if "photo" in txt else "unknown"


def dump_pill(page, row, name: str) -> None:
    """Print the Upload Documents cell markup — the ground truth for how
    OV renders uploaded vs missing. Diagnostic only."""
    try:
        html = row.evaluate(
            """el => [...el.querySelectorAll('td')]
                 .map(td => td.innerHTML.trim())
                 .filter(h => /photo/i.test(h))
                 .join('\\n---\\n').slice(0, 1200)""")
        print(f"    [pill markup for {name}]\n{html or '(no photo cell)'}")
    except Exception as e:  # noqa: BLE001
        print(f"    (couldn't dump pill markup: {type(e).__name__})")


def _search_probes(name: str):
    """Short strings to type in the DataTables search, best first.

    Full names filter to zero, so probe with the last name, then 4-char
    prefixes of the last and first name — a typo in the tail ("Crenshawe")
    still narrows the table, and a typo in the last name is covered by the
    first-name prefix."""
    parts = [p for p in name.split() if p]
    if not parts:
        return []
    out, seen = [], set()
    for cand in ([parts[-1], parts[-1][:4]] +
                 ([parts[0], parts[0][:4]] if len(parts) > 1 else [])):
        c = cand.strip()
        if len(c) >= 3 and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def find_rep(page, name: str, *, verbose: bool = True):
    """Locate the rep across campaigns/filters, tolerating typos.

    Returns (row, campaign, matched_name) or (None, tried_campaigns, None).
    matched_name is what the OV table actually calls them, which can differ
    from what was typed in Slack."""
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
            for probe in _search_probes(name):
                box = _search_box(page)
                box.fill("")
                # Search a SHORT probe, not the full name (probe #6: the
                # whole "First Last" string filters to zero — the searchable
                # field doesn't hold the display string). Prefixes also let
                # a typo'd tail still narrow the table. Key-by-key: old
                # DataTables filters on keyup, which fill() never fires.
                box.press_sequentially(probe, delay=40)
                page.wait_for_timeout(900)      # filters client-side
                row = _rep_row(page, name, debug=False)
                if row is None:
                    # One retry: DataTables sometimes re-renders under us
                    # and the first read hits the old body (2026-08-24).
                    page.wait_for_timeout(1500)
                    row = _rep_row(page, name, debug=False)
                matched = name
                if row is None:
                    # Exact text failed — allow a typo, but never a guess
                    # between near-twins.
                    row, got = _fuzzy_row(page, name, verbose=verbose)
                    if row is not None:
                        matched = got or name
                if row:
                    if verbose:
                        print(f"  found {matched!r} under {label}"
                              f"{' (Show All)' if widen else ''}")
                    return row, label, matched
            if verbose:
                print(f"    ({label}{' / Show All' if widen else ''}: "
                      f"{_sample_rows(page)})")
    return None, tried, None


def _click_any(scope, label: str, *, page=None, timeout: int = 12000) -> None:
    """Click a control named `label` inside `scope`, trying every shape OV
    might render it as. The first live run (Thomas Crenshaw, 2026-08-24)
    died on a bare get_by_text click that never resolved — OV renders these
    as <button>/<input value=…>/<a> inconsistently, so try them all, then
    force, then raw JS. On total failure DUMP the scope's HTML so the log
    says what's actually there instead of only that a click timed out."""
    attempts = (
        ("role=button", lambda: scope.get_by_role("button", name=label,
                                                  exact=False)),
        ("role=link", lambda: scope.get_by_role("link", name=label,
                                                exact=False)),
        ("input[value]", lambda: scope.locator(
            f"input[value='{label}' i], input[type='button'][value*='{label}' i]")),
        ("text", lambda: scope.get_by_text(label, exact=True)),
        ("text-loose", lambda: scope.get_by_text(label, exact=False)),
        ("css-contains", lambda: scope.locator(
            f"button:has-text('{label}'), a:has-text('{label}')")),
    )
    for how, build in attempts:
        try:
            loc = build().first
            if not loc.count():
                continue
            try:
                loc.click(timeout=timeout)
            except Exception:
                loc.click(force=True, timeout=5000)
            print(f"    clicked {label!r} via {how}")
            return
        except Exception:
            continue
    # Nothing worked — show the markup so the next run is not a guess.
    try:
        html = scope.evaluate("el => el.outerHTML")[:1500]
    except Exception:
        html = "(couldn't read HTML)"
    print(f"    !! no clickable {label!r} found. Scope HTML:\n{html}")
    raise OVUploadError(f"couldn't click {label!r} — see the HTML dump above")


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
        row, campaign, matched = find_rep(page, name, verbose=verbose)
        if row is None:
            return {"status": "not_found", "name": name, "tried": campaign}
        # What OV calls them, when a typo was forgiven — surfaced so the
        # Slack thread always shows WHO the photo actually went to.
        extra = {"matched_as": matched} if matched and matched != name else {}

        pill = _photo_pill(row)
        if dry_run:
            dump_pill(page, row, name)      # diagnostic on read-only runs
            return {"status": "already_uploaded" if pill == "uploaded"
                    else "dry_run_found", "name": name,
                    "campaign": campaign, "pill": pill, **extra}
        if pill == "uploaded":
            return {"status": "already_uploaded", "name": name,
                    "campaign": campaign, **extra}
        if photo is None or not Path(photo).exists():
            raise OVUploadError(f"photo file missing: {photo}")

        # Edit -> Set Status modal.
        _click_any(row, "Edit", page=page)
        modal = page.locator(".modal:visible, [role='dialog']:visible").filter(
            has_text="Set Status").first
        modal.wait_for(state="visible", timeout=20000)

        # UPLOAD DOCUMENTS section — expand if collapsed (the Photo row's
        # Upload link is hidden until the section opens).
        photo_row = modal.locator("tr").filter(
            has_text=re.compile(r"\bPhoto\b", re.I)).first
        if not photo_row.is_visible():
            _click_any(modal, "UPLOAD DOCUMENTS", page=page)
            photo_row.wait_for(state="visible", timeout=15000)

        # Upload via the file chooser — never the OS dialog. An <input
        # type=file> in the row is the most direct path; fall back to the
        # chooser event when the input is script-driven.
        file_input = photo_row.locator("input[type='file']")
        if file_input.count():
            file_input.first.set_input_files(str(photo))
        else:
            with page.expect_file_chooser(timeout=20000) as fc:
                _click_any(photo_row, "Upload", page=page)
            fc.value.set_files(str(photo))

        # Success = the Action cell flips to "Uploaded" (Megan's screenshot).
        photo_row.get_by_text("Uploaded", exact=False).first.wait_for(
            timeout=90000)
        if verbose:
            print(f"  {name}: photo uploaded — saving")

        _click_any(modal, "Save Changes", page=page)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:
            pass
        time.sleep(2)

        # Verify: back on the table, the pill should now be green.
        row2, _, _ = find_rep(page, name, verbose=False)
        verified = row2 is not None and _photo_pill(row2) == "uploaded"
        return {"status": "uploaded", "name": name, "campaign": campaign,
                "verified": verified, **extra}


def archived_headshot(name: str) -> Path | None:
    """The most recent processed headshot for `name` in output/headshots/.

    Lets the OV leg be retried on its own after a Slack reply has already
    been processed (that reply is marked done and never reprocesses, so the
    photo would otherwise have to be resubmitted)."""
    root = Path(__file__).resolve().parents[2] / "output" / "headshots"
    hits = sorted(root.glob(f"*/{_safe_name(name)} - Headshot.png"))
    return hits[-1] if hits else None


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 '-]", "", name).strip()


def announce(res: dict, *, dry_run: bool = False) -> str | None:
    """Post the outcome of a one-off OV retry into this week's headshot
    thread, so a stale "please upload this one manually" note never stands
    after the upload actually went through (Megan 2026-08-24).

    Posts as whoever this machine is — run it on Lucy 3 so it lands as
    Lucy, like every other message in the thread."""
    from automations.headshots import weekly_thread as wt
    name = res.get("name", "")
    as_who = (f" (matched to *{res['matched_as']}* in OwnerVille)"
              if res.get("matched_as") else "")
    if res.get("status") == "uploaded":
        text = (f":white_check_mark: *{name}* — sorted. The headshot is now "
                f"on their OwnerVille profile{as_who}. The earlier "
                "\u26a0\ufe0f note above is resolved.")
    elif res.get("status") == "already_uploaded":
        text = (f":white_check_mark: *{name}* — confirmed: the headshot is on "
                f"their OwnerVille profile{as_who}. The earlier "
                "\u26a0\ufe0f note above is resolved.")
    else:
        return None
    cl = wt._client()
    anchor = wt.find_week_anchor(cl, wt.CHANNEL_ID)
    if not anchor:
        print("  (no headshot thread this week — nothing to update)")
        return None
    if dry_run:
        print(f"  WOULD post in thread {anchor['ts']}:\n    {text}")
        return None
    cl.chat_postMessage(channel=wt.CHANNEL_ID, thread_ts=anchor["ts"],
                        text=text)
    print(f"  posted the correction in this week's thread ({anchor['ts']})")
    return anchor["ts"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Upload a headshot to OwnerVille.")
    ap.add_argument("--name", required=True, help='rep name, "First Last"')
    ap.add_argument("--file", default=None, help="processed headshot PNG")
    ap.add_argument("--from-archive", action="store_true",
                    help="use the newest processed headshot in output/headshots/ "
                         "for --name (retry the OV leg on its own)")
    ap.add_argument("--dry-run", action="store_true",
                    help="find the rep + report the photo pill, change nothing")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser (debug)")
    ap.add_argument("--announce", action="store_true",
                    help="post the outcome in this week's headshot thread "
                         "(clears a stale 'upload manually' note)")
    ap.add_argument("--announce-dry", action="store_true",
                    help="print the thread message instead of posting it")
    args = ap.parse_args(argv)
    photo = Path(args.file) if args.file else None
    if photo is None and args.from_archive:
        photo = archived_headshot(args.name)
        if photo is None:
            print(f"no archived headshot for {args.name!r} in output/headshots/")
            return 1
        print(f"using archived headshot: {photo}")
    res = upload(args.name, photo,
                 dry_run=args.dry_run, headless=not args.headed)
    print(res)
    if args.announce or args.announce_dry:
        announce(res, dry_run=args.announce_dry)
    return 0 if res["status"] in ("uploaded", "already_uploaded",
                                  "dry_run_found") else 1


if __name__ == "__main__":
    sys.exit(main())
