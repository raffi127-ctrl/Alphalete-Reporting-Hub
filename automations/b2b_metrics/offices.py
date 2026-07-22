"""THE B2B office registry — the ONE place to add a B2B office's Metrics thread.

Modelled on automations/office_metrics/offices.py (the D2D registry). Megan
2026-07-20: "eventually we'll do this for more B2B offices like we rolled out to
multiple D2D offices." So everything office-specific lives in one row, and the
generic runner (runner.py) posts the same ordered set of items for any office —
no per-office code to copy, which is how a stale copy sends one office's numbers
to another's channel.

ALL-TEAM SPLIT (Carlos 2026-07-21): the Tableau views are TEAM-wide custom views
(every office under Carlos's B2B org — the "CarlosTeam…" saved views) that we
slice to ONE office by appending `?Owner Name=<owner>` at capture. This is the
same win the D2D side got (office_metrics all-team views sliced per owner):
adding office #3–20 is a new B2BOffice row (owner + channel + sheet) and ZERO new
Tableau views. The team-view URLs live once in TEAM below.

THE THREAD, in Carlos's order (2026-07-20; churn expanded to 3 product views
2026-07-21 "3 churn views of each product, for Carlos as well"):
  1. Sales Metrics          Tableau — B2BATTSalesMetrics team view + Owner Name
                            URL slice (both panels scoped by the slice).
  2. Activation Rate        Tableau — ACTIVATIONRATES team view, owner-sliced.
  3. Wireless Churn         Tableau — CHURNRATES / CarlosTeamWIRELESSExp, sliced.
  4. INT Churn              Tableau — CHURNRATES / CarlosTeamINTExp, sliced.
  5. AIR Churn              Tableau — CHURNRATES / CarlosTeamAIRExp, sliced.
  6. Customer Churn         Sheet — the office board's LUCY CHURN tab main block
                            (the 0-30 Day Rolloff List), via vantura_churn.shot.
  7. Activation Rate by rep Sheet — the LUCY CHURN tab's rep chart (cols AE:AF).
  8. Order Log              The att_order_log xlsx (ORDERLOG export, owner-filtered).
  9. Activation report ovw. Two-week Activated/Cancelled/Still-Open per-rep image
                            (att_order_log.payout), from the same export.
 10. Out of Bounds          Tableau — OutofBoundsReport, owner-sliced. Posted even
                            when BLANK (Carlos's Loom: "if it shows nothing, we
                            still want the screenshot").

The 3 Tableau churn views are the RATE tables (per-rep disconnect counts); the
sheet Customer Churn is the actual 0-30 rolloff CUSTOMER list + tiers — different
surfaces, both posted (as Carlos's thread already did). The LUCY CHURN tab is
formula-driven off a raw block (cols P:AC) that a vantura_churn pull writes per
office; a freshly duplicated tab still holds the source office's data until that
pull runs against the new owner.

CHANNEL NOTE: these channels cannot be read by Lucy's token, so the thread is
found/created via a thread_state.json file (day|channel -> thread_ts), NOT by
reading channel history — same mechanism b2b_quality already uses. The runner
carries that; the registry only names the channel.

ADD AN OFFICE: add one B2BOffice(...) row — owner (exactly as Tableau's "Owner
Name" field spells it), its Slack channel id + name, and its board sheet id. No
Tableau views to clone. `python -m automations.b2b_metrics.runner --office <key>
--check` validates the table (refuses to run if two offices share a channel).
"""
from __future__ import annotations

from dataclasses import dataclass, field

_T = "https://us-east-1.online.tableau.com/#/site/sci/views/"

THREAD_TITLE = "B2B Metrics"      # header first line + thread_state needle

# The URL-filter field that isolates one office differs BY WORKSHEET (proven on
# captures): Sales Metrics + Out of Bounds slice on "Owner Name" (value = the
# owner's plain name), while CHURNRATES + ACTIVATIONRATES slice on "Owner &
# Office" (value = the owner's full "NAME [office]" string) — the "Owner Name"
# filter is silently ignored there and leaves the Grand Total at the team total.
# Each view names its field in VIEW_META["filter_field"]; the office supplies the
# matching value via slice_value().
OWNER_FIELD = "Owner Name"          # default when a view doesn't name one
OWNER_OFFICE_FIELD = "Owner & Office"

# ---------------------------------------------------------------------------
# SHARED TEAM VIEWS (Carlos 2026-07-21). All offices read these SAME views and
# slice by owner — no per-office clones. Order of the 6 keys matches the thread.
# ---------------------------------------------------------------------------
TEAM: dict = {
    "sales_metrics": (_T + "ATTTRACKER-B2B/B2BATTSalesMetrics/"
                      "403c5051-5762-4dfd-a9eb-8a6188a69a03/"
                      "CarlosTeamExpandedMetrics?:iid=2"),
    "activation_rate": (_T + "ATTTRACKER-B2B/ACTIVATIONRATES/"
                        "3c5ad8dd-5c2b-43d1-96fe-63b945de10fb/"
                        "CarlosTeamViewExpanded?:iid=1"),
    # The all-team product churn views (Carlos 2026-07-21 — the real bases).
    "churn_wireless": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                       "e5d34696-30de-4db7-a27e-2654dbf9babd/"
                       "CarlosTEAMWireless?:iid=1"),
    "churn_int": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                  "2365c727-4967-4bfc-a3c5-01015ea98278/"
                  "CarlosTEAMNewINTEXP?:iid=2"),
    "churn_air": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                  "66dd0946-c47b-488e-990c-cf67f04de4c0/"
                  "CarlosTEAMAIREXP?:iid=1"),
    # OutofBoundsReport base view already shows all offices — slice by owner.
    "out_of_bounds": _T + "ATTTRACKER-B2B/OutofBoundsReport",
}

# Per-view capture metadata shared by ALL offices (the views are identical; only
# the owner slice differs). sort_header = the measure column whose sort glyph is
# clicked before the shot (Activation only — Churn carries its own sort);
# data_cols = number of period columns used to crop to the last data row.
VIEW_META: dict = {
    "sales_metrics":   {"filter_field": OWNER_FIELD},
    "activation_rate": {"filter_field": OWNER_OFFICE_FIELD,
                        "sort_header": "0-7 Days", "data_cols": 4},
    "churn_wireless":  {"filter_field": OWNER_OFFICE_FIELD, "data_cols": 5},
    "churn_int":       {"filter_field": OWNER_OFFICE_FIELD, "data_cols": 5},
    "churn_air":       {"filter_field": OWNER_OFFICE_FIELD, "data_cols": 5},
    "out_of_bounds":   {"filter_field": OWNER_FIELD},
}


@dataclass(frozen=True)
class B2BOffice:
    key: str                # CLI handle, unique. e.g. "carlos".
    label: str              # "Carlos's B2B Office" — logs + header suffix.
    owner: str              # canonical owner name — EXACTLY as Tableau's
                            # "Owner Name" field spells it. Drives the Sales/OOB
                            # slice AND the order-log rep filter.
    channel_id: str         # Slack channel id.
    channel_name: str       # "#alphalete-gp-sales" — display.
    sheet_id: str           # the office's board (LUCY CHURN + order-log tabs).
    # The "Owner & Office" dimension value — the churn/activation slice. Tableau
    # spells it "<OWNER NAME> [office]" (e.g. "ATEF CHOUDHURY [domin8
    # acquisitions, inc.]"). Empty -> falls back to `owner`.
    owner_office: str = ""
    churn_tab: str = "LUCY CHURN"   # feeds #6 Customer Churn + #7 Activation-by-rep
    order_log_tab: str = "Lucy At&t Order Log"

    # Per-office saved-view URLs that OVERRIDE the shared TEAM view for a given
    # view_key. Use when the team view can't be URL-sliced to this office (e.g.
    # CHURNRATES filters on "Owner & Office", not "Owner Name", so the generic
    # ?Owner Name= slice is ignored — a saved view already filtered to the owner
    # is the reliable path). An overridden view is captured AS-IS: no owner slice
    # is appended (the saved view already carries the filter).
    view_overrides: dict = field(default_factory=dict)

    @property
    def tableau_views(self) -> dict:
        """view_key -> the URL to capture (per-office override if present, else
        the shared team view)."""
        return {k: self.view_overrides.get(k, TEAM[k]) for k in TEAM}

    def view_url(self, view_key: str) -> str:
        return self.view_overrides.get(view_key, TEAM[view_key])

    def is_override(self, view_key: str) -> bool:
        return view_key in self.view_overrides

    def slice_value(self, field: str) -> str:
        """The value to filter `field` to for this office. 'Owner & Office' uses
        the full NAME [office] string; everything else uses the plain owner."""
        if field == OWNER_OFFICE_FIELD:
            return self.owner_office or self.owner
        return self.owner


# ---------------------------------------------------------------------------
# THE TABLE. One row per B2B office. Owner + channel + sheet — no views.
# ---------------------------------------------------------------------------
OFFICES: dict = {
    "carlos": B2BOffice(
        key="carlos",
        label="Carlos's B2B Office",
        owner="Carlos Hidalgo",
        channel_id="C07J46MQNUX",
        channel_name="#alphalete-gp-sales",
        sheet_id="1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY",
    ),
    "atef": B2BOffice(
        key="atef",
        label="Atef's B2B Office (Domin8)",
        owner="Atef Choudhury",
        channel_id="C0B395PUUCW",   # #domin8-b2b-sales (Carlos 2026-07-21)
        channel_name="#domin8-b2b-sales",
        sheet_id="15YUHkAcG2AfiF6KRhCiOBKGDdS9nnjxdfvIXr7oRX30",
        owner_office="ATEF CHOUDHURY\r [domin8 acquisitions, inc.]",
        # CHURNRATES can't be URL-sliced by "Owner & Office" (compound value with
        # an embedded CR — Tableau URL returns empty). So churn rides Carlos's
        # Atef-scoped saved view AtefExp (Owner & Office baked in) and switches
        # PRODUCT via URL — a clean value Tableau URL filters DO match. One saved
        # view covers all three products. Activation still needs its own.
        view_overrides={
            "churn_wireless": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                               "5b6a79de-9727-4ff2-bf4f-4b9eac449d70/AtefExp"),
            "churn_int": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                          "5b6a79de-9727-4ff2-bf4f-4b9eac449d70/AtefExp"
                          "?Product%20Type%20(Broken%20Out)=NEW%20INTERNET"),
            "churn_air": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                          "5b6a79de-9727-4ff2-bf4f-4b9eac449d70/AtefExp"
                          "?Product%20Type%20(Broken%20Out)=AIR/AWB"),
            # Activation can't be URL-sliced (Owner & Office) either — Carlos's
            # Atef-scoped ACTIVATIONRATES saved view (named AtefEXP).
            "activation_rate": (_T + "ATTTRACKER-B2B/ACTIVATIONRATES/"
                                "9cfd3e6c-b221-47a6-8699-bd8eb524fd6e/AtefEXP"),
        },
    ),
}

ORDER = list(OFFICES)


def get(key: str) -> B2BOffice:
    try:
        return OFFICES[key]
    except KeyError:
        raise SystemExit("unknown office {!r}. known: {}".format(
            key, ", ".join(ORDER)))


class ConfigError(Exception):
    """The office table is internally inconsistent — refuse to run."""


def validate() -> list:
    """Hard structural check. [] = clean. Every channel + every owner must be
    UNIQUE across offices (a duplicate is the copy-paste mistake that posts one
    office's screenshot into another's channel), every required field present."""
    problems = []
    required = ("label", "owner", "channel_id", "channel_name", "sheet_id")
    seen_channel, seen_owner = {}, {}
    for key, o in OFFICES.items():
        if o.key != key:
            problems.append("{}: row key {!r} != dict key {!r}".format(
                key, o.key, key))
        for f in required:
            if not (getattr(o, f) or "").strip():
                problems.append("{}: empty {}".format(key, f))
        if o.channel_id in seen_channel:
            problems.append("{}: channel {} already used by {!r}".format(
                key, o.channel_id, seen_channel[o.channel_id]))
        else:
            seen_channel[o.channel_id] = key
        low = (o.owner or "").strip().lower()
        if low in seen_owner:
            problems.append("{}: owner {!r} already used by {!r} — the slice "
                            "would pull the same office twice".format(
                                key, o.owner, seen_owner[low]))
        else:
            seen_owner[low] = key
    return problems


def assert_valid() -> None:
    problems = validate()
    if problems:
        raise ConfigError("B2B office table is inconsistent — refusing to run:"
                          "\n  - " + "\n  - ".join(problems))
