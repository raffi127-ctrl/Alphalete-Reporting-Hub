"""THE B2B office registry — the ONE place to add a B2B office's Metrics thread.

Modelled on automations/office_metrics/offices.py (the D2D registry). Megan
2026-07-20: "eventually we'll do this for more B2B offices like we rolled out to
multiple D2D offices." So everything office-specific lives in one row, and the
generic runner (runner.py) posts the same ordered set of items for any office —
no per-office code to copy, which is how a stale copy sends one office's numbers
to another's channel.

THE THREAD, in Carlos's order (2026-07-20, "those are all of them in order"):
  1. Sales Metrics          Tableau — B2BATTSalesMetrics custom view + Owner
                            Name URL filter (both panels scoped, see
                            att_order_log.metrics_shot).
  2. Activate Rate          Tableau — ACTIVATIONRATES custom view.
  3. Churn Rate             Tableau — CHURNRATES custom view.
  4. Customer Churn         Sheet — the LUCY CHURN tab's main block (the
                            0-30 Day Rolloff List), via vantura_churn.shot.
  5. Activation Rate by rep Sheet — the LUCY CHURN tab's rep chart (cols AE:AF).
  6. Order log              The att_order_log workbook (overall + per-rep
                            paycheck tabs).
  7. Activation report      UNMAPPED (2026-07-20) — Carlos to clarify how it
                            differs from #6 / #8. Left out of the item list
                            until then.
  8. Activation report ovw. Two-week Activated/Cancelled/Still-Open per-rep
                            image (att_order_log.payout).
  9. Out of Bounds          Tableau — OutofBoundsReport custom view. Posted even
                            when BLANK (Carlos's Loom: "if it shows nothing, we
                            still want the screenshot").

CHANNEL NOTE: #alphalete-gp-sales cannot be read by Lucy's token, so the thread
is found/created via a thread_state.json file (day|channel -> thread_ts), NOT by
reading channel history — same mechanism b2b_quality already uses. The runner
carries that; the registry only names the channel.

ADD AN OFFICE: clone the office's Tableau custom views (Sales Metrics /
Activation / Churn / OOB) filtered to that owner, save its LUCY CHURN tab on its
board, add one B2BOffice(...) row with those URLs + its channel + owner + sheet.
`python -m automations.b2b_metrics.runner --office <key> --check` validates the
table (refuses to run if two offices share a channel or a view URL).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_T = "https://us-east-1.online.tableau.com/#/site/sci/views/"

THREAD_TITLE = "B2B Metrics"      # header first line + thread_state needle


@dataclass(frozen=True)
class B2BOffice:
    key: str                # CLI handle, unique. e.g. "carlos".
    label: str              # "Carlos's B2B Office" — logs + header suffix.
    owner: str              # canonical owner name, e.g. "Carlos Hidalgo".
    channel_id: str         # Slack channel id.
    channel_name: str       # "#alphalete-gp-sales" — display.
    sheet_id: str           # the office's board (holds the LUCY CHURN tab).
    churn_tab: str          # tab name for #4/#5, e.g. "LUCY CHURN".

    # Tableau custom-view URLs (each scoped to this owner under their login).
    view_sales_metrics: str
    view_activation_rate: str
    view_churn_rate: str
    view_out_of_bounds: str

    # #1 Sales Metrics also needs the RIGHT panel scoped via a URL filter — the
    # custom view only scopes the left table (proven 2026-07-20). Caption +
    # value of that filter; empty caption = no URL filter appended.
    metrics_filter_field: str = "Owner Name"
    metrics_filter_value: str = ""      # defaults to `owner` when empty

    @property
    def sales_metrics_owner(self) -> str:
        return self.metrics_filter_value or self.owner

    @property
    def tableau_views(self) -> dict:
        return {"sales_metrics": self.view_sales_metrics,
                "activation_rate": self.view_activation_rate,
                "churn_rate": self.view_churn_rate,
                "out_of_bounds": self.view_out_of_bounds}


# ---------------------------------------------------------------------------
# THE TABLE. One row per B2B office.
# ---------------------------------------------------------------------------
OFFICES: dict = {
    "carlos": B2BOffice(
        key="carlos",
        label="Carlos's B2B Office",
        owner="Carlos Hidalgo",
        channel_id="C07J46MQNUX",
        channel_name="#alphalete-gp-sales",
        sheet_id="1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY",
        churn_tab="LUCY CHURN",
        view_sales_metrics=(_T + "ATTTRACKER-B2B/B2BATTSalesMetrics/"
                            "eed37ad3-2bde-430e-9126-b1def96be8d3/"
                            "Carlos-ExpandedMetrics?:iid=1"),
        view_activation_rate=(_T + "ATTTRACKER-B2B/ACTIVATIONRATES/"
                              "4c53fb7e-5a1b-4e8f-990e-0b2c8cf42309/"
                              "CarlosLocalOfficeEXPANDED?:iid=2"),
        view_churn_rate=(_T + "ATTTRACKER-B2B/CHURNRATES/"
                         "7419b960-0fb1-41d5-a11e-76f0e81c0547/"
                         "CarlosLocalOfficeEXPANDEDCHURN?:iid=1"),
        view_out_of_bounds=(_T + "ATTTRACKER-B2B/OutofBoundsReport/"
                            "983b1e4d-99d4-4042-8b9d-5c3c1e33e2d4/"
                            "CarlosOOB?:iid=1"),
        metrics_filter_value="Carlos Hidalgo",
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
    """Hard structural check. [] = clean. Every channel + every Tableau view URL
    must be UNIQUE across offices (a duplicate is the copy-paste mistake that
    posts one office's screenshot into another's channel), every field present,
    every view a real sci Tableau URL."""
    problems = []
    required = ("label", "owner", "channel_id", "channel_name", "sheet_id",
                "churn_tab")
    seen_channel, seen_view = {}, {}
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
        for vname, url in o.tableau_views.items():
            if not re.match(r"^https://[\w.-]+/#/site/sci/views/\S+", url or ""):
                problems.append("{}: {} not a sci Tableau URL: {!r}".format(
                    key, vname, url))
            if url in seen_view:
                problems.append("{}: {} URL identical to {!r} — clone + "
                                "re-filter the view".format(
                                    key, vname, seen_view[url]))
            else:
                seen_view[url] = "{}.{}".format(key, vname)
    return problems


def assert_valid() -> None:
    problems = validate()
    if problems:
        raise ConfigError("B2B office table is inconsistent — refusing to run:"
                          "\n  - " + "\n  - ".join(problems))
