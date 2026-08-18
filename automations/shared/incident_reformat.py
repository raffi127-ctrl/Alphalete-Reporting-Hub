"""Re-format alert posts that are ALREADY in #claudecorrections into the one-line
channel format (Megan 2026-08-18).

The format change itself lives in `alert_thread.headline` / `incident_thread`, so
everything posted from now on is right. This is the catch-up pass for the posts
that went out BEFORE it — Megan asked to fix today's channel too, and a channel
where half the alerts are the old wall and half are the new line is harder to
read than either one.

WHAT IT DOES to each top-level alert:
  1. keeps the ORIGINAL text — posted as a thread reply first, so nothing is
     lost, and only when that text isn't already in the thread
  2. edits the parent down to `*What broke* — a few words on why`
  3. keeps the `_incident · … _` marker EXACTLY as it was: every machine finds
     its open threads by scanning for that line, and a rewritten key would
     orphan the thread (or, worse, rename someone else's)
  4. keeps a `· *RESOLVED* <date>` stamp if the parent already carried one — a
     closed ticket must not read as open again

WHOSE POSTS: chat.update only touches your OWN messages, so this edits only what
the running token posted. These alerts come out as Lucy (U0BCG8F9B5Z), so RUN IT
ON THE MINI — `lucy rerun reformat_incident_alerts`. From a laptop it will report
every Lucy post as "not mine, skipped" and change nothing. Posts by a human
(Megan, Evelyn) can only be edited by that person.

Dry by default. Nothing is written without --apply.

    PYTHONPATH=. .venv/bin/python -m automations.shared.incident_reformat
    PYTHONPATH=. .venv/bin/python -m automations.shared.incident_reformat --apply

3.9-safe (the mini runs 3.9). [[feedback_corrections_alert_format]]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import List, Optional, Tuple

from automations.shared import alert_thread as at
from automations.shared.incident_thread import CHANNEL, _MARK_RE

# The pointer alert_thread.split_for_thread used to leave on a trimmed parent.
# It described the OLD split; carrying it into the new one-liner would be a
# dangling "see below" on a line that is already the whole channel post.
_MORE_RE = re.compile(r"^_…?\s*full detail in the thread.*_$")
_RESOLVED_RE = re.compile(r"\s*·\s*\*?RESOLVED\*?\s*(?P<rest>.*)$", re.I)


def _parts(text: str) -> Tuple[List[str], List[str]]:
    """(body lines, marker lines) — the marker is carried through untouched."""
    body, marks = [], []
    for ln in (text or "").splitlines():
        if _MARK_RE.search(ln):
            marks.append(ln)
        elif not _MORE_RE.match(ln.strip()):
            body.append(ln)
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return body, marks


def rewrite(text: str) -> Optional[str]:
    """The new parent text, or None when it's already in the new format."""
    body, marks = _parts(text)
    if not body:
        return None
    stamp = ""
    m = _RESOLVED_RE.search(body[0])
    if m:                                   # keep "· *RESOLVED* Tue Aug 18"
        stamp = " · *RESOLVED* {}".format(m.group("rest").strip()).rstrip()
        body[0] = body[0][:m.start()].rstrip()
    head = at.headline(body[0], body[1:]) + stamp
    new = "\n\n".join([head] + (["\n".join(marks)] if marks else []))
    return None if new.strip() == (text or "").strip() else new


def _already_in_thread(client, channel: str, ts: str, body: List[str]) -> bool:
    """True when the parent's own words are already somewhere in its thread, so
    trimming the parent loses nothing and needs no extra reply."""
    probe = at.strip_emoji(re.sub(r"[*_`]", "", body[-1])).strip()
    if len(probe) < 12:
        return False
    try:
        reps = client.conversations_replies(channel=channel, ts=ts, limit=50)
    except Exception:  # noqa: BLE001 — can't prove it's there, so keep a copy
        return False
    for msg in (reps.get("messages") or [])[1:]:
        if probe in at.strip_emoji(re.sub(r"[*_`]", "", msg.get("text") or "")):
            return True
    return False


def run(*, day: Optional[dt.date] = None, channel: str = CHANNEL,
        apply: bool = False) -> int:
    from automations.shared.slack_metrics_post import _client
    client = _client()
    me = client.auth_test().get("user_id") or ""
    day = day or dt.date.today()
    start = dt.datetime(day.year, day.month, day.day)
    oldest = str(int(start.timestamp()))

    msgs = (client.conversations_history(channel=channel, oldest=oldest,
                                         limit=200).get("messages") or [])
    msgs = [m for m in msgs
            if not m.get("thread_ts") or m.get("thread_ts") == m.get("ts")]
    msgs.sort(key=lambda m: float(m["ts"]))
    print("{} top-level post(s) on {} in {} — I am {}".format(
        len(msgs), day.isoformat(), channel, me))

    changed = skipped = foreign = 0
    for m in msgs:
        ts, text = m["ts"], m.get("text") or ""
        who = m.get("user") or m.get("bot_id") or "?"
        _clear_stray_pending(client, channel, m, me, apply=apply)
        new = rewrite(text)
        if not new:
            skipped += 1
            print("\n· {} — already one line, left alone".format(ts))
            continue
        if who != me:
            foreign += 1
            print("\n· {} — posted by {}, NOT mine: Slack won't let this token "
                  "edit it".format(ts, who))
            print("     would become: {}".format(new.splitlines()[0]))
            continue
        body, _ = _parts(text)
        keep = not _already_in_thread(client, channel, ts, body)
        print("\n· {} — rewrite{}".format(ts, "" if apply else " (dry run)"))
        print("   FROM: {}".format(text.replace("\n", " | ")[:160]))
        print("   TO:   {}".format(new.splitlines()[0]))
        print("   full text {} the thread".format(
            "→ copied into" if keep else "is already in"))
        if not apply:
            changed += 1
            continue
        try:
            if keep:
                client.chat_postMessage(
                    channel=channel, thread_ts=ts, unfurl_links=False,
                    unfurl_media=False,
                    text="_The original alert, kept here — the channel line "
                         "above is now the short version:_\n\n" + text)
            client.chat_update(channel=channel, ts=ts, text=new)
            changed += 1
        except Exception as e:  # noqa: BLE001 — one refusal must not stop the pass
            print("   ⚠ edit refused ({}: {})".format(type(e).__name__,
                                                      str(e)[:80]))
    print("\n{} rewritten{}, {} already fine, {} not editable by this "
          "token".format(changed, "" if apply else " (dry run — nothing sent)",
                         skipped, foreign))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--apply", action="store_true",
                    help="actually edit (default: dry run)")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else None
    return run(day=day, channel=a.channel, apply=a.apply)


if __name__ == "__main__":
    raise SystemExit(main())


def _clear_stray_pending(client, channel: str, m: dict, me: str, *,
                         apply: bool) -> None:
    """A RESOLVED parent must not still wear :pending: (Megan 2026-08-18: "it
    should only ever have 1 or the other"). The live fix is in
    incident_thread.mark_working; this clears the ones already standing. Only MY
    own reaction can come off — Slack has no removing someone else's."""
    mk = _MARK_RE.search(m.get("text") or "")
    if not mk or mk.group("state") != "resolved":
        return
    for rx in m.get("reactions") or []:
        if rx.get("name") == "pending" and me in (rx.get("users") or []):
            print("   stray :pending: on resolved {} — {}".format(
                m["ts"], "removing" if apply else "would remove (dry run)"))
            if apply:
                try:
                    client.reactions_remove(channel=channel, timestamp=m["ts"],
                                            name="pending")
                except Exception as e:  # noqa: BLE001
                    print("   ⚠ couldn't remove ({}: {})".format(
                        type(e).__name__, str(e)[:60]))
