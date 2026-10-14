"""Raf's Daily Update — TEST automation (Raf, #l10-alphalete, 2026-10-13).

Automates what the recruiters do by hand every evening (Loom
49724e847c734b69beef6e17915bf81f):

  1. ApplicantStream → Reports → Retention Details New → the day's
     2nd round interviews (office 11280).
  2. One row per candidate on the month's tab of the Daily Update sheet:
     NO SHOW / Leader said no / BOB (+ start date, time) / LM / Letting me
     know / Declined, sorted BOB → Declined → Leader said no → LM.
  3. Slack: parent "Daily Update M/D", then in the thread the congrats ask,
     the pre-made text, the picture of the day's showed rows, and a tag for
     every leader who hired someone.

TEST ONLY. It writes the TEST copy of the sheet and refuses the real one; it
posts only with --post AND an explicit --channel. Raf: "I don't want it to
impact my real one."

    python -m automations.raf_daily_update.run                        # dry: today
    python -m automations.raf_daily_update.run --date 2026-10-13 --compare-real
    python -m automations.raf_daily_update.run --write                # test sheet
    python -m automations.raf_daily_update.run --write --post --channel C0XXXX

--seed-from-real reads the day's rows off the REAL sheet (read-only) instead
of ApplicantStream — exercises the sheet + picture + Slack legs on a machine
with no AppStream session.

Needs (for the AppStream leg) the warm 'Lucy Reports' session — run on a Lucy:
    lucy rerun raf_daily_update --date 2026-10-13 --compare-real
"""
from __future__ import annotations

import argparse
import re
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

from automations.raf_daily_update import layout as L

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

CENTRAL = ZoneInfo("America/Chicago")
OFFICE_ID = "11280"                                       # Rafael Hidalgo
REAL_SHEET = "1hMdhHAFjFX9QJnXkFzH216Ti6aPbrmiO8DjUU1gaTnw"   # READ ONLY
TEST_SHEET = "15HUvyLJTyLTv_dxwQl2Hmxbs3KKdEZYbaccm8MDEw4o"   # copy made 10/14
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "raf_daily_update"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


# ------------------------------------------------------------------ sources

# The calendar's Follow-Up dropdown (one per applicant row, id followUp_<app
# id>) is where the recruiters record the BOB call. Its row no longer carries
# a "Phone:" label, so daily_update_fill's calendar reader finds nothing on
# 11280; this one keys on the dropdown itself (probed 2026-10-14).
_CALENDAR_JS = r"""() => {
    const out = [];
    document.querySelectorAll('select[id^="followUp_"],select[name^="followUp_"]')
      .forEach(sel => {
        const tr = sel.closest('tr');
        if (!tr) return;
        const cells = [...tr.children].map(td => (td.innerText || '').trim());
        const opt = sel.options[sel.selectedIndex];
        const offer = tr.querySelector('select[name="sOfferPosition"]');
        out.push({first: cells[1] || '', last: cells[2] || '',
                  phone: cells[3] || '',
                  follow: opt ? opt.text.trim() : '',
                  offer: offer && offer.options[offer.selectedIndex]
                         ? offer.options[offer.selectedIndex].text.trim() : '',
                  // last cell = the row's outcome: 'Brought on Board (Oct 19)',
                  // 'Declined (10-13 1:15 PM)', 'Disqualified (...)'
                  outcome: cells[cells.length - 1] || ''});
      });
    return out;
}"""

# Moves the calendar to another day. page.evaluate runs in an isolated world
# where window.cal is invisible, so the call goes in a <script> tag, which
# runs in the page's own world. Display only — changes nothing in AppStream.
_CAL_NAV_JS = r"""(d) => {
    const s = document.createElement('script');
    s.textContent = `try { if (window.jQuery) jQuery("#topLevelDatePicker").val("${d}");
        if (window.cal) { cal.currentDate = "${d}"; cal.currentDateLocale = "${d}"; cal.navigate(); }
        document.body.setAttribute('data-calnav', window.cal ? 'ok' : 'nocal');
    } catch (e) { document.body.setAttribute('data-calnav', 'err'); }`;
    document.head.appendChild(s);
    return document.body.getAttribute('data-calnav');
}"""


# The START day's calendar lists every new start as a "First Day of
# Training" row; its first cell is the time they're scheduled to start —
# the sheet's Time Slot (Megan 2026-10-14). Cesar Flores, 10/19: 12:30 PM.
_TRAINING_JS = r"""() => [...document.querySelectorAll('tr')]
    .filter(tr => tr.children.length > 4 &&
            /First Day of Training/.test(tr.children[tr.children.length - 1].innerText || ''))
    .map(tr => { const c = [...tr.children].map(td => (td.innerText || '').trim());
                 return [c[0], c[1], c[2], c[3]]; })"""


def read_start_times(app, start: dt.date) -> Dict[tuple, str]:
    """{(name, phone10): '12:30'} for the new starts on `start`."""
    try:
        app.open_calendar()
        app.page.wait_for_timeout(10000)
        if start != dt.datetime.now(CENTRAL).date():
            app.page.evaluate(_CAL_NAV_JS, start.strftime("%m/%d/%Y"))
            app.page.wait_for_timeout(15000)
            if not app.page.evaluate("(w) => document.body.innerText.includes(w)",
                                     f"found for {start:%m-%d-%Y}"):
                log(f"  !! calendar did not move to {start}")
                return {}
        rows = app.page.evaluate(_TRAINING_JS)
    except Exception as e:  # noqa: BLE001
        log(f"  !! start-time read failed ({type(e).__name__}: {e})")
        return {}
    out = {}
    for tm, first, last, ph in rows:
        m = re.match(r"\s*(\d{1,2}:\d{2})", tm or "")
        if m:
            out[(L._norm(f"{first} {last}"), _ph10(ph))] = m.group(1)
    log(f"  start day {start}: {len(out)} new start(s) with a time")
    return out


def add_start_times(app, cands: List[dict], day: dt.date) -> None:
    """Fill each BOB's 'orientation' with ' <time>' from their start day."""
    by_start: Dict[dt.date, List[dict]] = {}
    for c in cands:
        if c["bob_status"] != L.BOB or not c["orientation"]:
            continue
        sd = L.parse_sheet_date(c["orientation"], day.year)
        if sd and sd < day - dt.timedelta(days=60):   # Dec BOB, Jan start
            sd = sd.replace(year=day.year + 1)
        if sd:
            by_start.setdefault(sd, []).append(c)
    for sd, group in sorted(by_start.items()):
        times = read_start_times(app, sd)
        for c in group:
            k = (L._norm(c["name"]), _ph10(c["phone"]))
            tm = times.get(k) or next(
                (v for (n, _p), v in times.items() if n == k[0]), "")
            if tm:
                c["orientation"] = f"{c['orientation']} {tm}"


def _ph10(s: str) -> str:
    return re.sub(r"\D", "", str(s or ""))[-10:]


def read_calendar(app, day: dt.date) -> Dict[tuple, dict]:
    """{(name, phone10): row} off the calendar for `day`. Keyed by phone as
    well as name: two different Oscar Castellons sat on 10/13's calendar."""
    try:
        app.open_calendar()
        app.page.wait_for_timeout(10000)            # rows render late
        if day != dt.datetime.now(CENTRAL).date():
            app.page.evaluate(_CAL_NAV_JS, day.strftime("%m/%d/%Y"))
            app.page.wait_for_timeout(15000)
            want = f"found for {day:%m-%d-%Y}"
            if not app.page.evaluate("(w) => document.body.innerText.includes(w)",
                                     want):
                log(f"  !! calendar did not move to {day}")
                return {}
        rows = app.page.evaluate(_CALENDAR_JS)
    except Exception as e:  # noqa: BLE001
        log(f"  !! calendar read failed ({type(e).__name__}: {e})")
        return {}
    out = {}
    for r in rows:
        k = (L._norm(f"{r['first']} {r['last']}"), _ph10(r["phone"]))
        if k[0]:
            out[k] = r
    log(f"  calendar {day}: {len(rows)} rows")
    return out


def calendar_result(r: dict) -> dict:
    """One calendar row → what it says about the BOB call.
    {'outcome': 'BOB'|'Declined'|'Leader said no'|'LM'|'Letting me know'|'',
     'bob_date': '10/19' or ''}"""
    outcome = r.get("outcome", "")
    follow = L._norm(r.get("follow", ""))
    m = re.search(r"Brought on Board\s*\(([^)]+)\)", outcome, re.I)
    bob_date = L.split_orientation(m.group(1))[0] if m else ""
    if m or follow == "bob - booked":
        res = L.BOB
    elif re.match(r"\s*declined", outcome, re.I):
        res = L.DECLINED
    elif re.match(r"\s*disqualified", outcome, re.I) or \
            L._norm(r.get("offer")) == "no":
        res = L.LEADER_NO
    elif follow.startswith("bob - waiting"):
        res = L.LETTING
    elif follow.startswith("bob - called") or follow in ("left message",
                                                          "no answer"):
        res = L.LM
    else:
        res = ""
    return {"outcome": res, "bob_date": bob_date}


def harvest(day: dt.date) -> List[dict]:
    """The day's 2nd-round candidates from ApplicantStream (Retention Details
    → the day's 2nd-round detail pages), plus the calendar's BOB-call result
    when the day is today."""
    from automations.applicant_tracker.applicantstream import session
    from automations.applicant_tracker.run import (
        L_2ND_ROSTER, L_2ND_SHOWED, L_OFFERED, L_BOB, N_2R_COLS,
        date_header_for)
    from automations.daily_update_fill.run import ensure_week, pick_sunday

    def names(rows):
        return {L._norm(f"{r[0]} {r[1]}") for r in rows if len(r) >= 2}

    with session() as app:
        log(f"  office {OFFICE_ID}: {app.select_office(OFFICE_ID)}")
        app.open_retention_details()
        if not ensure_week(app, pick_sunday(day)):
            raise RuntimeError(f"Retention Details would not open week of {day}")
        h = date_header_for(day)
        hrefs = {lbl: app.detail_href(lbl, h) for lbl in
                 (L_2ND_ROSTER, L_2ND_SHOWED, L_OFFERED, L_BOB)}
        roster = app.scrape_at(hrefs[L_2ND_ROSTER], N_2R_COLS) \
            if hrefs[L_2ND_ROSTER] else []
        showed = names(app.scrape_at(hrefs[L_2ND_SHOWED], 2)) \
            if hrefs[L_2ND_SHOWED] else set()
        offered = names(app.scrape_at(hrefs[L_OFFERED], 2)) \
            if hrefs[L_OFFERED] else set()
        # BOB page: First, Last, Email, Phone, Rating, Job Board, When, Ad
        bob_rows = app.scrape_at(hrefs[L_BOB], 8) if hrefs[L_BOB] else []
        cal = read_calendar(app, day)
        earlier = _find_earlier_interviews(
            app, day, names(bob_rows) - names(roster),
            ensure_week, pick_sunday, date_header_for, L_2ND_ROSTER, N_2R_COLS)
    bob = names(bob_rows)
    log(f"  {day}: roster={len(roster)} showed={len(showed)} "
        f"offered={len(offered)} bob={len(bob)} calendar={len(cal)}")

    cands, seen = [], set()

    def add(r, first_rd, second_rd, ad):
        key = L._norm(f"{r[0]} {r[1]}")
        if not key or key in seen:
            return
        seen.add(key)
        did_show = key in showed or key in bob
        row = cal.get((key, _ph10(r[3]))) or next(
            (v for (n, _p), v in cal.items() if n == key), None)
        res = calendar_result(row) if row else {"outcome": "", "bob_date": ""}
        out = L.BOB if key in bob else res["outcome"]
        cands.append({
            "day": day, "first": r[0].strip(), "last": r[1].strip(),
            "name": f"{r[0]} {r[1]}".strip(), "email": r[2].strip(),
            "phone": r[3].strip(), "first_round": first_rd,
            # A no-show had no 2nd round; AppStream repeats the 1st-round
            # person there, the sheet leaves it blank (Loom: "done by: none").
            "second_round": second_rd if did_show else "",
            "ad": ad, "show": "Showed" if did_show else "No Show",
            "offered": ("N" if out == L.LEADER_NO else
                        "Y" if (key in offered or key in bob or out) else "N")
            if did_show else "",
            "bob_status": out, "orientation": res["bob_date"]})

    for r in roster:                    # First Last Email Phone Rating 1st 2nd Board When Ad
        r = [str(x) for x in r] + [""] * (10 - len(r))
        add(r, r[5].strip(), r[6].strip(), r[9].strip())
    # BOB'd that day but interviewed under another date (Danny Martinez,
    # 10/13): still a hire today, still on the update.
    for r in bob_rows:
        r = [str(x) for x in r] + [""] * (8 - len(r))
        key = L._norm(f"{r[0]} {r[1]}")
        if key in earlier:              # his real interview row + start date
            er, start = earlier[key]
            add(er, er[5].strip(), er[6].strip(), er[9].strip())
            if cands and cands[-1]["name"].lower() == key and start:
                cands[-1]["orientation"] = start
        else:
            add(r, "", "", r[7].strip())
    if any(c["bob_status"] == L.BOB and c["orientation"] for c in cands):
        with session() as app:
            app.select_office(OFFICE_ID)
            add_start_times(app, cands, day)
    return cands


def _find_earlier_interviews(app, day, wanted, ensure_week, pick_sunday,
                             date_header_for, roster_label, n_cols,
                             lookback: int = 7) -> Dict[str, tuple]:
    """{name: (roster row, start date)} for people BOB'd on `day` who
    interviewed on an earlier day. The recruiters list them under the BOB
    day with that interview's leaders and the start date (Danny Martinez:
    2nd round 10/12, BOB 10/13, on the sheet under both)."""
    found: Dict[str, tuple] = {}
    for back in range(1, lookback + 1):
        if not wanted - set(found):
            break
        d = day - dt.timedelta(days=back)
        app.open_retention_details()
        if not ensure_week(app, pick_sunday(d)):
            continue
        href = app.detail_href(roster_label, date_header_for(d))
        if not href:
            continue
        hits = {}
        for r in app.scrape_at(href, n_cols):
            r = [str(x) for x in r] + [""] * (n_cols - len(r))
            k = L._norm(f"{r[0]} {r[1]}")
            if k in wanted and k not in found:
                hits[k] = r
        if not hits:
            continue
        cal = read_calendar(app, d)
        for k, r in hits.items():
            row = cal.get((k, _ph10(r[3])))
            start = calendar_result(row)["bob_date"] if row else ""
            found[k] = (r, start)
            log(f"  {k}: BOB'd {day}, interviewed {d}"
                + (f", starts {start}" if start else ""))
    return found


def _open(sheet_id: str):
    from automations.recruiting_report.fill import _retry, open_by_key
    return _retry(lambda: open_by_key(sheet_id))


def read_tab(sheet_id: str, day: dt.date):
    """(worksheet, layout, grid) for the month tab holding `day`."""
    sh = _open(sheet_id)
    title = L.month_tab([w.title for w in sh.worksheets()], day)
    if not title:
        raise RuntimeError(f"No month tab for {day:%B %Y} in {sh.title!r}")
    ws = sh.worksheet(title)
    grid = ws.get_values("A1:N")
    lay = L.resolve(grid[0] if grid else [])
    return ws, lay, grid


def sheet_rows(grid, lay, day: dt.date) -> List[dict]:
    """The day's rows as typed on a sheet, in layout-key dicts."""
    out = []
    for raw in grid[1:]:
        raw = list(raw) + [""] * 20
        d = L.parse_sheet_date(raw[lay["date"]], day.year)
        if d != day:
            continue
        r = {k: str(raw[i]).strip() for k, i in lay.items()}
        r["_day"] = d
        if r["first"] or r["last"]:
            out.append(r)
    return out


def seed_from_real(day: dt.date) -> List[dict]:
    """Real sheet rows → candidate dicts shaped like harvest_office's, so the
    rest of the run can't tell the difference."""
    _ws, lay, grid = read_tab(REAL_SHEET, day)
    cands = []
    for r in sheet_rows(grid, lay, day):
        st = r["status"]
        rank = L.ORDER[L.status_rank(st)]
        show = "No Show" if rank == L.NO_SHOW else "Showed"
        offered = "" if show == "No Show" else (
            "N" if rank == L.LEADER_NO else "Y")
        bob = {L.BOB: "BOB", L.LM: "LM", L.LETTING: "Letting us know",
               L.DECLINED: "Declined"}.get(rank, "")
        orient = f"{r.get('bob_date', '')} {r.get('time', '')}".strip()
        cands.append({
            "day": day, "name": f"{r['first']} {r['last']}".strip(),
            "first": r["first"], "last": r["last"], "email": r["email"],
            "phone": r["phone"], "first_round": r["int1"],
            "second_round": r["int2"], "ad": r.get("ad", ""), "show": show,
            "offered": offered, "bob_status": bob, "orientation": orient})
    return cands


# --------------------------------------------------------------- comparison

def compare(rows: List[dict], day: dt.date) -> int:
    """Grade the automation against what the recruiters typed on the REAL
    sheet for `day`. Read-only. Returns the number of mismatches."""
    _ws, lay, grid = read_tab(REAL_SHEET, day)
    typed = {L.person_key(day, r["first"], r["last"]): r
             for r in sheet_rows(grid, lay, day)}
    ours = {L.person_key(day, r["first"], r["last"]): r for r in rows}
    bad = 0
    log(f"compare vs REAL sheet {day}: ours={len(ours)} typed={len(typed)}")
    for k in sorted(set(ours) | set(typed), key=lambda k: k[1]):
        o, t = ours.get(k), typed.get(k)
        if not t:
            log(f"  + only in AppStream: {k[1]} ({o['status'] or 'to call'})")
            bad += 1
            continue
        if not o:
            log(f"  - only on sheet:     {k[1]} ({t['status']})")
            bad += 1
            continue
        want = L.ORDER[L.status_rank(t["status"])]
        diffs = []
        if o["status"] != want:
            diffs.append(f"status {o['status'] or 'to call'!r} vs {want!r}")
        if L.phone(t["phone"]) != o["phone"]:
            diffs.append(f"phone {o['phone']} vs {t['phone']}")
        if want == L.BOB and t.get("bob_date") and \
                L.split_orientation(t["bob_date"])[0] != o["bob_date"]:
            diffs.append(f"BOB date {o['bob_date']!r} vs {t['bob_date']!r}")
        if want == L.BOB and t.get("time") and \
                L._norm(t["time"]) != L._norm(o["time"]):
            diffs.append(f"time {o['time']!r} vs {t['time']!r}")
        if L._norm(o["int2"]) != L._norm(t["int2"]) and t["int2"]:
            diffs.append(f"2nd rd {o['int2']!r} vs {t['int2']!r}")
        if L._norm(o["int1"]) != L._norm(t["int1"]) and t["int1"]:
            diffs.append(f"1st rd {o['int1']!r} vs {t['int1']!r}")
        if L._norm(o["email"]) != L._norm(t["email"]) and t["email"]:
            diffs.append(f"email {o['email']!r} vs {t['email']!r}")
        if diffs:
            bad += 1
            log(f"  ~ {k[1]}: " + "; ".join(diffs))
    log(f"compare: {len(set(ours) | set(typed)) - bad} match, {bad} differ")
    return bad


# -------------------------------------------------------------------- write

def write_test_sheet(rows: List[dict], day: dt.date, write: bool) -> int:
    if TEST_SHEET == REAL_SHEET:                       # belt and braces
        raise RuntimeError("refusing to write Raf's real Daily Update")
    ws, lay, grid = read_tab(TEST_SHEET, day)
    cols = sorted(lay.values())
    have = []
    last = 1
    for i, raw in enumerate(grid[1:], 2):
        raw = list(raw) + [""] * 20
        if any(str(raw[c]).strip() for c in cols):
            last = i
        d = L.parse_sheet_date(raw[lay["date"]], day.year)
        if d:
            have.append(L.person_key(d, raw[lay["first"]], raw[lay["last"]]))
    add = L.new_rows(rows, have)
    log(f"  test sheet tab {ws.title!r}: {len(rows)} for {day}, "
        f"{len(rows) - len(add)} already there, appending {len(add)} "
        f"at row {last + 1}" + ("" if write else "  (dry-run)"))
    if not (write and add):
        return len(add)
    need = last + len(add)
    if need > ws.row_count:
        ws.add_rows(need - ws.row_count + 10)
    data = []
    for n, r in enumerate(add, last + 1):
        for key in ("date", "int1", "int2", "first", "last", "phone",
                    "status", "bob_date", "time", "email", "ad"):
            if key in lay and r.get(key):
                data.append({"range": f"'{ws.title}'!{L.col_letter(lay[key])}{n}",
                             "values": [[r[key]]]})
    ws.spreadsheet.values_batch_update(
        body={"valueInputOption": "USER_ENTERED", "data": data})
    return len(add)


# -------------------------------------------------------------------- slack

def slack_ids(rows: List[dict], live: bool) -> Dict[str, str]:
    """{leader name lower: Slack id}. The shared learned-tags list first; on
    a live post, the workspace member list for anyone it lacks."""
    from automations.shared import slack_tag_learning as tags
    out = {}
    client = None
    for leader in L.hires_by_leader(rows):
        sid = tags.lookup(leader)
        if not sid and live:
            from automations.shared import slack_metrics_post as smp
            client = client or smp._client()
            try:
                sid = smp._resolve_user_id(client, leader)
            except Exception:  # noqa: BLE001
                sid = None
        if sid:
            out[L._norm(leader)] = sid
    return out


def post(rows: List[dict], day: dt.date, image: Path, channel: str,
         live: bool) -> None:
    from automations.shared import slack_metrics_post as smp
    ids = slack_ids(rows, live)
    tag = L.tag_text(rows, ids)
    replies = [L.CONGRATS_ASK, L.CONGRATS_HOW, L.CONGRATS_TEXT]
    log(f"  slack -> {channel}" + ("" if live else "  (dry-run, not sent)"))
    log(f"    parent: {L.parent_text(day)}")
    for t in replies:
        log(f"    reply : {t}")
    log(f"    image : {image}")
    for line in tag.splitlines():
        log(f"    tags  : {line}")
    missing = [n for n in L.hires_by_leader(rows) if L._norm(n) not in ids]
    if missing:
        log(f"    (no Slack id yet for: {', '.join(missing)} — shown bold)")
    if not live:
        return
    client = smp._client()
    ts = client.chat_postMessage(channel=channel,
                                 text=L.parent_text(day))["ts"]
    for t in replies:
        client.chat_postMessage(channel=channel, thread_ts=ts, text=t)
    smp.post_reply_with_image(image, comment="", thread_ts=ts,
                              channel_id=channel, today=day, mirror=False,
                              wait_visible=True)
    if tag:
        client.chat_postMessage(channel=channel, thread_ts=ts, text=tag)
    log(f"  posted thread {ts}")


# --------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--write", action="store_true",
                    help="append to the TEST sheet (never the real one)")
    ap.add_argument("--post", action="store_true",
                    help="post the Slack thread (needs --channel)")
    ap.add_argument("--channel", default=None, help="test Slack channel id")
    ap.add_argument("--compare-real", action="store_true",
                    help="grade against the recruiters' rows on the real sheet")
    ap.add_argument("--seed-from-real", action="store_true",
                    help="read the day off the real sheet, not ApplicantStream")
    ap.add_argument("--dry-run", action="store_true",
                    help="accepted for the lucy queue; dry is the default")
    args = ap.parse_args(argv)
    if args.post and not args.channel:
        ap.error("--post needs an explicit --channel (test channel)")
    if args.dry_run:
        args.write = args.post = False

    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(CENTRAL).date())
    log(f"=== raf daily update (TEST) | {day} | office {OFFICE_ID} | "
        f"{'WRITE' if args.write else 'DRY-RUN'}"
        f"{' + POST' if args.post else ''} ===")

    cands = seed_from_real(day) if args.seed_from_real else harvest(day)
    rows = L.build_rows(cands)
    log(f"  {L.summary_line(rows)}")
    for r in rows:
        log(f"    {r['status'] or 'to call':<16} {r['first']} {r['last']:<22} "
            f"2nd: {r['int2']:<22} {r['bob_date']} {r['time']}")
    bad = compare(rows, day) if args.compare_real else 0

    if not rows:
        log("  no 2nd rounds for this day — nothing to write or post")
        return 0
    write_test_sheet(rows, day, args.write)

    from automations.raf_daily_update.render import render
    image = render(rows, OUT_DIR / f"daily_update_{day.isoformat()}.png",
                   f"Daily Update {day.month}/{day.day}")
    log(f"  picture: {image}")
    if any(r["status"] != L.NO_SHOW for r in rows):
        post(rows, day, image, args.channel or "(no channel)", args.post)
    else:
        log("  nobody showed — no Slack post (never post blank)")
    return 1 if bad and args.compare_real and not args.seed_from_real else 0


if __name__ == "__main__":
    raise SystemExit(main())
