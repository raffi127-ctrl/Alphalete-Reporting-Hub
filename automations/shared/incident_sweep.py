"""Take the in-progress marks off incident posts that are already CLOSED.

WHY THIS EXISTS (Megan 2026-08-20)
----------------------------------
#claudecorrections-and-requests is triaged by REACTION: :pending: means somebody
is on this one, the white check means it's done. Megan: "Lucy the bot is putting
a pending reaction on things that she's not actually working ... it looks like
it's been worked on, but it's not." Two separate leaks put a :pending: on a post
that nothing is going to take off again:

  1. it was added to a thread nobody was working (a scheduled run, a retry, or a
     report merely WAITING on data — hub_publish.publish_running used to mark on
     every start). Fixed at the source: only a person's re-run marks now.
  2. the thread was ROLLED OVER to the next day rather than resolved. Roll-over
     flips the parent's marker to `resolved`, and incident_thread.find() only
     ever returns `open` ones — so from that moment no resolve can reach the post
     and its mark is frozen there for good. Also fixed at the source
     (incident_thread._roll_over strips both marks now).

Both fixes are forward-looking. This is the BACKSTOP: it walks recent history and
clears the marks already standing, and it keeps running daily so a leak nobody
has thought of yet costs one day of confusion instead of forever.

THE RULE IS NARROW ON PURPOSE. A mark is cleared only when the post's own marker
line says `resolved` — i.e. the incident is closed or superseded, and no reading
of the channel makes "someone is working this" true. An OPEN post is never
touched, whatever it is wearing: that might be a person who really is on it.

WHAT IT CANNOT DO — and reports instead
---------------------------------------
Slack's reactions.remove only removes YOUR OWN reaction; there is no API for
taking off someone else's. :pending: is also added by hand (it is the workspace's
own emoji and predates any of this), so a mark Megan or Eve put on a post cannot
be removed by Lucy no matter what. Those are LISTED, not posted about — Megan
2026-08-20 chose the quiet option: "sweeper logs them and reports the list, no
channel noise." The list goes to stdout (so it lands in the run's log) and to
output/incident-stray-pending.md, and somebody clears those few by hand.

Nothing here ever posts, replies, edits or resolves. It removes reactions and it
prints. Dry run by default; --apply to act.

CLI:
    python -m automations.shared.incident_sweep              # dry run
    python -m automations.shared.incident_sweep --apply
    python -m automations.shared.incident_sweep --days 14 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

from automations.shared import incident_thread as inc

CHANNEL = inc.CHANNEL
# The marks that mean "in progress". The white check is NOT here: a resolved post
# is supposed to wear it, and this module's whole job is to leave exactly that.
IN_PROGRESS = (inc.WORKING_REACTION, inc.WAITING_REACTION)
# How far back to look. A week covers "we were away Friday to Monday" without
# paging through history that nobody is scrolling any more.
DEFAULT_DAYS = 7
_PAGE = 200
_MAX_PAGES = 10                  # 2000 posts of lookback is far past a week's
REPORT_PATH = inc.REPO_ROOT / "output" / "incident-stray-pending.md"

# ASCII only in everything this module prints: it runs on the mini AND on
# Windows, where a cp1252 console turns one stray emoji into a crashed run
# (same reason incident_thread shadows print()).


def _history(client, channel: str, days: int) -> List[dict]:
    """Top-level messages from the last `days` days, oldest first."""
    since = dt.datetime.now() - dt.timedelta(days=days)
    oldest = str(int(since.timestamp()))
    msgs: List[dict] = []
    cursor = None
    # `oldest` already bounds this, but a paging loop that trusts a remote cursor
    # to terminate is a hang waiting to happen inside the 4am batch.
    for _ in range(_MAX_PAGES):
        kw = dict(channel=channel, oldest=oldest, limit=_PAGE)
        if cursor:
            kw["cursor"] = cursor
        resp = client.conversations_history(**kw)
        msgs.extend(resp.get("messages") or [])
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    # A reply carries thread_ts != ts; the marks only ever live on parents.
    msgs = [m for m in msgs
            if not m.get("thread_ts") or m.get("thread_ts") == m.get("ts")]
    msgs.sort(key=lambda m: float(m.get("ts") or 0))
    return msgs


def _reactors(msg: dict, name: str) -> List[str]:
    """Who reacted `name` on this message ([] if nobody)."""
    for rx in msg.get("reactions") or []:
        if rx.get("name") == name:
            return list(rx.get("users") or [])
    return []


def _headline(msg: dict) -> str:
    """The post's channel line, for a log a person can actually read."""
    first = (msg.get("text") or "").splitlines()
    for line in first:
        if line.strip() and not line.startswith("_incident "):
            return line.strip()[:90]
    return "(no headline)"


def _permalink(client, channel: str, ts: str) -> str:
    try:
        return client.chat_getPermalink(channel=channel,
                                        message_ts=ts).get("permalink") or ""
    except Exception:  # noqa: BLE001 — a link is a convenience, never a blocker
        return ""


def _write_report(rows: List[dict], day: dt.date) -> Optional[Path]:
    """The hand-added marks nobody but their author can remove, as a file Megan
    can forward. Overwritten each run — it is a CURRENT list, not a log."""
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Stray pending marks — {}".format(day.isoformat()), ""]
        if not rows:
            lines.append("None. Every in-progress mark on a closed post was "
                         "Lucy's own, and has been cleared.")
        else:
            lines += [
                "These posts are CLOSED but still wear an in-progress mark that "
                "was added by hand. Slack only lets the person who added a "
                "reaction take it off, so Lucy cannot clear these — whoever put "
                "them on needs to.",
                "",
            ]
            for r in rows:
                lines.append("- `:{}:` on *{}* - {}{}".format(
                    r["mark"], r["headline"], r["key"],
                    "\n  {}".format(r["link"]) if r.get("link") else ""))
        lines.append("")
        REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
        return REPORT_PATH
    except Exception as e:  # noqa: BLE001 — the printed list still stands
        print("  - couldn't write {} ({}: {})".format(
            REPORT_PATH, type(e).__name__, str(e)[:80]))
        return None


def sweep(*, channel: str = CHANNEL, days: int = DEFAULT_DAYS,
          apply: bool = False, client=None) -> Dict[str, int]:
    """Clear Lucy's in-progress marks from closed posts; list the rest.

    Returns {'ok', 'checked', 'closed', 'cleared', 'by_hand'}. Never raises:
    this runs daily in the batch, and a Slack hiccup must not fail the morning
    with a traceback — it fails it with `ok: False`, which main() turns into a
    non-zero exit so the Hub pill says what actually happened. A sweep that
    couldn't read the channel swept nothing, and a green pill on that is the
    "ran clean on exit 0 alone" lie the orchestrator already has too much of."""
    day = dt.date.today()
    out = {"ok": False, "checked": 0, "closed": 0, "cleared": 0, "by_hand": 0}
    try:
        client = client or inc._client()
        me = inc.whoami(client)
    except Exception as e:  # noqa: BLE001
        print("[incident-sweep] no Slack client ({}: {}) - nothing swept".format(
            type(e).__name__, str(e)[:80]))
        return out
    if not me:
        print("[incident-sweep] can't tell who this token is - nothing swept")
        return out

    try:
        msgs = _history(client, channel, days)
    except Exception as e:  # noqa: BLE001
        print("[incident-sweep] history read failed ({}: {}) - nothing "
              "swept".format(type(e).__name__, str(e)[:80]))
        return out

    print("[incident-sweep] {} top-level post(s) in the last {} day(s); I am "
          "{}{}".format(len(msgs), days, me,
                        "" if apply else "  [DRY RUN - nothing changed]"))
    stray: List[dict] = []
    for m in msgs:
        out["checked"] += 1
        mk = inc._MARK_RE.search(m.get("text") or "")
        # No marker = not one of our incident posts. A marker still saying `open`
        # is a live ticket: whatever it is wearing, it is not ours to second-guess.
        if not mk or mk.group("state") != "resolved":
            continue
        out["closed"] += 1
        ts, key = m["ts"], mk.group("key")
        for mark in IN_PROGRESS:
            users = _reactors(m, mark)
            if not users:
                continue
            if me in users:
                print("   :{}: on CLOSED {} ({}) - {}".format(
                    mark, key, ts, "removing" if apply else "would remove"))
                out["cleared"] += 1
                if apply:
                    inc._react(client, channel, ts, mark, remove=True)
            # Somebody else's mark. Slack has no removing another user's
            # reaction, so all we can do is name it (option (a), Megan
            # 2026-08-20: no channel noise).
            others = [u for u in users if u != me]
            if others:
                out["by_hand"] += 1
                stray.append({"mark": mark, "key": key, "ts": ts,
                              "headline": _headline(m),
                              "link": _permalink(client, channel, ts)})

    out["ok"] = True
    if stray:
        print("\n[incident-sweep] {} mark(s) added BY HAND on closed posts - "
              "Lucy cannot remove these, whoever added them has to:".format(
                  len(stray)))
        for r in stray:
            print("   :{}:  {}  ({})  {}".format(
                r["mark"], r["headline"], r["key"], r["link"]))
    path = _write_report(stray, day)
    print("\n[incident-sweep] checked {checked}, closed {closed}, "
          "cleared {cleared}, by-hand {by_hand}".format(**out)
          + ("" if apply else "  (dry run)")
          + ("\n[incident-sweep] list: {}".format(path) if path else ""))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Clear stale :pending:/waiting marks off CLOSED incident "
                    "posts in #claudecorrections-and-requests.")
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help="how far back to look (default {})".format(DEFAULT_DAYS))
    ap.add_argument("--apply", action="store_true",
                    help="actually remove them (default: dry run)")
    a = ap.parse_args(argv)
    out = sweep(channel=a.channel, days=a.days, apply=a.apply)
    # Non-zero when the sweep could not run — see sweep()'s docstring.
    return 0 if out.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
