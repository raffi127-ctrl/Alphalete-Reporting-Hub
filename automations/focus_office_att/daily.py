"""Daily Rep Breakdown - ATT Program — the one-click daily runner.

This is the Hub-button entrypoint. It orchestrates the full pipeline:

  Monday:   full wipe -> scrape ALL days -> Tableau -> full cosmetic pass
  Tue-Sun:  re-scrape yesterday + today -> incremental -> Tableau -> skip-unchanged
  Both:     refresh tab colors + desktop notification on success/failure

Why Monday is special: per Raf, each Monday the previous week is
overwritten so terminated reps drop off. A wipe gives a clean slate.
Mid-week, reps are never removed -- a rep terminated Wednesday keeps
their Mon/Tue data visible, and a rep who first appears Wednesday is
added.

Why mid-week re-scrapes yesterday: a same-day scrape only ever sees a
partial day, so today's numbers are always incomplete until tomorrow's
run re-pulls the now-finished day.

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
# Resume checkpoint written by run_all_owners (Phase 2). That module owns
# it; daily.py only deletes it — after the Monday wipe (a wipe blanks the
# sheet, so a resume would skip owners whose data is now gone) and after a
# fully successful run. A file that survives a run means it was interrupted.
RUN_CHECKPOINT = WORKSPACE / "output" / "focus_office_run_checkpoint.json"

TABLEAU_ONLY_MARK = "\U0001f539"  # blue diamond emoji

# Tabs that are not owner reports — never scraped, never colored.
NON_OWNER_TABS = {"Template", "Raf play"}

# Tab colors
AMBER = {"red": 0.96, "green": 0.69, "blue": 0.26}       # pending OV access
LIGHT_BLUE = {"red": 0.62, "green": 0.76, "blue": 0.91}  # has Tableau-only reps


def _q(title: str) -> str:
    """A1-notation-safe single-quoted tab title (escapes embedded quotes)."""
    return "'" + title.replace("'", "''") + "'"


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
# Future-day wipe — Tue-Sat: clear cells for days AFTER today this week.
# Without this, last week's Wed-Sun data lingers in the same columns when
# the week rolls over (since the column headers change but the cell values
# don't until something writes them). Sunday has nothing to clear.
# ----------------------------------------------------------------------
def wipe_future_day_blocks(sh, today: "dt.date") -> int:
    """Clear cells in day-blocks for days AFTER `today` (this week).
    Each day spans 12 cols starting at col 13 (Mon). Clears both values
    and userEnteredFormat in rows 3-200. No-op on Sunday."""
    dow = today.weekday()    # 0=Mon..6=Sun
    first_future_col = 13 + (dow + 1) * 12   # 0-indexed column to start clearing
    if first_future_col > 96:
        return 0   # Sun — nothing after today
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return 0
    # A1 letters for the range
    def _coletter(c: int) -> str:
        s = ""
        while c > 0:
            c, r = divmod(c - 1, 26)
            s = chr(65 + r) + s
        return s
    rng = f"{_coletter(first_future_col)}3:{_coletter(96)}200"
    sh.values_batch_clear(body={"ranges": [f"{_q(t.title)}!{rng}" for t in tabs]})
    sh.batch_update({"requests": [
        {"updateCells": {
            "range": {"sheetId": t.id,
                      "startRowIndex": 2, "endRowIndex": 200,
                      "startColumnIndex": first_future_col - 1,
                      "endColumnIndex": 96},
            "fields": "userEnteredFormat",
        }} for t in tabs
    ]})
    return len(tabs)


# Day-block column-group ranges (0-indexed half-open) — Mon..Sun.
# These match the pre-existing depth=2 column groups Sheets already has on
# every owner tab, exactly. Each block is 11 cols; the 1-col gap between
# blocks (col 24, 36, 48, ...) is where the group's +/- toggle button
# lives, so it's intentionally NOT part of the group.
_DAY_BLOCK_RANGES = [
    (13, 24),  # Mon = N:X
    (25, 36),  # Tue = Z:AJ
    (37, 48),  # Wed = AL:AV
    (49, 60),  # Thu = AX:BH
    (61, 72),  # Fri = BJ:BT
    (73, 84),  # Sat = BV:CF
    (85, 96),  # Sun = CH:CR
]


def set_day_column_collapsed(sh, today: "dt.date") -> int:
    """Collapse day-block column GROUPS for days AFTER today; expand days
    up to and including today. Uses the pre-existing depth=2 column groups
    so the +/- toggle button stays visible at the top — Megan wants the
    user to be able to expand a collapsed day with one click, not just
    have the columns silently hidden.

    Sets BOTH the group's `collapsed` flag AND the underlying columns'
    `hiddenByUser` flag in the same batch — the Sheets API doesn't tie
    them together automatically (a group can be marked collapsed while
    its columns stay visible, which is what was breaking the visual
    effect before). The collapsed flag drives the +/- button, the
    hiddenByUser flag actually hides the columns; together they give
    Megan the expand-on-click UX she asked for. Idempotent."""
    dow = today.weekday()    # 0=Mon..6=Sun
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return 0
    requests = []
    for t in tabs:
        for day_idx, (start, end) in enumerate(_DAY_BLOCK_RANGES):
            should_collapse = (day_idx > dow)
            # 1. Group's collapsed state (controls the +/- button glyph).
            requests.append({"updateDimensionGroup": {
                "dimensionGroup": {
                    "range": {"sheetId": t.id, "dimension": "COLUMNS",
                              "startIndex": start, "endIndex": end},
                    "depth": 2,
                    "collapsed": should_collapse,
                },
                "fields": "collapsed",
            }})
            # 2. Columns' hiddenByUser (actually hides them visually).
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": t.id, "dimension": "COLUMNS",
                          "startIndex": start, "endIndex": end},
                "properties": {"hiddenByUser": should_collapse},
                "fields": "hiddenByUser",
            }})
    sh.batch_update({"requests": requests})
    return len(tabs)


# ----------------------------------------------------------------------
# Monday wipe
# ----------------------------------------------------------------------
def wipe_all_owner_tabs(sh) -> int:
    """Clear rep rows + static formatting on every owner tab (rows 3-200,
    cols A-CR). Leaves rows 1-2 (banners + headers) + conditional rules.
    Returns the count of tabs wiped. Monday-only.

    Batched: one values-clear call + one format-clear call covering ALL
    tabs, instead of two calls (plus a 2s sleep) per tab."""
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return 0
    # One values-clear covering A3:CR200 on every owner tab. gspread's
    # values_batch_clear takes the ranges in the request body (its first
    # positional arg is `params`, not `ranges`).
    sh.values_batch_clear(body={"ranges": [f"{_q(t.title)}!A3:CR200" for t in tabs]})
    # One format-clear (updateCells) covering rows 3-200 on every owner tab.
    sh.batch_update({"requests": [
        {"updateCells": {
            "range": {"sheetId": t.id, "startRowIndex": 2, "endRowIndex": 200,
                      "startColumnIndex": 0, "endColumnIndex": 96},
            "fields": "userEnteredFormat",
        }}
        for t in tabs
    ]})
    return len(tabs)


# ----------------------------------------------------------------------
# No-access banner — visible warning ON the tab itself
# ----------------------------------------------------------------------
# Light red bg + dark red bold text — same palette as the financial
# "Not Found In Email" marker so the visual language stays consistent.
_BANNER_BG = {"red": 1.0, "green": 0.78, "blue": 0.76}
_BANNER_FG = {"red": 0.78, "green": 0.15, "blue": 0.12}


def _banner_text_for(status: str) -> str:
    """Pick the right actionable banner text from a per-owner failure
    status string written to scrape_results.json by run_all_owners.

    Each status maps to ONE action a viewer can take — Megan/Raf
    shouldn't have to decode raw status strings like 'exception:
    TimeoutError:...'; the log has those for debugging."""
    s = (status or "").lower()
    # OV's "Office Access" table only lists offices the current login HAS
    # access to. If a name isn't in the table, the user doesn't have
    # access — not a name drift. Same banner as an explicit impersonate
    # denial; the actionable fix is the same (request OV access).
    if "name not found" in s or "no ov access" in s or "impersonate denied" in s:
        return "❌ NO OWNERVILLE ACCESS — request access"
    if "access request pending" in s or "request sent" in s:
        return "⏳ OWNERVILLE ACCESS REQUEST PENDING — waiting on approval"
    if "no impersonate button" in s or "office may be disabled" in s:
        return "❌ OFFICE DISABLED IN OWNERVILLE — check OV"
    if "ov page error" in s:
        return "❌ OWNERVILLE UI ERROR — retry later"
    if "couldn't reach office access" in s:
        return "❌ COULDN'T REACH OWNERVILLE — retry later"
    if s.startswith("exception:") or "timeout" in s:
        return "❌ OWNERVILLE PULL ERROR — retry later"
    # Legacy / unknown status (e.g. older "impersonate failed" before the
    # status string got more specific) — show a generic, still-actionable
    # message rather than a misleading one.
    return "❌ COULDN'T PULL FROM OWNERVILLE — check log"


def mark_no_access_tabs(sh, pending_results: dict) -> dict:
    """Stamp a per-failure banner on tabs whose OV scrape failed, and
    clear it from tabs that scraped OK.

    `pending_results` is `{tab_name: status_string}` — only entries where
    status != "ok" should be passed in (filtering happens at the call
    site). The banner text is chosen per-status by `_banner_text_for`
    so the viewer knows what to do (add alias vs request access vs retry).

    Banner lives at A1:B1 — those cells are empty by design (col C
    onward holds the merged weekly/per-day banners and is off-limits;
    row 2 holds the column headers). Merged into a single visible cell
    with light-red bg + dark-red bold text. Idempotent."""
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return {"marked": 0, "cleared": 0}
    requests = []
    marked = cleared = 0
    for t in tabs:
        status = pending_results.get(t.title)
        is_pending = bool(status)
        # Unmerge first — safe to do on a non-merged range (Sheets ignores).
        # Lets us re-write A1:B1 cleanly in either branch.
        requests.append({"unmergeCells": {
            "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 2},
        }})
        if is_pending:
            requests.append({"mergeCells": {
                "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 2},
                "mergeType": "MERGE_ALL",
            }})
            requests.append({"updateCells": {
                "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 1},
                "fields": "userEnteredValue,userEnteredFormat",
                "rows": [{"values": [{
                    "userEnteredValue": {"stringValue": _banner_text_for(status)},
                    "userEnteredFormat": {
                        "backgroundColor": _BANNER_BG,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {
                            "foregroundColor": _BANNER_FG,
                            "bold": True, "fontSize": 11,
                        },
                        "wrapStrategy": "WRAP",
                    },
                }]}],
            }})
            marked += 1
        else:
            # Wipe the banner — blank the cells + clear formatting
            requests.append({"updateCells": {
                "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 2},
                "fields": "userEnteredValue,userEnteredFormat",
                "rows": [{"values": [
                    {"userEnteredValue": {"stringValue": ""}, "userEnteredFormat": {}},
                    {"userEnteredValue": {"stringValue": ""}, "userEnteredFormat": {}},
                ]}],
            }})
            cleared += 1
    sh.batch_update({"requests": requests})
    return {"marked": marked, "cleared": cleared}


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
    pending: set[str] = set()
    if SCRAPE_RESULTS.exists():
        try:
            data = json.loads(SCRAPE_RESULTS.read_text())
            pending = {o for o, s in data.get("results", {}).items() if s != "ok"}
        except Exception:
            pending = set()
    pending -= NON_OWNER_TABS

    owner_tabs = [ws for ws in sh.worksheets() if ws.title not in NON_OWNER_TABS]
    # One batched read of column B for every non-pending owner tab. Pending
    # tabs go amber without needing their contents, so they're not read.
    to_read = [ws for ws in owner_tabs if ws.title not in pending]
    col_b: dict[str, list[str]] = {}
    if to_read:
        resp = sh.values_batch_get([f"{_q(ws.title)}!B:B" for ws in to_read])
        for ws, vr in zip(to_read, resp.get("valueRanges", [])):
            col_b[ws.title] = [(row[0] if row else "")
                               for row in vr.get("values", [])]

    counts = {"amber": 0, "light_blue": 0, "none": 0}
    requests = []
    for ws in owner_tabs:
        if ws.title in pending:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "tabColor": AMBER},
                "fields": "tabColor",
            }})
            counts["amber"] += 1
            continue
        has_tableau_only = any(
            TABLEAU_ONLY_MARK in (v or "") for v in col_b.get(ws.title, [])
        )
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
# Phase-level hard caps. A phase that exceeds these is killed (the scrape
# resumes from its checkpoint on the next run) so a single hung owner or a
# stuck Tableau load can never silently stall the whole report for an hour
# (Eve's run sat at 62 min before someone stopped it, 2026-05-31). Generous
# vs. the ~15 min normal total, so a legit slow Monday won't false-trip.
PHASE_TIMEOUT_EXIT = 124  # conventional "timed out" exit code
PHASE2_TIMEOUT_S = 40 * 60
PHASE3_TIMEOUT_S = 20 * 60


def _kill_process_tree(proc: "subprocess.Popen") -> None:
    """Kill a subprocess AND its descendants (the patchright browser),
    cross-platform. Killing just the direct child leaves the browser holding
    the stdout pipe, so the parent's read never returns."""
    import os
    import signal as _signal
    pid = proc.pid
    if _IS_WINDOWS:
        # /T = whole tree, /F = force. taskkill is always present on Windows.
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=20)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return
    # POSIX: the child was started with start_new_session=True, so its PGID
    # == its PID; signal the whole group.
    try:
        os.killpg(os.getpgid(pid), _signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
        return
    except Exception:
        pass
    try:
        os.killpg(os.getpgid(pid), _signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_phase(module: str, extra_args: list[str], log_fh,
               timeout_s: int | None = None) -> int:
    """Run a pipeline module as a subprocess. Streams its output line by
    line to BOTH the run log file and this process's stdout — so the Hub,
    which captures daily.py's stdout, shows live per-owner progress (the
    scraper's "[i/N]" markers) instead of just the phase headline.

    If `timeout_s` is set, a watchdog kills the subprocess after that many
    seconds and we return PHASE_TIMEOUT_EXIT — never blocking forever.
    Returns the process exit code."""
    cmd = [PYTHON, "-m", module, *extra_args]
    header = f"\n$ {' '.join(cmd)}\n"
    log_fh.write(header)
    log_fh.flush()
    print(header, end="", flush=True)
    # Start the child in its OWN process group/session so the watchdog can
    # kill the whole TREE — the scraper spawns a patchright browser as a
    # grandchild, and killing only the direct child leaves the browser alive
    # holding the stdout pipe open (the read below would block forever, so the
    # timeout wouldn't actually unstick us). Eve runs this on Windows, so the
    # tree-kill has to work there too (taskkill /T), not just on macOS.
    popen_kw = {}
    if _IS_WINDOWS:
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, cwd=str(WORKSPACE), **popen_kw)
    timed_out = {"hit": False}
    timer = None
    if timeout_s:
        import threading

        def _kill_hung():
            timed_out["hit"] = True
            _kill_process_tree(proc)

        timer = threading.Timer(timeout_s, _kill_hung)
        timer.daemon = True
        timer.start()
    try:
        for line in proc.stdout:
            log_fh.write(line)
            log_fh.flush()
            print(line, end="", flush=True)
        proc.wait()
    finally:
        if timer:
            timer.cancel()
    if timed_out["hit"]:
        msg = (f"\n⏱ phase '{module}' exceeded {timeout_s // 60} min — killed. "
               f"Progress is checkpointed; click Run Again to resume.\n")
        log_fh.write(msg)
        log_fh.flush()
        print(msg, end="", flush=True)
        return PHASE_TIMEOUT_EXIT
    return proc.returncode


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    from automations.focus_office_att._ratelimit import install as _install_pacing
    _install_pacing()
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

        # Phase 2 (run_all_owners) and Phase 3 (step7_download_tableau) both
        # self-auth via patchright now — no more debug-Chrome pre-flight gate.
        sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

        # 2. Monday wipe (or future-day wipe Tue-Sat)
        if is_monday:
            say("Monday: wiping all owner tabs for a clean week...")
            try:
                n = wipe_all_owner_tabs(sh)
                say(f"  wiped {n} tab(s)")
                # A wipe blanks the sheet — any leftover Phase-2 checkpoint
                # is now invalid, so the scrape must start fresh.
                try:
                    RUN_CHECKPOINT.unlink(missing_ok=True)
                except Exception:
                    pass
            except Exception as e:
                say(f"  wipe failed: {e}")
                _notify_failure("Focus Office Monday wipe failed.",
                                str(e), str(log_path))
                return 1
        else:
            # Tue-Sun: clear cells for days AFTER today so last week's
            # Wed-Sun stale data doesn't leak into this week (the column
            # headers roll over but cell values don't until something
            # writes them). Sunday no-ops.
            say("Clearing future-day blocks (post-today, this week)...")
            try:
                n = wipe_future_day_blocks(sh, today)
                say(f"  cleared future blocks on {n} tab(s)")
            except Exception as e:
                say(f"  future-day clear failed (non-fatal): {e}")

        # Collapse future-day column GROUPS so empty days are hidden
        # behind a +/- toggle the user can click to peek at them.
        # Idempotent — runs every day so collapse state tracks the date.
        say("Collapsing future-day column groups...")
        try:
            n = set_day_column_collapsed(sh, today)
            say(f"  collapse state set on {n} tab(s)")
        except Exception as e:
            say(f"  collapse set failed (non-fatal): {e}")

        # 3. Phase 2 — ownerville scrape
        say("Phase 2: ownerville scrape...")
        phase2_args = [] if is_monday else ["--daily-window"]
        rc2 = _run_phase("automations.focus_office_att.run_all_owners",
                         phase2_args, log, timeout_s=PHASE2_TIMEOUT_S)
        if rc2 == PHASE_TIMEOUT_EXIT:
            say(f"  Phase 2 TIMED OUT after {PHASE2_TIMEOUT_S // 60} min — "
                f"likely one owner hung the scrape.")
            _notify_failure(
                "Focus Office scrape (Phase 2) timed out.",
                f"The ownerville scrape ran past {PHASE2_TIMEOUT_S // 60} min "
                "and was stopped — usually one owner's page hung. Progress is "
                "checkpointed, so click Run Again to resume where it left off.",
                str(log_path))
            return 1
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
                         ["--format", "csv", "--fill"], log,
                         timeout_s=PHASE3_TIMEOUT_S)
        if rc3 == PHASE_TIMEOUT_EXIT:
            say(f"  Phase 3 TIMED OUT after {PHASE3_TIMEOUT_S // 60} min.")
            _notify_failure(
                "Focus Office Tableau pull (Phase 3) timed out.",
                "The ownerville scrape completed; only the Tableau sale-type "
                "pull hung. Click Run Again — Phase 2 won't re-scrape.",
                str(log_path))
            try:
                refresh_tab_colors(sh)
            except Exception:
                pass
            return 1
        if rc3 != 0:
            say(f"  Phase 3 failed (exit {rc3}).")
            _notify_failure(
                "Focus Office Tableau pull (Phase 3) failed.",
                "ownerville scrape DID complete — only the Tableau sale-type "
                "data is missing. Usually a transient patchright/Tableau "
                "load issue — click Run Again.",
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

        # 6. Per-failure banners on the sheet tabs — each pending owner
        # gets an actionable banner ("add alias" vs "request access" vs
        # "retry later") based on their failure status. Everyone else has
        # the banner cleared. Idempotent.
        say("Stamping per-failure banners on pending tabs...")
        try:
            pending_results: dict = {}
            if SCRAPE_RESULTS.exists():
                try:
                    data = json.loads(SCRAPE_RESULTS.read_text())
                    pending_results = {o: s for o, s in data.get("results", {}).items()
                                       if s != "ok" and o not in NON_OWNER_TABS}
                except Exception:
                    pending_results = {}
            banner_counts = mark_no_access_tabs(sh, pending_results)
            say(f"  banner marked on {banner_counts['marked']} tab(s), "
                f"cleared on {banner_counts['cleared']} tab(s)")
        except Exception as e:
            say(f"  banner refresh failed (non-fatal): {e}")

        say("=== DONE ===")
        # Pipeline finished cleanly — clear the Phase-2 resume checkpoint
        # so the next run starts fresh instead of resuming.
        try:
            RUN_CHECKPOINT.unlink(missing_ok=True)
        except Exception:
            pass

    _notify_success(
        f"{'Monday full' if is_monday else 'Daily'} run complete — "
        f"all 30 tabs refreshed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
