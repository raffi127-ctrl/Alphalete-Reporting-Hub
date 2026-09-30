"""Late Join Audit -- was each 1st round "Late Join" marked fairly?

Rafael, 2026-09-30 (from Analay's report on Drew's office): interviewers mark
a candidate "Late Join" 1-5 minutes after the slot and never run the interview,
even with nobody else waiting. Lucy checks EVERY Late Join, every org office,
against a 5-minute grace:

    marked less than 5 min after the slot  -> ❌ marked too early
    marked 5+ min after                   -> ✅ within the rule
    + ⚠️ when AppStream says the candidate DID show up

Where it comes from: AppStream Calendar day view (p=102), FIRST INTERVIEWS
table, one row per candidate: Time (the slot, office clock), Show Up, Done By,
Follow Up Status (= "Late Join"), Follow Up By (who marked it) and Follow Up
Time ("Tue,29 01:16 PM" -- shown on the LOGGED-IN ACCOUNT's clock, not the
office's: Lucy's AppStream account reads Pacific, converted to each office's
zone; see MARK_TZ).

Posted to #ars-recruiting-numbers (Rafael, 2026-09-30): ONE thread per day,
'Late Join Audit — September 29th 2026' -- the summary, then one reply per
office that had Late Joins. Runs the day AFTER (default --date = yesterday).
READ-ONLY on AppStream. Runs on Lucy 2.

    python -m automations.late_join_audit.run --date 2026-09-29            # dry-run: print
    python -m automations.late_join_audit.run --date 2026-09-29 --preview-to-eve --post
    python -m automations.late_join_audit.run --post                       # LIVE, today
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from zoneinfo import ZoneInfo

CHANNEL_ID = "C0C42793AKS"          # #ars-recruiting-numbers (Eve, 2026-09-30)
EVE_USER_ID = "U088E2KJEV8"         # preview DMs
GRACE_MIN = 5                       # Rafael, 2026-09-30: "5 minutes of grace for now"
DEFAULT_TZ = "America/Chicago"
# The clock AppStream shows Follow Up Time on for Lucy's account. NOT the
# browser's (Intl said Central on Lucy 2 and gave marks 2 hours before the
# slot). Pinned by two marks people saw live on 9/29: Shacty 01:16 PM here =
# 4:16 PM in Drew's Eastern office (Analay), Priscilla 06:49 AM = 8:49 AM in
# Raf's Central office (#rafs-office-recruiting-11280).
MARK_TZ = "America/Los_Angeles"
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "late_join_audit"
LEDGER = OUT_DIR / "posted.json"
# South Shore recruits through Colten's AppStream office, which the org roster
# lists without an id (ad_photo_threads.config has it)
EXTRA_OFFICES = [("Colten Wright", "14733")]


def offices() -> List[tuple]:
    """[(owner, office id)] -- every org office with an AppStream id."""
    from automations.funnel_board.roster import ORG
    out = [(name, oid) for name, oid, _ in ORG if oid]
    have = {oid for _, oid in out}
    return out + [o for o in EXTRA_OFFICES if o[1] not in have]


def office_tz(owner: str) -> ZoneInfo:
    from automations.captainship_night_knocks import zones
    return ZoneInfo(zones._BY_NORM.get(zones.normalize(owner), DEFAULT_TZ))


def _clock(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")          # no %-I: breaks on Windows


def parse_marked(text: str, day: dt.date, browser_tz: ZoneInfo) -> Optional[dt.datetime]:
    """'Tue,29 01:16 PM' (browser clock) -> aware datetime. The day number is
    matched against `day` and the month around it (a mark after midnight or
    a late fix the next day still parses)."""
    m = re.search(r"(\d{1,2})\s+(\d{1,2}:\d{2}\s*[AP]M)", text or "", re.I)
    if not m:
        return None
    dnum = int(m.group(1))
    clock = dt.datetime.strptime(m.group(2).upper().replace(" ", ""), "%I:%M%p").time()
    for delta in (0, 1, -1, 2, 3):
        d = day + dt.timedelta(days=delta)
        if d.day == dnum:
            return dt.datetime.combine(d, clock, tzinfo=browser_tz)
    return None


def parse_slot(text: str, day: dt.date, tz: ZoneInfo) -> Optional[dt.datetime]:
    try:
        t = dt.datetime.strptime((text or "").strip().upper(), "%I:%M %p").time()
    except ValueError:
        return None
    return dt.datetime.combine(day, t, tzinfo=tz)


def rows_to_late_joins(raw: List[List[str]], owner: str, office: str, day: dt.date,
                       browser_tz: ZoneInfo) -> List[Dict]:
    """The probe/day-view rows (['SECTION'|'ROW', section, cells...]) -> one
    dict per FIRST INTERVIEW whose Follow Up Status is Late Join. Columns are
    found by header label, never by position."""
    tz = office_tz(owner)
    out, hdr = [], None
    for r in raw:
        kind, section, cells = r[0], r[1], r[2:]
        if not section.upper().startswith("FIRST INTERVIEW"):
            continue
        if kind == "SECTION":
            hdr = {h.strip().lower(): i for i, h in enumerate(cells)}
            continue
        if hdr is None:
            continue
        col = lambda label: cells[hdr[label]] if label in hdr and hdr[label] < len(cells) else ""
        if "late join" not in col("follow up status").lower():
            continue
        slot = parse_slot(col("time"), day, tz)
        marked = parse_marked(col("follow up time"), day, browser_tz)
        marked_local = marked.astimezone(tz) if marked else None
        mins = (int((marked_local - slot).total_seconds() // 60)
                if slot and marked_local else None)
        show = col("show up")
        out.append({
            "owner": owner, "office": office,
            "name": f"{col('first name')} {col('last name')}".strip(),
            "slot": _clock(slot) if slot else col("time"),
            "marked": _clock(marked_local) if marked_local else "",
            "minutes": mins,
            "by": col("follow up by"),
            # Done By is a dropdown; "None" = nobody ran the interview
            "interviewer": re.sub(r"^SELECT=(None)?", "", col("done by")).strip(),
            "showed_up": "(x)1" in show,
            "too_early": mins is not None and mins < GRACE_MIN,
        })
    return out


def read_day(day: dt.date, only: Optional[List[str]] = None) -> Dict:
    """{'late': [...], 'read': [office ids], 'failed': {id: why}} off AppStream."""
    from automations.late_join_audit import probe
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.sms_thread_dump import run as dump
    late, read, failed = [], [], {}
    with appstream_direct_session(verbose=False) as page:
        tok = dump._rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the AppStream console page")
        browser_tz = ZoneInfo(MARK_TZ)
        for owner, oid in offices():
            if only and oid not in only:
                continue
            try:
                page.goto(f"https://www.applicantstream.com/index.cfm?p=104&rqst={tok}"
                          f"&newOfficeId={oid}")
                page.wait_for_load_state("networkidle")
                time.sleep(1.0)
                raw = probe._day_view(page, tok, day)
                got = rows_to_late_joins(raw, owner, oid, day, browser_tz)
                print(f"  {owner} ({oid}): {len(got)} late join(s)")
                late += got
                read.append(oid)
            except Exception as exc:  # noqa: BLE001 -- one office must not sink the rest
                failed[oid] = f"{type(exc).__name__}: {str(exc)[:120]}"
                print(f"  {owner} ({oid}): FAILED {failed[oid]}")
    return {"late": late, "read": read, "failed": failed}


def _line(r: Dict) -> str:
    mark = "❌" if r["too_early"] else "✅"
    when = (f"marked {r['marked']} ({r['minutes']} min after)" if r["minutes"] is not None
            else "marked time unreadable")
    by = f" by {r['by']}" if r["by"] else ""
    out = f"{mark} *{r['name']}* · slot {r['slot']} · {when}{by}"
    if r["showed_up"]:
        out += " · ⚠️ AppStream says they showed up"
    return out


def summary_text(data: Dict) -> str:
    """The first reply: the day's totals, then who marked them (worst first)."""
    late = data["late"]
    bad = [r for r in late if r["too_early"]]
    lines = [f"*{len(late)} Late Join{'s' if len(late) != 1 else ''}* across "
             f"{len(by_office(data))} offices · ❌ *{len(bad)} marked before the "
             f"{GRACE_MIN}-min grace*"]
    per = {}
    for r in late:
        who = r["by"] or "(nobody named)"
        per.setdefault(who, [0, 0])
        per[who][0] += 1
        per[who][1] += r["too_early"]
    for who, (n, b) in sorted(per.items(), key=lambda kv: (-kv[1][1], -kv[1][0])):
        lines.append(f"• {who}: {n} Late Join{'s' if n != 1 else ''}"
                     f"{f' · ❌ {b} too early' if b else ''}")
    showed = sum(r["showed_up"] for r in late)
    if showed:
        lines.append(f"⚠️ {showed} marked Late Join but AppStream says they showed up")
    if data.get("failed"):
        lines.append(f"_Couldn't read office {', '.join(sorted(data['failed']))}_")
    lines.append(f"_Rule: a Late Join is fair only {GRACE_MIN}+ min after the slot "
                 f"(Rafael 9/30). Source: AppStream → Calendar → day view → First "
                 f"Interviews → Follow Up Status / By / Time._")
    return "\n".join(lines)


def by_office(data: Dict) -> List[tuple]:
    """[((owner, office id), rows)] -- offices with a too-early mark first,
    rows in slot order."""
    per: Dict[tuple, List] = {}
    for r in data["late"]:
        per.setdefault((r["owner"], r["office"]), []).append(r)
    return sorted(per.items(), key=lambda kv: -sum(r["too_early"] for r in kv[1]))


def office_text(owner: str, office: str, rows: List[Dict]) -> str:
    bad = sum(r["too_early"] for r in rows)
    head = (f"*{owner}* ({office}) · {len(rows)} Late Join{'s' if len(rows) != 1 else ''}"
            f"{f' · ❌ {bad} too early' if bad else ''}")
    rows = sorted(rows, key=lambda r: not r["too_early"])     # stable: slot order kept
    return "\n".join([head] + [_line(r) for r in rows])


def thread_title() -> str:
    return "Late Join Audit"


def _ledger() -> Dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def post(day: dt.date, data: Dict, *, preview: bool) -> int:
    """ONE thread per day (Rafael, 2026-09-30: "not something that needs
    consistent monitoring", pick the all-in-one): the day's summary, then one
    reply per office that had Late Joins. A day posts once (the ledger)."""
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    if preview:
        channel = client.conversations_open(users=EVE_USER_ID)["channel"]["id"]
        ts = client.chat_postMessage(
            channel=channel,
            text=(f"*{thread_title()} — {day.strftime('%B')} {smp._ordinal(day.day)} "
                  f"{day.year}*  _(preview — only you see this)_")).get("ts")
    else:
        if day.isoformat() in _ledger().get("_days_done", []):
            print("already posted for this day")
            return 0
        channel = CHANNEL_ID
        ts = smp.ensure_named_thread(thread_title(), day, channel_id=channel).get("thread_ts")
    if not ts:
        print("FAILED - no thread")
        return 1
    texts = [summary_text(data)] + [office_text(o, oid, rows)
                                    for (o, oid), rows in by_office(data)]
    failed = 0
    for t in texts:
        resp = client.chat_postMessage(channel=channel, thread_ts=ts, text=t,
                                       unfurl_links=False, unfurl_media=False)
        failed += 0 if resp.get("ok") else 1
    if not preview and not failed:
        led = _ledger()
        led["_days_done"] = (led.get("_days_done", []) + [day.isoformat()])[-60:]
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(led, indent=1), encoding="utf-8")
    print(f"posted {len(texts) - failed}/{len(texts)} replies")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="late_join_audit.run")
    ap.add_argument("--date", help="YYYY-MM-DD (default: YESTERDAY, Central)")
    ap.add_argument("--office", default="", help="comma list of office ids (default: all org)")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    ap.add_argument("--preview-to-eve", action="store_true", help="post in Eve's DM instead")
    ap.add_argument("--cached", action="store_true",
                    help="reuse this machine's last read of that day (no AppStream)")
    args = ap.parse_args(argv)
    # Rafael 9/30: "a full audit for all of yesterday ... then do that daily"
    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(ZoneInfo(DEFAULT_TZ)).date() - dt.timedelta(days=1))
    only = [o.strip() for o in args.office.split(",") if o.strip()] or None
    print(f"Late Join Audit for {day:%a %b %d, %Y}")
    cache = OUT_DIR / f"{day}.json"
    if args.cached and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        print(f"(from {cache})")
    else:
        data = read_day(day, only)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print("\n" + summary_text(data))
    for (owner, oid), rows in by_office(data):
        print("\n" + office_text(owner, oid, rows))
    if not data["read"]:
        print("no office could be read - nothing posted")
        return 1
    if not args.post:
        print("DRY-RUN: nothing posted")
        return 0
    return post(day, data, preview=args.preview_to_eve)


if __name__ == "__main__":
    raise SystemExit(main())
