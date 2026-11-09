"""Background-check status from the Sterling EMAILS -> the relay, for the office
admin extension's "Next week's starts" list.

WHY (Megan 2026-11-06): on Fridays the admin may re-send the Sterling link to
people starting the following week. WHO starts comes from the ApplicantStream
calendars themselves (the extension reads next week's "First Day of Training"
rows on the office's selected accounts) -- not the onboarding checklist, which
only Raf's office has. What the list still needs is each person's background
check STATUS, and that comes from the Sterling / First Advantage result emails
(the same parse bg_check_sync uses). This copies the latest status per person
onto the relay workbook's 'BG Status' tab; the extension matches it by name.

Someone with NO result email yet hasn't taken their check -- the extension
ticks them by default.

    python -m automations.office_admin.roster_publish            # last 45 days of emails
    python -m automations.office_admin.roster_publish --dry-run  # print, write nothing

bg_check_sync calls publish() after each pass (11:30 / 4pm on Lucy 1).

WHERE THE RESULTS COME FROM. Raf's land in his own inbox (raffi127, read by
bg_check_sync's email_source). Every other office forwards its Sterling RESULT
mails to lucysterlingreports@gmail.com (sterling_forward.walk_results); a
forwarded mail carries the ICD's address in X-Forwarded-For, and the relay's
'Sterling Results Mail' tab says which office that address is.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Dict, List

TAB = "BG Status"
HEAD = ["Office", "First", "Last", "Status", "Email Date", "Updated"]
OFFICE = "raf"
DAYS = 45


def latest_by_person(events) -> List[Dict]:
    """One row per person: the most advanced status, newest email breaking ties
    (the same ranking bg_check_sync uses)."""
    best: Dict[str, object] = {}
    for e in events:
        key = "%s|%s" % (" ".join(e.first.lower().split()), " ".join(e.last.lower().split()))
        cur = best.get(key)
        if cur is None or (e.rank, e.date) > (cur.rank, cur.date):
            best[key] = e
    out = [{"first": e.first.strip(), "last": e.last.strip(), "status": e.status,
            "date": str(e.date)[:10]} for e in best.values()]
    out.sort(key=lambda r: (r["last"].lower(), r["first"].lower()))
    return out


def write(office: str, people: List[Dict], now: str) -> None:
    """Replace this office's rows on the relay's 'BG Status' tab."""
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    ss = open_by_key(P.RELAY_SPREADSHEET_ID)
    titles = [w.title for w in _retry(ss.worksheets)]
    ws = (_retry(ss.worksheet, TAB) if TAB in titles
          else _retry(ss.add_worksheet, title=TAB, rows=500, cols=len(HEAD)))
    vals = _retry(ws.get_all_values)
    keep = [r for r in vals[1:] if r and r[0].strip().lower() != office]
    rows = [[office, p["first"], p["last"], p["status"], p["date"], now] for p in people]
    _retry(ws.clear)
    _retry(ws.update, [HEAD] + keep + rows, "A1")


def _results_office_map() -> Dict[str, str]:
    """ICD address -> office key, off the relay's 'Sterling Results Mail' tab."""
    from automations.icd_alerts import code_answer as CA
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    book = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        rows = _retry(book.worksheet(CA.SERVICES[CA.STERLING_RESULTS]["tab"]).get_all_values)
    except Exception:  # noqa: BLE001 -- no office has set it up yet
        return {}
    return {r[1].strip().lower(): r[0].strip().lower() for r in rows[1:]
            if len(r) > 1 and r[0].strip() and "@" in r[1]}


def results_inbox_events(days: int = DAYS) -> Dict[str, list]:
    """office -> [BGEvent] from the results inbox, by X-Forwarded-For."""
    import email
    import imaplib
    import re
    from automations.bg_check_sync import email_source as ES, parse
    from automations.icd_alerts import code_answer as CA
    if not CA.RESULTS_APP_PW.exists():
        return {}
    who = _results_office_map()
    if not who:
        return {}
    M = imaplib.IMAP4_SSL(ES.IMAP_HOST)
    M.login(CA.RESULTS_INBOX, CA.RESULTS_APP_PW.read_text(encoding="utf-8-sig").strip().replace(" ", ""))
    out: Dict[str, list] = {}
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        since = (dt.date.today() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, '(FROM "%s" SINCE %s)' % (ES.FADV_SENDER, since))
        for mid in (data[0] or b"").split() if typ == "OK" else []:
            typ, got = M.fetch(mid, "(RFC822)")
            if typ != "OK" or not got or not got[0]:
                continue
            msg = email.message_from_bytes(got[0][1])
            # The forwarding Gmail first, then the Sterling-login email it was
            # sent to -- an ICD may have given either during setup.
            fwd = re.findall(r"[\w.+-]+@[\w.-]+\w", (msg.get("X-Forwarded-For", "") or "") + " " + (msg.get("To", "") or ""))
            office = next((who[a.lower()] for a in fwd if a.lower() in who), "")
            if not office:
                continue
            ev = parse.classify(ES._decode(msg.get("From", "")), ES._decode(msg.get("Subject", "")),
                                ES._best_text(msg), date=ES._to_iso(msg.get("Date", "")),
                                source_id=mid.decode())
            if ev:
                out.setdefault(office, []).append(ev)
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def publish(*, dry_run: bool = False, log=print) -> int:
    from automations.bg_check_sync import email_source
    by_office = {OFFICE: latest_by_person(email_source.fetch_events(since_days=DAYS, verbose=False))}
    try:
        for office, events in results_inbox_events().items():
            if office != OFFICE:           # Raf: his own inbox is the full record
                by_office[office] = latest_by_person(events)
    except Exception as e:  # noqa: BLE001 -- Raf's still publishes
        log("bg status: results inbox not read (%s)" % type(e).__name__)
    now = dt.datetime.now().isoformat(timespec="minutes")
    total = 0
    for office, people in by_office.items():
        log("bg status: %s -- %d people with a Sterling result email in the last %d days"
            % (office, len(people), DAYS))
        total += len(people)
        if dry_run:
            for p in people[:20]:
                log("  %s %s  %s  (%s)" % (p["first"], p["last"], p["status"], p["date"]))
            continue
        write(office, people, now)
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish Sterling email BG statuses for the office admin extension.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    publish(dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
