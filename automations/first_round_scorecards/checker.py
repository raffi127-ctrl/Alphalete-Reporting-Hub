"""Lucy's 1st round audit checker -- is every Zoom actually being audited?

Runs right after the day's 6 PM post (run.py) and looks for what silently
stops audits (Eve, 2026-10-22 -- ZOOM 8 recorded Jennifer's + Mercy's 1st
rounds for 2 weeks with no key, nobody noticed):

    no key      a Zoom in ZOOMS INFO that serves an office has no Fathom key
    bad key     Fathom rejects the key (401)
    not audited a recording today that never made it into the post
    gone        an office that had a Zoom slot yesterday and has none today
    quiet       a Zoom that serves an office, key fine, but Fathom recorded
                nothing on it for QUIET_WEEKDAYS weekdays (Megan, 2026-10-27 --
                Khalil's Zoom recorded nothing 9/15-10/26 with a working key:
                no 'no key', no 'bad key', so nobody heard)

Only what's NEW (or just fixed) is posted, as one thread in
#ars-recruiting-numbers that tags Camila -- an open problem isn't repeated
every day. A Zoom with no key in the sheet whose login still shows up under
another key (the creds file on the mini) is covered, so it's not flagged.

    python -m automations.first_round_scorecards.checker                     # dry-run: print
    python -m automations.first_round_scorecards.checker --preview-to-eve --post   # Eve's DM
    python -m automations.first_round_scorecards.checker --post              # LIVE: the channel
    ... --date 2026-10-22
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# run.py calls this after the live post only once Eve OKs the sample in her DM.
LIVE = True                         # Eve 10/22: sample OK, to the channel
CAMILA = "U07FWSYP3NV"              # Camila Hornos Kraschinsky
STATE = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards" / "checker.json"
SEEN_DAYS = 7                       # a login seen under any key this far back = covered
QUIET_WEEKDAYS = 2                  # nothing recorded on the last N weekdays = 'quiet'
_NO_OFFICE = {"", "LOST"}
# Offices whose 1st rounds aren't audited on purpose: never flagged.
# Joshua interviews on his own Zoom (Camila 10/21: not needed).
NOT_AUDITED = {"Joshua Ghorbani"}


def offices(z: Dict[str, str]) -> List[str]:
    """The owners a Zoom serves (morning, afternoon), blanks/LOST left out."""
    out = []
    for o in (z.get("morning", ""), z.get("afternoon", "")):
        o = " ".join(o.split())
        if o.upper() not in _NO_OFFICE and o not in NOT_AUDITED and o not in out:
            out.append(o)
    return out


def _label(z: Dict[str, str]) -> str:
    who = " / ".join(offices(z))
    return f"*{z.get('zoom') or 'a Zoom'}*" + (f" ({who})" if who else "")


def quiet_since(day: dt.date) -> dt.date:
    """The first of the last QUIET_WEEKDAYS weekdays up to `day` (Monday -> Friday)."""
    d, n = day, 0
    while True:
        if d.weekday() < 5:
            n += 1
            if n == QUIET_WEEKDAYS:
                return d
        d -= dt.timedelta(days=1)


def problems(accounts: Dict[str, Dict[str, str]], seen: Set[str], rejected: Set[str],
             missed: Dict[str, int], owners_before: Optional[List[str]],
             last: Optional[Dict[str, dt.date]] = None,
             day: Optional[dt.date] = None) -> Dict[str, str]:
    """{problem key: one line} from what was read.

    accounts       zooms.accounts() -- {login: {zoom, morning, afternoon, key}}
    seen           logins whose recordings some working key returned lately
    rejected       logins whose key Fathom refused
    missed         {owner: recordings today that the post left out}
    owners_before  the offices with a Zoom at the last check (None = first run)
    last, day      {login: newest recording date} and the day checked; a Zoom
                   with an office whose newest recording is older than the
                   last QUIET_WEEKDAYS weekdays is 'quiet' (None = not checked)
    """
    out: Dict[str, str] = {}
    for login, z in accounts.items():
        if not offices(z):
            continue
        if last is not None and day is not None and (login in seen or (z.get("key") and login not in rejected)):
            newest = last.get(login)
            if newest and newest < day - dt.timedelta(days=SEEN_DAYS):
                newest = None       # an odd old one Fathom hands back (a 2021 date, 10/27)
            if newest is None or newest < quiet_since(day):
                when = (f"since {newest:%a} {newest.month}/{newest.day}" if newest
                        else f"in the last {SEEN_DAYS} days")
                out[f"quiet:{login}"] = (f"{_label(z)}: the key works, but Fathom hasn't recorded "
                                         f"a single 1st round on it {when}. Is Fathom on and "
                                         "auto-recording every meeting, and are the interviews "
                                         "on this Zoom?")
        if login in seen:
            continue
        if not z.get("key"):
            out[f"nokey:{login}"] = (f"{_label(z)}: no Fathom API key in ZOOMS INFO, "
                                     "so its 1st rounds aren't audited.")
        elif login in rejected:
            out[f"badkey:{login}"] = (f"{_label(z)}: Fathom rejects the API key in ZOOMS INFO "
                                      "(wrong or old key), so its 1st rounds aren't audited.")
    for owner, n in sorted(missed.items()):
        if n:
            out[f"missed:{owner}"] = (f"*{owner}*: {n} recording(s) today that didn't get "
                                      "audited.")
    if owners_before is not None:
        now = {o for z in accounts.values() for o in offices(z)}
        for owner in sorted(set(owners_before) - now):
            out[f"gone:{owner}"] = (f"*{owner}*: had a Zoom in ZOOMS INFO until the last "
                                    "check and has none now. Still interviewing with ARS?")
    return out


def diff(found: Dict[str, str], before: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """new / still open / fixed, against the last check. 'missed' and 'gone'
    are about one day: they're news once and never reported as fixed."""
    one_day = ("missed:", "gone:")
    return {
        "new": {k: v for k, v in found.items() if k not in before},
        "open": {k: v for k, v in found.items() if k in before},
        "fixed": {k: v for k, v in before.items()
                  if k not in found and not k.startswith(one_day)},
    }


def texts(day: dt.date, d: Dict[str, Dict[str, str]], tag: bool = True):
    """(parent, reply) for the thread, or None when there's no news."""
    if not d["new"] and not d["fixed"]:
        return None
    bits = []
    if d["new"]:
        bits.append(f"{len(d['new'])} new problem{'s' if len(d['new']) != 1 else ''}")
    if d["fixed"]:
        bits.append(f"{len(d['fixed'])} fixed")
    parent = (f"🔎 *1st Round Audit Check — {day:%A, %b} {day.day}* · {', '.join(bits)}"
              + (f" <@{CAMILA}>" if tag and d["new"] else ""))
    lines = []
    for title, key, mark in (("New", "new", "⚠️"), ("Still open", "open", "•"),
                             ("Fixed", "fixed", "✅")):
        if d[key]:
            lines.append(f"*{title}:*")
            lines += [f"{mark} {v}" for v in d[key].values()]
            lines.append("")
    if d["new"]:
        lines.append("_API keys: Fathom → Settings → API Access, pasted in the Zoom's column "
                     "in ZOOMS INFO._")
        if any(k.startswith("quiet:") for k in d["new"]):
            lines.append("_Recording nothing: sign in to Fathom as that Zoom's login and set it to "
                         "auto-record every meeting, impromptu ones too._")
    return parent, "\n".join(lines).strip()


def _state() -> Dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(data: Dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def read_fathom(day: dt.date, keys: List[str]):
    """(logins seen in the last SEEN_DAYS under any key, rejected key tails,
    {login: its newest recording's date (CT)}). A recording counts for its
    recorder's login AND for 'key:<tail>' (a Zoom with no login in the sheet)."""
    from automations.first_round_scorecards import fathom
    start = dt.datetime.combine(day - dt.timedelta(days=SEEN_DAYS), dt.time(0), fathom.CT)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(6), fathom.CT)
    seen, rejected, last = set(), set(), {}
    for key in keys:
        cursor = None
        while True:
            p = {"created_after": start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "created_before": end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            if cursor:
                p["cursor"] = cursor
            try:
                page = fathom._get(key, p)
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise
                rejected.add(key[-12:])
                break
            for m in page.get("items") or []:
                email = ((m.get("recorded_by") or {}).get("email") or "").lower()
                seen.add(email or "key:" + key[-12:])
                began = m.get("recording_start_time") or m.get("created_at")
                if began:
                    d = fathom._utc(began).astimezone(fathom.CT).date()
                    for who in filter(None, (email, "key:" + key[-12:])):
                        last[who] = max(last.get(who, d), d)
            cursor = page.get("next_cursor")
            if not cursor:
                break
    return seen, rejected, last


def check(day: dt.date, missed: Optional[Dict[str, int]] = None):
    """(found, diff) -- reads ZOOMS INFO + Fathom, doesn't save or post."""
    from automations.first_round_scorecards import fathom, zooms
    acc = zooms.accounts()
    keys = list(dict.fromkeys(fathom._file_keys() + [z["key"] for z in acc.values() if z.get("key")]))
    seen, bad_tails, last = read_fathom(day, keys)
    rejected = {login for login, z in acc.items() if z.get("key") and z["key"][-12:] in bad_tails}
    st = _state()
    found = problems(acc, seen, rejected, missed or {}, st.get("owners"), last=last, day=day)
    return (found, diff(found, st.get("open") or {}),
            sorted({o for z in acc.values() for o in offices(z)}), acc, last)


def office_alerts(day: dt.date, d: Dict[str, Dict[str, str]], acc: Dict[str, Dict[str, str]],
                  last: Dict[str, dt.date]) -> List[tuple]:
    """Megan, 2026-10-27: a 'quiet' Zoom also goes to the recruiting channel of
    the office it serves, where the interviewers are. [(problem key, channel,
    parent, reply)] for each NEW quiet Zoom x office channel (title-only
    parent, detail in the thread). An office with no channel in
    office_post.CHANNELS is left to Camila's thread."""
    from automations.first_round_scorecards import office_post
    out = []
    for key in d["new"]:
        if not key.startswith("quiet:"):
            continue
        login = key.split(":", 1)[1]
        z = acc.get(login) or {}
        newest = last.get(login)
        if newest and newest < day - dt.timedelta(days=SEEN_DAYS):
            newest = None
        when = (f"since {newest:%a} {newest.month}/{newest.day}" if newest
                else f"in the last {SEEN_DAYS} days")
        zoom = z.get("zoom") or "this office's Zoom"
        acct = f" ({login})" if "@" in login else ""
        channels = {}
        for o in offices(z):
            ch = office_post.CHANNELS.get(office_post.office_name(o)) or office_post.CHANNELS.get(o)
            if ch:
                channels.setdefault(ch, o)
        for ch in channels:
            parent = f"⚠️ *1st Rounds not being recorded — {zoom}*"
            reply = (f"<@{CAMILA}> Fathom hasn't recorded a single 1st round on *{zoom}*{acct} {when}, so "
                     "none of this office's interviews are being scored.\n\n"
                     "To fix:\n"
                     f"• Run every 1st round on {zoom}\n"
                     "• Make sure Fathom on that Zoom auto-records every meeting, impromptu "
                     "ones too")
            out.append((key, ch, parent, reply))
    return out


def post_office_alerts(client, day: dt.date, d: Dict, acc: Dict, last: Dict,
                       threads: Dict[str, List[str]], preview_channel: str = "") -> Dict[str, List[str]]:
    """Post the new quiet alerts in the office channels, and a ✅ in the same
    thread when one is fixed. Returns the threads still open {key|channel: [channel, ts]}."""
    threads = dict(threads)
    for key, ch, parent, reply in office_alerts(day, d, acc, last):
        where = preview_channel or ch
        try:
            ts = client.chat_postMessage(channel=where, text=parent)["ts"]
            client.chat_postMessage(channel=where, thread_ts=ts, text=reply)
            print(f"office alert: {key} -> {where}")
            if not preview_channel:
                threads[f"{key}|{ch}"] = [ch, ts]
        except Exception as exc:  # noqa: BLE001
            print(f"office alert FAILED {key} -> {where}: {type(exc).__name__}: {exc}")
    for tkey, (ch, ts) in list(threads.items()):
        if tkey.split("|")[0] in d["fixed"]:
            if not preview_channel:
                try:
                    client.chat_postMessage(channel=ch, thread_ts=ts,
                                            text="✅ Recording again — 1st rounds are being scored.")
                    print(f"office alert fixed: {tkey}")
                except Exception as exc:  # noqa: BLE001
                    print(f"office alert ✅ FAILED {tkey}: {type(exc).__name__}: {exc}")
            threads.pop(tkey)
    return threads


def run(day: dt.date, *, post: bool, preview: bool, missed: Optional[Dict[str, int]] = None) -> int:
    found, d, owners, acc, last = check(day, missed)
    got = texts(day, d, tag=not preview)
    for k in ("new", "open", "fixed"):
        for v in d[k].values():
            print(f"[{k}] {v}")
    threads = _state().get("office_threads") or {}
    for key, ch, parent, reply in office_alerts(day, d, acc, last):
        print(f"[office] {ch}: {parent}\n  ↳ {reply}")
    if post:
        from automations.shared import slack_metrics_post as smp
        from automations.first_round_scorecards import run as r
        oc = smp._client()
        threads = post_office_alerts(oc, day, d, acc, last, threads,
                                     preview_channel=r._dm_channel(oc) if preview else "")
    if not got:
        print("no news -- nothing to post")
    elif post:
        from automations.shared import slack_metrics_post as smp
        from automations.first_round_scorecards import run as r
        client = smp._client()
        channel = r._dm_channel(client) if preview else r.CHANNEL_ID
        parent = client.chat_postMessage(channel=channel, text=got[0])
        client.chat_postMessage(channel=channel, thread_ts=parent["ts"], text=got[1])
        print(f"posted to {'Eve DM' if preview else '#ars-recruiting-numbers'}")
    else:
        print("DRY-RUN -- would post:\n" + got[0] + "\n---\n" + got[1])
    if post and not preview:     # only a real post moves the 'already told' line
        _save({"open": {k: v for k, v in found.items() if not k.startswith(("missed:", "gone:"))},
               "owners": owners, "checked": day.isoformat(), "office_threads": threads})
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.checker")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    ap.add_argument("--preview-to-eve", action="store_true", help="post in Eve's DM, no tag")
    a = ap.parse_args(argv)
    from automations.first_round_scorecards import fathom
    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.datetime.now(dt.timezone.utc).astimezone(fathom.CT).date())
    return run(day, post=a.post, preview=a.preview_to_eve)


if __name__ == "__main__":
    sys.exit(main())
