"""Per-owner knock boards for the Captainship Report emails — BOTH sections:

  * knock_dispo   (Sun+Mon)  — the Weekly Knock Dispositions board per owner,
                               plus a captainship summary board first.
  * daily_knocks  (every day) — YESTERDAY's combined Total Knocks board per
                               owner (the amber board their metrics threads
                               get daily), plus a daily summary board first
                               with Chan Park's teal comparison row.

Raf's Loom 2026-08-23 brought the weekly section: the SAME per-rep Mon–Sat
board the Sunday Metrics threads get (automations/weekly_knock_dispositions/)
— once per OWNER in the captainship. His Slack ask the same evening added the
daily section ("add the daily knocks to everyones captainship emails … and
have Chan's comparison in there") and gated the weekly one to Sun+Mon
(config.SECTION_DAYS — Monday re-shows Sunday's completed week for
one-on-ones). Nothing here re-derives board logic: pull / compute / render are
the wkd + total_knocks + rashad_metrics modules used as libraries; this module
only decides WHO and hands email_build lists of (title, png-or-None).

WHO comes from the captainship roster on the Org Sales Board — the Sheet
roster is truth. The captain's block is found by its "<NAME> CAPTAIN(SHIP)
TEAM" label via org_sales_board.captainship (never a hardcoded row), against
the SAME tab this report's §1 already screenshots
(captainship_drafts.sales_board._values — one cached read per process, so the
roster costs no extra Sheets quota). Board name cells carry field tags
("(Wk 2)" / "(NC)" / "(BO)"); board_read.clean_name strips the known ones, and
the ownerville / PSS side resolves spelling drift through the ICD alias list
(alias_to_canonical) rather than per-report patches.

SESSION ECONOMY (Raf's captains are 6 of the 12 drafts since 2026-08-23):
capture_sections() does ONE roster lookup and opens ONE ownerville session per
captain, and both sections' pulls run inside that session's owner loop — the
weekly pull only even happens on Sun/Mon. Chan Park's comparison data is
pulled AT MOST ONCE per build: when he's an owner of the captain being built
(his own / Raf's captainship) his loop rows are reused, and either way the
rows land in a per-process cache the other captains' summaries read instead
of re-impersonating him.

The WEEKLY pull goes one step further, through shared/knock_week_cache.py: a
completed Mon–Sat week is frozen, so each (office, week) is pulled from
ownerville at most ONCE across every report and every day. That kills the two
duplications that made this build 1h40m+ on 2026-08-24 — the overlap with
Sunday's weekly_knock_dispositions run (order 36.5, same offices, same week),
and Monday's full re-pull of a week Sunday already fetched. The DAILY pull is
deliberately NOT cached: one day, cheap, and it changes intraday.

Per-owner isolation mirrors weekly_knock_dispositions/run.py: Raf is the
MASTER login (the rhidalgo session IS his office; everyone else is an
impersonation entered and exited around their pull), and one owner failing
records errors["<kind>:<owner>"] and yields (owner, None) — the email shows a
pending note under that owner's sub-heading while the rest still ship. One
owner must never kill a section.

Needs a warm ownerville session (the login is Turnstile-gated, so this can't
run cold on a laptop) — runs on Lucy 1, like the Sunday board itself. The
owner-list extraction, cfg-row building and summary aggregation are pure and
offline-testable; capture_sections() only touches a browser once those are
done.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.shared.report_week import week_ending
# The prefix that tells email_build "the source answered, it had nothing" —
# a grey 'no data available' note instead of the yellow capture-failed one.
from automations.captainship_drafts.email_build import NO_DATA_MARK

# Own Chrome profile — the shared .browser_profile is first-come-first-served
# and a Sunday-morning build overlaps other browser reports. Same escape hatch
# weekly_knock_dispositions/run.py and other_office_knocks use; login comes
# from the shared storage_state, so a fresh dir here needs no new seeding.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_captainship_wkd")

# TeleMapper campaign pin for the pulls (sticky-campaign guard): "3" = RES
# AT&T, right for every captain wired today (rafael + the five fiber captains
# all knock RES AT&T). If a b2b/nds flavor ever joins SECTION_KINDS, its
# owners need "" here (no fiber campaign), same distinction
# weekly_knock_dispositions/offices.py draws.
CAMPAIGN_ID = "3"

# The daily summary board's columns, left→right (Raf's Slack + Megan
# 2026-08-23: "a daily overall and then each ICD broken out below it").
# Display labels only — the data keys stay total_knocks.pull's canonical
# SHEET_COLUMNS names.
DAILY_SUMMARY_HEADERS = [
    "ICD", "Total Leads Knocked", "Total Knocks", "Total Talk To",
    "Avg First Knock", "Avg Last Knock", "Gaps", "Total Gaps",
]

# Chan Park's yesterday rows, cached PER PROCESS keyed by the target date's
# ISO string. Six captains build in one run.py process; Chan's teal
# comparison row rides every daily summary, and this cache is what keeps
# that at ONE ownerville pull per build instead of one per captain. Failures
# are deliberately NOT cached, so a later captain's build retries.
_CHAN_DAILY_CACHE: Dict[str, list] = {}


# An owner on the captainship roster who has NO ownerville office at all —
# not a name-spelling drift an alias could fix (Megan checked Office Access
# on Raf's login for Michael Murphy, 2026-08-24: absent under his name, his
# nickname and his company). There is nothing to pull for that person, so
# the section must say ACCESS GAP, not show what reads as a failed run —
# the standing rule that a review email names the owners we can't scrape.
# Matched on the impersonation failure text rather than a hardcoded name
# list, so the next owner in this position is covered without a patch.
_NO_OFFICE_MARKERS = ("not found in ownerville", "couldn't impersonate",
                      "couldnt impersonate")


def _owner_error_note(exc) -> str:
    """The errors[] note for a failed owner pull — an ACCESS GAP reads as
    one, anything else keeps its exception text for debugging."""
    text = f"{type(exc).__name__}: {str(exc)[:200]}"
    if any(m in str(exc).lower() for m in _NO_OFFICE_MARKERS):
        return ("no ownerville office for this name — access gap, not a run "
                "failure: nothing can be pulled until the account exists")
    return text


def week_window(today: dt.date) -> Tuple[dt.date, dt.date, dt.date]:
    """(monday, saturday, we_sunday) — the completed Mon–Sat week for a run on
    `today`. Same math as weekly_knock_dispositions.run._week: the Sunday email
    build reports the week that just ended, and a Monday catch-up rerun still
    resolves to that same week, not the empty new one. This is also what makes
    the SECTION_DAYS Sun+Mon gate coherent: Monday's boards re-show Sunday's
    week (Raf: "Monday should re duplicate sundays post")."""
    sunday = week_ending(today - dt.timedelta(days=1))
    return sunday - dt.timedelta(days=6), sunday - dt.timedelta(days=1), sunday


def daily_target(today: dt.date) -> dt.date:
    """The day the daily_knocks section covers: YESTERDAY — the same today-1
    anchor every other section of this draft uses (email_build.reported_date),
    so a --date override moves the whole draft together. On the scheduled
    Lucy 1 run this equals yesterday-Central (the machine runs on Central
    time), matching the daily metrics-thread boards."""
    return today - dt.timedelta(days=1)


def _slug(name: str) -> str:
    """Filesystem-safe per-owner dir name (each board render's filename is
    fixed per date, so each owner renders into their OWN subdir)."""
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


# ---------------------------------------------------------------------------
# daily_knocks — YESTERDAY's boards (Raf's Slack ask, 2026-08-23 evening)
# ---------------------------------------------------------------------------

def _daily_rows_for_owner(page, cfg: dict, aliases_raw, target: dt.date
                          ) -> list:
    """One owner's yesterday knock rows (records keyed by total_knocks.pull
    SHEET_COLUMNS), on the already-open ownerville page.

    Impersonated owners ride rashad_metrics.knocks_pull.pull_office_on_page —
    the exact scrape the daily metrics-thread boards use (impersonate, pin
    campaign, Disposition + Time Tracker merged by badge id, exit
    impersonation). That helper impersonates UNCONDITIONALLY, so the MASTER
    (Raf — the rhidalgo login IS his office) can't go through it: for him
    this replicates total_knocks.pull.pull_disposition_day's body inline on
    the shared page — capture rqst, pin the campaign (the sticky-campaign
    guard applies to the master session too), _navigate, _header_index,
    _scrape_rows, _scrape_time_tracker, merged by badge id — the same
    master-vs-impersonate routing owner_cfgs decided for the weekly pull."""
    from automations.rashad_metrics import knocks_pull as KP
    from automations.total_knocks import pull as knocks
    if cfg.get("ov") == "master":
        mdy = target.strftime("%m/%d/%Y")
        rqst = knocks._capture_rqst(page)
        if not rqst:
            raise RuntimeError("Couldn't capture ownerville rqst token from "
                               f"{page.url!r} for the master office.")
        KP._pin_campaign(page, rqst)
        knocks._navigate(page, rqst, mdy)
        idx = knocks._header_index(page)
        rows = knocks._scrape_rows(page, idx)
        tt = knocks._scrape_time_tracker(page, rqst, mdy)
        for rec in rows:
            rid = str(rec.get(knocks.COL_ID, "")).strip()
            if rid in tt:
                rec.update(tt[rid])
        return rows
    _t, rows = KP.pull_office_on_page(page, cfg["name"], aliases_raw, target)
    return rows


def daily_summary_row(label: str, rows: list) -> List[str]:
    """One daily-summary board row aggregating `rows` (one owner's reps,
    records keyed by total_knocks.pull SHEET_COLUMNS): the count columns SUM;
    First/Last Knock are the AVERAGE of the reps' times (the wkd board's
    _avg_knock — reps with a parsable time only); Gaps sums the gap counts;
    Total Gaps sums the minutes and formats 'Xh Ym' like the daily board
    (total_knocks.render._fmt_hm). Pure — offline-testable."""
    from automations.weekly_knock_dispositions.board import _avg_knock
    from automations.total_knocks import pull as knocks
    from automations.total_knocks.render import _fmt_hm

    def _i(rec: dict, col: str) -> int:
        v = rec.get(col)
        return v if isinstance(v, int) else knocks._to_int(str(v or ""))

    return [
        label,
        str(sum(_i(r, knocks.COL_TOTAL_LEADS_KNOCKED) for r in rows)),
        str(sum(_i(r, knocks.COL_TOTAL_KNOCKS) for r in rows)),
        str(sum(_i(r, knocks.COL_TOTAL_TALK_TO) for r in rows)),
        _avg_knock(rows, knocks.COL_FIRST_KNOCK),
        _avg_knock(rows, knocks.COL_LAST_KNOCK),
        str(sum(_i(r, knocks.COL_GAPS) for r in rows)),
        _fmt_hm(str(sum(_i(r, knocks.COL_TOTAL_GAPS) for r in rows))),
    ]


def daily_summary_table(captured: list, chan_rows: Optional[list] = None
                        ) -> Tuple[List[List[str]], list]:
    """The daily summary board's rows: one row per ICD of THIS captainship in
    roster order, then the trailing highlight block — a teal CHAN PARK
    comparison row (Raf: "have Chan's comparison in there"; teal =
    weekly_knock_dispositions' COMPARE_ROW_BG, so a guest row reads the same
    everywhere) and the plum CAPTAINSHIP TOTALS row.

    `captured` is [(display, cfg, rows), …] per owner that produced daily
    rows. `chan_rows` is Chan Park's rep rows — when None, they're looked up
    IN `captured` (his own / Raf's captainship, where he is an owner); a
    captain whose roster doesn't carry him passes the extra data-only pull
    in. Either way the teal row just re-aggregates his reps, and TOTALS sums
    only the captainship's own owners (a data-only Chan is not one of them).
    No Chan data at all = no teal row, never a crash.

    Returns (table_rows, trailing_bgs) — trailing_bgs colors the trailing
    highlight block for _draw's total_row_bgs, teal row included, so its
    length is also the highlight_last_row count. Pure — offline-testable."""
    from automations.weekly_knock_dispositions.board import (
        COMPARE_ROW_BG, THEME_PLUM)
    from automations.weekly_knock_dispositions.offices import CHAN as _CHAN
    from automations.focus_office_att.aliases import _norm_name
    body = [daily_summary_row(d, r) for d, _c, r in captured]
    if chan_rows is None:
        chan_norm = _norm_name(_CHAN["name"])
        chan_rows = next((r for _d, c, r in captured
                          if _norm_name(c.get("name", "")) == chan_norm), None)
    tail: List[List[str]] = []
    bgs: list = []
    if chan_rows:
        tail.append(daily_summary_row("CHAN PARK", chan_rows))
        bgs.append(COMPARE_ROW_BG)
    all_rows = [rec for _d, _c, r in captured for rec in r]
    tail.append(daily_summary_row("CAPTAINSHIP TOTALS", all_rows))
    bgs.append(THEME_PLUM["header_bg"])
    return body + tail, bgs


def render_daily_summary(captured: list, target: dt.date, out_dir,
                         chan_rows: Optional[list] = None) -> Path:
    """Draw the daily summary board PNG — plum theme like the weekly
    captainship summary, so the two summary boards read as siblings above
    their amber/plum per-owner boards. The trailing block (teal Chan row +
    plum TOTALS) highlights via total_row_bgs; note _draw only paints
    total_row_bgs INSIDE the highlighted trailing block, so
    highlight_last_row must count the teal row too — not just the last row."""
    from automations.weekly_knock_dispositions.board import THEME_PLUM
    from automations.total_knocks import render as knocks_render
    table, bgs = daily_summary_table(captured, chan_rows)
    date_s = f"{target.strftime('%b')} {target.day}, {target.year}"
    return knocks_render._draw(
        list(DAILY_SUMMARY_HEADERS), table,
        f"DAILY KNOCKS SUMMARY — {date_s}", THEME_PLUM,
        Path(out_dir) / f"daily_knocks_summary_{target.isoformat()}.png",
        name_col=0, wrap_headers=True,
        highlight_last_row=len(bgs), total_row_bgs=bgs)


def _chan_daily_rows(page, captured_daily: list, aliases_raw,
                     target: dt.date, *, logfn=print) -> Optional[list]:
    """Chan Park's yesterday rows for the summary's teal comparison row —
    cheapest source first: (1) this captain's own loop, when Chan is one of
    its owners; (2) the per-process cache, filled by an earlier captain in
    the same build; (3) ONE extra data-only impersonated pull inside the
    already-open session. (1) and (3) both fill the cache, which is what
    holds the whole build to at most one Chan pull. None = unavailable — the
    summary simply omits the teal row (logged, never fatal, never cached so
    the next captain retries)."""
    from automations.focus_office_att.aliases import (
        _norm_name, alias_to_canonical)
    from automations.weekly_knock_dispositions.offices import CHAN as _CHAN
    key = target.isoformat()
    chan_norm = _norm_name(_CHAN["name"])
    for _d, cfg, rows in captured_daily:
        if _norm_name(cfg.get("name", "")) == chan_norm:
            _CHAN_DAILY_CACHE[key] = rows
            return rows
    if key in _CHAN_DAILY_CACHE:
        return _CHAN_DAILY_CACHE[key]
    try:
        from automations.rashad_metrics import knocks_pull as KP
        try:
            canonical = alias_to_canonical(_CHAN["name"], aliases_raw)
        except Exception:  # noqa: BLE001 — a broken alias sheet ≠ no row
            canonical = _CHAN["name"]
        logfn(f"    Chan comparison: extra data-only pull ({canonical})")
        _t, rows = KP.pull_office_on_page(page, canonical, aliases_raw,
                                          target)
        _CHAN_DAILY_CACHE[key] = rows
        return rows
    except Exception as e:  # noqa: BLE001 — a nicety, never the section
        logfn(f"    ⚠ Chan comparison pull failed ({type(e).__name__}: "
              f"{str(e)[:120]}) — daily summary omits the teal row")
        return None


# ---------------------------------------------------------------------------
# capture — both sections, one roster lookup, one ownerville session
# ---------------------------------------------------------------------------

class _ReusedDaily(Exception):
    """This owner's daily board came off disk — skip the pull, keep the loop."""


def _owner_png(root: Path, display: str, stem: str, stamp: dt.date) -> Path:
    """Where one owner's board for `stamp` lands — the SAME path the render
    helpers write to, derived once so reuse and capture can never disagree."""
    return Path(root) / _slug(display) / f"{stem}_{stamp.isoformat()}.png"


def _owner_rows_file(png: Path) -> Path:
    """The pull's rows, parked next to the board they drew.

    The PNG alone is enough to re-show one owner's board, but NOT enough to
    rebuild the captainship SUMMARY, which aggregates every owner's rows. Kept
    as its own file so an older run's PNG (no sidecar) still gets reused — the
    summary just says so instead of quietly dropping that ICD."""
    return png.parent / f"rows_{png.stem}.json"


def _read_rows(png: Path):
    try:
        f = _owner_rows_file(png)
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except Exception:  # noqa: BLE001 — a bad sidecar = pull-quality summary
        return None


def _write_rows(png: Path, payload) -> None:
    try:
        _owner_rows_file(png).write_text(json.dumps(payload), encoding="utf-8")
    except Exception:  # noqa: BLE001 — best effort, never fails a capture
        pass


def _manifest_path(render_dir, captain_key: str, target: dt.date,
                   saturday: dt.date) -> Path:
    """One file per captain per DAY — the daily target and the week's Saturday
    both ride the name, so yesterday's manifest can never satisfy today's run
    and a Monday's can never satisfy a Tuesday's."""
    return (Path(render_dir) / f"knocks_manifest_{captain_key}_"
            f"{target.isoformat()}_{saturday.isoformat()}.json")


def _save_manifest(render_dir, captain_key: str, target: dt.date,
                   saturday: dt.date, wanted, out: dict, errors: dict,
                   logfn=print) -> None:
    """Record what this pull produced so a later build today can skip it.

    Best-effort: a manifest that fails to write costs a re-pull, never a
    wrong board."""
    try:
        payload = {
            "kinds": sorted(wanted),
            "items": {k: [[lab, (str(p) if p else None)]
                          for lab, p in out.get(k, [])] for k in wanted},
            "errors": {k: v for k, v in errors.items()
                       if k.split(":", 1)[0] in wanted},
        }
        p = _manifest_path(render_dir, captain_key, target, saturday)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logfn(f"    ⚠ knocks manifest not saved: {type(e).__name__}: {e}")


def _load_manifest(render_dir, captain_key: str, target: dt.date,
                   saturday: dt.date, wanted):
    """Today's capture for this captain, or None to pull it fresh.

    Refuses the manifest unless it covers EVERY kind this run wants (a
    daily-only Tuesday capture must not satisfy Monday's weekly section) and
    every PNG it names is still on disk — /tmp is swept, and half a section is
    worse than a slow one."""
    p = _manifest_path(render_dir, captain_key, target, saturday)
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if not set(wanted).issubset(set(data.get("kinds") or [])):
            return None
        items = {}
        for kind in wanted:
            pairs = []
            for lab, path in data["items"][kind]:
                if path is None:
                    pairs.append((lab, None))
                    continue
                png = Path(path)
                if not png.exists() or png.stat().st_size == 0:
                    return None
                pairs.append((lab, png))
            items[kind] = pairs
        return {"items": items, "errors": data.get("errors") or {}}
    except Exception:  # noqa: BLE001 — an unreadable manifest = pull fresh
        return None


def capture_sections(captain, today: dt.date, render_dir, *,
                     want_daily: bool = True, want_weekly: bool = True,
                     logfn=print, errors: Optional[dict] = None) -> dict:
    """Both knock sections' images for `captain`, sharing ONE roster lookup
    and ONE ownerville session (run.py passes want_* from sections_on(today),
    so the weekly work simply doesn't happen Tue–Sat).

    Returns {"daily_knocks": […], "knock_dispo": […]} — each the
    [(title, png_path_or_None), …] shape email_build renders, summary board
    first, then the owners in roster order (empty when not wanted). A None
    path means that board could not be built; the reason sits in
    errors["<kind>:<title>"] and renders as that item's pending note. A
    roster/session-level failure records errors["<kind>"] for each wanted
    kind instead. Never raises for a single owner — mirror of the wkd
    runner's per-office try/except."""
    errors = {} if errors is None else errors
    out = {"daily_knocks": [], "knock_dispo": []}
    if not (want_daily or want_weekly):
        return out
    wanted = [k for k, w in (("daily_knocks", want_daily),
                             ("knock_dispo", want_weekly)) if w]

    monday, saturday, we_sunday = week_window(today)
    target = daily_target(today)
    if want_daily:
        logfn(f"  daily knocks boards: {target} ({captain.key})")
    if want_weekly:
        logfn(f"  knock dispo boards: {monday} → {saturday} ({captain.key})")

    try:
        names = owner_names(captain.key)
    except Exception as e:  # noqa: BLE001 — no roster = no section, not no draft
        logfn(f"  ⚠ captainship roster lookup failed: {type(e).__name__}: {e}")
        for k in wanted:
            errors[k] = f"{type(e).__name__}: {e}"
        return out
    if not names:
        for k in wanted:
            errors[k] = ("the captainship's Sales Board block has no "
                         "owner rows")
        return out
    logfn(f"    {len(names)} owner(s): {', '.join(names)}")

    # Already captured today? Then this whole function is a no-op. THE reason
    # this exists (Eve 2026-08-24): the pull is ~2h — one ownerville session,
    # every ICD impersonated, scraped and un-impersonated in single file,
    # because impersonation is per-account server state and cannot be
    # parallelised. On 2026-08-24 that 2h sat between Eve and every other job
    # on the mini, and the day's second build paid it all over again for
    # images that were already on disk.
    #
    # The manifest is what makes reuse honest: labels (INCOMPLETE suffix and
    # all) and the errors map come back exactly as the pull left them, so a
    # reused build renders the same notes as the original — never a blank
    # board wearing a fresh face.
    cached = _load_manifest(render_dir, captain.key, target, saturday, wanted)
    if cached is not None:
        for kind in wanted:
            out[kind] = cached["items"][kind]
        errors.update(cached["errors"])
        logfn(f"    ✓ reusing today's capture from {render_dir} "
              f"(no ownerville session needed)")
        return out

    from automations.focus_office_att.aliases import load_aliases
    aliases_raw = load_aliases()
    try:
        aliases_map = dict(aliases_raw)
    except Exception:  # noqa: BLE001
        aliases_map = {}
    pairs = owner_cfgs(names, aliases_raw)

    # The org-wide rep-level PSS crosstab, ONCE for every owner (the download
    # helper dedupes same-day pulls when the cache env is set, but one call per
    # build is the contract either way). WEEKLY-ONLY — the daily board carries
    # no apps columns. Failure = apps columns blank on every weekly board,
    # each flagged INCOMPLETE in its sub-heading — fill-but-flag, never a
    # dead section.
    pss_path = None
    if want_weekly:
        from automations.weekly_knock_dispositions import apps as A
        try:
            pss_path = A.download(we_sunday)
        except Exception as e:  # noqa: BLE001
            logfn(f"  ⚠ PSS crosstab failed ({type(e).__name__}: "
                  f"{str(e)[:160]}) — apps columns blank, weekly boards "
                  "flagged INCOMPLETE")

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
    from automations.total_knocks import render as knocks_render
    from automations.shared import knock_week_cache as KWC
    from automations.shared.tableau_patchright import ownerville_session

    # SESSION ECONOMY, honestly bounded: the week cache can make every weekly
    # pull free, but it can NOT make the session unnecessary here. want_daily
    # is True on both days this section runs (run.py's sections_on gates the
    # weekly section to Sun+Mon; the daily one runs every day), and the daily
    # knocks pulls are deliberately un-cached — they're one day, cheap, and
    # change intraday. So on every real build there is daily work for the
    # session regardless, and the browser opens either way. Deferring the
    # session open for the weekly-only `capture()` entry point would mean
    # restructuring the loop that owns the per-owner error isolation, for a
    # path nothing schedules — not worth the risk. Left as-is on purpose.

    out_daily: List[Tuple[str, Optional[Path]]] = out["daily_knocks"]
    out_weekly: List[Tuple[str, Optional[Path]]] = out["knock_dispo"]
    # Owners already answered per kind (board OR pending) — what the
    # session-failure sweep below checks, kept separate from the label in
    # `out` because a weekly label can carry an INCOMPLETE suffix.
    done_daily: set = set()
    done_weekly: set = set()
    # Everything each summary needs, kept as pulled.
    captured_daily: List[tuple] = []    # (display, cfg, rows)
    captured_weekly: List[tuple] = []   # (display, ov_rows, apps, dispo_cols)
    chan_rows: Optional[list] = None
    # Set when a board was reused from disk WITHOUT its rows sidecar (drawn
    # before the sidecar existed). That owner's own board is intact; only the
    # captainship SUMMARY loses their line, and it says so rather than showing
    # a total that silently misses an office.
    daily_partial = False
    weekly_partial = False
    daily_root = Path(render_dir) / f"daily_knocks_{captain.key}"
    weekly_root = Path(render_dir) / f"knock_dispo_{captain.key}"
    try:
        with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
            for display, cfg in pairs:
                if want_daily:
                    try:
                        # ALREADY DRAWN TODAY? Reuse it. Per OWNER, not per
                        # captain: on 2026-08-24 a rebuild had to re-pull all
                        # ~50 owner-slots to fix the handful that had failed,
                        # and the run that succeeded for the other forty had
                        # left their boards right here on disk.
                        done_png = _owner_png(daily_root, display,
                                              "total_knocks", target)
                        if done_png.exists() and done_png.stat().st_size:
                            out_daily.append((display, done_png))
                            prev = _read_rows(done_png)
                            if prev is not None:
                                captured_daily.append((display, cfg, prev))
                            else:
                                daily_partial = True
                            logfn(f"    · daily {display}: reusing "
                                  f"{done_png.name}")
                            done_daily.add(display)
                            if not want_weekly:
                                continue
                            raise _ReusedDaily
                        rows = _daily_rows_for_owner(page, cfg, aliases_raw,
                                                     target)
                        if not rows:
                            # Visible absence, never a blank board (standing
                            # rule): the email says so under this owner.
                            errors[f"daily_knocks:{display}"] = (
                                NO_DATA_MARK + "no knocks recorded yesterday")
                            out_daily.append((display, None))
                        else:
                            png = knocks_render.render_total_knocks(
                                target, rows=rows,
                                out_dir=daily_root / _slug(display),
                                title_suffix=display)
                            out_daily.append((display, png))
                            captured_daily.append((display, cfg, rows))
                            _write_rows(png, rows)
                            logfn(f"    ✓ daily {display}: {len(rows)} "
                                  f"rep(s) → {png.name}")
                    except _ReusedDaily:
                        pass          # reused above; the weekly half follows
                    except Exception as e:  # noqa: BLE001 — one owner ≠ section
                        logfn(f"    ✗ daily {display}: {type(e).__name__}: "
                              f"{str(e)[:200]}")
                        errors[f"daily_knocks:{display}"] = _owner_error_note(e)
                        out_daily.append((display, None))
                    done_daily.add(display)
                if want_weekly:
                    try:
                        # Board already drawn today? Same reuse as the daily
                        # half — and it saves more, because a weekly pull is
                        # ~12 ownerville round-trips against the daily's one.
                        done_png = _owner_png(weekly_root, display,
                                              "weekly_knock_dispositions",
                                              saturday)
                        if done_png.exists() and done_png.stat().st_size:
                            out_weekly.append((display, done_png))
                            logfn(f"    · weekly {display}: reusing "
                                  f"{done_png.name}")
                            prev = _read_rows(done_png)
                            if prev is not None:
                                captured_weekly.append(
                                    (display, prev.get("ov_rows") or [],
                                     prev.get("apps"),
                                     prev.get("dispo_cols") or []))
                            else:
                                weekly_partial = True
                            done_weekly.add(display)
                            continue
                        # Shared week cache (shared/knock_week_cache.py): the
                        # completed Mon–Sat week is frozen, and Sunday's
                        # weekly_knock_dispositions run + MONDAY's re-build of
                        # this very section ask for the exact same window. A
                        # hit skips the ~12 ownerville round-trips entirely
                        # and is NOT a failure — it falls through to the same
                        # render below with the same (ov_rows, dispo_cols)
                        # shape. A miss just pulls, exactly as before, and the
                        # per-owner try/except around all of it is untouched.
                        # (An EMPTY pull is never cached — see that module:
                        # an owner with no rows is usually a failed
                        # impersonation, and must be retried, not frozen in.)
                        hit = KWC.get(cfg["name"], saturday,
                                      aliases=aliases_raw)
                        if hit is not None:
                            ov_rows, dispo_cols = hit
                            logfn(f"    ↺ weekly {display}: from week cache")
                        else:
                            ov_rows, dispo_cols = P.pull_office_week(
                                page, cfg, aliases_raw, monday, saturday)
                            KWC.put(cfg["name"], saturday, ov_rows,
                                    dispo_cols, aliases=aliases_raw)
                        office_apps = (
                            A.rep_apps_for_owner(pss_path, cfg["pss_owner"],
                                                 aliases_map)
                            if pss_path is not None else None)
                        if not ov_rows and not office_apps:
                            # Visible absence, never a blank board (standing
                            # rule): the email says so under this owner.
                            errors[f"knock_dispo:{display}"] = (
                                NO_DATA_MARK
                                + "no knocks or sales recorded this week")
                            out_weekly.append((display, None))
                            done_weekly.add(display)
                            continue
                        gaps_only = B.is_gaps_only(ov_rows)
                        rows = B.compute_rows(ov_rows, office_apps, dispo_cols)
                        # office=display puts the owner's name in the image
                        # title — many owners share one email, so every board
                        # must say whose it is (unlike the Metrics-thread
                        # post, where the channel already does).
                        png = B.render(display, monday, saturday, rows,
                                       weekly_root / _slug(display),
                                       dispo_cols, gaps_only=gaps_only,
                                       n_totals=1)
                        # INCOMPLETE flag rides the display name so it lands
                        # in the sub-heading next to the board it qualifies.
                        label = (display if pss_path is not None
                                 else f"{display} — ⚠ INCOMPLETE: apps "
                                      "unavailable")
                        out_weekly.append((label, png))
                        captured_weekly.append((display, ov_rows, office_apps,
                                                dispo_cols))
                        _write_rows(png, {"ov_rows": ov_rows,
                                          "apps": office_apps,
                                          "dispo_cols": dispo_cols})
                        logfn(f"    ✓ weekly {display}: {len(ov_rows)} "
                              f"rep(s) → {png.name}")
                    except Exception as e:  # noqa: BLE001 — one owner ≠ section
                        logfn(f"    ✗ weekly {display}: {type(e).__name__}: "
                              f"{str(e)[:200]}")
                        errors[f"knock_dispo:{display}"] = _owner_error_note(e)
                        out_weekly.append((display, None))
                    done_weekly.add(display)
            # Chan's comparison rows for the daily summary — while the
            # session is still open, so a captainship that doesn't roster
            # him can pull him data-only (once per build, see the cache).
            if want_daily and captured_daily:
                chan_rows = _chan_daily_rows(page, captured_daily,
                                             aliases_raw, target, logfn=logfn)
    except Exception as e:  # noqa: BLE001 — the session itself never opened
        logfn(f"  ⚠ ownerville session failed: {type(e).__name__}: "
              f"{str(e)[:200]}")
        reason = (f"ownerville session failed: {type(e).__name__}: "
                  f"{str(e)[:200]}")
        for kind, done, out_list in (
                ("daily_knocks", done_daily, out_daily),
                ("knock_dispo", done_weekly, out_weekly)):
            if kind not in wanted:
                continue
            errors[kind] = reason
            for display, _cfg in pairs:
                if display not in done:
                    errors.setdefault(f"{kind}:{display}",
                                      "ownerville session failed before this "
                                      "owner's pull")
                    out_list.append((display, None))

    # Raf's email reply 2026-08-23 ("1 report of each ICD's averages so the
    # captain can look at one report for his whole captainship") + Megan
    # ("put this combined overall view before the individual ones"): ONE
    # summary board FIRST — each owner as a single row of their week's
    # totals/averages (the same totals-row math their own board's bottom row
    # shows), with a CAPTAINSHIP TOTALS row under them. Built from the data
    # already pulled above — zero extra pulls; an owner whose pull failed has
    # no row here (their pending note below says why).
    wsummary_png = (weekly_root / "summary"
                    / f"knock_dispo_summary_{saturday.isoformat()}.png")
    if not captured_weekly and want_weekly and wsummary_png.exists():
        # Same reasoning as the daily summary above: reuse the board
        # the earlier run drew instead of showing none.
        out_weekly.insert(0, ("Captainship Summary", wsummary_png))
    if captured_weekly:
        try:
            from automations.weekly_knock_dispositions.board import (
                THEME_PLUM, headers_for, totals_row)
            common_cols = next(
                (c for _d, _r, _a, c in captured_weekly if c), [])
            sum_rows = [totals_row(r, a, common_cols, label=d)
                        for d, r, a, _c in captured_weekly]
            all_rows = [rec for _d, r, _a, _c in captured_weekly for rec in r]
            merged_apps: dict = {}
            has_apps = False
            for _d, _r, a, _c in captured_weekly:
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
                weekly_root / "summary"
                / f"knock_dispo_summary_{saturday.isoformat()}.png",
                name_col=0, wrap_headers=True, highlight_last_row=1)
            out_weekly.insert(0, ("Captainship Summary" + (
                " — ⚠ INCOMPLETE: some ICDs reused from an earlier run"
                if weekly_partial else ""), png))
            logfn(f"    ✓ captainship summary: {len(captured_weekly)} "
                  "owner row(s)")
        except Exception as e:  # noqa: BLE001 — summary ≠ the section
            errors["knock_dispo:Captainship Summary"] = (
                f"{type(e).__name__}: {str(e)[:200]}")
            out_weekly.insert(0, ("Captainship Summary", None))
            logfn(f"    ✗ captainship summary: {type(e).__name__}: "
                  f"{str(e)[:160]}")

    # The daily counterpart (Megan: "a daily overall and then each ICD broken
    # out below it") — one row per ICD, teal Chan comparison row, plum
    # CAPTAINSHIP TOTALS. Same zero-extra-pulls economy (Chan's extra pull,
    # when it happened at all, happened once inside the session above).
    summary_png = (daily_root / "summary"
                   / f"daily_knocks_summary_{target.isoformat()}.png")
    if not captured_daily and want_daily and summary_png.exists():
        # Every owner came off disk and none carried rows, so there is nothing
        # to re-aggregate — but the summary this run would have drawn is
        # already sitting there from the run that drew them. Show that one
        # rather than dropping the board.
        out_daily.insert(0, (f"Daily Summary — {target.strftime('%b')} "
                             f"{target.day}", summary_png))
    if captured_daily:
        summary_label = f"Daily Summary — {target.strftime('%b')} {target.day}"
        try:
            png = render_daily_summary(captured_daily, target,
                                       daily_root / "summary",
                                       chan_rows=chan_rows)
            out_daily.insert(0, (summary_label + (
                " — ⚠ INCOMPLETE: some ICDs reused from an earlier run"
                if daily_partial else ""), png))
            logfn(f"    ✓ daily summary: {len(captured_daily)} ICD row(s)")
        except Exception as e:  # noqa: BLE001 — summary ≠ the section
            errors[f"daily_knocks:{summary_label}"] = (
                f"{type(e).__name__}: {str(e)[:200]}")
            out_daily.insert(0, (summary_label, None))
            logfn(f"    ✗ daily summary: {type(e).__name__}: {str(e)[:160]}")
    # Written LAST, so it only ever describes a finished pull: a run that dies
    # mid-session leaves no manifest and the next build pulls properly instead
    # of inheriting half a captainship.
    _save_manifest(render_dir, captain.key, target, saturday, wanted,
                   out, errors, logfn=logfn)
    return out


def capture(captain, today: dt.date, render_dir,
            *, logfn=print, errors: Optional[dict] = None
            ) -> List[Tuple[str, Optional[Path]]]:
    """The weekly boards alone — the original entry point, kept so a caller
    (or a scoped rerun) can still build just the Sunday section. run.py goes
    through capture_sections instead, which shares the roster lookup and the
    ownerville session between both sections."""
    return capture_sections(captain, today, render_dir, want_daily=False,
                            want_weekly=True, logfn=logfn,
                            errors=errors)["knock_dispo"]
