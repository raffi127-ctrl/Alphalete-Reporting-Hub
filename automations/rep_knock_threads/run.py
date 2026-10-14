"""Rep Knock Threads — GPS red-flag threads in #alphalete-sales-knocking-data.

Raf (Loom, 2026-10-14) asked for each rep's OwnerVille knocking data in a
thread, hourly, to catch knocks logged away from the door. Megan narrowed it
the same day:
  * ONLY reps whose GPS failures TODAY reach config.FLAG_FAIL_PCT (25%) are
    posted. The parent is the rep's name only; the chart goes in the thread.
  * A STREAK of days over the line puts that many 🚩 after the name.
  * The roster RESETS DAILY: the first tick of a new day deletes the previous
    day's posts (Lucy's own messages only) and starts a fresh list.
  * The chart: today on top, ongoing vitals (week so far, Mon–Sun) at the bottom.

Each tick (hourly, 10 AM–9 PM CT):
  1. Reset: clear any earlier day's threads still up.
  2. Pull Raf's office knocks (finished days cached; only today is re-pulled).
  3. Every rep over the line today gets a parent "Name 🚩🚩" the first time,
     then a fresh chart in that thread whenever their door count changed.
     New GPS failures get a 🚩 line on the reply.

DRY-RUN BY DEFAULT — renders to output/rep_knock_threads/preview/, posts and
deletes nothing. --send does both.

    python -m automations.rep_knock_threads.run                 # dry-run
    python -m automations.rep_knock_threads.run --rep "Shelja"  # dry-run, one rep
    python -m automations.rep_knock_threads.run --send          # live tick
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from zoneinfo import ZoneInfo

from automations.rep_knock_threads import config as C
from automations.rep_knock_threads import pull as P
from automations.rep_knock_threads import render as R
from automations.rep_knock_threads import stats as S


def now_local() -> dt.datetime:
    return dt.datetime.now(ZoneInfo(C.TZ)).replace(tzinfo=None)


def in_window(t: dt.datetime) -> bool:
    return C.FIRST_HOUR <= t.hour <= C.LAST_HOUR


# ── state ────────────────────────────────────────────────────────────────
# {"days": {"2026-10-14": {"cleared": false, "reps": {rep_id: {...}}}},
#  "last_hour": "2026-10-14T15"}
def load_state() -> dict:
    try:
        st = json.loads(C.STATE_PATH.read_text())
    except Exception:
        st = {}
    st.setdefault("days", {})
    return st


def save_state(state: dict) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = C.STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(C.STATE_PATH)


def day_state(state: dict, day: dt.date) -> dict:
    return state["days"].setdefault(day.isoformat(), {"cleared": False, "reps": {}})


# ── slack ────────────────────────────────────────────────────────────────
def parent_text(rep: str, streak: int) -> str:
    return f"*{rep}* {S.flags(streak)}".rstrip()


def reply_text(s: dict, as_of: dt.datetime, alert: str) -> str:
    t = s["today"]
    line = (f"{R._hm(as_of)} update — GPS failed on {t['gps_fail']} of "
            f"{t['knocks']} doors today ({R._pct(t['gps_fail_pct'])})")
    return f"{line}\n{alert}" if alert else line


def _client():
    from automations.shared.slack_metrics_post import _client as lucy
    return lucy()


def check_channel(client) -> None:
    info = client.conversations_info(channel=C.CHANNEL_ID)
    ch = info.get("channel") or {}
    if not ch.get("is_member", True):
        raise RuntimeError(f"Lucy is not a member of {C.CHANNEL_NAME} — "
                           "add her to the channel first")


def post_parent(client, text: str) -> str:
    r = client.chat_postMessage(channel=C.CHANNEL_ID, text=text,
                                unfurl_links=False, unfurl_media=False)
    if not r.get("ok") or not r.get("ts"):
        raise RuntimeError(f"parent post failed: {r.get('error')}")
    return r["ts"]


def post_card(client, thread_ts: str, png, comment: str) -> bool:
    from automations.shared.slack_metrics_post import (
        _uploaded_file_id, wait_for_share)
    r = client.files_upload_v2(channel=C.CHANNEL_ID, thread_ts=thread_ts,
                               file=str(png), filename=png.name,
                               initial_comment=comment)
    if not r.get("ok"):
        return False
    fid = _uploaded_file_id(r)
    # GREEN MEANS DELIVERED: an accepted upload is not a landed image.
    return bool(wait_for_share(client, C.CHANNEL_ID, thread_ts, fid or "",
                               text=comment))


def clear_thread(client, thread_ts: str, my_uid: str) -> bool:
    """Delete LUCY'S OWN messages in one thread (replies + their images, then
    the parent). Anyone else's reply is left alone. True when nothing of
    Lucy's is left."""
    try:
        msgs = client.conversations_replies(channel=C.CHANNEL_ID, ts=thread_ts,
                                            limit=200).get("messages") or []
    except Exception as e:
        if "thread_not_found" in str(e) or "message_not_found" in str(e):
            return True                       # already gone
        print(f"  ⚠ couldn't read thread {thread_ts}: {e}")
        return False
    ok = True
    # Replies first, parent last, so a half-finished clear never strands
    # Lucy's images under a deleted parent.
    for m in sorted(msgs, key=lambda m: m.get("ts") == thread_ts):
        if m.get("user") != my_uid:
            continue
        try:
            for f in m.get("files") or []:
                if f.get("id"):
                    client.files_delete(file=f["id"])
            if m.get("ts") and not m.get("subtype") == "tombstone":
                try:
                    client.chat_delete(channel=C.CHANNEL_ID, ts=m["ts"])
                except Exception as e:
                    if "message_not_found" not in str(e):
                        raise
        except Exception as e:
            ok = False
            print(f"  ⚠ couldn't delete {m.get('ts')}: {e}")
        time.sleep(0.6)
    return ok


def reset_old_days(client, state: dict, today: dt.date, *, send: bool) -> None:
    """Daily reset: every earlier day's threads come down."""
    my_uid = client.auth_test()["user_id"] if send else ""
    for key in sorted(state["days"]):
        if key >= today.isoformat():
            continue
        ds = state["days"][key]
        if ds.get("cleared"):
            continue
        threads = [(r.get("rep", rid), r["thread_ts"])
                   for rid, r in ds.get("reps", {}).items() if r.get("thread_ts")]
        if not send:
            print(f"  [dry-run] reset: would delete {len(threads)} thread(s) from {key}")
            continue
        all_ok = True
        for rep, ts in threads:
            all_ok = clear_thread(client, ts, my_uid) and all_ok
        ds["cleared"] = all_ok
        save_state(state)
        print(f"[rep_knocks] reset {key}: {len(threads)} thread(s) "
              + ("deleted" if all_ok else "PARTLY deleted — retrying next tick"))
    # Forget cleared days older than a week.
    for key in [k for k, v in state["days"].items()
                if v.get("cleared") and k < (today - dt.timedelta(days=7)).isoformat()]:
        state["days"].pop(key, None)


# ── main ─────────────────────────────────────────────────────────────────
def _match(rep_filter: str, s: dict) -> bool:
    if not rep_filter:
        return True
    f = rep_filter.strip().lower()
    return f == s["rep_id"] or f in s["rep"].lower()


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true",
                    help="post + do the daily reset (default: dry-run)")
    ap.add_argument("--rep", default="", help="only this rep (name piece or OwnerVille id)")
    ap.add_argument("--date", help="as-of day YYYY-MM-DD (dry-run only)")
    ap.add_argument("--force", action="store_true",
                    help="ignore the posting hours and re-post even if nothing changed")
    ap.add_argument("--tick", action="store_true",
                    help="LaunchAgent mode: post at most once per clock hour")
    ap.add_argument("--headless", action="store_true")
    a = ap.parse_args(argv)

    if a.date and a.send:
        print("[rep_knocks] --date is for previews only; it never posts or deletes")
        return 2
    as_of = now_local()
    today = dt.date.fromisoformat(a.date) if a.date else as_of.date()
    if a.date:
        as_of = dt.datetime.combine(today, dt.time(C.LAST_HOUR, 0))
    elif not a.force and not in_window(as_of):
        print(f"[rep_knocks] {as_of:%H:%M} CT is outside "
              f"{C.FIRST_HOUR}:00–{C.LAST_HOUR}:00 — nothing to do")
        return 0
    hour_key = f"{as_of:%Y-%m-%dT%H}"
    state = load_state()
    if a.tick and a.send and state.get("last_hour") == hour_key:
        return 0          # this hour already went out; the agent ticks every 10 min
    mode = "SEND" if a.send else "DRY-RUN"
    print(f"[rep_knocks] {mode} as of {as_of:%Y-%m-%d %H:%M} CT → {C.CHANNEL_NAME}")

    client = _client() if a.send else None
    if client:
        check_channel(client)
    reset_old_days(client, state, today, send=a.send)

    week = [d for d in S.week_days(today) if d <= today]
    back = [today - dt.timedelta(days=i) for i in range(C.STREAK_LOOKBACK_DAYS)]
    days = sorted(set(week) | set(back))
    by_day = P.pull_days(days, today, headless=a.headless)
    week_knocks = [r for d in week for r in by_day.get(d, [])]
    today_reps = {r["rep_id"] for r in by_day.get(today, [])}

    try:
        from automations.shared import terminated_icds as ti
        ti.alert_terminated(sorted({r["rep"] for r in by_day.get(today, [])}),
                            report_label=C.REPORT_NAME)
    except Exception as e:
        print(f"[rep_knocks] (terminated check skipped: {e})")

    ds = day_state(state, today)
    preview = C.OUT_DIR / "preview" / f"{today.isoformat()}_{as_of:%H%M}"
    posted = skipped = failed = 0
    over = []
    reps = S.group_by_rep(week_knocks)
    for rep_id in sorted(today_reps, key=lambda i: reps[i][0]["rep"].lower()):
        s = S.rep_week(reps[rep_id], today)
        if not _match(a.rep, s):
            continue
        rs = ds["reps"].get(rep_id)
        # Only reps over the line today. Once a rep's thread is up today it
        # keeps updating for the rest of the day, even if they dip under.
        if not s["flagged"] and not (rs and rs.get("thread_ts")):
            continue
        s["streak"] = S.streak(rep_id, by_day, today)
        over.append(f"{s['rep']} {R._pct(s['today']['gps_fail_pct'])} "
                    f"{S.flags(s['streak'])}".rstrip())
        rs = ds["reps"].setdefault(rep_id, {"rep": s["rep"]})
        if not a.force and rs.get("posted_count") == s["today"]["knocks"]:
            skipped += 1
            continue

        seen = set(rs.get("seen_fail_ids", []))
        fresh = S.new_failures(s["today_rows"], seen)
        alert = S.alert_line(fresh)
        png = R.render(s, as_of=as_of, out=preview / f"{_slug(s['rep'])}_{rep_id}.png")
        comment = reply_text(s, as_of, alert)

        if not a.send:
            print(f"  [dry-run] {parent_text(s['rep'], s['streak'])}  → {png.name}\n"
                  f"            {comment.replace(chr(10), ' | ')}")
            posted += 1
            continue

        try:
            if not rs.get("thread_ts"):
                rs["thread_ts"] = post_parent(client, parent_text(s["rep"], s["streak"]))
                save_state(state)
            ok = post_card(client, rs["thread_ts"], png, comment)
        except Exception as e:
            ok = False
            print(f"  ✗ {s['rep']}: {e}")
        if ok:
            posted += 1
            rs["posted_count"] = s["today"]["knocks"]
            rs["seen_fail_ids"] = sorted(seen | {str(r["knock_id"]) for r in fresh})
            save_state(state)
            print(f"  ✓ {parent_text(s['rep'], s['streak'])}: {comment.splitlines()[0]}")
        else:
            failed += 1
            print(f"  ✗ {s['rep']}: chart did not land in the thread")
        time.sleep(C.UPLOAD_PAUSE_S)

    if a.send and a.tick and not failed:
        state["last_hour"] = hour_key
    if a.send:
        save_state(state)
    print(f"[rep_knocks] over {C.FLAG_FAIL_PCT:.0f}% GPS failed today: "
          + (", ".join(over) if over else "nobody"))
    tag = "DRY-RUN " if not a.send else ""
    print(f"[rep_knocks] {tag}posted={posted} skipped={skipped} failed={failed}")
    if not a.send and posted:
        print(f"[rep_knocks] previews: {preview}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
