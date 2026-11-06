"""Generate the extension's engine.js from filler.py.

ONE source of truth, on purpose. The run engine is ~2,400 lines of JavaScript
that drives somebody's payroll system, and it is covered by the whole
test_filler / test_fields suite. Hand-copying it into the extension would have
forked it the first time either copy was touched, and the fork would show up as
a wrong value on a real employee's record.

So the extension does not have its own copy: `engine.js` is BUILT from
`filler._JS`, the same template the bookmarklet renders, and a test fails if
the file on disk has drifted from what this would write. Change the engine in
filler.py, run this, commit both.

What differs from the bookmarklet build is only how the week's details arrive.
The bookmarklet bakes them in (a new button per week); the extension ships the
code once and is handed a config at call time:

    window.__ansEngine({week, build, built_at, notice, start, data})

so `--button` keeps working unchanged and nobody re-saves anything.

    python -m automations.apex_new_starts.build_extension
"""
from __future__ import annotations

import json
from pathlib import Path

from automations.apex_new_starts import filler

OUT = (Path(__file__).resolve().parents[2]
       / "extension" / "apex-new-starts" / "engine.js")

HEAD = """// GENERATED -- do not edit. Built from automations/apex_new_starts/filler.py
// by `python -m automations.apex_new_starts.build_extension`.
//
// Editing this file would fork the engine away from the one the tests cover,
// and the symptom of a forked engine is a wrong value on a real payroll
// record. Change filler.py, rebuild, commit both.
//
// Everything below is the bookmarklet's own code, with the week's details
// taken from the config instead of baked in.
window.__ansEngine = function (CFG) {
  'use strict';
  var ANS_WEEK = String((CFG && CFG.week) || ''),
      ANS_BUILD = String((CFG && CFG.build) || ''),
      ANS_BUILT_AT = Number((CFG && CFG.built_at) || Date.now()),
      ANS_NOTICE = (CFG && CFG.notice) || null,
      ANS_START = String((CFG && CFG.start) || ''),
      ANS_DATA = (CFG && CFG.data) || null,
      ANS_ROLE = %s;
"""

TAIL = "\n};\n"


def engine_js() -> str:
    """The engine, as the extension's engine.js should read."""
    # Each placeholder is replaced by an EXPRESSION rather than a value. Every
    # %(week)s / %(build)s / %(start)s in the template sits inside a
    # single-quoted JS string, so closing the quote and concatenating is valid
    # in all of them; the rest are bare expressions already.
    body = filler._JS % {
        "week": "' + ANS_WEEK + '",
        "build": "' + ANS_BUILD + '",
        "built_at": "ANS_BUILT_AT",
        "notice": "ANS_NOTICE",
        "start": "' + ANS_START + '",
        "data": "ANS_DATA",
        "role": "ANS_ROLE",
    }
    role = json.dumps(filler.SECURITY_ROLE_LABEL.lower())
    return (HEAD % role) + body + TAIL


def main() -> int:
    text = engine_js()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    before = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    OUT.write_text(text, encoding="utf-8")
    print(f"{'unchanged' if before == text else 'wrote'} {OUT} "
          f"({len(text):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
