"""Who gets a background check: ApplicantStream Calendar -> SECOND INTERVIEWS
-> "Offer Position?" = Yes.

Megan 2026-11-03, with a screenshot of the calendar: "It should be anyone
marked yes in the offered position here in the second interview calendar."
That matches ARS "BOB Process" step 2 -- "Send the BGC link for all those
that we want to BOB" -- which comes BEFORE the BOB call, so the Retention
Details "Brought on Board Booked" row (filled after the call) would be too
late.

The dropdown is <select id="sOfferPosition" class="offerPosition"> (read
off Omar's real calendar 2026-11-03 -- an id, not a name). A row with Show Up =
No has no dropdown at all, so it can never come back as offered.

TWO CALENDARS (Megan 2026-11-03). Each ApplicantStream login can switch to
"version 2" (Applicant Interview Calendar, p=1511): tabs across the top --
1st Interview / 2nd Interview / FDOT/BOB / First Day of Sales -- the orange
"2nd Interview" tab has to be CLICKED, the table pages 50 at a time, and the
name is ONE "Name" column. read() recognises which one is on screen and
reads that one; neither recognised = an error, never an empty list.

Columns are found by HEADER TEXT ("First Name", "Last Name", "Phone",
"Email"), never by position, and only rows under the SECOND INTERVIEWS
banner count. If the banner can't be found the read FAILS rather than
guessing -- a wrong section would send background checks to 1st rounds.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List

SECTION = "SECOND INTERVIEWS"
# Read off Omar's real calendar 2026-11-03: <select id="sOfferPosition"
# class="offerPosition"> -- an id (repeated on every row), NOT a name.
OFFER_SELECT = 'select[id="sOfferPosition"], select.offerPosition, select[name="sOfferPosition"]'

# -> {ok, error, rows: [{first, last, phone, email, offer, section}]}
READ_JS = r"""(want) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  // A section banner: an element with no table rows inside whose text STARTS
  // with upper-case words ending in INTERVIEW(S)/ORIENTATION/TRAINING --
  // "SECOND INTERVIEWS   Brought on Board: 0 | 3rd Interview Comp..."
  const banner = /^([A-Z0-9 &]*?(INTERVIEWS?|ORIENTATIONS?|TRAINING))\b/;
  const out = [];
  let section = '', header = null, sawSection = false;
  for (const n of document.querySelectorAll('tr, td, th, div, span, h1, h2, h3, h4, b, strong')) {
    if (n.tagName !== 'TR') {
      if (n.querySelector('tr')) continue;
      const m = norm(n.innerText).match(banner);
      if (m && m[1] !== section) {
        section = m[1];
        header = null;
        if (section.indexOf(want) === 0) sawSection = true;
      }
      continue;
    }
    if (n.querySelector('tr')) continue;          // a layout row, not a data row
    const texts = [...n.children].map(c => norm(c.innerText));
    const low = texts.map(t => t.toLowerCase().replace(/[^a-z ]/g, '').trim());
    if (low.includes('first name') && low.includes('email')) {
      // Every section has its own header row. A SECOND header row in the same
      // section means a new section began under a banner we did not
      // recognise -- so stop counting it as the old one.
      if (header) section = '';
      header = {};
      for (const k of ['first name', 'last name', 'phone', 'email']) {
        const i = low.indexOf(k);
        if (i >= 0) header[k] = i;
      }
      continue;
    }
    const sel = n.querySelector('select[id="sOfferPosition"], select.offerPosition, select[name="sOfferPosition"]');
    if (!sel || !header) continue;
    const opt = sel.options[sel.selectedIndex];
    const at = k => (k in header && header[k] < texts.length) ? texts[header[k]] : '';
    out.push({first: at('first name'), last: at('last name'), phone: at('phone'),
              email: at('email'), offer: opt ? norm(opt.text) : '', section: section});
  }
  if (!sawSection) return {ok: false, error: 'no "' + want + '" banner on the calendar', rows: out};
  return {ok: true, rows: out};
}"""


def offered_yes(rows: List[Dict]) -> List[Dict]:
    """Second-interview rows whose Offer Position is Yes, one per person."""
    out, seen = [], set()
    for r in rows:
        if not str(r.get("section", "")).upper().startswith(SECTION):
            continue
        if str(r.get("offer", "")).strip().lower() != "yes":
            continue
        first = str(r.get("first") or "").strip()
        last = str(r.get("last") or "").strip()
        phone = re.sub(r"\D", "", str(r.get("phone") or ""))[-10:]
        key = (first.lower(), last.lower(), phone)
        if not first or key in seen:
            continue
        seen.add(key)
        out.append({"first_name": first, "last_name": last,
                    "email": str(r.get("email") or "").strip(),
                    "phone": phone, "stage": "Offered (2nd round)"})
    return out


# --- version 2 -------------------------------------------------------------
V2_TAB = "2nd Interview"

# Is the V2 calendar on screen? Its tab strip carries "2nd Interview" and
# "First Day of Sales" side by side.
IS_V2_JS = r"""() => {
  const t = document.body.innerText || '';
  return /Applicant Interview Calendar/i.test(t) && /2nd Interview/.test(t) && /First Day of Sales/.test(t);
}"""

# Pick the biggest "Show N entries" option on the visible table.
V2_ALL_ROWS_JS = r"""() => {
  const sel = [...document.querySelectorAll('select')].find(s =>
      s.offsetParent && /_length$/.test(s.name || '') ||
      (s.offsetParent && /entries/i.test((s.closest('label') || {}).innerText || '')));
  if (!sel) return '';
  let best = null;
  for (const o of sel.options) {
    const v = parseInt(o.value, 10);
    if (v === -1) { best = o; break; }
    if (!best || v > parseInt(best.value, 10)) best = o;
  }
  if (!best) return '';
  sel.value = best.value;
  sel.dispatchEvent(new Event('change', {bubbles: true}));
  return best.text;
}"""

# -> {ok, error, rows: [{name, phone, email, offer, has_offer_control}], info}
V2_READ_JS = r"""() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const tables = [...document.querySelectorAll('table')].filter(t => t.offsetParent);
  let table = null, col = null;
  for (const t of tables) {
    const hdr = t.querySelector('thead tr') || t.querySelector('tr');
    if (!hdr) continue;
    const low = [...hdr.children].map(c => norm(c.innerText).toLowerCase().replace(/[^a-z ]/g, '').trim());
    if (low.includes('name') && low.includes('email')) {
      table = t;
      col = {name: low.indexOf('name'), phone: low.indexOf('phone'),
             email: low.indexOf('email'), show: low.indexOf('show up')};
      break;
    }
  }
  if (!table) return {ok: false, error: 'no Name/Email table on the 2nd Interview tab', rows: []};
  const rows = [];
  for (const tr of table.querySelectorAll('tbody tr')) {
    const cells = [...tr.children];
    if (cells.length < 3) continue;          // "No data available" row
    const text = i => (i >= 0 && i < cells.length) ? norm(cells[i].innerText) : '';
    const sels = [...tr.querySelectorAll('select')];
    const offerSel = sels.find(x => x.id === 'sOfferPosition' || (x.name || '') === 'sOfferPosition' ||
                                   x.classList.contains('offerPosition')) ||
      sels.find(x => /offer/i.test((x.name || '') + ' ' + (x.id || ''))) ||
      sels.find(x => /offer position/i.test(norm((x.closest('td') || {}).innerText)));
    const opt = offerSel ? offerSel.options[offerSel.selectedIndex] : null;
    rows.push({name: text(col.name), phone: text(col.phone), email: text(col.email),
               show: text(col.show), offer: opt ? norm(opt.text) : '',
               has_offer_control: !!offerSel});
  }
  const info = [...document.querySelectorAll('.dataTables_info, [id$="_info"]')]
      .filter(x => x.offsetParent).map(x => norm(x.innerText))[0] || '';
  return {ok: true, rows: rows, info: info};
}"""

_SHOWING = re.compile(r"Showing\s+([\d,]+)\s+to\s+([\d,]+)\s+of\s+([\d,]+)", re.I)


def split_name(full: str):
    """'Evelyn Raudales' -> ('Evelyn', 'Raudales'). V2 shows one Name
    column; everything after the first word is the last name."""
    parts = (full or "").split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def v2_offered_yes(rows: List[Dict]) -> List[Dict]:
    out = []
    for r in rows:
        first, last = split_name(r.get("name", ""))
        out.append({"first": first, "last": last, "phone": r.get("phone", ""),
                    "email": r.get("email", ""), "offer": r.get("offer", ""),
                    "section": SECTION})
    return offered_yes(out)


def check_v2_rows(rows: List[Dict]) -> None:
    """Refuse a read we can't trust: people who SHOWED on the 2nd Interview
    tab but no Offer Position control anywhere means the page changed (or
    the column is somewhere we don't look) -- not that nobody was offered."""
    showed = [r for r in rows if "show" in str(r.get("show", "")).lower()
              and "not" not in str(r.get("show", "")).lower()]
    if showed and not any(r.get("has_offer_control") for r in rows):
        raise RuntimeError("V2 calendar: %d showed up on the 2nd Interview tab but no "
                           "Offer Position control was found -- page layout changed?" % len(showed))


def read_v2(app, log=print) -> List[Dict]:
    """Today's offered-yes rows off the V2 calendar's 2nd Interview tab."""
    page = app.page
    tab = page.get_by_text(re.compile(r"^\s*%s\b" % re.escape(V2_TAB))).first
    tab.click()
    page.wait_for_timeout(4000)
    shown = page.evaluate(V2_ALL_ROWS_JS)
    if shown:
        page.wait_for_timeout(3000)
    rows: List[Dict] = []
    for _ in range(50):                          # pages, if "all" wasn't offered
        got = page.evaluate(V2_READ_JS)
        if not got.get("ok"):
            raise RuntimeError("V2 calendar: %s" % got.get("error"))
        rows.extend(got.get("rows") or [])
        m = _SHOWING.search(got.get("info") or "")
        if not m or int(m.group(2).replace(",", "")) >= int(m.group(3).replace(",", "")):
            break
        nxt = page.locator(".paginate_button.next:not(.disabled), a.next:not(.disabled)").first
        if not nxt.count():
            raise RuntimeError("V2 calendar: more rows than shown and no Next button (%s)" % got.get("info"))
        nxt.click()
        page.wait_for_timeout(2500)
    check_v2_rows(rows)
    people = v2_offered_yes(rows)
    log("  V2 calendar, 2nd Interview tab: %d rows, %d offered" % (len(rows), len(people)))
    return people


def read(app, office_id: str, day: dt.date, log=print) -> List[Dict]:
    """Today's offered-yes second interviews for one office. `app` is an
    applicant_tracker ApplicantStream session. Raises when the calendar
    can't be read -- an empty list means it WAS read and nobody is offered."""
    from automations.raf_daily_update.run import _CAL_NAV_JS
    app.select_office(office_id)
    app.open_calendar()
    app.page.wait_for_timeout(10000)                    # rows render late
    if day != dt.date.today() and not app.page.evaluate(IS_V2_JS):
        app.page.evaluate(_CAL_NAV_JS, day.strftime("%m/%d/%Y"))
        app.page.wait_for_timeout(15000)
        want = "found for %s" % day.strftime("%m-%d-%Y")
        if not app.page.evaluate("(w) => document.body.innerText.includes(w)", want):
            raise RuntimeError("the calendar would not move to %s" % day)
    if app.page.evaluate(IS_V2_JS):
        if day != dt.date.today():
            raise RuntimeError("the V2 calendar can only be read for today")
        return read_v2(app, log=log)
    got = app.page.evaluate(READ_JS, SECTION)
    if not got.get("ok"):
        raise RuntimeError("calendar (neither version recognised): %s" % got.get("error"))
    people = offered_yes(got.get("rows") or [])
    log("  calendar %s: %d second-interview rows, %d offered" % (
        day, sum(1 for r in got["rows"] if str(r.get("section", "")).upper().startswith(SECTION)),
        len(people)))
    return people


def main(argv=None) -> int:
    """Read-only check: who would get a background check today.

        python -m automations.office_admin.offered --office 24153
        python -m automations.office_admin.offered --office 24153 --date 2026-11-02
    """
    import argparse
    ap = argparse.ArgumentParser(description="Today's offered second interviews (read-only).")
    ap.add_argument("--office", required=True, help="ApplicantStream office id, e.g. 24153")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    from automations.applicant_tracker.applicantstream import session
    with session() as app:
        people = read(app, args.office, day)
    for p in people:
        print("  %-28s %-12s %s" % ("%s %s" % (p["first_name"], p["last_name"]),
                                    p["phone"], p["email"] or "(no email)"))
    print("%d offered on %s" % (len(people), day))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
