"""Thread Builder — standalone/dev editor for an office's daily metrics thread.

Writes the committed thread_plans.json directly (LocalBackend). The PRODUCTION
home is the password-gated admin section of the metrics enrollment app
(office_onboarding/app.py), which uses the SAME editor with the SheetBackend so
edits go live on the next morning sync. Both share automations.thread_builder.editor.

Run it:  streamlit run automations/thread_builder/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from automations.thread_builder.editor import LocalBackend, render_editor

st.set_page_config(page_title="Thread Builder", page_icon="🧵", layout="centered")
st.title("🧵 Thread Builder")
render_editor(LocalBackend(), by="local")

with st.expander("What do these mean?"):
    st.caption("Each row is one section of the daily thread. The list on top posts "
               "in that exact order. Drag a row to the bottom bucket to leave it "
               "out entirely. “Reset to default” removes your custom plan so the "
               "office follows the standard order again.")
