"""Where SARA+ CC reads from and writes to.

SOURCE: ui.saraplus.com (Raf's login, alphaletemarketing@gmail.com -- the same
one the Alphalete Sales Board sweep uses) -> Analytics -> Reports/ReportingHub
-> Detail Reports -> Activities. Date Range = yesterday..today, Disposition
ALL, Customer Type Residential (page defaults) -> Export CSV.

TARGET: 'All in One Local Office - Raf' -> tab 'SARA+ CC' (Raf made it; his
Loom called it "Sarah Plus"; the tab was renamed SARA+ ORDERS -> SARA+ CC).
Columns found by their ROW-1 LABEL, never by letter.
"""
from __future__ import annotations

from pathlib import Path

from automations.shared.workbooks import ALL_IN_ONE_RAF

WORKBOOK_ID = ALL_IN_ONE_RAF
LIVE_TAB = "SARA+ CC"
SANDBOX_TAB = "SARA+ CC - SANDBOX (Claude)"

# Which tab the automatic pull (the hook in the Sales Board sweep) writes.
# SANDBOX until the first pulls are checked; then LIVE_TAB.
TARGET_TAB = SANDBOX_TAB

# Raf: "every 15 minutes, 30 minutes, hour, anything within that".
INTERVAL_MIN = 15

# How many days back each pull covers (0 = today only). 1 = also yesterday,
# so a record keyed after the last pull of the night (the sweep stops at
# 23:59) is still caught at noon the next day. Order ID dedupes the overlap.
DAYS_BACK = 1

STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "sara_activities_state.json")

# Row-1 labels on the tab -> the SaraPlus export column that fills it.
# 'TIME' is derived from the Date; 'NOTES' is Raf's and never written.
COLUMN_SOURCE = {
    "Date": "Date",
    "Order ID": "Order ID",
    "Dealer Code": "Dealer Code",
    "User Name": "User Name",
    "Agent Name": "Agent Name",
    "Customer": "Customer",
    "Customer Email": "Customer Email",
    "Phone": "Phone",
}
TIME_HEADER = "TIME"
KEY_HEADER = "Order ID"
