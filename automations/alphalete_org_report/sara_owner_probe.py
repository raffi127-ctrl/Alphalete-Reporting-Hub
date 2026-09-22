"""Read-only probe: WHICH owners does each Sara Plus view actually carry?

Rafael asked (2026-09-22) for a Focus Report covering every owner in the NDS
tracker, not just our org's. The NDS OPT fill then left New Lines / AIR /
Next Up % / Extra-Premium % blank for everyone outside the org, because
SARAPLUSSALESSUMMARYBYDAY's DEFAULT view came back with 17 owners while the
tracker has 47. Eve pointed at a CUSTOM VIEW of the same workbook —
.../SARAPLUSSALESSUMMARYBYDAY/56513c60-cab5-4dfb-98da-9fb575c8a743/
CostcoLeaderRecognition — so the question is whether the custom view widens
the owner list or it is really an access limit.

Prints, for each URL shape, the export's header, row count and distinct owner
names, plus how many NDS-tracker owners it covers. Writes nothing: stdout only
(the queue keeps the tail in the job's Result cell; `lucy logtail` has it all).

    python -m automations.alphalete_org_report.sara_owner_probe
"""
from __future__ import annotations

import codecs
import csv
import io
import json
import sys
from pathlib import Path
from typing import List, Tuple

from automations.alphalete_org_report import opt_nds, tableau_http
from automations.shared.tableau_patchright import (
    tableau_session,
    requests_session_from_page,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, same guard as opt_nds
    pass

OUT = opt_nds.OUTPUT_DIR / "probe_sara_owners"
BASE = tableau_http.TABLEAU_BASE
SITE = tableau_http.TABLEAU_SITE
CV_ID = "56513c60-cab5-4dfb-98da-9fb575c8a743"

# Same view, four ways to ask for it. The first is what opt_nds pulls today.
URLS: List[Tuple[str, str, dict]] = [
    ("byday DEFAULT view",
     f"{BASE}/t/{SITE}/views/DropshipV_2/SARAPLUSSALESSUMMARYBYDAY.csv", {}),
    ("byday CUSTOM view (:cv=)",
     f"{BASE}/t/{SITE}/views/DropshipV_2/SARAPLUSSALESSUMMARYBYDAY.csv",
     {":cv": "CostcoLeaderRecognition"}),
    ("byday CUSTOM view (path)",
     f"{BASE}/t/{SITE}/views/DropshipV_2/SARAPLUSSALESSUMMARYBYDAY/"
     f"{CV_ID}/CostcoLeaderRecognition.csv", {}),
    ("summary DEFAULT view",
     f"{BASE}/t/{SITE}/views/DropshipV_2/SARAPLUSSALESSUMMARY.csv", {}),
]


def _rows(path: Path) -> List[List[str]]:
    raw = path.read_bytes()
    # Decide by BOM, never by trial order: the crosstab exports opt_nds reads
    # are UTF-16, the .csv HTTP endpoint returns UTF-8 — and raw.decode("utf-16")
    # does NOT raise on UTF-8 bytes, it returns CJK mojibake. The first version
    # of this probe tried utf-16 first and so reported "0 owner(s)" for every
    # view, including the tracker we know has 47 (2026-09-22).
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        text = raw.decode("utf-16", errors="replace")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
    lines = text.splitlines()
    delim = "\t" if lines and "\t" in lines[0] else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _owners(rows: List[List[str]]) -> List[str]:
    if not rows:
        return []
    cols = [i for i, h in enumerate(rows[0])
            if "owner" in h.lower() or "icd" in h.lower()]
    names = set()
    for r in rows[1:]:
        for i in cols:
            v = (r[i] if i < len(r) else "").split("\r")[0].split("\n")[0].strip()
            if v and v.lower() not in ("total", "grand total"):
                names.add(v)
    return sorted(names)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tracker = sorted(opt_nds.parse_tt_detail(
        opt_nds.OUTPUT_DIR / "opt_nds_tt_detail.csv"))
    print(f"NDS tracker owners: {len(tracker)}")

    with tableau_session(verbose=False) as page:
        http = requests_session_from_page(page)
        for label, url, params in URLS:
            try:
                r = http.get(url, params=params, allow_redirects=True, timeout=120)
            except Exception as e:  # noqa: BLE001 — report, never raise
                print(f"{label}: REQUEST FAILED {type(e).__name__}: {str(e)[:120]}")
                continue
            ctype = (r.headers.get("content-type") or "").split(";")[0]
            if r.status_code != 200 or "csv" not in ctype.lower():
                print(f"{label}: HTTP {r.status_code} content-type={ctype!r} "
                      f"({len(r.content)} bytes) — no data")
                continue
            path = OUT / (label.replace(" ", "_").replace("(", "").replace(")", "")
                          + ".csv")
            path.write_bytes(r.content)
            rows = _rows(path)
            owners = _owners(rows)
            norm = {opt_nds._norm_owner(o) for o in owners}
            hits = [t for t in tracker if t in norm]
            print(f"{label}: {len(rows) - 1} row(s), {len(owners)} owner(s), "
                  f"{len(hits)}/{len(tracker)} tracker owners")
            print(f"  header: {json.dumps(rows[0][:10]) if rows else '(empty)'}")
            print(f"  owners: {', '.join(owners) if owners else '(none)'}")
            missing = [t for t in tracker if t not in norm]
            print(f"  MISSING from this view: "
                  f"{', '.join(missing) if missing else '(none — covers all)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
