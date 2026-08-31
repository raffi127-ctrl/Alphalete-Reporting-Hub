"""The per-click office guard refuses mutations when the page shows the wrong
office — and allows them when it matches (Carlos, 2026-08-30, Vincent/23318)."""
import sys, re
sys.path.insert(0, "/Users/carloshidalgo/recruiting-report")
from automations.oat_processing import run as oat, config

class P:
    def __init__(self, body): self._b = body
    def inner_text(self, _): return self._b
    frames = []

config.OFFICE_ID = "11580"
assert oat._guard_office_now(P("Office ID: 11580 Owner: CARLOS"), "t") is True
assert oat._guard_office_now(P("Office ID: 23318 Owner: VINCENT"), "t") is False
assert oat._guard_office_now(P("no banner at all"), "t") is False   # fails closed
config.OFFICE_ID = ""
assert oat._guard_office_now(P("Office ID: 11580"), "t") is False   # unset = closed
print("ok: guard passes right office, refuses wrong/unreadable/unset")
