#!/bin/bash
# One tick of what this Lucy's monitor shows. See automations/lucy_screens/run.py.
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD"
exec .venv/bin/python -W ignore -m automations.lucy_screens.run
