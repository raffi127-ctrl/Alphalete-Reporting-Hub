"""Minimal, dependency-free enqueue for the mini_control command queue.

The queue is a per-machine tab ("Mini Control" for Lucy 1, "Mini Control - <machine>"
otherwise) on the AUTOMATION MASTER sheet — the SAME sheet the onboarding forms
already write to. Kept import-light (no registry / notify / subprocess / patchright)
so a Streamlit Cloud onboarding app can drop a job for the mini by reusing its own
gspread client, without pulling the whole day_orchestrator into the Cloud app.

Mirrors mini_control.enqueue()'s row shape exactly (HEADERS + a 'queued' status),
so the mini poller picks these up identically to a `lucy ...` command.
"""
from __future__ import annotations

from datetime import datetime

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
CONTROL_TAB = "Mini Control"
DEFAULT_MACHINE = "Lucy 1"
HEADERS = ["Queued At", "Action", "Args", "By", "Status", "Result", "Finished At"]


def control_tab_for(machine: str | None) -> str:
    """The control tab for a machine — 'Mini Control' for the default (Lucy 1),
    'Mini Control - <machine>' otherwise. Matches mini_control._control_tab_for."""
    machine = (machine or DEFAULT_MACHINE).strip()
    return CONTROL_TAB if machine == DEFAULT_MACHINE else f"{CONTROL_TAB} - {machine}"


def enqueue(gc, action: str, args: str = "", by: str = "Megan",
            machine: str | None = None) -> str:
    """Append a 'queued' job to `machine`'s control tab using an existing gspread
    client `gc`. Returns the tab name queued to. Creates the tab (with header) if
    it doesn't exist yet."""
    tab = control_tab_for(machine)
    ss = gc.open_by_key(CONTROL_SHEET_ID)
    try:
        ws = ss.worksheet(tab)
    except Exception:                    # noqa: BLE001 — tab absent → create it
        ws = ss.add_worksheet(title=tab, rows=300, cols=len(HEADERS))
        ws.append_row(HEADERS)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    ws.append_row([now, action, args, by, "queued", "", ""],
                  value_input_option="RAW")
    return tab
