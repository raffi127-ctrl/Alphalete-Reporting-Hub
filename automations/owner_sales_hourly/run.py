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

ONLY OUR ORG (Raf 2026-10-24, "remove people that aren't in our org"): an owner
is listed only if they sit in one of the Org Sales Board's TOP boxes — the daily
per-campaign sections (ATT Fiber Team, ATT NDS Team, B2B, BOX, Retail ...)
above the first captainship block. Captains' downline owners (Trang, Jennifer,
Hasani ...) relay sales too but are not on those boxes, so they are left off.
Names match case-insensitively and through the ICD Aliases sheet.

SOUTH SHORE TOO (Colten 2026-10-24): a second text, only the South Shore owners
(funnel_board.roster.SOUTH_SHORE_NAMES), into his "SOUTHSHORE ORG" chat.
NDS TOO (Jairo 2026-10-26, Eve: "the ones on the same campaign as Jairo"): a
third text into his "A PLAYERSSS" chat -- only sales from NDS offices, only
owners on our Org board, titled "NDS Sales Today".

Usage
  # dry-run (DEFAULT): print the text, resolve the chat on a Mac, send nothing
  python -m automations.owner_sales_hourly.run

  # live (what the LaunchAgent runs)
  python -m automations.owner_sales_hourly.run --send

  --force   ignore the time window and the "nothing changed" skip
  --only owners|sso|jairo   text just that one chat

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


def owner_totals(relay: Dict, offices: Dict, day: dt.date,
                 campaign: Optional[str] = None) -> Dict[str, int]:
    """{owner: sales today}. Only offices that relayed a reading for `day` —
    no row is "agent did not run", not "zero sales", so it is left off rather
    than printed as a 0. `campaign` keeps only that campaign's offices, so an
    owner on two campaigns (Atef: NDS + B2B) counts just the one asked for."""
    from automations.shared import sale_hype as H

    out: Dict[str, int] = {}
    for key, days in relay.items():
        if day not in days:
            continue
        office = offices.get(key)
        office_campaign = getattr(office, "campaign", None)
        if campaign and office_campaign != campaign:
            continue
        total = sum(H.rep_total(m, office_campaign) for m in days[day].values())
        name = owner_name(key, office)
        out[name] = out.get(name, 0) + total
    return out


def _norm(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def org_owners(grid: List[List[str]], aliases: Optional[Dict] = None) -> set:
    """Normalized names in the board's top per-campaign boxes.

    A top box is a daily section — a row carrying a 'RUNNING WEEK TOTALS'
    header — ABOVE the first '<NAME> CAPTAIN(SHIP) TEAM' band; its owners are
    the col-B names down to its 'Totals' row. Found by label, never by row
    number, so a campaign box added or moved on the tab is picked up as is.
    `aliases` ({canonical: [alias, ...]}) widens each hit to its other
    spellings."""
    from automations.org_sales_board import captainship as cap
    from automations.org_sales_board import fill_section as fs

    names = set()
    for i, row in enumerate(grid):
        if cap.block_title(grid, i):
            break
        if not any((c or "").strip().lower() == fs.RUNNING_TOTAL_HDR
                   for c in row):
            continue
        for r in range(i + 2, len(grid)):
            if fs._cell(grid, r, 0).lower() == fs.TOTALS_ROW_LABEL:
                break
            if cap.block_title(grid, r):
                break
            b = fs._cell(grid, r, 1)
            if b:
                names.add(_norm(b))
    for canonical, alts in (aliases or {}).items():
        group = {_norm(canonical)} | {_norm(a) for a in alts or []}
        if group & names:
            names |= group
    return names


def only_org(totals: Dict[str, int], org: set) -> Tuple[Dict[str, int], List[str]]:
    """(kept, dropped names) — kept = owners on the board's top boxes."""
    kept = {n: v for n, v in totals.items() if _norm(n) in org}
    dropped = sorted(n for n in totals if n not in kept)
    return kept, dropped


def south_shore_owners(aliases: Optional[Dict] = None) -> set:
    """Normalized South Shore owner names (+ their ICD Aliases spellings)."""
    from automations.funnel_board.roster import SOUTH_SHORE_NAMES

    names = {_norm(n) for n in SOUTH_SHORE_NAMES}
    for canonical, alts in (aliases or {}).items():
        group = {_norm(canonical)} | {_norm(a) for a in alts or []}
        if group & names:
            names |= group
    return names


def _load_aliases() -> Dict:
    from automations.focus_office_att.aliases import load_aliases
    try:
        return load_aliases()
    except Exception as e:  # noqa: BLE001 — exact names still match
        print("aliases unreadable (%s) — matching exact names only" % e)
        return {}


def read_org_owners() -> set:
    from automations.org_sales_board.grid import read_grid
    from automations.org_sales_board.run import SHEET_ID
    from automations.org_sales_board.tabs import BOARD_TAB
    from automations.recruiting_report.fill import open_by_key

    ws = open_by_key(SHEET_ID).worksheet(BOARD_TAB)
    return org_owners(read_grid(ws, unformatted=False), _load_aliases())


def _clock(now: dt.datetime) -> str:
    """'5:50 PM' without %-I (Windows strftime has no '-')."""
    h = now.hour % 12 or 12
    return "%d:%02d %s" % (h, now.minute, "AM" if now.hour < 12 else "PM")


def build_text(totals: Dict[str, int], now: dt.datetime,
               title: str = "Owner Sales Today") -> str:
    rows: List[Tuple[str, int]] = sorted(totals.items(),
                                         key=lambda kv: (-kv[1], kv[0]))
    lines = ["%s - %s CT" % (title, _clock(now)), ""]
    for i, (name, n) in enumerate(rows, 1):
        lines.append("%d. %s %d" % (i, name, n))
    lines += ["", "🏆 TOTAL: %d" % sum(totals.values())]
    return "\n".join(lines)


def in_window(now: dt.datetime) -> bool:
    span = cfg.WINDOW.get(now.weekday())
    return bool(span) and span[0] <= now.hour <= span[1]


def _last_path(day: dt.date, key: str = "last_sent"):
    return cfg.OUT_DIR / day.isoformat() / ("%s.txt" % key)


def _numbers(text: str) -> str:
    """The text minus its time line — what 'nothing changed' compares."""
    return "\n".join(text.splitlines()[1:])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true",
                    help="actually text the owners chat (default: dry run)")
    ap.add_argument("--force", action="store_true",
                    help="ignore the time window and the unchanged-numbers skip")
    ap.add_argument("--only", choices=("owners", "sso", "jairo"),
                    help="text just one chat (e.g. a catch-up send to SSO)")
    args = ap.parse_args(argv)

    now = _now()
    day = now.date()
    if not args.force and not in_window(now):
        print("outside the window (%s %s) — nothing to do"
              % (now.strftime("%a"), _clock(now)))
        return 0

    from automations.icd_alerts import offices as O
    from automations.icd_sales_board import relay_read as R

    relay, offices = R.read_all(), O.all_offices()
    everyone = owner_totals(relay, offices, day)
    if not everyone:
        # Before the first office relays (or a dead relay) — a list with no
        # owners on it would read as everybody at zero.
        print("no office has relayed sales for %s yet — not texting" % day)
        return 0

    # No board = no way to tell who is ours; texting everyone is exactly
    # what Raf asked us to stop, so fail loud and try again next hour.
    org = read_org_owners()
    if not org:
        print("Org Sales Board top boxes read empty — not texting")
        return 1
    totals, dropped = only_org(everyone, org)
    if dropped:
        print("not on the Org board's top boxes (left off): %s"
              % ", ".join(dropped))
    sso, _ = only_org(everyone, south_shore_owners(_load_aliases()))
    nds, _ = only_org(owner_totals(relay, offices, day, cfg.JAIRO_CAMPAIGN), org)

    rc = 0
<<<<<<< Updated upstream
    for name, group, key, chat_totals in (
            ("owners", cfg.TEXT_GROUP, "last_sent", totals),
            ("sso", cfg.SSO_GROUP, "last_sent_sso", sso),
            ("jairo", cfg.JAIRO_GROUP, "last_sent_jairo", sso)):
=======
    for name, group, key, chat_totals, title in (
            ("owners", cfg.TEXT_GROUP, "last_sent", totals, "Owner Sales Today"),
            ("sso", cfg.SSO_GROUP, "last_sent_sso", sso, "Owner Sales Today"),
            ("jairo", cfg.JAIRO_GROUP, "last_sent_jairo", nds, "NDS Sales Today")):
>>>>>>> Stashed changes
        if args.only and args.only != name:
            continue
        print("=== %s ===" % (group if isinstance(group, str)
                               else group.get("group")))
        rc = max(rc, _send_one(group, key, chat_totals, now, day, args, title))
    return rc


def _send_one(group, key: str, totals: Dict[str, int], now: dt.datetime,
              day: dt.date, args, title: str = "Owner Sales Today") -> int:
    if not totals:
        print("nobody on this chat's list has relayed sales yet — not texting")
        return 0

    text = build_text(totals, now, title)
    print(text)
    print()

    last = _last_path(day, key)
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
    try:
        res = T.send_text_to_group(group, text, dry_run=dry)
    except Exception as e:  # noqa: BLE001 — one bad chat must not stop the other
        print("text failed: %s" % e)
        return 1
    print("%s -> %s (%s people)" % ("[dry-run] would text" if dry else "texted",
                                    res.get("resolved_name"),
                                    res.get("participants") or "?"))
    if not dry:
        last.parent.mkdir(parents=True, exist_ok=True)
        last.write_text(text, encoding="utf-8")
    return 0

if __name__ == "__main__":
    sys.exit(main())
