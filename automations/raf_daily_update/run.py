"""Raf's Daily Update (Raf, #l10-alphalete, 2026-10-13; live 2026-10-14).

Automates what the recruiters do by hand every evening (Loom
49724e847c734b69beef6e17915bf81f):

  1. ApplicantStream → Reports → Retention Details New → the day's
     2nd round interviews (office 11280), plus the calendar for each
     person's outcome, start date and start time.
  2. One row per candidate on the month's tab of Raf's Daily Update sheet:
     NO SHOW / Leader said no / BOB (+ start date, time) / LM / Letting me
     know / Declined, sorted BOB → Declined → Leader said no → LM. Anyone
     already on the tab for that day is skipped (re-runs and hand entries
     are safe).
  3. Slack (#rafs-office-recruiting-11280): parent "Daily Update M/D", then
     the congrats ask, the pre-made text, the picture of the day's showed
     rows, and a tag for every leader who hired someone. A leader Lucy can't
     tag is named for @Aisha and @Raf to tag; their hand-tag is learned on
     the next run (shared/slack_tag_learning). If a recruiter already posted
     the day's Daily Update, only the tags go into THEIR thread.

Schedule: Report Library card, 5:00 PM CT Mon-Sat (Megan 2026-10-14) —
`--write --post`.

    python -m automations.raf_daily_update.run                        # dry: today
    python -m automations.raf_daily_update.run --date 2026-10-13 --compare-real
    python -m automations.raf_daily_update.run --write --post         # the live run
    python -m automations.raf_daily_update.run --write --test-sheet   # test copy

--seed-from-real reads the day's rows off the real sheet (read-only) instead
of ApplicantStream. Needs the warm 'Lucy Reports' AppStream session.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
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
REAL_SHEET = "1hMdhHAFjFX9QJnXkFzH216Ti6aPbrmiO8DjUU1gaTnw"   # Raf's Daily Update
TEST_SHEET = "15HUvyLJTyLTv_dxwQl2Hmxbs3KKdEZYbaccm8MDEw4o"   # copy made 10/14
CHANNEL = "C0AUAS88FGW"                       # #rafs-office-recruiting-11280
# Who gets asked to tag a leader Lucy can't (Megan 2026-10-14).
TAG_HELPERS = {"Aisha Ceron": "U083X5ZJWSH", "Rafael Hidalgo": "U045Z8N0ZQC"}
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "raf_daily_update"
STATE = OUT_DIR / "state.json"        # posted threads + names awaiting a tag


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

def write_sheet(rows: List[dict], day: dt.date, write: bool,
                sheet_id: str = REAL_SHEET) -> int:
    """Append the day's rows nobody has typed yet, below the tab's last row.
    Only the mapped cells are written — the MONTHLY TOTALS block right of
    the table and every existing row are never touched."""
    ws, lay, grid = read_tab(sheet_id, day)
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
    which = "test sheet" if sheet_id == TEST_SHEET else "sheet"
    log(f"  {which} tab {ws.title!r}: {len(rows)} for {day}, "
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

def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {"posted": {}, "pending": []}


def _save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def learn_pending(client, st: dict) -> None:
    """Read the threads where Lucy asked Aisha/Raf to tag someone; every
    leader they hand-tagged since is learned for good. Asks older than two
    weeks are dropped."""
    from automations.shared import slack_tag_learning as tags
    keep = []
    cutoff = dt.date.today() - dt.timedelta(days=14)
    for p in st.get("pending", []):
        if dt.date.fromisoformat(p["day"]) < cutoff:
            continue
        try:
            msgs = client.conversations_replies(
                channel=p["channel"], ts=p["thread_ts"], limit=200)["messages"]
        except Exception as e:  # noqa: BLE001
            log(f"  !! couldn't read {p['day']} thread for tags: {e}")
            keep.append(p)
            continue
        found = tags.learn_from_replies(client, msgs, p["names"],
                                        after_ts=p["ask_ts"],
                                        source="raf_daily_update")
        for name, sid in found.items():
            log(f"  learned tag: {name} -> {sid}")
        p["names"] = [n for n in p["names"] if n not in found]
        if p["names"]:
            keep.append(p)
    st["pending"] = keep


def _workspace_ids(client) -> Dict[str, str]:
    """{normalized name: id} for active people. EXACT names only — a name
    two people share is dropped, never guessed."""
    out: Dict[str, str] = {}
    dup = set()
    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor)
        for u in resp.get("members", []):
            if u.get("deleted") or u.get("is_bot"):
                continue
            p = u.get("profile", {})
            for n in {L._norm(x) for x in (u.get("real_name"), p.get("real_name"),
                                          p.get("display_name")) if x}:
                if n in out and out[n] != u["id"]:
                    dup.add(n)
                out[n] = u["id"]
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    for n in dup:
        out.pop(n, None)
    return out


def slack_ids(rows: List[dict], client=None) -> Dict[str, str]:
    """{leader name lower: Slack id}: the shared learned-tags list first,
    then (live only) an exact name match in the workspace."""
    from automations.shared import slack_tag_learning as tags
    out, ws = {}, None
    for leader in L.hires_by_leader(rows):
        sid = tags.lookup(leader)
        if not sid and client is not None:
            if ws is None:
                try:
                    ws = _workspace_ids(client)
                except Exception as e:  # noqa: BLE001
                    log(f"  !! workspace lookup failed: {e}")
                    ws = {}
            sid = ws.get(L._norm(leader))
        if sid:
            out[L._norm(leader)] = sid
    return out


def _existing_parent(client, channel: str, day: dt.date) -> str:
    """ts of a Daily Update M/D a recruiter already posted today, or ''."""
    start = dt.datetime.combine(day, dt.time(0), CENTRAL).timestamp()
    want = re.compile(rf"daily update\s+{day.month}/{day.day}\b", re.I)
    try:
        msgs = client.conversations_history(channel=channel, oldest=str(start),
                                            limit=200)["messages"]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"couldn't read the channel before posting: {e}")
    for m in msgs:
        if want.search(m.get("text") or ""):
            return m["ts"]
    return ""


def post(rows: List[dict], day: dt.date, image: Path, channel: str,
         live: bool) -> None:
    from automations.shared import slack_metrics_post as smp
    client = smp._client() if live else None
    st = _load_state()
    if client is not None:
        learn_pending(client, st)
        _save_state(st)
    ids = slack_ids(rows, client)
    missing = [n for n in L.hires_by_leader(rows) if L._norm(n) not in ids]
    tag = L.tag_text(rows, ids, helpers=list(TAG_HELPERS.values()))
    replies = [L.CONGRATS_ASK, L.CONGRATS_HOW, L.CONGRATS_TEXT]
    log(f"  slack -> {channel}" + ("" if live else "  (dry-run, not sent)"))
    log(f"    parent: {L.parent_text(day)}")
    for t in replies:
        log(f"    reply : {t}")
    log(f"    image : {image}")
    for line in tag.splitlines():
        log(f"    tags  : {line}")
    if not live:
        return
    if st.get("posted", {}).get(day.isoformat()):
        log(f"  already posted {day} (thread {st['posted'][day.isoformat()]})"
            " — not posting again")
        return
    theirs = _existing_parent(client, channel, day)
    if theirs:
        # A recruiter beat us to it: don't post a second Daily Update — add
        # only the leader tags (the part they don't post) to THEIR thread.
        log(f"  recruiters already posted Daily Update {day.month}/{day.day} "
            f"({theirs}) — adding only the tags to their thread")
        ts = theirs
    else:
        ts = client.chat_postMessage(channel=channel,
                                     text=L.parent_text(day))["ts"]
        for t in replies:
            client.chat_postMessage(channel=channel, thread_ts=ts, text=t)
        smp.post_reply_with_image(image, comment="", thread_ts=ts,
                                  channel_id=channel, today=day, mirror=False,
                                  wait_visible=True)
    st.setdefault("posted", {})[day.isoformat()] = ts
    _save_state(st)
    if tag:
        ask_ts = client.chat_postMessage(channel=channel, thread_ts=ts,
                                         text=tag)["ts"]
        if missing:
            st.setdefault("pending", []).append(
                {"day": day.isoformat(), "channel": channel, "thread_ts": ts,
                 "ask_ts": ask_ts, "names": missing})
            _save_state(st)
            log(f"  asked Aisha/Raf to tag: {', '.join(missing)}")
    log(f"  posted thread {ts}")


# --------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--write", action="store_true",
                    help="append the day's rows to Raf's Daily Update sheet")
    ap.add_argument("--test-sheet", action="store_true",
                    help="write the TEST copy instead of the real sheet")
    ap.add_argument("--post", action="store_true",
                    help="post the Slack thread")
    ap.add_argument("--channel", default=CHANNEL,
                    help="Slack channel id (default #rafs-office-recruiting-11280)")
    ap.add_argument("--compare-real", action="store_true",
                    help="grade against the recruiters' rows on the real sheet")
    ap.add_argument("--seed-from-real", action="store_true",
                    help="read the day off the real sheet, not ApplicantStream")
    ap.add_argument("--dry-run", action="store_true",
                    help="write and post nothing (the default without flags)")
    args = ap.parse_args(argv)
    if args.dry_run:
        args.write = args.post = False
    if args.seed_from_real and (args.write or args.post):
        ap.error("--seed-from-real is for testing; it can't write or post")

    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(CENTRAL).date())
    log(f"=== raf daily update | {day} | office {OFFICE_ID} | "
        f"{'WRITE' if args.write else 'DRY-RUN'}"
        f"{' + POST' if args.post else ''} ===")
    if day.weekday() == 6 and not args.date:
        log("  Sunday — no 2nd rounds, nothing to do")
        return 0

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
    write_sheet(rows, day, args.write,
                TEST_SHEET if args.test_sheet else REAL_SHEET)

    from automations.raf_daily_update.render import render
    image = render(rows, OUT_DIR / f"daily_update_{day.isoformat()}.png",
                   f"Daily Update {day.month}/{day.day}")
    log(f"  picture: {image}")
    if any(r["status"] != L.NO_SHOW for r in rows):
        post(rows, day, image, args.channel, args.post)
    else:
        log("  nobody showed — no Slack post (never post blank)")
    return 1 if bad and args.compare_real and not args.seed_from_real else 0


if __name__ == "__main__":
    raise SystemExit(main())
