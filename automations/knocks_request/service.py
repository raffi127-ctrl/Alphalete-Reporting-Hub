"""The engine behind `/knocks`: one office + one day -> the knock board PNG.

CACHE FIRST, AND THAT IS THE WHOLE DESIGN. Ownerville allows ONE live session
per account, so an on-demand pull that just opens a browser would fight the
morning build for it — the build that is already scraping every office on the
same login. The way out is that the build already leaves what it pulled on
disk: `captainship_drafts.knock_dispo_images` writes each owner's board PNG
plus a `rows_*.json` sidecar of the very records it scraped. So for the day
people actually ask about — today's board, i.e. yesterday's knocks — this
module answers from those rows and never opens ownerville at all.

Order of attempts, first hit wins:
  1. our own cache        output/knocks_request/<office>/<date>.json
  2. the build's sidecar  <RENDER_DIR>/daily_knocks_*/<office>/rows_total_knocks_<date>.json
  3. a live pull          rashad_metrics.knocks_pull.pull_office_knocks

Only step 3 needs ownerville, and it refuses to start while another module on
this machine is holding the session (proc_guard) — `wait_for_ownerville` polls
instead, so a request during the 07:15 build lands when the build is done
rather than stealing its session and failing both.

NOTHING HERE IS A NEW SCRAPE OR A NEW DRAWING. The pull is the same
`pull_office_knocks` the Rashad/other-office reports use (impersonate by name,
Disposition by Rep + Time Tracker, exit impersonation), and the image is the
same `total_knocks.render.render_total_knocks` board Raf gets every morning —
rendered from rows in memory, so no Sheet is read or written by a request.

No Slack in this module on purpose: `run.py` exercises the whole path offline.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

OUT_DIR = Path("output") / "knocks_request"

# Modules that hold the ONE ownerville session while they run. A live pull
# waits for all of them. Names are `python -m` module paths, which is what
# proc_guard matches on.
OWNERVILLE_MODULES = (
    "automations.captainship_drafts.run",
    "automations.captainship_drafts.knocks_capture",
    "automations.weekly_knock_dispositions.run",
    "automations.total_knocks.run",
    "automations.other_office_knocks.run",
    "automations.rashad_metrics.knocks_run",
    "automations.focus_office_att.run_all_owners",
)

# How long a request is willing to wait for the session before giving up. The
# 07:15 captainship build can run ~2h, so the default covers a request sent
# while it works; the caller is told it is waiting, never left silent.
WAIT_TIMEOUT_S = 150 * 60
WAIT_POLL_S = 45


@dataclass
class Board:
    """What a request produced. `png` is None only when the day is a real
    zero — an office that recorded no knocks — which is an answer, not a
    failure, and `note` says so."""
    office: str                  # the canonical office/owner name
    asked_as: str                # what the requester typed
    target: dt.date
    png: Optional[Path] = None
    rows: List[dict] = field(default_factory=list)
    source: str = ""             # "cache" | "build" | "live"
    note: str = ""
    partial: bool = False        # today's board: the day isn't over yet
    compared_to: str = ""        # office whose teal TOTAL line rides the board


def central_today() -> dt.date:
    from automations.total_knocks.pull import central_today as _ct
    return _ct()


def default_target() -> dt.date:
    """Yesterday, Central — the day this morning's board covers."""
    return central_today() - dt.timedelta(days=1)


def _slug(name: str) -> str:
    from automations.captainship_drafts.knock_dispo_images import _slug as s
    return s(name)


def resolve_office(office: str) -> str:
    """The canonical ICD spelling for whatever the requester typed. A miss
    here is not fatal — the impersonation search tries the aliases too — so a
    broken alias sheet returns the input rather than raising."""
    try:
        from automations.focus_office_att.aliases import (
            alias_to_canonical, load_aliases,
        )
        return alias_to_canonical(office, load_aliases())
    except Exception:  # noqa: BLE001 — a name we can't canonicalise still pulls
        return office


# --------------------------------------------------------------- cache ----
def _cache_path(canonical: str, target: dt.date) -> Path:
    return OUT_DIR / _slug(canonical) / f"{target.isoformat()}.json"


def _build_render_dir() -> Path:
    """Where the captainship build parks the day's boards. Imported from its
    config so the two can't drift; the literal is only the fallback for a
    machine where that import pulls in something mid-refactor."""
    try:
        from automations.captainship_drafts import config as C
        return Path(C.RENDER_DIR)
    except Exception:  # noqa: BLE001
        return Path(tempfile.gettempdir()) / "captainship_drafts_render"


def cached_rows(canonical: str, target: dt.date) -> tuple[Optional[list], str]:
    """(rows, source) from disk, or (None, "") — see the module docstring for
    the order. Empty rows are NOT a cache hit: the build stores an empty pull
    for a real zero-knock day, but so does a failed impersonation, and a
    request should retry rather than freeze a maybe-wrong zero."""
    own = _cache_path(canonical, target)
    if own.exists():
        try:
            rows = json.loads(own.read_text(encoding="utf-8"))
            if rows:
                return rows, "cache"
        except Exception:  # noqa: BLE001 — a bad cache file just misses
            pass

    from automations.captainship_drafts.knock_dispo_images import (
        _owner_png, _read_rows,
    )
    root = _build_render_dir()
    slug = _slug(canonical)
    for daily_root in sorted(root.glob("daily_knocks_*")):
        # The build's dirs are per CAPTAIN; the owner subdir is what we match.
        if not (daily_root / slug).is_dir():
            continue
        png = _owner_png(daily_root, canonical, "total_knocks", target)
        rows = _read_rows(png)
        if rows:
            return rows, "build"
    return None, ""


def save_rows(canonical: str, target: dt.date, rows: list) -> None:
    """Park a live pull so the second person asking the same thing is free.

    TODAY IS NEVER CACHED. A mid-day pull is a snapshot of a day still being
    knocked; storing it would hand the next person this morning's half-numbers
    as if they were the day's, hours later. Only a finished day is frozen."""
    if not rows or target >= central_today():
        return
    p = _cache_path(canonical, target)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows), encoding="utf-8")
    except Exception:  # noqa: BLE001 — a cache that won't write is not an error
        pass


# ----------------------------------------------------------- ownerville ----
def ownerville_busy() -> List[str]:
    """Modules currently holding the ownerville session on this machine.

    [] on Windows and anywhere pgrep is missing (proc_guard's documented
    limit) — there the request just goes, which is what a laptop test wants."""
    from automations.day_orchestrator import proc_guard
    busy = []
    for mod in OWNERVILLE_MODULES:
        try:
            if proc_guard.running_pids(mod):
                busy.append(mod.rsplit(".", 2)[-2])
        except Exception:  # noqa: BLE001 — a guard must never raise
            pass
    return sorted(set(busy))


def wait_for_ownerville(*, timeout_s: int = WAIT_TIMEOUT_S,
                        poll_s: int = WAIT_POLL_S,
                        logfn: Callable[[str], None] = print) -> bool:
    """Block until nothing else holds the session. False = still busy at the
    timeout, and the caller reports that instead of pulling anyway."""
    deadline = time.monotonic() + timeout_s
    told = False
    while True:
        busy = ownerville_busy()
        if not busy:
            return True
        if not told:
            logfn(f"ownerville is busy ({', '.join(busy)}) — waiting for it "
                  "to finish before pulling")
            told = True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)



# ------------------------------------------------------------- compare ----
# Raf 2026-08-23 ("add Chan's totals above ours daily") put a teal CHAN PARK
# TOTAL line on the morning board; a board pulled on demand is the same board,
# so it carries the same line. render_total_knocks already takes `extra_totals`
# for exactly this — nothing is drawn here.
def compare_office() -> str:
    """Whose totals ride every board as the comparison line."""
    from automations.weekly_knock_dispositions.offices import CHAN
    return resolve_office(CHAN["name"])


def compare_rows(canonical: str, target: dt.date, *, allow_live: bool,
                 logfn: Callable[[str], None] = print
                 ) -> Optional[list]:
    """The comparison office's rows for `target`, or None to omit the line.

    NEVER opens an ownerville session of its own: a comparison is a nicety and
    a second session would fight the one the real pull needs. `allow_live` is
    True only when the caller is already inside a live pull and can afford the
    extra office in the SAME session."""
    compare = compare_office()
    if _norm(compare) == _norm(canonical):
        return None                     # asking for Chan: nothing to compare to
    rows, source = cached_rows(compare, target)
    if rows:
        logfn(f"comparison: {compare} from the {source}")
        return rows
    if not allow_live:
        logfn(f"comparison: no stored {compare} rows for {target} — board "
              "goes out without the teal line")
        return None
    return None                         # live path fills this in; see board_for


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


# ---------------------------------------------------------------- board ----
def board_for(office: str, target: Optional[dt.date] = None, *,
              allow_live: bool = True,
              wait_timeout_s: int = WAIT_TIMEOUT_S,
              logfn: Callable[[str], None] = print) -> Board:
    """The whole request: cache, else pull, then draw. Raises only on a real
    failure (no such office, ownerville still busy, a broken pull) — a day
    with genuinely no knocks comes back as a Board with png=None and a note."""
    target = target or default_target()
    today = central_today()
    # A day that hasn't happened is not an empty day. Ownerville answers a
    # future date with an empty grid — exactly what a real zero looks like —
    # so it has to be refused HERE, or the requester is told "no knocks
    # recorded" about tomorrow.
    if target > today:
        raise ValueError(
            f"{target.isoformat()} hasn't happened yet — pick today or a day "
            "that's already gone by.")
    canonical = resolve_office(office)
    b = Board(office=canonical, asked_as=office, target=target,
              partial=(target == today))
    if canonical.lower() != office.strip().lower():
        logfn(f"'{office}' resolves to '{canonical}'")

    # Cache-first for the comparison too, so a cached board stays a
    # zero-session answer. allow_live=False here: the live branch below pulls
    # it in the session it is already opening.
    chan_rows = compare_rows(canonical, target, allow_live=False, logfn=logfn)

    rows, source = cached_rows(canonical, target)
    if rows:
        logfn(f"{canonical} {target}: {len(rows)} rep(s) from the {source} "
              "(no ownerville session needed)")
    else:
        if not allow_live:
            raise RuntimeError(
                f"No stored knocks for {canonical} on {target} and live pulls "
                "are off for this run.")
        if not wait_for_ownerville(timeout_s=wait_timeout_s, logfn=logfn):
            raise RuntimeError(
                "Ownerville is still busy with the scheduled reports — nothing "
                "was pulled. Ask again once they finish.")
        # One session, both offices (pull_offices_knocks exists for exactly
        # this): a second session for the comparison line would race the
        # first for the same Chrome profile. The comparison office rides
        # along ONLY when it isn't already on disk.
        # ALWAYS the multi-office helper, even for one office: it is the
        # path that routes the MASTER office (Raf) around impersonation.
        # pull_office_knocks impersonates unconditionally, so asking it for
        # Raf reports his own office as an access gap.
        from automations.rashad_metrics.knocks_pull import pull_offices_knocks
        compare = compare_office()
        want_compare = (chan_rows is None
                        and _norm(compare) != _norm(canonical))
        wanted = [canonical] + ([compare] if want_compare else [])
        logfn(f"pulling {' + '.join(wanted)} for {target} from ownerville…")
        _t, pulled = pull_offices_knocks(wanted, target, verbose=True)
        _n, rows, err = pulled[0]
        if err is not None:
            raise err                          # THIS office failing is fatal
        if want_compare:
            _cn, c_rows, c_err = pulled[1]
            if c_err is not None:
                # A missing comparison costs one line, never the board.
                logfn(f"⚠ {compare} comparison pull failed "
                      f"({type(c_err).__name__}) — board goes out without it")
            elif c_rows:
                chan_rows = c_rows
                save_rows(compare, target, c_rows)
        source = "live"
        save_rows(canonical, target, rows)

    b.rows, b.source = rows, source
    if not rows:
        # An empty grid is genuinely ambiguous: a day nobody knocked and a day
        # the office has no data for at all look identical coming back. Say
        # both possibilities rather than asserting the flattering one.
        b.note = ("Ownerville returned no rows for that day — either nobody "
                  "knocked, or that office has no data that far back")
        return b

    from automations.total_knocks import render as knocks_render
    extra = []
    if chan_rows:
        extra.append((compare_office(), chan_rows))
        b.compared_to = compare_office()
    b.png = knocks_render.render_total_knocks(
        target, rows=rows, out_dir=OUT_DIR / _slug(canonical),
        title_suffix=canonical, extra_totals=extra)
    logfn(f"board -> {b.png}")
    return b


def access_gap(exc: BaseException) -> bool:
    """True when the failure is 'this office isn't on our ownerville account'
    rather than a run problem — the same test the captainship section uses, so
    both places call an access gap by the same name."""
    from automations.captainship_drafts.knock_dispo_images import (
        _NO_OFFICE_MARKERS,
    )
    return any(m in str(exc).lower() for m in _NO_OFFICE_MARKERS)
