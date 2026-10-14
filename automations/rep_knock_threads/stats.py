"""Per-rep weekly numbers from the raw knocks. Pure functions — no I/O."""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from automations.rep_knock_threads import config as C
from automations.rep_knock_threads.pull import gps_kind, gps_reason

# Talk-to = every disposition EXCEPT these — the same rule as Raf's Sunday
# Weekly Knock Dispositions board (reference_talk_to_rule_differs), since
# this is a weekly view too. So "Already has AT&T" IS a talk-to here.
NOT_TALK_TO = {"no answer", "inaccessible"}


def week_start(day: dt.date) -> dt.date:
    """Monday of `day`'s week. The week runs Monday → Sunday."""
    return day - dt.timedelta(days=day.weekday())


def week_days(day: dt.date) -> list[dt.date]:
    mon = week_start(day)
    return [mon + dt.timedelta(days=i) for i in range(7)]


def parse_when(s: str) -> "dt.datetime | None":
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def avg_gap_min(times: list[dt.datetime]) -> "float | None":
    """Average minutes between consecutive doors, per day. Gaps over
    GAP_CAP_MIN are breaks/drives and are left out."""
    by_day = defaultdict(list)
    for t in times:
        by_day[t.date()].append(t)
    gaps = []
    for ts in by_day.values():
        ts.sort()
        for a, b in zip(ts, ts[1:]):
            m = (b - a).total_seconds() / 60
            if m <= C.GAP_CAP_MIN:
                gaps.append(m)
    return sum(gaps) / len(gaps) if gaps else None


def pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def rep_week(knocks: list[dict], today: dt.date) -> dict:
    """Everything the image + alert need for ONE rep's week so far."""
    rows = sorted(knocks, key=lambda r: r["when"])
    n = len(rows)
    times = [t for t in (parse_when(r["when"]) for r in rows) if t]
    disp = Counter(r["status"] for r in rows)
    colors = {}
    for r in rows:
        colors.setdefault(r["status"], r["color"])
    kinds = Counter(gps_kind(r["gps"]) for r in rows)
    reasons = Counter(gps_reason(r["gps"]) for r in rows
                      if gps_kind(r["gps"]) == "fail")
    talk = sum(c for s, c in disp.items() if s.strip().lower() not in NOT_TALK_TO)

    days = []
    for d in week_days(today):
        dr = [r for r in rows if r["when"][:10] == d.isoformat()]
        dt_ = [t for t in (parse_when(r["when"]) for r in dr) if t]
        days.append({
            "date": d,
            "knocks": len(dr),
            "fails": sum(1 for r in dr if gps_kind(r["gps"]) == "fail"),
            "first": min(dt_) if dt_ else None,
            "last": max(dt_) if dt_ else None,
            "future": d > today,
        })

    today_rows = [r for r in rows if r["when"][:10] == today.isoformat()]
    t_kinds = Counter(gps_kind(r["gps"]) for r in today_rows)
    t_disp = Counter(r["status"] for r in today_rows)
    t_talk = sum(c for s_, c in t_disp.items() if s_.strip().lower() not in NOT_TALK_TO)
    t_times = [t for t in (parse_when(r["when"]) for r in today_rows) if t]
    return {
        "rep": rows[0]["rep"] if rows else "",
        "rep_id": rows[0]["rep_id"] if rows else "",
        "knocks": n,
        "avg_gap": avg_gap_min(times),
        "talk_to": talk,
        "talk_pct": pct(talk, n),
        "disp": disp.most_common(),
        "colors": colors,
        "gps_ok": kinds["ok"],
        "gps_fail": kinds["fail"],
        "gps_none": kinds["none"],
        "gps_ok_pct": pct(kinds["ok"], n),
        "gps_fail_pct": pct(kinds["fail"], n),
        "gps_none_pct": pct(kinds["none"], n),
        "fail_reasons": reasons.most_common(),
        "days": days,
        "today_rows": today_rows,
        "rows": rows,
        "today": {
            "knocks": len(today_rows),
            "avg_gap": avg_gap_min(t_times),
            "talk_pct": pct(t_talk, len(today_rows)),
            "gps_ok_pct": pct(t_kinds["ok"], len(today_rows)),
            "gps_fail": t_kinds["fail"],
            "gps_fail_pct": pct(t_kinds["fail"], len(today_rows)),
            "fail_reasons": Counter(gps_reason(r["gps"]) for r in today_rows
                                    if gps_kind(r["gps"]) == "fail").most_common(),
        },
        "flagged": day_flagged(today_rows),
        "streak": 0,          # filled by streak() — needs days before this week
    }


def day_flagged(day_rows: list[dict]) -> bool:
    """Over the line for ONE day: ≥FLAG_FAIL_PCT GPS failures on ≥FLAG_MIN_KNOCKS doors."""
    n = len(day_rows)
    fails = sum(1 for r in day_rows if gps_kind(r["gps"]) == "fail")
    return n >= C.FLAG_MIN_KNOCKS and pct(fails, n) >= C.FLAG_FAIL_PCT


def streak(rep_id: str, by_day: dict, today: dt.date) -> int:
    """Consecutive worked days over the line, ending today. Today must be
    over the line or the streak is 0. A day the rep didn't knock (Sunday,
    a day off) is skipped, not a break."""
    n = 0
    for d in sorted((d for d in by_day if d <= today), reverse=True):
        mine = [r for r in by_day[d] if r["rep_id"] == rep_id]
        if not mine:
            if d == today:
                return 0
            continue
        if not day_flagged(mine):
            break
        n += 1
    return n


def carried_streak(rep_id: str, by_day: dict, today: dt.date) -> "tuple[int, dt.date | None]":
    """(streak, its last day) ending on the rep's most recent worked day in the
    last CARRY_DAYS days before today. (0, None) if none."""
    for back in range(1, C.CARRY_DAYS + 1):
        d = today - dt.timedelta(days=back)
        if any(r["rep_id"] == rep_id for r in by_day.get(d, [])):
            return streak(rep_id, by_day, d), d
    return 0, None


def today_streak(rep_id: str, by_day: dict, today: dt.date) -> "tuple[int, bool]":
    """(streak to show, carried?). With enough doors today, today decides:
    over → the streak including today, under → 0 (broken). Not enough doors
    yet → the carried streak, if it's long enough to carry."""
    mine = [r for r in by_day.get(today, []) if r["rep_id"] == rep_id]
    if len(mine) >= C.FLAG_MIN_KNOCKS:
        return streak(rep_id, by_day, today), False
    n, _ = carried_streak(rep_id, by_day, today)
    return (n, True) if n >= C.CARRY_MIN_STREAK else (0, False)


def flags(n: int) -> str:
    return "🚩" * max(n, 0)


def group_by_rep(knocks: list[dict]) -> dict:
    out = defaultdict(list)
    for r in knocks:
        out[r["rep_id"]].append(r)
    return dict(out)


def new_failures(rows: list[dict], seen_ids: set) -> list[dict]:
    """GPS failures the rep's thread hasn't been told about yet."""
    return [r for r in rows if gps_kind(r["gps"]) == "fail"
            and str(r["knock_id"]) not in seen_ids]


def alert_line(fails: list[dict]) -> str:
    """'🚩 4 new GPS failures — 3 too far from door, 1 location turned off'."""
    if not fails:
        return ""
    why = Counter(gps_reason(r["gps"]) for r in fails).most_common()
    parts = ", ".join(f"{c} {w.lower()}" for w, c in why)
    s = "s" if len(fails) != 1 else ""
    return f"🚩 {len(fails)} new GPS failure{s} — {parts}"
