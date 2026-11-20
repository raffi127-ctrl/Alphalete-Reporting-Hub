"""No Python string literal may contain a real backspace character.

WHY THIS TEST EXISTS. Every browser-driving module in this repo hands
JavaScript to Playwright as a triple-quoted Python string, and JS regexes are
full of `\\b` word boundaries. In a NON-raw Python string `\\b` is not two
characters -- it is chr(8), the backspace control character -- so the regex
Playwright receives is `/<BS>(yes|submitted)<BS>/`, which matches nothing, ever.

Nothing warns. `\\s`, `\\d` and `\\{` are *invalid* escapes and Python prints a
SyntaxWarning for them; `\\b` is a *valid* escape, so it is converted in silence
and the only symptom is a reader that always comes back empty:

  * shared/saraplus.py      -- the sentence-off-the-body fallback for a login
                               bounce. Written 2026-09-22 to fix "no error
                               shown"; it never once ran.
  * headshots/ov_upload.py  -- owner_submitted(), which decides whether a
                               headshot redo is still allowed. Any Owner Submit
                               cell rendered as text read 'unknown'.
  * oat_processing/run.py   -- the "prefer the Send to AI button" match, so the
                               broader fallback always won instead.

All three were one character from correct: the literal needed an `r` prefix.
This test walks every module's AST so the fourth one is caught here rather than
in a run that quietly does nothing.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
AUTOMATIONS = ROOT / "automations"

# chr(8), never a "\\b" literal: this file is walked by its own check,
# and a literal here would make the guard report itself forever.
BACKSPACE = chr(8)


def _offenders():
    out = []
    for path in sorted(AUTOMATIONS.rglob("*.py")):
        parts = set(path.parts)
        if "__pycache__" in parts or ".claude" in parts:
            continue
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if BACKSPACE in node.value:
                    out.append("%s:%d" % (path.relative_to(ROOT), node.lineno))
    return out


class BackspaceInStringLiterals(unittest.TestCase):

    def test_no_literal_holds_a_backspace(self):
        found = _offenders()
        self.assertEqual(
            found, [],
            "These string literals contain chr(8) because a JS `\\b` was "
            "written in a non-raw string. Prefix the literal with r: "
            + ", ".join(found))

    def test_the_check_can_actually_see_one(self):
        """A guard that cannot fail is not a guard."""
        tree = ast.parse('x = "' + chr(92) + 'b(yes)"')
        hit = [n for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and BACKSPACE in n.value]
        self.assertEqual(len(hit), 1)


if __name__ == "__main__":
    unittest.main()
