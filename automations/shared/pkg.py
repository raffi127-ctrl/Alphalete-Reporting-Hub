"""Import a third-party package, pip-installing it on first use if it's missing.

WHY THIS EXISTS (2026-08-26). This repo has no requirements file: every machine's
venv was built by hand, so "is package X here?" is answered per box and nobody
finds out until a report dies at 10am. `captainship_drafts.review_gate` imports
pypdf INSIDE build_pdf (it's only needed on the print leg), and on 2026-08-26 the
mini's venv didn't have it. The 12 previews built fine, the deadline path reached
the PDF and raised `ModuleNotFoundError: No module named 'pypdf'`, so nothing was
posted to #revision-emails, Evelyn had nothing to check, and the captains got
nothing. The 15-minute agent then re-ran the identical failure until 8pm — a
retry loop cannot fix a missing package.

The pattern was already in the repo (day_orchestrator/tdb_data.py `_ensure`), and
it is the right one for an UNATTENDED fleet: the box repairs itself on the next
tick instead of waiting for somebody to ssh in. This just puts it in one place so
a second module doesn't get its own copy — `override_bulletin.review_gate` had
the same bare `from pypdf import ...` and the same latent break.

NOT a substitute for installing deps properly; it is the backstop for the gap
between "code pushed to the fleet" and "every venv updated by hand". Deliberately
loud: the install prints, and a failed install raises with the pip command to run
by hand, so the caller's alert carries something actionable instead of a bare
ImportError.
"""
from __future__ import annotations

import importlib
import subprocess
import sys

# Installed-this-process cache. The review agent ticks every 15 minutes and the
# orchestrator runs several reports per process; re-shelling to pip to be told
# "already satisfied" is pure latency.
_done: set[str] = set()

# import name -> pip name, for the ones that differ.
_PIP_NAME = {
    "fitz": "pymupdf",
    "PIL": "pillow",
    "dateutil": "python-dateutil",
    "yaml": "pyyaml",
}


def ensure(module: str, pip_name: str | None = None):
    """Return the imported `module`, pip-installing it first if it's missing.

    Raises RuntimeError (not ImportError) when the install fails, so the message
    a report puts in its failure alert names the fix instead of the symptom.
    """
    try:
        return importlib.import_module(module)
    except ImportError:
        pass
    if module in _done:
        # Installed once already this process and STILL not importable — a real
        # problem (wrong venv, name mismatch). Don't loop on it.
        raise RuntimeError(
            f"installed {pip_name or module} but `import {module}` still fails "
            f"— check that {sys.executable} is the venv you think it is")
    pkg = pip_name or _PIP_NAME.get(module, module)
    print(f"  · {module} is missing on this machine — installing {pkg} "
          f"(one-time)", flush=True)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet",
           "--disable-pip-version-check", pkg]
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:  # noqa: BLE001 — no network, no pip, wheel build, ...
        raise RuntimeError(
            f"{module} is not installed on this machine and installing it "
            f"failed ({type(e).__name__}). Run by hand: "
            f"{' '.join(cmd[:1])} -m pip install {pkg}") from e
    _done.add(module)
    importlib.invalidate_caches()
    return importlib.import_module(module)
