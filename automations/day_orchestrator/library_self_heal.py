"""Generic self-heal for EVERY shared-library report.

Editing stays wide open — anyone with Hub access can improve any report. This is
the safety net so a bad save can't permanently break or gut a report:

  - keeps a last-known-good BACKUP of each report (library_backups), refreshed
    whenever the live code compiles and looks intact;
  - if a report's materialized code WON'T COMPILE, or a registered CRITICAL
    MARKER vanished (e.g. Texas de Brazil's Slack/iMessage send layer), it
    restores the backup to both the local cache (this run) and the Sheet cell
    (future runs + the Hub), and logs LOUD;
  - it will NOT overwrite a good backup with code that doesn't compile or that
    shrank suspiciously — so the safety copy can't be poisoned by a wipe. A big
    shrink that still compiles + keeps its markers is treated as a legit edit
    (not reverted) but the prior backup is preserved for one-off restore.

Called from run_library_report after materialize, for every report. Best-effort;
never raises into a run.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO / "automations" / "uploaded" / "_shared"
CELL_CAP = 50000
SHRINK = 0.40           # >40% smaller than the backup = suspicious (don't trust)

# Reports can register substrings that MUST always be present. Losing one means a
# semantic wipe (the code still compiles but a critical feature is gone).
CRITICAL_MARKERS = {
    # files_upload_v2 = Slack layer; send_imessage = the iMessage/text layer.
    # Both must survive an edit — guarding only Slack let the text layer vanish
    # from the cell without the safety net catching it.
    "june_texas_de_brazil_monthly_competition": ["files_upload_v2", "send_imessage"],
}


def _compiles(src: str) -> bool:
    try:
        compile(src, "<lib>", "exec")
        return True
    except Exception:
        return False


def _intact(lib_id: str, src: str) -> bool:
    """Compiles AND has all its registered critical markers."""
    return _compiles(src) and all(m in src for m in CRITICAL_MARKERS.get(lib_id, []))


def _write_cell(lib_id: str, script: str) -> bool:
    from automations import dashboard as D
    ws = D._shared_library_ws()
    col = ws.row_values(1).index("Script") + 1
    for i, r in enumerate(ws.get_all_records(), start=2):
        if lib_id in str(r.get("Metadata") or ""):
            ws.update_cell(i, col, script)
            return True
    return False


def guard(lib_id: str) -> dict:
    """Protect one report. Returns a small summary; never raises."""
    from automations.day_orchestrator import library_backups
    cache = _CACHE_DIR / f"{lib_id}.py"
    try:
        live = cache.read_text() if cache.exists() else ""
    except Exception:
        return {"action": "none"}
    if not live:
        return {"action": "none"}

    backup = library_backups.get(lib_id)

    # 1) Broken or gutted -> restore from a good backup.
    if not _intact(lib_id, live):
        if backup and _intact(lib_id, backup) and len(backup) < CELL_CAP:
            try:
                cache.write_text(backup)
            except Exception:
                return {"action": "restore-failed"}
            cell = False
            try:
                cell = _write_cell(lib_id, backup)
            except Exception:
                cell = False
            print(f"[library_self_heal] ⚠️ '{lib_id}' was broken/wiped — restored "
                  f"last-known-good (cache=True, cell={cell}). Someone saved bad code "
                  "over the cell; edits are welcome but must keep it working.")
            return {"action": "restored", "cell": cell}
        print(f"[library_self_heal] ⚠️ '{lib_id}' won't compile / lost a marker and "
              "there's no good backup to restore. Needs a human.")
        return {"action": "broken-no-backup"}

    # 2) Healthy. Refresh the backup, but never poison it with a suspicious shrink.
    if backup is None:
        if len(live) < CELL_CAP:
            library_backups.save(lib_id, live)
        return {"action": "seeded-backup"}
    if live == backup:
        return {"action": "ok"}
    if len(live) < len(backup) * (1 - SHRINK):
        print(f"[library_self_heal] note: '{lib_id}' shrank >{int(SHRINK*100)}% but still "
              "compiles + keeps its markers — treating as a real edit, keeping the "
              "previous backup as a safety copy.")
        return {"action": "kept-old-backup"}
    if len(live) < CELL_CAP:
        library_backups.save(lib_id, live)
    return {"action": "updated-backup"}


def main(lib_id: str) -> int:
    guard(lib_id)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1]) if len(sys.argv) > 1 else 2)
