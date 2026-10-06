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
    return EN.rows()


def main() -> None:
    st.markdown("#### Alphalete Marketing")
    st.title("Lucy ECOsystem")
    st.caption("Every office, what it is enrolled in, and when each one runs. "
               "Read-only — nothing here changes anything.")

    rows = _rows()
    if not rows:
        st.info("Couldn't read the registries just now. Refresh in a minute.",
                icon="🚧")
        return

    # SAFETY, ENFORCED AT RENDER. This page has no access code, so the check
    # that nothing extra reached it happens here rather than being left to
    # whoever edits enrollment.py next.
    safe = [c for c in EN.SAFE_COLUMNS if any(c in r for r in rows)]
    rows = [{c: r.get(c, "") for c in safe} for r in rows]

    counts = EN.counts(rows)
    live = sum(1 for r in rows if r.get("LucyECO") == "Active")
    c1, c2, c3 = st.columns(3)
    c1.metric("Offices", len(rows))
    c2.metric("On LucyECO", live)
    c3.metric("Most-used", max(counts, key=counts.get) if counts else "—",
              help="The report the most offices are enrolled in")

    st.dataframe(rows, use_container_width=True, hide_index=True,
                 height=min(42 * (len(rows) + 1) + 8, 900))

    st.caption(
        "A cell shows WHEN that report runs for that office; blank means the "
        "office is not enrolled. Times are the office's own local time where "
        "the report is scheduled that way. "
        + " · ".join(f"**{k}** {v}" for k, v in sorted(counts.items())
                     if v))
    st.caption(f"Read live from the registries that run these reports, "
               f"{dt.date.today():%b %d %Y} — not a list anybody maintains by "
               f"hand, so it cannot drift from what actually runs. To change "
               f"what an office gets, change it where it is set and this "
               f"follows.")


main()
