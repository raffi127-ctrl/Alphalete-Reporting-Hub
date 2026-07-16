"""Standalone launcher for the New-Hire Swag Texts tool.

    streamlit run automations/swag_welcome/preflight_app.py

The actual UI lives in preflight_ui.render() so the Hub card (Office
Operations profile) and this standalone app share one codebase.
"""

from __future__ import annotations

import streamlit as st

from automations.swag_welcome import preflight_ui

st.set_page_config(page_title="New-Hire Swag Texts", page_icon="🏢", layout="wide")
preflight_ui.render(show_header=True)
