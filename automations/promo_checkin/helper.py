"""Board helper for Shikamaru's Monday promotion check-in (Carlos, 2026-07-19).

Shikamaru (~/shikamaru, same machine) posts a Monday Slack message listing all
In Training + Entry Level reps and asking which were promoted to leadership.
Its button handler shells out to THIS helper, which owns all Google-Sheets
logic via the recruiting-report auth.

  .venv/bin/python -m automations.promo_checkin.helper list
      -> JSON [{"name","campaign","tag","status"}, ...]
  .venv/bin/python -m automations.promo_checkin.helper promote '["Name", ...]'
      -> JSON {"promoted": [...], "not_found": [...]}  (sets col P = "Level 1")

Col P (Leadership Status) is deliberately NOT hard-protected, and this runs as
the board owner's auth anyway. Only exact-name matches are promoted.
"""
from __future__ import annotations

import json
import re
import sys

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
WK_TAG = re.compile(r"^\d+(st|nd|rd|th) Wk$")
CAMPS = ("B2B", "BOX", "JE", "Base")


def _board():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(SHEET_ID).worksheet("Sales Board")


def _reps(vals):
    for r in range(5, 69):
        row = vals[r - 1] if len(vals) >= r else []
        name = str(row[1]).strip() if len(row) > 1 else ""
        camp = str(row[11]).strip() if len(row) > 11 else ""
        if name and camp in CAMPS:
            tag = str(row[13]).strip() if len(row) > 13 else ""
            status = str(row[15]).strip() if len(row) > 15 else ""
            yield r, name, camp, tag, status


def list_candidates() -> list[dict]:
    vals = _board().get("A1:P75")
    return [{"name": n, "campaign": c, "tag": t, "status": s}
            for _, n, c, t, s in _reps(vals)
            if s in ("In Training", "Entry Level")]


def promote(names: list[str]) -> dict:
    sb = _board()
    vals = sb.get("A1:P75")
    want = {" ".join(x.lower().split()) for x in names}
    updates, promoted = [], []
    for r, n, _c, _t, s in _reps(vals):
        if " ".join(n.lower().split()) in want and s in ("In Training",
                                                         "Entry Level"):
            updates.append({"range": f"P{r}", "values": [["Level 1"]]})
            promoted.append(n)
    if updates:
        sb.batch_update(updates, value_input_option="USER_ENTERED")
    not_found = [x for x in names
                 if " ".join(x.lower().split())
                 not in {" ".join(p.lower().split()) for p in promoted}]
    return {"promoted": promoted, "not_found": not_found}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if mode == "list":
        print(json.dumps(list_candidates()))
    elif mode == "promote":
        print(json.dumps(promote(json.loads(sys.argv[2]))))
    else:
        print(json.dumps({"error": f"unknown mode {mode}"}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
