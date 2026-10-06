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


_CSS = """<style>
.eco{border-collapse:collapse;font-size:12.5px;width:100%}
.eco th,.eco td{border:1px solid #CBD5E1;padding:4px 7px;text-align:center;
  vertical-align:middle;line-height:1.35;white-space:nowrap}
.eco th{background:#F1F5F9;font-weight:700;font-size:11.5px}
.eco td.name{text-align:left;font-weight:600;white-space:nowrap}
.eco tr:nth-child(even) td{background-image:linear-gradient(rgba(0,0,0,.02),
  rgba(0,0,0,.02))}
/* Each line is already as short as it can be, so nothing wraps mid-word —
   '#a-players-b2b' split across two lines was the last thing making this
   look uncondensed. The table scrolls sideways instead, which keeps a row
   readable. */
/* The two-column layout inside one cell: cadence on the left, where it
   lands on the right, so several destinations read as rows rather than as a
   paragraph. Borderless — the outer cell is already the box. */
.sub{border-collapse:collapse;margin:0 auto}
.sub td{border:0;padding:0 4px;white-space:nowrap}
.sub td.k{text-align:right;opacity:.85}
.sub td.v{text-align:left;font-weight:600}
.sub td.w{text-align:center;padding-bottom:1px}
.eco-wrap{overflow-x:auto}
</style>"""

_TONE_CSS = {
    "good": "background:#DCFCE7;color:#065F46;font-weight:600",
    "wait": "background:#FEF3C7;color:#78350F;font-weight:600",
    "bad": "background:#FEE2E2;color:#991B1B",
}


def _cell_html(value) -> str:
    """A cell's lines, with any two-field line laid out as columns.

    enrollment separates a cadence from the room it posts to, so they can sit
    under each other instead of running together and wrapping mid-name. Lines
    with no separator (a window, a bare status) span the whole cell."""
    lines = str(value or "").split("\n")
    if not any(EN.FIELD in ln for ln in lines):
        return _esc(value)
    out = []
    for ln in lines:
        left, sep, right = ln.partition(EN.FIELD)
        if sep:
            out.append(f'<tr><td class="k">{_esc(left)}</td>'
                       f'<td class="v">{_esc(right)}</td></tr>')
        else:
            out.append(f'<tr><td class="w" colspan="2">{_esc(ln)}</td></tr>')
    return '<table class="sub">' + "".join(out) + "</table>"


def _esc(text: str) -> str:
    """Escape, THEN turn newlines into breaks — never the other way round, or
    the breaks get escaped along with the content."""
    import html
    return html.escape(str(text or "")).replace("\n", "<br>")


def _table(rows: list, cols: list) -> str:
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            css = _TONE_CSS.get(EN.cell_tone(c, v), "")
            klass = ' class="name"' if c == "ICD" else ""
            cells.append(f'<td{klass} style="{css}">{_cell_html(v)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (_CSS + '<div class="eco-wrap"><table class="eco"><thead><tr>'
            + head + "</tr></thead><tbody>" + "".join(body)
            + "</tbody></table></div>")


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

    # WHAT IS THIS COLUMN? (Megan 2026-10-05: "when I click on 'Text
    # Scoreboard' I want an image example of what it is"). A table header
    # cannot be clicked, so the answer sits directly above it as one popover
    # per feature — same gesture, and it works on a phone.
    st.caption("What each column means — click one:")
    picks = [c for c in safe if c in EN.EXPLAINS]
    for chunk in range(0, len(picks), 5):
        for col, box in zip(picks[chunk:chunk + 5], st.columns(5)):
            words, shots = EN.EXPLAINS[col]
            # One name or several — call-outs are two different messages, the
            # nudge and the praise, and showing one of them explains half.
            shots = [shots] if isinstance(shots, str) else list(shots or [])
            with box.popover(col, use_container_width=True):
                st.markdown(f"**{col}**")
                st.write(words)
                shown = 0
                for shot in shots:
                    img = _ROOT / "resources" / "report-screenshots" / shot
                    if shot and img.exists():
                        st.image(str(img), use_container_width=True)
                        shown += 1
                if not shown:
                    st.caption("No example image for this one yet.")
    st.write("")

    # A REAL TABLE, NOT st.dataframe. That widget draws to a canvas: it shows
    # a newline as a space and then truncates, so every cell carrying a
    # window over a room arrived as one clipped line and the page still
    # looked uncondensed (Megan 2026-10-05) — no amount of shortening the
    # text would have fixed it. HTML gives real line breaks and the house
    # borders, the same reason the sales boards are drawn this way. Colour
    # comes from enrollment.cell_tone, by MEANING: a schedule is as much a
    # yes as the word Enrolled, so matching particular words would leave
    # every time-carrying column white.
    st.html(_table(rows, safe))

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
