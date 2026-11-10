"""Which offices Lucy runs online presence for, and everything per office.

ONE ROW PER OFFICE in offices.json, keyed by the office's ECO key (the same key
as automations/icd_alerts/offices.py), so "kash" means Kash everywhere.

Each office posts to ITS OWN pages and ITS OWN Google listing (Megan,
2026-11-08). One Slack room per office holds both halves: photos for social
posts AND the review replies waiting on an approver.

    photos   -> the office's room -> Lucy edits + captions -> approver ✅ ->
                a job on the relay -> the office's OWN computer posts it from
                the ICD's OWN Zoho (they make it, pay for it, connect their
                pages to it; Megan 2026-11-08) -> their socials
    reviews  -> the office's Google listing (we are a Manager on it) ->
                4-5★ auto-reply, under 4★ waits in the room for ✅ / ❌

ALPHALETE IS NOT A ROW. Its own run (brand_audit noon + social scanner) keeps
the two rooms and the settings it has always had; `alphalete()` rebuilds that
exact setup from brand_audit/config.py, so the shared code takes one shape and
Alphalete's behaviour does not move.

THE MODE IS PER OFFICE: "dry" (the default) reads everything and posts
nothing, anywhere. An office goes "live" only by editing its row -- never by a
flag somebody passes on a command line.

    python -m automations.online_presence.setup add ...     # new office row
    python -m automations.online_presence.setup check kash  # the Zoom checklist
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Optional, Tuple

OFFICES_FILE = Path(__file__).resolve().parent / "offices.json"

# Per-office working files live outside the repo, one folder per office, so an
# office can never read or overwrite Alphalete's (or another office's) state.
STATE_ROOT = Path.home() / ".config" / "brand-audit" / "offices"

# When an office names nobody, these two can still approve (Megan 2026-09-13:
# "Eve or I can complete the set up"). Never "anyone in the room": a rep
# reacting ✅ on their own photo must not publish it.
FALLBACK_APPROVERS: Tuple[str, ...] = ("U04G5HJBGFN",   # Megan
                                       "U088E2KJEV8")   # Eve

# Times we rotate across until an office has its own posting history. Megan's
# rule: nothing posts after 7pm, so the latest window is 6pm.
DEFAULT_POST_HOURS: Tuple[int, ...] = (9, 12, 15, 18)


@dataclass(frozen=True)
class Presence:
    """Everything one run needs to know about one office."""
    key: str                       # ECO key, e.g. "kash"
    business_name: str             # as it reads on Google; signs every reply
    slack_channel: str             # the office's ONE room (photos + reviews)
    approvers: Tuple[str, ...] = ()           # Slack ids whose ✅/❌/💀 count
    contact_email: str = ""        # where a complaint is invited to write
    gbp_location: str = ""         # accounts/<a>/locations/<l>; "" = not linked yet
    timezone: str = "America/Chicago"
    mode: str = "dry"              # "dry" | "live"
    reviews: bool = True           # run review replies for this office
    social: bool = True            # run photo posting for this office
    # THE TRUTH FROM SIGN-UP (Megan 2026-11-08). What the office says its
    # address, phone, website and Google listing ARE -- every audit checks
    # Google, their website, Indeed and Glassdoor against these
    # (consistency.py), and the Google link is what picks THE listing, not
    # a name two offices could share.
    address: str = ""
    phone: str = ""
    website: str = ""
    google_link: str = ""
    indeed_url: str = ""           # optional: their Indeed company page
    glassdoor_url: str = ""        # optional
    # Their social accounts, from sign-up. The website must link to THESE
    # (an old or look-alike account linked from their site gets flagged).
    instagram_url: str = ""
    facebook_url: str = ""
    linkedin_url: str = ""
    x_url: str = ""
    tiktok_url: str = ""
    youtube_url: str = ""

    @property
    def social_links(self) -> Dict[str, str]:
        return {k: v for k, v in (("instagram", self.instagram_url),
                                  ("facebook", self.facebook_url),
                                  ("linkedin", self.linkedin_url),
                                  ("x", self.x_url), ("tiktok", self.tiktok_url),
                                  ("youtube", self.youtube_url)) if v}
    # WHICH PAGES the ICD chose on sign-up (zoho_draft.PAGES: instagram,
    # facebook, google, linkedin, x). Lucy posts ONLY to these, and DMs the
    # owner only when one of THESE drops out of their Zoho -- a page they
    # never picked being disconnected is not news to them.
    pages: Tuple[str, ...] = ()
    owner_slack_id: str = ""       # who gets "your Instagram disconnected"
    # "eco" = the office's own computer posts from the ICD's own Zoho (the
    # default for every office). "lucy" = a Zoho login kept on a Lucy.
    post_via: str = "eco"
    # Free Zoho may not schedule. False = Lucy publishes ("Post Now") herself
    # inside the posting window instead of handing Zoho a time.
    zoho_schedules: bool = False
    post_hours: Tuple[int, ...] = DEFAULT_POST_HOURS
    auto_reply_min_stars: int = 4
    auto_reply_daily_cap: int = 10
    # Review cards waiting on a ✅ (1-3★, or anything Lucy can't auto-post)
    # added per day. A new office's backlog of old bad reviews comes in a few a
    # day instead of all at once (Megan 2026-11-10: "we want every review they
    # have to have a response"). 0 = no limit (Alphalete, unchanged).
    review_draft_daily_cap: int = 5
    notes: str = ""
    # --- set only by alphalete(); offices never write these ---
    review_channel: str = ""       # "" = same room as photos
    state_dir: str = ""            # "" = STATE_ROOT/<key>
    zoho_profile_dir: str = ""     # "" = the office's own profile folder
    learned_style_path: str = ""
    scrape_best_time: bool = False  # Alphalete reads its own Zoho analytics

    # -- derived ---------------------------------------------------------
    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def reviews_channel(self) -> str:
        return self.review_channel or self.slack_channel

    @property
    def counted_approvers(self) -> Tuple[str, ...]:
        return tuple(self.approvers) or FALLBACK_APPROVERS

    @property
    def folder(self) -> Path:
        return Path(self.state_dir) if self.state_dir else STATE_ROOT / self.key

    def path(self, name: str) -> Path:
        return self.folder / name

    @property
    def zoho_profile(self) -> Path:
        if self.zoho_profile_dir:
            return Path(self.zoho_profile_dir)
        from automations.shared.tableau_patchright import PROFILE_DIR
        return PROFILE_DIR.parent / f".browser_profile_zoho_{self.key}"

    @property
    def style_file(self) -> Path:
        return (Path(self.learned_style_path) if self.learned_style_path
                else self.path("learned_style.json"))

    def problems(self) -> List[str]:
        """What is missing for this office to run at all (plain English)."""
        out = []
        if not self.business_name.strip():
            out.append("no business name")
        if not self.slack_channel.strip():
            out.append("no Slack channel")
        for field, label in (("address", "office address"), ("phone", "company phone"),
                             ("website", "company website"),
                             ("google_link", "Google listing link")):
            if not str(getattr(self, field) or "").strip():
                out.append(f"no {label}")
        if self.mode not in ("dry", "live"):
            out.append(f"mode must be 'dry' or 'live', not {self.mode!r}")
        if self.reviews and not self.contact_email.strip():
            out.append("no contact email for review complaints")
        if any(h < 8 or h > 18 for h in self.post_hours):
            out.append("post hours must be between 8am and 6pm")
        if self.post_via not in ("eco", "lucy"):
            out.append(f"post_via must be 'eco' or 'lucy', not {self.post_via!r}")
        if self.social:
            from automations.brand_audit.zoho_draft import PAGES
            if not self.pages:
                out.append("no pages chosen to post to")
            bad = [x for x in self.pages if x not in PAGES]
            if bad:
                out.append(f"unknown page(s) {bad} (pick from {', '.join(PAGES)})")
            if not self.owner_slack_id:
                out.append("no owner Slack id (for 'your page disconnected' DMs)")
            for page in self.pages:
                if page != "google" and page not in self.social_links:
                    out.append(f"posts to {page} but has no {page} link")
        return out


def alphalete() -> Presence:
    """Alphalete's existing setup, exactly as brand_audit/config.py has it."""
    from automations.brand_audit import config as C
    ba = Path.home() / ".config" / "brand-audit"
    from automations.brand_audit import zoho_draft
    return Presence(
        key="alphalete",
        business_name="Alphalete Marketing",
        slack_channel=C.SOCIAL_INBOX_CHANNEL_ID,
        review_channel=C.ALERT_SLACK_CHANNEL_ID,
        approvers=tuple(C.SOCIAL_APPROVERS),
        contact_email=C.REVIEW_REPLY_CONTACT,
        gbp_location=C.GBP_LOCATION_PATH or "",
        mode="live",
        post_via="lucy",
        address="5217 Tennyson Pkwy Suite 100, Plano, TX 75024",
        phone="(469) 242-0625",
        website="https://alphaletemarketing.com",
        google_link="https://maps.google.com/maps?cid=7671689793908717645",
        indeed_url="https://www.indeed.com/cmp/Alphalete-Marketing",
        glassdoor_url="https://www.glassdoor.com/Overview/Working-at-Alphalete-Marketing-EI_IE1528823.11,30.htm",
        instagram_url="https://www.instagram.com/alphaletemarketing/",
        facebook_url="https://www.facebook.com/alphaletemarketing",
        linkedin_url="https://www.linkedin.com/company/15255695",
        zoho_schedules=True,
        auto_reply_min_stars=C.AUTO_POST_MIN_STARS,
        auto_reply_daily_cap=C.AUTO_POST_DAILY_CAP,
        review_draft_daily_cap=0,
        state_dir=str(ba),
        zoho_profile_dir=str(zoho_draft.ZOHO_PROFILE_DIR),
        learned_style_path=str(ba / "learned_style.json"),
        scrape_best_time=True,
    )


# ---- the rows -------------------------------------------------------------
_FIELDS = {f.name for f in fields(Presence)}
_TUPLES = ("approvers", "post_hours", "pages")
_ALPHALETE_ONLY = ("review_channel", "state_dir", "zoho_profile_dir",
                   "learned_style_path", "scrape_best_time")


def _from_row(row: Dict) -> Presence:
    unknown = set(row) - _FIELDS
    if unknown:
        raise ValueError(f"office {row.get('key')!r}: unknown field(s) "
                         f"{sorted(unknown)} in offices.json")
    for k in _ALPHALETE_ONLY:
        if row.get(k):
            raise ValueError(f"office {row.get('key')!r}: {k} is set by Lucy, "
                             "not in offices.json")
    vals = dict(row)
    for k in _TUPLES:
        if k in vals:
            vals[k] = tuple(vals[k])
    return Presence(**vals)


def _to_row(p: Presence) -> Dict:
    row = asdict(p)
    for k in _ALPHALETE_ONLY:
        row.pop(k, None)
    for k in _TUPLES:
        row[k] = list(row[k])
    return row


def load(path: Path = OFFICES_FILE) -> Dict[str, Presence]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    out = {}
    for row in rows:
        p = _from_row(row)
        if p.key in out or p.key == "alphalete":
            raise ValueError(f"office key {p.key!r} is used twice")
        out[p.key] = p
    return out


def get(key: str, path: Path = OFFICES_FILE) -> Optional[Presence]:
    key = (key or "").strip().lower()
    if key == "alphalete":
        return alphalete()
    return load(path).get(key)


def save(p: Presence, path: Path = OFFICES_FILE) -> None:
    """Add or replace one office's row. Other rows are left exactly as they are."""
    if p.key == "alphalete":
        raise ValueError("Alphalete's setup lives in brand_audit/config.py")
    rows = []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    rows = [r for r in rows if r.get("key") != p.key] + [_to_row(p)]
    rows.sort(key=lambda r: r["key"])
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
