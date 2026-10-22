"""NDS (RES AT&T OOF) reports for Carlos's crew -- settings.

Carlos 2026-10-19: "instead of going through fiber codes and Raf's login
... you're going to start going through mine ... the campaign on Ownerville
... AT&T OOF ... OOF is out of footprint ... we're just going to refer to it
as NDS, so label NDS knocks board etc."

Runs on LUCY 2 (its Ownerville login IS Carlos's office 11580 -- no
impersonation), under the RES AT&T OOF campaign. Replaces the Fiber reports
(gap_alerts guests on Lucy 1), which are switched off in their own config.
"""
from __future__ import annotations

from pathlib import Path

TEAM = "NDS"                                   # the word in front of every post
CAMPAIGN_LABEL = "RES AT&T OOF"                # as the Ownerville picker shows it
# invD2DClientId of RES AT&T OOF on office 11580. Found by
# `rerun b2b_dispositions --probe-campaigns` on Lucy 2 (2026-10-19).
CAMPAIGN_ID = "1"       # picker href on 2026-10-19: p=510&invD2DClientId=1

# Where it goes (Carlos's rooms).
TEXT_GROUPS = ["NEW A Players", "ATT B2B Leaders"]
SLACK_CHANNEL = "C07J46MQNUX"                  # #alphalete-gp-sales
THREAD_BOARD = "%s Knocks Board" % TEAM        # "<title> — Month Dth YYYY" (shared style)
THREAD_GAPS = "%s 15 Min Gaps" % TEAM

# Hours, on this machine's clock (Lucy 2 = Central). Sunday off unless
# shared/day_override says that date is a Saturday.
WEEKDAY_START, WEEKDAY_STOP = (14, 0), (21, 0)
SATURDAY_START, SATURDAY_STOP = (10, 30), (17, 30)

# First Knock colours on the board (Sebastian 2026-10-21, OK'd by Eve): this
# crew starts at 2:00, not Raf's 1:30 -- green up to 2:00, gray 2:01-2:29, red
# from 2:30. Every other KPI still reads Raf's "Knocking KPI's" tab.
FIRST_KNOCK_GREEN_AT = (14, 0)
FIRST_KNOCK_RED_AT = (14, 30)

# Extra board slots on top of the hourly ones (Carlos 2026-10-22: "send the
# knock board at 2:30 as well and then have it continue its regular
# schedule"). Weekday clock; each is a (hour, minute) half-hour slot.
EXTRA_BOARD_SLOTS = [(14, 30)]
GAPS_EVERY_MIN = 15          # the typed list
BOARD_EVERY_MIN = 60         # the picture
CALLOUT_EVERY_MIN = 60       # "no dispo, no credit check" lines
GAP_THRESHOLD_MIN = 15

# Post kinds, as the b2b_dispositions text handoff keys them.
KIND_BOARD = "nds_board"
KIND_GAPS = "nds_gaps"

# Credit checks for the call-outs come from Carlos's own SaraPlus, relayed by
# his office Mac mini under this ICD office key (icd_alerts).
RELAY_OFFICE_KEY = "carlos-b2batt"

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "nds_oof_state.json"
PROFILE_DIR = Path(__file__).resolve().parents[1] / "uploaded" / ".browser_profile_nds_oof"
