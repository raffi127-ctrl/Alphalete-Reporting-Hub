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
                            (Carlos SKIPS 4+5 as of 2026-07-27 — skip_views;
                            Atef still posts them.)
  5. AIR Churn              Tableau — CHURNRATES / CarlosTeamAIRExp, sliced.
  6. Customer Churn         Sheet — the office board's LUCY CHURN tab main block
                            (the 0-30 Day Rolloff List), via vantura_churn.shot.
  7. Activation Rate by rep Sheet — the LUCY CHURN tab's rep chart (cols AE:AF).
  8. Order Log              The att_order_log xlsx (ORDERLOG export, owner-filtered).
  9. Order Tiered Bonus     Tableau — OrderTieredBonus-RepRanking, Owner Name
                            sliced, full canvas. Carlos only (Domin8 gets it via
                            the Tableau Country Trackers post). Added 2026-07-27.
 10. Activation report ovw. Two-week Activated/Cancelled/Still-Open per-rep image
                            (att_order_log.payout), from the same export.
 11. Out of Bounds          Tableau — OutofBoundsReport, owner-sliced. Posted even
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

# The ATT workbooks' week dropdown. THE SUFFIX IS PART OF THE CAPTION — Tableau
# matches URL filters on the field's caption and silently DROPS an unrecognised
# parameter, so "Sale Date Week Ending" without "(mon-sun)" is an inert no-op
# that leaves the view on its own default week (rep_sales_fill.run.WEEK_FIELD
# learned this the expensive way, 2026-08-14). Views that carry this filter name
# it in VIEW_META["week_filter"]; capture computes the value.
WEEK_FIELD = "Sale Date Week Ending (mon-sun)"

# …EXCEPT on OutofBoundsReport, where the dashboard PRINTS that caption but the
# field behind the dropdown is named differently. Read off the live filter
# checkbox ids on Lucy 2, 2026-08-17:
#   id='FI_sqlproxy.0pea…,none:Sale Date Week Ending (copy)_1603…:ok25…_147'
# So the URL has to say "(copy)". Sending the printed caption is a silent no-op
# — which is the whole reason the 8/17 post went out blank on the current week.
# Per-view, because it is a per-workbook accident, not a house convention.
WEEK_FIELD_OOB = "Sale Date Week Ending (copy)"

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
    # Order Tiered Bonus - Rep Ranking (Carlos 2026-07-27). Base view shows
    # every team — slice by Owner Name (Carlos's screenshot filters on "Owner
    # Name" = the plain owner). Captured full canvas (no data_cols in VIEW_META)
    # so the un-highlighted DNQ reps below the yellow "1-order-away" rows aren't
    # cropped off. Carlos posts it; Atef skips it (Country Trackers covers him).
    "order_tiered_bonus": _T + "ATTTRACKER-B2B/OrderTieredBonus-RepRanking",
    # OutofBoundsReport base view already shows all offices — slice by owner.
    "out_of_bounds": _T + "ATTTRACKER-B2B/OutofBoundsReport",
}

# Per-view capture metadata shared by ALL offices (the views are identical; only
# the owner slice differs). sort_header = the measure column whose sort glyph is
# clicked before the shot (Activation only — Churn carries its own sort);
# data_cols = number of period columns used to crop to the last data row.
VIEW_META: dict = {
    "sales_metrics":   {"filter_field": OWNER_FIELD},
    # Activation views (CarlosLocalOfficeEXPANDED, AtefEXP) load ALPHABETICAL —
    # verified 2026-07-23 (Atef's posted unsorted). Unlike churn (sort baked),
    # activation needs a sort click on "0-7 Days" high->low, the way b2b_quality
    # does it. apply_sort is best-effort, so a miss just leaves it alphabetical,
    # never blank.
    # NO data_cols -> no crop: show EVERY rep (Carlos 2026-08-12). The crop trims
    # to the last COLOURED row, but an Activations/Sales rep whose orders are all
    # still PENDING renders blank/white cells (not a red 0%) and sorts to the
    # bottom, so the crop was dropping real reps. Same reasoning as
    # order_tiered_bonus/out_of_bounds below — keep the whole ranking table.
    "activation_rate": {"filter_field": OWNER_OFFICE_FIELD,
                        "sort_header": "0-7 Days"},
    "churn_wireless":  {"filter_field": OWNER_OFFICE_FIELD, "data_cols": 5},
    "churn_int":       {"filter_field": OWNER_OFFICE_FIELD, "data_cols": 5},
    "churn_air":       {"filter_field": OWNER_OFFICE_FIELD, "data_cols": 5},
    # No data_cols -> no last-colored-row crop: keep the WHOLE ranking table
    # (the DNQ reps at the bottom aren't highlighted and would be trimmed).
    "order_tiered_bonus": {"filter_field": OWNER_FIELD},
    # WEEK-PINNED (Megan 2026-08-17). OutofBoundsReport opens on the CURRENT
    # Mon-Sun week, so every Monday it filtered to a week that had not started
    # selling yet — 2026-08-17 it asked for week ending 8/23 while the extract
    # only reached 8/16, and posted a header with no rows. Carlos posted the
    # section himself. Pin the week that holds the last COMPLETED sales day
    # (capture.report_week_ending) instead of trusting the view's default; the
    # capture then VERIFIES the pinned week actually rendered before the image
    # is allowed to post. Same class of bug as owner_showdown's Monday empty
    # week and box_order_log's stale window.
    # Per-view on purpose ([[reference_tableau_url_filters]] #3): the churn and
    # activation views are day-bucket cohorts and a week pin would wreck them.
    "out_of_bounds":   {"filter_field": OWNER_FIELD,
                        "week_filter": WEEK_FIELD_OOB},
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

    # ITEM ids to OMIT for this office. Use when a capture isn't correct for the
    # office yet AND a proven external poster still covers it in the SAME thread
    # (b2b_quality posts activation + churn) — the thread shows the working item
    # instead of a blank. Carlos's 4 ATTTRACKER captures (activation + 3 churn)
    # can't be URL-sliced ("Owner & Office"); his proven CarlosLocalOffice* saved
    # views need per-office sort/product handling not wired here yet, so skip them
    # until fixed + validated. b2b_quality keeps posting his activation + churn.
    skip_views: frozenset = field(default_factory=frozenset)

    # view_keys whose saved view is ALREADY sorted (sort baked in) — the capture
    # must NOT click the sort glyph on these, because a click TOGGLES the baked
    # sort back off. VIEW_META.sort_header sets which offices click by DEFAULT;
    # this opts an office out per view. (Atef's AtefEXP activation is baked;
    # Carlos's CarlosLocalOfficeEXPANDED is not, so Carlos clicks.)
    baked_sort_views: frozenset = field(default_factory=frozenset)

    # view_keys whose view_override is a whole-workbook saved view (a different
    # layout/expand state, NOT a pre-filtered owner slice) and so STILL needs the
    # ?<field>=<owner> slice appended at capture. Normal overrides are captured
    # as-is (their filter is baked); a slice_override keeps the owner slice so both
    # dashboard panels stay scoped to the office. (Carlos's Sales Metrics: CarlosEXP
    # carries the per-rep EXPANDED layout, still sliced by Owner Name.)
    slice_overrides: frozenset = field(default_factory=frozenset)

    # EXTRA channels that get the SAME post as `channel_id` (Carlos 2026-07-23:
    # his thread also goes to #a-players-b2b). Slack threads are per-channel, so
    # each mirror gets its own daily thread with the same header + same items.
    # The capture happens ONCE — a mirror only costs one upload per item, no extra
    # Tableau work — so mirroring stays cheap as offices are added.
    # Entries are (channel_id, "#display-name") so the id and the name the Hub
    # card shows can never drift apart.
    mirror_channels: tuple = field(default_factory=tuple)

    # Per-channel FAN-OUT — each channel gets only ITS metrics (unlike
    # mirror_channels, which posts the SAME set to every channel). Empty = no
    # fan-out (Carlos/Atef: byte-identical). Each element is a dict:
    #   {"channel_id","channel_name","report_keys":[owner-b2b-key,…]}
    # report_keys are the owner-facing ReportKind keys; the runner maps them to the
    # internal item ids via B2B_OWNER_KEY_TO_ITEMS. Only used when every plan has a
    # resolved channel_id (else the merge leaves this empty and the office mirrors).
    channel_plans: tuple = field(default_factory=tuple)

    @property
    def channel_names(self) -> list:
        """Every channel this office posts into, primary first — for display."""
        return [self.channel_name] + [n for _, n in self.mirror_channels]

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
        # Carlos's ATTTRACKER captures render BLANK via the shared TEAM views
        # (they filter on "Owner & Office", which can't be URL-sliced to
        # "Carlos Hidalgo" — verified 2026-07-22). Fix = his OWN proven saved
        # views (the ones b2b_quality posts correctly), product-switched by URL
        # exactly like Atef's AtefExp — captured as-is, no owner slice.
        # CHURNRATES sort ("0-30 disconnect count" desc) is baked into the view.
        view_overrides={
            # Sales Metrics: Carlos's CarlosEXP view (Megan 2026-08-06) — same
            # B2BATTSalesMetrics workbook as the team view, but the Owner Name
            # row group is EXPANDED so the post shows the per-rep breakdown
            # (Carlos's ask: "have Lucy hit the +/- so it shows my reps"). Kept in
            # slice_overrides below so it STILL gets the ?Owner Name= slice — the
            # only change from the old team view is the expanded layout.
            "sales_metrics": (_T + "ATTTRACKER-B2B/B2BATTSalesMetrics/"
                              "4a1c404e-54e1-4325-a1a8-61e361f8fd12/"
                              "CarlosEXP?:iid=1"),
            "churn_wireless": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                               "7419b960-0fb1-41d5-a11e-76f0e81c0547/"
                               "CarlosLocalOfficeEXPANDEDCHURN"
                               "?Product%20Type%20(Broken%20Out)=WIRELESS"),
            "churn_int": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                          "7419b960-0fb1-41d5-a11e-76f0e81c0547/"
                          "CarlosLocalOfficeEXPANDEDCHURN"
                          "?Product%20Type%20(Broken%20Out)=NEW%20INTERNET"),
            "churn_air": (_T + "ATTTRACKER-B2B/CHURNRATES/"
                          "7419b960-0fb1-41d5-a11e-76f0e81c0547/"
                          "CarlosLocalOfficeEXPANDEDCHURN"
                          "?Product%20Type%20(Broken%20Out)=AIR/AWB"),
            # Activation = the SAME view b2b_quality posts correctly. Captured
            # as-is (owner filter baked); VIEW_META's sort_header clicks "0-7
            # Days" high->low, exactly as b2b_quality does.
            "activation_rate": (_T + "ATTTRACKER-B2B/ACTIVATIONRATES/"
                                "4c53fb7e-5a1b-4e8f-990e-0b2c8cf42309/"
                                "CarlosLocalOfficeEXPANDED"),
        },
        # Carlos 2026-07-27: drop INT + AIR churn from HIS thread (Atef keeps
        # them). The overrides above stay intact so un-skipping restores them;
        # skip_views is the only toggle. Wireless churn + Customer churn remain.
        skip_views=frozenset({"churn_int", "churn_air"}),
        # CarlosEXP is a whole-workbook saved view (expanded layout), NOT a
        # pre-filtered slice — keep the ?Owner Name= slice so both panels stay
        # scoped to Carlos's office, exactly as the old team view did.
        slice_overrides=frozenset({"sales_metrics"}),
        # Carlos 2026-07-23: the SAME thread also posts to #a-players-b2b
        # (private, Lucy added as a member). Its own daily thread + dedup.
        mirror_channels=(("C0AJQA8P716", "#a-players-b2b"),),
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
        # AtefEXP already carries its 0-7 Days descending sort (it posted
        # correctly this morning with NO click — Megan 2026-07-23). Clicking it
        # would toggle that off, so opt Atef's activation OUT of the sort click.
        baked_sort_views=frozenset({"activation_rate"}),
        # Order Tiered Bonus already reaches #domin8-b2b-sales via the daily
        # "Tableau Country Trackers" post (tableau_screenshots, AtefExp view).
        # Skip it here so Domin8 doesn't get it twice in the same channel; the
        # section stays in Carlos's thread only (Carlos 2026-07-27 asked for it
        # in his B2B Metrics post).
        skip_views=frozenset({"order_tiered_bonus"}),
    ),
}

# ---------------------------------------------------------------------------
# B2B offices onboarded via the Metrics Onboarding tool (office_onboarding).
# Same pattern as office_metrics.offices: a committed sibling JSON that
# office_onboarding.apply regenerates from the 'Office Onboarding' tab. A normal
# B2B office is owner + channel + sheet (+ owner_office) and URL-slices the shared
# TEAM views — no view_overrides. STRICT NO-OP when the file is absent.
# ---------------------------------------------------------------------------
import json as _json                              # noqa: E402
from pathlib import Path as _Path                 # noqa: E402

_ONBOARDED_FILE = _Path(__file__).with_name("onboarded_offices.json")

# onboarding report key -> B2B view_key it overrides (only the cleanly-mapped
# ones; a single churn URL can't drive the 3 product views, so churn/order-log
# overrides are left for a manual view_overrides edit and flagged in EXTRA).
_B2B_VIEW_FIELD = {"b2b_sales": "sales_metrics", "b2b_activation": "activation_rate"}

# Owner-facing B2B ReportKind keys -> the internal thread item ids they include.
# Several owner concepts bundle multiple sections (Activation = the rate chart +
# by-rep + overview; AT&T Order Log = the log + the tiered-bonus ranking). Used by
# the runner to fan a channel plan's picked metrics out to the right sections.
# NOTE: b2b_order_log_box maps to NOTHING here — the Box log is the standalone
# box_order_log report (its own thread), not a metrics-thread section.
B2B_OWNER_KEY_TO_ITEMS = {
    "b2b_sales":          ["sales_metrics"],
    "b2b_activation":     ["activation_rate", "activation_by_rep", "activation_overview"],
    "b2b_churn_wireless": ["churn_wireless"],
    "b2b_churn_int":      ["churn_int"],
    "b2b_churn_air":      ["churn_air"],
    "b2b_customer_churn": ["customer_churn"],
    "b2b_order_log_att":  ["order_log", "order_tiered_bonus"],
    "b2b_order_log_box":  [],   # standalone report, not a thread section
}

ONBOARDED_EXTRA: dict = {}


def items_for_report_keys(report_keys) -> set:
    """Translate owner-facing B2B ReportKind keys to the internal item ids they
    cover (unknown keys pass through unchanged, so a raw item id also works)."""
    out = set()
    for k in report_keys or []:
        mapped = B2B_OWNER_KEY_TO_ITEMS.get(k)
        if mapped is None:
            out.add(k)          # already an item id
        else:
            out.update(mapped)
    return out


def _merge_onboarded() -> None:
    if not _ONBOARDED_FILE.exists():
        return
    try:
        rows = _json.loads(_ONBOARDED_FILE.read_text())
    except Exception:
        return
    for r in rows:
        key = (r.get("key") or "").strip()
        if not key or key in OFFICES:
            continue
        pov = r.get("per_office_views") or {}
        overrides, unmapped = {}, []
        for rk, url in pov.items():
            fld = _B2B_VIEW_FIELD.get(rk)
            if fld and url:
                overrides[fld] = url
            elif url:
                unmapped.append(rk)
        # Per-channel fan-out: build channel_plans ONLY when there are 2+ plans AND
        # every one has a resolved channel_id (else mirror/single behaviour — safe).
        _plans, _ok = [], True
        for p in (r.get("channel_plans") or []):
            cid = (p.get("channel_id") or "").strip()
            if not cid:
                _ok = False
                break
            _plans.append({"channel_id": cid,
                           "channel_name": p.get("channel_name", ""),
                           "report_keys": p.get("report_keys") or p.get("slugs") or []})
        _cp = tuple(_plans) if (_ok and len(_plans) > 1) else tuple()
        # Board TAB NAMES are per-office: an onboarded board is a hand-made
        # duplicate, so its churn / order-log tabs can be spelled differently
        # (Jamis's is 'Lucy Churn', not 'LUCY CHURN'). Carry them from the JSON
        # when present; the B2BOffice defaults still apply when they're absent.
        # Matching is case-tolerant at read time (fill.worksheet_ci), so this is
        # only needed for a genuinely different NAME, not different casing.
        _tabs = {}
        for _f in ("churn_tab", "order_log_tab"):
            if (r.get(_f) or "").strip():
                _tabs[_f] = r[_f].strip()
        # NO auto-skip any more (2026-08-01, same day it was added). It existed
        # because the "Owner & Office" team views appeared un-sliceable and an
        # onboarded office was posting blank churn/activation panels. Proven
        # wrong the same afternoon against the live view: they slice fine once
        # the value carries BOTH escapes Tableau needs — see
        # capture._tableau_filter_value. So an onboarded office needs no saved
        # views at all, which is the all-team design this registry was built for.
        try:
            OFFICES[key] = B2BOffice(
                key=key, label=r.get("label") or f"{key.title()}'s B2B Office",
                owner=r.get("owner", ""), channel_id=r.get("channel_id", ""),
                channel_name=r.get("channel_name", ""), sheet_id=r.get("sheet_id", ""),
                **_tabs,
                owner_office=r.get("owner_office", ""),
                view_overrides=overrides, channel_plans=_cp)
            ex = {"thresholds": r.get("thresholds", {}), "notes": r.get("notes", "")}
            if unmapped:
                ex["_unmapped_views"] = unmapped   # need a manual view_overrides edit
            ONBOARDED_EXTRA[key] = ex
        except Exception:
            continue


_merge_onboarded()

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
