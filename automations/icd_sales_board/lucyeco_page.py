"""Who is enrolled in what, and when it runs — a link anyone can open.

Megan 2026-10-05: "I want to add a part to this LucyEco system so that it's a
live link - whoever has it can view it. And it shows what everyone is enrolled
in and on what schedule."

THERE IS NO ACCESS CODE ON THIS PAGE, AND THAT IS THE POINT. The sales board
next door is gated because it carries every rep's name and daily production;
this carries neither. What it shows is which offices get which of our reports
and at what time — the kind of thing you want to be able to send to an owner
asking "am I getting the knocks board?" without minting them a code first.

WHAT KEEPS IT SAFE IS THE DATA, NOT A GATE. enrollment.SAFE_COLUMNS is the
whole contract: office names, campaigns, feature names, schedules. No board
codes (the rollout list used to print them and no longer does), no money, no
rep names, no phone numbers, no channel ids. A test asserts the page cannot
render a column outside that list, because the gate that would otherwise catch
a mistake here does not exist.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from automations.icd_sales_board import enrollment as EN  # noqa: E402

st.set_page_config(page_title="Lucy ECOsystem — who gets what",
                   page_icon=":material/hub:", layout="wide")


@st.cache_data(ttl=600, show_spinner="Reading the registries…")
def _rows():
    """The table, from the last snapshot when it is recent enough.

    Two caches on purpose: Streamlit's holds it for ten minutes inside one
    running app, and the snapshot survives the app RESTARTING — which is what
    every deploy does, and what made somebody wait seventy seconds for the
    first view each time."""
    return EN.rows_cached()


def main() -> None:
    st.markdown("#### Alphalete Marketing")
    st.title("Lucy ECOsystem")
    st.caption("Every office, what it is enrolled in, and when each one runs. "
               "Read-only — nothing here changes anything.")
    # WHERE TO ASK. The page tells an owner what they could have and then
    # left them with nowhere to go (Megan 2026-10-06).
    st.caption("Want something switched on for your office, or something "
               "changed? **DM Megan or Eve on Slack** and they will set "
               "it up.")

    rows, taken = _rows()
    if not rows:
        st.info("Couldn't read the registries just now. Refresh in a minute.",
                icon="🚧")
        return

    # SAFETY, ENFORCED AT RENDER. This page has no access code, so the check
    # that nothing extra reached it happens here rather than being left to
    # whoever edits enrollment.py next.
    safe = [c for c in EN.SAFE_COLUMNS if any(c in r for r in rows)]
    # The underscored keys are the renderer's working notes — they decide
    # the colour of a cell and are never printed as a column. Narrowing
    # them away is what left a 22-hour-cold relay painted green on the
    # board (Megan 2026-10-06: "RYAN STILL ISN'T RED").
    rows = [{**{c: r.get(c, "") for c in safe},
             **{k: v for k, v in r.items() if str(k).startswith("_")}}
            for r in rows]

    counts = EN.counts(rows)
    live = sum(1 for r in rows if r.get("LucyECO") == "Active")
    c1, c2, c3 = st.columns(3)
    c1.metric("Offices", len(rows))
    c2.metric("On LucyECO", live)
    c3.metric("Most-used", max(counts, key=counts.get) if counts else "—",
              help="The report the most offices are enrolled in")

    # WHAT IS THIS COLUMN? (Megan 2026-10-05: "when I click on 'Text
    # Scoreboard' I want an image example of what it is"). A table header
    # cannot be clicked, so the answer sits directly above it as one popover
    # per feature — same gesture, and it works on a phone.
    EN.render_explainers(st, safe, _ROOT)

    # A REAL TABLE, NOT st.dataframe. That widget draws to a canvas: it shows
    # a newline as a space and then truncates, so every cell carrying a
    # window over a room arrived as one clipped line and the page still
    # looked uncondensed (Megan 2026-10-05) — no amount of shortening the
    # text would have fixed it. HTML gives real line breaks and the house
    # borders, the same reason the sales boards are drawn this way. Colour
    # comes from enrollment.cell_tone, by MEANING: a schedule is as much a
    # yes as the word Enrolled, so matching particular words would leave
    # every time-carrying column white.
    st.html(EN.html_table(rows, safe))

    # The colour key, the counts and the "read at" line are gone (Megan
    # 2026-10-06, twice — once for the board and again here). The
    # explainers above already say what each column is, and the table is
    # the point of the page.


main()
