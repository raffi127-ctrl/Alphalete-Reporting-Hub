"""READ-ONLY build run: every OwnerVille rep (active, lead, admin AND retired)
with email + phone, dumped to output/logs/ov-roster-dump.json.

Why: the alphaletereception contacts cleanup, step 2 (JD, 2026-11-19). JD only
wants removed the contacts we can PROVE were reps -- in OwnerVille -- and that
never showed up on a Sales Board. The match is done afterwards on Eve's
Windows by phone/email against the contacts snapshot; this run only reads.

Getting it back: `logdump` copies at most 3900 lines of 4000 chars, and the
JSON is one huge line. So the run also writes ov-roster-dump.packed.log --
records as tab-separated fields, several per line joined by " || ", every line
under 3800 chars -- which `logdump ov-roster-dump.packed.log` brings back whole.

    lucy rerun ov_roster_dump               # pull OwnerVille + pack
    lucy rerun "ov_roster_dump --pack-only" # re-pack the last pull, no login
"""
from __future__ import annotations  # Lucy runs Python 3.9

import json
import sys
from dataclasses import asdict
from pathlib import Path

LOGS = Path(__file__).resolve().parents[2] / "output" / "logs"
OUT = LOGS / "ov-roster-dump.json"
PACKED = LOGS / "ov-roster-dump.packed.log"
FIELDS = ("roster", "first", "last", "email", "phone", "start", "retired")
MAX_LINE = 3800


def pack(rows) -> list:
    lines, cur = [], ""
    for r in rows:
        rec = "\t".join(str(r.get(f) or "").replace("\t", " ").replace("|", "/")
                        for f in FIELDS)
        if cur and len(cur) + 4 + len(rec) > MAX_LINE:
            lines.append(cur)
            cur = ""
        cur = rec if not cur else cur + " || " + rec
    if cur:
        lines.append(cur)
    return lines


def main() -> None:
    if "--pack-only" in sys.argv[1:]:
        rows = json.loads(OUT.read_text(encoding="utf-8"))
    else:
        from automations.mobrium_list import ownerville
        d = ownerville.load(include_inactive=True)
        rows = [asdict(r) for r in d.reps]
        LOGS.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    lines = pack(rows)
    PACKED.write_text("\n".join(lines) + "\n", encoding="utf-8")
    by = {}
    for r in rows:
        by[r["roster"]] = by.get(r["roster"], 0) + 1
    print("ov roster dump: %d reps %s -> %s (%d packed lines)"
          % (len(rows), by, PACKED.name, len(lines)))
    if len(lines) > 3900:
        print("WARNING: more than 3900 packed lines -- logdump will cut it")


if __name__ == "__main__":
    main()
