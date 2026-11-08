"""LucyECO Social sign-up: the answers, checked, and where they're kept.

The office fills the form at lucyeco…/join-lucyeco-social (signup_app.py).
Answers land on the 'LucyECO Social Signups' tab of the relay workbook as
PENDING. Nothing is switched on from here: on the install call we run

    python -m automations.online_presence.setup add --office <key> --from-signup "<business name>"

which turns the row into the office's online-presence row (dry, like every
new office).

WHY THESE QUESTIONS (Megan 2026-11-08): the address, phone, website and
Google listing link are the TRUTH every audit checks the internet against
(consistency.py). The Google link also picks THE listing -- a name two
offices can share; a link can't be.

NEVER ASKS FOR A PASSWORD. Their Zoho and social logins stay with them.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Dict, List

TAB = "LucyECO Social Signups"
# Social links are part of the TRUTH too (Megan 2026-11-08: "the form should
# just ask for all their social links"): audits check their website links to
# THESE accounts, and a page they pick to post to must have its link.
SOCIAL_FIELDS = (("Instagram Link", "instagram.com", "Instagram"),
                 ("Facebook Link", "facebook.com", "Facebook"),
                 ("LinkedIn Link", "linkedin.com", "LinkedIn"),
                 ("X Link", ("x.com", "twitter.com"), "X"),
                 ("TikTok Link", "tiktok.com", "TikTok"),
                 ("YouTube Link", ("youtube.com", "youtu.be"), "YouTube"))
HEADER = ["Submitted At", "Status", "Owner", "Owner Email", "Business Name",
          "Address", "Phone", "Website", "Google Listing Link", "Indeed Link",
          "Glassdoor Link", "Pages", "Approvers", "Complaints Email", "Timezone",
          "Notes"] + [f for f, _, _ in SOCIAL_FIELDS]
PAGES = ("Instagram", "Facebook", "Google", "LinkedIn", "X")
_LOCAL = Path(__file__).resolve().parents[2] / "output" / "lucyeco_social_signups_local.json"
_CLIENT = None


def set_client(gc) -> None:
    global _CLIENT
    _CLIENT = gc


# ---- checking the answers --------------------------------------------------
_GOOGLE = re.compile(r"(google\.[a-z.]+/maps|maps\.google\.|maps\.app\.goo\.gl|goo\.gl/maps|"
                     r"g\.page|g\.co/kgs|share\.google|business\.google\.com)", re.I)


def problems(a: Dict) -> List[str]:
    """Plain-English reasons the form can't be sent yet ([] = good)."""
    out = []
    need = (("Owner", "your full name"), ("Business Name", "your business name"),
            ("Address", "your office address"), ("Phone", "your company phone"),
            ("Website", "your website"), ("Google Listing Link", "your Google listing link"),
            ("Complaints Email", "an email for customer concerns"),
            ("Approvers", "who approves posts"))
    for k, label in need:
        if not str(a.get(k) or "").strip():
            out.append(f"Add {label}.")
    if a.get("Phone") and len(re.sub(r"\D", "", a["Phone"])) not in (10, 11):
        out.append("The phone number should have 10 digits.")
    if a.get("Address") and not re.search(r"\b\d{5}\b", a["Address"]):
        out.append("Add the ZIP code to the address.")
    if a.get("Address") and not re.match(r"\s*\d", a["Address"]):
        out.append("The address should start with the street number.")
    if a.get("Website") and not re.search(r"\.[a-z]{2,}", a["Website"], re.I):
        out.append("The website doesn't look like a web address.")
    if a.get("Google Listing Link") and not _GOOGLE.search(a["Google Listing Link"]):
        out.append("The Google link should come from your listing's Share button "
                   "(it starts with maps.app.goo.gl or google.com/maps).")
    for k in ("Indeed Link", "Glassdoor Link"):
        v = str(a.get(k) or "").strip()
        site = k.split()[0].lower()
        if v and site not in v.lower():
            out.append(f"The {k.split()[0]} link should be an {k.split()[0]} page.")
    for k in ("Complaints Email", "Owner Email"):
        v = str(a.get(k) or "").strip()
        if v and not re.match(r"[^@\s]+@[^@\s]+\.[a-z]{2,}$", v, re.I):
            out.append(f"Check the {k.lower()}.")
    for field, hosts, name in SOCIAL_FIELDS:
        v = str(a.get(field) or "").strip()
        hosts = (hosts,) if isinstance(hosts, str) else hosts
        if v and not any(h in v.lower() for h in hosts):
            out.append(f"The {name} link should be a {name} page ({hosts[0]}/…).")
    for page in a.get("Pages") or []:
        if page == "Google":
            continue                       # the Google listing link covers it
        field = f"{page} Link"
        if not str(a.get(field) or "").strip():
            out.append(f"You picked {page} for posting: add your {page} link.")
    if not a.get("Pages"):
        out.append("Pick at least one page for Lucy to post to.")
    return out


def tidy(a: Dict) -> Dict:
    a = {k: (v.strip() if isinstance(v, str) else v) for k, v in a.items()}
    for k in ["Website"] + [f for f, _, _ in SOCIAL_FIELDS]:
        if a.get(k) and not str(a[k]).lower().startswith("http"):
            a[k] = "https://" + a[k]
    d = re.sub(r"\D", "", a.get("Phone") or "")[-10:]
    if len(d) == 10:
        a["Phone"] = f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return a


# ---- keeping them ------------------------------------------------------------
def _tab():
    from automations.icd_alerts import post as P
    if _CLIENT is not None:
        book = _CLIENT.open_by_key(P.RELAY_SPREADSHEET_ID)
    else:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        tab = book.worksheet(TAB)
    except Exception:
        tab = book.add_worksheet(title=TAB, rows=200, cols=len(HEADER))
        tab.append_row(HEADER)
    return tab


def submit(a: Dict) -> bool:
    """Save one sign-up. True = in the workbook; False = kept as a local draft."""
    a = dict(a, **{"Submitted At": dt.datetime.now().isoformat(timespec="seconds"),
                   "Status": "PENDING"})
    row = [", ".join(a[h]) if isinstance(a.get(h), (list, tuple)) else str(a.get(h) or "")
           for h in HEADER]
    try:
        if os.environ.get("LUCYECO_SOCIAL_LOCAL_ONLY"):
            raise RuntimeError("local only")     # testing: never the real workbook
        _tab().append_row(row, value_input_option="RAW")
        return True
    except Exception:
        rows = []
        try:
            rows = json.loads(_LOCAL.read_text())
        except Exception:
            pass
        rows.append(dict(zip(HEADER, row)))
        _LOCAL.parent.mkdir(parents=True, exist_ok=True)
        _LOCAL.write_text(json.dumps(rows, indent=2))
        return False


def find(business_name: str) -> Dict | None:
    """The newest sign-up for this business name (case-blind)."""
    want = business_name.strip().lower()
    rows = [r for r in _tab().get_all_records()
            if str(r.get("Business Name", "")).strip().lower() == want]
    return rows[-1] if rows else None
