"""Thread Builder — a self-serve editor for an office's daily metrics Slack thread.

Pick a campaign + office, then drag sections between "In the thread" and "Not
included" (and drag to reorder). Save writes the office's plan to thread_plans.json,
which both metrics runners read. An office you never touch keeps its default order.

Run it:  streamlit run automations/thread_builder/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `streamlit run automations/thread_builder/app.py` from the repo root OR
# the file's dir — put the repo root (two levels up) on the path either way.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from streamlit_sortables import sort_items

from automations.shared import thread_plans as tp
from automations.thread_builder import catalog as C

st.set_page_config(page_title="Thread Builder", page_icon="🧵", layout="centered")

st.title("🧵 Thread Builder")
st.caption("Choose which sections post in an office's daily thread — and drag to "
           "set the order they post in. Changes take effect on the next run after "
           "they're pushed to the reporting machine.")

# --- 1. Campaign ------------------------------------------------------------
campaign = st.radio("Campaign", options=list(C.CAMPAIGNS),
                    format_func=lambda k: C.CAMPAIGN_LABEL[k], horizontal=True)

# --- 2. Office --------------------------------------------------------------
offs = C.offices(campaign)
if not offs:
    st.warning("No offices found for this campaign.")
    st.stop()
disp = dict(offs)
office_key = st.selectbox("Office", options=[k for k, _ in offs],
                          format_func=lambda k: disp[k])

has_plan = tp.plan_for(campaign, office_key) is not None
st.markdown("**Status:** " + ("✏️ custom plan saved" if has_plan
                              else "🟢 using the default order"))

# --- 3. Build the two drag buckets from the office's CURRENT thread ---------
lab = C.label_map(campaign)                       # id -> "emoji Title"
rev = {v: k for k, v in lab.items()}              # label -> id
all_ids = [i for i, _ in C.catalog(campaign)]
included = C.current_ids(campaign, office_key)     # ordered, effective now
excluded = [i for i in all_ids if i not in included]

buckets = [
    {"header": "✅ In the thread  (top = posts first)",
     "items": [lab[i] for i in included]},
    {"header": "🚫 Not included",
     "items": [lab[i] for i in excluded]},
]

st.write("")
result = sort_items(buckets, multi_containers=True, direction="vertical",
                    key="sort_{}_{}".format(campaign, office_key))

# streamlit-sortables returns the same [{header, items}] shape, reordered.
new_included = [rev[l] for l in result[0]["items"] if l in rev]

# --- 4. Live preview of the resulting thread --------------------------------
st.write("---")
st.markdown("**Resulting thread order:**")
if new_included:
    st.markdown("\n".join("{}. {}".format(n + 1, lab[i])
                          for n, i in enumerate(new_included)))
else:
    st.info("Nothing selected — drag at least one section into the thread.")

default = C.default_ids(campaign, office_key)
is_default = new_included == default

# --- 5. Save / reset --------------------------------------------------------
st.write("")
c1, c2 = st.columns(2)
with c1:
    if st.button("💾 Save", type="primary", use_container_width=True,
                 disabled=not new_included):
        if is_default:
            # Re-states the runner default -> drop any plan so the office keeps
            # auto-inheriting future sections rather than freezing this list.
            existed = tp.clear_plan(campaign, office_key)
            st.success("Saved — this matches the default, so no custom plan is "
                       "stored" + (" (previous custom plan removed)." if existed
                                   else "."))
        else:
            tp.save_plan(campaign, office_key, new_included)
            st.success("Saved a custom plan for {}.".format(disp[office_key]))
        st.info("⤴️ To go live: commit + push, then update the reporting machine "
                "(e.g. `lucy update --machine \"Lucy 2\"`). Preview first with the "
                "office's dry-run handle before it posts.")
with c2:
    if st.button("↩️ Reset to default", use_container_width=True,
                 disabled=not has_plan):
        tp.clear_plan(campaign, office_key)
        st.success("Reset {} to the default order.".format(disp[office_key]))
        st.rerun()

with st.expander("What do these mean?"):
    st.caption("Each row is one section of the daily thread. The list on top posts "
               "in that exact order. Drag a row to the bottom bucket to leave it "
               "out entirely. “Reset to default” removes your custom plan so the "
               "office follows the standard order again.")
