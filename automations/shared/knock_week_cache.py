"""Per-week shared cache of ONE office's Mon–Sat ownerville knock pull.

WHY THIS EXISTS (Megan 2026-08-24). Two reports pull the SAME ownerville data
for the SAME completed Mon–Sat week, on the same two days:

  * weekly_knock_dispositions (Sunday, order 36.5) — ~13 offices, each
    6 single-day Disposition scrapes + 6 Time-Tracker calls.
  * captainship_drafts.knock_dispo_images' `knock_dispo` section (Sun+Mon,
    order 24) — every owner of six fiber captainships (~50 owner-slots),
    through the SAME pull.pull_office_week, for the SAME week (week_window
    resolves Sunday and Monday to the identical Mon–Sat window on purpose —
    Raf wants Monday's email to re-show Sunday's board).

Sunday therefore paid for the overlap twice, and Monday paid for the whole
captainship sweep again from scratch: the 2026-08-24 build sat 1h40m+ on the
mini's SERIAL control queue, blocking everything behind it. Nothing about the
data justified that — a completed week is frozen; re-pulling it can only
return what the first pull already returned.

So: cache the pull RESULT, keyed by (office, saturday). Whichever report gets
to an office first pays the ownerville cost; every later reader that week gets
it free, in either order, across processes and across days.

WHAT IS CACHED — the DATA, not the PNG. pull_office_week returns
(ov_rows, dispo_cols): flat dicts of str → str/int (total_knocks.pull's COL_*
names + wkd pull's K_TALK_TO / K_GAP_MIN / K_SAT_FIRST / K_SAT_LAST + the live
disposition-column names) plus the column-name list. Re-rendering a board from
those rows is milliseconds of local Pillow work; re-pulling them is ~12
ownerville round-trips per office. Caching the rows also means the two reports
keep drawing their own boards their own way (different titles, themes, totals
rows) off one shared pull.

WEEKLY ONLY. The daily (`daily_knocks`) pulls are deliberately NOT cached:
one day, cheap, and they change intraday — a mid-day rerun must see the newer
number.

FILE FORMAT — one JSON file per week, output/knock_week_cache/<saturday>.json:

    {"saturday": "2026-08-22",
     "written_at": "2026-08-24T04:11:07",
     "offices": {
       "rafaelhidalgo": {"office": "Rafael Hidalgo",     # raw, for debugging
                         "canonical": "Rafael Hidalgo",  # alias-resolved
                         "at": "2026-08-24T04:11:07",
                         "rows": [...], "dispo_cols": [...]}}}

output/ is gitignored, so this is per-machine scratch — exactly right: it's a
speed-up, never a source of truth, and a machine that loses it just pulls
again.

FAILURE POSTURE. Every entry point is best-effort: a missing file, a corrupt
file, an unreadable directory, a JSON type surprise — all return "no hit" and
let the caller pull live. A cache that can wedge a report is worse than no
cache, which is also why DISABLED / KNOCK_WEEK_CACHE_OFF=1 exists: one env var
turns every get() into a miss without a deploy.

NEVER CACHE AN EMPTY PULL. `ov_rows == []` is usually a FAILED impersonation
(the office answered as somebody with no reps), not a real empty week — the
same trap that made "No data available" posts look like clean runs before
weekly_knock_dispositions learned to fail loudly. Caching that would freeze one
bad pull in for the rest of the week, so put() drops it on the floor and the
next reader re-pulls.

Public API is deliberately four functions:

    get(office, saturday)                       → (rows, cols) | None
    put(office, saturday, ov_rows, dispo_cols)  → None
    prune(keep_weeks=3)                         → None
    DISABLED / KNOCK_WEEK_CACHE_OFF=1           → every get() misses
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Repo root / output/… — anchored to THIS file, never to the cwd: the mini
# runs reports from the day-orchestrator's working dir, not the repo root
# (cross-platform rule; a bare Path("output") would scatter caches).
CACHE_DIR = Path(__file__).resolve().parents[2] / "output" / "knock_week_cache"

# Kill switch. Flip the module flag from a REPL/test, or set the env var on the
# machine — either makes get() miss while put() keeps writing, so a suspect
# cache can be bypassed for one run and inspected afterwards instead of being
# deleted blind.
DISABLED = False
ENV_OFF = "KNOCK_WEEK_CACHE_OFF"

# Alias table, memoized per process. aliases.load_aliases() deliberately does
# NOT memoize (the long-running Hub must see a new alias row without a
# restart), but a cache KEY only needs to be stable for the length of one run,
# and re-reading the Sheet once per office would cost more than the cache
# saves. Callers that already hold the table (both of ours do) pass it in and
# never touch this.
_ALIASES: Dict[str, list] = {}
_ALIASES_LOADED = False


def _off() -> bool:
    """True when the cache is switched off. Env is re-read every call on
    purpose — `KNOCK_WEEK_CACHE_OFF=1 lucy rerun …` must work without anyone
    reasoning about import order."""
    return DISABLED or os.environ.get(ENV_OFF, "").strip() not in ("", "0")


def _aliases(aliases: Optional[Dict[str, list]]) -> Dict[str, list]:
    global _ALIASES_LOADED
    if aliases is not None:
        return aliases
    if not _ALIASES_LOADED:
        try:
            from automations.focus_office_att.aliases import load_aliases
            _ALIASES.update(load_aliases() or {})
        except Exception:  # noqa: BLE001 — no alias table ≠ no cache
            pass
        _ALIASES_LOADED = True
    return _ALIASES


def office_key(office: str,
               aliases: Optional[Dict[str, list]] = None) -> str:
    """The cache key for an office name: alias-resolved canonical, then a
    lower/alnum squeeze.

    Both halves matter. The alias hop is what stops "Muhammad UI Haque"
    (weekly_knock_dispositions' enrolled row, spelled the way ownerville
    spells it) and "Hammad Haque" (the Org Sales Board roster's spelling, what
    the captainship section carries) from becoming two keys for one office —
    which would quietly re-pull the very office the cache exists for. The
    squeeze then absorbs the residue the alias sheet doesn't cover: casing,
    double spaces, a smart apostrophe in "D'Mari Longmire", a stray period in
    "Jr.".
    """
    name = (office or "").strip()
    try:
        from automations.focus_office_att.aliases import alias_to_canonical
        canonical = alias_to_canonical(name, _aliases(aliases)) or name
    except Exception:  # noqa: BLE001 — a broken alias sheet ≠ no cache
        canonical = name
    return re.sub(r"[^a-z0-9]+", "", canonical.lower())


def _sat_iso(saturday) -> str:
    """Accept a date or an already-ISO string — callers hold a dt.date, but a
    scoped rerun that reads a date off argv shouldn't have to convert."""
    return saturday.isoformat() if hasattr(saturday, "isoformat") else str(
        saturday)


def _week_path(saturday) -> Path:
    return CACHE_DIR / f"{_sat_iso(saturday)}.json"


def _read_week(saturday) -> dict:
    """The week file's dict, or {} for missing/corrupt/wrong-shape. Never
    raises: a half-written or hand-edited file must cost a re-pull, not a run.
    """
    try:
        raw = json.loads(_week_path(saturday).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing, truncated, not-JSON, unreadable
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("offices"), dict):
        return {}
    return raw


def _jsonable(v: Any) -> Any:
    """Coerce one cell value to something JSON round-trips unchanged.

    In practice pull_office_week only ever emits str and int (scraped cell
    text, _to_int counts, _fmt_knock time strings, summed gap minutes), and
    the round-trip test asserts that. This exists for the day a new
    disposition column or a Time-Tracker field arrives as something else: a
    date, a Path, a tuple. Those would either explode json.dump or come back a
    DIFFERENT type than the board expects, so they're stringified on write —
    documented lossiness beats a surprise TypeError at 4am.
    """
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    # Lists round-trip as lists (recursing, so a list of lists survives too).
    # WITHOUT this they were stringified — 2026-08-30, the day pull_office_week
    # started carrying K_DAILY_KNOCKS, every cached row came back holding
    # "[35, 53, 141, 65, 49, 50]" instead of the six numbers. Nothing raised:
    # board.is_knocking type-checks for a list, so it just answered False for
    # every rep, and the two knocking columns went BLANK on every board drawn
    # from cache — which is Monday's captainship build and every Sunday
    # weekly_knock_dispositions run after the captainship one. The fill-but-
    # flag blank is the correct output for "we can't tell"; it is the wrong
    # output for "we measured it and threw it away in the cache writer".
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)


# The shape of what put() writes. BUMP THIS whenever pull_office_week starts
# carrying a field the boards need: an entry written by an older build is then
# a MISS, so the office re-pulls once and every reader after it gets the new
# field — instead of the board quietly drawing a blank column off a row that
# predates it. Bumped to 2 on 2026-08-30 (per-day door counts, for Raf's reps-
# knocking columns). A miss costs one pull; a stale hit costs a wrong board.
#
# 3 on the same day: _jsonable was stringifying the list it had just started
# storing, so every schema-2 entry holds a useless "[35, 53, …]" string and has
# to be thrown away, not read.
# 4 (2026-08-30, later the same day): per-day GAP minutes and Total Leads
# Knocked joined the pull for Raf's Saturday columns and the Mon–Fri knocking
# fix. A schema-3 row has neither, so it must re-pull rather than draw them
# blank.
# 5 (2026-08-30, same evening): K_TT_DAYS — which days the rep had a Time
# Tracker record — for Raf's Saturday clock-in column. A schema-4 row cannot be
# topped up: "no record" and "record with no gaps" both stored 0 minutes, so
# the distinction has to come from a fresh pull.
SCHEMA = 5


def get(office: str, saturday, *,
        aliases: Optional[Dict[str, list]] = None
        ) -> Optional[Tuple[List[dict], List[str]]]:
    """This office's cached (ov_rows, dispo_cols) for the week ending
    `saturday`, or None for a miss (which includes: cache off, no file,
    corrupt file, office not in it, or an entry that somehow holds no rows —
    an empty hit is treated as no hit, same rule put() writes by)."""
    if _off():
        return None
    entry = _read_week(saturday).get("offices", {}).get(
        office_key(office, aliases))
    if not isinstance(entry, dict):
        return None
    if int(entry.get("schema") or 1) < SCHEMA:
        return None                     # written by an older build — re-pull
    rows, cols = entry.get("rows"), entry.get("dispo_cols")
    if not isinstance(rows, list) or not isinstance(cols, list) or not rows:
        return None
    return rows, cols


def put(office: str, saturday, ov_rows: List[dict], dispo_cols: List[str], *,
        aliases: Optional[Dict[str, list]] = None) -> None:
    """Record a SUCCESSFUL pull. No-op for an empty result (see the module
    docstring: an empty week is usually a failed impersonation, and freezing
    one in would cost the office its board for the rest of the week).

    Writes are ATOMIC (tmp file in the same dir + os.replace) because the two
    reports run back-to-back on the mini's serial queue and a half-written
    week file must never be what the next one reads. The read-modify-write of
    the week dict is NOT locked: the queue is serial, so nothing here races
    today, and the worst a future overlap could do is lose one office's entry
    — which costs a re-pull, not a wrong board. Ignoring the write entirely on
    any error is the same trade: this is a speed-up, never a dependency."""
    if not ov_rows:
        return
    try:
        data = _read_week(saturday)
        offices = data.get("offices")
        if not isinstance(offices, dict):
            offices = {}
        now = dt.datetime.now().replace(microsecond=0).isoformat()
        offices[office_key(office, aliases)] = {
            # Raw + canonical both kept: when someone opens this file to work
            # out why an office re-pulled, "which spelling landed here" is the
            # first question, and the squeezed key alone can't answer it.
            "office": office,
            "canonical": office_key(office, aliases),
            "at": now,
            "schema": SCHEMA,
            "rows": [{str(k): _jsonable(v) for k, v in rec.items()}
                     for rec in ov_rows],
            "dispo_cols": [str(c) for c in dispo_cols or []],
        }
        data = {"saturday": _sat_iso(saturday), "written_at": now,
                "offices": offices}
        path = _week_path(saturday)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                                   prefix=".knock_week_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)      # no-op once os.replace moved it
            except OSError:
                pass
    except Exception:  # noqa: BLE001 — a cache write must never fail a report
        return
    prune()


def prune(keep_weeks: int = 3) -> None:
    """Keep the newest `keep_weeks` week files, delete older ones.

    Called opportunistically from put(), so the directory self-limits without
    anyone scheduling a sweep. Three weeks is enough that a late catch-up
    rerun of an older week still hits, and small enough that the directory
    stays a handful of files. Non-date filenames are left strictly alone —
    if someone parks a note in there, it is not ours to delete."""
    try:
        dated = []
        for p in CACHE_DIR.glob("*.json"):
            try:
                dt.date.fromisoformat(p.stem)
            except ValueError:
                continue            # not one of ours — leave it
            dated.append(p)
        for p in sorted(dated, key=lambda q: q.stem,
                        reverse=True)[max(int(keep_weeks), 0):]:
            try:
                p.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001 — housekeeping never fails a report
        pass
