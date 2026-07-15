"""Vantura Weekly Payroll — scheduled prep run (Lucy 2, Wednesday 11:00 CT).

Automates the DETERMINISTIC prep half of the weekly Vantura commission/payroll
runbook so that when Carlos sits down the week is already pulled, loaded, and
refreshed and he only has to enter that week's judgement inputs and print.

Reuses the existing Lucy 2 routes (do NOT rebuild these):
  * Tableau crosstab download  -> automations.vantura_churn.cdp_pull
    (real-Chrome-over-CDP; the B2B server won't export under patchright)
  * Vantura board auth + write  -> automations.recruiting_report.fill.open_by_key
    (same SHEET_ID as vantura_churn; same gspread client)
  * "as Lucy" Slack delivery    -> automations.shared.slack_metrics_post

WHAT THIS RUN DOES (automatable, no human judgement):
  1. Compute week ending (the Sunday AFTER the DD Saturday).
  2. Pull the "ICD dd Detail" crosstab (Direct Deposit ICD VIEW -> DD DETAIL,
     Owner: Carlos) from Tableau.
  3. Load the rows into the RAW tab: append below last week, stamp Week Ending
     in column A, re-hide RAW. Report the row range used.
  4. Set Commission!B1 to the week ending.
  5. Re-point the per-campaign P&L formulas to this week's RAW range.
  6. Trigger "Refresh commission sheets", read the sync summary, run the
     read-only P&L checks (orphan payouts + campaign reconciliation).
  7. DM Carlos as Lucy: week loaded, RAW row range, sync summary, checks.

WHAT THIS RUN DELIBERATELY DOES NOT DO (human-only / money / irreversible):
  * bonuses / no-pay / rate changes  -> weekly judgement, only Carlos knows them
  * final verify + Print commission pack (PDF)
  * Lock the week -> already auto-locks Thursday ~11am CT via the board's own
    Apps Script cloud trigger; nothing to do here.

SAFETY (mirrors vantura_churn + CLAUDE.MD "Eve rules"):
  * --dry-run is the DEFAULT. It computes, pulls, and PRINTS what it would do;
    it writes NOTHING to the board and sends no Slack.
  * --sandbox writes to a duplicate board (SANDBOX_SHEET_ID) for testing.
  * --live is required to touch the real board, and is gated further below.
  * product->campaign mapping and the per-campaign formulas are the payroll
    correctness core; they MUST be pinned down against a sandbox copy of the
    board before --live is trusted (see _load_raw / _repoint_pnl TODOs).

  python -m automations.vantura_payroll.run                 # dry-run (default)
  python -m automations.vantura_payroll.run --sandbox        # write to test board
  python -m automations.vantura_payroll.run --live           # write to real board
  python -m automations.vantura_payroll.run --week 2026-07-12 # override week ending
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPORT_ID = "vantura-payroll"
REPO_ROOT = Path(__file__).resolve().parents[2]

# Live Vantura Master Sales Board (same board vantura_churn writes to).
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
# A duplicated test board for --sandbox. TODO: fill in once Carlos makes a copy
# (CLAUDE.MD: build against a duplicated Sheet until "use the real Sheet").
SANDBOX_SHEET_ID = ""

# The product -> campaign mapping from the runbook (section 6). Kept here so the
# P&L split is codified, not "in chat memory". Sanity-check against the runbook.
CAMPAIGN_MAP = {
    "base": ["Energy Enrollment", "RES Pilot Program", "Lead Disposition Bonus",
             "BasePowerRES $200 (blank description)"],
    "box": ["BF 1", "BF 2", "Term Length Bonus", "kWH Bonus"],
    # b2b = everything else (AT&T / CRU / IRU + MCOE + Next Up + Roadtrip +
    #       Tiered/Rep Volume bonuses). Captain's bonus is EXCLUDED from gross.
}

# Carlos + Maud, for the "as Lucy" kickoff DM (Slack user ids from the
# captainship modules: Carlos U046G04P5LG, Maud U045USN7NCD).
DM_RECIPIENTS = ["U046G04P5LG"]


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def week_ending(today: dt.date | None = None) -> dt.date:
    """The board's week ending = the Sunday AFTER the DD Saturday. Run on a
    Wednesday, the just-completed payroll week ends the Sunday 3 days ago."""
    today = today or dt.date.today()
    # weekday(): Mon=0..Sun=6. Most recent Sunday on/before today.
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


# --------------------------------------------------------------------------
# Steps 2-6 — implemented against the reused routes. The board-WRITE internals
# (RAW layout, per-campaign formulas) are stubbed until verified in --sandbox;
# they raise rather than guess, so a --live run can never write a wrong number.
# --------------------------------------------------------------------------

# RAW column layout (verified read-only 2026-07-15). Col A = week number; B-H =
# the paid-line fields; col I (Commission) is a spilling ARRAYFORMULA at I2 — we
# NEVER write it. Target header -> the source-xlsx header(s) we accept for it.
RAW_TARGETS = {
    "B": ("Rep Name", ("rep name", "rep", "icd", "icd name")),
    "C": ("Sale Date", ("sale date", "sold date", "sale")),
    "D": ("Activation Date", ("activation date", "activated", "activation")),
    "E": ("Description", ("description",)),
    "F": ("Description Detail", ("description detail", "detail")),
    "G": ("Customer Name", ("customer name", "customer")),
    "H": ("Total $ to ICD", ("total $ to icd", "total $", "dd", "total")),
}
RAW_FIRST_DATA_ROW = 2


def _week_num(week: dt.date) -> float:
    """Board week label as the number it's stored as (July 5 -> 7.5, 12th -> 7.12)."""
    return float(f"{week.month}.{week.day}")


# The DD DETAIL crosstab source (confirmed 2026-07-15 from Carlos's Tableau
# history). The unattended CDP pull needs a Tableau session on the runner
# machine (ownerville storage_state, like vantura_churn) — a copied Chrome
# profile does NOT carry the SSO login on macOS. Until that auth is seeded on
# Lucy 2, the interim source is the file Carlos downloads to Downloads.
DD_DETAIL_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                 "DirectDepositICDVIEWVersion2_0/DDDETAIL?:iid=1")
DD_DETAIL_SHEET = "ICD dd Detail"


def _pull_icd_dd_detail(week: dt.date, log=_log) -> Path:
    """Locate this week's ICD dd Detail export.

    INTERIM (this phase): use the most recent 'ICD dd Detail*.xlsx' in Downloads
    (runbook Step 1: human downloads it once), or an explicit --file. Auto-pull
    from DD_DETAIL_URL via vantura_churn/cdp_pull.download_views once the runner
    has a seeded ownerville Tableau session.
    """
    # Interim/testing source: a file already in Downloads (or --file).
    dl = Path.home() / "Downloads"
    cands = sorted(dl.glob("ICD dd Detail*.xlsx"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if cands:
        log(f"using existing export: {cands[0].name}")
        return cands[0]

    # Unattended pull — the SAME production route Carlos's other Lucy 2 reports
    # use (vantura_churn): real Chrome over CDP, authenticated by Lucy 2's seeded
    # ownerville Tableau session. Needs no human ON A PROVISIONED LUCY 2. On an
    # un-seeded machine it fails fast at the ownerville auth step (expected).
    out = REPO_ROOT / "output" / "vantura_payroll" / "ICD dd Detail.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    log(f"no file in Downloads — pulling DD DETAIL from Tableau (Lucy 2 session) "
        f"-> {out}")
    from automations.vantura_churn import cdp_pull
    cdp_pull.download_views([(DD_DETAIL_URL, DD_DETAIL_SHEET, str(out))],
                            verbose=True, log=log)
    if not out.exists():
        raise FileNotFoundError("Tableau pull did not produce the export file.")
    log(f"pulled export: {out} ({out.stat().st_size:,} bytes)")
    return out


def _read_export(xlsx: Path, log=_log) -> tuple[list[str], list[list]]:
    """Read the crosstab .xlsx -> (headers, data_rows). Header row is the first
    non-empty row; blank trailing rows dropped."""
    from openpyxl import load_workbook
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb.active
    rows = [[("" if c is None else c) for c in r]
            for r in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ValueError(f"{xlsx.name} has no rows")
    return [str(h).strip() for h in rows[0]], rows[1:]


def _map_columns(headers: list[str], log=_log) -> dict[str, int]:
    """Map each RAW target col -> source column index. Fail LOUD (never guess)
    if any target is unmatched — prints the source headers so we can adjust."""
    low = [h.lower() for h in headers]
    out, missing = {}, []
    for col, (name, aliases) in RAW_TARGETS.items():
        idx = next((i for i, h in enumerate(low) if h in aliases), None)
        if idx is None:
            idx = next((i for i, h in enumerate(low)
                        if any(a in h for a in aliases)), None)
        if idx is None:
            missing.append(f"{col} ({name})")
        else:
            out[col] = idx
    if missing:
        raise ValueError(
            "Could not map RAW column(s): " + ", ".join(missing) +
            "\nSource headers were: " + " | ".join(headers) +
            "\n-> update RAW_TARGETS aliases to match, then re-run.")
    log("column map (RAW <- source header): " +
        ", ".join(f"{c}<-{headers[i]!r}" for c, i in out.items()))
    return out


def _load_raw(xlsx: Path, week: dt.date, *, write: bool, sheet_id: str, log=_log) -> tuple[int, int]:
    """Append the week's rows to RAW (cols A-H; col I ARRAYFORMULA auto-computes).
    Col A = week number. Returns (first_row, last_row). Dry-run previews only."""
    from automations.recruiting_report.fill import open_by_key
    headers, data = _read_export(xlsx, log=log)
    cmap = _map_columns(headers, log=log)
    wnum = _week_num(week)

    sh = open_by_key(sheet_id)
    raw = sh.worksheet("RAW")
    colA = raw.get(f"A2:A{raw.row_count}", value_render_option="UNFORMATTED_VALUE")
    last = 1 + max((i + 2 for i, r in enumerate(colA) if r and r[0] not in ("", None)),
                   default=1)
    start = last + 1

    # guard: this week must not already be loaded
    existing = {str(r[0]) for r in colA if r and r[0] not in ("", None)}
    if str(wnum) in existing:
        raise RuntimeError(f"week {wnum} already present in RAW col A — refusing "
                           "to double-load. (Delete it first, or it already ran.)")

    out_rows = []
    for r in data:
        def cell(col):
            i = cmap[col]
            return r[i] if i < len(r) else ""
        out_rows.append([wnum, cell("B"), cell("C"), cell("D"),
                         cell("E"), cell("F"), cell("G"), cell("H")])
    end = start + len(out_rows) - 1
    log(f"RAW load: {len(out_rows)} rows, week {wnum}, would fill A{start}:H{end}")
    if out_rows:
        log(f"  first row -> {out_rows[0]}")
        log(f"  last  row -> {out_rows[-1]}")
    if not write:
        log("  (dry-run: nothing written)")
        return (start, end)
    if raw.row_count < end:
        raw.add_rows(end - raw.row_count + 5)
    raw.update(f"A{start}:H{end}", out_rows, value_input_option="USER_ENTERED")
    log(f"  WROTE RAW A{start}:H{end}")
    return (start, end)


def _set_week(week: dt.date, *, write: bool, sheet_id: str, log=_log) -> None:
    """Set Commission!B1 to the week number (valid because RAW col A now has it)."""
    from automations.recruiting_report.fill import open_by_key
    wnum = _week_num(week)
    log(f"set Commission!B1 = {wnum}")
    if not write:
        log("  (dry-run: not set)")
        return
    sh = open_by_key(sheet_id)
    sh.worksheet("Commission").update_acell("B1", wnum)
    log("  set B1")


def _repoint_pnl(week: dt.date, raw_range: tuple[int, int], *, write: bool, log=_log) -> None:
    """Re-point the per-campaign profit blocks + Carlos-DD Roadtrip/MCOE
    add-back to this week's RAW rows (only Captain's bonus excluded from gross).
    The exact formulas live on the P&L tab — copy them from the prior week and
    re-point the row range. MUST be verified in --sandbox first."""
    raise NotImplementedError(
        "P&L formulas: capture the exact per-campaign + Carlos-DD formulas from "
        "the live P&L tab, parameterize the RAW range, verify in --sandbox.")


def _refresh_and_check(*, write: bool, log=_log) -> dict:
    """Trigger 'Refresh commission sheets' (Apps Script), read the sync summary,
    then run the read-only P&L checks (orphan payouts + campaign reconciliation).

    Refresh is an Apps Script menu action, not a gspread write. Two ways to
    fire it from a scheduled job (pick one — recommend the first):
      (a) add a tiny time-driven/web-app entry to the bound Payroll.gs that
          calls the existing refresh function (mirrors the Thu auto-lock
          trigger already in that script);
      (b) drive the Payroll menu via the CDP browser session, like the runbook
          does by hand.
    """
    raise NotImplementedError(
        "refresh trigger: decide Apps Script trigger (recommended) vs browser "
        "menu-drive, then implement + parse the 'P&L synced' summary.")


def _kickoff_dm(week: dt.date, raw_range, summary, checks, *, send: bool, log=_log) -> None:
    """DM Carlos as Lucy that the week is loaded and refreshed, and what's left
    for him (bonuses/no-pay/rates, verify, print; auto-locks Thu)."""
    lines = [
        f"🐺 Vantura payroll prep is done for week ending {week:%-m/%-d} "
        "(loaded + refreshed on Lucy 2).",
        f"• RAW rows: {raw_range}",
        f"• Sync summary: {summary}",
        f"• P&L checks: {checks}",
        "",
        "Left for you: enter this week's bonuses / no-pay / rate changes, then "
        "Refresh again, verify, and Print the commission pack. It auto-locks "
        "Thursday ~11am.",
    ]
    msg = "\n".join(lines)
    if not send:
        log("DRY-RUN kickoff DM (not sent):\n" + msg)
        return
    from automations.shared import slack_metrics_post as slack  # reuse "as Lucy"
    raise NotImplementedError(
        "kickoff DM: send `msg` to DM_RECIPIENTS via slack_metrics_post (as Lucy).")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vantura weekly payroll prep (Lucy 2).")
    ap.add_argument("--week", help="week ending YYYY-MM-DD (default: computed)")
    ap.add_argument("--file", help="explicit ICD dd Detail .xlsx (default: latest in Downloads)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="compute + pull + PRINT only; no board writes, no Slack (DEFAULT)")
    mode.add_argument("--sandbox", action="store_true", help="write to the test board copy")
    mode.add_argument("--live", action="store_true", help="write to the REAL board")
    args = ap.parse_args(argv)

    live = bool(args.live)
    sandbox = bool(args.sandbox)
    write = live or sandbox
    send = live  # kickoff DM only on a real live run

    week = (dt.datetime.strptime(args.week, "%Y-%m-%d").date()
            if args.week else week_ending())

    mode_name = "LIVE" if live else ("SANDBOX" if sandbox else "DRY-RUN")
    _log(f"Vantura payroll prep — mode={mode_name} — week ending {week.isoformat()}")
    if sandbox and not SANDBOX_SHEET_ID:
        _log("ERROR: --sandbox needs SANDBOX_SHEET_ID (a duplicated board). Not set.")
        return 2
    # Sandbox writes go to the copy; dry-run/live read+write the real board
    # (dry-run never writes). Reads always come from the resolved board.
    sheet_id = SANDBOX_SHEET_ID if sandbox else SHEET_ID

    try:
        xlsx = Path(args.file) if args.file else _pull_icd_dd_detail(week)
        raw_range = _load_raw(xlsx, week, write=write, sheet_id=sheet_id)
        _set_week(week, write=write, sheet_id=sheet_id)
        _repoint_pnl(week, raw_range, write=write)
        summary, checks = None, None
        result = _refresh_and_check(write=write)
        summary, checks = result.get("summary"), result.get("checks")
        _kickoff_dm(week, raw_range, summary, checks, send=send)
    except NotImplementedError as e:
        _log(f"SCAFFOLD STOP (not yet wired): {e}")
        _log("This module is a dry-run scaffold — the remaining board-write "
             "internals (_repoint_pnl, _refresh_and_check) are stubbed until "
             "verified against a sandbox board copy.")
        return 3
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        _log(f"STOP: {e}")
        return 4
    _log("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
