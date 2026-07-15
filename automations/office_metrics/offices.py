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
# office can pull this ONE view (deduped across offices by the Step-2 crosstab
# cache) and slice to its own owner — no per-office ABP view needed. This is
# RafLocalofficeINTABP: it's all-teams (Megan 2026-07-15) AND is the ABP module's
# built-in default — the view Raf's daily_metrics already uses in production, so
# it's battle-tested and won't be deleted (preferred over a freshly-made view).
# Per-office view_abp fields stay for the cell-for-cell proof + fallback. Prove
# before flipping: `runner --office rashad --prove-abp`.
ALL_OFFICE_ABP_VIEW = (_T + "ATTTRACKER2_1-D2D/Metrics/"
                       "07afddc4-36b3-4ecc-98a8-28b9ef1648c1/RafLocalofficeINTABP?:iid=1")
# Flip to True only after the proof is clean for every office (sliced all-office
# == per-office view). When True, metrics_for() points ABP at the shared view.
# PROVEN + flipped 2026-07-15: --prove-abp IDENTICAL for rashad (21 reps) + aya
# (23 reps) — sliced all-office == per-office view, cell for cell.
ABP_USE_ALL_OFFICE = True


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
    view_ongoing_cancel: str    # cancel-rates view (RashadExpanded-style).
    view_churn_ni: str          # New-Internet churn view (INTRashad-style).
    view_churn_wl: str          # Wireless churn view (WirelessRashad-style).
    view_abp: str               # New-Internet ABP view (RashadNLABP-style).

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
}

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
                "sheet_id", "knocks_office", "view_ongoing_cancel",
                "view_churn_ni", "view_churn_wl", "view_abp")

    seen_channel: dict[str, str] = {}
    seen_view: dict[str, str] = {}
    seen_report: dict[str, str] = {}
    for key, o in OFFICES.items():
        if o.key != key:
            problems.append(f"{key}: row key {o.key!r} != dict key {key!r}")
        for f in required:
            if not (getattr(o, f) or "").strip():
                problems.append(f"{key}: empty {f}")
        # channel uniqueness — two offices → same channel would double-post +
        # merge two offices' numbers into one thread.
        if o.channel_id in seen_channel:
            problems.append(f"{key}: channel {o.channel_id} ({o.channel_name}) "
                            f"already used by {seen_channel[o.channel_id]!r} — "
                            f"two offices must not share a channel")
        else:
            seen_channel[o.channel_id] = key
        # report_id uniqueness — shared id => clobbered manifest / wrong pill.
        if o.report_id in seen_report:
            problems.append(f"{key}: report_id {o.report_id!r} already used by "
                            f"{seen_report[o.report_id]!r}")
        else:
            seen_report[o.report_id] = key
        # view uniqueness — THE big one. A shared view URL means one office is
        # pointed at another's data → wrong numbers in that channel.
        for vname, url in o.views.items():
            if not re.match(r"^https://[\w.-]+/#/site/sci/views/\S+", url or ""):
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
