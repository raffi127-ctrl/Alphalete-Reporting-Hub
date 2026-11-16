"""Retract the Tier Bonus TEST posts Lucy sent to one person's DM, keeping one.

2026-11-16: the --post-to test ran for all 19 offices and filled Eve's DM; she
asked to keep only one. Keeps Raf's pair (his board image + the text message
right after it) -- or the first pair if Raf's never went out -- and deletes the
rest of TODAY's Tier Bonus test posts Lucy wrote there (chat.delete + the
uploaded file). Only Lucy's own messages that look like this test are touched.

  python -m automations.fiber_tier_bonus.cleanup_test_dm U088E2KJEV8           (preview)
  python -m automations.fiber_tier_bonus.cleanup_test_dm U088E2KJEV8 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
MARKS = ("Tier Bonus Breakdown", "Sales away from the next tier bonus")
KEEP_OWNER = "Rafael Hidalgo"


def _is_test(m) -> bool:
    text = m.get("text") or ""
    names = " ".join((f.get("title") or f.get("name") or "") for f in m.get("files") or [])
    return any(k in text or k in names for k in MARKS) or "tier_bonus_" in names


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("user")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    from automations.shared import slack_metrics_post as smp
    c = smp._client()
    me = c.auth_test()["user_id"]
    ch = c.conversations_open(users=a.user)["channel"]["id"]
    start = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    msgs, cursor = [], None
    while True:
        r = c.conversations_history(channel=ch, limit=200, cursor=cursor,
                                    oldest=str(start.timestamp()))
        msgs.extend(r.get("messages", []))
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    mine = sorted((m for m in msgs if m.get("user") == me and _is_test(m)),
                  key=lambda m: float(m["ts"]))
    print(f"DM {ch}: {len(msgs)} message(s) today, {len(mine)} are Lucy's Tier Bonus test posts")
    if not mine:
        return 0
    keep_i = next((i for i, m in enumerate(mine)
                   if m.get("files") and KEEP_OWNER in (m.get("text") or "")), 0)
    keep = {mine[keep_i]["ts"]}
    if keep_i + 1 < len(mine) and not mine[keep_i + 1].get("files"):
        keep.add(mine[keep_i + 1]["ts"])
    gone = 0
    for m in mine:
        first = ((m.get("text") or "").splitlines() or [""])[0][:70]
        if m["ts"] in keep:
            print(f"  KEEP   {m['ts']} {first}")
            continue
        print(f"  {'DELETE' if a.apply else 'would delete'} {m['ts']} {first}")
        if not a.apply:
            continue
        for f in m.get("files") or []:
            try:
                c.files_delete(file=f["id"])
            except Exception as e:  # noqa: BLE001
                print(f"    file {f.get('id')}: {e}")
        try:
            c.chat_delete(channel=ch, ts=m["ts"])
            gone += 1
        except Exception as e:  # noqa: BLE001
            print(f"    message: {e}")
    print(f"{'deleted' if a.apply else 'preview, nothing deleted'}: {gone if a.apply else len(mine) - len(keep)} message(s); kept {len(keep)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
