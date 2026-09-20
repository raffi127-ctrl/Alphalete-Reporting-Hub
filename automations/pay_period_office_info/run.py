"""Pay Period image for #alphalete-sales -> Files -> Office Info (Raf 2026-09-16).

Lucy has no bookmark scopes, so the Office Info link can't be edited by code.
Instead the link points at ONE Lucy message that holds the image, and every
month Lucy swaps the image INSIDE that message (chat.update) — the link never
changes and nobody gets a new post.

    python -m automations.pay_period_office_info.run            # dry: PNG only
    python -m automations.pay_period_office_info.run --live     # post/update

First --live run posts the message and prints its link; a human adds that link
once under Files -> Office Info (right under "Commission structure"). Must run
on a Lucy: a message posted by another account can't be edited by Lucy.
Scopes used: files:write, chat:write (Lucy has both).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from automations.shared.pay_period import pay_weeks

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANNEL = "C068PH3RFSM"                 # #alphalete-sales
FOLDER_TITLE = "Office Info"
LINK_TITLE = "Pay Period"
# ~3 months on the image: it is only redrawn monthly, so a month from now it
# still shows a couple of weeks back and two months ahead.
WEEKS_BACK = 4
WEEKS_TOTAL = 16
OUT_DIR = REPO_ROOT / "output" / "pay_period_office_info"
STATE = REPO_ROOT / "output" / "state" / "pay_period_office_info.json"
THREAD_TEXT = ("📅 *Pay Period* — activation week (Sun–Sat) and the Friday "
               "it pays. Updated every month; also under Files → Office Info.")


def build_image(today: date) -> Path:
    from automations.pay_period_office_info.render import render
    weeks = pay_weeks(today, WEEKS_BACK, WEEKS_TOTAL)
    return render(weeks, OUT_DIR / f"Pay Period {today:%Y-%m}.png", today)


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt = first run
        return {}


def _write_state(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _blocks(file_id: str, today: date) -> list:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": THREAD_TEXT}},
        {"type": "image", "slack_file": {"id": file_id},
         "alt_text": f"Pay Period calendar, updated {today:%m/%d/%Y}"},
    ]


def publish(png: Path, today: date) -> str:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()

    # Upload without sharing (no channel): the file only shows up through the
    # image block, so the channel sees no new post.
    up = client.files_upload_v2(file=str(png), filename=png.name,
                                title=LINK_TITLE)
    file_id = smp._uploaded_file_id(up)
    blocks = _blocks(file_id, today)

    state = _read_state()
    ts = state.get("message_ts")
    # A fresh upload can take a few seconds before Slack lets a block show it
    # (invalid_blocks meanwhile) — retry briefly rather than fail the month.
    for attempt in range(6):
        try:
            if ts:
                client.chat_update(channel=CHANNEL, ts=ts, text=THREAD_TEXT,
                                   blocks=blocks)
                action = "updated the image in"
            else:
                ts = client.chat_postMessage(channel=CHANNEL, text=THREAD_TEXT,
                                             blocks=blocks)["ts"]
                action = "posted"
            break
        except Exception as e:  # noqa: BLE001
            if "invalid_blocks" not in str(e) or attempt == 5:
                raise
            time.sleep(5)
    link = client.chat_getPermalink(channel=CHANNEL, message_ts=ts)["permalink"]
    state.update({"message_ts": ts, "permalink": link, "file_id": file_id,
                  "published": today.isoformat()})
    _write_state(state)
    note = "" if action != "posted" else (
        f" — ADD THIS LINK ONCE under Files → {FOLDER_TITLE}, "
        f"titled '{LINK_TITLE}'")
    return f"{action} the Pay Period message: {link}{note}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pay_period_office_info")
    ap.add_argument("--live", action="store_true",
                    help="post / update the Pay Period message in "
                         "#alphalete-sales (default: draw the PNG only)")
    args = ap.parse_args(argv)
    png = build_image(date.today())
    print(f"✓ drew {png}")
    if not args.live:
        print("(dry run — nothing posted; add --live to publish)")
        return 0
    try:
        print("✓ " + publish(png, date.today()))
    except Exception as e:  # noqa: BLE001
        print(f"✗ Pay Period not published: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
