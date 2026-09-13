#!/usr/bin/env python3
"""Parse Python files with the FLEET's interpreter version, not this laptop's.

WHY THIS EXISTS (2026-09-13). Every Lucy runs Python 3.9. Megan's laptop runs
3.14. On 2026-09-13 two f-strings with a replacement field spanning LINES — PEP
701, which is 3.12+ — were committed and pushed after a full green test run here.
On Lucy 2 both modules raised SyntaxError on import and EVERY applicant-push walk
exited 1 for about 45 minutes, across all four offices, until it was traced.

The local test suite cannot catch this: it runs on the interpreter that accepts
the syntax. Neither can ast.parse(..., feature_version=(3, 9)) — that flag was
tried and it accepts the broken form. The only thing that catches it is a real
3.9 parser, which is what this runs under.

    /opt/homebrew/bin/python3.9 deploy/check_py39.py [files...]

With no arguments it checks every tracked .py file. The pre-commit hook passes
the staged ones. Uses ast.parse rather than py_compile so it never writes .pyc
files next to the source.
"""
from __future__ import annotations

import ast
import subprocess
import sys

MIN = (3, 10)   # anything at or above this is the WRONG interpreter for this check


def _tracked_py():
    out = subprocess.run(["git", "ls-files", "*.py"],
                         capture_output=True, text=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def main(argv):
    if sys.version_info >= MIN:
        print("[py39] REFUSING to run on Python %d.%d — this check is only "
              "meaningful under the fleet's 3.9, because a newer parser accepts "
              "the very syntax it is looking for."
              % sys.version_info[:2])
        return 2
    paths = argv[1:] or _tracked_py()
    bad = 0
    for p in paths:
        if not p.endswith(".py"):
            continue
        try:
            with open(p, "rb") as fh:
                src = fh.read()
        except OSError:          # deleted in this commit, nothing to parse
            continue
        try:
            ast.parse(src, filename=p)
        except SyntaxError as e:
            bad += 1
            print("[py39] %s:%s: %s" % (p, e.lineno, e.msg))
            if e.text:
                print("       %s" % e.text.rstrip())
    if bad:
        print("\n[py39] %d file(s) will not parse on Python 3.9 — the version "
              "every Lucy runs. They would raise SyntaxError on import and take "
              "the report down on the machine, not here." % bad)
        return 1
    print("[py39] ok — %d file(s) parse on %d.%d"
          % (len(paths), sys.version_info[0], sys.version_info[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
