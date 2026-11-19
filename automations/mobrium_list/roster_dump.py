"""READ-ONLY build run: every OwnerVille rep (active, lead, admin AND retired)
with email + phone, dumped to output/logs/ov-roster-dump.json.

Why: the alphaletereception contacts cleanup, step 2 (JD, 2026-11-19). JD only
wants removed the contacts we can PROVE were reps -- in OwnerVille -- and that
never showed up on a Sales Board. The match is done afterwards on Eve's
Windows by phone/email against the contacts snapshot; this run only reads.
The file lands in output/logs so `logtail`/`peek` can bring it back.

    lucy rerun ov_roster_dump
"""
from __future__ import annotations  # Lucy runs Python 3.9

import json
from dataclasses import asdict
from pathlib import Path

from automations.mobrium_list import ownerville

OUT = Path(__file__).resolve().parents[2] / "output" / "logs" / "ov-roster-dump.json"


def main() -> None:
    d = ownerville.load(include_inactive=True)
    rows = [asdict(r) for r in d.reps]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    by = {}
    for r in rows:
        by[r["roster"]] = by.get(r["roster"], 0) + 1
    print("ov roster dump: %d reps %s -> %s" % (len(rows), by, OUT))


if __name__ == "__main__":
    main()
