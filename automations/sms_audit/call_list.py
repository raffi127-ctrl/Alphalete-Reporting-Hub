# -*- coding: utf-8 -*-
"""Resumes received -> 1st round booked. The office's main number.

Megan 2026-10-01: "what retention to call list is (that's the amount of
people applied vs how many we booked. This is the MAIN thing we need to get
as high as possible - goal at 80%+)".

The ARS doc names the same chain on Friday of training week: "Retention
Details & goals: resumes received -> 1st round retention".

WHERE THE TWO NUMBERS COME FROM
  booked    AppStream Activity Report (p=704) -> "First Interview Date"
            rows, one per interview actually on the calendar that week.
  applied   AppStream Call List export (p=4000 -> Export), the file
            callList_<office>.xls. Every applicant is saved to the call
            list when their resume arrives, and they come OFF it once
            they are booked. So the people still sitting on it, plus the
            people booked, is everyone whose resume arrived.

THE ASSUMPTION, SAID OUT LOUD: that booking is the only thing that takes
somebody off the call list. If an office also clears people off by hand,
this denominator is too small and the percentage reads too high. The
report prints the assumption next to the number rather than burying it.

READ-ONLY. Reads files already pulled; starts nothing on AppStream.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import collections
import datetime as dt
import html
import json
import re
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[2] / "output"
GOAL = 80.0            # Megan 2026-10-01: "goal at 80%+"

# Where an export lands. Downloads first: that is where a hand-pull goes.
LOOK_IN = (Path.home() / "Downloads", OUTPUT)


def _cells(row):
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]


def _date(s):
    try:
        return dt.datetime.strptime((s or "").strip(), "%m-%d-%Y").date()
    except ValueError:
        return None


def load_call_list(office):
    """[{name, phone, saved, status}] from callList_<office>.xls.

    AppStream calls it .xls; it is an HTML table. Returns ([], None) when
    no export has been pulled — a missing file is a check we cannot run,
    never a zero."""
    for folder in LOOK_IN:
        f = folder / "callList_{}.xls".format(office)
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        out = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
            c = _cells(row)
            if len(c) != 10:
                continue
            out.append({
                "name": "{} {}".format(c[0], c[1]).strip(),
                "phone": "".join(ch for ch in (c[4] or c[5]) if ch.isdigit())[-10:],
                "board": c[2],
                "saved": _date(c[8]),
                "status": c[9],
            })
        return out, str(f)
    return [], None


def load_booked(office):
    """[{name, phone, day}] of 1st interviews, from the activity pull."""
    f = OUTPUT / "activity_{}.json".format(office)
    if not f.exists():
        return [], None
    rows = json.loads(f.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        if (r.get("activity") or "") != "First Interview Date":
            continue
        out.append({
            "name": r.get("applicant", ""),
            "phone": "".join(c for c in (r.get("phone") or "") if c.isdigit())[-10:],
            "day": _date(r.get("day", "")),
        })
    return out, str(f)


def conversion(office, start=None, end=None):
    """{applied, booked, rate, ...} over a date window.

    The window is applied to BOTH sides: people whose resume arrived in it,
    and interviews that sat in it. Without a window the whole export is
    used, which mixes months — the caller should pass one."""
    calls, csrc = load_call_list(office)
    booked, bsrc = load_booked(office)
    if not csrc:
        return {"ok": False, "why": "no call list export for this office "
                                    "(callList_{}.xls)".format(office)}
    if not bsrc:
        return {"ok": False, "why": "no activity pull for this office "
                                    "(activity_{}.json)".format(office)}

    def inside(d):
        if d is None:
            return False
        if start and d < start:
            return False
        if end and d > end:
            return False
        return True

    waiting = [c for c in calls if inside(c["saved"])]
    got = [b for b in booked if inside(b["day"])]
    applied = len(waiting) + len(got)
    if not applied:
        return {"ok": False, "why": "nobody applied and nobody booked in "
                                    "this window"}
    rate = 100.0 * len(got) / applied
    return {
        "ok": True, "applied": applied, "booked": len(got),
        "waiting": len(waiting), "rate": rate, "goal": GOAL,
        "short_by": max(0, int(round(applied * GOAL / 100.0)) - len(got)),
        "call_src": csrc, "booked_src": bsrc,
        "pulled": dt.date.fromtimestamp(Path(csrc).stat().st_mtime),
        "by_status": collections.Counter(c["status"] for c in waiting),
        "by_board": collections.Counter(
            c["board"] for c in waiting).most_common(6),
    }


def stuck(office, start=None, end=None, top=8):
    """Where the ones we did NOT book are sitting, worst first. An office
    that is at 64% wants to know which pile the other 36% is in."""
    c = conversion(office, start, end)
    if not c.get("ok"):
        return []
    total = sum(c["by_status"].values()) or 1
    return [{"status": s, "n": n, "share": 100.0 * n / total}
            for s, n in c["by_status"].most_common(top)]
