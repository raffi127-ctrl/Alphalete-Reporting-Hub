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

Since 2026-10-02 the reps sit on three tabs of one shape — "NDS Sales Board"
(the AT&T program, NDS on the sheet since 2026-10-03), "BOX Sales Board",
"Verizon Sales Board" — so the list spans all three and a promotion is
written on the tab the rep's row is on. The campaign in the JSON is the
board's canonical label (vantura_boards.canon_campaign): an AT&T rep reads
"NDS", even off a row that still says "B2B".
"""
from __future__ import annotations

import json
import re
import sys

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
WK_TAG = re.compile(r"^\d+(st|nd|rd|th) Wk$")
CAMPS = ("NDS", "B2B", "BOX", "JE", "Base", "Verizon")   # B2B = legacy NDS


def _sheet():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(SHEET_ID)


def _reps(sh):
    """(tab, row, name, campaign, tag, status) for every rep on the boards."""
    from automations.vantura_boards import all_reps
    for rep in all_reps(sh):
        if rep["name"] and rep["campaign"] in CAMPS:
            yield (rep["tab"], rep["row"], rep["name"], rep["campaign"],
                   rep["field"], rep["lead"])


def list_candidates() -> list[dict]:
    return [{"name": n, "campaign": c, "tag": t, "status": s}
            for _tab, _r, n, c, t, s in _reps(_sheet())
            if s in ("In Training", "Entry Level")]


def promote(names: list[str]) -> dict:
    sh = _sheet()
    want = {" ".join(x.lower().split()) for x in names}
    updates, promoted = {}, []
    for tab, r, n, _c, _t, s in _reps(sh):
        if " ".join(n.lower().split()) in want and s in ("In Training",
                                                         "Entry Level"):
            updates.setdefault(tab, []).append(
                {"range": f"P{r}", "values": [["Level 1"]]})
            promoted.append(n)
    for tab, ups in updates.items():
        sh.worksheet(tab).batch_update(ups, value_input_option="USER_ENTERED")
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
