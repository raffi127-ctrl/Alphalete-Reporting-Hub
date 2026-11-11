"""Daily plan text (Carlos 2026-11-11): one text at 8:00 AM, Monday-Saturday,
to the NEW A Players chain. Each weekday has its own template; a weekday with
no template yet sends nothing and says so in the log.

Carlos: "Every morning at 8 am, I want a text message structured like this
that gets sent out Monday through Saturday. Every day is going to be a
slightly different text message." Wednesday's came first; the rest follow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

# Routing key in b2b_dispositions.config.TEXT_ROUTES -> [NEW A Players].
CAMPAIGN_LABEL = "DAILY PLAN"
KIND = "daily_plan"

SEND_TIME = (8, 0)
WEEKDAYS = [0, 1, 2, 3, 4, 5]          # Monday .. Saturday (python weekday)

# Verbatim from Carlos. Keys are python weekdays: 0=Mon .. 5=Sat.
# None = no template yet -> nothing is sent that day.
TEMPLATES: Dict[int, Optional[str]] = {
    0: None,   # Monday    -- pending
    1: None,   # Tuesday   -- pending
    2: (       # Wednesday -- Carlos 2026-11-11
        "Wednesday\n"
        "*Please assign who’s doing what and what room will be used for "
        "leader meetings & day 1’s and day 2’s*\n"
        "\n"
        "ATT Leaders Meeting - \n"
        "VZ Leaders Meeting - \n"
        "\n"
        "ATT Day 1 (Garden theory, 5 steps, Fugi)  - \n"
        "VZ Day 1 - \n"
        "ATT Day 2 - \n"
        "VZ Day 2 - \n"
        "\n"
        "Lesson (5 steps to a convo ) -\n"
        "\n"
        "Circle up - \n"
        "\n"
        "ATT announcements -\n"
        "\n"
        "VZ Announcements - \n"
        "\n"
        "Impact -"
    ),
    3: None,   # Thursday  -- pending
    4: None,   # Friday    -- pending
    5: None,   # Saturday  -- pending
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Once per day: the 8am card and a hand `rerun --send` must not double-text.
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "daily_plan_text.json"
