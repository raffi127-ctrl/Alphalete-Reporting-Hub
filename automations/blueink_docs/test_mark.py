"""The Blue Ink column's colours (Megan 2026-09-21): blue while we wait on a
signature, green once it's signed. The rule that is easy to break is the
second half -- anything that repaints a SIGNED box blue says "still waiting"
about a finished packet.

    python -m automations.blueink_docs.test_mark
"""
from __future__ import annotations

import sys

from automations.blueink_docs import completed, mark


class _Person:
    def __init__(self, name, row, ticked=""):
        self.name, self.row, self.blueink_col = name, row, 14
        self.blueink_val = ticked
        self.key = name.lower()
        self.email = ""
        self.eligible = True


class _Sheet:
    """Records the colours sent; no network."""
    id = 7

    def __init__(self):
        self.spreadsheet = self
        self.painted, self.values = {}, []

    def batch_update(self, body, **_):
        if isinstance(body, dict):            # a format request
            for r in body["requests"]:
                rc = r["repeatCell"]
                self.painted[rc["range"]["startRowIndex"] + 1] = \
                    rc["cell"]["userEnteredFormat"]["backgroundColor"]
        else:                                 # a values write
            self.values += body


def _check(name, ok, bad):
    print(("  ok  " if ok else "FAIL  ") + name)
    return bad + (not ok)


def main() -> int:
    bad = 0

    ws = _Sheet()
    mark.highlight(ws, [_Person("Ana", 3)])
    bad = _check("a fresh send goes light blue",
                 ws.painted[3] == mark.SENT_BLUE, bad)

    ws = _Sheet()
    mark.highlight(ws, [_Person("Ben", 4)], color=mark.CARRIED_BLUE)
    bad = _check("a carried-over packet goes the deeper blue",
                 ws.painted[4] == mark.CARRIED_BLUE, bad)

    ws = _Sheet()
    mark.highlight(ws, [_Person("Le'derius", 5, ticked="TRUE")],
                   color=mark.CARRIED_BLUE)
    bad = _check("an already-SIGNED box stays green, never back to blue",
                 ws.painted[5] == mark.DONE_GREEN, bad)

    ws = _Sheet()
    people = [_Person("Cy", 6), _Person("Di", 7)]
    completed.tick(ws, people, {"cy": "9/21/26"})
    bad = _check("ticking a box turns it green in the same pass",
                 ws.painted == {6: mark.DONE_GREEN}
                 and [v["values"] for v in ws.values] == [[["TRUE"]]], bad)

    ws = _Sheet()
    completed.green_ticked(ws, [_Person("Ed", 8, ticked="TRUE"),
                                _Person("Flo", 9, ticked="FALSE"),
                                _Person("Gus", 10, ticked="x")])
    bad = _check("boxes ticked by hand go green; unticked ones are left alone",
                 set(ws.painted) == {8, 10}
                 and all(c == mark.DONE_GREEN for c in ws.painted.values()), bad)

    # The sweep's repaint: the rule applied to a whole tab at once.
    from automations.blueink_docs import ledger, run
    ws = _Sheet()
    ws.title = "D2D OBCL 9.21"
    log = [["2026-09-21 07:40", "D2D OBCL 9.21", "Ann Sent", "a@x.com", "B1", "sent", "", ""],
           ["2026-09-21 07:41", "D2D OBCL 9.21", "Bo Signed", "b@x.com", "B2", "sent", "", ""],
           ["2026-09-07 07:40", "D2D OBCL 9.7", "Cal Carried", "c@x.com", "B3", "sent", "", ""]]
    real = ledger.read
    ledger.read = lambda wb: log
    try:
        people = [_Person("Ann Sent", 20), _Person("Bo Signed", 21, ticked="TRUE"),
                  _Person("Cal Carried", 22), _Person("Dee Declined", 23)]
        quit_ = _Person("Cal Carried", 24)            # same old packet, but Declined
        quit_.eligible = False
        people.append(quit_)
        for pp in people:
            pp.key = "|".join(reversed(pp.name.lower().split()))
        run._repaint(None, ws, people)
    finally:
        ledger.read = real
    bad = _check("sweep repaint: sent=blue, signed=green, carried=deeper blue, "
                 "declined + everyone else untouched",
                 ws.painted == {20: mark.SENT_BLUE, 21: mark.DONE_GREEN,
                                22: mark.CARRIED_BLUE}, bad)

    bad = _check("the send colour is not green any more",
                 mark.SENT_BLUE != mark.DONE_GREEN
                 and mark.CARRIED_BLUE != mark.DONE_GREEN, bad)

    print()
    print("all good" if not bad else f"{bad} FAILURE(S)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
