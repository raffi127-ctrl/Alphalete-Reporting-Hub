#!/bin/bash
# Double-click this file to launch the Reports dashboard.
# Binds to all network interfaces so Tailscale peers can reach it.

cd "$(dirname "$0")"
exec ./.venv/bin/streamlit run automations/dashboard.py \
  --server.headless true \
  --server.address 0.0.0.0 \
  --server.port 8501
