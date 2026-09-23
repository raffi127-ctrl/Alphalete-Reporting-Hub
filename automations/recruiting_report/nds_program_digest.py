"""What the NDS Program - Focus Report filled this week, DM'd to Eve as Lucy.

Eve, 2026-09-22: "avisame el lunes al dm de evelyn (mandalo como lucy)". She
closed the terminal, so this is a job, not a reminder — it runs on Lucy 3 right
after nds_program_focus_all (order 40) and reports on the week that run just
filled.

WHAT IT CHECKS, per tab, in the week's column: the APPS / PULL row
(recruiting), New Lines (sales) and Total Funds Available (financials) — each
counted against the SAME row in last week's column, because every one of them
is legitimately blank on some tabs: 24 owners have no AppStream office, Double
Entry only exposes our own org, and an owner can simply not have sold. "Filled
last week, blank now" is the only comparison that means something went wrong.

Plus: owners on the NDS tracker with no tab at all — the one gap nothing else
would surface, since every per-tab check is blind to a missing tab.

Read-only. Nothing is written to the Sheet; the only side effect is the DM.

    python -m automations.recruiting_report.nds_program_digest [--dry-run]
    python -m automations.recruiting_report.nds_program_digest --to U088E2KJEV8
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List

from automations.recruiting_report import fill as rfill

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, same guard as opt_nds
    pass

SHEET_ID = "1Vu_J7bcSpreIBcsYuAVEQMusL9-RaOSgB65DiKxrYtI"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
# Evelyn Sobrino. A user id, not a name, so a display-name change can't
# silently redirect the DM (focus_slack.py keeps the same id).
EVE_USER_ID = "U088E2KJEV8"
MAPPING = (Path(__file__).resolve().parent / "office-mapping-nds-program.json")

# Row label per section, matched as a SUBSTRING of column B: the tabs cut from
# the NDS template say 'APPS / PULL' where the org sheet says 'Sent To Call
# List - APPS / PULL', and an exact match found neither on half the tabs.
ROWS = {
    "recruiting": "apps / pull",
    "sales": "new lines",
    "financials": "total funds available",
}


def _last_sunday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7 or 7)


def _with_appstream() -> set:
    """Tabs the recruiting pull is even supposed to fill."""
    import json
    try:
        mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a missing mapping must not kill the DM
        return set()
    return {e["sheet_tab"] for e in mapping.get("confirmed", [])}


def collect(week: dt.date) -> dict:
    """Filled/blank per section for `week` AND for the week before it. The
    previous week is the yardstick: every section here is legitimately blank on
    some tabs (no AppStream office, no Double Entry office, an owner who sold
    nothing), so 'filled last week, blank this week' is the only signal that
    means something went wrong."""
    sh = rfill.open_by_key(SHEET_ID)
    tabs = [w.title for w in sh.worksheets() if w.title.endswith(" - NDS")]
    grids = sh.values_batch_get([f"'{t}'!A1:H60" for t in tabs])
    confirmed = _with_appstream()
    prev_week = week - dt.timedelta(days=7)
    got: Dict[str, List[str]] = {k: [] for k in ROWS}
    lost: Dict[str, List[str]] = {k: [] for k in ROWS}
    prev: Dict[str, List[str]] = {k: [] for k in ROWS}
    no_column = []
    for tab, vr in zip(tabs, grids["valueRanges"]):
        grid = vr.get("values", [])
        cols = rfill.find_sunday_columns(grid, header_row_idx=0)
        col = cols.get(week)
        if col is None:
            no_column.append(tab)
            continue
        prev_col = cols.get(prev_week)
        owner = tab[: -len(" - NDS")]
        for key, label in ROWS.items():
            row = next((r for r in grid
                        if len(r) > 1 and label in r[1].strip().lower()), None)
            if row is None:
                continue

            def at(c):
                return str(row[c - 1]).strip() if c and len(row) >= c else ""

            now, before = at(col), at(prev_col)
            if now:
                got[key].append(owner)
            if before:
                prev[key].append(owner)
            if before and not now:
                lost[key].append(owner)
    return {"tabs": tabs, "confirmed": confirmed, "got": got, "lost": lost,
            "prev": prev, "no_column": no_column, "prev_week": prev_week}


def tracker_owners_without_tab(tabs: List[str]) -> List[str]:
    """Owners the NDS tracker shows that this workbook has no tab for — read
    off the crosstab the run itself just downloaded, so it costs no pull."""
    try:
        from automations.alphalete_org_report.opt_nds import (
            parse_tt_detail, OUTPUT_DIR, _norm_owner)
        detail = parse_tt_detail(OUTPUT_DIR / "opt_nds_tt_detail.csv")
    except Exception:  # noqa: BLE001
        return []
    have = {_norm_owner(t[: -len(" - NDS")]) for t in tabs}
    return sorted(o for o in detail if o not in have)


def compose(week: dt.date, data: dict, new_owners: List[str]) -> str:
    n_tabs = len(data["tabs"])
    n_conf = len(data["confirmed"] & set(data["tabs"])) or len(data["confirmed"])
    got, lost, prev = data["got"], data["lost"], data["prev"]

    def line(label: str, key: str) -> str:
        n, was = len(got[key]), len(prev[key])
        mark = "⚠️" if lost[key] else "✅"
        out = f"{mark} {label}: {n} tab(s) — last week {was}"
        if lost[key]:
            shown = ", ".join(lost[key][:6])
            more = f" +{len(lost[key]) - 6} more" if len(lost[key]) > 6 else ""
            out += f"\n    filled last week, blank now: {shown}{more}"
        return out

    parts = [
        f"*NDS Program - Focus Report* — week ending {week:%-m/%-d}"
        if sys.platform != "win32" else
        f"*NDS Program - Focus Report* — week ending {week.month}/{week.day}",
        line("Recruiting (AppStream)", "recruiting"),
        line("Sales", "sales"),
        line("Financials", "financials"),
        "",
        f"{n_tabs} owner tabs · {n_tabs - n_conf} with no AppStream office "
        f"(they carry 'No access to this office' — expected, not a gap)",
    ]
    if new_owners:
        parts.append(
            f"🆕 On the tracker with no tab yet: {', '.join(o.title() for o in new_owners)}")
    if data["no_column"]:
        parts.append(f"⚠️ No {week} column: {', '.join(data['no_column'])}")
    parts.append(SHEET_URL)
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", metavar="YYYY-MM-DD",
                    help="Week ending Sunday. Default: the most recent one.")
    ap.add_argument("--to", default=EVE_USER_ID,
                    help="Slack user id / email / name. Default: Evelyn.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the message instead of sending it.")
    args = ap.parse_args()
    week = dt.date.fromisoformat(args.week) if args.week else _last_sunday()

    data = collect(week)
    text = compose(week, data, tracker_owners_without_tab(data["tabs"]))
    print(text)
    if args.dry_run:
        print("\n(dry run — not sent)")
        return 0
    from automations.shared import slack_metrics_post as smp
    client = smp._bot_client()             # Lucy's token: the DM comes from Lucy
    user_id = smp._resolve_user_id(client, args.to)
    channel = client.conversations_open(users=user_id)["channel"]["id"]
    client.chat_postMessage(channel=channel, text=text)
    print(f"\nsent to {args.to} ({channel})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
