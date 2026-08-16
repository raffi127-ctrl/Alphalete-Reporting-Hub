"""Inspect the Carlos bonus source view: what worksheets it offers, and what
shape each one actually has.

READ-ONLY with respect to report data: it downloads crosstabs to a scratch dir
and writes its findings to a DIAGNOSTIC tab. It never touches the
*All In One - CARLOS* sheet.

Why this exists: when ATTTRACKER-B2B was restructured on 2026-08-13 the old
`CaptainsTeam` sheet vanished and every worksheet on the replacement view had
been renamed, so the pull failed on the FIRST worksheet and its error only
named that one. Reading the failure through `lucy logtail` didn't help either —
the result cell caps at ~470 chars and the dialog's name list is one long line,
so it always came back truncated.

Two modes:

  # names only (fast, no downloads) — one per line, prefixed XTAB:
  lucy rerun probe_carlos_bonus_sheets --machine "Lucy 2"
  lucy logtail <that log> XTAB 15

  # names + column headers + sample rows for the candidate worksheets
  lucy rerun probe_carlos_bonus_sheets --dump --machine "Lucy 2"
  ...then read the '<DIAG_TAB>' tab (too big for logtail).

Re-run this after any republish of the workbook, then re-map
tableau_pull.SHEETS. [[project_carlos-captainship-bonus-view-dead]]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

# Same scratch workbook the ATT Order Log probe writes to — a diagnostics-only
# book, so a new tab here is never someone's filled-in work.
DIAG_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
DIAG_TAB = "Carlos Bonus Probe"

# Worksheets worth dumping when --dump is on: the ones whose names suggest they
# could carry what tableau_pull needs. Names come from the 2026-08-13 listing.
# The (LW)/(LW2) pair matters: the plain "_Captain View" sales sheet ignores the
# week param and always renders the IN-PROGRESS week as day columns, so the
# completed week has to come from a last-week sheet.
CANDIDATES = (
    "Sales By ICD (ATT) (V2)_Captain View",
    "Sales By ICD (ATT) (V2) (LW2)",
    "ICD Summary - ATT (V2) (LW)_Captain's View",
    "ICD Summary - ATT (V2) (TW) (3)",
    "ICD Churn Rate- Captain's View",
    "Churn, Activation and Tiers",
    "Captains View - Non pmt%",
    "Activation Rate- Captains View",
)

# The captain-team filter, same field captainship_drafts drives (proven live
# 2026-07-22). Applying it is what collapses the new views' CRU/IRU split into a
# single "Grand Total" row per team — which is the shape the old, now-deleted
# 'Captain Team Check' worksheets had.
TEAM_FIELD = "B2B Captain's Teams (SFDC)"
TEAM_VALUE = "Carlos's Team"

# GROUND TRUTH for identifying the replacement worksheet. These are the values
# the report itself wrote into the 'Carlos B2B Captainship' tab for WE 8.9 — the
# last week that filled BEFORE the workbook was restructured. A candidate sheet
# that reproduces them (pinned to that week, team-filtered) is the replacement;
# one that doesn't, isn't. Beats guessing from worksheet names, which no longer
# resemble the old ones at all.
FINGERPRINT_WEEK_SAT = "2026-08-08"      # the Saturday of WE 8.9
FINGERPRINT_TOTAL = 827
FINGERPRINT_REPS = {
    "atef choudhury": 221, "carlos hidalgo": 90, "george hipolito": 101,
    "jamis garay": 87, "joey ramirez": 81, "justin wood": 70,
    "kinsey guenther": 76, "joseph eckhart": 48, "sabrina alicea": 34,
    "gary whitaker": 19,
}


def _fingerprint(rows, rec) -> None:
    """Does this crosstab carry the WE 8.9 per-owner numbers the report already
    wrote? Scans EVERY cell of each row for the expected integer, so it works
    regardless of which column ends up holding the weekly total."""
    from automations.carlos_captainship_bonus import tableau_pull as T

    def _is(cell, name) -> bool:
        # startswith, not equality: ACTIVATIONRATES' member is
        # "CARLOS HIDALGO\r [alphalete …]" — the office is glued onto the name.
        c = T._norm(str(cell).replace("\r", " ").replace("\n", " "))
        return c == name or c.startswith(name + " ")

    found, missing = [], []
    for name, want in sorted(FINGERPRINT_REPS.items()):
        mine = [r for r in rows if any(_is(c, name) for c in r[:3])]
        if not mine:
            missing.append(f"{name}=<no row>")
            continue
        # Try the value in ONE row, then the SUM down each column. A view that
        # splits an owner across rows (ACTIVATIONRATES has a row per Activation
        # Bucket) only reconciles once the buckets are added up, and checking
        # single rows there would report a false miss.
        width = max(len(r) for r in mine)
        hit = None
        for ci in range(width):
            vals = [T._parse_int(r[ci]) for r in mine
                    if ci < len(r) and (r[ci] or "").strip()]
            if not vals:
                continue
            if len(mine) == 1 and vals[0] == want:
                hit = f"col{ci}"
                break
            if sum(vals) == want:
                hit = f"col{ci}(sum of {len(vals)})"
                break
        (found if hit else missing).append(
            f"{name}={want}@{hit}" if hit else
            f"{name}!={want} ({len(mine)} row(s), e.g. "
            f"{[str(c)[:10] for c in mine[0][:8]]})")
    rec(f"  FINGERPRINT: {len(found)}/{len(FINGERPRINT_REPS)} owners matched WE 8.9")
    if found:
        rec("    hit : " + ", ".join(found[:10]))
    if missing:
        rec("    miss: " + ", ".join(missing[:4]))


def _upload(lines) -> None:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(DIAG_SHEET_ID)
    try:
        ws = sh.worksheet(DIAG_TAB)
    except Exception:  # noqa: BLE001 — tab may not exist yet
        ws = sh.add_worksheet(title=DIAG_TAB, rows=800, cols=1)
    ws.clear()
    ws.update("A1", [[ln[:900]] for ln in lines[:800]])


SHOT_TAB = "Carlos Bonus Shot"


def _upload_shot(png_bytes: bytes) -> int:
    """base64-chunk a PNG into SHOT_TAB so a screenshot taken on the runner can
    be decoded and LOOKED AT from another machine. Same trick as 'RP Shot' /
    'Vantura Shot' — the runner has no display we can see, and a viz whose
    controls are drawn on canvas can't be found by reading the DOM."""
    import base64
    from automations.recruiting_report import fill as _fill
    b64 = base64.b64encode(png_bytes).decode()
    chunks = [b64[i:i + 45000] for i in range(0, len(b64), 45000)]
    sh = _fill._client().open_by_key(DIAG_SHEET_ID)
    try:
        ws = sh.worksheet(SHOT_TAB)
        ws.clear()
    except Exception:  # noqa: BLE001 — tab may not exist yet
        ws = sh.add_worksheet(title=SHOT_TAB, rows=max(50, len(chunks) + 5),
                              cols=1)
    ws.update("A1", [[c] for c in chunks])
    return len(chunks)


def _parse_at(spec: str):
    """'0.06,0.64' -> (0.06, 0.64). Fractions of the viz iframe box, same
    convention as activate_xy."""
    x, y = (float(v) for v in spec.split(","))
    return x, y


def shoot_view(view_url: str, rec, wait_ms: int = 25_000,
               verbose: bool = False, at=(), click: bool = False) -> None:
    """Open a view, let it render, and upload a screenshot + a dump of anything
    in the DOM that could be the hierarchy's +/- control.

    Why both: Tableau draws the crosstab on a canvas, so the '+' usually has no
    DOM node to query — but the accessibility layer sometimes exposes one, and
    when it doesn't the screenshot is what gives us the pixel position to click.
    """
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=verbose) as page:
        page.goto(view_url, wait_until="domcontentloaded")
        viz = page.frame_locator('iframe[title="Data Visualization"]')
        try:
            viz.locator(
                '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
            ).wait_for(state="visible", timeout=60_000)
        except Exception as e:  # noqa: BLE001 — a blank viz is a finding
            rec(f"  !! toolbar never rendered: {type(e).__name__}: {str(e)[:120]}")
        page.wait_for_timeout(wait_ms)

        frame = page.frame(url=lambda u: "vizql" in (u or "")) or None
        box = None
        try:
            box = page.query_selector(
                'iframe[title="Data Visualization"]').bounding_box()
            rec(f"  viz iframe box: x={box['x']:.0f} y={box['y']:.0f} "
                f"w={box['width']:.0f} h={box['height']:.0f}")
        except Exception:
            rec("  !! could not measure the viz iframe")

        # Anything that smells like an expand control, with its position so a
        # hit can be turned straight into a fractional click target.
        js = """() => {
          const out = [];
          document.querySelectorAll('*').forEach(e => {
            const a = (e.getAttribute && (e.getAttribute('aria-label') || '')) || '';
            const t = (e.getAttribute && (e.getAttribute('title') || '')) || '';
            const d = (e.getAttribute && (e.getAttribute('data-tb-test-id') || '')) || '';
            const s = (a + ' ' + t + ' ' + d).toLowerCase();
            if (!s.trim()) return;
            if (/expand|collapse|drill|hierarch|\\+\\/-|plus|minus/.test(s)) {
              const r = e.getBoundingClientRect();
              out.push([e.tagName, a.slice(0,60), t.slice(0,40), d.slice(0,50),
                        Math.round(r.x), Math.round(r.y),
                        Math.round(r.width), Math.round(r.height)]);
            }
          });
          return out.slice(0, 40);
        }"""
        for label, target in (("page", page), ("vizql-frame", frame)):
            if target is None:
                continue
            try:
                hits = target.evaluate(js)
            except Exception as e:  # noqa: BLE001
                rec(f"  !! {label}: DOM scan failed: {type(e).__name__}")
                continue
            rec(f"  {label}: {len(hits)} expand-ish element(s)")
            for h in hits:
                rec(f"CTRL: {h}")

        # Hover (and optionally click) fractional points inside the viz before
        # shooting. A Tableau hierarchy's +/- only PAINTS on hover and lives on
        # the canvas, so "hover here, then show me" is the only way to find it.
        if at and box:
            for spec in at:
                try:
                    fx, fy = _parse_at(spec)
                except Exception:
                    rec(f"  !! bad --at {spec!r} (want 'x,y' fractions)")
                    continue
                cx = box["x"] + box["width"] * fx
                cy = box["y"] + box["height"] * fy
                page.mouse.move(cx, cy)
                page.wait_for_timeout(1200)
                rec(f"  hovered {spec} -> ({cx:.0f}, {cy:.0f})")
                if click:
                    page.mouse.click(cx, cy)
                    page.wait_for_timeout(3500)
                    rec(f"  clicked {spec}")

        try:
            n = _upload_shot(page.screenshot(full_page=True))
            rec(f"  screenshot -> {SHOT_TAB!r} tab, {n} base64 chunk(s)")
        except Exception as e:  # noqa: BLE001 — never fail the probe on upload
            rec(f"  !! screenshot upload failed: {type(e).__name__}: {str(e)[:120]}")


def list_workbook_views(workbook_url: str, rec, verbose: bool = False) -> list:
    """Every view in a workbook's `/views` page, as (name, href).

    Do this BEFORE reaching for list_crosstab_sheets: the workbook page is one
    page load, while listing a view's worksheets has to open that view and wait
    for its Download dialog (minutes each). Enumerating first is what turns
    "probe the whole workbook" from a timeout into a shortlist.

    Same approach as att_order_log.probe._list_views. Never raises: a workbook
    that won't render is a finding, not a crash."""
    from automations.shared.tableau_patchright import tableau_session
    out: list = []
    with tableau_session(headless=True, verbose=verbose) as page:
        page.goto(workbook_url, wait_until="domcontentloaded")
        # The list is rendered by the SPA well after domcontentloaded.
        page.wait_for_timeout(15_000)
        try:
            links = page.eval_on_selector_all(
                "a[href*='/views/']",
                "els => els.map(e => [(e.innerText||'').trim(), "
                "e.getAttribute('href')])")
        except Exception as e:      # noqa: BLE001 — see docstring
            rec(f"  !! could not read the view list: "
                f"{type(e).__name__}: {str(e)[:160]}")
            return out
        seen = set()
        for name, href in links:
            if not href or href in seen:
                continue
            seen.add(href)
            out.append(((name or "(unnamed)").replace("\n", " ")[:70], href))
    return out


def main(argv=None) -> int:
    from automations.carlos_captainship_bonus import tableau_pull as T
    from automations.recruiting_report.opt_phase import list_crosstab_sheets

    ap = argparse.ArgumentParser(prog="carlos_captainship_bonus.probe_sheets")
    ap.add_argument("--url", action="append", default=None,
                    help="view to probe; repeatable. Default: the report's. "
                         "Names-only listing runs for EVERY url given, so one "
                         "run can settle 'which dashboard did these worksheets "
                         "move to' across several candidates. --dump uses the "
                         "FIRST url only.")
    ap.add_argument("--dump", action="store_true",
                    help="also download each CANDIDATE worksheet and print its "
                         "columns + first rows")
    ap.add_argument("--no-upload", action="store_true",
                    help="print only; don't write the diag tab")
    ap.add_argument("--team", action="store_true",
                    help=f"apply the {TEAM_FIELD!r}={TEAM_VALUE!r} URL filter")
    ap.add_argument("--cached", action="store_true",
                    help="skip Tableau entirely: dump the crosstab CSVs the LAST "
                         "GOOD run left in CACHE_DIR. These are the deleted "
                         "worksheets' exact output — the spec any replacement has "
                         "to reproduce.")
    ap.add_argument("--week-sat", default=None, metavar="YYYY-MM-DD",
                    help="pin the activation week to this SATURDAY (ISO only — "
                         "M/D/YYYY silently no-ops) instead of last cycle's")
    ap.add_argument("--no-week", action="store_true",
                    help="never append the week param. The (LW)/(LW2) sheets are "
                         "already scoped to last week, so pinning a week on top "
                         "may be what empties them.")
    ap.add_argument("--rows", type=int, default=15, metavar="N",
                    help="how many data rows to print per sheet (default 15). "
                         "Raise it for bucketed views, where one owner spans "
                         "several rows.")
    ap.add_argument("--sheet", action="append", default=None, metavar="NAME",
                    help="dump these EXACT worksheet names instead of CANDIDATES; "
                         "repeatable. Lets --dump work on any view, not just the "
                         "report's own.")
    ap.add_argument("--shot", action="store_true",
                    help="open the FIRST url, screenshot it into the "
                         f"{SHOT_TAB!r} tab (base64) and dump any DOM element "
                         "that looks like a hierarchy +/- control, then stop. "
                         "The way to SEE a canvas-drawn viz from another "
                         "machine.")
    ap.add_argument("--at", action="append", default=None, metavar="X,Y",
                    help="with --shot: hover this fractional point of the viz "
                         "before shooting; repeatable, applied in order. A "
                         "Tableau hierarchy's +/- only paints on hover.")
    ap.add_argument("--click", action="store_true",
                    help="with --shot --at: CLICK each point instead of just "
                         "hovering, then shoot the result")
    ap.add_argument("--workbook", default=None, metavar="URL",
                    help="enumerate every VIEW in a workbook's /views page and "
                         "stop. One page load, so it is the cheap first step "
                         "when you don't yet know which view to open.")
    ap.add_argument("--only", action="append", default=None, metavar="SUBSTR",
                    help="restrict --dump to CANDIDATES containing SUBSTR "
                         "(case-insensitive); repeatable. Each sheet costs "
                         "5-10 min, so narrow it or blow the timeout.")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    buf = []

    def rec(msg=""):
        print(msg, flush=True)
        buf.append(str(msg))

    from urllib.parse import quote

    # Both of the report's sources by default — since 2026-08-13 the numbers come
    # from TWO views, not one (activations moved to ACTIVATIONRATES).
    urls = args.url or [T.VIEW_RATES, T.VIEW_ACTIVATIONS]

    def _url(week_sat=None) -> str:
        """Base view + optional team filter + optional pinned activation week."""
        parts = []
        if args.team:
            parts.append(f"{quote(TEAM_FIELD)}={quote(TEAM_VALUE)}")
        if week_sat:
            parts.append(f"{T.WEEK_FIELD}={week_sat}")
        parts.append(":iid=1")
        return f"{urls[0]}?" + "&".join(parts)

    rec(f"Carlos bonus source probe @ {dt.datetime.now().isoformat(timespec='seconds')}")
    rec(f"team filter: {TEAM_VALUE!r}" if args.team else "team filter: (none)")
    rec(f"week pinned to Sat: {args.week_sat or '(last cycle)'}")

    if args.cached:
        # The four files pull_carlos() writes every run. They are still whatever
        # the LAST SUCCESSFUL run downloaded, so after the source view died they
        # are the only surviving record of the deleted worksheets' shape.
        import time
        # Keyed by the DELETED worksheet name, not by T.SHEETS: SHEETS now names
        # the replacements, while these files are the last download the old ones
        # ever produced (2026-08-12). Both sets are listed so the two shapes can
        # be diffed side by side.
        names = {"CB-Owner Sales": "cb_owner_sales.csv",
                 "Captain Team Check (2)": "captain_team_check_2.csv",
                 "Captain Team Check (4)": "captain_team_check_4.csv",
                 "CB-Owner Metrics": "cb_owner_metrics.csv"}
        names.update({T.SHEETS["activations"]: "activation_office.csv",
                      T.SHEETS["rates"]: "churn_activation_tiers.csv",
                      T.SHEETS["nonpmt"]: "captains_non_pmt.csv"})
        for key, fn in names.items():
            p = Path(T.CACHE_DIR) / fn
            rec("")
            rec(f"=== {key!r}  ({fn}) ===")
            if not p.exists():
                rec("  MISSING — no cached copy on this machine")
                continue
            age_h = (time.time() - p.stat().st_mtime) / 3600.0
            rec(f"  downloaded {age_h:.1f}h ago ({p.stat().st_size} bytes)")
            try:
                rows = T._read(p)
            except Exception as e:  # noqa: BLE001
                rec(f"  !! unreadable: {type(e).__name__}: {str(e)[:120]}")
                continue
            if not rows:
                rec("  (empty)")
                continue
            rec(f"  {len(rows)} rows, {len(rows[0])} columns")
            for c, h in enumerate(rows[0]):
                rec(f"  COL [{c:>2}] {h!r}")
            rec("  first 15 data rows:")
            for r in rows[1:16]:
                rec("    " + " | ".join(str(c or "")[:26] for c in r[:10]))
        if not args.no_upload:
            try:
                _upload(buf)
                rec("")
                rec(f"findings -> {DIAG_TAB!r} tab")
            except Exception as e:  # noqa: BLE001
                print(f"diag upload failed: {e}", flush=True)
        return 0

    if args.shot:
        rec("")
        rec(f"### shot: {urls[0]}")
        shoot_view(urls[0], rec, at=tuple(args.at or ()), click=args.click)
        if not args.no_upload:
            try:
                _upload(buf)
                rec("")
                rec(f"findings -> {DIAG_TAB!r} tab")
            except Exception as e:      # noqa: BLE001 — never fail on upload
                rec(f"(upload failed: {type(e).__name__}: {str(e)[:120]})")
        return 0

    if args.workbook:
        rec("")
        rec(f"### workbook: {args.workbook}")
        views = list_workbook_views(args.workbook, rec)
        rec(f"  {len(views)} view link(s):")
        for name, href in views:
            rec(f"VIEW: {name}  ->  {href}")
        if not views:
            rec("  (none — the workbook page may not have rendered, or the "
                "account cannot see it)")
        if not args.no_upload:
            try:
                _upload(buf)
                rec("")
                rec(f"findings -> {DIAG_TAB!r} tab")
            except Exception as e:      # noqa: BLE001 — never fail on upload
                print(f"diag upload failed: {e}", flush=True)
        return 0

    names = []
    for u in urls:
        rec("")
        rec(f"### view: {u}")
        try:
            found = list_crosstab_sheets(u, verbose=False)
        except Exception as e:  # noqa: BLE001 — a dead view must not kill the run
            rec(f"  !! could not open: {type(e).__name__}: {str(e)[:160]}")
            continue
        rec(f"  dialog offers {len(found)} worksheet(s):")
        for n in found:
            rec(f"XTAB: {n}")
        hit = [w for w in T.SHEETS.values() if w in found]
        rec(f"  MATCHES the report's needs: {len(hit)}/{len(T.SHEETS)}"
            + (f" -> {hit}" if hit else ""))
        if u == urls[0]:
            names = found

    rec("")
    for key, want in sorted(T.SHEETS.items()):
        rec(f"NEED: {key:<8} {want!r} -> "
            f"{'PRESENT' if want in names else 'MISSING'} (on first url)")

    if args.dump:
        from automations.fiber_activations import pull as P
        from automations.shared.tableau_patchright import download_crosstab_patchright
        today = dt.date.today()
        scratch = Path(T.CACHE_DIR) / "probe"
        scratch.mkdir(parents=True, exist_ok=True)
        wanted = args.sheet or CANDIDATES
        if args.only:
            subs = [s.lower() for s in args.only]
            wanted = [c for c in CANDIDATES if any(s in c.lower() for s in subs)]
            rec("")
            rec(f"--only {args.only} -> dumping {len(wanted)}: {list(wanted)}")
        for i, sheet in enumerate(wanted):
            if sheet not in names:
                rec("")
                rec(f"=== {sheet!r}: NOT OFFERED by this view, skipping ===")
                continue
            rec("")
            rec(f"=== {sheet!r} ===")
            # The per-rep sales sheet is the only one that needs the week pinned;
            # the rate sheets degenerate if you pin it (see tableau_pull._rates_url).
            # An explicit --week-sat wins everywhere: the is_sales guess only
            # knows this report's own view, and we now probe others too.
            is_sales = "Sales By ICD" in sheet or "ICD Summary" in sheet
            if args.no_week:
                sat = None
            elif args.week_sat:
                sat = args.week_sat
            else:
                sat = P.cycle_saturday(today).isoformat() if is_sales else None
            url = _url(sat)
            rec(f"  url: {url}")
            out = scratch / f"probe_{i}.csv"
            try:
                download_crosstab_patchright(url, sheet, out, verbose=False)
                rows = T._read(out)
            except Exception as e:  # noqa: BLE001 — one bad sheet must not kill the probe
                rec(f"  !! download/parse failed: {type(e).__name__}: {str(e)[:160]}")
                for ln in traceback.format_exc().splitlines()[-4:]:
                    rec("    " + ln[:180])
                continue
            if not rows:
                rec("  (empty export)")
                continue
            rec(f"  {len(rows)} rows, {len(rows[0])} columns")
            for c, h in enumerate(rows[0]):
                rec(f"  COL [{c:>2}] {h!r}")
            rec(f"  first {args.rows} data rows:")
            for r in rows[1:1 + args.rows]:
                rec("    " + " | ".join(str(c or "")[:26] for c in r[:10]))
            # Does Carlos' team actually appear, and where?
            team_label = T._norm(TEAM_VALUE)
            hits = [(ri, r) for ri, r in enumerate(rows[1:], 1)
                    if any(T._norm(c) == team_label for c in r[:3])]
            rec(f"  rows whose first 3 cols contain {team_label!r}: {len(hits)}")
            for ri, r in hits[:6]:
                rec(f"    [row {ri}] " + " | ".join(str(c or "")[:26] for c in r[:10]))
            _fingerprint(rows, rec)

    if not args.no_upload:
        try:
            _upload(buf)
            rec("")
            rec(f"findings -> {DIAG_TAB!r} tab")
        except Exception as e:  # noqa: BLE001 — never fail the probe on upload
            print(f"diag upload failed: {e}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
