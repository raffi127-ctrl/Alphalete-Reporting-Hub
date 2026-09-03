"""Alert when the order log has sales that land on NO board row.

WHY THIS EXISTS (Carlos 2026-09-03): Gary sold 2 BOX and Jayden 1 on 9/2. The
order log had all three, the confirm pass SAW them — and logged them as
"! IN THE LOG BUT ON NO BOX ROW" where nobody looks, because the board rows
were named "Gary Van Whitetaker II" and "Jayden Luna" while the log says
"Gary Van Whitaker" and "Jayden Willingham". Worse than invisible: BOX is
authoritative, so every pass also WIPED the hand-typed fix a human made,
board 10 -> 7, twice in one morning. The flag has to reach the corrections
channel, exactly like vantura_slack_sales' unknown-poster alert.

One incident thread (shared.incident_thread), at most one post per day per
set of names; any live pass with zero unmatched reps closes it.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

REPORT_NAME = "Vantura Order-Log Sales fill"
INC_UNMATCHED = "vantura-orderlog-unmatched-rep"
UNMATCHED_STATE = (Path(__file__).resolve().parents[2]
                   / "output" / ".vorder_unmatched_alert")


def build_unmatched_message(items) -> list[str]:
    """items: [(log_name, count, campaign, 'm/d'), ...]"""
    lines = [
        f":mag: *{REPORT_NAME}* — {len(items)} order-log rep(s) match "
        "NO row on the Sales Board",
        "",
        "The order log HAS these sales; the board total does NOT. Until the "
        "names match, every pass leaves them off — and a BOX pass also "
        "clears any number typed into a row it can't find in the log:",
        "",
    ]
    lines += [f"  • *{name}* — {n} {camp} on {day}"
              for name, n, camp, day in items]
    return lines + [
        "",
        "*To fix:* rename the rep's row (col B, Sales Board tab) to the "
        "order log's name — matching is exact or first+last token — or add "
        "the rep's row if they're new. The next pass fills the day itself.",
        "",
        "*PASTE TO CLAUDE*",
        "```",
        "Report: automations/vantura_orderlog_sales — log reps on no board row",
        "Unmatched: "
        + ", ".join(f"{name} ({n} {camp} {day})"
                    for name, n, camp, day in items),
        "```",
    ]


def alert_unmatched(items, state: Path = UNMATCHED_STATE) -> bool:
    """Post the unmatched-rep warning, at most once a day per set of names."""
    key = dt.date.today().isoformat() + "|" + ",".join(
        sorted(name for name, _n, _c, _d in items))
    try:
        if state.read_text().strip() == key:
            print("[alert] same unmatched reps already reported today",
                  flush=True)
            return False
    except Exception:  # noqa: BLE001 — no state file yet is normal
        pass
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(key)
    except Exception:  # noqa: BLE001 — never block the alert on bookkeeping
        pass

    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config

    lines = build_unmatched_message(items)
    ts = notify.post_alert(lines[0], lines[1:],
                           tag="vantura_orderlog_sales-unmatched-rep",
                           cfg=load_config(), incident=INC_UNMATCHED)
    print(f"[alert] unmatched-rep post {'sent' if ts else 'SKIPPED/failed'}",
          flush=True)
    return bool(ts)


def resolve_unmatched(*, dry_run: bool = False) -> bool:
    """Every log rep landed on a row — close the thread."""
    from automations.shared import incident_thread as inc
    return inc.resolve_if_open(
        INC_UNMATCHED,
        what=f"*{REPORT_NAME}* — every order-log rep matches a board row",
        detail="_No unmatched log reps this run._", dry_run=dry_run)
