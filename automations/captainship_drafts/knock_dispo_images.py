"""Per-owner Weekly Knock Dispositions boards for the Sunday Captainship email.

Raf's Loom 2026-08-23: the Captainship Report email gains the Weekly Knock
Dispositions board — the SAME per-rep Mon–Sat board the Sunday Metrics threads
get (automations/weekly_knock_dispositions/) — once per OWNER in the
captainship. Nothing here re-derives board logic: pull / compute / render are
the wkd modules used as a library; this module only decides WHO and hands
email_build a list of (owner, png-or-None).

WHO comes from the captainship roster on the Org Sales Board — the Sheet
roster is truth. The captain's block is found by its "<NAME> CAPTAIN(SHIP)
TEAM" label via org_sales_board.captainship (never a hardcoded row), against
the SAME tab this report's §1 already screenshots
(captainship_drafts.sales_board._values — one cached read per process, so the
roster costs no extra Sheets quota). Board name cells carry field tags
("(Wk 2)" / "(NC)" / "(BO)"); board_read.clean_name strips the known ones, and
the ownerville / PSS side resolves spelling drift through the ICD alias list
(alias_to_canonical) rather than per-report patches.

Per-owner isolation mirrors weekly_knock_dispositions/run.py: ONE ownerville
session serves every owner (Raf is the MASTER login — the rhidalgo session IS
his office; everyone else is an impersonation entered and exited around their
pull), and one owner failing records errors["knock_dispo:<owner>"] and yields
(owner, None) — the email shows a pending note under that owner's sub-heading
while the rest still ship. One owner must never kill the section.

Needs a warm ownerville session (the login is Turnstile-gated, so this can't
run cold on a laptop) — runs on Lucy 1, like the Sunday board itself. The
owner-list extraction and cfg-row building are pure and offline-testable;
capture() only touches a browser once those are done.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.shared.report_week import week_ending

# Own Chrome profile — the shared .browser_profile is first-come-first-served
# and a Sunday-morning build overlaps other browser reports. Same escape hatch
# weekly_knock_dispositions/run.py and other_office_knocks use; login comes
# from the shared storage_state, so a fresh dir here needs no new seeding.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_captainship_wkd")

# TeleMapper campaign pin for the pulls (sticky-campaign guard): "3" = RES
# AT&T, right for Raf's fiber captainship — the only flavor wired today. If an
# NDS flavor ever joins SECTION_KINDS, its owners need "" here (no fiber
# campaign), same distinction weekly_knock_dispositions/offices.py draws.
CAMPAIGN_ID = "3"


def week_window(today: dt.date) -> Tuple[dt.date, dt.date, dt.date]:
    """(monday, saturday, we_sunday) — the completed Mon–Sat week for a run on
    `today`. Same math as weekly_knock_dispositions.run._week: the Sunday email
    build reports the week that just ended, and a Monday catch-up rerun still
    resolves to that same week, not the empty new one."""
    sunday = week_ending(today - dt.timedelta(days=1))
    return sunday - dt.timedelta(days=6), sunday - dt.timedelta(days=1), sunday


def _slug(name: str) -> str:
    """Filesystem-safe per-owner dir name (board.render's filename is fixed
    per week, so each owner renders into their OWN subdir)."""
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def owner_names(captain_key: str, grid: Optional[List[List[str]]] = None
                ) -> List[str]:
    """The owner names in `captain_key`'s captainship block on the Org Sales
    Board, in board order (leaderboard first, then any daily-only stragglers),
    field tags stripped, de-duped case-insensitively.

    `grid` is injectable for offline tests; None reads the live tab through
    sales_board's process cache. Lazy imports so importing THIS module stays
    light (config.py's _fiber_boxes rationale — a mid-refactor dependency must
    not take the whole drafts run down at import time)."""
    from automations.captainship_drafts import sales_board as sb
    from automations.org_sales_board import captainship as cap
    from automations.icd_sales_board.board_read import clean_name
    if grid is None:
        grid = sb._values()
    token = sb.CAPTAIN_TOKEN[captain_key]
    # discover_captainships reads every block title off the board; match ours
    # by the same captain token §1 anchors on (tolerant containment, like
    # sales_board._is_ps_header — "Raf's" and "RAF'S CAPTAINSHIP" both hit).
    title = next((t for t, _hint in cap.discover_captainships(grid)
                  if token in cap._cap_key(t).lower()), None)
    if title is None:
        raise RuntimeError(
            f"no captainship block for {captain_key!r} (token {token!r}) "
            "found on the Org Sales Board — the roster is the block's "
            "leaderboard, so without it there are no owners to board.")
    anchor = cap.find_captainship(grid, title)
    names: List[str] = []
    seen: set = set()
    # Leaderboard THEN daily: same people normally, but a rep present in only
    # one table still gets a board rather than silently dropping.
    for _row, raw in list(anchor.leaderboard) + list(anchor.daily):
        name, _tags = clean_name(raw)          # "Cody Cannon (Wk 2)" → "Cody Cannon"
        key = " ".join(name.lower().split())
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def owner_cfgs(names: List[str], aliases_raw: Dict[str, list]
               ) -> List[Tuple[str, dict]]:
    """[(display_name, pull cfg), …] — the cfg rows pull_office_week takes.

    display_name keeps the BOARD's spelling (that's what the email sub-heading
    and the image title show — the name the captainship knows the owner by);
    the cfg's "name" is the alias-resolved canonical, which is what the
    ownerville impersonation search and the PSS owner slice both match on.

    Raf is the one MASTER row (the login session IS his office — no
    impersonation); everyone else impersonates. Detected by canonical name
    against the wkd RAF row so the two reports can never disagree on who the
    master is. Pure — offline-testable."""
    from automations.focus_office_att.aliases import alias_to_canonical, _norm_name
    from automations.weekly_knock_dispositions.offices import RAF as _RAF
    out: List[Tuple[str, dict]] = []
    for display in names:
        try:
            canonical = alias_to_canonical(display, aliases_raw)
        except Exception:  # noqa: BLE001 — a broken alias sheet ≠ no boards
            canonical = display
        is_master = _norm_name(canonical) == _norm_name(_RAF["name"])
        out.append((display, {
            "name": canonical,
            "ov": "master" if is_master else "impersonate",
            "campaign_id": CAMPAIGN_ID,
            "pss_owner": canonical,
        }))
    return out


def capture(captain, today: dt.date, render_dir,
            *, logfn=print, errors: Optional[dict] = None
            ) -> List[Tuple[str, Optional[Path]]]:
    """One Weekly Knock Dispositions PNG per owner of `captain`'s captainship.

    Returns [(owner_display, png_path_or_None), …] in roster order — the
    bundle["knock_dispo"] shape email_build renders. A None path means that
    owner's board could not be built; the reason sits in
    errors["knock_dispo:<owner>"] and renders as that owner's pending note.
    A roster/session-level failure records errors["knock_dispo"] instead.
    Never raises for a single owner — mirror of the wkd runner's per-office
    try/except."""
    errors = {} if errors is None else errors
    monday, saturday, we_sunday = week_window(today)
    logfn(f"  knock dispo boards: {monday} → {saturday} ({captain.key})")

    try:
        names = owner_names(captain.key)
    except Exception as e:  # noqa: BLE001 — no roster = no section, not no draft
        logfn(f"  ⚠ knock dispo roster lookup failed: {type(e).__name__}: {e}")
        errors["knock_dispo"] = f"{type(e).__name__}: {e}"
        return []
    if not names:
        errors["knock_dispo"] = ("the captainship's Sales Board block has no "
                                 "owner rows")
        return []
    logfn(f"    {len(names)} owner(s): {', '.join(names)}")

    from automations.focus_office_att.aliases import load_aliases
    aliases_raw = load_aliases()
    try:
        aliases_map = dict(aliases_raw)
    except Exception:  # noqa: BLE001
        aliases_map = {}
    pairs = owner_cfgs(names, aliases_raw)

    # The org-wide rep-level PSS crosstab, ONCE for every owner (the download
    # helper dedupes same-day pulls when the cache env is set, but one call per
    # build is the contract either way). Failure = apps columns blank on every
    # board, each flagged INCOMPLETE in its sub-heading — fill-but-flag, never
    # a dead section.
    from automations.weekly_knock_dispositions import apps as A
    pss_path = None
    try:
        pss_path = A.download(we_sunday)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ PSS crosstab failed ({type(e).__name__}: {str(e)[:160]}) "
              "— apps columns blank, boards flagged INCOMPLETE")

    # §1's login-free Sales Board renderer holds a LIVE sync playwright in this
    # thread, and a second sync start in the same thread dies with "you are
    # using Playwright Sync API inside the asyncio loop" — the exact failure
    # that silently killed every §2 Tableau shot until _tableau_shots learned
    # to close first. Same medicine here, best-effort: costs one browser
    # relaunch for the next captain's §1, buys a session that can open at all.
    try:
        from automations.captainship_drafts import sheet_render
        sheet_render.close_renderer()
    except Exception:  # noqa: BLE001
        pass

    from automations.weekly_knock_dispositions import board as B
    from automations.weekly_knock_dispositions import pull as P
    from automations.shared.tableau_patchright import ownerville_session

    out: List[Tuple[str, Optional[Path]]] = []
    # Everything the combined summary needs, kept as pulled: (display,
    # ov_rows, apps, dispo_cols) per owner that produced a board.
    captured: List[tuple] = []
    out_root = Path(render_dir) / f"knock_dispo_{captain.key}"
    try:
        with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
            for display, cfg in pairs:
                try:
                    ov_rows, dispo_cols = P.pull_office_week(
                        page, cfg, aliases_raw, monday, saturday)
                    office_apps = (
                        A.rep_apps_for_owner(pss_path, cfg["pss_owner"],
                                             aliases_map)
                        if pss_path is not None else None)
                    if not ov_rows and not office_apps:
                        # Visible absence, never a blank board (standing rule):
                        # the email says so under this owner's name.
                        errors[f"knock_dispo:{display}"] = (
                            "no knock or sales data for this week")
                        out.append((display, None))
                        continue
                    gaps_only = B.is_gaps_only(ov_rows)
                    rows = B.compute_rows(ov_rows, office_apps, dispo_cols)
                    # office=display puts the owner's name in the image title —
                    # many owners share one email, so every board must say
                    # whose it is (unlike the Metrics-thread post, where the
                    # channel already does).
                    png = B.render(display, monday, saturday, rows,
                                   out_root / _slug(display), dispo_cols,
                                   gaps_only=gaps_only, n_totals=1)
                    # INCOMPLETE flag rides the display name so it lands in
                    # the sub-heading next to the board it qualifies.
                    label = (display if pss_path is not None
                             else f"{display} — ⚠ INCOMPLETE: apps unavailable")
                    out.append((label, png))
                    captured.append((display, ov_rows, office_apps,
                                     dispo_cols))
                    logfn(f"    ✓ {display}: {len(ov_rows)} rep(s) → {png.name}")
                except Exception as e:  # noqa: BLE001 — one owner ≠ the section
                    logfn(f"    ✗ {display}: {type(e).__name__}: "
                          f"{str(e)[:200]}")
                    errors[f"knock_dispo:{display}"] = (
                        f"{type(e).__name__}: {str(e)[:200]}")
                    out.append((display, None))
    except Exception as e:  # noqa: BLE001 — the session itself never opened
        logfn(f"  ⚠ ownerville session failed: {type(e).__name__}: "
              f"{str(e)[:200]}")
        errors["knock_dispo"] = (f"ownerville session failed: "
                                 f"{type(e).__name__}: {str(e)[:200]}")
        done = {d for d, _ in out}
        for display, _cfg in pairs:
            if display not in done:
                errors.setdefault(f"knock_dispo:{display}",
                                  "ownerville session failed before this "
                                  "owner's pull")
                out.append((display, None))

    # Raf's email reply 2026-08-23 ("1 report of each ICD's averages so the
    # captain can look at one report for his whole captainship") + Megan
    # ("put this combined overall view before the individual ones"): ONE
    # summary board FIRST — each owner as a single row of their week's
    # totals/averages (the same totals-row math their own board's bottom row
    # shows), with a CAPTAINSHIP TOTALS row under them. Built from the data
    # already pulled above — zero extra pulls; an owner whose pull failed has
    # no row here (their pending note below says why).
    if captured:
        try:
            from automations.weekly_knock_dispositions.board import (
                THEME_PLUM, headers_for, totals_row)
            from automations.total_knocks import render as knocks_render
            common_cols = next((c for _d, _r, _a, c in captured if c), [])
            sum_rows = [totals_row(r, a, common_cols, label=d)
                        for d, r, a, _c in captured]
            all_rows = [rec for _d, r, _a, _c in captured for rec in r]
            merged_apps: dict = {}
            has_apps = False
            for _d, _r, a, _c in captured:
                if a:
                    has_apps = True
                    merged_apps.update(a)
            sum_rows.append(totals_row(
                all_rows, merged_apps if has_apps else None, common_cols,
                label="CAPTAINSHIP TOTALS"))
            span = (f"{monday.strftime('%b')} {monday.day} – "
                    f"{saturday.strftime('%b')} {saturday.day}, "
                    f"{saturday.year}")
            png = knocks_render._draw(
                headers_for(common_cols), sum_rows,
                f"CAPTAINSHIP SUMMARY — {span}", THEME_PLUM,
                out_root / "summary"
                / f"knock_dispo_summary_{saturday.isoformat()}.png",
                name_col=0, wrap_headers=True, highlight_last_row=1)
            out.insert(0, ("Captainship Summary", png))
            logfn(f"    ✓ captainship summary: {len(captured)} owner row(s)")
        except Exception as e:  # noqa: BLE001 — summary ≠ the section
            errors["knock_dispo:Captainship Summary"] = (
                f"{type(e).__name__}: {str(e)[:200]}")
            out.insert(0, ("Captainship Summary", None))
            logfn(f"    ✗ captainship summary: {type(e).__name__}: "
                  f"{str(e)[:160]}")
    return out
