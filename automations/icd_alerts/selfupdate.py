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

  * ONLY WHEN WE SAY SO. The agent reads one small file each sweep and pulls
    nothing unless its release number has moved, so work can land in main
    without reaching anybody -- and a fix we HAVE published arrives within a
    sweep rather than the next morning (Megan 2026-09-16: "we need it where
    we can push the updates we make to their machines"). A daily check stays
    underneath it as the floor.
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

# --- PUSHING A FIX, RATHER THAN WAITING A DAY FOR IT ------------------------
#
# Megan, 2026-09-16: "we need it where we can push the updates we make to their
# machines."
#
# Code already reaches the offices on its own -- but once a day, so a fix made
# at ten in the morning landed the following morning. Today that meant Ryan
# pasting a broken command twice while the correction sat in main.
#
# WHAT THIS IS NOT: a poll of the whole bundle every couple of minutes. That
# is twenty-odd files per office per sweep for a tree that changes a few times
# a week, and it multiplies the chance of catching a half-pushed one.
#
# Instead the agent reads ONE SMALL FILE each sweep. If its contents match
# what this machine already applied, nothing else happens -- one request, a
# few bytes. If they differ, the full verified update runs immediately.
#
# THE NUMBER IS BUMPED DELIBERATELY, NOT BY EVERY COMMIT. That is the part
# that makes this a push rather than a race: work lands in main as usual and
# reaches nobody, and when a change is actually ready to go out, RELEASE is
# raised and every office picks it up within one sweep. A tree caught
# mid-push carries the old number and is ignored.
RELEASE_PATH = "automations/icd_alerts/agent_release.txt"
APPLIED = C.APP_DIR / "agent-release.txt"


def _app_root() -> Optional[Path]:
    """Where the installed package lives -- the directory holding
    `automations/`. Derived from this very file, so it is right wherever the
    office put it."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "automations" / "icd_alerts" / "run.py").is_file():
            return parent
    return None


def applied_release() -> str:
    try:
        return APPLIED.read_text().strip()
    except OSError:
        return ""


def published_release() -> Optional[str]:
    """What we have asked the offices to be on, or None if we cannot tell.

    None is not "no update". A machine that cannot reach GitHub must fall
    back to the daily rule rather than either updating on nothing or deciding
    it is current -- both of those turn a flaky connection into a fleet that
    silently stops tracking main.
    """
    try:
        got = _fetch(RELEASE_PATH, dt.datetime.now().strftime("%Y%m%d%H%M%S"))
        text = got.decode("utf-8", "replace").strip()
        # A whole HTML error page is not a version. Anything that is not a
        # short token is treated as "could not tell".
        return text if text and len(text) <= 40 and "\n" not in text else None
    except Exception:  # noqa: BLE001 — offline, rate-limited, slow
        return None


def due(today: Optional[dt.date] = None) -> bool:
    """Is there anything to pull?

    TWO REASONS, and the fast one first. A published release this machine has
    not applied means a fix is waiting, and waiting is the thing this exists
    to stop -- so it pulls on the next sweep rather than the next morning.

    The daily stamp stays as the floor: it is what catches a machine whose
    release check cannot reach GitHub, and what every office ran on before
    releases existed.
    """
    published = published_release()
    if published and published != applied_release():
        return True
    today = today or C.today()
    try:
        return STAMP.read_text().strip() != today.isoformat()
    except OSError:
        return True


def _stamp(today: Optional[dt.date] = None,
           release: Optional[str] = None) -> None:
    """Record that this machine has dealt with today, and with this release.

    THE RELEASE IS RECORDED ON FAILURE TOO, deliberately -- every caller here
    passes it, including the rollback path. A bad push that left the machine
    on its old code must not be retried every two minutes for the rest of the
    day: it would be a loop of downloads, failed imports and rollbacks on a
    computer nobody can reach, and the fault it reports is already on its way
    to us. The daily rule still retries it tomorrow.
    """
    try:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text((today or C.today()).isoformat())
        if release:
            APPLIED.write_text(release)
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
    if (root / ".git").exists():
        # A DEVELOPMENT CHECKOUT, NOT AN INSTALL. Installs are plain folders
        # under ~/.lucy-reports/app; a .git beside `automations/` means this
        # is the repo, and overwriting it with GitHub's copies deletes every
        # uncommitted edit to these 29 files -- other people's included. It
        # happened on 2026-09-21: a test ran a sweep in Megan's checkout and
        # this silently reverted a fix that was mid-way to being committed.
        log("self-update: %s is a git checkout, not an install; skipping" % root)
        return False

    # READ ONCE, at the top. Asking again after the files are in would risk
    # recording a release we did not actually install -- somebody could
    # publish a second one in the seconds between -- and this machine would
    # then believe it was current and stop pulling.
    release = published_release()
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
            _stamp(today, release)          # do not retry the same bad push all day
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
            _stamp(today, release)
            return False

        _stamp(today, release)
        log("self-update: updated %d file(s). The next run uses them."
            % replaced)
        # AND THE SCHEDULE, which is code's blind spot: setup.py wrote the
        # LaunchAgent once at install time and nothing has revisited it since,
        # so a cadence change would otherwise reach new offices only. Here and
        # not in run.py: this is the point at which the new code is proven in
        # place, and the retime belongs to the code that asked for it.
        try:
            from automations.icd_alerts import sweep_cadence
            sweep_cadence.ensure(log=log)
        except Exception as e:  # noqa: BLE001 — an update is not worth losing
            log("self-update: schedule check skipped (%s)" % type(e).__name__)
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
