"""Text every owner's sales so far today into the "Alphalete Owners" chat.

RUNS ON LUCY 1 — Messages there is signed in as alphaletereporting@gmail.com
and is already a member of the owners chat (owner_chat_texts texts it every
morning). Raf's 2026-10-24 ask: once an hour, how many sales each owner is at.

    Owner Sales Today - 5:50 PM CT
    1. Jairo Ruiz 33
    2. Colten Wright 31
    ...
    🏆 TOTAL: 280

Numbers are each office's Lucy ECO relay for today ('ICD Relay' -> 'Sales
JSON'), totalled per rep with the campaign's own rule (sale_hype.rep_total:
AT&T Int+Up+DTV+NL, Box Sales, NDS adds Air), then summed per OWNER — an owner
with two campaigns (Carlos: B2B AT&T + Box) is one line.

Usage
  # dry-run (DEFAULT): print the text, resolve the chat on a Mac, send nothing
  python -m automations.owner_sales_hourly.run

  # live (what the LaunchAgent runs)
  python -m automations.owner_sales_hourly.run --send

  --force   ignore the time window and the "nothing changed" skip

--send is the ONLY thing that texts anyone. Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional, Tuple

from automations.owner_sales_hourly import config as cfg

try:
    from zoneinfo import ZoneInfo
    _CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    _CENTRAL = None


def _now() -> dt.datetime:
    return dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()


def owner_name(key: str, office) -> str:
    """The owner as the chat knows them; never a bare office key if avoidable."""
    if office is not None and (getattr(office, "owner", "") or "").strip():
        return office.owner.strip()
    if key in cfg.OWNER_FALLBACK:
        return cfg.OWNER_FALLBACK[key]
    return key.replace("_", " ").replace("-", " ").title()


def owner_totals(relay: Dict, offices: Dict, day: dt.date) -> Dict[str, int]:
    """{owner: sales today}. Only offices that relayed a reading for `day` —
    no row is "agent did not run", not "zero sales", so it is left off rather
    than printed as a 0."""
    from automations.shared import sale_hype as H

    out: Dict[str, int] = {}
    for key, days in relay.items():
        if day not in days:
            continue
        office = offices.get(key)
        campaign = getattr(office, "campaign", None)
        total = sum(H.rep_total(m, campaign) for m in days[day].values())
        name = owner_name(key, office)
        out[name] = out.get(name, 0) + total
    return out


def _clock(now: dt.datetime) -> str:
    """'5:50 PM' without %-I (Windows strftime has no '-')."""
    h = now.hour % 12 or 12
    return "%d:%02d %s" % (h, now.minute, "AM" if now.hour < 12 else "PM")


def build_text(totals: Dict[str, int], now: dt.datetime) -> str:
    rows: List[Tuple[str, int]] = sorted(totals.items(),
                                         key=lambda kv: (-kv[1], kv[0]))
    lines = ["Owner Sales Today - %s CT" % _clock(now), ""]
    for i, (name, n) in enumerate(rows, 1):
        lines.append("%d. %s %d" % (i, name, n))
    lines += ["", "🏆 TOTAL: %d" % sum(totals.values())]
    return "\n".join(lines)


def in_window(now: dt.datetime) -> bool:
    span = cfg.WINDOW.get(now.weekday())
    return bool(span) and span[0] <= now.hour <= span[1]


def _last_path(day: dt.date):
    return cfg.OUT_DIR / day.isoformat() / "last_sent.txt"


def _numbers(text: str) -> str:
    """The text minus its time line — what 'nothing changed' compares."""
    return "\n".join(text.splitlines()[1:])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true",
                    help="actually text the owners chat (default: dry run)")
    ap.add_argument("--force", action="store_true",
                    help="ignore the time window and the unchanged-numbers skip")
    args = ap.parse_args(argv)

    now = _now()
    day = now.date()
    if not args.force and not in_window(now):
        print("outside the window (%s %s) — nothing to do"
              % (now.strftime("%a"), _clock(now)))
        return 0

    from automations.icd_alerts import offices as O
    from automations.icd_sales_board import relay_read as R

    totals = owner_totals(R.read_all(), O.all_offices(), day)
    if not totals:
        # Before the first office relays (or a dead relay) — a list with no
        # owners on it would read as everybody at zero.
        print("no office has relayed sales for %s yet — not texting" % day)
        return 0

    text = build_text(totals, now)
    print(text)
    print()

    last = _last_path(day)
    if (not args.force and last.exists()
            and _numbers(last.read_text(encoding="utf-8")) == _numbers(text)):
        print("same numbers as the last text — skipped")
        return 0

    dry = not args.send
    if sys.platform != "darwin":
        if not dry:
            print("--send only works on a Mac with Messages (Lucy 1)")
            return 1
        print("[dry-run] not a Mac — chat resolution skipped, nothing sent")
        return 0

    from automations.b2b_dispositions import text_post as T
    res = T.send_text_to_group(cfg.TEXT_GROUP, text, dry_run=dry)
    print("%s -> %s (%d people)" % ("[dry-run] would text" if dry else "texted",
                                    res.get("resolved_name"),
                                    len(res.get("participants") or [])))
    if not dry:
        last.parent.mkdir(parents=True, exist_ok=True)
        last.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
