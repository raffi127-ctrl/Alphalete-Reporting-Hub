"""Email the owner when a card is published/edited through the Hub.

Hub uploads land in the shared "Report Library" Google Sheet (not git), and each
Hub instance may run on a teammate's machine that lacks the mail app password —
so notifying from inside the Hub would silently miss those. Instead this polls
the Sheet from the always-on mini (which always has creds), exactly parallel to
the git push watcher (automations.hub_push_watch).

Each poll compares every row to a saved snapshot:
  • id not seen before        → "new card" email (metadata + code preview)
  • Metadata or Script changed → "card updated" email (field changes + code diff)
The email body is built by shared.hub_upload_notify (same renderer either way).

The snapshot advances per-id only after that id's email sends, so a failed send
just retries next poll — no missed uploads, no dupes. First run snapshots
silently (no backfill blast). `--init` re-snapshots without emailing;
`--dry-run` builds emails to output/logs and neither sends nor moves state.

Usage:
  python -m automations.hub_library_watch.run [--dry-run] [--init]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from automations.shared import hub_upload_notify

# Mirror of the dashboard's constants (kept in sync by hand — they're stable).
# NOT imported from dashboard.py to avoid pulling in Streamlit on the mini.
SHARED_LIBRARY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
SHARED_LIBRARY_TAB = "Report Library"

# Per-machine snapshot of the last-seen library — {id: {"meta_json", "script"}}.
# Local state, never committed (lives with creds/oauth token).
STATE = Path.home() / ".config" / "recruiting-report" / "hub-library-watch-state.json"


def _load_state() -> dict | None:
    try:
        return json.loads(STATE.read_text())
    except FileNotFoundError:
        return None
    except Exception:
        # Corrupt state: treat as first run rather than crash-loop. Re-snapshot.
        return None


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=0))


def _read_library() -> dict:
    """Return {id: {"meta_json": raw col-F str, "script": raw col-G str,
    "metadata": parsed dict}} for every row in the shared library."""
    from automations.recruiting_report import fill as _fill
    sh = _fill.open_by_key(SHARED_LIBRARY_SHEET_ID)
    ws = sh.worksheet(SHARED_LIBRARY_TAB)
    rows = ws.get_all_records()
    out: dict = {}
    for r in rows:
        meta_json = str(r.get("Metadata") or "").strip()
        script = str(r.get("Script") or "")
        rid = str(r.get("ID") or "").strip()
        if not rid or not meta_json or not script:
            continue
        try:
            meta = json.loads(meta_json)
        except Exception:
            meta = {}
        meta.setdefault("id", rid)
        meta.setdefault("name", str(r.get("Name") or rid))
        meta.setdefault("module", str(r.get("Module") or ""))
        # "Created By" is the uploader; keep it as creator if the metadata blob
        # didn't carry one.
        meta.setdefault("creator", str(r.get("Created By") or ""))
        out[rid] = {"meta_json": meta_json, "script": script, "metadata": meta}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="build emails to output/logs; don't send or move state")
    ap.add_argument("--init", action="store_true",
                    help="snapshot the library without emailing")
    args = ap.parse_args(argv)
    ts = dt.datetime.now().isoformat(timespec="seconds")

    try:
        current = _read_library()
    except Exception as e:
        print(f"[{ts}] hub-library-watch: read failed: {type(e).__name__}: {e}",
              flush=True)
        return 1  # transient (auth/quota/network) — retry next poll

    state = _load_state()

    if args.init or state is None:
        snap = {rid: {"meta_json": v["meta_json"], "script": v["script"]}
                for rid, v in current.items()}
        if not args.dry_run:
            _save_state(snap)
        why = "re-init" if args.init else "first run — snapshot taken"
        print(f"[{ts}] hub-library-watch: {why}, {len(snap)} cards (no email)",
              flush=True)
        return 0

    new_ids, edited_ids, failures = [], [], 0
    for rid, cur in current.items():
        prev = state.get(rid)
        if prev is None:
            kind, preimage = "new", None
        elif (prev.get("meta_json") != cur["meta_json"]
              or prev.get("script") != cur["script"]):
            kind = "edit"
            preimage = {"script": prev.get("script", ""),
                        "metadata": json.loads(prev["meta_json"])
                        if prev.get("meta_json") else {}}
        else:
            continue  # unchanged

        try:
            hub_upload_notify.build_and_send(
                cur["metadata"], cur["script"], preimage, dry_run=args.dry_run)
        except Exception as e:
            failures += 1
            print(f"[{ts}] hub-library-watch: send failed for {rid}, state NOT "
                  f"advanced (retry next poll): {type(e).__name__}: {e}",
                  flush=True)
            continue  # leave this id's old state so it retries

        (new_ids if kind == "new" else edited_ids).append(rid)
        # Advance THIS id now (per-id, so one bad send doesn't lose the others).
        if not args.dry_run:
            state[rid] = {"meta_json": cur["meta_json"], "script": cur["script"]}

    # Forget cards removed from the library so state doesn't grow forever. (No
    # email — removal isn't an "upload"; if one returns it notifies as new.)
    removed = [rid for rid in list(state) if rid not in current]
    for rid in removed:
        if not args.dry_run:
            state.pop(rid, None)

    if not args.dry_run and (new_ids or edited_ids or removed):
        _save_state(state)

    print(f"[{ts}] hub-library-watch: {len(new_ids)} new, {len(edited_ids)} "
          f"edited, {len(removed)} removed, {failures} send-failure(s)"
          f"{' (dry-run)' if args.dry_run else ''}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
