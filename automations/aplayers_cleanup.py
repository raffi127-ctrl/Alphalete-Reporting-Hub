"""Delete Lucy's report threads from #a-players-b2b (Carlos 2026-10-28).

Carlos, after stopping every scheduled A-Players post: "in the Aplayers
slack delete the box metrics thread and all its screen shots the last two
weeks. do the same for the verizon metrics thread, Tableau country trackers
thread and all the posts inside of it / Customers who didn't receive a
wrap-up text thread and everything inside of it / Knocks and dispositions
threads and everything inside of it."

Scans the room's history for the window, matches PARENT posts by title,
deletes every reply in the thread (newest first) and then the parent.
chat_delete only works on Lucy's own messages, so anything a human wrote
in those threads survives with an error logged, never silently.

DRY RUN by default — prints every thread it would delete with its reply
count. --live deletes. --days widens the window (default 15).

    lucy rerun aplayers_cleanup                 # preview
    lucy rerun aplayers_cleanup --live          # delete
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

CHANNEL = "C0AJQA8P716"            # #a-players-b2b
PATTERNS = (
    "box metrics",
    "verizon metrics",
    "country tracker",
    "wrap up text",
    "wrap-up text",
    "knocks and dispositions",
)


def _matches(text: str) -> str | None:
    low = (text or "").lower()
    for p in PATTERNS:
        if p in low:
            return p
    return None


def _is_gone(parent_msg) -> bool:
    """A deleted parent shows up as a tombstone (or not at all)."""
    if not parent_msg:
        return True
    return (parent_msg.get("subtype") == "tombstone"
            or (parent_msg.get("text") or "") == "This message was deleted.")


def orphan_sweep(client, days: int, live: bool) -> None:
    """Threads whose PARENT Carlos deleted by hand still hold Lucy's
    screenshots (2026-10-28: "look for some threads where i deleted the
    begining of it but the post are still there"). History never shows
    those replies, but files.list shows the uploads — walk Lucy's files
    in the room, group by thread, and clear the threads whose parent is
    a tombstone."""
    import collections
    oldest = int((dt.datetime.now() - dt.timedelta(days=days)).timestamp())
    threads = collections.defaultdict(set)
    # files.list's channel filter returns nothing for this private room —
    # list LUCY's uploads instead and match the room from each file's
    # shares (seen 2026-10-28: channel-filtered call came back empty).
    me = client.auth_test().get("user_id")
    page = 1
    total = 0
    while True:
        resp = client.files_list(user=me, ts_from=str(oldest),
                                 count=100, page=page)
        total += len(resp.get("files", []))
        for f in resp.get("files", []):
            for shares in (f.get("shares") or {}).values():
                for ch, posts in shares.items():
                    if ch != CHANNEL:
                        continue
                    for pmeta in posts:
                        tts = pmeta.get("thread_ts")
                        if tts:
                            threads[tts].add(pmeta.get("ts"))
        paging = resp.get("paging") or {}
        if page >= int(paging.get("pages") or 1):
            break
        page += 1
        time.sleep(1)
    print(f"[orphans] {total} file(s) by Lucy in the window; "
          f"{len(threads)} thread(s) of them in this room")
    deleted = failed = orphaned = 0
    for tts in sorted(threads):
        try:
            msgs = client.conversations_replies(
                channel=CHANNEL, ts=tts, limit=200).get("messages", [])
        except Exception as e:  # noqa: BLE001
            if "thread_not_found" in str(e):
                msgs = []
            else:
                print(f"  ! couldn't list {tts}: {str(e)[:100]}")
                continue
        parent = next((m for m in msgs if m.get("ts") == tts), None)
        if not _is_gone(parent):
            continue
        orphaned += 1
        when = dt.datetime.fromtimestamp(float(tts))
        kill = [m for m in msgs if m.get("ts") != tts]
        print(f"  [orphan] {when:%m/%d %H:%M} parent gone — "
              f"{len(kill)} leftover msg(s)")
        if not live:
            continue
        for m in sorted(kill, key=lambda m: m.get("ts", ""), reverse=True):
            try:
                client.chat_delete(channel=CHANNEL, ts=m["ts"])
                deleted += 1
            except Exception as e:  # noqa: BLE001
                if "message_not_found" not in str(e):
                    print(f"    ✗ {m['ts']}: {str(e)[:90]}")
                    failed += 1
            time.sleep(1.1)
    print(f"[orphans] {orphaned} orphaned thread(s); "
          + (f"deleted {deleted}, {failed} failure(s)" if live
             else "dry run — add --live to delete"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aplayers_cleanup")
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--live", action="store_true",
                    help="actually delete (default: preview only)")
    ap.add_argument("--orphans", action="store_true",
                    help="sweep threads whose parent was deleted by hand")
    a = ap.parse_args(argv)
    from automations.shared.slack_metrics_post import _client
    client = _client()
    if a.orphans:
        orphan_sweep(client, a.days, a.live)
        print("=== done ===", flush=True)
        return 0
    oldest = (dt.datetime.now() - dt.timedelta(days=a.days)).timestamp()

    parents, cursor = [], None
    while True:
        kw = {"cursor": cursor} if cursor else {}
        resp = client.conversations_history(channel=CHANNEL, limit=200,
                                            oldest=str(oldest), **kw)
        for m in resp.get("messages", []):
            hit = _matches(m.get("text", ""))
            if hit:
                parents.append((m, hit))
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(1)

    print(f"[cleanup] {len(parents)} matching parent(s) in the last "
          f"{a.days} day(s)")
    deleted = failed = 0
    for m, hit in sorted(parents, key=lambda x: x[0]["ts"]):
        when = dt.datetime.fromtimestamp(float(m["ts"]))
        try:
            replies = client.conversations_replies(
                channel=CHANNEL, ts=m["ts"], limit=200).get("messages", [])
        except Exception as e:  # noqa: BLE001
            print(f"  ! couldn't list {m['ts']}: {str(e)[:100]}")
            replies = [m]
        print(f"  [{hit}] {when:%m/%d %H:%M} "
              f"{(m.get('text') or '')[:50]!r} — {len(replies)} msg(s)")
        if not a.live:
            continue
        for r in sorted(replies, key=lambda r: r.get("ts", ""),
                        reverse=True):
            try:
                client.chat_delete(channel=CHANNEL, ts=r["ts"])
                deleted += 1
            except Exception as e:  # noqa: BLE001
                err = str(e)
                if "message_not_found" not in err:
                    print(f"    ✗ {r['ts']}: {err[:90]}")
                    failed += 1
            time.sleep(1.1)        # chat.delete rate limit
    print(f"[cleanup] {'deleted' if a.live else 'WOULD delete'} "
          f"{deleted if a.live else sum(1 for _ in parents)} — "
          f"{failed} failure(s)" if a.live else
          f"[cleanup] dry run — add --live to delete")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
