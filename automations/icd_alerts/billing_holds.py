"""Indeed billing holds, from the office computer's checks to the live-ads
numbers and to Slack (Lucy 1's poster tick).

WHY. The 5am/1pm Octo run on an office computer reads every Indeed account's
All Jobs page for a billing alert and files the result as a quiet relay row
(probe-octo-lookup: billing = {account: ok | PROBLEM: ...}, since 2026-11-19
billing_mail = {account: {declined, paid, live}} read off the account's own
Gmail). Carlos's live-ads sheet prices every ad as Daily Budget x Days Live,
so a hold has to come off that count -- and he wants to hear when the ads
come back: "it needs to somehow communicate when the ads go back live"
(2026-11-19).

WHAT THIS DOES, every poster tick, cheaply (one state read; a Sheets read only
when a check row is newer than the last one handled):
  * ok -> PROBLEM: a hold opens. Start = the account's newest 'Payment
    declined' mail if the check carried one, else the check time (marked
    estimated). A row goes on the dashboard's 'Billing Holds' tab unless the
    account already has an open row there (a person may have typed one).
    Slack already carries the alert itself (the loud octo-billing fault).
  * PROBLEM -> ok: the hold closes. End = the newest 'We received your
    payment' mail after the start if the check carried one, else the check
    time (estimated). The row's Hold Until is filled, and the office's group
    DM gets one line: ads back live, since when, how long.
    UNLESS no ad is open on the account (newest week block of 'carlos' live
    ads'): Indeed's alert sits on a JOB, so closing the job clears the page
    without any payment (Carlos closed every held account's ads 11/25). No
    payment mail -> the hold ends at the ads' close time, noted "not a
    payment", and nobody is told the ads are live. A payment mail -> the DM
    says the payment went through and that no ads are open.
  * walled / in use / could not start: no information; nothing moves.

State: ~/.config/recruiting-report/billing_holds_state.json
       {"handled": ["<date> <at>", ...], "open": {"<office>|<account>": {...}}}

    python -m automations.icd_alerts.billing_holds            # preview today
    python -m automations.icd_alerts.billing_holds --send     # what the poster does
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

STAGE = "probe-octo-lookup"
DASHBOARD_ID = "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA"
HOLDS_TAB = "Billing Holds"
HOLDS_HEAD = ["Indeed Account", "Hold From", "Hold Until", "Source / note"]
# The tally names accounts by their Octo profile title; the live-ads tab's
# column D spells a few differently. Unlisted = same spelling.
LIVE_ADS_NAME = {"New Ascendra": "Ascendra", "VividReach - Active": "VividReach"}
OFFICE_KEY = {"11580": "carlos"}          # office id on the tally -> relay office key (the DM)
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "billing_holds_state.json"
MAX_MAIL_GAP_DAYS = 4                      # a decline older than this is not this hold's
LIVE_ADS_TAB = "carlos' live ads"          # A Week Ending | B Date Posted | C Closed Date | D Indeed Account


def ads_on_accounts(dash) -> Optional[Dict[str, Dict]]:
    """{account (lower case): {"open": n, "closed": newest close datetime or None}}
    off the NEWEST week block of the live-ads tab, or None when the tab can't
    be read (the caller then behaves as before)."""
    try:
        vals = dash.worksheet(LIVE_ADS_TAB).get_all_values()[1:]
    except Exception:  # noqa: BLE001
        return None
    rows = []
    for r in vals:
        r = list(r) + [""] * (4 - len(r))
        try:
            we = dt.datetime.strptime(r[0].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if r[3].strip():
            rows.append((we, r[2].strip(), r[3].strip().lower()))
    if not rows:
        return None
    newest = max(we for we, _c, _a in rows)
    out: Dict[str, Dict] = {}
    for we, closed, acct in rows:
        if we != newest:
            continue
        rec = out.setdefault(acct, {"open": 0, "closed": None})
        if not closed:
            rec["open"] += 1
        else:
            d = _parse(closed)
            if d and (rec["closed"] is None or d > rec["closed"]):
                rec["closed"] = d
    return out


def _load_state() -> Dict:
    try:
        d = json.loads(STATE_PATH.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(st: Dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=1))


def _parse(ts: Optional[str]) -> Optional[dt.datetime]:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S"):
        try:
            return dt.datetime.strptime(str(ts or "").strip(), fmt)
        except ValueError:
            continue
    return None


def _sheet_ts(d: dt.datetime) -> str:
    return d.strftime("%m/%d/%Y %H:%M")


def _hm12(d: dt.datetime) -> str:
    return d.strftime("%a %m/%d %I:%M %p").replace(" 0", " ")


# --- the relay rows --------------------------------------------------------
def _tolerant_json(detail: str) -> Dict:
    """The row's JSON, or what is still whole in a cut one. The relay cuts a
    Detail at 6000 characters (relay._scrub); on 2026-11-25 eight accounts on
    hold made the tally longer than that, json.loads failed, and no hold
    opened and nobody was told. Each top-level value is decoded from its own
    key (the type that follows tells the key apart from a same-named one
    inside `ran`); a dict cut in the middle keeps its whole entries."""
    try:
        d = json.loads(detail or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        pass
    dec = json.JSONDecoder()
    out: Dict = {"cut": True}
    typed = {"office": '"', "date": '"', "at": '"', "ran": "{", "accounts": "{", "billing": "{", "billing_mail": "{"}
    for key, t in typed.items():
        m = re.search(r'"%s":\s*(?=[%s])' % (key, re.escape(t)), detail)
        if not m:
            continue
        try:
            out[key], _ = dec.raw_decode(detail, m.end())
        except ValueError:
            part: Dict = {}
            for k, v in re.findall(r'"([^"]+)":\s*("(?:[^"\\]|\\.)*"|\{[^{}]*\})', detail[m.end():]):
                try:
                    part[k] = json.loads(v)
                except ValueError:
                    pass
            out[key] = part
    return out


def octo_rows(book, day: dt.date) -> List[Dict]:
    """Every probe-octo-lookup row of the day, oldest first: [{office, at,
    key, body}] where key = '<date> <at>' identifies the run."""
    from automations.icd_alerts import post as P
    try:
        rows = book.worksheet(P.FAULTS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in rows[1:]:
        if len(r) <= P.F_DETAIL or (r[P.F_STAGE] or "").strip() != STAGE:
            continue
        if P._day_key(r[P.F_DAY]) != day.isoformat():
            continue
        body = _tolerant_json(r[P.F_DETAIL])
        if not isinstance(body, dict) or not body.get("billing"):
            continue
        at = str(body.get("at") or "")
        out.append({"office": str(body.get("office") or r[P.F_OFFICE]).strip(), "at": at,
                    "key": "%s %s" % (day.isoformat(), at), "body": body})
    return sorted(out, key=lambda x: x["at"])


# --- the holds tab ----------------------------------------------------------
def _holds_ws(dash):
    try:
        return dash.worksheet(HOLDS_TAB)
    except Exception:  # noqa: BLE001
        ws = dash.add_worksheet(title=HOLDS_TAB, rows=60, cols=4)
        ws.update("A1", [HOLDS_HEAD])
        return ws


def _open_row(ws, name: str) -> Optional[int]:
    """The row number of the account's open hold (blank Hold Until), or None."""
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        r = r + [""] * (4 - len(r))
        if r[0].strip().lower() == name.lower() and r[1].strip() and not r[2].strip():
            return i
    return None


def _last_closed(ws, name: str) -> Optional[dt.datetime]:
    """When the account's most recent CLOSED hold ended, or None."""
    ends = []
    for r in ws.get_all_values()[1:]:
        r = r + [""] * (4 - len(r))
        if r[0].strip().lower() == name.lower() and r[2].strip():
            d = _parse(r[2])
            if d:
                ends.append(d)
    return max(ends) if ends else None


def open_hold(ws, name: str, start: dt.datetime, note: str) -> int:
    """Append a hold row unless one is open. A new episode never starts
    before the previous one ended -- two rows overlapping would count the
    same hours twice in Days Down (Ascendra, 11/21-11/25)."""
    row = _open_row(ws, name)
    if row:
        return row
    prev = _last_closed(ws, name)
    if prev and start < prev:
        start = prev
        note = note + " | start moved to the previous hold's end"
    ws.append_row([name, _sheet_ts(start), "", note], value_input_option="USER_ENTERED")
    return _open_row(ws, name) or 0


def close_hold(ws, name: str, end: dt.datetime, note: str) -> Optional[int]:
    row = _open_row(ws, name)
    if not row:
        return None
    old = (ws.get("D%d" % row) or [[""]])[0][0] if True else ""
    ws.update("C%d:D%d" % (row, row), [[_sheet_ts(end), (old + " | " if old else "") + note]],
              value_input_option="USER_ENTERED")
    return row


# --- one tick -----------------------------------------------------------------
def run(day: Optional[dt.date] = None, *, send: bool = False, book=None, dash=None,
        dm=None, log=print) -> List[Dict]:
    """Handle every check row of the day not handled yet. Returns what it did
    (or would do without --send)."""
    day = day or dt.date.today()
    st = _load_state()
    handled = set(st.get("handled") or [])
    opens: Dict = st.setdefault("open", {})
    if book is None:
        from automations.icd_alerts import post as P
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(P.RELAY_SPREADSHEET_ID)
    all_rows = octo_rows(book, day)
    rows = [r for r in all_rows if r["key"] not in handled]
    log("BILLING-HOLDS: %d check row(s) today (%s), %d not handled yet; %d hold(s) open"
        % (len(all_rows), ", ".join(r["at"] for r in all_rows) or "none", len(rows), len(opens)))
    if not rows:
        return []
    ws = None
    ads: Optional[Dict] = None
    ads_read = False
    did: List[Dict] = []
    for r in rows:
        office, body = r["office"], r["body"]
        when = _parse("%s %s" % (day.isoformat(), r["at"])) or dt.datetime.combine(day, dt.time(12, 0))
        mail_all = body.get("billing_mail") or {}
        for acct, status in (body.get("billing") or {}).items():
            status = str(status or "")
            key = "%s|%s" % (office, acct)
            name = LIVE_ADS_NAME.get(acct, acct)
            mail = mail_all.get(acct) or {}
            cur = opens.get(key)
            last_ok = _parse((st.get("last_ok") or {}).get(key))
            if status.startswith("PROBLEM"):
                if cur:
                    continue                                   # still on hold, nothing new
                start, src = when, "billing check %s (estimated)" % _hm12(when)
                # Indeed re-sends 'Payment declined' every afternoon while an
                # account stays unpaid (Titanium 11/22 and 11/24, Peak 11/23 and
                # 11/25), so the FIRST one after the last payment dates the hold
                # (declined_first, office side since 2026.11.25.20); the newest
                # is the fallback for older tallies.
                dec = _parse(mail.get("declined_first") or mail.get("declined"))
                # A decline mail dates THIS hold only if it came after the
                # account last read clean; an older one belongs to the
                # previous episode (Ascendra 11/21: Indeed sent no new mail).
                if (dec and 0 <= (when - dec).days <= MAX_MAIL_GAP_DAYS
                        and (last_ok is None or dec > last_ok)):
                    start, src = dec, "Indeed 'Payment declined' mail %s" % _hm12(dec)
                elif last_ok and last_ok < when:
                    # Indeed's declines land in the evening; the first check that
                    # sees one is the next 5am. Halfway between the last clean
                    # check and this one is a better guess than either end.
                    start = last_ok + (when - last_ok) / 2
                    src = ("between the last clean check %s and the first flagged one %s (estimated)"
                           % (_hm12(last_ok), _hm12(when)))
                act = {"office": office, "account": acct, "event": "hold", "start": start.isoformat(timespec="minutes"), "source": src}
                if send:
                    if dash is None:
                        from automations.recruiting_report.fill import open_by_key
                        dash = open_by_key(DASHBOARD_ID)
                    ws = ws or _holds_ws(dash)
                    act["row"] = open_hold(ws, name, start, "opened by the billing check: " + src)
                opens[key] = {"since": start.isoformat(timespec="minutes"), "source": src, "name": name}
                log("HOLD   %-28s from %s (%s)" % (acct, _hm12(start), src))
                did.append(act)
            elif status == "ok":
                st.setdefault("last_ok", {})[key] = when.isoformat(timespec="minutes")
                if not cur:
                    continue                                   # clean and was clean
                since = _parse(cur.get("since")) or when
                end, src = when, "billing check %s (estimated)" % _hm12(when)
                paid = _parse(mail.get("paid"))
                paid_ok = bool(paid and paid > since and paid <= when + dt.timedelta(hours=1))
                if paid_ok:
                    end, src = paid, "Indeed 'We received your payment' mail %s" % _hm12(paid)
                if not ads_read:
                    ads_read = True
                    try:
                        if dash is None:
                            from automations.recruiting_report.fill import open_by_key
                            dash = open_by_key(DASHBOARD_ID)
                        ads = ads_on_accounts(dash)
                    except Exception as e:  # noqa: BLE001 -- unreadable = behave as before
                        log("live-ads tab not read (%s); treating a clean page as back live" % type(e).__name__)
                        ads = None
                on = ads.get(name.lower()) if ads is not None else None
                no_ads = ads is not None and (on is None or on["open"] == 0)
                event, note, text = "live", "closed by the billing check: " + src, None
                if no_ads and not paid_ok:
                    closed = on["closed"] if on else None
                    if closed and since <= closed <= when:
                        end, src = closed, "ads closed %s, not a payment" % _hm12(closed)
                    else:
                        end, src = when, "no ad open at the %s check, not a payment (estimated)" % _hm12(when)
                    event = "closed-no-ads"
                    note = ("closed by the billing check: %s -- the page reads clean because no job is open; "
                            "billing NOT confirmed paid" % src)
                elif no_ads:
                    event = "paid-no-ads"
                    text = (":white_check_mark: *%s* — Indeed payment went through (%s). No ads are open on it right now."
                            % (acct, _hm12(paid)))
                hours = max(0.0, (end - since).total_seconds() / 3600)
                act = {"office": office, "account": acct, "event": event, "since": cur.get("since"),
                       "end": end.isoformat(timespec="minutes"), "source": src, "hours": round(hours, 1)}
                if event == "live":
                    text = (":white_check_mark: *%s* — Indeed ads are back live (seen at the %s check). "
                            "On hold since %s, about %s. The live-ads sheet's Days Down has it."
                            % (acct, _hm12(when), _hm12(since),
                               ("%.0f hours" % hours) if hours < 48 else ("%.1f days" % (hours / 24))))
                if send:
                    if dash is None:
                        from automations.recruiting_report.fill import open_by_key
                        dash = open_by_key(DASHBOARD_ID)
                    ws = ws or _holds_ws(dash)
                    act["row"] = close_hold(ws, name, end, note)
                    if text:
                        try:
                            (dm or _dm_office)(OFFICE_KEY.get(office, office), text)
                            act["dm"] = True
                        except Exception as e:  # noqa: BLE001 -- the telling, never the sheet
                            log("could not DM the back-live note: %s" % type(e).__name__)
                opens.pop(key, None)
                log("%-6s %-28s hold ended %s (%s); was down since %s"
                    % ({"live": "LIVE", "paid-no-ads": "PAID", "closed-no-ads": "NOADS"}[event], acct,
                       _hm12(end), src, _hm12(since)))
                did.append(act)
            # walled / in use / could not start: no information, nothing moves
        handled.add(r["key"])
    if send:
        st["handled"] = sorted(handled)[-200:]
        _save_state(st)
    return did


def _dm_office(office_key: str, text: str) -> None:
    from automations.icd_alerts import post as P
    P.dm_office_people(office_key, text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Indeed billing holds -> Billing Holds tab + Slack")
    ap.add_argument("--send", action="store_true", help="write the tab, send the DM, remember")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--state", action="store_true", help="print the state file and stop")
    ap.add_argument("--reset", action="store_true", help="forget handled rows and open holds (the tab is untouched)")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else dt.date.today()
    if args.state:
        print(json.dumps(_load_state(), indent=1)[:3000]); return 0
    if args.reset:
        _save_state({}); print("state reset")
    did = run(day, send=args.send)
    print("%d event(s)%s" % (len(did), "" if args.send else " (preview, nothing written)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
