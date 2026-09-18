"""1st to 2nd Below the Mark — the screenshot DM that goes out with every fill.

Renders the filled tab to a PNG (Sheets PDF export, exact-sheet look, no
browser) and sends it as ONE shared Slack GROUP DM from Lucy, so the five
recipients read it in a single thread instead of five separate ones.

    Rafael Hidalgo, Carlos Hidalgo, Camila Hornos Kraschinsky,
    Perla Falabella, Evelyn Sobrino

MUST RUN ON THE MINI. `smp._client()` is not Lucy everywhere: on Eve's Windows
box that token is Evelyn's personal account, and Evelyn is one of the
recipients -- a "DM from Lucy" sent from there is Evelyn messaging herself, and
it looks completely normal in her sidebar. The scheduled agent runs on the mini,
which is also where the AppStream session lives, so the two constraints agree.

Dry-run by default: it builds the PNG and resolves the recipients but sends
nothing. `--post` delivers.

    python -m automations.first_to_second_below_mark.slack_post           # dry-run
    python -m automations.first_to_second_below_mark.slack_post --post    # send
    python -m automations.first_to_second_below_mark.slack_post --post --only U045Z8N0ZQC
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.first_to_second_below_mark import run as rep
from automations.shared import slack_metrics_post as smp

# Slack user IDs, not names, so delivery never depends on the bot holding the
# users:read scope (the Lucy bot does not have it). Names in the comments.
RECIPIENTS = [
    "U045Z8N0ZQC",   # Rafael Hidalgo
    "U046G04P5LG",   # Carlos Hidalgo
    "U07FWSYP3NV",   # Camila Hornos Kraschinsky
    "U07R68ZGHT6",   # Perla Falabella
    "U088E2KJEV8",   # Evelyn Sobrino
]

TITLE = "1st to 2nd Below the Mark"
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "below_the_mark"
# Stops at P on purpose: column Q ("Office to Fill out report for (MUST MATCH
# APP STREAM NAME)") is a working column nobody reading the DM needs, and it is
# wide enough to shrink everything else in the picture (Eve, 2026-09-17).
LAST_COL = "P"
# How many blank rows past the last owner to include, so the picture does not
# end flush against the final row.
TAIL_ROWS = 1


def _last_data_row(ws, first_data_row: int) -> int:
    """Last row that actually names an owner, so the PNG is not mostly blank."""
    col = ws.get(f"A{first_data_row}:A{first_data_row + 499}")
    last = first_data_row - 1
    for i, cell in enumerate(col or []):
        if cell and str(cell[0]).strip():
            last = first_data_row + i
    return last


def build_png(tab: Optional[str] = None, out: Optional[Path] = None) -> tuple:
    """(png path, A1 range, headline) for the current state of the tab."""
    from automations.org_sales_board.screenshot_email import _export_png, _access_token

    tab = tab or rep.SANDBOX_TAB
    sh = fill.open_by_key(rep.SHEET_ID)
    ws = fill.worksheet_ci(sh, tab)
    values = ws.get_all_values()
    hrow = rep.find_header_row(values)
    if hrow is None:
        raise SystemExit(f"{tab!r}: no header row found - nothing to screenshot")
    first_data_row = hrow + 1
    last = _last_data_row(ws, first_data_row)
    rng = f"A1:{LAST_COL}{max(last + TAIL_ROWS, first_data_row)}"

    # Row 2 already says which day and week the fill covers, and how many
    # offices are listed -- reuse it rather than recomputing, so the message and
    # the picture can never disagree.
    status = (values[rep.STATUS_ROW - 1][0]
              if len(values) >= rep.STATUS_ROW and values[rep.STATUS_ROW - 1]
              else "")
    listed = max(0, last - first_data_row + 1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or (OUT_DIR / "below_the_mark.png")
    _export_png(ws.id, rng, out, _access_token(), spreadsheet_id=rep.SHEET_ID)
    headline = f"*{TITLE}* — {status}" if status else f"*{TITLE}* — {listed} offices"
    return out, rng, headline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark.slack_post")
    ap.add_argument("--post", action="store_true",
                    help="actually send the group DM (default: dry-run, no send)")
    ap.add_argument("--only", default="",
                    help="comma-separated Slack user id(s) to send to INSTEAD of "
                         "the full list, for a targeted test")
    ap.add_argument("--tab", default=None, help="screenshot a different tab")
    args = ap.parse_args(argv)
    dry = not args.post

    recipients: List[str] = ([r.strip() for r in args.only.split(",") if r.strip()]
                             if args.only else list(RECIPIENTS))
    if args.only:
        print(f"  --only override: sending to {recipients} (test)")

    png, rng, headline = build_png(tab=args.tab)
    print(f"screenshot {rng} -> {png} ({png.stat().st_size // 1024} KB)")
    print(f"{'DRY-RUN (no send)' if dry else 'SENDING group DM'} to {recipients}")
    print(f"  comment: {headline}")

    # Send as LUCY via the provisioned 'Lucy Reporting' USER token, the same
    # xoxp token every metrics post already uses. as_bot=False on purpose: the
    # separate bot-app token was never created on the mini, and asking for it
    # makes a perfectly good send log an error.
    resp = smp.dm_users_with_file(png, users=recipients, comment=headline,
                                  file_name=f"{TITLE}.png", dry_run=dry,
                                  as_bot=False)
    print(f"  result: {resp}")
    if not dry and resp.get("mode") == "individual_dms":
        print("  ! fell back to INDIVIDUAL DMs - the Lucy bot is missing the "
              "mpim:write scope; add it + reinstall for ONE shared group DM.")

    # A FAILED SEND MUST FAIL THE RUN. dm_users_with_file swallows Slack errors
    # into the payload, so returning 0 unconditionally would record a DM that
    # delivered nothing as DONE and the failure alert would never fire. Partial
    # delivery counts as failure too: the individual-DM fallback reports ok=True
    # if ANY recipient got it, so four of five silently missing out would
    # otherwise look clean.
    failed = [r.get("user_id") for r in resp.get("results", []) if not r.get("ok")]
    if not dry and (not resp.get("ok", False) or failed):
        print(f"  FAILED{f' for {failed}' if failed else ''} - not everyone got it.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
