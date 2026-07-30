"""Build and send one board's screenshot email.

    python -m automations.board_emails.email_send --board country --dry-run
    python -m automations.board_emails.email_send --board all-units --send-reviewed

Same two-step shape as the Org Sales Board email, for the same reason: the run
that BUILDS writes a manifest, and --send-reviewed mails the files that manifest
names. Nothing is re-rendered at send time, so what the approvers looked at in
Slack is byte-for-byte what lands in the inbox even if the board moved in
between.

The subject carries YESTERDAY. Both boards only ever hold completed days, so a
run on the 30th is showing the 29th's sales; dating the email with the run day
would put it a day ahead of its own numbers (Eve, 2026-07-27 / 07-29 — the same
rule the Slack DMs and the Org board email already follow).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from automations.board_emails import boards as B
# SMTP and the preview renderer live with the Org board email — one sender, one
# preview format for every screenshot email we mail.
from automations.org_sales_board.screenshot_email import (
    send as _smtp_send, preview_html,
)
from automations.scheduled_6_days_out.email_send import FROM_ADDR

# Texas company — the reported day is Central, never the machine clock. The mini
# and Eve's box sit in different zones and a UTC-evening run would otherwise
# title itself with tomorrow. [[project_central-time-for-texas-reports]]
CENTRAL = ZoneInfo("America/Chicago")

_REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — redirected stdout / older Pythons
    pass


def today_central() -> dt.date:
    return dt.datetime.now(CENTRAL).date()


def reported_day(run_day: dt.date) -> dt.date:
    """The day the numbers are FOR — the day before the run."""
    return run_day - dt.timedelta(days=1)


def out_dir_for(board: B.Board, run_day: dt.date) -> Path:
    return _REPO_ROOT / "output" / "board_emails" / board.key / run_day.isoformat()


# ------------------------------------------------------------------ capture
def capture(board: B.Board, run_day: dt.date, *, verbose: bool = True) -> List[Tuple[str, Path]]:
    """Render the board and COPY the PNG into the day's folder.

    The copy matters: each board's slack_post writes to one fixed filename that
    tomorrow's run overwrites. --send-reviewed has to be able to mail the image
    that was approved, which may be hours old, so it gets its own dated copy."""
    png, rng = board.build_png()
    out_dir = out_dir_for(board, run_day)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{board.key}.png"
    shutil.copyfile(png, dest)
    if verbose:
        print(f"[board_emails] {board.name}: {rng} -> {dest} "
              f"({dest.stat().st_size // 1024} KB)", flush=True)
    return [(board.key, dest)]


def write_manifest(board: B.Board, run_day: dt.date,
                   images: List[Tuple[str, Path]]) -> Path:
    p = out_dir_for(board, run_day) / "manifest.json"
    p.write_text(json.dumps([{"name": n, "file": Path(f).name} for n, f in images],
                            indent=2), encoding="utf-8")
    return p


def reviewed_images(board: B.Board, run_day: dt.date) -> List[Tuple[str, Path]]:
    """The day's captured images, in email order, from the manifest."""
    out_dir = out_dir_for(board, run_day)
    man = out_dir / "manifest.json"
    if not man.exists():
        raise RuntimeError(
            f"no manifest in {out_dir} — nothing was captured for "
            f"{run_day:%Y-%m-%d}. Build the preview first (--dry-run).")
    rows = json.loads(man.read_text(encoding="utf-8"))
    images = [(r["name"], out_dir / r["file"]) for r in rows]
    missing = [str(p) for _n, p in images if not p.exists()]
    if missing:
        raise RuntimeError(f"manifest lists files that are gone: {missing}")
    return images


# -------------------------------------------------------------------- email
def subject_for(board: B.Board, run_day: dt.date) -> str:
    """'Country Sales Board 7/29' — .month/.day, never %-m (that strftime flag
    does not exist on Windows and this runs on both machines)."""
    d = reported_day(run_day)
    return f"{board.name} {d.month}/{d.day}"


def build_email(board: B.Board, images: List[Tuple[str, Path]],
                to_addrs: List[str], run_day: dt.date) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject_for(board, run_day)

    parts, cids = [], []
    for _name, path in images:
        cid = make_msgid()[1:-1]
        cids.append((cid, path))
        parts.append(f'<img src="cid:{cid}" style="max-width:1000px;width:100%;'
                     f'border:1px solid #ddd;margin:0 0 16px">')
    banner = (f'<div style="background:{board.banner_bg};text-align:center;'
              f'padding:10px;font-size:22px;font-weight:bold;'
              f'color:{board.banner_fg};border:1px solid #bbb;max-width:1000px;'
              f'width:100%;box-sizing:border-box;margin:0 0 16px">'
              f'{board.name.upper()}</div>')
    html = ('<div style="font-family:Arial,Helvetica,sans-serif;color:#000">'
            + banner + "".join(parts)
            + '<div style="font-size:11px;color:#888;margin-top:6px">'
              'Auto-generated from the board. — Alphalete Reporting</div></div>')
    msg.set_content(f"{board.name} — see the HTML version for the screenshot.")
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_payload()[-1]
    for cid, path in cids:
        html_part.add_related(Path(path).read_bytes(), "image", "png",
                              cid=f"<{cid}>")
    return msg


def _recipients(board: B.Board, override: Optional[str]) -> List[str]:
    if override:
        return [x.strip() for x in override.split(",") if x.strip()]
    return list(board.to)


def _publish_sent(board: B.Board) -> None:
    """Tell the Hub this email actually went out today, from whatever machine
    sent it — the send is a separate review-gate run from the morning build, so
    the card would otherwise reflect only the build."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(board.report_id.replace("-", "_"),
                                 board.hub_name, status="success")
    except Exception:  # noqa: BLE001 — the Hub must never fail a delivered email
        pass


# ---------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", required=True, choices=B.KEYS,
                    help="which board's email to build/send")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture + build + write the preview, but DON'T send")
    ap.add_argument("--to", default=None,
                    help="comma-separated recipients instead of the board's own")
    ap.add_argument("--send-reviewed", action="store_true",
                    help="mail the image ALREADY captured for --date (from the "
                         "manifest); capture nothing. This is what the review "
                         "gate calls.")
    ap.add_argument("--date", default=None,
                    help="run date (default today, Central). The email reports "
                         "the day BEFORE it.")
    a = ap.parse_args(argv)

    board = B.get(a.board)
    run_day = dt.date.fromisoformat(a.date) if a.date else today_central()
    to = _recipients(board, a.to)

    if a.send_reviewed:
        images = reviewed_images(board, run_day)
        print(f"[board_emails] mailing {len(images)} reviewed image(s) from "
              f"{out_dir_for(board, run_day)}", flush=True)
        msg = build_email(board, images, to, run_day)
        if a.dry_run:
            print(f"[board_emails] DRY-RUN — not sent. Would go to: {to}", flush=True)
            print("=== done (dry-run) ===", flush=True)
            return 0
        _smtp_send(msg)
        print(f"[board_emails] sent to {to}", flush=True)
        _publish_sent(board)
        print("=== done ===", flush=True)
        return 0

    out_dir = out_dir_for(board, run_day)
    images = capture(board, run_day)
    write_manifest(board, run_day, images)
    msg = build_email(board, images, to, run_day)

    if a.dry_run:
        (out_dir / "preview.eml").write_bytes(bytes(msg))
        html = out_dir / "preview.html"
        html.write_text(preview_html(msg), encoding="utf-8")
        print(f"[board_emails] DRY-RUN — not sent. Recipients would be: {to}\n"
              f"  subject: {msg['Subject']}\n"
              f"  preview: {html}", flush=True)
        print("=== done (dry-run) ===", flush=True)   # Hub success sentinel
        return 0

    _smtp_send(msg)
    print(f"[board_emails] sent to {to}", flush=True)
    _publish_sent(board)
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
