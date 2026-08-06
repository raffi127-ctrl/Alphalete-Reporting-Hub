"""THE office registry — the ONE place to add a single-office daily-metrics feed.

Each office is one row. Everything that differs between offices lives here and
nowhere else: the Slack channel, the owner name, the office's Sheet, its
ownerville name (for knocks), and its four ICD-scoped Tableau views. The generic
runner (runner.py) reads a row and runs the eight metrics against it, so there is
no per-office code to copy — a stale copy is exactly how the wrong channel gets
the wrong office's numbers.

ADD AN OFFICE
  1. In Tableau, clone these FOUR views, set the ICD/owner filter to the new
     office, and Save As a new name (keep the filter ON):
       - ongoing-cancel  (like RashadExpanded / AyaExpanded)
       - churn New Internet   (like INTRashad / INTAYA)
       - churn Wireless       (like WirelessRashad / WirelessAYA)
       - New Internet ABP     (like RashadNLABP / AyaINTABP)
  2. Add one Office(...) row below with those four view URLs, the office's
     Slack channel, owner name, Sheet id, and ownerville office name.
  3. `python -m automations.office_metrics.runner --office <key> --check`
     validates the whole table (see validate() — it REFUSES to run if any two
     offices share a channel or a view URL, which is the copy-paste mistake that
     would cross-post one office's numbers to another's channel).

The other four metrics (order_log, sales_6plus, cancels, disconnects) need NOTHING
per office but the owner name — they pull an org-wide view and filter to the owner
in Python. knocks needs the ownerville office name. So a new office is really just
"clone 4 views + fill one row."
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_T = "https://us-east-1.online.tableau.com/#/site/sci/views/"

# Shared ALL-OFFICE ABP view. The ABP module already FILTERS by owner, so every
# office pulls this ONE view (deduped across offices by the Step-2 crosstab cache)
# and slices to its own owner — no per-office ABP view needed.
# MUST be genuinely all-teams: AllOfficeINTABP is (PROVEN 2026-07-15, --prove-abp
# IDENTICAL for rashad 21 reps + aya 23 reps). Do NOT use RafLocalofficeINTABP
# (07afddc4) — despite the name/appearance it is scoped to RAF's office; the proof
# returned ZERO of Rashad's reps when sliced. The name of a view is not proof of
# its scope — always --prove-abp a candidate before pointing ABP at it.
ALL_OFFICE_ABP_VIEW = (_T + "ATTTRACKER2_1-D2D/Metrics/"
                       "b0b90f8f-e597-425d-93ae-c55cf1898ae1/AllOfficeINTABP?:iid=1")
# Flip to True only after the proof is clean for every office (sliced all-office
# == per-office view). When True, metrics_for() points ABP at the shared view.
# PROVEN + flipped 2026-07-15: --prove-abp IDENTICAL for rashad (21 reps) + aya
# (23 reps) — sliced all-office == per-office view, cell for cell.
ABP_USE_ALL_OFFICE = True

# Shared ALL-OFFICE churn views (verified all-office 2026-07-15: INTAllTeams = 88
# offices, WirelessAllTeams = 87, both contain Rashad + Aya). The churn parse,
# with env CHURN_SLICE_OWNER set, filters to the office's ICD owner and RECOMPUTES
# the office total from its reps (these views have no per-office Total row — churn
# counts sum cleanly, unlike the ongoing-cancel rate). Prove before flipping:
#   runner --office rashad --prove-churn
ALL_OFFICE_CHURN_NI = (_T + "ATTTRACKER2_1-D2D/CHURN/"
                       "907184c5-3782-4c32-92ff-919b63d5d402/INTAllTeams?:iid=1")
ALL_OFFICE_CHURN_WL = (_T + "ATTTRACKER2_1-D2D/CHURN/"
                       "66b10d0a-1bb2-441a-85b1-982977a9514e/WirelessAllTeams?:iid=1")
# Flip True only after --prove-churn is IDENTICAL for every office.
# PROVEN + flipped 2026-07-15: --prove-churn ALL IDENTICAL for rashad + aya
# (both NI + WL, 0 rep diffs, office totals match) — sliced all-office ==
# per-office view, cell for cell.
CHURN_USE_ALL_OFFICE = True

# Shared ALL-OFFICE ongoing-cancel view (AllExpanded, verified all-office). It has
# one combined Grand Total (no per-office subtotal) and the rate can't be
# averaged — but the crosstab carries summable count measures (Running Sum of
# Canceled Internet Orders / Internet Sales), so the slice recomputes each
# office's rate = sum(cancels)/sum(sales), the same trick as churn. Env
# ONGOING_CANCEL_SLICE_OWNER drives it. Prove: runner --office X --prove-cancel.
ALL_OFFICE_CANCEL_VIEW = (_T + "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
                          "878f4f05-e565-4e93-9c78-be4a8f96b73c/AllExpanded?:iid=1")
# TRUE (Megan 2026-07-15): EVERY office slices the one shared AllExpanded view —
# consistent (all offices computed identically, same window/colors) + fastest
# (one cached pull), same as churn/ABP. --prove-cancel confirmed the office TOTAL
# matches per-office cell-for-cell on shared days (rashad); the only per-office
# difference was that the OLD per-office views had a different date window, which
# standardising on AllExpanded removes. So no per-office cancel view is needed
# for anyone — a new office is pure config.
CANCEL_USE_ALL_OFFICE = True


@dataclass(frozen=True)
class Office:
    key: str            # CLI handle + shim identity, e.g. "rashad". unique.
    report_id: str      # manifest / Hub-card / orchestrator id (KEEP existing).
    label: str          # "Rashad's Local Office" — the ABP subtitle + logs.
    owner: str          # Sheet/owner name, e.g. "Rashad Reed".
    channel_id: str     # Slack channel to post into.
    channel_name: str   # "#elevate-sales" — display + the guard's messages.
    sheet_id: str       # this office's metrics workbook (churn + ABP fills).
    knocks_office: str  # ownerville office name for the knocks scrape.
    # Per-office view URLs — LEGACY. Every metric now slices a SHARED all-office
    # view (ABP/CHURN/CANCEL flags all True), so a new office leaves these EMPTY.
    # They stay only for rashad/aya history + as a fallback if a shared flag is
    # ever turned back off. validate() checks uniqueness of the non-empty ones.
    view_ongoing_cancel: str = ""
    view_churn_ni: str = ""
    view_churn_wl: str = ""
    view_abp: str = ""
    # Set ONLY when two offices share a channel (Salik + Hammad → #elite-prime-
    # sales): the owner name is added to the Metrics header so each gets its own
    # distinguishable thread. Empty = single-office channel, no label (default).
    header_label: str = ""
    # Onboarding extras (only ever set on offices added via office_onboarding —
    # the hardcoded rows above leave them default). website auto-brands Pay
    # Structure; business_name is the office's own brand for displays.
    website: str = ""
    business_name: str = ""
    # Per-office metrics-tab labels. Empty = the original D2D "Local Office - ..."
    # convention baked into the churn/ABP fills (so every existing office is
    # byte-identical). An office whose sheet uses the newer "Lucy ..." template
    # (onboarded offices) sets these to its own tab labels, so the fill writes to
    # the tab that actually exists. Passed to the fills as CHURN_NI_TAB /
    # CHURN_WL_TAB / ABP_TAB; an empty value there falls back to the default name.
    churn_ni_tab: str = ""
    churn_wl_tab: str = ""
    abp_tab: str = ""
    # Per-channel fan-out. Empty = the office posts ALL its metrics to the single
    # channel_id above (every existing office — byte-identical). When set, the
    # office posts each plan to its OWN channel with only that plan's metric slugs
    # (e.g. cancels-only to a leaders channel). Each element is a dict:
    #   {"channel_id","channel_name","slugs":[metric-slug,…],"header_label":""}
    # slugs are ReportKind.key values, which equal the runner's metric slugs.
    channel_plans: tuple = ()
    # NDS owner: their metrics live in the NDS-SN (RES-ATT-OOF) workbook, not the
    # ATT-D2D one the standard boards pull. When True, the runner sources the NDS
    # equivalents (churn -> office_metrics.nds_churn, etc.). Default False = every
    # existing D2D office is byte-identical.
    nds: bool = False
    # Cross-workspace posting. Empty = post with the machine's default Lucy token
    # (the AO workspace — every existing office). Set to a filename under
    # ~/.config/recruiting-report/ holding a Slack BOT token (xoxb-…) when the
    # office's channel lives in a DIFFERENT Slack workspace than AO (e.g. trang's
    # #freshsuccess-all-leaders is in the FRESH SUCCESS workspace). The runner
    # loads it and posts THIS office's metrics with that token instead. See
    # [[project_trang_fresh_success]].
    slack_token_file: str = ""

    @property
    def views(self) -> dict:
        return {"ongoing_cancel": self.view_ongoing_cancel,
                "churn_ni": self.view_churn_ni,
                "churn_wl": self.view_churn_wl,
                "abp": self.view_abp}


# ---------------------------------------------------------------------------
# THE TABLE. One row per office. Add a row to add an office.
# ---------------------------------------------------------------------------
OFFICES: dict[str, Office] = {
    "rashad": Office(
        key="rashad",
        report_id="rashad_metrics",
        label="Rashad's Local Office",
        owner="Rashad Reed",
        channel_id="C0B3KTCCMT7",
        channel_name="#elevate-sales",
        sheet_id="11louWIU8IuSPrZLsMkRh8qEnO3wNqmeNwIOSKPpXzm8",
        knocks_office="Rashad Reed",
        view_ongoing_cancel=_T + "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
                            "b7cb521f-8535-4d3e-b4be-7a644065ad48/RashadExpanded?:iid=1",
        view_churn_ni=_T + "ATTTRACKER2_1-D2D/CHURN/"
                      "39c6f9f5-77c8-4de6-909e-5db242f9ee4a/INTRashad?:iid=1",
        view_churn_wl=_T + "ATTTRACKER2_1-D2D/CHURN/"
                      "2a80ee2a-7471-47ae-a592-27832a6e0ff5/WirelessRashad?:iid=1",
        view_abp=_T + "ATTTRACKER2_1-D2D/Metrics/"
                 "d932e0f6-72b4-4003-a5d1-4262137363de/RashadNLABP?:iid=1",
    ),
    "aya": Office(
        key="aya",
        report_id="aya_metrics",
        label="Aya's Local Office",
        owner="Aya Al-Khafaji",
        channel_id="C0AA85Y3FPE",
        channel_name="#indelible-sales",
        sheet_id="10t16jDAFDtQNytFWU6O6gJtoOFlg0UHLwoArTW_sRNg",
        knocks_office="Aya Al-Khafaji",
        view_ongoing_cancel=_T + "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
                            "64401f95-14e8-4b35-8c7c-7a61061cda1c/AyaExpanded?:iid=1",
        view_churn_ni=_T + "ATTTRACKER2_1-D2D/CHURN/"
                      "d3238662-2bb4-4e1f-86d0-487f13cc320b/INTAYA?:iid=1",
        view_churn_wl=_T + "ATTTRACKER2_1-D2D/CHURN/"
                      "43c24436-272f-444a-91b9-b7c467d19704/WirelessAYA?:iid=1",
        view_abp=_T + "ATTTRACKER2_1-D2D/Metrics/"
                 "c51fa7b7-f75d-4ca0-bb6a-f63c9a83eb32/AyaINTABP?:iid=1",
    ),
    # --- Offices added 2026-07-15 — PURE CONFIG (all metrics slice shared views,
    # no per-office Tableau views). owner = canonical name (alias sheet); the
    # churn/ABP/cancel slices match it case-insensitively. knocks_office = the
    # ownerville name (may differ from canonical — verified from OV).
    "cyrus": Office(
        key="cyrus", report_id="cyrus_metrics", label="Cyrus's Local Office",
        owner="Cyrus Wade", knocks_office="Cyrus Wade",
        channel_id="C0B1DHEFVLH", channel_name="#ambient-sales-1",
        sheet_id="1PVWJq4v1Ju3o5R3W3ugigxCaB1c3ZobRLsswx1tjdcc",
    ),
    "hammad": Office(
        key="hammad", report_id="hammad_metrics", label="Hammad's Local Office",
        owner="Hammad Haque", knocks_office="Muhammad UI Haque",
        channel_id="C06A6A8ED34", channel_name="#elite-prime-sales",
        sheet_id="1oJrhHAUA3k36VXiiN7yPGKYQmQ9gK7L4TSIYsklNoSA",
        header_label="Hammad Haque",       # shares #elite-prime-sales with Salik
    ),
    "kash": Office(
        key="kash", report_id="kash_metrics", label="Kash's Local Office",
        owner="Kash Rai", knocks_office="Akashdeep Rai",
        channel_id="C09AVM17PAR", channel_name="#palace-sales",
        sheet_id="1Nj7r35zyFNpupcN_2-KcEAI5JH8uPwqRnzJODDcWC5g",
    ),
    "salik": Office(
        key="salik", report_id="salik_metrics", label="Salik's Local Office",
        owner="Salik Mallick", knocks_office="Muhammad Waqar",
        channel_id="C06A6A8ED34", channel_name="#elite-prime-sales",
        sheet_id="1iJ4R99A6ul7jNYEEVEGlXT32pNf-He-oE0-N-EI_-78",
        header_label="Salik Mallick",      # shares #elite-prime-sales with Hammad
    ),
    "cody": Office(
        key="cody", report_id="cody_metrics", label="Cody's Local Office",
        owner="Cody Cannon", knocks_office="Cody Cannon",
        channel_id="C0849EPM4LD", channel_name="#aeon-sales",
        sheet_id="1YMBUk-q4Jqx_TVFJB0vbtwK_7sIEDbEAMgsIZc-gmXc",
    ),
}

# ---------------------------------------------------------------------------
# Offices onboarded via the Metrics Onboarding tool (office_onboarding). They
# live in a COMMITTED sibling JSON that office_onboarding.apply regenerates from
# the 'Office Onboarding' tab, so a new D2D office is data — no row hand-added
# here, and the Hub card + Pay Structure (both read OFFICES) pick it up for free.
#
# STRICT NO-OP when the file is absent (today's state): the merge only runs if
# onboarded_offices.json exists and parses, and it never overrides a hardcoded
# row. A local file read at import mirrors branding.json — no network.
# ---------------------------------------------------------------------------
import json as _json                              # noqa: E402
from pathlib import Path as _Path                 # noqa: E402

_ONBOARDED_FILE = _Path(__file__).with_name("onboarded_offices.json")

# map an onboarded per_office_views {report_key: url} onto the Office view fields
_VIEW_FIELD = {"ongoing_cancel": "view_ongoing_cancel", "churn_ni": "view_churn_ni",
               "churn_wl": "view_churn_wl", "abp": "view_abp"}

# Per-office thresholds/notes captured at onboarding, keyed by office key. Not
# consumed by the runner yet (defaults hold); exposed for displays + later use.
ONBOARDED_EXTRA: dict = {}

# Committed per-office SECTION override — the runner posts ONLY these metric slugs
# for the listed office (values are ReportKind keys or runner slugs; both resolve
# through OWNER_KEY_TO_SLUG). This is the durable bridge for an office whose
# onboarding enrolled the all-11 D2D default but that only runs a subset — e.g.
# Isaiah/Legacy is WIRELESS-ONLY (Smart Circle retail, no new-internet/D2D), so
# every internet board posts blank and is dropped. `knocks_gaps` is intentionally
# omitted: his ownerville Disposition has no wireless campaign, so the Knocks/Gaps
# board renders empty (see knocks_pull) — it goes back in once that's sourced from
# the Time Tracker. TODO: retire this once onboarding writes the subset directly.
SECTION_OVERRIDES: dict = {
    # Isaiah / Legacy is WIRELESS-ONLY (Smart Circle retail, no new-internet/D2D).
    # Every office_metrics board is either N/A (the internet/D2D ones) or empty
    # (Wireless Churn has no data; the one Churn board bundles New-Internet +
    # Wireless so the internet half can't be dropped). An all-blank thread "looks
    # horrible" (Megan 2026-08-04), so this office posts NO metrics thread — its
    # reporting is its trackers (NDS + VZ+FTR SCI). Empty tuple = post nothing.
    # HELD: post NOTHING until the FULL wireless/NDS thread is ready (Megan
    # 2026-08-05: nothing posts until ALL his metrics are wired). Time Gaps
    # already works (sources from the Time Tracker), and the NDS-workbook boards
    # (order log / cancels / 6+ / disconnects / wireless churn / rep activations /
    # tableau — from NDS-SN RES-ATT-OOF) are the remaining build. When ALL are
    # ready, flip to ("knocks_gaps", <nds slugs...>). Empty tuple = post nothing.
    # HELD OFF (Megan 2026-08-05: nothing posts until ALL his metrics are ready).
    # Built + dry-run-verified so far: knocks_gaps (Time Gaps), churn (Wireless
    # Churn), rep_activations. Still BLOCKED on Raf's NDS views for order log /
    # wireless 6+ / wireless cancels. When ALL are wired + verified, flip to the
    # full slug list for go-live sign-off. Empty tuple = post nothing.
    # HELD OFF while mid-build. Built + verified: churn, rep_activations,
    # knocks_gaps (Time Gaps). ORDER LOG pull verified (166 rows) but its 3 renders
    # (order_log/cancels/sched_6plus) aren't built yet. Flip to the full slug list
    # only when every board renders + Megan signs off. Empty tuple = post nothing.
    # LIVE (Megan 2026-08-06 go-live). Full NDS thread, all 6 boards dry-run-
    # verified 6/6: Time Gaps, Wireless Churn, Rep Activations, Order Log (166),
    # Canceled + Disconnected Orders. Header lists exactly these; cancels/disconnects
    # post "No new ... orders" on empty days.
    "isaiah": ("knocks_gaps", "churn", "rep_activations", "order_log",
               "cancels", "disconnects"),
}

# Onboarded office keys whose metrics come from the NDS-SN (RES-ATT-OOF) workbook
# (NDS owners), so the runner sources the NDS equivalents. Committed here (not in
# each mini's onboarded_offices.json) so it deploys via git like SECTION_OVERRIDES.
NDS_OFFICES: set = {"isaiah"}

# Offices whose Slack channel lives in a DIFFERENT workspace than AO, so their
# metrics must post with a workspace-specific BOT token instead of the machine's
# default AO 'Lucy' token. Maps office key -> token filename under
# ~/.config/recruiting-report/. Committed here (like NDS_OFFICES) so it survives
# an onboard_apply re-materialize (which regenerates onboarded_offices.json from
# the sheet and wouldn't otherwise carry this field). [[project_trang_fresh_success]]
CROSS_WS_TOKEN_FILES: dict = {"trang": "slack-token-freshsuccess"}


def _merge_onboarded() -> None:
    if not _ONBOARDED_FILE.exists():
        return
    try:
        rows = _json.loads(_ONBOARDED_FILE.read_text())
    except Exception:
        return
    for r in rows:
        key = (r.get("key") or "").strip()
        # only D2D rows belong here; never clobber a hardcoded office
        if not key or key in OFFICES or r.get("machine", "Lucy 1") == "__b2b__":
            continue
        kw = dict(
            key=key, report_id=r.get("report_id") or f"{key}_metrics",
            label=r.get("label") or f"{key.title()}'s Local Office",
            owner=r.get("owner", ""), channel_id=r.get("channel_id", ""),
            channel_name=r.get("channel_name", ""), sheet_id=r.get("sheet_id", ""),
            knocks_office=r.get("knocks_office", "") or r.get("owner", ""),
            header_label=r.get("header_label", ""),
            website=r.get("website", ""), business_name=r.get("business_name", ""),
            churn_ni_tab=r.get("churn_ni_tab", ""),
            churn_wl_tab=r.get("churn_wl_tab", ""),
            abp_tab=r.get("abp_tab", ""),
            slack_token_file=CROSS_WS_TOKEN_FILES.get(
                key, r.get("slack_token_file", "")),
            nds=(key in NDS_OFFICES))
        for rk, url in (r.get("per_office_views") or {}).items():
            fld = _VIEW_FIELD.get(rk)
            if fld and url:
                kw[fld] = url
        # Per-channel fan-out: build channel_plans ONLY when there are 2+ plans AND
        # every one has a resolved channel_id (Megan sets these on finalize). If any
        # id is missing, fan-out stays OFF and the office posts everything to its
        # primary channel — a safe fallback, never a crash or a lost metric.
        _plans, _ok = [], True
        for p in (r.get("channel_plans") or []):
            cid = (p.get("channel_id") or "").strip()
            if not cid:
                _ok = False
                break
            _plans.append({"channel_id": cid,
                           "channel_name": p.get("channel_name", ""),
                           "slugs": p.get("report_keys") or p.get("slugs") or [],
                           "header_label": p.get("header_label", "")})
        if _ok and len(_plans) > 1:
            kw["channel_plans"] = tuple(_plans)
        try:
            OFFICES[key] = Office(**kw)
            ONBOARDED_EXTRA[key] = {"thresholds": r.get("thresholds", {}),
                                    "notes": r.get("notes", ""),
                                    "enrolled_reports": r.get("enrolled_reports", [])}
        except Exception:
            # a malformed row must never break import for the live offices
            continue


_merge_onboarded()

ORDER = list(OFFICES)          # stable order for listing


def get(key: str) -> Office:
    try:
        return OFFICES[key]
    except KeyError:
        raise SystemExit(f"unknown office {key!r}. known: {', '.join(ORDER)}")


class ConfigError(Exception):
    """The office table is internally inconsistent — refuse to run."""


def validate() -> list[str]:
    """Hard structural check of the whole table. Returns [] when clean, else a
    list of problems. This is the anti-'wrong channel gets wrong info' guard:
    the ONLY way an office posts another office's numbers is if its config points
    at another office's channel or view, i.e. a duplicated value from copying a
    row and forgetting to swap it. So every channel and every view URL must be
    UNIQUE across the table, every field present, every view a real Tableau URL.
    The runner calls this at startup and aborts before any pull or post."""
    problems: list[str] = []
    required = ("report_id", "label", "owner", "channel_id", "channel_name",
                "sheet_id", "knocks_office")   # view_* are legacy/optional now

    seen_channel: dict[str, str] = {}
    seen_view: dict[str, str] = {}
    seen_report: dict[str, str] = {}
    for key, o in OFFICES.items():
        if o.key != key:
            problems.append(f"{key}: row key {o.key!r} != dict key {key!r}")
        for f in required:
            if not (getattr(o, f) or "").strip():
                problems.append(f"{key}: empty {f}")
        # channel sharing — two offices MAY share a channel, but ONLY if BOTH set
        # a header_label so they post to distinct, distinguishable threads
        # (Salik + Hammad → #elite-prime-sales). Without labels their numbers
        # would merge into one thread.
        if o.channel_id in seen_channel:
            other_key, other_labeled = seen_channel[o.channel_id]
            if not (o.header_label and other_labeled):
                problems.append(
                    f"{key}: channel {o.channel_id} ({o.channel_name}) already "
                    f"used by {other_key!r} — two offices sharing a channel BOTH "
                    f"need a header_label (distinct threads)")
        else:
            seen_channel[o.channel_id] = (key, bool(o.header_label))
        # report_id uniqueness — shared id => clobbered manifest / wrong pill.
        if o.report_id in seen_report:
            problems.append(f"{key}: report_id {o.report_id!r} already used by "
                            f"{seen_report[o.report_id]!r}")
        else:
            seen_report[o.report_id] = key
        # view uniqueness — only for POPULATED legacy views (rashad/aya). A new
        # office slices the shared views and leaves these empty, so skip empties.
        for vname, url in o.views.items():
            if not (url or "").strip():
                continue
            if not re.match(r"^https://[\w.-]+/#/site/sci/views/\S+", url):
                problems.append(f"{key}: {vname} is not a sci Tableau view URL: "
                                f"{url!r}")
            if url in seen_view:
                problems.append(
                    f"{key}: {vname} view URL is IDENTICAL to "
                    f"{seen_view[url]!r} — clone the view + change the ICD "
                    f"filter; a shared view posts the wrong office's numbers")
            else:
                seen_view[url] = f"{key}.{vname}"
    return problems


def assert_valid() -> None:
    problems = validate()
    if problems:
        raise ConfigError(
            "office table is inconsistent — refusing to run:\n  - "
            + "\n  - ".join(problems))
