"""The shape of ONE onboarded office, plus the two derivations that make the
form drive real wiring: machine (Lucy 1 / Lucy 2) and report family.

Nothing here talks to the network — this is pure data + rules, so it unit-tests
and both the form (app.py) and the apply CLI (apply.py) share one source of
truth for "what an office needs" and "which machine runs it."

WHY MACHINE = VIEW OWNER
  Saved Tableau views render as whoever is logged in on that machine. Lucy 1 is
  logged in as Raf, Lucy 2 as Carlos. A Raf-owned saved view only renders Raf's
  scope, so it MUST run on Lucy 1; a Carlos-owned view MUST run on Lucy 2, or the
  report captures the wrong office's data. So every per-office Tableau view the
  office enrolls carries a `view_owner` (Raf|Carlos), and the office's machine is
  derived from them: any Carlos-owned view -> Lucy 2, else Lucy 1. A single
  office that mixes Raf- and Carlos-owned views is a hard error (it can't run on
  both machines at once) — the form + apply both refuse it.

The two report families map straight onto the two machines/registries:
  • D2D  -> office_metrics.runner  (Raf   / Lucy 1) — the bundled 12 daily metrics
  • B2B  -> b2b_metrics.runner     (Carlos / Lucy 2) — Carlos's B2B thread
Each bundles its metrics into ONE office thread and is data-driven from its own
OFFICES registry, so a new office is one config row + one schedule entry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

# --- The reports Megan can enroll an office into. -------------------------
# Each is a metric the bundled runner already posts (office_metrics runs all of
# these for a D2D office; b2b_metrics for a B2B office). Most slice a SHARED
# all-office view and need NO per-office view URL — the runner filters by owner
# in Python (see office_metrics/offices.py flags). A report is listed with
# needs_view=True only when it may require a per-office (non-shared) saved view;
# for those the form reveals a view-URL field + a Raf/Carlos owner toggle, and
# THAT owner drives the machine. When a report uses the shared view, leave the
# URL blank and the office inherits its family's default owner.
@dataclass(frozen=True)
class ReportKind:
    key: str            # stable slug, matches the runner's --only metric slug
    label: str          # what Megan sees on the checkbox
    family: str         # "d2d" | "b2b"
    needs_view: bool    # does this report ever need a per-office saved view?
    default_on: bool    # pre-checked when Megan picks this family


REPORTS: List[ReportKind] = [
    # D2D bundle (office_metrics.runner). All shared-view / owner-sliced today, so
    # needs_view=False — a plain D2D office is pure config. needs_view stays a
    # knob for the rare office that can't use a shared view.
    ReportKind("knocks",         "🚪 Telemapper Knocks",           "d2d", False, True),
    ReportKind("order_log",      "📋 Order Log",                   "d2d", False, True),
    ReportKind("sales_6plus",    "📅 Sales Scheduled 6+ Days Out", "d2d", False, True),
    ReportKind("cancels",        "🚫 Canceled Orders",             "d2d", False, True),
    ReportKind("ongoing_cancel", "🔁 Ongoing Cancel",              "d2d", True,  True),
    ReportKind("disconnects",    "❎ Disconnected New Internets",   "d2d", False, True),
    ReportKind("churn_ni",       "🌐 New Internet Churn",          "d2d", True,  True),
    ReportKind("churn_wl",       "📊 Wireless Churn",              "d2d", True,  True),
    ReportKind("activations",    "🆕 Rep Activations",             "d2d", False, True),
    ReportKind("abp",            "💳 New Internet ABP %",          "d2d", True,  True),
    ReportKind("tableau_shot",   "📸 Tableau Metrics screenshot",  "d2d", False, True),
    # B2B bundle (b2b_metrics.runner) — Carlos's team views, owner-sliced.
    ReportKind("b2b_sales",      "B2B Sales Metrics",              "b2b", True,  True),
    ReportKind("b2b_activation", "B2B Activation Rate",            "b2b", True,  True),
    ReportKind("b2b_churn",      "B2B Churn (3 product views)",    "b2b", True,  True),
    ReportKind("b2b_order_log",  "B2B Order Log",                  "b2b", False, True),
]

REPORTS_BY_KEY: Dict[str, ReportKind] = {r.key: r for r in REPORTS}

# Which machine a saved Tableau view renders on. Expressed as the machine
# directly (Lucy 1 / Lucy 2) rather than the person logged into it — Lucy 1 is
# the D2D login, Lucy 2 the B2B login. A view that renders on the other machine
# than the campaign's default flips the office to that machine.
MACHINES = ("Lucy 1", "Lucy 2")
FAMILY_DEFAULT_MACHINE = {"d2d": "Lucy 1", "b2b": "Lucy 2"}

# Color thresholds are UNIVERSAL (the house standard), not set per office — the
# form doesn't expose them; every office stores the same standard.
DEFAULT_THRESHOLDS = {"green": 85, "yellow": 75}

# The workbook Megan copies every tab FROM — the Master Metrics Templates (given
# 2026-07-25). EVERY template link points here; never at a live office's board.
TEMPLATE_WORKBOOK_URL = ("https://docs.google.com/spreadsheets/d/"
                         "1b472JR73QZGZ8C_1oDtc3pF08cz9vh3pYCtSXZlDqio/edit")
_TPL = TEMPLATE_WORKBOOK_URL


def _tpl(gid: str) -> str:
    return f"{_TPL}?gid={gid}#gid={gid}"


# The tabs an office's metrics sheet must contain, per report that WRITES to the
# sheet. `template` deep-links the tab to copy (all in the Master Templates book).
#
# D2D: only churn NI + WL and ABP write to the sheet. The D2D ORDER LOG does NOT
#      — it builds an .xlsx (a tab per rep INSIDE the file) and posts it to Slack,
#      so there's no D2D order-log sheet tab. Knocks/cancels/etc. also Slack-only.
# B2B: the order log DOES write sheet tabs (Lucy At&t / Lucy Box Order Log, each
#      with a hidden data tab the code auto-creates), plus the consolidated churn
#      tab (Lucy OA Churn) and the 3 product churn-rate tabs. AIR is B2B only.
#   report_key: [ {"tab": <template tab name>, "template": <copy link | "">} ]
SHEET_TAB_TEMPLATES: "Dict[str, list]" = {
    # --- D2D (no template tabs in the book yet — names only) ---
    "churn_ni": [{"tab": "Local Office - New Internet Churn", "template": ""}],
    "churn_wl": [{"tab": "Local Office - Wireless Churn",     "template": ""}],
    "abp":      [{"tab": "Local Office - New Internet ABP%",  "template": ""}],
    # --- B2B (all in the Master Templates workbook) ---
    "b2b_churn": [
        {"tab": "Lucy OA Churn",       "template": _tpl("169198075")},
        {"tab": "Lucy New INT Churn",  "template": _tpl("1578352442")},
        {"tab": "Lucy Wireless Churn", "template": _tpl("0")},
        {"tab": "Lucy AIR Churn",      "template": _tpl("420276109")},
    ],
    "b2b_order_log": [
        {"tab": "Lucy At&t Order Log", "template": _tpl("1952579837")},
        {"tab": "Lucy Box Order Log",  "template": _tpl("882492646")},
    ],
}


# --- Pay Structure invite ---------------------------------------------------
# On onboarding, the tool emails the owner their Pay Structure link + a code so
# they can set their office's commission structure (feeds each rep's estimated
# payout on the daily order log). Same self-serve site as [[project_pay_structure]].
PAY_STRUCTURE_URL = "https://alphaletepaystructure.streamlit.app"
EVE_EMAIL = "alphaletereporting@gmail.com"


def gen_pay_code(business: str, key: str) -> str:
    """A per-office access code, e.g. 'aeon137'. First word of the business name
    (or the key) + a stable 3-digit suffix (deterministic from the key so
    re-submits don't churn the code). Megan can edit it before sending."""
    first = (business or key or "office").strip().split()[0] if (business or key) else "office"
    slug = re.sub(r"[^a-z0-9]", "", first.lower()) or (key or "office")
    seed = sum(ord(c) for c in (key or business or "x"))
    return f"{slug}{100 + seed % 900}"


def welcome_email(owner: str, code: str) -> "tuple":
    """(subject, html_body) — the WELCOME email a newly-enrolled office gets: Lucy
    now posts their office's daily metrics, plus their Pay Structure link + code so
    they can set their payouts. Same formatting as Megan's rollout email, reframed
    from a 'new feature' note to an onboarding welcome."""
    last = owner.strip().split()[-1] if owner.strip() else "your office"
    subject = f"Welcome to Lucy reporting - {last}"
    body = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#222;line-height:1.5">
<p>Hey team!</p>
<p><b>Welcome to Lucy reporting!</b> Your office is now set up with its own daily
metrics — every morning Lucy posts them to your Slack channel (knocks, order log,
churn, activations, ABP and more), so you can see how your office is doing at a
glance.</p>
<p>One thing to set up on your end: your commission structure. Enter what you pay
per product at each level and Lucy will show each rep an estimated payout — right
on their order log tab, <b><i>every morning.</i></b></p>
<p><b>It takes about 5 minutes:</b></p>
<ul>
  <li>Open your link: <a href="{PAY_STRUCTURE_URL}">{PAY_STRUCTURE_URL}</a></li>
  <li>Enter your code: <b>{code}</b></li>
  <li>Check the campaigns you run, then fill in your pay per product at each level
      (Level 1, Level 2, …). Fill in every cell — even when the pay is the same
      across levels.</li>
  <li>Hit Save. Done.</li>
</ul>
<p><b>A few notes:</b></p>
<ul>
  <li>You can update your pricing anytime; the next morning's log picks up the
      change automatically.</li>
  <li>Any product showing "NYP" (Not Yet Priced) just means you haven't set a rate
      for it yet — set it and save, and it starts calculating.</li>
  <li>Questions, or don't see a campaign you run? Message Eve
      (<a href="mailto:{EVE_EMAIL}">{EVE_EMAIL}</a>) &amp; Megan and we'll help.</li>
</ul>
<p><b>Welcome aboard!</b></p>
</div>"""
    return subject, body


def needed_tabs(family: str, enrolled_keys: "Optional[List[str]]" = None) -> "List[dict]":
    """The sheet tabs this office needs — the sheet-writing reports it enrolls.
    Each entry: {report, tab, template}. When enrolled_keys is None, returns all
    of the family's possible sheet tabs (used to preview before reports are
    picked)."""
    out = []
    for rk in REPORTS:
        if rk.family != family or rk.key not in SHEET_TAB_TEMPLATES:
            continue
        if enrolled_keys is not None and rk.key not in enrolled_keys:
            continue
        for t in SHEET_TAB_TEMPLATES[rk.key]:
            out.append({"report": rk.key, "tab": t["tab"], "template": t["template"]})
    return out


@dataclass
class EnrolledReport:
    key: str                      # ReportKind.key
    order: int = 0                # thread position; lower = earlier (default = seq)
    view_url: str = ""            # per-office saved-view URL, or "" = shared view
    view_machine: str = ""        # "Lucy 1" | "Lucy 2"; "" = inherit campaign default


@dataclass
class OnboardingRecord:
    """Everything the form captures for one office — the row written to the
    'Office Onboarding' tab and the input to apply.py's wiring."""
    key: str                      # stable handle, e.g. "cyrus" (unique).
    owner: str                    # canonical owner name (alias-sheet truth).
    knocks_office: str            # ownerville/knocks name (may differ from owner).
    business_name: str            # the office's own brand.
    website: str                  # site we auto-brand Pay Structure from.
    channel_id: str               # Slack channel id (C...).
    channel_name: str             # "#elevate-sales".
    sheet_id: str                 # the office's metrics workbook id.
    family: str                   # "d2d" | "b2b".
    ov_account: str = ""          # Ownerville account number (metadata; may equal
                                  # the AppStream office id but isn't guaranteed to).
    owner_email: str = ""         # where the Pay Structure invite is sent.
    pay_code: str = ""            # the office's Pay Structure access code.
    reports: List[EnrolledReport] = field(default_factory=list)
    label: str = ""               # "Cyrus's Local Office"; derived if blank.
    header_label: str = ""        # set ONLY when sharing a channel (distinct thread).
    thresholds: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    notes: str = ""
    submitted_at: str = ""        # ISO stamp, set by the store on write.
    submitted_by: str = ""        # who filled the form (audit).

    # ---- derivations -----------------------------------------------------
    def display_label(self) -> str:
        if self.label.strip():
            return self.label.strip()
        first = self.owner.split()[0] if self.owner.strip() else self.key.title()
        kind = "B2B Office" if self.family == "b2b" else "Local Office"
        return f"{first}'s {kind}"

    def report_id(self) -> str:
        return f"{self.key}_metrics"

    def ordered_reports(self) -> "List[EnrolledReport]":
        """Enrolled reports in thread order (by their order number, stable)."""
        return sorted(self.reports, key=lambda r: (r.order, r.key))

    def enrolled_views(self) -> "List[EnrolledReport]":
        """Reports that carry a real per-office saved view (the ones whose machine
        can differ from the campaign default)."""
        return [r for r in self.reports if (r.view_url or "").strip()]

    def machine(self) -> str:
        """Lucy 1 / Lucy 2. The campaign sets the default (D2D -> Lucy 1, B2B ->
        Lucy 2); a per-office saved view that renders on the other machine flips
        it (conflict if it enrolls views on both — checked in validate)."""
        machines = {(r.view_machine or "").strip()
                    for r in self.enrolled_views() if (r.view_machine or "").strip()}
        if machines:
            return "Lucy 2" if "Lucy 2" in machines else "Lucy 1"
        return FAMILY_DEFAULT_MACHINE[self.family]

    def runner_module(self) -> str:
        return ("automations.b2b_metrics.runner" if self.family == "b2b"
                else "automations.office_metrics.runner")

    def to_json(self) -> dict:
        d = asdict(self)
        d["_derived"] = {"machine": self.machine(),
                         "report_id": self.report_id(),
                         "label": self.display_label(),
                         "runner_module": self.runner_module()}
        return d


# --------------------------------------------------------------------------
# Parsing helpers the form uses to be forgiving about paste format.
# --------------------------------------------------------------------------
def sheet_id_from(link: str) -> str:
    """Accept a full Google Sheet URL or a bare id; return the id."""
    s = (link or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    return s            # assume it's already a bare id


def slug_from_owner(owner: str) -> str:
    """First name, lowercased, a-z0-9 only — the conventional office key."""
    first = (owner or "").strip().split()[0] if (owner or "").strip() else ""
    return re.sub(r"[^a-z0-9]", "", first.lower())


_SCI_VIEW = re.compile(r"^https://[\w.-]+/#/site/sci/views/\S+")


def validate(rec: OnboardingRecord, *,
             existing_channels: Optional[Dict[str, str]] = None,
             existing_keys: Optional[List[str]] = None,
             existing_views: Optional[Dict[str, str]] = None) -> List[str]:
    """Return [] when the record is safe to wire, else a list of problems.

    Mirrors office_metrics.offices.validate — the same anti-'wrong channel gets
    wrong office' guard — but runs at FORM time so Megan sees the conflict before
    anything is written. `existing_*` are the current registry values (channel_id
    -> key, list of keys, view_url -> "key.report") so we catch a collision with
    an already-wired office, not just within this one record.
    """
    existing_channels = existing_channels or {}
    existing_keys = existing_keys or []
    existing_views = existing_views or {}
    problems: List[str] = []

    if not rec.key.strip():
        problems.append("Office key is empty.")
    elif not re.match(r"^[a-z0-9]+$", rec.key):
        problems.append(f"Office key {rec.key!r} must be lowercase letters/digits "
                        "only (it's a CLI handle + file identity).")
    if rec.key in existing_keys:
        problems.append(f"Office key {rec.key!r} is already in the registry — "
                        "pick a unique handle.")

    for fname, val in (("owner", rec.owner), ("knocks_office", rec.knocks_office),
                       ("business_name", rec.business_name),
                       ("channel_id", rec.channel_id),
                       ("channel_name", rec.channel_name),
                       ("sheet_id", rec.sheet_id)):
        if not (val or "").strip():
            problems.append(f"{fname} is empty.")

    if rec.family not in ("d2d", "b2b"):
        problems.append(f"family {rec.family!r} must be 'd2d' or 'b2b'.")

    if not rec.reports:
        problems.append("No reports enrolled — check at least one.")

    # Channel collision: two offices may share a channel ONLY if both set a
    # header_label (distinct threads), exactly like office_metrics.validate.
    if rec.channel_id in existing_channels and not rec.header_label.strip():
        problems.append(
            f"Channel {rec.channel_id} ({rec.channel_name}) is already used by "
            f"{existing_channels[rec.channel_id]!r}. Two offices sharing a channel "
            "BOTH need a header label (distinct threads) — set one, or use a "
            "different channel.")

    # Per-office saved views (Advanced, rare): valid sci URL, unique vs the
    # registry, and a single machine so the office isn't split across both.
    seen_machine = set()
    for er in rec.enrolled_views():
        url = er.view_url.strip()
        if not _SCI_VIEW.match(url):
            problems.append(f"{er.key}: view URL isn't a Tableau /site/sci/ view: "
                            f"{url!r}")
        if url in existing_views:
            problems.append(f"{er.key}: view URL is identical to "
                            f"{existing_views[url]!r} — clone the view + set this "
                            "office's filter; a shared URL posts the wrong office.")
        m = (er.view_machine or "").strip()
        if m not in MACHINES:
            problems.append(f"{er.key}: view machine must be one of {MACHINES}.")
        else:
            seen_machine.add(m)
    if seen_machine == set(MACHINES):
        problems.append(
            "This office enrolls saved views on BOTH Lucy 1 and Lucy 2 — it can't "
            "run on both at once. Put every per-office view on one machine, or "
            "split it into two offices.")

    return problems
