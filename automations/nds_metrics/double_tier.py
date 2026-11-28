"""Sean Balderrama's "Double Tier Bonus - <date>" days, read off Carlos's inbox.

Carlos 2026-11-06: "Double tiers you can see off of my email and then you'll
know sales from that date are double tiers." Every eligible sale on such a
day counts twice toward the rep tier (line_revenue.tier_order_counts). The
mini's inbox manager already holds Carlos's Gmail app password; the same file
is pushed to Lucy 2 (push_cred_file), and Raf's inbox is the fallback on a
box that has his file. The search: sender sbalderrama@thesmartcircle.com, subject
"Double Tier Bonus  - 10/31" (the date in the subject IS the double day --
the 10/30 evening email says "tomorrow, 10/31", the 10/9 morning one says
"today, 10/9"). From 11/24 his subject reads "NDS - Double Tiers - 11/25" and
a reply adds days to it, "Re: NDS - Double Tiers - 11/25 & 11/27" -- every date
after the words is a double day (the old "Bonus"-only pattern missed both;
Carlos 11/28: "Wednesday and Friday were double tiers"). Known days are cached in output/nds_metrics/double_tier_days.json
and unioned with sow_rates.json's seed list, so an inbox outage never
forgets a day.

    lucy rerun nds_metrics_probe --double-days      # what the inbox says
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import email
import email.utils
import imaplib
import json
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set

from automations.fiber_owners_distro.roster import IMAP_HOST, _decode
from automations.nds_metrics.run import OUT_DIR

# Carlos's own inbox (he is on Smart Circle's NDS distribution); the app
# password travels with `push_cred_file gmail-app-password-carloshidalgo349
# "Lucy 2"` from the mini. Raf's file is the fallback on a box that has it.
_CFG = Path.home() / ".config" / "recruiting-report"
INBOXES = (("carloshidalgo349@gmail.com", _CFG / "gmail-app-password-carloshidalgo349"),
           ("raffi127@gmail.com", _CFG / "gmail-app-password-raffi127"))
SENDER = "sbalderrama@thesmartcircle.com"
SINCE = dt.date(2026, 10, 1)
CACHE = OUT_DIR / "double_tier_days.json"
# "Double Tier Bonus  - 10/31" (10/8-11/14), "NDS - Double Tiers - 11/25" and
# "Re: NDS - Double Tiers - 11/25 & 11/27" (11/24 on): the words, then dates.
_HEAD = re.compile(r"double\s+tiers?(?:\s+bonus)?", re.I)
_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?(?!\d)")


def parse_subject_all(subject: str, sent: Optional[dt.date]) -> List[dt.date]:
    """'Re: NDS - Double Tiers - 11/25 & 11/27' (+ the email's send date for
    the year) -> [2026-11-25, 2026-11-27]. [] when the subject is not a
    double-tier one or carries no date."""
    m = _HEAD.search(subject or "")
    if not m:
        return []
    out: List[dt.date] = []
    for g in _DATE.finditer(subject[m.end():]):
        mo, d = int(g.group(1)), int(g.group(2))
        if g.group(3):
            y = int(g.group(3))
            y = y + 2000 if y < 100 else y
        else:
            y = (sent or dt.date.today()).year
            if sent and mo < sent.month - 6:      # a December email about January
                y += 1
        try:
            day = dt.date(y, mo, d)
        except ValueError:
            continue
        if day not in out:
            out.append(day)
    return out


def parse_subject(subject: str, sent: Optional[dt.date]) -> Optional[dt.date]:
    """The subject's first double day (parse_subject_all); None if it has none."""
    found = parse_subject_all(subject, sent)
    return found[0] if found else None


def _inbox():
    for account, path in INBOXES:
        if path.exists():
            return account, path.read_text(encoding="utf-8-sig").strip().replace(" ", "")
    raise RuntimeError("no Gmail app password on this box for any of: "
                       + ", ".join(a for a, _ in INBOXES))


def fetch(log=print) -> Set[str]:
    """The inbox, live: every double-tier day Sean has announced since SINCE."""
    account, password = _inbox()
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(account, password)
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        # EVERY email from Sean, subjects filtered HERE: Gmail's IMAP SUBJECT
        # search matches whole words, so SUBJECT "Double Tier" never returned
        # "NDS - Double Tiers - 11/25" (11/28: 6 of his 8 double-tier emails).
        _typ, data = M.search(None, '(FROM "%s" SINCE "%s")'
                              % (SENDER, SINCE.strftime("%d-%b-%Y")))
        ids = (data[0] or b"").split()
        out: Set[str] = set()
        undated, hits = [], 0
        for i in range(0, len(ids), 100):
            _typ, md = M.fetch(b",".join(ids[i:i + 100]),
                               "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
            for part in md or []:
                if not isinstance(part, tuple):
                    continue
                msg = email.message_from_bytes(part[1])
                subj = _decode(msg.get("Subject", ""))
                if not _HEAD.search(subj or ""):
                    continue
                hits += 1
                try:
                    sent = email.utils.parsedate_to_datetime(msg.get("Date")).date()
                except Exception:  # noqa: BLE001
                    sent = None
                found = parse_subject_all(subj, sent)
                out.update(d.isoformat() for d in found)
                if not found:
                    undated.append(subj)
        log("[nds] double tier: %d double-tier email(s) of %d from Sean in %s since %s -> %s"
            % (hits, len(ids), account, SINCE, ", ".join(sorted(out)) or "none"))
        if undated:     # a subject that matched the search but gave no day: a new format?
            log("[nds] double tier: no day read from %d subject(s): %s"
                % (len(undated), " | ".join(s[:70] for s in undated[:5])))
        return out
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def days(seed: Iterable[str] = (), log=print) -> Set[str]:
    """seed (sow_rates) + the cache + whatever the inbox says now. An inbox
    error keeps what is known and says so."""
    known: Set[str] = set(seed)
    try:
        known |= set(json.loads(CACHE.read_text()).get("days", []))
    except Exception:  # noqa: BLE001
        pass
    try:
        known |= fetch(log=log)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"days": sorted(known),
                                     "checked": dt.datetime.now().isoformat(timespec="seconds")}))
    except Exception as e:  # noqa: BLE001
        log("[nds] double tier: inbox unreadable (%s: %s) -- using the %d known day(s)"
            % (type(e).__name__, str(e)[:80], len(known)))
    return known


if __name__ == "__main__":
    print(sorted(days()))
