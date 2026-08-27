"""The whole cleanup path, end to end, with nothing real touched.

THE ONE SEQUENCE PRODUCTION HAS NEVER RUN. It needs a rep who sells under a
spelling too far from their board row for near_matches to catch, gets a row of
their own, and is then confirmed in the chat -- which has not happened by
chance yet. Each piece is unit-tested; this is the only place they run in
order, which is where the mistakes actually live.

Everything outside the code under test is stubbed: no Sheets, no iMessage, no
state file. What IS real: fill.add_rep, fill.remove_rep, state's add ledger,
replies.resolve and apply_replies.handle.

Run: python -m automations.alphalete_sales_board.test_cleanup_path
"""
from __future__ import annotations

import datetime as dt

from automations.alphalete_sales_board import (aliases, apply_replies, fill,
                                               notify as N, replies, state as S)

MONDAY = dt.date(2026, 8, 24)
# A LEGAL NAME vs A NICKNAME — the case the guard genuinely cannot catch, and
# the only kind that reaches this path. "Miguel Angel Rivera" vs
# "Kelvinton ( BO ) Scarbough" IS caught (difflib sees the resemblance), which
# is the guard working: no row gets added, so there is nothing to take back.
REAL_ROW = "Mikey Ortiz (Wk 2)"
SARA_NAME = "MIGUEL ANGEL RIVERA"

HEAD_DAY = ["", "", "", "MON"] + [""] * 16
HEAD_SUB = ["", "", "Rep", "Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx",
            "Roll Call"] + [""] * 9


def _grid(rows):
    return [HEAD_DAY, [""] * 20, HEAD_SUB] + rows + [["", "", "TOTALS"] + [""] * 17]


def _row(name, mon=("", "", "", "", "")):
    return ["", "", name] + list(mon) + [""] * 12


class FakeWS:
    title = "Sales Board WE 8.30"

    def __init__(self):
        self.cells, self.batches = {}, []

    def update_acell(self, a1, value):
        self.cells[a1] = value

    def batch_update(self, updates, **kw):
        self.batches.append(updates)
        for u in updates:
            self.cells[u["range"]] = u["values"][0][0]


def test_added_then_confirmed_then_row_taken_back():
    ws = FakeWS()
    # A blank pre-built roster row (row 5), plus the man's real row (row 4).
    grid = _grid([_row(REAL_ROW, mon=("", "1", "", "", "")), _row("")])

    # 1. the guard genuinely does not catch this spelling
    assert fill.near_matches(SARA_NAME, [REAL_ROW]) == [], \
        "if near_matches catches it, no row is ever added and this path can't happen"

    # 2. so the sweep adds him a row of his own, and records that it did
    row, note = fill.add_rep(ws, grid, "Miguel Angel Rivera")
    assert row == 5 and not note, (row, note)
    assert ws.cells["C5"] == "Miguel Angel Rivera"
    store = {}
    store = S.record_added(store, MONDAY, SARA_NAME, "Miguel Angel Rivera", row)

    # the board now carries him twice — which is the damage being undone
    grid = _grid([_row(REAL_ROW, mon=("", "1", "", "", "")),
                  _row("Miguel Angel Rivera", mon=("", "2", "", "", ""))])
    board_names = fill.board_names(grid)
    assert len(board_names) == 2, board_names

    # 3. somebody types "Bo=Kelvin" in the chat
    sent = []
    saved = {"aliases": []}
    _load, _save, _add, _text = S.load, S.save, aliases.add, N.text_group
    S.load = lambda *a, **k: store
    S.save = lambda d, *a, **k: store.update(d)
    aliases.add = lambda s, b, **k: saved["aliases"].append((s, b))
    N.text_group = lambda g, body, **k: sent.append(body)
    apply_replies._load_feed = lambda: {
        "pending": [{"rowid": 1, "left": "Mikey", "right": "Miguel"}]}
    apply_replies._save_feed = lambda d: None
    try:
        out = apply_replies.handle(ws, grid, board_names, [SARA_NAME], MONDAY,
                                   send=True, log=lambda m: None)
    finally:
        S.load, S.save, aliases.add, N.text_group = _load, _save, _add, _text

    # 4. it aliased him, cleared the row it made, and said so
    assert saved["aliases"] == [(SARA_NAME, REAL_ROW)], saved["aliases"]
    assert ws.cells.get("C5") == "", "the duplicate row's name was not cleared"
    assert ws.cells.get("E5") == "", "the duplicate row's Int was not cleared"
    assert len(out) == 1, out
    assert "same person" in out[0], out[0]
    assert "deleted the extra row" in out[0], out[0]
    # and the ledger forgets it, so it can never be cleared twice
    assert S.added_row(store, SARA_NAME) is None


def test_the_real_row_is_never_touched():
    ws = FakeWS()
    grid = _grid([_row(REAL_ROW, mon=("", "3", "", "", "")),
                  _row("Miguel Angel Rivera", mon=("", "2", "", "", ""))])
    ok, note = fill.remove_rep(ws, grid, 5, "Miguel Angel Rivera", MONDAY)
    assert ok, note
    assert "C4" not in ws.cells and "E4" not in ws.cells, \
        "row 4 is the man's REAL row and must not be written at all"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print("ok  %s" % t.__name__)
    print("%d passed" % len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
