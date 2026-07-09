"""Self-heal the Texas de Brazil report cell.

The recurring failure: someone (Maud's Claude) saves an OLD PDF-only copy of the
script over the Report Library cell, wiping the whole delivery layer (Slack +
iMessage + --send). The run then exits 0 but posts nothing.

This guard runs at the top of every TdB run (after the cell is materialized to the
local cache). If the cache has lost its delivery fingerprint, it restores the
known-good version from the committed backup — to BOTH the local cache (fixes this
run) and the Sheet cell (fixes future runs + the Hub) — and logs LOUD so we know a
wipe happened. Leaders are unaffected: they flow from the board auto-detect + the
'TdB Manual Inputs' store, not this code.
"""
from __future__ import annotations

from pathlib import Path

LIB_ID = "june_texas_de_brazil_monthly_competition"
_REPO = Path(__file__).resolve().parents[2]
BACKUP = _REPO / "deploy" / "texas_de_brazil_slim_backup.py"
CACHE = _REPO / "automations" / "uploaded" / "_shared" / f"{LIB_ID}.py"
MARKER = "files_upload_v2"        # the delivery layer's fingerprint
CELL_CAP = 50000                  # Google Sheets per-cell char limit


def heal() -> dict:
    """Restore the delivery version if the materialized cache was wiped.
    Best-effort; returns a summary and never raises into a run."""
    try:
        cache_txt = CACHE.read_text() if CACHE.exists() else ""
    except Exception:
        cache_txt = ""
    if MARKER in cache_txt:
        return {"healed": False}          # delivery code present — all good

    try:
        good = BACKUP.read_text()
    except Exception as e:  # noqa: BLE001
        return {"healed": False, "error": f"backup unreadable: {e}"}
    if MARKER not in good or len(good) >= CELL_CAP:
        return {"healed": False, "error": "backup invalid (no delivery / too big)"}

    # Fix THIS run: overwrite the local cache with the good code.
    try:
        CACHE.write_text(good)
    except Exception as e:  # noqa: BLE001
        return {"healed": False, "error": f"cache write failed: {e}"}

    # Fix FUTURE runs + the Hub: write the good code back to the Sheet cell.
    cell = False
    try:
        from automations import dashboard as D
        ws = D._shared_library_ws()
        col = ws.row_values(1).index("Script") + 1
        for i, r in enumerate(ws.get_all_records(), start=2):
            if LIB_ID in str(r.get("Metadata") or ""):
                ws.update_cell(i, col, good)
                cell = True
                break
    except Exception as e:  # noqa: BLE001
        return {"healed": True, "cache": True, "cell": False, "error": str(e)}
    return {"healed": True, "cache": True, "cell": cell}


def main() -> int:
    r = heal()
    if r.get("healed"):
        print(f"[tdb_self_heal] ⚠️ CELL WAS WIPED — restored delivery code "
              f"(cache={r.get('cache')}, cell={r.get('cell')}). "
              "Someone saved an old copy over the cell; tell them to stop editing the code.")
    elif r.get("error"):
        print(f"[tdb_self_heal] not healed — {r['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
