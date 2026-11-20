"""One-off (Eve 2026-11-20): today's Metrics threads go back to "only the
fiber image" (Raf: "one pic in the metrics thread with the fiber scheduled
orders for the day, then a different thread with the same fiber orders + the
pending wireless").

For every '*Metrics for: <today>' header THIS token's user (Lucy) posted today
in the D2D metrics channels + mirrors:
  1. the index goes back to the single ':calendar: Activations Scheduled
     Today' line (undoes the earlier one-off, if it ran);
  2. the '⏳ Pending Orders (fiber + pending wireless) — … → open' pointer line
     is deleted (in the thread, or top-level in a mirror).
The Pending Orders posts themselves are NOT touched.

    python -m automations.activations_today.fix_index            # dry run
    python -m automations.activations_today.fix_index --live     # edit
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from automations.activations_today import pull

ORIGINAL = ":calendar: Activations Scheduled Today\n"
ADDED = (":calendar: Activations Scheduled Today (fiber only)\n"
         ":hourglass_flowing_sand: Pending Orders (fiber + wireless, by rep)\n")
POINTER = "Pending Orders (fiber + pending wireless) —"
_CH = re.compile(r"\bC0[A-Z0-9]{7,10}\b")


def channels() -> list:
    """Every channel id named in the office list, its onboarded file and the
    mirror table — a wide net on purpose: only Lucy's own posts get touched."""
    from automations.office_metrics import offices as om
    from automations.shared import slack_metrics_post as smp
    found = []
    srcs = [Path(om.__file__).read_text(encoding="utf-8")]
    onb = Path(om.__file__).with_name("onboarded_offices.json")
    if onb.exists():
        srcs.append(onb.read_text(encoding="utf-8"))
    srcs.append(json.dumps(smp.MIRROR_CHANNELS))
    srcs.append(smp.CHANNEL_ID)
    for s in srcs:
        for c in _CH.findall(s):
            if c not in found:
                found.append(c)
    return found


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "{}th".format(n)
    return "{}{}".format(n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def is_pointer(text: str) -> bool:
    return POINTER in (text or "") and "*Pending Orders" not in (text or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fix_index")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    me = client.auth_test()["user_id"]
    day = pull.central_today()
    first = "Metrics for: {} {} {}".format(day.strftime("%B"), _ordinal(day.day), day.year)
    start = dt.datetime.combine(day, dt.time.min, tzinfo=pull.CENTRAL).timestamp()
    chans = channels()
    print("token user {} — '{}' in {} channels".format(me, first, len(chans)))
    verb = "" if args.live else "would "
    n_head = n_del = 0
    for ch in chans:
        try:
            msgs = client.conversations_history(channel=ch, oldest=str(start),
                                                limit=200).get("messages") or []
        except Exception as e:  # noqa: BLE001 — not a member / other workspace
            print("  {}: can't read ({})".format(ch, str(e)[:80]))
            continue
        doomed = [m for m in msgs if m.get("user") == me and is_pointer(m.get("text"))]
        for m in msgs:
            text = m.get("text") or ""
            if first not in text.split("\n", 1)[0] or m.get("user") != me:
                continue
            if ADDED in text + "\n":
                print("  {} {}: {}restore index".format(ch, m["ts"], verb))
                if args.live:
                    client.chat_update(channel=ch, ts=m["ts"],
                                       text=(text + "\n").replace(ADDED, ORIGINAL, 1).rstrip("\n"))
                n_head += 1
            if m.get("reply_count"):
                reps = client.conversations_replies(channel=ch, ts=m["ts"],
                                                    limit=500).get("messages") or []
                doomed += [r for r in reps if r.get("user") == me
                           and r.get("ts") != m["ts"] and is_pointer(r.get("text"))]
        for r in doomed:
            print("  {} {}: {}delete pointer: {}".format(ch, r["ts"], verb, (r.get("text") or "")[:90]))
            if args.live:
                client.chat_delete(channel=ch, ts=r["ts"])
            n_del += 1
    print("done: {} index(es) {}restored, {} pointer line(s) {}deleted".format(
        n_head, verb, n_del, verb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
