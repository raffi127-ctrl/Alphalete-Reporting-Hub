#!/bin/bash
# Visit the public LucyEco page; wake it if Streamlit put it to sleep.
# See automations/lucyeco_awake/run.py.
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD"
exec .venv/bin/python -W ignore -m automations.lucyeco_awake.run
