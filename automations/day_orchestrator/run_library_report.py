"""Run a shared-library report with its LATEST code from the Report Library Sheet.

The library report scripts under `automations/uploaded/_shared/*.py` are a local
CACHE the Hub materializes from the Report Library Sheet. A plain
`python -m automations.uploaded._shared.<id>` (what `lucy rerun` and the Hub
"Run Live" button do) runs whatever is ON DISK — which can be stale if the Hub
process hasn't re-read the library recently. This wrapper materializes the
current Sheet version FIRST, then runs it, so a rerun/Run-Live always executes
the code that's actually in the library.

    python -m automations.day_orchestrator.run_library_report <library_id> [args...]

e.g. `... run_library_report june_texas_de_brazil_monthly_competition --send`
materializes the latest Texas de Brazil script, then runs it with --send.
"""
from __future__ import annotations

import runpy
import sys


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: run_library_report <library_id> [args...]")
        sys.exit(2)
    lib_id, rest = argv[0], argv[1:]

    # 1) Materialize the latest script text from the Report Library Sheet into the
    #    local cache. Best-effort: if the Hub login isn't importable/authorized we
    #    fall through and run whatever is already on disk (same as before).
    try:
        from automations import dashboard as D
        try:
            D._read_shared_library_rows.clear()   # bust the 60s st.cache_data
        except Exception:
            pass
        D._read_shared_library_rows()
    except Exception as e:  # noqa: BLE001 — never block the run on a refresh hiccup
        print(f"(run_library_report: materialize skipped — {type(e).__name__}: {e})")

    # 1b) Texas de Brazil: the dinner date is typed on the Hub card (any machine)
    #     but the report reads a MACHINE-LOCAL manual-inputs JSON — so a date set
    #     on the laptop never reached the mini's run (flyer showed "TBD"). Merge
    #     the git-synced seed into this machine's local JSON before running.
    #     Best-effort; only touches dinner_schedule (never leaders).
    if lib_id == "june_texas_de_brazil_monthly_competition":
        try:
            from automations.day_orchestrator import tdb_sync_inputs
            tdb_sync_inputs.main()
        except Exception as e:  # noqa: BLE001 — never block the run on a sync hiccup
            print(f"(run_library_report: tdb dinner sync skipped — {type(e).__name__}: {e})")

    # 2) Run the (now-current) module as __main__, passing the remaining args
    #    through so its own argparse sees them (e.g. --send / --dry-run).
    module = f"automations.uploaded._shared.{lib_id}"
    sys.argv = [module, *rest]
    runpy.run_module(module, run_name="__main__")

    # 3) Texas de Brazil: echo the dinner date the flyer just used, LAST, so it
    #    shows in the (short) status tail — a positive check that the Hub-card
    #    date crossed over to this machine (vs. the old "TO BE DETERMINED").
    if lib_id == "june_texas_de_brazil_monthly_competition":
        try:
            import datetime as _dt
            import json
            from automations.day_orchestrator import tdb_sync_inputs as _T
            _anchor = _dt.date.today() - _dt.timedelta(days=1)
            _period = f"{_anchor.year}-{_anchor.month:02d}"
            _data = json.loads(_T.LOCAL_INPUTS.read_text())
            _ent = (_data.get("dinner_schedule") or {}).get(_period) or {}
            _day = str(_ent.get("day", "") or "").strip()
            print(f"TDB FLYER DINNER DATE [{_period}]: "
                  f"{(_day + ' / ' + str(_ent.get('time','')).strip()) if _day else 'TO BE DETERMINED (not set)'}")
        except Exception as e:  # noqa: BLE001
            print(f"(run_library_report: tdb date readout skipped — {type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
