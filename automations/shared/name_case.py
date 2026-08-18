"""Title-case a person's name from a messy source, without wrecking real names.

Megan's standing rule (2026-07-27): report output must ALWAYS correct
punctuation and capitalization on people's names — never render a name the way
it arrives. Sources hand us "cinthya reyes", "AMJAD MALHAS", "adairus phillips";
all of those go out as "Cinthya Reyes", "Amjad Malhas", "Adairus Phillips".

The implementation is the one that has been running on the Leader's Call deck
since 2026-07-27 (`automations.leaders_call.build_pdf.titlecase_name`), lifted
here so every report shares ONE copy instead of each growing its own. This
module deliberately imports nothing — clean/parse layers pull it in on the hot
path and must not drag reportlab (or anything else) along with them.

Rules, in order:
  * a word with no letters (a number, "&", "-") is left exactly as it is;
  * a roman-numeral suffix stays upper — II, III, IV …;
  * a word that is ENTIRELY one case gets recased — that's the messy input;
  * anything already mixed-case is left alone, because that mix is a decision
    somebody made: McClain, LeRoy, DePaz, O'Brien.

Python 3.9 on the mini / Lucy 2 — no runtime `X | Y`.
"""
from __future__ import annotations

_ROMAN = {"II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}


def _recase_word(w: str) -> str:
    """Capitalize the first letter of each alpha run (after space/hyphen/
    apostrophe/paren/period) and lowercase the rest: 'adairus'->'Adairus',
    "o'brien"->"O'Brien"."""
    out, cap_next = [], True
    for ch in w:
        if ch.isalpha():
            out.append(ch.upper() if cap_next else ch.lower())
            cap_next = False
        else:
            out.append(ch)
            cap_next = True
    return "".join(out)


def titlecase_name(s) -> str:
    """Fix capitalization on a person's name; see the module docstring."""
    words = str(s).split()
    res = []
    for w in words:
        letters = [c for c in w if c.isalpha()]
        if not letters:
            res.append(w)
        elif w.upper().strip(".") in _ROMAN:          # roman-numeral suffix
            res.append(w.upper())
        elif all(c.isupper() for c in letters) or all(c.islower() for c in letters):
            res.append(_recase_word(w))               # single-case -> recase it
        else:
            res.append(w)                             # intentional mixed case
    return " ".join(res)
