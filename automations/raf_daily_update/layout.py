"""Raf's Daily Update sheet: column vocabulary, status wording, row order.

The sheet ("Daily Update & 2nd Round Retention 2026 - Alphalete") has one tab
per month ('October -2026', 'August-2026' — the spacing drifts) and one row
per 2nd-round candidate:

    Date · 1st round Interviewer · 2nd Round Interviewer · First Name ·
    Last Name · Phone Number · Status · BOB Date · Time Slot · Email ·
    SHOWED TO DAY 1 · Ad applied to · Owner Liked the applicant

Right of that block sit the MONTHLY TOTALS formulas — never written. Columns
are found by header; anything past the first blank header is not ours.

Status wording is the recruiters' own (from the Loom + the October tab):
NO SHOW · Leader said no · BOB · LM · Letting me know · Declined. The daily
screenshot shows showed people only, ordered BOB → Declined → Leader said no →
LM (Raf's sheet, 10/13 post).

Pure functions only — no Sheets, no Slack, no browser — so the tests run
anywhere.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Tuple

NO_SHOW = "NO SHOW"
LEADER_NO = "Leader said no"
BOB = "BOB"
LM = "LM"
LETTING = "Letting me know"
DECLINED = "Declined"
TO_CALL = ""          # showed + offered, no call result in AppStream yet

# Screenshot / sheet order. NO SHOW is last and left out of the picture.
ORDER = [BOB, DECLINED, LEADER_NO, LM, LETTING, TO_CALL, NO_SHOW]


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _key_for(h: str) -> Optional[str]:
    if h == "date":
        return "date"
    if h.startswith("1st round"):
        return "int1"
    if h.startswith("2nd round"):
        return "int2"
    if h == "first name":
        return "first"
    if h == "last name":
        return "last"
    if h.startswith("phone"):
        return "phone"
    if h == "status":
        return "status"
    if h.startswith("bob"):
        return "bob_date"
    if h.startswith("time slot"):
        return "time"
    if h == "email":
        return "email"
    if h.startswith("showed to day"):
        return "day1"
    if h.startswith("ad applied"):
        return "ad"
    if h.startswith("owner liked"):
        return "owner_liked"
    return None


REQUIRED = ("date", "int1", "int2", "first", "last", "phone", "status",
            "email")


def resolve(header_row: List[str]) -> Dict[str, int]:
    """{key: 0-based column} from row 1. Stops at the first blank header —
    everything right of it is the MONTHLY TOTALS block."""
    out: Dict[str, int] = {}
    for i, raw in enumerate(header_row):
        h = _norm(raw)
        if not h:
            break
        k = _key_for(h)
        if k and k not in out:
            out[k] = i
    missing = [k for k in REQUIRED if k not in out]
    if missing:
        raise ValueError(f"Daily Update header is missing {missing}: "
                         f"{header_row[:14]}")
    return out


def col_letter(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def month_tab(titles: Iterable[str], day: dt.date) -> Optional[str]:
    """'October -2026' / 'October-2026' / 'Febuary-2026' for `day`."""
    want = re.sub(r"[^a-z0-9]", "", f"{day:%B}{day.year}".lower())
    alt = want.replace("february", "febuary")       # the sheet's own spelling
    for t in titles:
        k = re.sub(r"[^a-z0-9]", "", t.lower())
        if k in (want, alt):
            return t
    return None


def sheet_date(d: dt.date) -> str:
    return f"{d.month}/{d.day}/{d.year % 100:02d}"


def parse_sheet_date(s: str, year: int) -> Optional[dt.date]:
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", str(s or ""))
    if not m:
        return None
    y = int(m.group(3)) if m.group(3) else year
    y += 2000 if y < 100 else 0
    try:
        return dt.date(y, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def phone(s: str) -> str:
    """The sheet keeps 11 digits with the leading 1: '19454039050'."""
    d = re.sub(r"\D", "", str(s or ""))
    if len(d) == 10:
        d = "1" + d
    return d


def status_for(c: dict) -> str:
    """One harvested candidate (daily_update_fill.harvest_office) → the
    recruiters' Status wording."""
    if c.get("show") != "Showed":
        return NO_SHOW
    if c.get("offered") != "Y":
        return LEADER_NO
    b = _norm(c.get("bob_status"))
    if b == "bob":
        return BOB
    if b == "lm":
        return LM
    if b.startswith("letting"):
        return LETTING
    if b.startswith("declined"):
        return DECLINED
    return TO_CALL


def split_orientation(text: str) -> Tuple[str, str]:
    """AppStream 'Brought on Board (10/19/2026 1:00 PM)' text → ('10/19',
    '1:00'), the sheet's BOB Date / Time Slot shape. Either part may be ''."""
    t = str(text or "")
    m = re.search(r"(\d{1,2})/(\d{1,2})", t)
    date = f"{int(m.group(1))}/{int(m.group(2))}" if m else ""
    if not date:                                   # calendar: 'Oct 19'
        mm = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                       r"[a-z]*\.?\s+(\d{1,2})\b", t, re.I)
        if mm:
            mon = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                   "sep", "oct", "nov", "dec"].index(mm.group(1).lower()) + 1
            date = f"{mon}/{int(mm.group(2))}"
    tm = re.search(r"\b(\d{1,2}:\d{2})\s*(?:[ap]\.?m\.?)?", t, re.I)
    return date, (tm.group(1) if tm else "")


def status_rank(status: str) -> int:
    s = _norm(status)
    for i, k in enumerate(ORDER):
        if k and s.startswith(k.lower()):
            return i
    return ORDER.index(TO_CALL)


def build_rows(cands: List[dict]) -> List[dict]:
    """Harvested candidates → sheet rows (dicts keyed like resolve()),
    sorted the way the recruiters sort a day: status, then 2nd-round
    interviewer, then name."""
    rows = []
    for c in cands:
        st = status_for(c)
        bob_date, slot = (split_orientation(c.get("orientation", ""))
                          if st == BOB else ("", ""))
        first, last = c.get("first", ""), c.get("last", "")
        if not (first or last):
            parts = (c.get("name") or "").split(" ", 1)
            first, last = parts[0], (parts[1] if len(parts) > 1 else "")
        rows.append({
            "_day": c["day"], "date": sheet_date(c["day"]),
            "int1": c.get("first_round", ""), "int2": c.get("second_round", ""),
            "first": first, "last": last, "phone": phone(c.get("phone", "")),
            "status": st, "bob_date": bob_date, "time": slot,
            "email": c.get("email", ""), "ad": c.get("ad", ""),
        })
    rows.sort(key=lambda r: (r["_day"], status_rank(r["status"]),
                             _norm(r["int2"]), _norm(r["first"])))
    return rows


def person_key(day: dt.date, first: str, last: str) -> Tuple:
    return (day, _norm(f"{first} {last}"))


def new_rows(rows: List[dict], existing: Iterable[Tuple]) -> List[dict]:
    """Drop anyone the tab already has for that interview day — re-runs and
    hand entries are safe."""
    have = set(existing)
    out = []
    for r in rows:
        k = person_key(r["_day"], r["first"], r["last"])
        if k in have:
            continue
        have.add(k)
        out.append(r)
    return out


# --------------------------------------------------------------- Slack copy

def parent_text(day: dt.date) -> str:
    return f"*Daily Update {day.month}/{day.day}*"


CONGRATS_ASK = ("Hey Team! Can we text all the people hired and congratulate "
                "them for getting the position?")
CONGRATS_HOW = ("Send them this pre-made text, and make edits with your name "
                "and their name; phone numbers are in the screenshot. Once the "
                "text is sent, please confirm with “sent” on this "
                "Slack thread.")
CONGRATS_TEXT = ("Hey X, this is X, I talked to our hiring managers, and they "
                 "told me that they decided to offer you the position. "
                 "Congratulations on getting the position, and I look forward "
                 "to working with you!")


def hires_by_leader(rows: List[dict]) -> "OrderedDict[str, List[dict]]":
    """BOB'd people grouped under their 2nd-round interviewer, A→Z."""
    out: "OrderedDict[str, List[dict]]" = OrderedDict()
    for r in sorted((r for r in rows if r["status"] == BOB),
                    key=lambda r: (_norm(r["int2"]), _norm(r["first"]))):
        out.setdefault(r["int2"].strip() or "No leader listed", []).append(r)
    return out


def tag_text(rows: List[dict], slack_ids: Dict[str, str]) -> str:
    """One line per leader who hired today: their tag (or bold name when we
    have no Slack id) and who they hired, with the start date."""
    groups = hires_by_leader(rows)
    if not groups:
        return ""
    lines = ["*Your new hires today* — please text them and reply "
             "“sent”:"]
    for leader, hires in groups.items():
        sid = slack_ids.get(_norm(leader))
        who = f"<@{sid}>" if sid else f"*{leader}*"
        names = ", ".join(
            f"{h['first']} {h['last']}".strip()
            + (f" (starts {h['bob_date']})" if h["bob_date"] else "")
            for h in hires)
        lines.append(f"• {who}: {names}")
    return "\n".join(lines)


def summary_line(rows: List[dict]) -> str:
    n = len(rows)
    showed = sum(r["status"] != NO_SHOW for r in rows)
    bob = sum(r["status"] == BOB for r in rows)
    to_call = sum(r["status"] == TO_CALL for r in rows)
    s = f"{n} 2nd rounds · {showed} showed · {bob} BOB"
    if to_call:
        s += f" · {to_call} still to call"
    return s
