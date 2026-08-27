"""Ranges and auth for the Ad Sales Board tabs.

Same workbook and same credential chain as the Source Report - Indeed job —
everything is borrowed from its sheet module so the two can never drift on
auth. Only the tab names are ours:

  * 'Ad Sales Data'  (hidden)  — the only thing the scheduled job writes.
  * 'Ad Sales Board' (visible) — pickers + one FILTER formula; the job touches
    just its C2 week picker, on Wednesdays.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

from automations.indeed_source_report.sheet import (  # noqa: F401 — re-exported
    API, SPREADSHEET_ID, clear, get_values, put_values, session,
)

DATA_TAB = "Ad Sales Data"
VIEW_TAB = "Ad Sales Board"

DATA_HEADERS = ["Manager", "Week", "Account", "Inbox Email", "Ad Title", "City",
                "Pull", "To Call List", "# Names", "Names", "Week Start",
                "D1 Mon", "D2 Tue", "D3 Wed", "D4 Thu", "D5 Fri", "D6 Sat",
                "D7 Sun"]


def data_range(a1):
    return "'%s'!%s" % (DATA_TAB, a1)


def view_range(a1):
    return "'%s'!%s" % (VIEW_TAB, a1)


def probe_write(sess):
    """Prove this credential can WRITE the workbook before anything is pulled.
    Same trick as the monthly job: rewrite one throwaway in-grid cell with what
    it already holds. Raises on 403/404 (and on a missing data tab — which
    means build_tab.py was never run on this workbook)."""
    cell = data_range("N19999")
    r = sess.get("%s/%s/values/%s" % (API, SPREADSHEET_ID, cell),
                 params={"valueRenderOption": "UNFORMATTED_VALUE"})
    r.raise_for_status()
    current = (r.json().get("values") or [[""]])[0]
    w = sess.put("%s/%s/values/%s" % (API, SPREADSHEET_ID, cell),
                 params={"valueInputOption": "RAW"},
                 json={"majorDimension": "ROWS", "values": [current or [""]]})
    w.raise_for_status()
