"""Text every owner's sales so far today into the "Alphalete Owners" chat.

RUNS ON LUCY 1 — Messages there is signed in as alphaletereporting@gmail.com
and is already a member of the owners chat (owner_chat_texts texts it every
morning). Raf's 2026-10-24 ask: how many sales each owner is at; since 2026-11-04 every
30 minutes in that chat (the SSO and NDS chats below stay hourly).

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
CARLOS TOO (Carlos 2026-11-04): the owners list into his "ATT B2B Leaders" chain,
hourly on the :15, titled "Alphalete Owner Sales Today"; the org totals under it too (Carlos 2026-11-06).
ALPHALETE IN THE SSO CHAT (Colten 2026-11-06, Raf approved): a second text into
SOUTHSHORE ORG on the same :45 -- our Org-board owners who are NOT South Shore,
titled "Alphalete Owner Sales Today", its own TOTAL -- so the two orgs compete.
Raf is on the Alphalete text, not the South Shore one (Megan 2026-11-06).
OWNERS CHAT SPLIT TOO (Raf 2026-11-06): "Alphalete Owner Sales Today" then
"South Shore Owner Sales Today", each ending with "Alphalete Org. Total" and
"Southshore Org. Total" under its TOTAL; both go when either moves.
KNOCKING CHAT TOO (Raf 2026-11-06): the owners chat's text, word for word and
on its cadence (:15 and :45), into "Knocking Chat A-Players" -- so Raf's office
sees the other owners' numbers. Own "nothing changed" skip.

Usage
  # dry-run (DEFAULT): print the text, resolve the chat on a Mac, send nothing
  python -m automations.owner_sales_hourly.run

  # live (what the LaunchAgent runs)
  python -m automations.owner_sales_hourly.run --send

  --force   ignore the time window and the "nothing changed" skip
  --only owners|owners_sso|sso|sso_alphalete|jairo|carlos|knocking|knocking_sso   text just that one chat

--send is the ONLY thing that texts anyone. Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, Iterable, List, Optional, Tuple

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
        newer = cfg.SUPERSEDED_BY.get(key)
        if newer and day in (relay.get(newer) or {}):
            continue    # same office, counted under its newer key
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

    names = {_norm(n) for n in list(SOUTH_SHORE_NAMES) + cfg.SSO_EXTRA}
    for canonical, alts in (aliases or {}).items():
        group = {_norm(canonical)} | {_norm(a) for a in alts or []}
        if group & names:
            names |= group
    return names


def alphalete_only(totals: Dict[str, int], south_shore: set) -> Dict[str, int]:
    """Org-board owners minus South Shore — the "Alphalete" side of the SSO
    chat's head-to-head. Raf is Alphalete, so he counts here."""
    return {n: v for n, v in totals.items() if _norm(n) not in south_shore}


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
               title: str = "Owner Sales Today",
               not_in_total: Iterable[str] = (),
               org_totals: Iterable[Tuple[str, int]] = ()) -> str:
    """`not_in_total`: owners who get a ranked line but don't count in the TOTAL.
    `org_totals`: (label, n) lines under the TOTAL, e.g. each org's sum."""
    left_out = {_norm(n) for n in not_in_total}
    rows: List[Tuple[str, int]] = sorted(totals.items(),
                                         key=lambda kv: (-kv[1], kv[0]))
    lines = ["%s - %s CT" % (title, _clock(now)), ""]
    for i, (name, n) in enumerate(rows, 1):
        lines.append("%d. %s %d" % (i, cfg.DISPLAY_NAMES.get(name, name), n))
    total = sum(n for name, n in rows if _norm(name) not in left_out)
    lines += ["", "🏆 TOTAL: %d" % total]
    lines += ["%s: %d" % (label, n) for label, n in org_totals]
    return "\n".join(lines)


def in_window(now: dt.datetime) -> bool:
    span = cfg.WINDOW.get(now.weekday())
    return bool(span) and span[0] <= now.hour <= span[1]


def hourly_chat_skips(name: str, now: dt.datetime) -> bool:
    """True on the pass a one-text-an-hour chat sits out: :15 for most, :45
    for the ones on the :15."""
    if name in cfg.HOURLY_ON_THE_15:
        return now.minute >= 30
    return name in cfg.HOURLY_CHATS and now.minute < 30


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
    ap.add_argument("--only", choices=("owners", "owners_sso", "sso", "sso_alphalete", "jairo", "carlos",
                             "knocking", "knocking_sso"),
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
    sso_names = south_shore_owners(_load_aliases())
    sso, _ = only_org(everyone, sso_names)
    alphalete = alphalete_only(totals, sso_names)
    nds, _ = only_org(owner_totals(relay, offices, day, cfg.JAIRO_CAMPAIGN), org)

    # The SSO chat's South Shore + Alphalete texts are a head-to-head: if
    # EITHER moved, both go, so the chat never compares a fresh number with a
    # stale one (Megan 2026-11-06).
    # The owners chat is split the same way since Raf 2026-11-06 ("we need the
    # post separated"): Alphalete text, then South Shore text, each one ending
    # with BOTH org totals. Same pair rule as the SSO chat.
    pairs = {
        "sso": {"sso": ("last_sent_sso", sso, cfg.SSO_TITLE),
                "sso_alphalete": ("last_sent_sso_alphalete", alphalete,
                                  cfg.SSO_ALPHALETE_TITLE)},
        "owners": {"owners": ("last_sent_owners_alphalete", alphalete,
                              cfg.SSO_ALPHALETE_TITLE),
                   "owners_sso": ("last_sent_owners_sso", sso, cfg.SSO_TITLE)},
        # Raf's knocking chat carries the owners chat's texts, so it is split
        # the same way (Megan 2026-11-06).
        "knocking": {"knocking": ("last_sent_knocking_alphalete", alphalete,
                                  cfg.SSO_ALPHALETE_TITLE),
                     "knocking_sso": ("last_sent_knocking_sso", sso,
                                      cfg.SSO_TITLE)},
    }
    org_lines = org_total_lines(alphalete, sso)
    # The chats that carry the two org lines under the TOTAL: owners (Megan
    # 11/6; both of its texts, Raf 11/6), Knocking (Raf 11/6), Carlos's chain
    # (Carlos 11/6).
    ORG_TOTAL_CHATS = ("owners", "owners_sso", "knocking", "knocking_sso",
                       "carlos")
    pair_of = {name: pid for pid, members in pairs.items() for name in members}
    pair_moved = {
        pid: head_to_head_moved(
            day, now, members.values(),
            org_lines if set(members) & set(ORG_TOTAL_CHATS) else ())
        for pid, members in pairs.items()}
    rc = 0
    for name, group, key, chat_totals, title, not_in_total in (
            ("owners", cfg.TEXT_GROUP, "last_sent_owners_alphalete", alphalete,
             cfg.SSO_ALPHALETE_TITLE, ()),
            # Right after the Alphalete text, same chat (Raf 2026-11-06).
            ("owners_sso", cfg.TEXT_GROUP, "last_sent_owners_sso", sso,
             cfg.SSO_TITLE, ()),
            ("sso", cfg.SSO_GROUP, "last_sent_sso", sso, cfg.SSO_TITLE, ()),
            # Right after the South Shore text, same chat (Colten 2026-11-06).
            ("sso_alphalete", cfg.SSO_GROUP, "last_sent_sso_alphalete",
             alphalete, cfg.SSO_ALPHALETE_TITLE, ()),
            ("jairo", cfg.JAIRO_GROUP, "last_sent_jairo", nds, "NDS Sales Today", ()),
            ("carlos", cfg.CARLOS_GROUP, "last_sent_carlos", totals,
             cfg.CARLOS_TITLE, ()),
            # The owners text again, same cadence, for Raf's office (Raf
            # 2026-11-06: "I want the office to see other guys crushing").
            ("knocking", cfg.KNOCKING_GROUP, "last_sent_knocking_alphalete",
             alphalete, cfg.SSO_ALPHALETE_TITLE, ()),
            ("knocking_sso", cfg.KNOCKING_GROUP, "last_sent_knocking_sso", sso,
             cfg.SSO_TITLE, ())):
        if args.only and args.only != name:
            continue
        # --only / --force are a person asking for that text now.
        if not args.only and not args.force and hourly_chat_skips(name, now):
            continue
        print("=== %s ===" % (group if isinstance(group, str)
                               else group.get("group")))
        rc = max(rc, _send_one(group, key, chat_totals, now, day, args, title,
                               not_in_total,
                               send_anyway=pair_moved.get(pair_of.get(name), False),
                               org_totals=(org_lines if name in ORG_TOTAL_CHATS
                                           else ())))
    return rc


def org_total_lines(alphalete: Dict[str, int],
                    south_shore: Dict[str, int]) -> List[Tuple[str, int]]:
    """The two org lines under a TOTAL."""
    return [(cfg.ALPHALETE_ORG_LINE, sum(alphalete.values())),
            (cfg.SSO_ORG_LINE, sum(south_shore.values()))]


def head_to_head_moved(day: dt.date, now: dt.datetime, pair,
                       org_totals: Iterable[Tuple[str, int]] = ()) -> bool:
    """True when ANY (last-sent key, totals, title) in `pair` has new numbers."""
    return any(t and _changed(_last_path(day, k),
                              build_text(t, now, ti, org_totals=org_totals))
               for k, t, ti in pair)


def _changed(last, text: str) -> bool:
    """True when `text` has different numbers from the last one sent."""
    return not (last.exists()
                and _numbers(last.read_text(encoding="utf-8")) == _numbers(text))


def _send_one(group, key: str, totals: Dict[str, int], now: dt.datetime,
              day: dt.date, args, title: str = "Owner Sales Today",
              not_in_total: Iterable[str] = (), send_anyway: bool = False,
              org_totals: Iterable[Tuple[str, int]] = ()) -> int:
    """`send_anyway`: its partner text moved, so this one goes even unchanged."""
    if not totals:
        print("nobody on this chat's list has relayed sales yet — not texting")
        return 0

    text = build_text(totals, now, title, not_in_total, org_totals)
    print(text)
    print()

    last = _last_path(day, key)
    if not args.force and not send_anyway and not _changed(last, text):
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
