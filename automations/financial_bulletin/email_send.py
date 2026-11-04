"""Org Finances — the 'Financial Bulletin - Our Org' tab, emailed to Raf + Maud weekly.

Raf via Maud, 2026-11-03: "could that be emailed to him once a week once it's
filled out for the week?". Runs right after the bulletin is rebuilt at the end
of the Financial Report, so it pictures the numbers just written. Eve added Maud
the same day.

    python -m automations.financial_bulletin.email_send                 # DRY RUN
    python -m automations.financial_bulletin.email_send --send --to me@x  # test
    python -m automations.financial_bulletin.email_send --send          # Raf + Maud

Goes out only when the newest week is filled for most owners. One send per week:
a re-run of the Financial Report does not mail them twice (--force overrides). A
--to test never marks the week sent.

The tab's week columns sit 8 days after the books' week ending (WE 11/01 = the
books through 10/24), so the email says which books it shows.

Eve gets a Slack DM whenever the weekly pass does NOT send: week not filled, no
new week since the last send, or an error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from automations.board_emails import boards as B
from automations.board_emails import email_send as ES
from automations.financial_bulletin import run as FB
from automations.org_sales_board import screenshot_email as SE
from automations.recruiting_report import fill as rfill

TO = [B.RAFAEL, B.MAUD]
EVE_SLACK = "U088E2KJEV8"
# Books close on a Saturday; their tab column is the Sunday of the next week.
# Checked against Double Entry: books 10/24 = column 11/01, books 9/26 = 10/04.
BOOKS_LAG_DAYS = 8
NEW_WEEK_DAYS = 6   # sent longer ago than this + same week = no new week arrived
NAME = "Org Finances"
MIN_FILLED = 0.75   # share of owners the newest week needs before it counts as filled
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "org_finances_last_sent.txt"
OUT = Path(__file__).resolve().parents[2] / "output" / "financial_bulletin_email"
FIRST_BLOCK = FB.METRICS[0][0].upper()   # matched inside the block's title
DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")


def _text(row, i: int = 0) -> str:
    return str(row[i]).strip() if i < len(row) else ""


def blocks(g: List[list]) -> List[Tuple[int, int]]:
    """(first, last) 0-based rows of each block; blocks are split by blank rows."""
    out, start = [], None
    for i, row in enumerate(g):
        blank = not any(str(c).strip() for c in row)
        if blank and start is not None:
            out.append((start, i - 1))
            start = None
        elif not blank and start is None:
            start = i
    if start is not None:
        out.append((start, len(g) - 1))
    return out


def newest_week(g: List[list]) -> Tuple[str, int]:
    """The newest week header in the first metric block, and its column."""
    head = next(r for r in g if _text(r) == "OWNER" and
                any(DATE.match(str(c).strip()) for c in r))
    cols = [j for j, c in enumerate(head) if DATE.match(str(c).strip())]
    return str(head[cols[-1]]).strip(), cols[-1]


def filled_share(g: List[list], col: int) -> float:
    """Share of owner rows with a value in `col`, in the Total Funds block."""
    start = next((i for i, r in enumerate(g) if FIRST_BLOCK in _text(r).upper() and
                  not any(str(c).strip() for c in r[1:])), None)
    if start is None:
        raise RuntimeError(f"block '{FIRST_BLOCK}' not found on the tab")
    have = total = 0
    for row in g[start + 2:]:
        label = _text(row)
        if not label or label.upper() == "TOTAL":
            break
        if label.isupper() or label.lower().endswith("average"):
            continue   # org title / org average rows are not owners
        total += 1
        have += bool(_text(row, col))
    return have / total if total else 0.0


def last_col_letter(g: List[list], first: int, last: int) -> str:
    width = max(max((j for j, c in enumerate(r) if str(c).strip()), default=0)
                for r in g[first:last + 1])
    return SE._colletter(width + 1)


def capture(sh, ws, g: List[list], out_dir: Path) -> List[Tuple[str, Path, int]]:
    colpx = SE.column_pixels(sh, ws.id)
    token = SE._access_token()
    images = []
    # The title + "Updated" lines are text only: the subject already names the week.
    for n, (first, last) in enumerate(blocks(g)[1:], 1):
        rng = f"A{first + 1}:{last_col_letter(g, first, last)}{last + 1}"
        path = SE._export_png(ws.id, rng, out_dir / f"block_{n}.png", token,
                              spreadsheet_id=FB.CAPTAINSHIP_SHEET_ID)
        images.append((f"block_{n}", path, SE._range_width_px(colpx, rng)))
    return images


def already_sent(week: str) -> bool:
    return STATE_PATH.exists() and STATE_PATH.read_text(encoding="utf-8").strip() == week


def books_through(week: str) -> str:
    """'11/01/26' -> '10/24': the books' week ending behind a tab week column."""
    m, d, y = (int(x) for x in week.split("/"))
    end = dt.date(2000 + y % 100, m, d) - dt.timedelta(days=BOOKS_LAG_DAYS)
    return f"{end.month}/{end.day}"


def _sent_days_ago() -> float:
    return (time.time() - STATE_PATH.stat().st_mtime) / 86400


def _warn(text: str) -> None:
    """DM Eve. Best-effort: Slack being down must not break the Financial Report."""
    print(f"org finances: telling Eve — {text}")
    try:
        from automations.shared.slack_metrics_post import _client
        _client().chat_postMessage(channel=EVE_SLACK, text=f":warning: Org Finances: {text}")
    except Exception as e:  # noqa: BLE001
        print(f"org finances: Slack DM failed ({type(e).__name__}: {str(e)[:100]})")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    ap.add_argument("--to", default=None, help="send to this address INSTEAD of Raf (test)")
    ap.add_argument("--force", action="store_true", help="send even if held or already sent")
    a = ap.parse_args(argv)
    weekly = a.send and not a.to   # the real pass: only this one warns or marks

    sh = rfill.open_by_key(FB.CAPTAINSHIP_SHEET_ID, rfill._client())
    ws = sh.worksheet(FB.ORG_TAB)
    g = rfill._retry(ws.get_all_values)
    week, col = newest_week(g)
    share = filled_share(g, col)
    print(f"org finances: newest week {week}, {share:.0%} of owners filled")
    if share < MIN_FILLED and not a.force:
        print(f"org finances: HELD, week {week} is not filled out yet — nothing sent")
        if weekly:
            _warn(f"el mail a Raf y Maud NO salió: la semana {week} tiene solo "
                  f"{share:.0%} de los dueños llenos.")
        return 0
    if not a.to and already_sent(week) and not a.force:
        print(f"org finances: week {week} already sent — nothing to do")
        if weekly and _sent_days_ago() > NEW_WEEK_DAYS:
            _warn(f"el mail a Raf y Maud NO salió: no hay semana nueva, la tab "
                  f"sigue en {week}, que ya se mandó.")
        return 0

    to = [a.to] if a.to else TO
    run_day = ES.today_central()
    images = capture(sh, ws, g, OUT / run_day.isoformat())
    books = books_through(week)
    board = B.Board(key="org-finances", name=f"{NAME} — books through {books}",
                    build_pngs=lambda: None, to=to,
                    drive_folder="", review_title="", report_id="", hub_name="",
                    subject=lambda _d: f"{NAME} — WE {week} (books through {books})")
    msg = ES.build_email(board, images, to, run_day)
    if not a.send:
        preview = OUT / run_day.isoformat() / "preview.html"
        preview.write_text(SE.preview_html(msg), encoding="utf-8")
        print(f"org finances: DRY RUN, would send '{msg['Subject']}' to {to}; preview {preview}")
        return 0
    SE.send(msg)
    print(f"org finances: sent '{msg['Subject']}' to {to}")
    if weekly:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(week, encoding="utf-8")
    return 0


def weekly_pass() -> None:
    """The step the Financial Report calls. Never raises; an error reaches Eve."""
    try:
        main(["--send"])
    except Exception as e:  # noqa: BLE001
        _warn(f"el mail a Raf y Maud NO salió por un error: "
              f"{type(e).__name__}: {str(e)[:150]}")


if __name__ == "__main__":
    sys.exit(main())
