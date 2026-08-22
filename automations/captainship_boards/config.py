"""Captainship boards — identities + geometry.

The 11 captainship owner boards (order-log-only by Carlos's rule: outside
owners have no workbook we can read), the Captainship Dashboard master that
holds the Focus Report storage tabs ('MT · <First>', hidden), and the org
Alphalete Recruiting Dashboard's Daily Log for the recruiting rows.
Full architecture: ~/Desktop/captainship-sales-boards/README.md on the mini.
"""
import datetime as dt
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")

# label -> (uppercase name as it appears in the ORDERLOG export, board sheet id)
OWNERS = {
    "Jackie LeRoy":    ("JACKIE LEROY",    "1gK_QL06yPzHdSh6cNbaQ9lp7qSofoneti3kWxOgdf8I"),
    "Justin Wood":     ("JUSTIN WOOD",     "1TJpMQWJXnunqs3yrL_LV0-JZrjZEsGKtVzu5skGue6s"),
    "Joshua Murphy":   ("JOSHUA MURPHY",   "1VZEEpW--Us6_4UHhBJX8fYhY44Wu6CtJ3AdFtppZccc"),
    "Jamis Garay":     ("JAMIS GARAY",     "1wDWeiS0IuzwsYFGF-s6mA6by8CtBtI5eOEnNmahBd6s"),
    "Dhyey Patel":     ("DHYEY PATEL",     "1-gJfYtz8teNIMpYpMPVk5bBqomZWqu5yRfUGTfjqTlQ"),
    "Jeff Starr":      ("JEFFREY STARR",   "1CmUEyC_rwidScsLeuE1WywKUvqHE7avtytFLQgzD1pU"),
    "Kinsey Guenther": ("KINSEY GUENTHER", "1MxORzw6WFGxSXCuJf1hVok68eMOvRX02T9fhauVDFq0"),
    "George Hipolito": ("GEORGE HIPOLITO", "1XtKmB-C_hXFgBKyyBWbW9h8fG5riVXAM5ckaOClxQAs"),
    "Atef Choudhury":  ("ATEF CHOUDHURY",  "1PZwxUYDodOJ6LkxGrgB5ytDi0Fbd4h-mZJdM5q4ADnU"),
    "Joey Ramirez":    ("JOEY RAMIREZ",    "1n2d5vDiwwj6d3bFBIe5OcuEWEEc1OFn2Hp28wuaSFOY"),
    "Vincent Smith":   ("VINCENT SMITH",   "1LOi7JPQ8j0qlbe3PvgZumaHuWCd2HKLNYDRGZOBxrnE"),
}
MASTER_ID = "14_T4fySyQhRPsyWZLGEs6Sarc0jyJ4oD-gV8E97WZU8"   # Captainship Dashboard
ORG_TRACKER_ID = "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA"  # Alphalete Recruiting Dashboard (Daily Log lives here; READ-ONLY)

def mt_tab(label: str) -> str:
    return "MT · " + label.split()[0]

# ---- Focus Report geometry (current layout, post 8/22 reorg + goals) ----
# Current week block: WK col C (0-based 2), days D..J. 34 week blocks of 8.
WEEK0_COL = 2
N_WEEKS = 34
NCOLS = 2 + 8 * N_WEEKS

# campaign rows written from the ORDER LOG (current-week WK + day cells)
R_ACTIVE_HC = 35     # rolling week-to-date distinct sellers
R_APPS = 37          # total units
R_SPR = 38           # cumulative apps / cumulative sellers, 1dp
R_RANK = 39          # rolling rank among ALL owners in the export
R_NI = 41
R_CRU_NI = 42
R_WL_XBYOD = 43      # wireless excl BYOD
R_BYOD = 44
R_CRU_BYOD = 45
R_IRU_BYOD = 46
R_AIR = 47
R_VOIP = 48
R_CRU_PCT = 50       # cumulative: CRU/(CRU+IRU) all flagged units
R_ABP_PCT = 51       # cumulative: ABP Y/(Y+N) all units
R_BYOD_PCT = 52      # cumulative: BYOD / wireless units
# rows 53/54 (activation/churn) + 56/57 (nationals) come from the daily
# tracker crosstabs — separate --with-tableau section (not in v1 default).

# recruiting rows 5..27 from the org Daily Log (A serial, C manager, E..Q):
# spec: 'count' -> index into r[4:17]; 'rate' -> (num_idx, den_idx)
RECRUIT_ROWS = {
    5:  ("count", 0), 6:  ("count", 2), 7:  ("count", 1), 8:  ("rate", (2, 3)),
    10: ("count", 5), 11: ("rate", (4, 1)), 12: ("count", 6), 13: ("rate", (6, 5)),
    15: ("count", 7), 16: ("rate", (7, 6)), 17: ("count", 8), 18: ("rate", (8, 7)),
    20: ("count", 9), 21: ("rate", (9, 8)), 22: ("count", 10), 23: ("rate", (10, 9)),
    25: ("count", 11), 26: ("count", 12), 27: ("rate", (12, 11)),
}

def monday_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())

def week_label(mon: dt.date) -> str:
    s = mon + dt.timedelta(days=6)
    return f"{s.month}.{s.day}"

def serial(d: dt.date) -> int:
    return (d - dt.date(1899, 12, 30)).days
