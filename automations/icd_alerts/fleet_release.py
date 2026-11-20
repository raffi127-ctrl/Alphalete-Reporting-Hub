"""Which release each office's computer is ACTUALLY running.

  python -m automations.icd_alerts.fleet_release

WHY THIS EXISTS (Megan, 2026-11-19). A Sterling fix went into main at 2:58pm
and I told her the office could rerun. It could not: office computers do not
take code from main, they take it when `agent_release.txt` moves, and nothing
anywhere reported which release an office had actually applied. The only way
to reason about it was "no update fault was filed, so it must have landed" --
an inference, not a reading, and the same blind spot that had me check a core
Lucy's git HEAD for a job that does not run on a Lucy at all.

So each office now sends its applied release on every relay
(`relay.agent_release`), the relay keeps it in the machine blob it already
writes, and this reads it back. Read-only: no Sheet writes, no Slack, no mail.

HOW TO READ THE THREE GROUPS:
  * Running it   -- applied release == what we published. The fix is live.
  * Behind       -- applied an OLDER release. It is still updating, just not
                    yet; if one sits here for hours, its self-update is
                    failing and that is worth chasing.
  * Can't say    -- no answer. EITHER the agent predates this reporting (it
                    will start answering on its next update) OR the machine
                    has never self-updated at all and runs installer code.
                    This group is NOT an all-clear; it is the unexamined pile,
                    the same way laptop_offices() reads a zero.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.icd_alerts import post as P


def _blob_release(info) -> Optional[str]:
    """The release a machine blob reports, or None when it never said.

    "" is not None. An office that answered with an empty stamp HAS been
    asked and has no self-update behind it -- different from an agent too old
    to be asked, and the difference is the whole point of the Can't-say note.
    """
    if not isinstance(info, dict) or "agent_release" not in info:
        return None
    return str(info.get("agent_release") or "").strip()


def machine_releases(book=None) -> List[Dict]:
    """One entry per machine, newest row wins. Never raises on a bad row."""
    from automations.recruiting_report.fill import open_by_key

    book = book or open_by_key(P.RELAY_SPREADSHEET_ID)
    newest: Dict[str, Dict] = {}
    for tab, col in ((P.RELAY_TAB, P.COL_MACHINES),
                     (P.KNOCKS_TAB, P.KN_MACHINES)):
        # BOTH TABS, for the same reason laptop_offices() reads both: an
        # office with no SaraPlus never writes a relay row at all.
        try:
            got = book.worksheet(tab).get_all_values()
        except Exception:  # noqa: BLE001 — tab renamed, no access
            continue
        for row in got[1:]:
            if not row or not (row[P.COL_OFFICE] or "").strip():
                continue
            office = (row[P.COL_OFFICE] or "").strip().lower()
            for mid, info in (P.machines_for(row, col) or {}).items():
                last = str((info or {}).get("last") or "")
                prev = newest.get(mid)
                if prev and str(prev.get("last") or "") >= last:
                    continue
                newest[mid] = {
                    "office": office,
                    "id": mid,
                    "name": (info or {}).get("name") or mid,
                    "release": _blob_release(info),
                    "last": last,
                }
    return sorted(newest.values(), key=lambda m: (m["office"], m["name"]))


def _when(stamp: str) -> str:
    """A machine's last-heard time, in the reader's OWN clock.

    The stamp arrives UTC ("...Z"). Printing it unconverted was worse than
    useless: on 2026-11-20 at 06:59 CST the report said a machine was last
    heard at 09:02, which reads as two hours into the future and makes a
    quiet office look busy. So it is converted to local time and labelled.

    No `%-d`/`%-H`: those are glibc-only and blow up on Windows, and every
    report here has to run on both. lstrip("0") does the same job everywhere.
    """
    try:
        when = dt.datetime.fromisoformat(
            stamp.replace("Z", "")[:19]).replace(tzinfo=dt.timezone.utc)
    except (AttributeError, TypeError, ValueError):
        # AttributeError: a blob with no `last` at all -- .replace on None.
        # A machine that never stamped a time is "?", not a crash that takes
        # the whole fleet report down with it.
        return "?"
    local = when.astimezone()
    day = local.strftime("%d").lstrip("0") or "0"
    hour = local.strftime("%H")
    return "%s %s %s:%s" % (day, local.strftime("%b"), hour,
                            local.strftime("%M"))


# `published=None` has to MEAN "we could not tell" -- that is what
# selfupdate.published_release() returns when GitHub is unreachable, and the
# whole point of this report is that an unanswerable question reads as
# unanswered. So "go and look it up" needs its own value; a None default would
# quietly turn "could not tell" into a network call.
_LOOK_IT_UP = object()


def report(book=None, published=_LOOK_IT_UP, log=print) -> Dict:
    from automations.icd_alerts import selfupdate

    if published is _LOOK_IT_UP:
        published = selfupdate.published_release()
    rows = machine_releases(book=book)

    current = [m for m in rows if published and m["release"] == published]
    behind = [m for m in rows if m["release"] not in (None, published)]
    unknown = [m for m in rows if m["release"] is None]
    never = [m for m in behind if m["release"] == ""]
    behind = [m for m in behind if m["release"] != ""]

    log("Published release: %s" % (published or "could not reach GitHub"))
    log("")
    log("Running it (%d)" % len(current))
    log("Behind (%d)" % len(behind))
    for m in behind:
        log("  · %-22s %-16s last heard %s"
            % (m["office"], m["release"], _when(m["last"])))
    if never:
        log("Never self-updated (%d) — running installer code" % len(never))
        for m in never:
            log("  · %-22s %s  last heard %s"
                % (m["office"], m["name"], _when(m["last"])))
    log("Can't say (%d) — agent too old to be asked; not an all-clear"
        % len(unknown))
    for m in unknown:
        log("  · %-22s %s  last heard %s"
            % (m["office"], m["name"], _when(m["last"])))
    return {"published": published, "current": current, "behind": behind,
            "never": never, "unknown": unknown}


if __name__ == "__main__":   # pragma: no cover
    report()
