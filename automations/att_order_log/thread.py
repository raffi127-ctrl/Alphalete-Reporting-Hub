"""The B2B Metrics thread for Carlos — assemble, report, DO NOT POST.

Carlos's original ask (Slack, 2026-07-19): "This will run on Lucy 2 and post to
carlos' slack channel in this thread. We would rename the header thread
'B2B Metrics MM/DD/YYYY' with the logs then in the response to the thread."

Contents, from Megan's list plus the Loom items she asked me to fold in:

    B2B Metrics 07/20/2026
      📦 BOX Order Log
      💵 Accepted by supplier — last week & this week
      📋 AT&T B2B Order Log
      🌐 New Internet Churn
      📊 Wireless Churn
      🔁 Ongoing Cancel          (Loom 2:21, not on Megan's list)
      📸 Tableau Metrics

POSTING IS NOT WIRED, and that is deliberate rather than unfinished. Megan has a
standing rule that nothing goes out to Slack without her say-so, and this posts
into someone else's channel. `plan()` reports exactly what WOULD be sent and
which artifacts are missing; turning it on is a separate, reviewable change that
adds a poster and a channel id — not a flag flip on a module that already has
the ability.

WHY A READINESS REPORT RATHER THAN A POSTER. Seven artifacts are produced by six
different modules on two machines. The failure that matters is a thread that
posts five of seven and looks complete, so the useful thing to build first is
the check that says which are present, how old they are, and what is missing.

RUN IT ON LUCY 2. Every artifact is written to that machine's output/ by the
module that produced it, so a run on the laptop truthfully reports 0/7 — the
files are simply elsewhere. That is not a bug in the check, but it does mean
the check is only meaningful where the work happens.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "output"

# Carlos's wording, kept verbatim. Megan's note wrote the header as "Metrics
# for: July 19th 2026"; Carlos asked for "B2B Metrics MM/DD/YYYY" and he is the
# one reading it, so his form wins unless she says otherwise. One constant to
# change if she does.
HEADER_FMT = "B2B Metrics {:%m/%d/%Y}"

# Channel is INTENTIONALLY unset. box_order_log posts Carlos's BOX thread to
# #alphalete-gp-sales (C07J46MQNUX), which is the likely target, but "carlos'
# slack channel in this thread" is not the same claim as "that channel", and a
# standing rule says resolve every recipient before sending. Left None so the
# dry run cannot quietly acquire a destination.
CHANNEL_ID: Optional[str] = None
CHANNEL_NAME = "(unset — confirm with Megan)"


def _newest(patterns: List[str], root: Path = OUTPUT) -> Optional[Path]:
    """Most recently modified file matching any glob, or None."""
    hits: List[Path] = []
    for pat in patterns:
        hits.extend(root.glob(pat))
    hits = [p for p in hits if p.is_file()]
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_mtime)


# One row per thread reply, in the order Carlos reads them. `find` returns the
# artifact or None; `note` explains what produces it, so a missing item points
# at the module to run rather than just saying "absent".
ITEMS = [
    dict(emoji="\U0001F4E6", label="BOX Order Log",
         patterns=["BOX Order Log*.pdf", "box_order_log*.pdf"],
         note="automations.box_order_log.run --xlsx"),
    dict(emoji="\U0001F4B5", label="Accepted by supplier — last week & this week",
         patterns=["*Accepted by supplier*.pdf", "box_order_log_payout*.pdf"],
         note="automations.box_order_log.run (payout section)"),
    dict(emoji="\U0001F4CB", label="AT&T B2B Order Log",
         patterns=["att_order_log/*.csv", "ATT Order Log*.pdf"],
         note="automations.att_order_log.run --sheet"),
    dict(emoji="\U0001F310", label="New Internet Churn",
         patterns=["att_churn/new_int*.csv", "new_internet_churn*.png"],
         note="automations.att_order_log.churn_run --fill"),
    dict(emoji="\U0001F4CA", label="Wireless Churn",
         patterns=["att_churn/wireless*.csv", "wireless_churn*.png"],
         note="automations.att_order_log.churn_run --fill"),
    dict(emoji="\U0001F501", label="Ongoing Cancel",
         patterns=["att_cancels/*.csv"],
         note="automations.att_order_log.cancels_run --sheet"),
    dict(emoji="\U0001F4F8", label="Tableau Metrics",
         patterns=["att_metrics_shot/*.png"],
         note="automations.att_order_log.metrics_shot"),
]


def header_text(today: dt.date) -> str:
    return HEADER_FMT.format(today)


def body_lines() -> List[str]:
    """The parent message lists what is in the thread, one emoji-led line per
    reply — same convention as the other Lucy threads in Carlos's channels, and
    defined once so the header and the replies cannot drift apart."""
    return ["{} {}".format(i["emoji"], i["label"]) for i in ITEMS]


def plan(today: Optional[dt.date] = None) -> Dict[str, object]:
    today = today or dt.date.today()
    now = dt.datetime.now()
    rows = []
    for item in ITEMS:
        path = _newest(item["patterns"])
        age_h = None
        if path:
            age_h = (now - dt.datetime.fromtimestamp(
                path.stat().st_mtime)).total_seconds() / 3600.0
        rows.append({
            "emoji": item["emoji"], "label": item["label"],
            "path": str(path) if path else None,
            "age_hours": round(age_h, 1) if age_h is not None else None,
            "stale": bool(age_h is not None and age_h > 24),
            "note": item["note"],
        })
    ready = [r for r in rows if r["path"] and not r["stale"]]
    return {
        "date": today.isoformat(),
        "header": header_text(today),
        "channel_id": CHANNEL_ID,
        "channel_name": CHANNEL_NAME,
        "items": rows,
        "ready": len(ready),
        "total": len(rows),
        "complete": len(ready) == len(rows),
    }


def render(p: Dict[str, object]) -> str:
    out = []
    out.append("=" * 62)
    out.append("WOULD POST TO: {}".format(p["channel_name"]))
    out.append("")
    out.append("  *{}*".format(p["header"]))
    for line in body_lines():
        out.append("  {}".format(line))
    out.append("")
    out.append("THREAD REPLIES ({}/{} ready):".format(p["ready"], p["total"]))
    for r in p["items"]:
        if not r["path"]:
            mark, detail = "MISSING", "run: {}".format(r["note"])
        elif r["stale"]:
            mark = "STALE"
            detail = "{}h old — {}".format(r["age_hours"],
                                           Path(r["path"]).name)
        else:
            mark = "ok"
            detail = "{}h — {}".format(r["age_hours"], Path(r["path"]).name)
        out.append("  [{:^7}] {} {:<44} {}".format(
            mark, r["emoji"], r["label"], detail))
    out.append("")
    if not p["complete"]:
        out.append("NOT COMPLETE — a thread that posts some of the items reads "
                   "as finished. Fix the gaps above before enabling posting.")
    if not p["channel_id"]:
        out.append("NO CHANNEL SET — resolve the destination with Megan before "
                   "any posting code is added.")
    out.append("=" * 62)
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="att_order_log.thread")
    ap.add_argument("--json", action="store_true",
                    help="emit the plan as JSON")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())

    p = plan(today)
    if args.json:
        print(json.dumps(p, indent=2))
    else:
        print(render(p))
    # 0 whether or not it is complete: this is a report, and a non-zero exit
    # would make the orchestrator treat "not everything has run yet" as a
    # failure of THIS module.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
