"""Daily Rep Breakdown - ATT Program — the one-click daily runner.

This is the Hub-button entrypoint. It orchestrates the full pipeline:

  Monday:   full wipe -> scrape ALL days -> Tableau -> full cosmetic pass
  Tue-Sun:  scrape TODAY only -> incremental -> Tableau -> skip-unchanged
  Both:     refresh tab colors + Mac notification on success/failure

Why Monday is special: per Raf, each Monday the previous week is
overwritten so terminated reps drop off. A wipe gives a clean slate.
Mid-week, reps are never removed -- a rep terminated Wednesday keeps
their Mon/Tue data visible, and a rep who first appears Wednesday is
added.

Prereq: debug Chrome at :9222 with ownerville logged in. Tableau SSO is
bootstrapped automatically from the ownerville session (step7).

Run:
    .venv/bin/python -m automations.focus_office_att.daily
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
CDP_URL = "http://localhost:9222"
WORKSPACE = Path(__file__).resolve().parents[2]
# The interpreter currently running this file — correct on macOS, Windows,
# and Linux. (A hardcoded ".venv/bin/python" only exists on macOS/Linux;
# Windows venvs put it at ".venv\Scripts\python.exe".)
PYTHON = sys.executable
LOG_DIR = WORKSPACE / "output" / "logs"
SCRAPE_RESULTS = WORKSPACE / "output" / "focus_office_scrape_results.json"

TABLEAU_ONLY_MARK = "\U0001f539"  # blue diamond emoji

# Tabs that are not owner reports — never scraped, never colored.
NON_OWNER_TABS = {"Template", "Raf play"}

# Tab colors
AMBER = {"red": 0.96, "green": 0.69, "blue": 0.26}       # pending OV access
LIGHT_BLUE = {"red": 0.62, "green": 0.76, "blue": 0.91}  # has Tableau-only reps


# ----------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------
def _chrome_ok() -> tuple[bool, str]:
    """Return (ok, message). ok=True iff debug Chrome is reachable AND an
    ownerville tab is open (logged-in session is assumed if the tab is
    on a v2.ownerville.com URL with an rqst param)."""
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json", timeout=4) as r:
            tabs = json.loads(r.read())
    except Exception:
        return False, "Debug Chrome isn't running on port 9222."
    ov = [t for t in tabs if "ownerville" in (t.get("url") or "").lower()]
    if not ov:
        return False, "Chrome is open but no ownerville tab is logged in."
    return True, "Chrome + ownerville OK."


# ----------------------------------------------------------------------
# Monday wipe
# ----------------------------------------------------------------------
def wipe_all_owner_tabs(sh) -> int:
    """Clear rep rows + static formatting on every owner tab (rows 3-200,
    cols A-CR). Leaves rows 1-2 (banners + headers) + conditional rules.
    Returns the count of tabs wiped. Monday-only."""
    import time
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    for ws in tabs:
        ws.batch_clear(["A3:CR200"])
        ws.spreadsheet.batch_update({"requests": [{
            "updateCells": {
                "range": {"sheetId": ws.id, "startRowIndex": 2, "endRowIndex": 200,
                          "startColumnIndex": 0, "endColumnIndex": 96},
                "fields": "userEnteredFormat",
            },
        }]})
        time.sleep(2.0)  # stay under Sheets write quota
    return len(tabs)


# ----------------------------------------------------------------------
# Tab colors
# ----------------------------------------------------------------------
def refresh_tab_colors(sh) -> dict:
    """Recolor owner tabs:
      - amber      = owner not scraped OK this run (pending OV access)
      - light blue = tab has Tableau-only reps (a sale but no OV activity)
      - no color   = fully matched

    Pending status is read from focus_office_scrape_results.json (written
    by run_all_owners). Self-maintaining: when an owner's access lands and
    they scrape OK, they drop out of the pending set automatically."""
    import time

    pending: set[str] = set()
    if SCRAPE_RESULTS.exists():
        try:
            data = json.loads(SCRAPE_RESULTS.read_text())
            pending = {o for o, s in data.get("results", {}).items() if s != "ok"}
        except Exception:
            pending = set()
    pending -= NON_OWNER_TABS

    counts = {"amber": 0, "light_blue": 0, "none": 0}
    requests = []
    for ws in sh.worksheets():
        if ws.title in NON_OWNER_TABS:
            continue
        if ws.title in pending:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "tabColor": AMBER},
                "fields": "tabColor",
            }})
            counts["amber"] += 1
            continue
        col_b = ws.col_values(2)
        has_tableau_only = any(TABLEAU_ONLY_MARK in (v or "") for v in col_b)
        if has_tableau_only:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "tabColor": LIGHT_BLUE},
                "fields": "tabColor",
            }})
            counts["light_blue"] += 1
        else:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "tabColorStyle": {"rgbColor": {}}},
                "fields": "tabColorStyle",
            }})
            counts["none"] += 1
        time.sleep(0.05)

    if requests:
        sh.batch_update({"requests": requests})
    return counts


# ----------------------------------------------------------------------
# Desktop notifications — cross-platform (macOS + Windows)
# ----------------------------------------------------------------------
_NOTIFY_TITLE = "Daily Rep Breakdown - ATT Program"
_IS_WINDOWS = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"


def _win_popup(message: str, *, failure: bool) -> None:
    """Show a Windows popup via a .NET MessageBox (built into Windows — no
    install needed). The script is base64-encoded and passed via
    -EncodedCommand so quotes/newlines in the message can't break it.
    Fire-and-forget (Popen) so the run never blocks on the popup."""
    icon = "Warning" if failure else "Information"
    safe = message.replace("'", "''")  # PowerShell single-quote escape
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "[System.Windows.Forms.MessageBox]::Show("
        f"'{safe}','{_NOTIFY_TITLE}','OK','{icon}') | Out-Null"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
         "-EncodedCommand", encoded]
    )


def _notify_success(msg: str) -> None:
    try:
        if _IS_WINDOWS:
            _win_popup(msg, failure=False)
        elif _IS_MAC:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{msg}" with title "{_NOTIFY_TITLE}"'],
                check=False, timeout=10,
            )
    except Exception:
        pass


def _notify_failure(headline: str, detail: str, log_file: str) -> None:
    try:
        if _IS_WINDOWS:
            _win_popup(f"{headline}\n\n{detail}\n\nLog: {log_file}",
                       failure=True)
        elif _IS_MAC:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{headline} Tap for details." '
                 f'with title "{_NOTIFY_TITLE}" sound name "Sosumi"'],
                check=False, timeout=10,
            )
            dialog = (
                f'display dialog "{headline}\n\n{detail}\n\nLog: {log_file}" '
                f'buttons {{"OK"}} default button 1 with icon caution'
            )
            subprocess.run(["osascript", "-e", dialog], check=False, timeout=120)
    except Exception:
        pass


# ----------------------------------------------------------------------
# Phase runners (subprocess — each phase has its own CLI entrypoint)
# ----------------------------------------------------------------------
def _run_phase(module: str, extra_args: list[str], log_fh) -> int:
    """Run a pipeline module as a subprocess, streaming output to log_fh.
    Returns the process exit code."""
    cmd = [PYTHON, "-m", module, *extra_args]
    log_fh.write(f"\n$ {' '.join(cmd)}\n")
    log_fh.flush()
    proc = subprocess.run(cmd, stdout=log_fh, stderr=subprocess.STDOUT, cwd=str(WORKSPACE))
    return proc.returncode


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_path = LOG_DIR / f"focus-office-daily-{stamp}.log"
    today = dt.date.today()
    is_monday = today.weekday() == 0

    with open(log_path, "w") as log:
        def say(m: str) -> None:
            print(m, flush=True)
            log.write(m + "\n")
            log.flush()

        say(f"=== Daily Rep Breakdown - ATT Program — {today.isoformat()} "
            f"({'MONDAY full run' if is_monday else 'mid-week incremental'}) ===")

        # 1. Pre-flight
        ok, msg = _chrome_ok()
        say(f"Pre-flight: {msg}")
        if not ok:
            _notify_failure(
                "Focus Office run can't start.",
                f"{msg}\n\nFix: launch the debug Chrome + log into ownerville, "
                f"then click Run again.",
                str(log_path),
            )
            return 1

        sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

        # 2. Monday wipe
        if is_monday:
            say("Monday: wiping all owner tabs for a clean week...")
            try:
                n = wipe_all_owner_tabs(sh)
                say(f"  wiped {n} tab(s)")
            except Exception as e:
                say(f"  wipe failed: {e}")
                _notify_failure("Focus Office Monday wipe failed.",
                                str(e), str(log_path))
                return 1

        # 3. Phase 2 — ownerville scrape
        say("Phase 2: ownerville scrape...")
        phase2_args = [] if is_monday else ["--today-only"]
        rc2 = _run_phase("automations.focus_office_att.run_all_owners",
                         phase2_args, log)
        # run_all_owners exits non-zero when SOME owners were skipped — that's
        # expected (pending-access owners). A genuine failure = no results
        # file written.
        if not SCRAPE_RESULTS.exists():
            say("  Phase 2 crashed — no results file written.")
            _notify_failure("Focus Office scrape (Phase 2) crashed.",
                            "ownerville scrape didn't complete. "
                            "Chrome/ownerville session may have dropped.",
                            str(log_path))
            return 1
        say(f"  Phase 2 done (exit {rc2}).")

        # 4. Phase 3 — Tableau download + fill
        say("Phase 3: Tableau auto-download (CSV) + Sheet fill...")
        rc3 = _run_phase("automations.focus_office_att.step7_download_tableau",
                         ["--format", "csv", "--fill"], log)
        if rc3 != 0:
            say(f"  Phase 3 failed (exit {rc3}).")
            _notify_failure(
                "Focus Office Tableau pull (Phase 3) failed.",
                "ownerville scrape DID complete — only the Tableau sale-type "
                "data is missing. The Tableau tab may need a fresh login.",
                str(log_path))
            # Phase 2 data is still good — colors still worth refreshing.
            try:
                refresh_tab_colors(sh)
            except Exception:
                pass
            return 1
        say("  Phase 3 done.")

        # 5. Tab colors
        say("Refreshing tab colors...")
        try:
            counts = refresh_tab_colors(sh)
            say(f"  amber={counts['amber']} (pending access), "
                f"light blue={counts['light_blue']} (Tableau-only reps), "
                f"plain={counts['none']}")
        except Exception as e:
            say(f"  tab-color refresh failed (non-fatal): {e}")

        say("=== DONE ===")

    _notify_success(
        f"{'Monday full' if is_monday else 'Daily'} run complete — "
        f"all 30 tabs refreshed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
