"""One THREAD per problem: the first failure posts, every recurrence replies in
it, and the fix is announced in that same thread.

WHY THIS EXISTS (Eve 2026-08-14)
--------------------------------
#claudecorrections-and-requests had become unreadable. Every producer deduped
its alerts PER DAY — the day orchestrator via `failure_alerts_sent`, the
machine_digest watcher via `error_watch_<day>.json`, section_drop_alert via a
per-day dedup file. That is correct for one morning and wrong for a week: a
report that keeps failing (or a benign "no new emails today") opened a BRAND NEW
top-level message every single day, so the channel filled with near-identical
posts about ONE unfixed thing and the actual state of the morning had to be
reconstructed by scrolling. Eve: "es muy confuso y redundante … podemos
responder con un nuevo aviso de falla dentro del primer mensaje enviado? … y por
favor publicar dentro del mismo hilo cuando algo se resolvió".

So an alert is no longer a message, it's an INCIDENT:
  • first occurrence  → one top-level post (the channel gains ONE item)
  • same key again    → a reply in that post's thread ("Happened again — …")
  • fixed             → a reply in the SAME thread + the parent edited to ✅,
                        then the incident is CLOSED, so the next occurrence
                        opens a fresh post rather than reviving a stale one.

A threaded reply doesn't bump the channel for people who aren't following it, so
a problem on day 9 costs the channel nothing while still being on the record.

CROSS-MACHINE (the reason the marker lives in the message text)
--------------------------------------------------------------
These alerts are posted from Lucy 1, Lucy 2 and the mini. A local state file
can't be the source of truth, so — same trick as section_drop_alert's grouping —
each parent carries a visible marker line:

    _incident · failure-b2b_metrics · open 2026-08-14_

Any machine finds the open incident by scanning recent channel history for that
marker. The local index (output/state/incident_threads.json) is only a cache so
the common path costs no API call; losing it degrades to a channel scan, never
to a lost alert. Channel history is fetched at most ONCE per process and reused
for every lookup, so a sweep over 50 reports is still one API call.

LENGTH is delegated to `alert_thread` (the other half of this channel's cure,
2026-08-13): the parent keeps the headline and the first short facts, the rest —
always including any ``` block — goes in the thread, and every message is chunked
under Slack's 4000-char cap rather than truncated. An incident post must never
reintroduce the wall of text that made this channel unreadable in the first place.

FAILURE LADDER — every step is quieter than losing the alert:
  reply in the thread → post standalone → return None and let the caller do
  whatever it did before this module existed. Nothing here ever raises.

AGING OUT: an incident that has been open longer than MAX_AGE_DAYS, or has
collected more than MAX_FOLLOWUPS replies, is closed with a note and a fresh
post opens. A thread nobody can scroll to the bottom of is the problem this
module exists to prevent.

CLI:
    python -m automations.shared.incident_thread --list
    python -m automations.shared.incident_thread --resolve failure-b2b_metrics \
        --note "fixed by hand"
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]

CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests
# Same sidecar the orchestrator's notify.py writes when it resolves "#name" to a
# numeric id (kept in sync by hand on purpose — importing notify here would make
# a cycle, and this module must stay importable from anywhere).
CHANNEL_ID_CACHE = REPO_ROOT / "output" / ".corrections_channel_id"
STATE_PATH = REPO_ROOT / "output" / "state" / "incident_threads.json"

MAX_AGE_DAYS = 14                # older than this → close it and start fresh
MAX_FOLLOWUPS = 12               # more replies than this → same
_HISTORY_PAGES = 3               # 3 × 200 messages of lookback for the scan
_HISTORY_LIMIT = 200

# Keys are code-generated ids ("failure-b2b_metrics"), never free text: the
# marker is parsed back out of Slack, so a key with a space or a "·" in it would
# be unfindable. Reject it loudly at the door instead of alerting into a void.
_KEY_RE = re.compile(r"^[A-Za-z0-9_.:@/-]+$")
_MARK_RE = re.compile(
    r"_incident · (?P<key>[^ ·]+) · (?P<state>open|resolved) (?P<date>\d{4}-\d{2}-\d{2})_")

_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}

# One channel-history fetch per process, shared by every lookup (see docstring).
_HISTORY_CACHE: Dict[str, list] = {}


# ------------------------------------------------------------------ helpers ---

def marker(key: str, state: str = "open", day: Optional[dt.date] = None) -> str:
    return "_incident · {} · {} {}_".format(key, state,
                                            (day or dt.date.today()).isoformat())


def _ordinal(n: int) -> str:
    return _ORDINAL.get(n, f"{n}th")


def _human(day: dt.date) -> str:
    # No %-d / %#d: this runs on macOS AND Windows (CLAUDE.md).
    return "{} {}".format(day.strftime("%a %b"), day.day)


def _valid(key: str) -> bool:
    if key and _KEY_RE.match(key):
        return True
    print(f"  ⚠ incident key {key!r} is not marker-safe — alerting without a "
          "thread", flush=True)
    return False


def _load_index() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no index yet is the normal first run
        return {}


def _save_index(idx: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(idx, indent=2, sort_keys=True),
                              encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — the index is a cache, never critical
        print(f"  ⚠ incident index not saved: {type(e).__name__}: {e}", flush=True)


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _history(client, channel: str) -> list:
    """Recent channel messages, fetched at most once per process per channel."""
    if channel in _HISTORY_CACHE:
        return _HISTORY_CACHE[channel]
    msgs: list = []
    if channel.startswith("#"):
        # conversations_history needs an id, not a name. The first post resolves
        # and caches the id (see _post), so this only skips the very first run.
        _HISTORY_CACHE[channel] = msgs
        return msgs
    cursor = None
    try:
        for _ in range(_HISTORY_PAGES):
            kw = dict(channel=channel, limit=_HISTORY_LIMIT)
            if cursor:
                kw["cursor"] = cursor
            resp = client.conversations_history(**kw)
            msgs.extend(resp.get("messages") or [])
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:  # noqa: BLE001 — no history = open a new post, fine
        print(f"  ⚠ incident history scan failed ({type(e).__name__}: "
              f"{str(e)[:80]}) — treating as no open incident", flush=True)
    _HISTORY_CACHE[channel] = msgs
    return msgs


def _forget_history(channel: str) -> None:
    """Drop the cached history after we post, so a later lookup in the same
    process sees the incident we just opened."""
    _HISTORY_CACHE.pop(channel, None)


def _days_open(opened: str, day: dt.date) -> int:
    try:
        return (day - dt.date.fromisoformat(opened)).days
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------------ lookup ----

def find(key: str, *, channel: str = CHANNEL, client=None,
         day: Optional[dt.date] = None) -> Optional[dict]:
    """The OPEN incident for `key`, or None. Index first (no API call), then a
    channel scan so an incident opened on another machine is still found."""
    if not _valid(key):
        return None
    day = day or dt.date.today()
    ent = (_load_index() or {}).get(key)
    if isinstance(ent, dict) and ent.get("ts") and not ent.get("resolved"):
        return dict(ent, key=key, source="index")
    # A parent we CLOSED but couldn't edit still carries an "open" marker —
    # chat.update only works on your own messages, and these posts come from
    # three identities. Remember the ts so the scan below doesn't re-open the
    # thread we just resolved.
    closed_ts = (ent.get("ts") if isinstance(ent, dict) and ent.get("resolved")
                 else None)
    want = "_incident · {} · open ".format(key)
    try:
        client = client or _client()
    except Exception as e:  # noqa: BLE001 — no Slack client = caller posts fresh
        print(f"  ⚠ incident lookup: no Slack client ({type(e).__name__}: "
              f"{str(e)[:60]})", flush=True)
        return None
    for msg in _history(client, channel):
        text = msg.get("text") or ""
        if want not in text or msg.get("ts") == closed_ts:
            continue
        m = _MARK_RE.search(text)
        opened = m.group("date") if m else day.isoformat()
        return {"key": key, "ts": msg.get("ts"), "opened": opened,
                "count": int(msg.get("reply_count") or 0), "text": text,
                "channel": channel, "resolved": False, "source": "channel"}
    return None


def open_keys() -> List[str]:
    """Keys the local index still has OPEN — the cheap way for a caller to ask
    'is anything of mine outstanding?' without touching Slack."""
    return sorted(k for k, v in (_load_index() or {}).items()
                  if isinstance(v, dict) and v.get("ts") and not v.get("resolved"))


# ------------------------------------------------------------------ posting ---

def _post(client, channel: str, text: str, thread_ts: Optional[str] = None):
    kw = dict(channel=channel, text=text, unfurl_links=False, unfurl_media=False)
    if thread_ts:
        kw["thread_ts"] = thread_ts
    resp = client.chat_postMessage(**kw)
    cid = resp.get("channel")
    if cid and cid != channel:
        try:  # first post by "#name" — cache the numeric id for the scan
            CHANNEL_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
            CHANNEL_ID_CACHE.write_text(cid)
        except Exception:  # noqa: BLE001
            pass
    return resp.get("ts")


def _send(client, channel: str, lines: Sequence[str],
          thread_ts: Optional[str] = None):
    """Post `lines`, CHUNKED to stay under Slack's per-message limit.

    Every message this module sends goes through here. Slack hard-caps a message
    at 4000 chars and answers `msg_too_long` — a lost alert, which is the one
    outcome worse than a noisy channel. alert_thread.chunk splits on line
    boundaries and re-opens ``` fences across the split, so a paste-to-Claude
    block or a log tail survives being cut (Megan 2026-08-13)."""
    from automations.shared import alert_thread
    first = None
    for msg in alert_thread.chunk(list(lines)) or [""]:
        ts = _post(client, channel, msg, thread_ts=thread_ts)
        first = first or ts
    return first


def _remember(key: str, *, ts: str, channel: str, opened: str, count: int,
              text: str, resolved: bool = False) -> None:
    idx = _load_index()
    idx[key] = {"ts": ts, "channel": channel, "opened": opened,
                "last": dt.date.today().isoformat(), "count": count,
                "text": text, "resolved": resolved}
    _save_index(idx)


def open_or_followup(*, key: str, title: str, body: Sequence[str],
                     details: Optional[Sequence[str]] = None,
                     followup: Optional[Sequence[str]] = None,
                     channel: str = CHANNEL, day: Optional[dt.date] = None,
                     dry_run: bool = False, client=None,
                     max_age_days: int = MAX_AGE_DAYS,
                     max_followups: int = MAX_FOLLOWUPS) -> Optional[dict]:
    """Open a new incident post, or reply in the one that's already open.

      title     first line of the parent post
      body      the rest of the parent (the error, kept short — it's the channel)
      details   posted as a threaded reply ONLY when the incident is NEW (the
                re-run command, the paste-to-Claude block: unchanged from before)
      followup  what a RECURRENCE says in-thread; defaults to title + body. The
                recurrence stamp ("Happened again — Thu Aug 14 · 3rd time") is
                prepended here, so callers don't each invent their own wording.

    Returns {'ts', 'new', 'key', 'text', 'count'} — 'ts' is always the PARENT, so
    a caller can thread more under it and resolve() can find it later. None means
    nothing was posted and the caller should fall back to its old path.
    """
    if not _valid(key):
        return None
    day = day or dt.date.today()
    body = list(body or [])
    details = list(details or [])

    # LENGTH: the parent keeps the headline + the first short facts, anything
    # longer (and any ``` block) moves into the thread — the same rule
    # notify._post_corrections applies, so an incident post can't reintroduce
    # the wall-of-text this channel was just cured of. The marker is appended
    # AFTER the split on purpose: it has to stay on the PARENT or no other
    # machine can find the thread.
    from automations.shared import alert_thread
    head, overflow = alert_thread.split_for_thread([title] + body)
    parent_text = "\n".join(head + ["", marker(key, "open", day)])
    if overflow:
        details = list(overflow) + ([""] if details else []) + details

    if dry_run:
        ent = (_load_index() or {}).get(key) or {}
        again = bool(ent.get("ts") and not ent.get("resolved"))
        where = f"reply→{ent.get('ts')}" if again else "NEW POST"
        shown = "\n".join(followup or ([title] + body)) if again else parent_text
        print(f"[incident] DRY-RUN — {key} {where} → {channel}:\n{shown}\n",
              flush=True)
        if not again and details:
            print("[incident] DRY-RUN — thread detail:\n"
                  + "\n".join(details) + "\n", flush=True)
        return {"ts": ent.get("ts") or "dry-run-ts", "new": not again,
                "key": key, "text": parent_text, "count": ent.get("count", 0)}

    try:
        client = client or _client()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ incident post: no Slack client ({type(e).__name__}: "
              f"{str(e)[:60]})", flush=True)
        return None

    inc = find(key, channel=channel, client=client, day=day)

    # Age out a thread nobody can follow any more — close it, then fall through
    # to a fresh post so the channel gets a readable item again.
    if inc:
        n = int(inc.get("count") or 0)
        age = _days_open(inc.get("opened") or day.isoformat(), day)
        if age > max_age_days or n >= max_followups:
            try:
                _post(client, channel,
                      ":arrows_counterclockwise: *Still not fixed after {} day(s)"
                      "* — closing this thread and opening a fresh one so it's "
                      "readable. Same problem, new post.".format(age),
                      thread_ts=inc["ts"])
            except Exception:  # noqa: BLE001
                pass
            _mark_resolved_in_index(key)
            inc = None

    if inc:
        n = int(inc.get("count") or 0) + 1
        # n counts FOLLOW-UPS; the reader counts OCCURRENCES, and the parent post
        # is the first one — so the first reply is the 2nd time this happened.
        stamp = ":repeat: *Happened again* — {} · {} time".format(_human(day),
                                                                 _ordinal(n + 1))
        opened = inc.get("opened")
        if opened and opened != day.isoformat():
            try:
                stamp += " since {}".format(_human(dt.date.fromisoformat(opened)))
            except Exception:  # noqa: BLE001
                stamp += " since {}".format(opened)
        lines = [stamp] + list(followup or ([title] + body))
        try:
            _send(client, channel, lines, thread_ts=inc["ts"])
        except Exception as e:  # noqa: BLE001 — fall back to a standalone post
            print(f"  ⚠ incident follow-up failed ({type(e).__name__}: "
                  f"{str(e)[:80]}) — posting standalone", flush=True)
        else:
            _remember(key, ts=inc["ts"], channel=channel,
                      opened=opened or day.isoformat(), count=n,
                      text=inc.get("text") or parent_text)
            print(f"[incident] {key}: follow-up #{n} in thread {inc['ts']}",
                  flush=True)
            return {"ts": inc["ts"], "new": False, "key": key,
                    "text": inc.get("text") or parent_text, "count": n}

    try:
        ts = _post(client, channel, parent_text)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ incident post failed ({type(e).__name__}: {str(e)[:80]})",
              flush=True)
        return None
    if not ts:
        return None
    if details:
        try:
            _send(client, channel, details, thread_ts=ts)
        except Exception as e:  # noqa: BLE001 — parent landed; detail is a bonus
            print(f"  ⚠ incident detail reply failed ({type(e).__name__}: "
                  f"{str(e)[:80]})", flush=True)
    _remember(key, ts=ts, channel=channel, opened=day.isoformat(), count=0,
              text=parent_text)
    _forget_history(channel)
    print(f"[incident] {key}: opened {ts}", flush=True)
    return {"ts": ts, "new": True, "key": key, "text": parent_text, "count": 0}


def _mark_resolved_in_index(key: str) -> None:
    idx = _load_index()
    ent = idx.get(key)
    if isinstance(ent, dict):
        ent["resolved"] = True
        ent["last"] = dt.date.today().isoformat()
        _save_index(idx)


# ------------------------------------------------------------------ resolve ---

def resolve(*, key: str, lines: Sequence[str], channel: str = CHANNEL,
            parent_text: Optional[str] = None, day: Optional[dt.date] = None,
            dry_run: bool = False, client=None) -> bool:
    """Announce the fix IN THE INCIDENT'S OWN THREAD and close it.

    Eve 2026-08-14 asked for this explicitly: a resolution that only edited the
    parent (which is what the orchestrator did) is invisible to anyone who read
    the alert earlier — they keep working a problem that's already fixed. So the
    reply goes first (it's the part people see), and the parent edit to ✅ is
    best-effort on top: chat.update only works on your OWN messages, and these
    posts come from three different machines/identities.

    Closing matters as much as posting: once resolved, the NEXT occurrence opens
    a fresh top-level post instead of reviving a thread everyone stopped reading.
    Returns True when the thread was told. Never raises."""
    if not _valid(key):
        return False
    day = day or dt.date.today()
    if dry_run:
        ent = (_load_index() or {}).get(key) or {}
        print(f"[incident] DRY-RUN — would resolve {key} (ts {ent.get('ts')}) "
              f"→ {channel}:\n" + "\n".join(lines) + "\n", flush=True)
        return bool(ent.get("ts"))
    try:
        client = client or _client()
    except Exception:  # noqa: BLE001
        return False
    inc = find(key, channel=channel, client=client, day=day)
    if not inc or not inc.get("ts"):
        return False
    ts = inc["ts"]
    told = False
    try:
        _send(client, channel, lines, thread_ts=ts)
        told = True
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ incident resolve reply failed ({type(e).__name__}: "
              f"{str(e)[:80]})", flush=True)
    new_parent = parent_text
    if new_parent is None:
        was = inc.get("text") or ""
        new_parent = _MARK_RE.sub("", was).rstrip()
    new_parent = "{}\n\n{}".format(new_parent.rstrip(),
                                  marker(key, "resolved", day))
    try:
        client.chat_update(channel=channel, ts=ts, text=new_parent)
    except Exception as e:  # noqa: BLE001 — the thread reply already told people
        print(f"  ⚠ incident parent edit refused ({type(e).__name__}: "
              f"{str(e)[:60]}) — the in-thread note stands", flush=True)
    _mark_resolved_in_index(key)
    _forget_history(channel)
    print(f"[incident] {key}: resolved in thread {ts}", flush=True)
    return told


def close(key: str) -> None:
    """Forget an incident WITHOUT posting (e.g. it aged out of relevance)."""
    _mark_resolved_in_index(key)


# ---------------------------------------------------------------------- CLI ---

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Inspect / close corrections-channel "
                                             "incident threads.")
    ap.add_argument("--list", action="store_true", help="show open incidents")
    ap.add_argument("--resolve", metavar="KEY", help="close an incident and say "
                                                     "so in its thread")
    ap.add_argument("--note", default="", help="one line to add to --resolve")
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.resolve:
        lines = [":white_check_mark: *Resolved* — {}.".format(_human(dt.date.today()))]
        if a.note:
            lines.append(a.note)
        ok = resolve(key=a.resolve, lines=lines, channel=a.channel,
                     dry_run=a.dry_run)
        print("resolved" if ok else "no open incident for that key")
        return 0 if ok else 1
    idx = _load_index()
    rows = [(k, v) for k, v in sorted(idx.items())
            if isinstance(v, dict) and (a.list is False or not v.get("resolved"))]
    if not rows:
        print("no incidents recorded.")
        return 0
    for k, v in rows:
        print("{:<40} {:<12} opened {}  {} follow-up(s)  ts {}".format(
            k, "RESOLVED" if v.get("resolved") else "OPEN",
            v.get("opened", "?"), v.get("count", 0), v.get("ts", "?")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
