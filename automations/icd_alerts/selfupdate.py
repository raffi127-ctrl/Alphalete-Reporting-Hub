"""Keep an office's copy current without anybody running anything.

Megan 2026-09-13: "we need to get it where we update it and they get it
automatically without having to run anything on their ends."

THE PROBLEM THIS SOLVES. Kash sat on the first agent for a day with no sales,
because getting a fix onto an office's machine meant messaging a person and
hoping they pasted a line. That does not survive fifty offices, and it is
exactly how a fix comes to exist and not be running anywhere.

THE PROBLEM IT COULD CREATE, and why this is careful. These are computers we
cannot reach. An update that breaks the agent does not break one office's
alerts for an afternoon -- it breaks them until somebody drives there, and it
would do it to every office at once, because they all pull the same code.
So:

  * ONCE A DAY, not every tick. The agent runs every few minutes; pulling that
    often is pointless traffic and multiplies the chance of catching a half-
    pushed tree.
  * DOWNLOADED TO ONE SIDE, verified, and only then swapped in. The new code
    has to import in a subprocess before it is allowed to replace anything.
  * THE OLD COPY IS KEPT until the new one has proved itself in place, and
    restored if it has not. A machine that cannot be reached must be able to
    put itself back.
  * A FAILED UPDATE IS REPORTED upstream and leaves the office running
    yesterday's code, which works. Silence would leave us thinking every
    office is current.
"""
from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import List, Optional

from automations.icd_alerts import config as C

RAW = ("https://raw.githubusercontent.com/raffi127-ctrl/"
       "Alphalete-Reporting-Hub/main")
LIST_PATH = "automations/icd_alerts/agent_files.txt"
STAMP = C.APP_DIR / "last-selfupdate.txt"
TIMEOUT = 30


def _app_root() -> Optional[Path]:
    """Where the installed package lives -- the directory holding
    `automations/`. Derived from this very file, so it is right wherever the
    office put it."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "automations" / "icd_alerts" / "run.py").is_file():
            return parent
    return None


def due(today: Optional[dt.date] = None) -> bool:
    """Once a day. A stamp rather than a timer: the machine sleeps, and a
    timer that counted uptime would pull three times on a Monday and none on
    a Friday."""
    today = today or C.today()
    try:
        return STAMP.read_text().strip() != today.isoformat()
    except OSError:
        return True


def _stamp(today: Optional[dt.date] = None) -> None:
    try:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text((today or C.today()).isoformat())
    except OSError:
        pass


def _ssl_ctx():
    from automations.icd_alerts import relay as R
    return R._ssl_context()


def _fetch(path: str, bust: str) -> bytes:
    req = urllib.request.Request("%s/%s?t=%s" % (RAW, path, bust),
                                 headers={"User-Agent": "lucy-selfupdate"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_ctx()) as r:
        return r.read()


def _verify(root: Path) -> bool:
    """Does the agent actually import from here? In a SUBPROCESS, because
    importing it in this process would tell us only that the code already
    running still runs."""
    try:
        p = subprocess.run(
            [sys.executable, "-c", "import automations.icd_alerts.run"],
            cwd=str(root), capture_output=True, timeout=120)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def run(log=print, today: Optional[dt.date] = None) -> bool:
    """Update if due. Returns True only when files were actually replaced.

    NEVER RAISES. This runs at the top of every sweep, and an office's numbers
    must not be lost because GitHub was slow.
    """
    if not due(today):
        return False
    root = _app_root()
    if root is None:
        log("self-update: cannot find the installed copy; skipping")
        return False

    bust = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        listing = _fetch(LIST_PATH, bust).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — no wifi is the usual reason
        log("self-update: could not reach the update server (%s)"
            % type(e).__name__)
        return False

    wanted: List[str] = [ln.strip() for ln in listing.splitlines()
                         if ln.strip() and not ln.strip().startswith("#")]
    if not wanted:
        log("self-update: the file list came back empty; not touching anything")
        return False

    staging = Path(tempfile.mkdtemp(prefix="lucy-update-"))
    try:
        for rel in wanted:
            try:
                data = _fetch(rel, bust)
            except Exception as e:  # noqa: BLE001
                log("self-update: could not fetch %s (%s) -- leaving this "
                    "machine on the version it has" % (rel, type(e).__name__))
                return False
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        # The package needs its __init__ files to import from staging at all.
        for rel in wanted:
            part = staging
            for seg in Path(rel).parts[:-1]:
                part = part / seg
                init = part / "__init__.py"
                if not init.exists():
                    init.write_text("")

        if not _verify(staging):
            log("self-update: the new code did not import -- NOT installing "
                "it. This office stays on the version it has.")
            _report("downloaded update did not import; not installed")
            _stamp(today)          # do not retry the same bad push all day
            return False

        # Keep the current copy until the new one has proved itself in place.
        backup = Path(tempfile.mkdtemp(prefix="lucy-backup-"))
        replaced = 0
        for rel in wanted:
            live = root / rel
            if live.exists():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(live, backup / rel)
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / rel, live)
            replaced += 1

        if not _verify(root):
            log("self-update: the update broke this copy -- putting it back.")
            for rel in wanted:
                saved = backup / rel
                if saved.exists():
                    shutil.copy2(saved, root / rel)
            _report("update installed but would not import; rolled back")
            _stamp(today)
            return False

        _stamp(today)
        log("self-update: updated %d file(s). The next run uses them."
            % replaced)
        return True
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _report(summary: str) -> None:
    """Tell us a machine could not update. Best effort, never raises."""
    try:
        from automations.icd_alerts import relay as R
        R.report_fault("update", summary)
    except Exception:  # noqa: BLE001
        pass
