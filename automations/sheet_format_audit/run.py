"""Daily check of the monthly recruiting tabs: formulas + colors. See audit.py.

    python -m automations.sheet_format_audit.run                # report only
    python -m automations.sheet_format_audit.run --fix          # + repair
    python -m automations.sheet_format_audit.run --fix --post   # what the mini runs

What --fix touches, and nothing else:
  * ADDS four color rules (0% white / green / yellow / red, the tab's own
    legend) on a % column whose colors are wrong. Never deletes a rule and
    never clears a hand-painted fill — the new rules sit first, so they win.
  * Rewrites a % formula that divides the wrong columns (or is missing on a row
    with a leader name) to =iferror(num/den,0), and a TOTALS =SUM that stops
    short of the last leader.
Only the current month (leftmost block) unless --all-months.
A TYPED number where a formula belongs, or a formula it doesn't recognise, is
only reported — someone may have typed it on purpose.

--post goes to #claudecorrections-and-requests, and only when something was
fixed or a new problem showed up (the same open problem isn't re-posted every
day). Refuses from Windows: the Slack token there is Evelyn, not Lucy.

Adding another owner's tab = one more Target in TARGETS, as long as the tab
uses the same '<Month> BOB Call / Stats' block layout.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

from automations.sheet_format_audit import audit as A

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "output" / "sheet_format_audit" / "state.json"
CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests


@dataclass(frozen=True)
class Target:
    name: str
    sheet_id: str
    tab: str


def _targets() -> List[Target]:
    from automations.shared.workbooks import ALL_IN_ONE_RAF
    return [Target("All in One Local Office - Raf", ALL_IN_ONE_RAF, "2nd rds %'s")]


def _read(sh, tab: str):
    from automations.shared import sheets_retry as RETRY
    meta = RETRY.call(sh.fetch_sheet_metadata, params={
        "ranges": "'%s'" % tab.replace("'", "''"),
        "includeGridData": "true",
        "fields": "sheets(properties(sheetId,title),conditionalFormats,"
                  "data(rowData(values(formattedValue,userEnteredValue))))"})
    s = meta["sheets"][0]
    shown, formulas = [], []
    for row in (s.get("data") or [{}])[0].get("rowData", []):
        vals = row.get("values", [])
        shown.append([v.get("formattedValue", "") for v in vals])
        formulas.append([(v.get("userEnteredValue") or {}).get("formulaValue")
                         for v in vals])
    return s["properties"]["sheetId"], shown, formulas, s.get("conditionalFormats", [])


def _apply(sh, tab: str, findings: List[A.Finding]) -> List[A.Finding]:
    from automations.shared import sheets_retry as RETRY
    reqs, data, done = [], [], []
    for f in findings:
        if not f.fix:
            continue
        # Each added at index 0, so add them last-first: the block ends up
        # white, green, yellow, red at the top of the list.
        for rule in reversed(f.fix.get("add_rules", [])):
            reqs.append({"addConditionalFormatRule": {"rule": rule, "index": 0}})
        for cell, formula in f.fix.get("formulas", {}).items():
            data.append({"range": "'%s'!%s" % (tab.replace("'", "''"), cell),
                         "values": [[formula]]})
        done.append(f)
    if reqs:
        RETRY.call(sh.batch_update, {"requests": reqs})
    if data:
        RETRY.call(sh.values_batch_update,
                   {"valueInputOption": "USER_ENTERED", "data": data})
    return done


def _message(t: Target, fixed: List[A.Finding], still: List[A.Finding]) -> str:
    parts = [f":mag: *Sheet check — {t.name} › `{t.tab}`*"]
    if fixed:
        parts.append("*Fixed on its own:*\n" + "\n".join(f"• {f.line()}" for f in fixed))
    if still:
        parts.append("*Still wrong — needs a person:*\n" +
                     "\n".join(f"• {f.line()}" for f in still))
    return "\n\n".join(parts)


def _post(text: str, dry_run: bool) -> bool:
    if dry_run:
        print("\n--- would post to Slack ---\n" + text + "\n---------------------------")
        return True
    if platform.system() == "Windows":
        print("\n! not posting from Windows (the token here is Evelyn, not Lucy). "
              "The mini posts it on its daily run.")
        return False
    from automations.shared import slack_metrics_post as smp
    smp._client().chat_postMessage(channel=CHANNEL, text=text)
    print("  posted to #claudecorrections-and-requests")
    return True


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no state = first run
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true", help="Repair what can be repaired.")
    ap.add_argument("--post", action="store_true", help="Post fixes/new problems to Slack.")
    ap.add_argument("--all-months", action="store_true",
                    help="Check the closed months too (default: current month only).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be fixed/posted; write nothing.")
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key
    state = _state()
    for t in _targets():
        sh = open_by_key(t.sheet_id)
        sid, shown, formulas, rules = _read(sh, t.tab)
        found = A.audit(shown, formulas, rules, sid, a.all_months)
        print(f"{t.name} › {t.tab}: {len(found)} problem(s)")
        for f in found:
            print("  - " + f.line())

        fixed: List[A.Finding] = []
        if a.fix and any(f.fix for f in found):
            if a.dry_run:
                fixed = [f for f in found if f.fix]
                print(f"  (dry run) would fix {len(fixed)}")
            else:
                fixed = _apply(sh, t.tab, found)
                sid, shown, formulas, rules = _read(sh, t.tab)
                after = A.audit(shown, formulas, rules, sid, a.all_months)
                print(f"  fixed {len(fixed)}; re-checked: {len(after)} left")
                found = after
        still = [f for f in found if not (a.dry_run and f in fixed)]

        key = f"{t.sheet_id}|{t.tab}"
        lines = sorted(f.line() for f in still)
        new = [f for f in still if f.line() not in state.get(key, [])]
        if a.post and (fixed or new):
            _post(_message(t, fixed, still), a.dry_run)
        if not a.dry_run:
            state[key] = lines

    if not a.dry_run:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
