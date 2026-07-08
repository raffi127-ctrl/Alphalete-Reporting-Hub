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

    # 2) Run the (now-current) module as __main__, passing the remaining args
    #    through so its own argparse sees them (e.g. --send / --dry-run).
    module = f"automations.uploaded._shared.{lib_id}"
    sys.argv = [module, *rest]
    runpy.run_module(module, run_name="__main__")


if __name__ == "__main__":
    main()
