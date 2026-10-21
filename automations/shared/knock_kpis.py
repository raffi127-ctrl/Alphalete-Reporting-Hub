"""Rafael's knocking KPIs — the green / gray / red scale on the knocks boards.

Raf 2026-10-20 (Loom): "my goal is on these categories for the daily report
and then the weekly report that it categorizes these columns as green, gray,
or red", with the numbers on the "Knocking KPI's" tab of 'All in One Local
Office - Raf'. "Knocking KPIs are going to change over time as I understand
this better" — so the tab is the source of truth, read on every board, and the
DEFAULTS below are only what draws when the tab can't be read.

Only the GREEN and RED cells are parsed. Gray is everything between them, so a
value that falls in a crack of the tab's own wording (19.95 between "19.9" red
and "20-21.9" gray) still lands somewhere sensible, and Raf editing one bound
can never leave the gray cell disagreeing with the other two.

Columns are found by the tab's HEADER TEXT, never by position (standing rule:
templates change, labels survive).

Six KPIs, and which board column each one paints (each board keeps its own
column -> KPI map, built from its own header constants):

    KPI            daily board              weekly board
    knocks_hr      Avg Knocks / Hr          Mon–Sat Avg Knocks / Hr
    doors          Total Knocks             Mon–Fri Avg Doors / Day
    talk_tos       Total Talk to            Mon–Sat Avg Talk To's / Day
    tt_per_app     Avg Talk To's per App    Mon–Sat Avg Talk To's per App
    first_knock    First Knock (not Sat)    Mon–Fri Avg First Knock
    hours          Avg. Hrs Knocking        Mon–Fri Avg Hrs Knocking / Day

"I don't want to even have Saturday first knock time" — so a Saturday daily
board leaves First Knock uncoloured, and the weekly board's Saturday columns
are never judged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Fill colours. Green is the boards' existing "hit" green so the two schemes
# read the same; gray has to stand off the white / striped rep rows, and red
# has to keep a black number readable.
GREEN = (74, 222, 128)
GRAY = (190, 190, 196)
RED = (248, 113, 113)

KPI_TAB = "Knocking KPI's"

# Every office's boards carry the scale, and First Knock is green at 1:30 for
# all of them, not at each office's own start (Rafael 2026-10-21: "Yes, every
# office. Every office should be at 1:30 start time Monday - Friday").


@dataclass(frozen=True)
class Scale:
    green: float          # the GREEN bound (inclusive)
    red: float            # the RED bound (inclusive)

    @property
    def lower_is_better(self) -> bool:
        return self.green < self.red

    def color(self, v: float):
        if self.lower_is_better:
            if v <= self.green:
                return GREEN
            return RED if v >= self.red else GRAY
        if v >= self.green:
            return GREEN
        return RED if v <= self.red else GRAY


# What the tab said on 2026-10-20. Times are minutes since midnight, hours
# are minutes knocked.
DEFAULTS = {
    "knocks_hr": Scale(22, 19.9),
    "doors": Scale(125, 99.9),
    "talk_tos": Scale(25, 19.9),
    "tt_per_app": Scale(16, 21),
    "first_knock": Scale(13 * 60 + 30, 14 * 60),
    "hours": Scale(4 * 60, 2 * 60 + 59),
}

def kpi_for_header(text: str) -> "str | None":
    """Which KPI one of the tab's headers names. Order matters: 'talk to's per
    app' is also 'talk', and 'hrs knock' is also 'knock'."""
    t = " ".join(str(text or "").lower().replace("’", "'").split())
    if "per app" in t:
        return "tt_per_app"
    if "first knock" in t:
        return "first_knock"
    if "hrs" in t or "hours" in t:
        return "hours"
    if "per hr" in t or "per hour" in t or "/ hr" in t:
        return "knocks_hr"
    if "door" in t:
        return "doors"
    if "talk" in t:
        return "talk_tos"
    return None


_NUM = re.compile(r"\d+(?:\.\d+)?")


def parse_time(text) -> "int | None":
    """'1:30 or prior' / '2:00 or later' / '1:06 PM' / '13:45' -> minutes since
    midnight. A bare hour under 12 with no AM is afternoon: nobody starts
    knocking at 1:30 in the morning."""
    s = str(text or "").strip().upper()
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if "AM" in s:
        h = 0 if h == 12 else h
    elif h < 12 and ("PM" in s or h < 9):
        h += 12
    return h * 60 + mi


def parse_hours(text) -> "int | None":
    """'4hrs+' / '2hrs 59mins or less' / '3h 24m' / '2.5' -> minutes."""
    s = str(text or "").strip().lower()
    h = re.search(r"(\d+(?:\.\d+)?)\s*h", s)
    m = re.search(r"(\d+)\s*m", s)
    if h or m:
        return round(float(h.group(1)) * 60 if h else 0) + (int(m.group(1))
                                                           if m else 0)
    n = _NUM.search(s)
    return round(float(n.group()) * 60) if n else None


def parse_number(text) -> "float | None":
    n = _NUM.search(str(text or "").replace(",", ""))
    return float(n.group()) if n else None


def parse_value(kpi: str, text) -> "float | None":
    if kpi == "first_knock":
        return parse_time(text)
    if kpi == "hours":
        return parse_hours(text)
    return parse_number(text)


def scales_from_grid(grid: list, *, logfn=print) -> dict:
    """{kpi: Scale} from the tab's values. Any KPI the tab doesn't carry, or
    whose cell doesn't parse, keeps its default — and says so."""
    out = dict(DEFAULTS)
    if not grid:
        return out
    header = grid[0]
    rows = {str(r[0]).strip().lower(): r for r in grid[1:] if r}
    green, red = rows.get("green"), rows.get("red")
    if not green or not red:
        logfn(f"[kpis] ! {KPI_TAB}: no Green/Red rows — using defaults")
        return out
    for ci, h in enumerate(header):
        kpi = kpi_for_header(h)
        if not kpi:
            continue
        g = parse_value(kpi, green[ci] if ci < len(green) else "")
        r = parse_value(kpi, red[ci] if ci < len(red) else "")
        if g is None or r is None or g == r:
            logfn(f"[kpis] ! {KPI_TAB} {h!r}: can't read "
                  f"{green[ci] if ci < len(green) else ''!r} / "
                  f"{red[ci] if ci < len(red) else ''!r} — using the default")
            continue
        out[kpi] = Scale(g, r)
    return out


_CACHE: dict = {}


def load(*, logfn=print) -> dict:
    """The live scales, read once per process (a run draws many boards)."""
    if "scales" not in _CACHE:
        try:
            from automations.recruiting_report.fill import open_by_key
            from automations.shared.workbooks import ALL_IN_ONE_RAF
            grid = open_by_key(ALL_IN_ONE_RAF).worksheet(KPI_TAB).get_all_values()
            _CACHE["scales"] = scales_from_grid(grid, logfn=logfn)
        except Exception as exc:  # noqa: BLE001 — a colour ≠ the board
            logfn(f"[kpis] ! {KPI_TAB} unreadable ({type(exc).__name__}) — "
                  "using the defaults")
            _CACHE["scales"] = dict(DEFAULTS)
    return _CACHE["scales"]


def for_office(office: str, *, logfn=print) -> dict:
    """The scales an office's boards draw with — the same for every office."""
    return load(logfn=logfn)


def cell_colors(header: list, rows: list, scales: dict, columns: dict,
                skip_rows, *, saturday: bool = False) -> dict:
    """{(row, col): rgb} for every rep cell the scales judge. `skip_rows` are
    the summary / comparison / team-band rows — the KPIs are per rep."""
    out = {}
    for ci, h in enumerate(header):
        kpi = columns.get(h)
        if not kpi or (saturday and kpi == "first_knock"):
            continue
        for ri, row in enumerate(rows):
            if ri in skip_rows or ci >= len(row):
                continue
            v = parse_value(kpi, row[ci])
            if v is not None and str(row[ci]).strip():
                out[(ri, ci)] = scales[kpi].color(v)
    return out
