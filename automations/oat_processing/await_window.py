"""What the Await-text's time window should say RIGHT NOW (Carlos 2026-10-28).

Office 11580's "Await Call AI" SMS template offers interview times. Those times
were static, so afternoon applicants were offered mornings that had already
passed. Before each push pass the pusher recomputes the clause and edits the
template (await_template.py drives the browser; this module is the pure logic,
so the rules are testable without a browser).

Carlos's rules, his corrections applied:
- First-round interview slots run 8:15-10:45 and 12:15-3:45, every 30 minutes
  (:15 and :45).
- A slot under 30 minutes away is too soon — "it skips to the next time slot".
- After the last offerable slot (now past 3:15), offer tomorrow instead.
"""

import datetime as dt

# (start, end) of each interview window, minutes-from-midnight.
WINDOWS = [(8 * 60 + 15, 10 * 60 + 45), (12 * 60 + 15, 15 * 60 + 45)]
SLOT_STEP_MIN = 30
LEAD_MIN = 30          # a slot this close or closer is skipped


def _fmt(minutes: int) -> str:
    """615 -> '8:15am', 825 -> '1:45pm' — the template's own style (probed live
    2026-10-28: 'Are you available TODAY between 12:15pm-3:45pm for a quick
    ZOOM…')."""
    h, m = divmod(minutes, 60)
    return "%d:%02d%s" % (h % 12 or 12, m, "am" if h < 12 else "pm")


def _full_day_clause(day_word: str) -> str:
    w1, w2 = WINDOWS
    return "available %s between %s-%s or %s-%s" % (
        day_word, _fmt(w1[0]), _fmt(w1[1]), _fmt(w2[0]), _fmt(w2[1]))


def await_clause(now: dt.datetime) -> str:
    """The 'available …?' clause the template should carry at `now`.

    Always ends with '?', always starts with 'available', so the template
    editor can splice it over the old clause with one regex.
    """
    mins = now.hour * 60 + now.minute
    for wi, (start, end) in enumerate(WINDOWS):
        slot = start
        while slot <= end:
            if slot - mins > LEAD_MIN:
                if wi == 0:
                    # Morning offer still shows the afternoon window too.
                    w2 = WINDOWS[1]
                    first = ("at %s" % _fmt(slot) if slot == WINDOWS[0][1]
                             else "between %s-%s"
                             % (_fmt(slot), _fmt(WINDOWS[0][1])))
                    return ("available TODAY %s or %s-%s"
                            % (first, _fmt(w2[0]), _fmt(w2[1])))
                if slot == end:
                    return "available TODAY at %s" % _fmt(slot)
                return ("available TODAY between %s-%s"
                        % (_fmt(slot), _fmt(end)))
            slot += SLOT_STEP_MIN
    return _full_day_clause("TOMORROW")
