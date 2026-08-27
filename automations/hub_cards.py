"""Every Hub report card — THE file to edit when adding or changing a report.

Split out of dashboard.py 2026-08-20 (Megan): with several Claude sessions
working concurrently, the 13k-line dashboard was the one file everyone had to
touch — constant collisions. Card work now happens here; dashboard.py
(layout / nav / card schema — Megan-owned) imports AUTOMATED_REPORTS,
WEEKDAY_NAMES and _last_completed_we_sunday from here. The uploaded/shared-
library merge still happens in dashboard.py after the import.

House rules that apply to every card in this file: no hardcoded rows/columns,
preview new multi-tab fills on Marcellus first, every report wires
ti.alert_terminated, cross-platform (macOS AND Windows).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

from automations.recruiting_report import fill as _fill  # noqa: E402

SHEET_URL = f"https://docs.google.com/spreadsheets/d/{_fill.SPREADSHEET_ID}/edit"
# Daily Focus reports (Raf + Carlos captainships) live in their own shared
# sheet — one tab per captainship.
DAILY_FOCUS_SHEET_URL = "https://docs.google.com/spreadsheets/d/11FRYGG1hvuxcbWiYtDv7LzVss6ujZE_SOpqfhrQrVAo/edit"
# Carlos 1on1s - Focus Report (the B2B equivalent of Raf's weekly recruiting
# report). Shared module — set CAPTAINSHIP=Carlos when running.
CARLOS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1KLF8diMJ8pwIQWW9IqN7CL288t1l9VGUKxzBcMl8Of4/edit"
# Alphalete Org 1on1s - Focus Reports — third sheet, reps × campaign tabs
# (NDS / B2B / BOX / Retail / JE / Frontier). Shared module — set
# CAPTAINSHIP=Alphalete-Org when running.
ALPHALETE_ORG_SHEET_URL = "https://docs.google.com/spreadsheets/d/1C6BLttOSZhs_dREySac19XkxnMl-Ab_sYacNSl2l6AQ/edit"


WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _last_completed_we_sunday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


# DEPRECATED (2026-06-29): recruiting_report.run's --week now means the Sheet WE
# Sunday (it reads AppStream from week-7 internally), so callers pass
# _last_completed_we_sunday() directly. This WE-minus-7 helper is the OLD
# AS-picker convention and is no longer wired anywhere — do NOT use it for a
# --week arg or you'll fill the column one week too early.
def _last_completed_as_picker(today: dt.date | None = None) -> dt.date:
    return _last_completed_we_sunday(today) - dt.timedelta(days=7)


def _office_run_args(base_args, report_id: str):
    """CLICK-time args for one office's re-run button.

    If TODAY's run left metrics missing, re-run ONLY those (the run-manifest's
    scoped retry_args); otherwise run the whole office. Scoping matters because a
    re-run RE-POSTS every metric it executes — there's no already-posted guard —
    so a blind full re-run duplicates a thread that's already complete (Megan
    2026-07-16: "it will only try to pull the missed metrics on a rerun?" — now
    it does).

    Date-guarded: a manifest from an earlier day must never scope the button to
    YESTERDAY's misses. args_fn is evaluated on click, so this reads the manifest
    as it stands at click time, not at render. Best-effort — any hiccup falls
    back to the full run, which is always correct, just noisier."""
    try:
        from automations.shared import run_manifest as _rm
        spec = _rm.retry_spec(report_id)
        if spec and spec.get("retry_args"):
            if str(spec.get("run_ts") or "").startswith(dt.date.today().isoformat()):
                return list(spec["retry_args"])
    except Exception:
        pass
    return list(base_args)


def _office_metrics_card() -> dict:
    """ONE card for every per-office daily-metrics feed (Megan 2026-07-17 — was
    a card per office, and only Rashad + Aya ever had one, so the five offices
    added 7/15-16 had no Hub presence at all).

    The office list is read from office_metrics.offices.OFFICES and the
    per-office "re-run" buttons are GENERATED from it — so adding an office stays
    one row in that registry, with no card to hand-write. Per-office outcomes
    show as a ✅/❌ checklist (post_run.channel_status_file, written by each
    office's run). That checklist is what makes one card safe here: a single red
    light would hide a lone office failing.

    Same shape as _tableau_trackers_card, which consolidated the same way."""
    from automations.office_metrics import offices as _off
    from automations.office_metrics import runner as _omr
    offs = [_off.OFFICES[k] for k in _off.ORDER]
    # (label, channel, module, args) per office button. Raf's local office is
    # FIRST and still runs its own older module — same 11 metrics, but it
    # predates the generic runner (see runner.MAIN_OFFICE_*), so its button
    # launches it exactly as its own card always did. The other 7 are generated
    # from the registry.
    buttons = [(_omr.MAIN_OFFICE_LABEL, _omr.MAIN_OFFICE_CHANNEL,
                _omr.MAIN_OFFICE_MODULE, [], "daily_metrics")]
    buttons += [(o.label, o.channel_name, "automations.office_metrics.runner",
                 ["--office", o.key, "--live"], o.report_id) for o in offs]
    # One office per line for the breakdown panel (white-space:pre-wrap).
    office_bullets = "\n".join(f"• {lb} → {ch}" for lb, ch, _m, _a, _r in buttons)
    # De-duped: Hammad + Salik share #elite-prime-sales, so the raw list repeats
    # it. Keep first-seen order.
    _seen: set = set()
    channels = ", ".join(
        ch for _lb, ch, _m, _a, _r in buttons
        if not (ch in _seen or _seen.add(ch)))
    return {
        "id": "office-metrics",
        "name": "D2D Office Daily Metrics",
        "creator": "Megan",
        "emoji": "📈",
        "color": "#8B5CF6",
        "category": "🏢 Other Offices",
        "description": (
            f"The same 12 daily metrics as the main report, run for each of the "
            f"{len(buttons)} offices and posted into that office's own Metrics "
            f"thread: {channels}. Every metric slices a shared org-wide view and "
            "filters to the office's owner, so adding an office is config only — "
            "no new Tableau views. Each office runs + posts independently; use "
            "the per-office buttons to re-run just one. Sundays add the "
            "Weekly Knock Dispositions board to the same threads."),
        "breakdown": (
            "WHAT IT DOES\n"
            f"For each office below, runs all the daily metrics and posts them "
            "into today's Metrics thread in that office's channel (one header "
            "thread per office per day, created first if it isn't up yet).\n\n"
            f"OFFICES\n{office_bullets}\n\n"
            "METRICS POSTED (in thread order)\n"
            "• 🚪 Total Knocks (one combined board — knocks + time gaps). A "
            "wireless office gets TeleMapper Knocks instead: its reps don't "
            "disposition, so Ownerville records knock times and gaps, not "
            "knock counts. Also one board.\n"
            "• 📋 Order Log\n"
            "• 📅 Sales Scheduled 6+ Days Out\n"
            "• 🚫 Canceled Orders\n"
            "• 🔁 Ongoing Cancel\n"
            "• ❎ Disconnected New Internets\n"
            "• 🌐 New Internet Churn\n"
            "• 📊 Wireless Churn\n"
            "• 🆕 Rep Activations\n"
            "• 💳 New Internet ABP %\n"
            "• 📸 Tableau Metrics (screenshot of the ATT TRACKER Metrics view, scoped to the office)\n\n"
            "SUNDAYS ONLY (extra board, same thread)\n"
            "• 📋 Weekly Knock Dispositions — per-rep Mon–Sat talk-to "
            "productivity + total apps (Raf's ask, 2026-08-22): talk-to "
            "totals/averages, apps from the Product Sales Summary, first/last "
            "knock, gap time, office totals. Runs as its own scheduler entry "
            "(weekly_knock_dispositions) but reports onto THIS card — no card "
            "of its own. Raf's office now; offices enrolled for Knocks/Time "
            "Gaps join when the rollout flag flips "
            "(weekly_knock_dispositions/offices.py INCLUDE_ENROLLED).\n\n"
            "WHEN IT RUNS\n"
            "Daily in the 4am batch, each office in turn."),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4:50 AM",
            # ~6 min of metrics per office, plus the one-login Tableau capture
            # pass the first office pays for everyone (12th metric, 2026-07-16).
            "estimated_minutes": 6 * len(buttons) + 12,
        },
        "checklist": [],
        "post_run": {
            "message_success": (
                f"✅ Office metrics posted — all 12 metrics in each of the "
                f"{len(buttons)} offices' threads."),
            "message_failed": (
                "❌ An office had a miss — check the per-office checklist, then "
                "re-run that office from its button below."),
            # Drives the ✅/❌ per-office checklist on the card (_channel_status).
            "channel_status_file": "output/office_metrics/_posted_today.json",
        },
        "actions": [
            {
                "label": "Run All Offices",
                "icon": "▶",
                "primary": True,
                "help": (f"Runs all 12 metrics for each of the {len(buttons)} "
                         "offices in turn and posts to each office's own "
                         "channel. Continues past an office that fails. Needs a "
                         "warm Tableau + ownerville session (best run on the "
                         "mini)."),
                "module": "automations.office_metrics.runner",
                "args_fn": lambda: ["--all", "--live"],
            },
        ] + [
            {
                "label": f"Re-run {lb} ({ch})",
                "icon": "🔁",
                "help": ("Re-runs only the metrics that missed today; runs the "
                         "whole office if nothing missed."),
                "module": mod,
                # default-bind — a bare closure would capture the loop variable
                # and every button would run the LAST office.
                "args_fn": (lambda a=args, rid=rid_: _office_run_args(a, rid)),
            }
            for lb, ch, mod, args, rid_ in buttons
        ],
    }


def _b2b_metrics_card() -> dict:
    """ONE card for the B2B Metrics thread, run per office (Megan 2026-07-20 —
    mirrors _office_metrics_card, and scales the same way: the office list is
    read from b2b_metrics.offices.OFFICES and the per-office re-run buttons are
    GENERATED from it, so adding a B2B office stays one registry row).

    This consolidates what used to be several reports racing into one thread
    (b2b_quality + vantura_churn + …) into a single ordered run per office —
    the same win office_metrics gave the D2D side."""
    from automations.b2b_metrics import offices as _bo
    from automations.b2b_metrics import runner as _bmr
    offs = [_bo.OFFICES[k] for k in _bo.ORDER]
    # An office can mirror its thread into extra channels, so show every channel
    # it posts into (primary first) — otherwise a mirrored office reads as one.
    office_bullets = "\n".join(
        "• {} → {}".format(o.label, ", ".join(o.channel_names)) for o in offs)
    _seen: set = set()
    channels = ", ".join(
        c for o in offs for c in o.channel_names
        if not (c in _seen or _seen.add(c)))
    item_lines = "\n".join(
        "• {} {}".format(i["emoji"], i["title"]) for i in _bmr.ITEMS)
    return {
        "id": "b2b-metrics",
        "name": "B2B Metrics",
        "creator": "Megan",
        "emoji": "📊",
        "color": "#2563EB",
        "category": "🏢 Other Offices",
        "description": (
            "The B2B Metrics thread for each B2B office, posted in order into "
            "that office's channel ({}). Consolidates what used to be several "
            "reports racing into one thread into a single ordered run — adding "
            "an office is config only (one registry row).".format(channels)),
        "breakdown": (
            "WHAT IT DOES\n"
            "For each B2B office below, captures the ordered set of items and "
            "posts them into today's 'B2B Metrics' thread in that office's "
            "channel (one header thread per office per day, created first if it "
            "isn't up yet).\n\n"
            "OFFICES\n{}\n\n"
            "POSTED (in thread order)\n{}\n\n"
            "WHEN IT RUNS\n"
            "In the 4:00am orchestrator flow on Lucy 2."
        ).format(office_bullets, item_lines),
        "assignees": ["Lucy 2"],
        "schedule": {
            "frequency": "daily",
            # `time` must be a real clock value (drives sort + the "Daily at …"
            # label); the descriptive cadence lives in time_label (box-order-log
            # pattern). Was a prose string that rendered literally + broke sort.
            "time": "5:00 AM",
            "time_label": "4am flow (~5 AM CST)",
            "estimated_minutes": 10 * len(offs),
        },
        "checklist": [],
        "post_run": {
            "message_success": (
                "✅ B2B Metrics posted — every item in each office's thread."),
            "message_failed": (
                "❌ A B2B Metrics item missed — check the log and re-run that "
                "office from its button below."),
            # Per-office ✅/❌ rows naming EVERY channel each office posts into
            # (mirrors + fan-out included) — written by runner main()'s loop.
            "channel_status_file": "output/b2b_metrics/_posted_today.json",
        },
        "actions": [
            {
                "label": "Run All Offices",
                "icon": "▶",
                "primary": True,
                "help": ("Captures + posts the ordered B2B Metrics set for each "
                         "office into its channel. Continues past a failed "
                         "item. Needs a warm Tableau session — run on Lucy 2."),
                "module": "automations.b2b_metrics.runner",
                "args_fn": lambda: ["--office", _bo.ORDER[0], "--post"],
            },
        ] + [
            {
                "label": "Re-run {} ({})".format(o.label, o.channel_name),
                "icon": "🔁",
                "help": "Re-captures + posts this office's B2B Metrics thread.",
                "module": "automations.b2b_metrics.runner",
                "args_fn": (lambda k=o.key: ["--office", k, "--post"]),
            }
            for o in offs
        ],
    }


def _tableau_trackers_card() -> dict:
    """ONE card for the country-wide Tableau trackers, posted to EVERY channel
    off a single capture (Megan 2026-07-14 — was 5 cards, one per org).

    The channel list is read from slack_post.ORG_CHANNELS, and the per-channel
    "re-post" buttons are GENERATED from it — so adding a channel is one line in
    that map and the Hub picks it up automatically, with no card to hand-write.
    Per-channel outcomes show as a ✅/❌ checklist (see _tableau_channel_status),
    and the standard manifest-retry button re-posts only the channels that
    missed. That's what makes one card safe here: a single red light would hide
    a lone channel failing.

    B2B Box IS listed on this card's thread but posts LATER on its own run
    (_tableau_box_card) — its Tableau data isn't in during the 4am run, so its
    image follows ~7am. Two runs, two pills, so a board that simply hasn't
    landed yet doesn't turn the 4am card red."""
    from automations.tableau_screenshots import slack_post as _sp
    from automations.tableau_screenshots import pages as _pages
    # Org-wide boards = every channel gets them. EXCLUDE opt_in_only boards: those
    # post ONLY to the channels that name them (ORG_TRACKERS), so counting them as
    # "posted to every channel" would overstate the card. They're covered in the
    # CHANNEL-SPECIFIC section of the breakdown instead.
    morning = [p for p in _pages.PAGES
               if not _pages.is_late(p) and not _pages.is_opt_in_only(p)]
    late = [p for p in _pages.PAGES if _pages.is_late(p)]
    # Every tracker that shows in the thread (org-wide + late), in board order —
    # excludes only opt-in-only boards. Late boards (B2B Box) are LISTED here from
    # the start; their image just follows once the data refreshes. (Megan 7/28)
    _display = [p for p in _pages.PAGES if not _pages.is_opt_in_only(p)]
    # Boards TODAY's run left out because their source wasn't in yet (an email
    # tracker's .xlsx hadn't landed) — read from the status file so the success
    # line reports exactly what posted, not a blanket "all N". Stale/absent → none.
    _omitted_today: list = []
    try:
        _sf = WORKSPACE / "output/tableau_screenshots/_posted_today.json"
        if _sf.exists():
            _d = json.loads(_sf.read_text())
            if _d.get("date") == dt.date.today().isoformat():
                _omitted_today = list(_d.get("omitted") or [])
    except Exception:
        _omitted_today = []
    trackers = "\n".join(
        f"{i}. {p['title']}" + ("  — posts ~7am" if _pages.is_late(p) else "")
        for i, p in enumerate(_display, 1))
    late_names = ", ".join(p["title"] for p in late)
    # Prose form (one line, for the card description sentence).
    channels = ", ".join(_sp.ORG_LABEL[o] for o in _sp.ORGS)
    # Bulleted form (one Slack channel per line, for the breakdown panel — the
    # panel is white-space:pre-wrap, so the newlines survive). An org whose label
    # covers two channels ("#a + #b") is split so each channel gets its own line.
    channel_bullets = "\n".join(
        f"• {name.strip()}"
        for o in _sp.ORGS
        for name in _sp.ORG_LABEL[o].split(" + "))
    return {
        "id": "tableau-screenshots",
        "name": "Tableau Country Trackers",
        "creator": "Megan",
        "emoji": "📸",
        "color": "#1F4E79",
        "category": "📊 Metrics",
        "description": (
            f"Posts {len(_display)} Tableau country sales trackers as images "
            "daily into a 'Tableau Country Trackers M/D/YYYY' thread in every "
            f"sales channel: {channels}. The boards are country-wide, so all "
            "channels get identical images from a single capture (one Tableau "
            f"login) in the 4am run. Replaces Jolie's manual tracker post. "
            f"{late_names} is listed in the thread from the start; its image "
            "follows once its data refreshes (~7am)."),
        "breakdown": (
            "WHAT IT DOES\n"
            f"Grabs these {len(_display)} Tableau country trackers as images and "
            "posts them into today's dated thread in every channel below (the "
            f"first {len(morning)} in the 4am run; {late_names} follows ~7am).\n\n"
            f"TRACKERS\n{trackers}\n\n"
            f"CHANNELS\n{channel_bullets}\n\n"
            "B2B BOX (POSTS ~7AM)\n"
            f"{late_names}'s numbers don't settle until its Tableau data "
            "refreshes (~7am) — that tracker is posted then.\n\n"
            "IF A CHANNEL MISSES\n"
            "The card shows a per-channel checklist after the run. Use "
            "'Retry failed only' to re-post just the channels that missed, or "
            "the per-channel buttons under More actions."),
        "assignees": ["Lucy 3"],  # runner since 2026-08-22 (schedule_config machine field is the source of truth)
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 12,
        },
        "checklist": [],
        "post_run": {
            "message_success": (
                (f"✅ Tableau Country Trackers posted — all {len(morning)} tracker "
                 f"screenshots in the dated thread in every channel. "
                 f"({late_names} follows on its own card once its data lands.)")
                if not _omitted_today else
                (f"✅ Tableau Country Trackers posted — "
                 f"{len(morning) - len(_omitted_today)} of {len(morning)} boards in "
                 f"the dated thread in every channel. Not posted this run "
                 f"(source not in yet): {', '.join(_omitted_today)} — reposts "
                 f"automatically once it lands. "
                 f"({late_names} follows on its own card once its data lands.)")),
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
            # Drives the ✅/❌ per-channel checklist on the card (_channel_status).
            "channel_status_file": "output/tableau_screenshots/_posted_today.json",
        },
        "actions": [
            {
                "label": "Post Today's Trackers (all channels)",
                "icon": "▶",
                "primary": True,
                "help": (f"Captures the {len(morning)} Tableau trackers once and "
                         f"posts them to every channel. Needs a warm Tableau "
                         f"session (best run on the mini). {late_names} is not "
                         f"included — use its own card."),
                "module": "automations.tableau_screenshots.run",
                "args_fn": lambda: [],
            },
        ] + [
            {
                # No help text — the label says it. It's just a full re-run of
                # that one channel (Megan 2026-07-14).
                "label": f"Re-post {_sp.ORG_LABEL[o]}",
                "icon": "🔁",
                "module": "automations.tableau_screenshots.run",
                # default-bind o — a bare closure would capture the loop variable
                # and every button would post to the LAST org.
                "args_fn": (lambda org=o: ["--orgs", org, "--replace"]),
            }
            for o in _sp.ORGS
        ],
    }


def _tableau_box_card() -> dict:
    """The late half of the tracker set: B2B Box, posted once its data is in.

    Same code, same channels, same thread as _tableau_trackers_card — only the
    timing differs, so everything here is derived from the same pages.py/
    ORG_CHANNELS source rather than restated. Its own card because it's its own
    run with its own outcome: Box failing at 7am and the 5:00 batch failing are
    different problems, and one pill couldn't tell Megan which happened."""
    from automations.tableau_screenshots import slack_post as _sp
    from automations.tableau_screenshots import pages as _pages
    late = [p for p in _pages.PAGES if _pages.is_late(p)]
    late_names = ", ".join(p["title"] for p in late)
    channels = ", ".join(_sp.ORG_LABEL[o] for o in _sp.ORGS)
    channel_bullets = "\n".join(
        f"• {name.strip()}"
        for o in _sp.ORGS
        for name in _sp.ORG_LABEL[o].split(" + "))
    return {
        "id": "tableau-screenshots-box",
        "name": "Tableau Country Trackers — Box (late)",
        "creator": "Megan",
        "emoji": "📦",
        "color": "#1F4E79",
        "category": "📊 Metrics",
        "description": (
            f"Adds the {late_names} image to the morning's "
            "'Tableau Country Trackers M/D/YYYY' thread in every sales channel "
            f"({channels}) — but only once Box's Tableau data has actually "
            "refreshed. Box's numbers don't settle until ~7am, so it used to "
            "post yesterday's figures with the 5:00 batch."),
        "breakdown": (
            "WHAT IT DOES\n"
            f"Captures {late_names} and adds it to the tracker thread that "
            "already went out at 5:00 — same thread, every channel below. The "
            "thread's header lists Box from 5:00, marked as still coming; this "
            "run posts the image and clears that note.\n\n"
            "WHEN IT RUNS\n"
            "Not on a clock. It waits for Box's Tableau data to actually land "
            "and posts within ~12 minutes of that — usually before 7am, and by "
            "8am at the latest even if the check can't confirm (it posts "
            "anyway rather than skip). It's the same readiness check the Org "
            "Sales Board already waits on.\n\n"
            f"CHANNELS\n{channel_bullets}\n\n"
            "IF A CHANNEL MISSES\n"
            "Per-channel checklist, same as the main tracker card. Re-running "
            "is safe — a channel that already has today's Box image is left "
            "alone."),
        "assignees": ["Lucy 3"],  # runner since 2026-08-22 (schedule_config machine field is the source of truth)
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": (
                f"✅ {late_names} posted into today's tracker thread in every "
                "channel."),
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
            "channel_status_file": "output/tableau_screenshots/_posted_today_box.json",
        },
        "actions": [
            {
                "label": "Post Box Now (all channels)",
                "icon": "▶",
                "primary": True,
                "help": ("Captures Box and adds it to today's tracker thread in "
                         "every channel. Only do this if Box's data is in — "
                         "before ~7am it's still yesterday's numbers. Safe to "
                         "re-run; channels that already have it are skipped."),
                "module": "automations.tableau_screenshots.run",
                "args_fn": lambda: ["--late-only"],
            },
        ] + [
            {
                "label": f"Re-post Box to {_sp.ORG_LABEL[o]}",
                "icon": "🔁",
                "module": "automations.tableau_screenshots.run",
                # default-bind o — a bare closure would capture the loop variable
                # and every button would post to the LAST org.
                "args_fn": (lambda org=o: ["--late-only", "--orgs", org,
                                           "--replace"]),
            }
            for o in _sp.ORGS
        ],
    }
AUTOMATED_REPORTS = [
    # 🏆 TEMP COMPETITION CARD — August Owner Showdown (Raf, 2026-07-29).
    # Two $5,000 battles for August only: personal new-internet sales (daily)
    # + rep-count growth (Sundays). Remove this card after 2026-08-31. Pill is
    # forced BRIGHT YELLOW (temp) via the calstat CSS override below (search
    # 'owner-showdown__calstat'); it still turns GREEN when the day's run
    # succeeds. Fills the KTS tab; Sunday digest emails Raf only.
    # Intraday knock boards — its own LaunchAgent (com.alphalete.knocks-intraday)
    # ticking every 5 min, NOT the 4am batch, so self_scheduled puts it under
    # ⏰ TIME SET REPORTS with its real times on the pill (Megan 2026-08-25).
    # CARD ID MUST SLUG-MATCH the wrapper's report_id (`knocks_intraday`), or
    # the resolver files its runs under a library card of its own and this card
    # says "no run logged" forever — see day_orchestrator.test_hub_card_ids.
    {
        "id": "knocks-intraday",
        "name": "Intraday Knock Updates 🚪",
        # Renders under the "Other Offices" divider on the schedule, below the
        # main-office run (Megan 2026-08-25). Every board it posts belongs to a
        # single office's own channel, which is exactly what that section is for.
        "category": "🏢 Other Offices",
        "creator": "Raf & Claude",
        "emoji": "🚪",
        # The knocks amber, same as the board it posts.
        "color": "#B45309",
        # Lucy 3: the rerun/overflow box, on Raf's accounts with
        # ownerville-creds.json already in place, so it impersonates the same
        # offices Lucy 1 does. Picked for load, not access — at 9 PM Lucy 1 is
        # holding the Jiraiya socket listener and has the 11 PM STF Field Check
        # right behind it, while Lucy 3 is idle. The job runs its OWN Chrome
        # profile, so the old one-warm-session-per-account rule doesn't bind
        # (superseded 2026-08-24: ownerville sessions parallelise).
        "assignees": ["Lucy 3"],
        "run_machine": "Lucy 3",
        "run_rerun_id": "knocks_intraday",
        "self_scheduled": True,
        # A PHASE CARD: each slot is its own phase, and the pill advances as
        # each one lands (Megan 2026-08-25: "this should also be a phase card -
        # changing color on each pass"). phase_runs counts DISTINCT Report
        # NAMES, and deploy/knocks_intraday.sh names every publish after the
        # slot that fired ("… — First Knocks (2 PM)" / "— Money Lap (5:15 PM)" /
        # "— End of Day (9 PM)").
        #
        # THREE, NOT FOUR. The 9 PM slot fires as TWO ticks — 21:00 Eastern
        # (=20:00 Central) for aya/hammad/salik/nii, then 21:00 Central for the
        # rest — but that is ONE phase reaching two timezones. Both ticks publish
        # the same name, so they count once. That is also what makes the count
        # immune to a re-run of any single slot, and to the org ever collapsing
        # into one timezone (a plain pass-counter would have needed 4, then 3).
        "daily_runs": 3,
        "phase_runs": True,
        "schedule": {
            "frequency": "daily",
            "time": "9:00 PM",
            "time_label": "2 PM · 5:15 PM · 9 PM office-local",
            "estimated_minutes": 12,
        },
        "description": (
            "Knock boards for the CURRENT day, posted to each office's own "
            "channel at its OWN local 2 PM, 5:15 PM and 9 PM. Every office "
            "gets the 9 PM board; the two afternoon slots are Cody's only. "
            "The morning board still re-pulls the same day from scratch, "
            "because reps keep knocking after 9."
        ),
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Ticks every 5 minutes and asks which offices are owed a "
            "board **right now in their own timezone** — most ticks do nothing "
            "at all and open no browser.\n"
            "**•** A due office gets its **current day** pulled from "
            "Ownerville and posted as the same amber **Total Knocks** board "
            "the morning thread uses, in that office's own channel.\n\n"
            "THE THREE SLOTS (office-local, Mon–Sat)\n"
            "**•** **2:00 PM — First Knocks** and **5:15 PM — Money Lap**: "
            "**Cody's office only** (he asked for these two).\n"
            "**•** **9:00 PM — End of Day**: **every enrolled office**, each "
            "at its own 9 PM. Four offices are Eastern, so the 9 PM run rolls "
            "across the timezones over about an hour rather than firing once.\n"
            "**•** A slot missed by more than 15 minutes is **skipped, not "
            "posted late** — a 2 PM board landing at 6 PM is worse than none.\n\n"
            "WHAT KEEPS IT HONEST\n"
            "**•** **Tonight's pull is never reused tomorrow.** It writes only "
            "to `output/knocks_intraday/`, never the caches the morning board "
            "reads, so the morning re-collects the day and picks up every "
            "knock that landed after 9.\n"
            "**•** Each board is stamped in the office's **own** abbreviation "
            "(CST / EST) — a Michigan board reading 9 PM CST would be an hour "
            "off its own evening.\n"
            "**•** **Never posts blank** — an office with no rows is skipped "
            "and named in the log, never posted as an empty board.\n"
            "**•** One office failing, or one channel refusing an image, does "
            "not stop the others.\n\n"
            "WHO GETS IT\n"
            "**•** Everyone enrolled in **D2D metrics**, so enrolling an "
            "office enrols it here too.\n"
            "**•** **Isaiah is excluded** (wireless-only: his gaps-only rows "
            "still render as 'no rows'). The reason prints in the log nightly "
            "so the exclusion can't quietly outlive the bug.\n"
            "**•** **Hammad and Salik post two separate boards** into the "
            "channel they share — deliberate: each owner is measured on his "
            "own reps, so the totals on each are per owner.\n"
            "**•** **Trang** posts with her own FRESH SUCCESS workspace token; "
            "if that file isn't on the machine she's skipped rather than "
            "posted with Lucy's."
        ),
        "post_run": {
            "message_success": "✅ Intraday Knocks — every due office posted.",
            "message_failed": "❌ Intraday Knocks failed — see the log above.",
        },
    },
    {
        "id": "owner-showdown",
        "name": "August Owner Showdown 🏆",
        "creator": "Raf & Claude",
        "emoji": "🏆",
        # Bright yellow accent — temporary competition card.
        "color": "#EAB308",
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "owner_showdown",
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"
                      "?gid=893154737#gid=893154737"),
        # It does NOT run in the 4am batch — it has its own agent,
        # com.alphalete.owner-showdown-daily, firing at 09:00. self_scheduled
        # puts it under ⏰ TIME SET REPORTS with its real time on the pill
        # instead of sitting in the morning batch claiming "4 AM"
        # (Megan 2026-08-19).
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "9:00 AM",
            "time_label": "9 AM",
            "estimated_minutes": 3,
        },
        "description": (
            "August-only competition tracker. Fills the KTS tab daily: each "
            "owner's personal NEW-INTERNET sales (daily) and active rep-count "
            "growth (Sundays), both sorted highest→lowest. Sunday digest emails "
            "Raf the standings. $5,000 to each of the two winners."
        ),
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** **Personal Sales** — every new-internet sale in each owner's "
            "own codes (Aug 1–31), pulled daily from Tableau and written into "
            "the KTS 'Personal Production' table. 0 entered on a day with no "
            "sale. TOTALS = month-to-date, sorted most→least.\n"
            "**•** **Rep Count Growth** — active rep count pulled on Sundays "
            "(8/2, 8/9, 8/16, 8/23, 8/30) into the 'Rep Count' table. "
            "TOTALS = growth vs the 8/2 baseline, sorted most→least.\n"
            "**•** **Sunday email** — standings digest to Raf only, first Sun "
            "Aug 2, last Sun Aug 30.\n"
            "**•** Temp card — retired after Aug 31."
        ),
        "post_run": {
            "message_success": "✅ Owner Showdown updated — KTS tab filled and sorted.",
            "message_failed": "❌ Owner Showdown run failed — see the log above.",
        },
        "checklist": [],
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Pulls the latest numbers and refills the KTS competition tables now.",
                "module": "automations.owner_showdown.run",
                "args_fn": (lambda: []),
            },
        ],
    },
    # 🏢 Office Operations — New-Hire Swag Texts. Renders a custom upload →
    # preflight → send UI via the report-id hook in _render_report_card (not
    # the standard checklist/run-button flow). `actions` is present only to
    # satisfy the card schema; it's never used.
    {
        "id": "swag-welcome",
        "name": "New-Hire Swag Texts",
        "creator": "Megan & Claude",
        "emoji": "🎁",
        "color": "#6C5CE7",
        # 📲 Ops category → renders under the "OPS" divider on its day (not the
        # timed/morning-batch sections), so NO run-time is shown — it's a manual
        # task, not a scheduled auto-run.
        "category": "📲 Ops",
        "assignees": ["Office Operations"],
        # Manual weekly task: run Friday to text next Monday's new hires. The
        # weekly schedule just surfaces it on Friday's tile; self_scheduled +
        # hide_schedule keep it out of the 4am batch, the due-today counter, and
        # any time/DUE pills (a human runs it on demand, no fixed time).
        "self_scheduled": True,
        "hide_schedule": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [4],   # Friday
            "estimated_minutes": 10,
        },
        "description": (
            "Upload the Friday new-hire roster screenshot → review names & "
            "phone numbers → text each hire a welcome message with their name "
            "handwritten on the swag-package card. Sends via iMessage from "
            "whatever machine runs the Hub."
        ),
        "actions": [
            {"label": "Open", "args_fn": (lambda: []), "primary": True},
        ],
    },
    {
        "id": "interview-audit-bot",
        "name": "2nd Round Interview Auditor — AO (24/7)",
        "creator": "Raf & Claude",
        "emoji": "🐺",
        # Amber = an ONGOING self-running job, matching the other continuous Ops
        # cards (sara-plus-issues, rc-autoread, bg-check-sync, resume-pushing).
        "color": "#F59E0B",
        "category": "📲 Ops",
        "assignees": ["Lucy 1"],
        # The card's link opens the live scorecard (public, no login).
        "sheet_url": "https://raffi127-ctrl.github.io/scorecard-9f3kx7q2/",
        "description": "Reps DM their 2nd-round interview recording → Gemini grades it → scored PDF back in ~90 sec. Keeps a live scorecard (office & rep rankings) and DMs Raf a daily 2 PM PDF with a retire/bring-back picker.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** A rep drops their 2nd-round interview recording in Slack → the "
            "bot grades it against our 11-frame framework and DMs back a scored "
            "PDF (Posture / D2D / Pay / Overall) in **~60–90 sec**.\n"
            "**•** Before sending a score it asks the rep their **owner**, so every "
            "submission is credited to the right office.\n"
            "**•** Keeps a **live scorecard** — office & rep rankings, submissions, "
            "and the weekly trend — always current:\n"
            "https://raffi127-ctrl.github.io/scorecard-9f3kx7q2/\n"
            "**•** DMs Raf a **daily 2 PM PDF** of the scorecard, with a "
            "**manage-reps picker**: retire reps who've left, or bring a retired "
            "rep back with all their data.\n"
            "**•** DMs Raf a **6 PM per-owner digest** — one PDF per office/ICD "
            "(labeled up top) bundling all of that office's scorecards from the "
            "day (office sends 5 → all 5 in one PDF).\n"
            "**•** A retired rep who submits again returns automatically, starting "
            "fresh at 1 submission.\n\n"
            "WHEN IT RUNS\n"
            "**Continuously, 24/7** on Lucy 1 (its own LaunchAgent — separate from "
            "the 4 AM orchestrator). The daily digest fires at **2 PM Central**. A "
            "quiet card is the *normal, healthy* state."
        ),
        "assignee_note": "Runs 24/7 on Lucy 1 (the mini) as its own service, independent of the 4 AM orchestrator. Not a Hub-run report — nothing to trigger from here.",
        # Continuous service: self_scheduled + hide_schedule keep it out of the
        # 4am batch, the due-today counter, and time/DUE pills (no single run time).
        "self_scheduled": True,
        "hide_schedule": True,
        "schedule": {
            "frequency": "daily",
            "time": "2:00 PM",
            "time_label": "24/7 · 2 PM digest",
            "estimated_minutes": 1,
        },
        "checklist": [],
    },
    {
        "id": "interview-audit-bot-colten",
        "name": "2nd Round Interview Auditor — SSO (24/7)",
        "creator": "Colten & Claude",
        "emoji": "🎙️",
        # Amber = an ONGOING self-running job, matching the other continuous Ops
        # cards. Second workspace instance of the audit bot (Colten's Slack).
        "color": "#F59E0B",
        "category": "📲 Ops",
        "assignees": ["Lucy 1"],
        # The card's link opens Colten's live scorecard (public, no login).
        "sheet_url": "https://raffi127-ctrl.github.io/colten-scorecard-x8k3/",
        "description": "Colten's workspace instance. Reps DM their 2nd-round interview recording → Gemini grades it → scored PDF back in ~90 sec. Keeps a live scorecard (office & rep rankings) and DMs Colten a daily 2 PM PDF with a retire/bring-back picker.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Same bot as the main 2nd Round Interview Auditor, running as its "
            "own isolated instance in **Colten's Slack workspace** (separate roster, "
            "scorecard, and tokens).\n"
            "**•** A rep DMs their 2nd-round interview recording → the bot grades it "
            "against our 11-frame framework and DMs back a scored PDF (Posture / D2D "
            "/ Pay / Overall) in **~60–90 sec**.\n"
            "**•** Before sending a score it asks the rep their **owner**, so every "
            "submission is credited to the right office.\n"
            "**•** Keeps a **live scorecard** — office & rep rankings, submissions, "
            "and the weekly trend — always current:\n"
            "https://raffi127-ctrl.github.io/colten-scorecard-x8k3/\n"
            "**•** DMs **Colten** a **daily 2 PM PDF** of the scorecard, with a "
            "**manage-reps picker**: retire reps who've left, or bring a retired "
            "rep back with all their data.\n"
            "**•** DMs Colten a **6 PM per-owner digest** — one PDF per office/ICD "
            "(labeled up top) bundling all of that office's scorecards from the "
            "day (office sends 5 → all 5 in one PDF).\n"
            "**•** A retired rep who submits again returns automatically, starting "
            "fresh at 1 submission.\n\n"
            "WHEN IT RUNS\n"
            "**Continuously, 24/7** on Lucy 1 (its own LaunchAgent — separate from "
            "the 4 AM orchestrator). The daily digest fires at **2 PM Central**. A "
            "quiet card is the *normal, healthy* state."
        ),
        "assignee_note": "Runs 24/7 on Lucy 1 (the mini) as its own service in Colten's workspace, independent of the 4 AM orchestrator. Not a Hub-run report — nothing to trigger from here.",
        # Continuous service: self_scheduled + hide_schedule keep it out of the
        # 4am batch, the due-today counter, and time/DUE pills (no single run time).
        "self_scheduled": True,
        "hide_schedule": True,
        "schedule": {
            "frequency": "daily",
            "time": "2:00 PM",
            "time_label": "24/7 · 2 PM digest",
            "estimated_minutes": 1,
        },
        "checklist": [],
    },
    {
        "id": "due-diligence-bot",
        "name": "Due Diligence Bot — Jiraiya (24/7)",
        "creator": "Raf & Claude",
        "emoji": "🐸",
        # Amber = ongoing self-running job, like the other continuous Ops bots.
        "color": "#F59E0B",
        "category": "📲 Ops",
        "assignees": ["Lucy 1"],
        # The card's link opens the DD log sheet (one tab per ICD).
        "sheet_url": "https://docs.google.com/spreadsheets/d/1RB07z5xmXBzFgKPRmbvqsvbFJ4yymrsk2z0tkMeCbpQ/edit",
        "description": "Type /dd in Slack → fill in ICD, leader & team → Jiraiya pulls their last 8 weeks of fiber, wireless, cancel & churn from Tableau and DMs back a rendered 3-chart image, logging it to the ICD's tab. The same bot also answers /knocks: pick an office and a day — or a stretch of days — and get that knock board back in a DM, with Chan's totals on it for comparison.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Any leader types **/dd** in Slack → a popup opens (ICD / Leader "
            "/ Team) → hit **Summon Jiraiya**.\n"
            "**•** Jiraiya pulls the team's **last 8 weeks** of New Internet + "
            "Wireless sales, cancel rates, and churn from Tableau, and **DMs back "
            "a 3-chart image** (New INT / Wireless / Total Sales) for review.\n"
            "**•** Logs the block to that **ICD's tab** in the DD sheet — newest on "
            "top, older pulls scroll down (a running log, never erased).\n"
            "**•** Names are matched loosely (short → Tableau names); any it can't "
            "match are flagged so you can fix the spelling.\n"
            "**•** Replies only to **you** in a DM — never posts in the channel.\n\n"
            "ALSO: /knocks\n"
            "**•** Type **/knocks** → pick **whose office** and **which day** "
            "(defaults to yesterday) → the knock board comes back in a DM, the "
            "same one the morning thread posts.\n"
            "**•** A third box, **Through which day?**, is optional — leave it "
            "blank for a single day, or pick an end date to get one board "
            "covering the whole stretch (counts added up, up to 31 days).\n"
            "**•** Usually instant: it answers from what the morning run already "
            "pulled. Only an older day needs a live Ownerville pull, and it waits "
            "its turn behind the scheduled reports instead of taking their "
            "session away.\n"
            "**•** Every board carries **Chan Park's totals** as a comparison "
            "line above the office's own, the same way the morning board "
            "does.\n"
            "**•** A **wireless office** comes back as a TeleMapper Knocks "
            "board — knock times and gaps, no knock counts, because its reps "
            "don't disposition and Ownerville has no counts to give. One "
            "board, not two.\n"
            "**•** An office we have no Ownerville access to says so plainly — "
            "that one is a permissions gap, not a spelling mistake.\n\n"
            "WHEN IT RUNS\n"
            "**Continuously, 24/7** on Lucy 1 (its own LaunchAgent, separate from "
            "the 4 AM orchestrator). A nightly **3 AM** pre-harvest caches the data "
            "so requests come back in seconds. A quiet card is the normal, healthy "
            "state."
        ),
        "assignee_note": "Runs 24/7 on Lucy 1 (the mini) as its own Socket Mode service, independent of the 4 AM orchestrator. Triggered by /dd or /knocks in Slack — nothing to run from here.",
        # Continuous service: keep it out of the 4am batch + time/DUE pills.
        "self_scheduled": True,
        "hide_schedule": True,
        "schedule": {
            "frequency": "daily",
            "time": "3:00 AM",
            "time_label": "24/7 · 3 AM harvest",
            "estimated_minutes": 1,
        },
        "checklist": [],
    },
    {
        # Promoted from an auto-registered library row (Megan 2026-08-19) so it
        # renders like the other Ops cards — the library path does not apply a
        # card's `color`, which is why it sat white next to the amber ones.
        "id": "enrollment_pending_check",
        # Cadence in the name, same pattern as Sara+ / RingCentral above.
        "name": "Pending Enrollments Check (Hourly)",
        "creator": "Megan & Claude",
        "emoji": "📋",
        # Amber = an ONGOING self-running job, matching the other continuous Ops
        # cards (sara-plus-issues, rc-autoread, stf-field-check, bg-check-sync).
        "color": "#F59E0B",
        # 📲 Ops category → renders under the "OPS" divider.
        "category": "📲 Ops",
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "enrollment_pending_check",
        "description": "Safety net for office onboarding — every hour from 9 AM to 10 PM it checks the 'Office Onboarding' sheet and posts to the corrections channel if an enrollment is sitting un-applied. A quiet card is the normal, healthy state.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Reads the **Office Onboarding** sheet and looks for an "
            "enrollment that has been submitted but never applied.\n"
            "**•** If it finds one, it posts to the corrections channel so it "
            "gets picked up the same day.\n"
            "**•** Finds nothing → says nothing. It never writes anything.\n\n"
            "WHY IT EXISTS\n"
            "Section EDITS (Thread Builder) sync themselves each morning, but a "
            "BRAND-NEW office needs a reviewed `office_onboarding.apply --write` "
            "plus a commit — it rewrites the committed registry and "
            "schedule_config, so it is deliberately NOT auto-applied at 4am. "
            "This is what stops a new office sitting unnoticed in the meantime. "
            "Apply the flagged ones via the **apply_enrollments** handle.\n\n"
            "WHEN IT RUNS\n"
            "**Hourly, 9 AM–10 PM**, on its own LaunchAgent "
            "(com.alphalete.enrollment-pending-hourly). It used to run once in "
            "the 4am batch, which meant an enrollment added at 9:05am waited a "
            "full day to be noticed (Megan 2026-08-19). Nothing overnight — a "
            "2am enrollment is caught by the 9 AM pass."
        ),
        "assignee_note": "Runs unattended on Lucy 1 (the mini) as a LaunchAgent. Nothing to run from here.",
        # Hourly self-runner: self_scheduled + hide_schedule keep it out of the
        # 4am batch, the due-today counter, and any time/DUE pills — there is no
        # single run time to show (same treatment as sara-plus-issues).
        "self_scheduled": True,
        "hide_schedule": True,
        "schedule": {
            "frequency": "daily",
            "time": "9:00 AM",
            "time_label": "hourly 9 AM–10 PM",
            "estimated_minutes": 1,
        },
        "checklist": [],
    },
    {
        "id": "sara-plus-issues",
        # Cadence in the name, same as the RingCentral Auto-Read card. The
        #   are non-breaking spaces so "(Q 5 Min)" wraps as ONE clean unit
        # onto line 2 of the This Week strip pill instead of breaking mid-phrase.
        "name": "Sara+ Issue Escalation (Q 5 Min)",
        "creator": "Raf & Claude",
        "emoji": "🚨",
        # Amber = an ONGOING self-running job, matching the other continuous Ops
        # cards (rc-autoread, stf-field-check, bg-check-sync, resume-pushing).
        "color": "#F59E0B",
        # 📲 Ops category → renders under the "OPS" divider.
        "category": "📲 Ops",
        "assignees": ["Lucy 1"],
        "description": "Watches #saraplus-issues on Slack — when anyone posts a screenshot of a Sara+ problem, it emails Sara+ support automatically with the screenshots attached, then replies ✅ in the thread.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Checks the **#saraplus-issues** Slack channel **every 5 "
            "minutes, 24/7** (nights included — that's when an outage hurts "
            "most).\n"
            "**•** When anyone in that channel posts screenshot(s) of a Sara+ "
            "problem, it emails **support@saraplus.com** — subject "
            "**Sara+ Issue — <date>**, CC'ing Raf, Alphalete Marketing, and "
            "Twaddle.\n"
            "**•** The email body is **exactly what the person typed** "
            "(spelling/grammar tidied, wording never changed), and **every** "
            "screenshot on that post is attached.\n"
            "**•** Replies in the thread with a ✅ confirming the email went "
            "out, so the reporter knows it's handled.\n"
            "**•** Remembers what it already sent, so an issue is never "
            "emailed twice.\n\n"
            "HOW TO POST AN ISSUE\n"
            "Put the note **and** the screenshots in **ONE message** — a "
            "message with the pictures added as a thread reply underneath "
            "won't be read correctly.\n\n"
            "WHEN IT RUNS\n"
            "**Continuously, every 5 minutes.** A quiet card is the *normal, "
            "healthy* state — it only records activity when an issue was "
            "actually escalated."
        ),
        "assignee_note": "Runs unattended on Lucy 1 (the mini) as a LaunchAgent.",
        # Continuous 5-min poller: self_scheduled + hide_schedule keep it out of
        # the 4am batch, the due-today counter, and any time/DUE pills (there's
        # no single run time to show).
        "self_scheduled": True,
        "hide_schedule": True,
        "schedule": {
            "frequency": "daily",
            # Runs every 5 min around the clock, so a bare time would read as if
            # it fires once. time_label shows the real window at a glance (same
            # pattern as rc-autoread); schedule.time stays the sortable start
            # (midnight, since there's no start/stop window) for card ordering.
            "time": "12:00 AM",
            "time_label": "24/7",
            "estimated_minutes": 1,
        },
        # The dedupe state file is PER-MACHINE, so a laptop run could re-send an
        # escalation the mini already sent. Route any Hub "play" to Lucy 1 via
        # the mini-control queue so it always uses the mini's state.
        "run_machine": "Lucy 1",
        "run_rerun_id": "sara_down",
        "checklist": [],
        "post_run": {
            "message_success": "✅ Checked #saraplus-issues. Any new screenshot posted there has been emailed to Sara+ support.",
            "message_failed": "❌ Check failed. See the log above — the 5-minute job keeps running regardless.",
        },
        "actions": [
            {
                "label": "Check Now",
                "icon": "▶",
                "primary": True,
                "help": "Checks the channel right now instead of waiting for the next 5-minute run. Emails Sara+ support if a new screenshot is waiting.",
                "module": "automations.sara_down.run",
                "args_fn": (lambda: []),
            },
        ],
    },
    {
        "id": "recruiting",
        "name": "ATT Program - Focus Report (Raf)",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#FF6B6B",
        "category": "🎯 Recruiting",
        "description": "Pulls funnel metrics from ApplicantStream, fills the mass-report Sheet across ~52 ICD office tabs.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Provides a **week-over-week** overview of the recruiting "
            "numbers for selected ICDs.\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the most recently finished week.\n\n"
            "TO ADD AN ICD\n"
            "**1.**  Add a tab and label it the ICD's name — it must match "
            "the **AppStream name** exactly.\n"
            "**2.**  Make sure the **rcaptain** AppStream login has access "
            "to that ICD.\n"
            "✅  Claude auto-adds the template and fills in that ICD's data "
            "on the next run.\n\n"
            "IF AN ICD IS SKIPPED\n"
            "It most likely isn't in AppStream — check that the **rcaptain** "
            "login can see it."
        ),
        # Deep-links to the Focus Report tab this run fills (same workbook as
        # SHEET_URL; inline so the shared constant / Financial Report card
        # keep their own link).
        "sheet_url": SHEET_URL + "?gid=845564380#gid=845564380",
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            # Runs in the Monday 4am orchestrator flow (att_focus_raf), not at a
            # fixed clock — show the batch label, not a set time (Megan 2026-07-28).
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 15,
        },
        # Fully unattended via patchright (rcaptain AppStream + ownerville
        # Tableau) — no pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Recruiting report run complete — the rcaptain login reaches every ICD, so it's all done in one run.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda: ["--week", _last_completed_we_sunday().isoformat()],
            },
            {
                "label": "Backfill Last 10 Weeks (one office)",
                "icon": "🔁",
                "needs_text": True,
                "text_label": "Office tab name (exact match)",
                "help": "Fill any empty cells in the last 10 weeks for ONE office. Won't overwrite existing data.",
                "module": "automations.recruiting_report.backfill_blanks",
                "args_fn": lambda name: ["--weeks", "10", "--only", name],
            },
            {
                "label": "Run a Specific Past Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick a WE Sunday to fill",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d: ["--week", (d - dt.timedelta(days=7)).isoformat()],
            },
            {
                "label": "Run for One Office (pick a week)",
                "icon": "🎯",
                "needs_date": True,
                "needs_text": True,
                "text_label": "Office tab name (exact match)",
                "help": "Just refill ONE office's tab for any week. Pick the WE Sunday + type the office tab name.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d, name: ["--week", (d - dt.timedelta(days=7)).isoformat(), "--only", name],
            },
        ],
    },
    {
        "id": "recruiting-carlos",
        "name": "Carlos 1on1s - Focus Report",
        "creator": "Megan",
        "emoji": "📊",
        "color": "#A78BFA",
        "category": "🎯 Recruiting",
        "description": "Pulls B2B funnel + OPT metrics from ApplicantStream + Tableau, fills Carlos's 27-ICD focus-report Sheet.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Recruiting pull (APPS / Total Applies / Retention / "
            "1st & 2nd Booked / etc.) from AppStream\n"
            "**•** OPT metrics (Active Headcount, Sales by product, "
            "AVG Apps, Scorecard Ranking, etc.) from Tableau\n"
            "**•** Cancel Rate, Activation %, Churn buckets, Penetration "
            "Rate, Direct Deposit, Personal Production from Tableau\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the just-ended week's column "
            "(WE Sunday).\n\n"
            "TO ADD AN ICD\n"
            "**1.**  Add a tab named the ICD's exact AppStream name.\n"
            "**2.**  Make sure the **CarlosNLR** AppStream login (Lucy 2) can "
            "see that ICD.\n"
            "✅  Next run auto-fills the new tab.\n\n"
            "IF DATA IS MISSING\n"
            "Cells marked **'No Data In Tableau'** mean the ICD is too "
            "new for that time window (e.g. 60/90/120-day churn). Cells "
            "marked **'No Access'** mean the Tableau session doesn't have "
            "permission to that ICD's data."
        ),
        "sheet_url": CARLOS_SHEET_URL,
        "assignees": ["Lucy 2"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 15,
        },
        # Fully unattended via patchright (rcaptain AppStream + ownerville
        # Tableau) — no pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Carlos report run complete — Recruiting pull + 6 Tableau OPT views + Personal Production all filled across 27 ICD tabs.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        # CAPTAINSHIP=Carlos switches the shared recruiting_report module
        # to Carlos's sheet/master tab/template/mapping file at import time.
        "env": {"CAPTAINSHIP": "Carlos"},
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "ONE run: recruiting pull + all 7 Carlos B2B OPT views.",
                # Chains recruiting (--no-opt) + each opt_phase_carlos B2B view
                # as its own subprocess (carlos_opt_all), so one bad view can't
                # abort the rest. The shared ATT opt_phase is NOT used — Carlos's
                # B2B owners aren't in those views (glitch 2026-06-01).
                "module": "automations.recruiting_report.carlos_opt_all",
                "args_fn": lambda: ["--week", _last_completed_we_sunday().isoformat()],
            },
            {
                "label": "Run a Specific Past Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick a WE Sunday to fill",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d: ["--week", (d - dt.timedelta(days=7)).isoformat(), "--no-opt"],
            },
            {
                "label": "Run for One ICD (pick a week)",
                "icon": "🎯",
                "needs_date": True,
                "needs_text": True,
                "text_label": "ICD tab name (exact match)",
                "help": "Just refill ONE ICD's tab for any week.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d, name: ["--week", (d - dt.timedelta(days=7)).isoformat(), "--only", name, "--no-opt"],
            },
        ],
    },
    {
        "id": "recruiting-alphalete-org",
        "name": "Alphalete Org 1on1s - Focus Report",
        "creator": "Megan",
        "emoji": "🌐",
        "color": "#10B981",
        "category": "🎯 Recruiting",
        "description": "Pulls recruiting + OPT metrics for the "
                       "rep-per-campaign tabs on the Alphalete Org sheet "
                       "(NDS / B2B / BOX / Retail / JE / Frontier).",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Recruiting pull (APPS / Total Applies / Retention / "
            "1st & 2nd Booked / etc.) from AppStream for every visible "
            "rep tab.\n"
            "**•** OPT / Personal Production from Tableau — the campaign "
            "OPT views (NDS / B2B / BOX / JE / Retail) plus Personal "
            "Production, for every rep tab.\n"
            "**•** Financial section — handled by the weekly Financial "
            "Pull card, which distributes uploaded workbooks to every "
            "matched ICD on this sheet too.\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the just-ended week's column.\n\n"
            "TO ADD A NEW REP\n"
            "**1.**  Create a tab named with the rep's exact AppStream "
            "name + ` - <CAMPAIGN>` suffix.\n"
            "**2.**  The campaign suffix tells the runner which template "
            "to clone (NDS Template / B2B Template).\n"
            "✅  Next run auto-fills the new tab.\n\n"
            "WHEN A REP RETIRES\n"
            "Just **hide the tab** in the Sheet. Runner auto-skips "
            "hidden tabs — no mapping edit needed."
        ),
        # Deep-links to this report's tab (same workbook as
        # ALPHALETE_ORG_SHEET_URL; inline so the shared constant / other cards
        # keep their own link).
        "sheet_url": ALPHALETE_ORG_SHEET_URL + "?gid=700355042#gid=700355042",
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 45,
        },
        # Fully unattended via patchright (rcaptain AppStream + ownerville
        # Tableau) — no pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Alphalete Org run complete — recruiting + all "
                               "OPT (NDS, BOX, JE, B2B, Retail) ran. Check the "
                               "per-step summary at the bottom of the log: any "
                               "step marked ❌ can be re-run from its own button. "
                               "Financial section is handled by the weekly "
                               "Financial Pull card.",
            "message_failed":  "❌ Run failed. Check the log above, fix the "
                               "issue, then run again.",
        },
        # CAPTAINSHIP=Alphalete-Org switches the shared recruiting_report
        # module to the Alphalete Org sheet/mapping at import time.
        "env": {"CAPTAINSHIP": "Alphalete-Org"},
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "ONE run: recruiting pull + all OPT (NDS, BOX, JE, B2B, "
                        "Retail) for the current week. Needs Report Chrome open + "
                        "logged into AppStream + ownerville.",
                # Chains recruiting (--no-opt) + every OPT module in sequence via
                # opt_all (Megan 2026-05-25: "chain them"). Each step is an
                # isolated subprocess so one failure can't abort the rest; the
                # OPT modules auto-target the current week, so only the
                # recruiting step needs --week.
                "module": "automations.alphalete_org_report.opt_all",
                "args_fn": lambda: ["--week", _last_completed_we_sunday().isoformat()],
            },
            {
                # Retail OPT - fills BOTH ICD sections on Boaktear's tab
                # (Akib = Boaktear Chowdhury + MJ = Amjad Malhas) plus the
                # shared Costco section. Pulls fresh from CHURNRATES/RETAILPULL,
                # SARAPLUSSALESSUMMARY, ABPCONVERSIONS, RETAILSALESSUMMARYBYCLUB.
                "label": "Run Retail OPT",
                "icon": "🛒",
                "help": "Fills the Retail OPT block on Boaktear's tab for BOTH "
                        "Akib + MJ sections: churn %, Next Up %, Extra/Premium "
                        "%, ABP %, Costco store wireless lines, Internet, and "
                        "Total New Lines. Needs the Reporting Chrome open.",
                "module": "automations.alphalete_org_report.opt_retail",
                "args_fn": lambda: [],
            },
            {
                # BOX OPT - fully automated (Tableau B2B BOX Energy daily
                # tracker, no email/upload needed), so it runs as part of
                # this report. Fills every ' - BOX' tab on each run.
                "label": "Run BOX OPT",
                "icon": "🔋",
                "help": "Fills the BOX OPT block on every ' - BOX' tab: "
                        "Active Selling Heads, Total Box CX's, AVG Kwh per "
                        "CX, AVG Sales per Leader, the shared National AVGs, "
                        "and Accepted %. Pulls fresh from the B2B BOX Energy "
                        "daily tracker (current week).",
                "module": "automations.alphalete_org_report.opt_box",
                "args_fn": lambda: [],
            },
            {
                # NDS OPT - fully automated (Tableau via patchright, no manual
                # Chrome). Fills every ' - NDS' tab's OPT block + rep chart.
                "label": "Run NDS OPT",
                "icon": "📡",
                "help": "Fills the NDS OPT block on every ' - NDS' tab: Active "
                        "Selling Heads, New Lines, AVG Apps/Headcount, Scorecard "
                        "Ranking, churn, Activation %, Cancel Rate, Total Leads, "
                        "Direct Deposit, Next Up/Extra %, plus the rep chart.",
                "module": "automations.alphalete_org_report.opt_nds",
                "args_fn": lambda: [],
            },
            {
                # JE OPT - fully automated (Tableau via patchright). Fills the
                # ' - JE' tab(s): per-store sales, totals, conversion, DD.
                "label": "Run JE OPT",
                "icon": "⚡",
                "help": "Fills the JE OPT block on every ' - JE' tab: per-store "
                        "sales, Total Sales, Store Count, AVG/Store, Conversion, "
                        "Personal Production, Direct Deposit.",
                "module": "automations.alphalete_org_report.opt_je",
                "args_fn": lambda: [],
            },
            {
                # B2B OPT - fully automated (ATTTRACKER-B2B via patchright).
                # Fills the ' - B2B' tab, mapping every metric by label.
                "label": "Run B2B OPT",
                "icon": "🏢",
                "help": "Fills the B2B OPT block on every ' - B2B' tab: rep "
                        "count, new internets/voice/wireless/new lines, total "
                        "apps + AVGs, scorecard ranking, cancel/activation/churn "
                        "rates, penetration, Direct Deposit.",
                "module": "automations.alphalete_org_report.opt_b2b",
                "args_fn": lambda: [],
            },
            {
                "label": "Run a Specific Past Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick a WE Sunday to fill.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d: ["--week", (d - dt.timedelta(days=7)).isoformat(),
                                      "--no-opt"],
            },
            {
                "label": "Run for One Rep (pick a week)",
                "icon": "🎯",
                "needs_date": True,
                "needs_text": True,
                "text_label": "Rep tab name (exact match, incl. campaign suffix)",
                "help": "Just refill ONE rep's tab for any week.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d, name: ["--week", (d - dt.timedelta(days=7)).isoformat(),
                                            "--only", name, "--no-opt"],
            },
        ],
    },
    {
        "id": "carlos-captainship-headcount",
        "name": "Carlos Captainship Headcount",
        "creator": "Maud",
        "emoji": "🧮",
        "color": "#FF6B6B",
        "category": "📊 Metrics",
        "description": "Adds this week's column to the 'Captainship Head count' tab of the All In One - CARLOS sheet — each active owner's Rep Count from Tableau, retotaled and sorted high→low — then DMs a 4-week screenshot to Carlos + Maud on Slack.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Inserts a fresh leftmost week column.\n"
            "**•** Fills each **active** owner's **Rep Count**, pulled live "
            "from Tableau.\n"
            "**•** DMs a screenshot of the past 4 weeks to **Carlos + Maud** "
            "on Slack (as Lucy).\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the just-ended week. Re-running the "
            "same week refreshes the numbers in place (no duplicate column).\n\n"
            "IF THE ROSTER CHANGES\n"
            "The run only fills the owners already listed (rows 2–12). If it "
            "prints a **⚠ NOT FOUND** owner, that person may have left "
            "Carlos' team — move+hide their row. To add a new owner, add a "
            "row with their short name; it fills on the next run."
        ),
        # Deep-links straight to the 'Captainship Head count' tab (the tab this
        # run writes to), not the workbook's default first tab.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1xQQLzE8mU-a4lpk1IK3WolTPlFxavuMzdK3jA7NGga8/edit"
                      "?gid=732054054#gid=732054054"),
        "assignees": ["Lucy 2"],
        # Runs on Lucy 2 (Carlos' Neo Laptop) — its Tableau session + the Monday
        # 7am launchd job (com.alphalete.carlos-captainship-headcount-mon) live
        # there. A Hub "play" from ANY machine routes the run to Lucy 2 via the
        # mini-control queue (run_rerun_id = the schedule_config id `rerun` resolves).
        "run_machine": "Lucy 2",
        "run_rerun_id": "carlos_captainship_headcount",
        # Self-running weekly launchd job: it doesn't report a per-day completion
        # to the Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": False,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 3,
        },
        # Tableau login is unattended (ownerville SSO via patchright) — no
        # pre-flight clicks needed.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship Headcount done — this week's column filled, total recomputed, owners sorted, and the 4-week screenshot DM'd to Carlos + Maud on Slack. Review any ⚠ roster flags in the log.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column from Tableau (idempotent — refreshes if it already exists), then DMs a 4-week screenshot to Carlos + Maud on Slack.",
                "module": "automations.carlos_captainship_headcount.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "raf-captainship-bonus",
        "name": "Raf Captainship Bonus",
        "creator": "Maud",
        "emoji": "💰",
        "color": "#E8612A",
        "category": "📊 Metrics",
        "description": "Adds this week's column to the 'Captainship Bonuses' tab of the Alphalete Org/Captainship Reports sheet — each rep's Total Activations + the team New Internet 60-day churn % and activation % from Tableau, recomputes Money Made, re-points the chart, and DMs the PDF to Raf, Dylan + Maud on Slack as Lucy.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Inserts a fresh leftmost week column (this past Sunday, "
            "e.g. `WE 7.5`).\n"
            "**•** Fills each **active** rep's **Total Activations** for Raf's "
            "team, plus the team **60-day churn %** and **activation %** "
            "(Rolling 4 Weeks).\n"
            "**•** Auto-syncs the roster: **adds** a row for a new rep and "
            "**hides** one who left the team.\n"
            "**•** DMs **Raf Captainship WE <date>.pdf** (4 weeks + chart) "
            "to Raf, Dylan + Maud on Slack.\n\n"
            "WHEN IT RUNS\n"
            "**Tuesdays.** Each run fills the just-ended week. Re-running the "
            "same week refreshes in place (no duplicate column)."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit?gid=450789281#gid=450789281"),
        "assignees": ["Lucy 1"],
        # Runs in Lucy 1's Tuesday 4am orchestrator flow, readiness-gated on the
        # CaptainsBonus week (grand activations > 0) with a 10am fail-open floor
        # so it's never later than its old send time (Megan 2026-07-28).
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1],  # Tuesday
            "time": "4 AM flow (out by 10am)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Raf Captainship Bonus done — column filled, roster synced, Money Made recomputed, chart re-pointed, PDF DM'd to Raf, Dylan + Maud on Slack.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column from Tableau, syncs the roster, and DMs the PDF to Raf, Dylan + Maud on Slack (idempotent — refreshes if it already exists).",
                "module": "automations.raf_captainship_bonus.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "stf-field-check",
        "name": "STF Field Check",
        "creator": "Raf",
        "emoji": "🚫",
        "color": "#F59E0B",
        # 📊 Metrics (not Ops): Ops-category cards are routed to the OPS
        # section regardless of self_scheduled, which kept this out of
        # ⏰ TIME SET REPORTS. It's a Sales Board data report, so Metrics
        # is both the right home and puts it in the 11 PM timed lineup.
        "category": "📊 Metrics",
        "description": "For the current day, finds the reps marked STF (Straight To Field) on the Sales Board and checks their ownerville Time Tracker knocks. Anyone who worked under 3 hours — or never showed — is switched from STF to X, so Raf's count of reps actually in the field stays honest.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Opens the current week's **Sales Board WE** tab and finds "
            "every rep whose day status reads **STF**.\n"
            "**•** Pulls that same day's **Time Tracker** (ownerville, Raf's "
            "view) and reads each rep's **First Knock** and **Last Knock**.\n"
            "**•** Worked time = Last Knock − First Knock. If it's **under "
            "3 hours** (or the rep has **no knocks** — never showed), the cell "
            "is changed from **STF** to **X**.\n"
            "**•** Only ever overwrites a cell that still says STF, and if a "
            "rep can't be found in Time Tracker it flags the closest name so a "
            "spelling miss can't wrongly mark someone X.\n\n"
            "WHEN IT RUNS\n"
            "**Every night at 11:00pm CST** for that day — late enough that "
            "reps are out of the field and the knocks are final, but before "
            "the 4am board post."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc/edit"),
        "assignees": ["Lucy 1"],
        # Ownerville is single-session and lives on the mini — a Time Tracker
        # scrape from any other machine evicts the session holder. So a Hub
        # "play" from ANY machine routes the run to Lucy 1 via the mini-control
        # queue (run_rerun_id = the schedule_config id `rerun` resolves there),
        # instead of spawning a laptop-local scrape.
        "run_machine": "Lucy 1",
        "run_rerun_id": "stf_field_check",
        # Self-running nightly launchd job on Lucy 1 (11pm CST), not the 4am
        # batch — show the run time on the tile and keep it out of the
        # "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "11:00 PM",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ STF Field Check done — any STF rep who worked under 3 hours (or never showed) was switched to X on the board.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "For today: flips STF→X on the Sales Board for any rep who worked under 3 hours or never showed. Writes to the board.",
                "module": "automations.stf_field_check.run",
                "args_fn": lambda: ["--write"],
            },
        ],
    },
    {
        "id": "carlos-captainship-bonus",
        "name": "Carlos B2B Captainship Bonus",
        "creator": "Maud",
        "emoji": "💰",
        "color": "#6AA84F",
        "category": "📊 Metrics",
        "description": "Adds this week's column to the 'Carlos B2B Captainship' tab of the All In One - CARLOS sheet — each rep's activations + the four churn / activation / non-payment metrics from Tableau, recomputes Money Made, re-points the chart, and DMs the PDF to Carlos + Maud on Slack.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Inserts a fresh leftmost week column (this past Sunday, "
            "e.g. `WE 7.5`).\n"
            "**•** Fills each **active** rep's **weekly activations** for "
            "Carlos' B2B team, plus the **team 0-30 churn %**, **Carlos' "
            "personal 0-30 churn %**, **31-60 activation %**, and "
            "**non-payment %**.\n"
            "**•** Auto-syncs the roster: **adds** a row for a new rep and "
            "**hides** one who left the team.\n"
            "**•** DMs **Carlos Captainship WE <date>.pdf** (5 weeks + "
            "chart) to Carlos + Maud on Slack.\n\n"
            "WHEN IT RUNS\n"
            "**Tuesdays.** Each run fills the just-ended week. Re-running the "
            "same week refreshes in place (no duplicate column)."
        ),
        # Deep-links to the 'Carlos B2B Captainship' tab this run writes to.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1xQQLzE8mU-a4lpk1IK3WolTPlFxavuMzdK3jA7NGga8/edit"
                      "?gid=310459982#gid=310459982"),
        "assignees": ["Lucy 2"],
        # Runs in Lucy 2's Tuesday 4am orchestrator flow, readiness-gated on the
        # Captain Team week (grand activations > 0) with a 10am fail-open floor
        # so it's never later than its old send time (Megan 2026-07-28).
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1],  # Tuesday
            "time": "4 AM flow (out by 10am)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Carlos B2B Captainship Bonus done — column filled, roster synced, Money Made recomputed, chart re-pointed, PDF DM'd to Carlos + Maud on Slack.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column from Tableau, syncs the roster, and saves the PDF (idempotent — refreshes if it already exists).",
                "module": "automations.carlos_captainship_bonus.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "daily-focus",
        "name": "Daily Recruiting Focus",
        "creator": "Megan",
        "emoji": "☀️",
        "color": "#4ECDC4",
        "category": "🎯 Recruiting",
        "description": "Per-ICD daily breakdown (Mon–Fri current week, last week, plus next-week scheduled) for every captainship tab — fills them all in one run.",
        "breakdown": (
            "WHAT IT DOES\n"
            "A day-by-day breakdown (Mon-Fri) of the recruiting numbers "
            "for **every ICD across all captainship tabs** — current "
            "week and last week, side by side. One run fills every tab.\n\n"
            "SLACK DMs\n"
            "After each captainship tab is filled, its screenshot is DM'd "
            "(as Lucy) to that captainship's private group DM — one image per "
            "3 owners, captioned *M/D/YY Daily Recruiting Focus Report*:\n"
            "• **Carlos** → Carlos, Elena Camargo, Valeria Rodea, Evelyn "
            "Sobrino, Maud Miller.\n"
            "• **Colten Wright** → Colten, Eveliz Wright, Valeria Zavala.\n"
            "• **Jairo Ruiz** → Jairo, Colten Wright, Analay Ruiz.\n"
            "A Slack hiccup on one tab is logged but never fails the run or "
            "blocks the other tabs' DMs.\n\n"
            "WEEKEND ROLLOVER\n"
            "Per Raf's rule, weekend numbers fold into the adjacent weekday:\n"
            "• **Sunday → Monday** (Sun + Mon counts combined into Mon's cell).\n"
            "• **Saturday → Friday** (Fri + Sat counts combined into Fri's cell).\n"
            "Tue/Wed/Thu pass through unchanged. Percentages get recomputed "
            "from the combined counts.\n\n"
            "COLUMN V IS THE LIST — ADD / REMOVE / REORDER\n"
            "The names in **column V** are the source of truth. Each run:\n"
            "• **Adds** a section for any name newly in col V (needs "
            "**rcaptain** AppStream access + an exact-match name).\n"
            "• **Deletes** the section for any name removed from col V.\n"
            "• **Reorders** the sections to match col V's order.\n\n"
            "IF SOMETHING MISSES\n"
            "If an ICD can't be pulled or a Slack DM doesn't send, the gap is "
            "posted to **#claudecorrections-and-requests** so it's caught."
        ),
        "sheet_url": DAILY_FOCUS_SHEET_URL,
        "assignees": ["Lucy 1"],
        "schedule": {
            # Weekly with weekdays [0..4] = Mon–Fri. (frequency 'daily' would
            # short-circuit and ignore the weekdays filter, so it'd appear
            # 7 days a week on the calendar.)
            "frequency": "weekly",
            "weekdays": [0, 1, 2, 3, 4],  # Mon–Fri (Megan 2026-06-07)
            "time": "4 AM flow (when data's ready)",  # 7am CST (Eve)
            "estimated_minutes": 10,
        },
        # Fully unattended via patchright (rcaptain AppStream) — no pre-flight
        # clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Daily Focus run complete — every captainship tab is filled. Any ICD that couldn't be pulled (rcaptain has no AppStream access to it yet) is listed below.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
            "again_label": "🔁 Retry the skipped ICDs",
            "again_action": {
                "label": "Retry skipped ICDs",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: ["--retry-inaccessible"],
            },
            "again_state_file": "output/daily_focus_state.json",
            "again_state_key": "inaccessible",
            "again_empty_message": "✅ All ICDs pulled — nothing to retry.",
        },
        "actions": [
            {
                "label": "Run Daily Focus",
                "icon": "▶",
                "primary": True,
                "help": "Fills today's daily focus report for every ICD across all captainship tabs.",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: [],
            },
            {
                "label": "Run for One ICD",
                "icon": "🎯",
                "needs_text": True,
                "text_label": "ICD name (as it appears in col V)",
                "help": "Just refill one ICD's section — handy after a typo fix or partial run",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda name: ["--only", name],
            },
        ],
    },
    {
        "id": "financial-pull",
        "name": "Financial Report",
        "creator": "Megan",
        "emoji": "💰",
        "color": "#34D399",
        "category": "🎯 Recruiting",
        "description": "Parses the emailed FINANCIAL SUMMARY workbooks "
                       "(plus the German + Coel files) and fills the "
                       "financial section across every matched ICD tab on "
                       "the ATT Program, Carlos 1on1s, and Alphalete Org "
                       "1on1s focus reports.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads the financial workbooks emailed each week and writes "
            "them into the latest 4 week columns on every matched ICD.\n\n"
            "WHEN IT RUNS\n"
            "Auto-runs Thursday mornings on the mac mini scheduler — it "
            "pulls this week's FINANCIAL SUMMARY workbooks straight from the "
            "reporting inbox (all senders) and fills, no upload needed. The "
            "manual upload button below stays as a fallback for a re-run.\n\n"
            "IF AN ICD ISN'T IN THIS UPLOAD\n"
            "Their tab is **left untouched** — whatever was filled by a "
            "previous run stays put. When you later upload a file that "
            "DOES include that ICD, the cells fill in then. (So you can "
            "safely upload partial / incremental sets of files any day.) "
            "Raf Hidalgo is permanently skipped (his financials live in "
            "a separate report)."
        ),
        "sheet_url": SHEET_URL,
        # The financial pull writes to three different focus reports. Listed
        # here so the card surfaces all three destinations, not just the
        # primary 'Open Sheet' link (which is the ATT Program one).
        "target_sheets": [
            {"name": "ATT Program - Focus Report",          "url": SHEET_URL},
            {"name": "Carlos 1on1s - Focus Report",         "url": CARLOS_SHEET_URL},
            {"name": "Alphalete Org 1on1s - Focus Reports", "url": ALPHALETE_ORG_SHEET_URL},
        ],
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [3],   # Thursday — 2026-07-01: cut over to auto
                                # email-ingest. All 3 senders land by Wed
                                # midday, so Thursday's 4am run has the full
                                # week with a day of buffer.
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 5,
        },
        "checklist": [
            {"text": "Upload financial .xlsx files received via email",
             "uploader": {
                 "target_dir": "automations/uploaded/financial",
                 "accept": [".xlsx"],
                 "multiple": True,
             }},
        ],
        "post_run": {
            "message_success": "✅ Financial section filled on every "
                               "matched ICD tab. Unmatched tabs were left "
                               "untouched (re-upload with their file later).",
            "message_failed": "❌ Run failed. Check the log above.",
        },
        "actions": [
            {
                "label": "Run Financial Pull",
                "icon": "▶",
                "primary": True,
                "help": "Pulls the Double Entry org summary (logs in on its "
                        "own) AND this week's emailed workbooks, then fills "
                        "the financial section. Double Entry wins where both "
                        "have an office; the books still cover the owners it "
                        "doesn't expose.",
                "module": "automations.financial_report.run",
                "args_fn": lambda: ["--web", "--email"],
            },
            {
                "label": "Fill from uploaded files only",
                "icon": "📄",
                "help": "Fallback: ignore Double Entry and the inbox, and "
                        "parse only the .xlsx files uploaded above.",
                "module": "automations.financial_report.run",
                "args_fn": lambda: [],
            },
        ],
    },
    # "Frontier OPT Data Pull" card REMOVED 2026-08-23 (Megan: "we no longer
    # use anything with frontier"). The Sunday 6pm LaunchAgent was uninstalled
    # and frontier_opt RETIRED in schedule_config the same day; the module
    # (alphalete_org_report.opt_frontier) is kept for history. Frontier
    # sections inside other reports come out in a separate pass.
    {
        "id": "leaders-call",
        "name": "Leader's Call - Weekly Recognition",
        "creator": "Claude",
        "emoji": "📣",
        "color": "#F59E0B",
        "category": "🎯 Recruiting",
        "self_scheduled": True,
        "description": "The Monday recognition build. 2pm pulls each campaign's "
                       "qualifying reps from Tableau (Fiber, NDS, B2B, BOX, Costco, "
                       "Revenue) into the Leader's Call tab. 7:30pm builds the "
                       "widescreen deck (campaigns + Revenue + the Leadership "
                       "Promotions finale) and posts it to #top-leaders-alphalete-org "
                       "+ #alphalete-gp-sales as Lucy — finished before the 8pm call. "
                       "(The Monday reminder emails are their own card now — Promo "
                       "Reminder Email.)",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills the **Leader's Call** tab with the week's recognition "
            "names per campaign, each section sorted high-to-low:\n"
            "- **Fiber / NDS / B2B / BOX** — reps with **12+** apps\n"
            "- **Costco** — reps with **8+** (ATV+DTV+Internet+AIA+New/Port, "
            "no Up)\n"
            "- **Revenue over 2K** — reps at **$2,000+** (local-office owners)\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each campaign view's 'This Week' = the just-"
            "completed week, so the run recognizes the finished week.\n\n"
            "DELIVERY (two steps)\n"
            "1. **2:00pm** — pulls every Tableau campaign and writes the Leader's "
            "Call tab (no send).\n"
            "2. **7:30pm** — builds the widescreen deck (campaigns + Revenue + the "
            "Leadership Promotions finale, read from the recognition sheet with "
            "notes tidied up) and posts the PDF to **#top-leaders-alphalete-org** + "
            "**#alphalete-gp-sales** as Lucy — finished before the 8pm call. The "
            "tile goes **green** once the deck posts.\n\n"
            "The Monday reminder emails (11am / 4pm / 7:15pm) that nudge owners to "
            "fill the recognition sheet are their **own card now — Promo Reminder "
            "Email**."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit?gid=1296972441#gid=1296972441"),
        "assignees": ["Lucy 1"],
        # Two-phase pill (Monday): the 2pm pull writes the tab and publishes
        # (1/2, amber), the 7:30pm deck post publishes the 2nd pass and greens it
        # (2/2). The 3 Monday reminder emails moved to their own card —
        # "Promo Reminder Email" (promo-reminder-email), split out 2026-08-02
        # (Megan) — so those are NOT phases of this card anymore.
        "daily_runs": {"0": 2},   # Mon: 2pm pull + 7:30pm deck post
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],   # Monday
            "time": "7:30 PM",               # final phase (sortable fallback)
            "time_label": "2 PM · 7:30 PM",  # both phase times shown on the tile
            "estimated_minutes": 8,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Done — check the log above. (2pm 'Pull "
                               "campaigns' writes the tab; 7:30pm 'Build + post "
                               "deck' posts to the channels as Lucy.)",
            "message_failed": "❌ Run failed. Check the log above, then re-run.",
        },
        "actions": [
            {
                "label": "Pull campaigns → tab",
                "icon": "▶",
                "primary": True,
                "help": "The 2pm step — pull every Tableau campaign and write the "
                        "Leader's Call tab. No PDF, nothing sent.",
                "module": "automations.leaders_call.run",
                "args_fn": lambda: ["--write", "--no-pdf"],
            },
            {
                "label": "Build + post deck",
                "icon": "📣",
                "help": "The 7:30pm step — rebuild the deck from the tab + the "
                        "latest promotions and post it to #top-leaders-alphalete-org "
                        "+ #alphalete-gp-sales as Lucy.",
                "module": "automations.leaders_call.run",
                "args_fn": lambda: ["--finalize"],
            },
            {
                "label": "Add promos → re-post to thread",
                "icon": "🔄",
                "help": "For last-minute promotions: pull the latest promos, rebuild "
                        "the deck, and re-post the updated PDF as a reply in today's "
                        "existing Leader's Call thread (not a new post).",
                "module": "automations.leaders_call.run",
                "args_fn": lambda: ["--repost"],
            },
        ],
    },
    {
        "id": "promo-reminder-email",
        "name": "Promo Reminder Email",
        "creator": "Maud & Claude",
        "emoji": "📧",
        "color": "#0EA5E9",
        "category": "🎯 Recruiting",
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "owners_call_reminder",
        "self_scheduled": True,
        # Three Monday email sends (11am / 4pm / 7:15pm final) — daily_runs makes
        # the pill climb 1/3 → 2/3 → 3/3 green as they land (yellow→orange→teal→
        # green ramp). Split out of the Leader's Call card 2026-08-02 (Megan) so
        # the recognition-sheet nudges are their own thing, not folded into the
        # Monday deck flow.
        "daily_runs": {"0": 3},
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],   # Monday
            "time": "7:15 PM",   # final send; card sorts on its FIRST send (11 AM, from time_label)
            "time_label": "11 AM · 4 PM · 7:15 PM (final)",
            "estimated_minutes": 2,
        },
        "description": "Emails the owners/ICDs three Monday reminders — 11 AM, 4 PM, "
                       "and a 7:15 PM final call — to fill in their office promotions "
                       "on the recognition sheet before the Leader's Call. Sent from "
                       "the reporting Gmail to the 'Org. Call Invite' Contacts distro.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Each **Monday** it emails the owners/ICDs a reminder to fill in their "
            "office promotions on the **recognition sheet** before the Leader's "
            "Call.\n\n"
            "THE THREE SENDS (the pill climbs as each lands)\n"
            "1. **11:00 AM** — first reminder.\n"
            "2. **4:00 PM** — second reminder.\n"
            "3. **7:15 PM** — 🚨 final call, last chance before the 8pm call.\n\n"
            "WHO GETS IT\n"
            "The **'Org. Call Invite'** Google Contacts distro (Megan maintains it; "
            "membership changes are picked up each run). Sent from the reporting "
            "Gmail.\n\n"
            "WHEN IT RUNS\n"
            "**Monday only**, on its own LaunchAgent on Lucy 1 (the mini). The deck "
            "build itself is the separate **Leader's Call** card."
        ),
        "checklist": [],
        "post_run": {
            "message_success": "✅ Reminder emailed to the Org. Call Invite distro.",
            "message_failed": "❌ Send failed — check the log above (usually the "
                              "distro list or the Gmail app password).",
        },
        "actions": [
            {
                "label": "Send a reminder now",
                "icon": "▶",
                "primary": True,
                "help": "Emails the recognition-sheet reminder to the Org. Call "
                        "Invite distro now (7pm+ auto-uses the final-call wording).",
                "module": "automations.owners_call_reminder.run",
                "args_fn": lambda: ["--send"],
            },
            {
                "label": "Preview (writes .eml, sends nothing)",
                "icon": "👁",
                "help": "Builds the email to output/ without sending — safe anytime.",
                "module": "automations.owners_call_reminder.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "recognition-tab",
        "name": "Recognition Weekly Tab",
        "creator": "Claude",
        "emoji": "🗓️",
        "color": "#10B981",
        "category": "🎯 Recruiting",
        "self_scheduled": True,
        "description": "Each Sunday morning, creates that week's tab (a copy of the "
                       "LUCY TEMPLATE) in Maud's Alphalete Recognition sheet so ICDs "
                       "have a fresh place to log office promotions before the Monday "
                       "Leader's Call.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Duplicates the **LUCY TEMPLATE** tab into a new tab named for the "
            "week-ending Sunday (e.g. **7.26.26**) in the Alphalete Recognition "
            "sheet. Additive + idempotent — it only ADDS a tab; it never edits, "
            "clears, or deletes anything, and skips if the week's tab already "
            "exists.\n\n"
            "WHEN IT RUNS\n"
            "**Sundays 8:00am CST**."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1lgYjfpCwYbeeGAdx7FEyI9PIqFk-W57X7HaZ4nsuoFM/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [6],   # Sunday
            "time": "8:00 AM",
            "estimated_minutes": 1,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ This week's recognition tab is created — ICDs "
                               "can fill in their promotions.",
            "message_failed": "❌ Couldn't create the tab. Check the log above.",
        },
        "actions": [
            {
                "label": "Create this week's tab",
                "icon": "▶",
                "primary": True,
                "help": "Duplicate the LUCY TEMPLATE into this week's dated tab "
                        "(skips if it already exists — never overwrites).",
                "module": "automations.leaders_call.recognition_tab",
                "args_fn": lambda: ["--write"],
            },
        ],
    },
    {
        "id": "daily-rep-breakdown",
        "name": "Daily Rep Breakdown - ATT Program",
        "creator": "Megan",
        "emoji": "📊",
        "color": "#F472B6",
        "category": "🎯 Recruiting",
        "description": "Per-rep day-by-day production breakdown from "
                       "ownerville + Tableau — one tab per owner. "
                       "Monday wipes + scrapes the full week; Tue-Sun "
                       "incremental.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls each rep's daily production from ownerville and "
            "Tableau into the Daily Rep Breakdown Sheet. Monday does a "
            "full wipe + re-scrape (so terminated reps drop off "
            "cleanly). Tue-Sun do an incremental update (yesterday's "
            "now-complete numbers plus today's partial).\n\n"
            "WHEN IT RUNS\n"
            "**Every day.** Monday is a fresh start; the rest of the "
            "week is additive."
        ),
        "sheet_url": "https://docs.google.com/spreadsheets/d/"
                     "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY/edit",
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 15,
        },
        # Fully unattended via patchright (ownerville Tableau session) — no
        # pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Daily Rep Breakdown complete — Sheet "
                               "updated and you'll see a desktop "
                               "notification when it finishes.",
            "message_failed": "❌ Run failed. Check the log above, fix "
                              "the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Daily Rep Breakdown",
                "icon": "▶",
                "primary": True,
                "help": "Monday = full wipe + scrape. Tue-Sun = "
                        "incremental update.",
                "module": "automations.focus_office_att.daily",
                "args_fn": lambda: [],
            },
        ],
    },
    _office_metrics_card(),
    _b2b_metrics_card(),
    {
        "id": "fiber-activations",
        "name": "Fiber Activations Report",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#A78BFA",
        "category": "🎯 Fiber",
        "description": "Daily Wed→Tue fill on the 'Captainship Activations' tab — Raf's team activations + country activations + EOW sales + 60-day churn + activation rate. Then posts the blue + orange screenshots to Slack.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls 6 Tableau numbers daily into the 'Captainship Activations' "
            "tab, then renders two PNGs (blue Fiber table + secondary tables, "
            "orange Country table) and posts them to #level10-alphalete.\n\n"
            "WHEN IT RUNS\n"
            "**Every day, Wed–Tue.** Each Wednesday inserts a new row for the "
            "new cycle.\n\n"
            "SLACK\n"
            "Replies in the weekly **'Activations Report Tracker WE MM.DD'** "
            "thread (created automatically each Wednesday, under Eve). Post "
            "name = PNG file name; Wednesday's Fiber post tags Rafael, Maud "
            "& Dylan."
        ),
        # Deep-links to the 'Captainship Activations' tab this run fills
        # (SHEET_ID/TAB_NAME in fiber_activations/run.py). The old link pointed
        # at the wrong workbook (1Ez-mbRO, the local-office sheet).
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"
                      "?gid=1505152764#gid=1505152764"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Fiber Activations done — sheet updated (day cell + Activations + EOW Sales + Churn + Activation Rate) and both screenshots posted to the WE tracker thread in #level10-alphalete.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Today's Fill",
                "icon": "▶",
                "primary": True,
                "help": "Fills today's day-of-week cell (Wednesday also inserts the new row), then posts the blue + orange screenshots to the weekly tracker thread in #level10-alphalete.",
                "module": "automations.fiber_activations.run",
                "args_fn": lambda: [],
            },
        ],
    },
    _tableau_trackers_card(),
    _tableau_box_card(),
    {
        "id": "owner-chat-texts",
        "name": "Owner Chat Texts → iMessage owner chats",
        "creator": "Megan & Claude",
        "emoji": "\U0001F4AC",
        # Same blue as the Tableau Country Trackers card above — this is their
        # delivery arm, so they read as one artwork family.
        "color": "#1F4E79",
        "category": "\U0001F4CA Metrics",
        "description": (
            "Texts the morning boards into the owner iMessage group chats as "
            "alphaletereporting@gmail.com (Lucy 1): all the Country Trackers "
            "as ONE PDF (a page per tracker) into \"Alphalete Owners "
            "\U0001F525 - Real\" at 7:30 AM, then the All Units WOW delta "
            "chart (owners numbered 1-n, sorted most-to-least apps) into that "
            "chat AND \"Alphalete A-Team Chat\U0001F525\U0001F525\" at 7:45 AM."
        ),
        "breakdown": (
            "WHAT IT DOES\n"
            "Two passes each morning, both from **Lucy 1** (Messages is signed "
            "in there as **alphaletereporting@gmail.com**):\n"
            "• **7:30 AM — Trackers.** Downloads the tracker PNGs already "
            "posted in **#alphalete-sales** (no second Tableau pull), bundles "
            "them into **one PDF** — a page per tracker, in channel order "
            "(Raf 8/23: one message, not nine) — and texts it into "
            "**Alphalete Owners \U0001F525 - Real**.\n"
            "• **7:45 AM — WOW board.** Re-sorts the All Units board "
            "most-to-least apps, renders the delta chart with the 1-n owner "
            "numbering, and texts it into **both** owner chats.\n\n"
            "IF SOMETHING'S LATE\n"
            "The PDF **waits** while any tracker is still missing from the "
            "Slack thread (the scheduler retries through the morning), and "
            "from **9:00 AM** it stops waiting and sends what's there with "
            "the gaps named in the caption. A board still short of yesterday "
            "(data gate) holds the same way. Per-day sent-markers make "
            "retries duplicate-proof: nothing ever texts twice.\n\n"
            "IF IT FAILS\n"
            "A pass that never completes posts a failure incident to "
            "**#claudecorrections-and-requests**, same as every scheduled "
            "report.\n\n"
            "SAFETY\n"
            "Chats are resolved by NAME on every send and the send refuses to "
            "guess between lookalikes. The Run button is a full DRY-RUN "
            "rehearsal — it fetches, renders, and resolves both chats but "
            "texts no one; only the two scheduled passes send."
        ),
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        # Base registry entry = the module WITHOUT --send: a safe full rehearsal.
        "run_rerun_id": "owner_chat_texts",
        "self_scheduled": True,
        # PHASE card (Megan 2026-08-23: "2 colors"): each pass publishes its own
        # scheduler id, and these strings must match the stored Report IDs
        # exactly or the pill sticks on the mid-colour. Listing both ids here is
        # also what keeps the second one from auto-registering a phantom card.
        # No approval_phase — the second pass is a machine, not a checkmark.
        # TWO PHASES, ONE CARD ID (Megan 2026-08-25: "this text did go out"
        # while the card read "no run logged"). This was a `phases` chain —
        # which resolves each phase id against the Activity log — but 1a5179a
        # added _HUB_CARD mappings routing BOTH halves to this card id, so the
        # phase ids stop appearing in the log entirely and the chain can never
        # complete. The two mechanisms cancel out. Keep the mapping (it is what
        # stops each half auto-registering a phantom library card) and count the
        # halves the other supported way: phase_runs counts DISTINCT Report
        # NAMES, and the halves already carry different ones ("… — Trackers
        # (iMessage)" vs "… — WOW Board (iMessage)"), so the 7:37 failure and
        # its 9:37 re-run still count ONCE — amber after trackers, green after
        # the board. [[reference_phase_pill_id_match]]
        "daily_runs": 2,
        "phase_runs": True,
        "schedule": {
            "frequency": "daily",
            "time": "7:30 AM",
            "time_label": "7:30 AM trackers · 7:45 AM WOW board",
            "estimated_minutes": 5,
        },
        "checklist": [],
    },
    {
        "id": "lucy-weather-forecast",
        "name": "Lucy Weather Forecast",
        "creator": "Megan",
        "emoji": "🌤️",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "self_scheduled": True,
        "description": "Lucy posts the daily DFW weather forecast to "
                       "#alphalete-sales each morning — temp, precipitation, "
                       "recommended dressing, and what to bring for the field. "
                       "Pulled from Open-Meteo (no API key). Plain, fixed "
                       "layout — no AI.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls today's Frisco/DFW forecast from Open-Meteo and posts a short, "
            "fixed-layout note as Lucy 🐺 to #alphalete-sales:\n"
            "**•** **Temp** — high / low.\n"
            "**•** **Precipitation** — chance + time + type, or 'none expected'.\n"
            "**•** **Recommended dressing** — weather-driven.\n"
            "**•** **Recommended to bring** — water / sunscreen / umbrella / "
            "bug spray.\n\n"
            "WHEN IT RUNS\n"
            "Daily at 6:00 AM CST on the mini, on its own job — no upload, no "
            "trigger."
        ),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "6:00 AM",
            "estimated_minutes": 1,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Weather forecast posted to #alphalete-sales "
                               "as Lucy.",
            "message_failed": "❌ Run failed. Check the log above, fix, then "
                              "run again.",
        },
        "actions": [
            {
                "label": "Post Today's Forecast",
                "icon": "▶",
                "primary": True,
                "help": "Pulls today's DFW forecast and posts it to "
                        "#alphalete-sales as Lucy. Runs from any machine.",
                "module": "automations.weather_alert.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "energy-slack-fill",
        "name": "Energy Sales → Sales Board (from Slack)",
        "creator": "Eve",
        "emoji": "⚡",
        "color": "#F2C744",
        "category": "📊 Metrics",
        "description": "Fills the EN column for every Campaign = Energy rep on 'Alphalete SALES BOARD 2025' by reading the last running sales board the office posted in #alphalete-sales the night before. Replaces the hand-typing that had to happen before the morning Production post.",
        "breakdown": (
            "WHAT IT DOES\n"
            "The Energy reps are the one campaign on the Sales Board with no "
            "feed — their sales exist only in the running board the office "
            "re-posts in #alphalete-sales all evening ('Energy / Rivera ⚡ / "
            "Edgar ⚡ / Base 2/15'). Every re-post carries the whole day, so "
            "the last message of the night is the finished day. This reads it, "
            "counts the ⚡ per rep, matches them to the Energy rows on the "
            "week's tab, and writes each rep's EN cell for that day.\n\n"
            "IT ONLY EVER RAISES A NUMBER\n"
            "A sale that reached the board some other way stands — a rep is "
            "written only when Slack says MORE than the cell already holds. So "
            "re-running a day is safe and the number can never go backwards.\n\n"
            "WHEN IT HOLDS (writes nothing, says why)\n"
            "• no Energy block posted for that day\n"
            "• the block's own 'N/goal' tally disagrees with the lines — the "
            "only independent check on the read\n"
            "• a name matches no rep, or two reps, on the Energy roster\n\n"
            "WHEN IT RUNS\n"
            "Daily, just before the ~4 AM Alphalete Production post — whose "
            "'Energy Sales Board' image is rendered off exactly these cells."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "3:50 AM",
            "estimated_minutes": 2,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Energy sales filled from #alphalete-sales. Anything it couldn't place is named in the log above — check before the Production post goes out.",
            "message_failed": "❌ Held or failed. The log says which day and why (no post / tally mismatch / a name it couldn't place). Nothing was written.",
        },
        "actions": [
            {
                "label": "Preview Yesterday",
                "icon": "👁",
                "primary": True,
                "help": "Reads last night's board and shows every rep against the cell already on the Sheet. Writes nothing.",
                "module": "automations.energy_slack_fill.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Fill Yesterday",
                "icon": "▶",
                "primary": False,
                "help": "Same read, then writes the EN cells. Only ever raises a number, so it's safe to run twice.",
                "module": "automations.energy_slack_fill.run",
                "args_fn": lambda: ["--apply"],
            },
        ],
    },
    {
        "id": "alphalete-production",
        "name": "Alphalete Daily Production Slack Post",
        "creator": "Eve",
        "emoji": "🐺",
        "color": "#6A4C93",
        "category": "📊 Metrics",
        "description": "Combines Jolie's two manual morning screenshot posts into ONE dated '🐺 Alphalete Production' thread in #alphalete-sales AND #alphalete-lvl1-chat: Daily Production, an All Teams Sales Board, an Entry Level (Wk 1–4) board, a Back-to-Back Zeros callout, an Energy-only sales board, a Team Sales board per team, Highrollers of the day, and 3 rankings (Apps / New Internets / Wireless).",
        "breakdown": (
            "WHAT IT DOES\n"
            "Takes screenshots the Sales Board tab into clean PNGs and posts "
            "them as Lucy in one threaded post.\n\n"
            "IMAGES\n"
            "1. Daily Production — days already played only (Raf 8/23), no "
            "Leadership Status / Location, Teams table split into its own image\n"
            "2. All Teams Sales Board — the Teams table (current/last week Total "
            "Units + per-day Apps) as its own post (Raf 8/23)\n"
            "3. Daily Production — Entry Level — 1st–4th-week reps only "
            "(drops 5th-wk+ veterans), grouped by team, same trims as #1\n"
            "4. Back-to-Back Zeros — reps who rolled a 0 on both of the last two "
            "mandatory days (Sundays don't count; Monday compares Fri + Sat), by team\n"
            "5. Energy Sales Board — Campaign = Energy only, ranked by Apps\n"
            "6. Team Sales — one image per team (auto-counts from the sheet)\n"
            "7. Highrollers of the Day\n"
            "8. Total Week Production (Ranking based on Apps)\n"
            "9. Ranking based on New Internets\n"
            "10. Ranking based on Wireless\n\n"
            "WHEN IT RUNS\n"
            "Daily, ~4 AM on the mini (before the manual post), into "
            "#alphalete-sales + a mirrored copy in #alphalete-lvl1-chat (Raf 8/23). "
            "Monday shows the fully-completed prior Mon–Sun week."
        ),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 8,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Alphalete Production posted — Daily Production, All Teams Sales Board, Entry Level, Back-to-Back Zeros, Energy board, team boards, Highrollers, and the 3 rankings in the dated threads in #alphalete-sales + #alphalete-lvl1-chat.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Post Today's Production",
                "icon": "▶",
                "primary": True,
                "help": "Renders every section off a hidden copy of the Sales Board tab and posts them to the dated thread in #alphalete-sales. Best run on the mini (posts as Lucy).",
                "module": "automations.alphalete_production.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "other-office-knocks",
        "name": "Knocks for Other Offices (#alphalete-sales)",
        "creator": "Eve",
        # 📸 like the other cards whose output IS a Slack image post, and the
        # channel is in the name the way the per-office metrics cards carry
        # theirs (Megan 2026-08-19).
        "emoji": "📸",
        "color": "#C1651B",
        "category": "📊 Metrics",
        "description": "Posts the SAME combined Total Knocks board (knocks + time gaps in one image) the main report posts for Rafael Hidalgo's office, but for the offices that don't have a metrics thread of their own — Sahil Multani and Chan Park — into their own 'Knocks for other offices' thread in #alphalete-sales. One image per office, same layout and columns as Raf's.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Opens ownerville as each office in turn (impersonation), scrapes "
            "'Disposition by Rep' + Time Tracker for yesterday, and draws the "
            "same combined Total Knocks board Raf's report posts — knocks + "
            "gaps in one image, same columns, same theme, alphabetical.\n\n"
            "WHERE IT POSTS\n"
            "#alphalete-sales, in its OWN dated thread, one image per office:\n"
            "'Knocks for other offices — <Month> <day> <year>'\n"
            "• 🚪 Total Knocks — Sahil Multani\n"
            "• 🚪 Total Knocks — Chan Park\n\n"
            "It never replies into the Metrics thread — that one stays exactly "
            "as it is. The office name is in each image's title too, so a "
            "screenshot forwarded on its own still says whose office it is.\n\n"
            "NO SHEET IS TOUCHED\n"
            "The images are drawn straight from the fresh pull, so no tab is "
            "read or written for these offices.\n\n"
            "IF AN OFFICE HAS NO KNOCKS\n"
            "It posts 'No data available' for that office instead of skipping "
            "it, so an empty day is visible rather than silent.\n\n"
            "WHEN IT RUNS\n"
            "Daily in the 4am batch, immediately after the Daily Metrics "
            "report — so it goes out with the morning metrics — but it is "
            "its own report: if an office drops, THIS card goes red and the "
            "failure alert names the office, instead of it getting lost inside "
            "the metrics summary."
        ),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (right after Daily Metrics)",
            # ~4 min per office: ownerville login + impersonate + two scrapes.
            "estimated_minutes": 9,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Knocks posted for Sahil Multani and Chan Park in today's 'Knocks for other offices' thread in #alphalete-sales.",
            "message_failed": "❌ An office didn't post. The log names which one — usually ownerville couldn't reach that office (session expired, or the office was renamed, which the ICD Aliases tab fixes). Use 'Post Today's Knocks' again: it re-runs ONLY the office that's missing.",
        },
        "actions": [
            {
                "label": "Post Today's Knocks",
                "icon": "▶",
                "primary": True,
                "help": "Pulls both offices and posts one image each into today's 'Knocks for other offices' thread. If today's run already left an office missing, this re-runs ONLY that office — it won't re-post the one that already landed.",
                "module": "automations.other_office_knocks.run",
                "args_fn": lambda: _office_run_args(["--live"],
                                                    "other_office_knocks"),
            },
            {
                "label": "Preview (no post)",
                "icon": "👁",
                "primary": False,
                "help": "Pulls both offices and saves the images to output/other_office_knocks/ so you can look at them. Posts nothing to Slack.",
                "module": "automations.other_office_knocks.run",
                "args_fn": lambda: ["--dry-run"],
            },
        ],
    },
    {
        "id": "energy-crossref",
        "name": "Energy Cross-reference (webform check)",
        "creator": "Eve",
        "emoji": "🔎",
        "color": "#F2C744",
        "category": "📊 Metrics",
        "description": "Checks that every Energy sale from yesterday has its Google-Form ('webform') submission, and posts the result in that morning's 🐺 Alphalete Production thread — tagging the reps who still owe one, plus Rafael and Dylan. Replaces the check Evelyn was doing by hand every morning.",
        "breakdown": (
            "WHY IT MATTERS\n"
            "A rep doesn't get paid on a sale whose webform was never filled "
            "out. This is the daily nudge, sent to the people who owe one.\n\n"
            "IT COUNTS THE DAY THREE WAYS\n"
            "1. Slack — the last running Energy board of the night in "
            "#alphalete-sales\n"
            "2. Sales Board — the EN column on 'Alphalete SALES BOARD 2025'\n"
            "3. Webform — the 'Base Power Energy' form responses, filtered on "
            "'Date of Sale' (NOT the timestamp: reps file days late)\n\n"
            "WHO GETS TAGGED\n"
            "Each rep owes one form per sale and is asked for the HIGHER of "
            "their two sale counts, so nobody is let off because one source "
            "lagged. Whoever is short is tagged by name, then Rafael Hidalgo "
            "and Dylan Twaddle — always, even on a clean day.\n\n"
            "DOUBLE-FILED FORMS DON'T COUNT TWICE\n"
            "Two rows from one rep with the same phone number or the same "
            "customer are one sale, so a rep who submitted the same one twice "
            "still shows as owing the other. The post names it.\n\n"
            "IMAGES\n"
            "The Energy Sales Board (re-rendered, because the 4:34 AM copy "
            "predates the board's own fill) and the day's webform rows.\n\n"
            "WHEN IT RUNS\n"
            "Daily, right after the ~4 AM Production post creates the thread "
            "it replies into. It never starts a thread of its own."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1wwvSEQAYqeGfgguvUeBR5ebtmez0JSik4BCHKOswa50/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (after the Production post)",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Cross-reference posted in the day's 🐺 thread. Anyone short of a webform was tagged.",
            "message_failed": "❌ Held or failed. The log says why — no Energy sales in either source, the 🐺 thread isn't up yet, or a rep couldn't be matched to a Slack account.",
        },
        "actions": [
            {
                "label": "Preview Yesterday",
                "icon": "👁",
                "primary": True,
                "help": "Shows the rep-by-rep table and the exact message that would go out. Posts nothing.",
                "module": "automations.energy_crossref.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Post Yesterday's Check",
                "icon": "▶",
                "primary": False,
                "help": "Renders both images and posts the check as a reply in the day's 🐺 Alphalete Production thread, tagging the reps who owe a webform.",
                "module": "automations.energy_crossref.run",
                "args_fn": lambda: ["--post"],
            },
        ],
    },
    {
        "id": "fiber-owners-distro",
        "name": "AT&T Fiber Owners — Email Distro Sync",
        "creator": "Raf & Claude",
        "emoji": "🐺",
        "color": "#F59E0B",
        "category": "🎯 Fiber",
        "assignees": ["Lucy 1"],
        # Runs INSIDE the Sat + Sun 4am orchestrator batch, so it belongs in the
        # MORNING BATCH section with NO clock time on the pill (Megan 2026-08-02:
        # "if it's in the 4am run it goes in the morning run section, no time on
        # the pill"). self_scheduled:False puts it there; hide_schedule keeps a
        # time off the pill; weekdays [5,6] means it's only expected on the
        # weekend, so weekday passes don't flag it. The Sat/Sun split is the
        # per-day WHAT, not a clock time.
        "hide_schedule": True,
        "self_scheduled": False,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [5, 6, 0],
            "time_label": "Sat: add owners + post departures · Sun/Mon: finalize removals",
            "estimated_minutes": 2,
        },
        "description": "Keeps Raf's “AT&T Fiber Owners” email list matched to Kelly's weekly roster — adds new owners, and removes ones who left after a 24-hour ✅/❌ check in #l10-alphalete.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads **Kelly Pavone's weekly “AT&T ICD Owner Roster”** and keeps "
            "Raf's **“AT&T Fiber Owners”** Google Contacts list in sync:\n"
            "**•** **New owners** on the **Fiber + Hybrid** tabs are **added** "
            "right away (Wireless & B2B ignored).\n"
            "**•** **Owners who dropped off** the roster are posted in "
            "**#l10-alphalete**, one line each — **✅ keep / ❌ remove**.\n"
            "**•** Only **Eve / Raf / Megan / Maud**'s reactions count. **✅** "
            "keeps someone; no ✅ = removed the next day.\n\n"
            "SAFETY\n"
            "**•** Never drops an owner who just **changed their email**, or who "
            "is still on **any** roster tab.\n"
            "**•** **Backs up** the list before every change.\n\n"
            "WHEN IT RUNS\n"
            "**Saturday** posts the removal thread (off Friday's roster); "
            "**Sunday** finalizes it 24h later. Runs on the mini as Lucy."
        ),
        "checklist": [],
    },
    {
        "id": "captainship-activations",
        "name": "Captainship Activations (per-captain)",
        "creator": "Eve",
        "emoji": "🧑‍✈️",
        "color": "#8E7CC3",
        "category": "🎯 Fiber",
        "description": "Daily Wed→Tue fill of the 5 per-captain tabs (Wayne, Starr, Chan, Tony, Sahil): violet captain table + shared country table. Renders 6 PNGs and saves them to your Downloads folder (no Slack).",
        "breakdown": (
            "WHAT IT DOES\nOne Tableau pull → writes each captain's violet cells "
            "(activations, EOW, churn, appr) + the global country cells, then "
            "renders 6 PNGs (5 captain violet w/o the Payout col + 1 country) and "
            "saves them to your Downloads folder.\n\nDRIVE\nUpload to the "
            "'Captainship Activations - PNGs' Drive folder is OPTIONAL (the "
            "'Run + upload to Drive' button) and pending the Drive API being "
            "enabled — a failed/disabled upload never breaks the run.\n\nWHEN\n"
            "**On the scheduler — every day, Wed–Tue** (fully unattended, "
            "gated on the same Fiber Tableau session as Fiber Activations). "
            "You can also trigger it by hand here. Wednesday "
            "structure-only-inserts the new WE row. NO Slack."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "13-9f_aPDlPa6L6_Wash4ws7959mn822J__vB5OYmcB8/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {"frequency": "daily", "time": "4 AM flow (when data's ready)", "estimated_minutes": 6},
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship Activations done — 5 tabs filled (violet + country) and 6 PNGs uploaded to the Drive folder.",
            "message_failed": "❌ Run failed. Check the log, fix, re-run.",
        },
        "actions": [
            {
                "label": "Run Today's Fill",
                "icon": "▶",
                "primary": True,
                "help": "Pulls Tableau, fills the 5 tabs, renders the 6 PNGs and saves them to your Downloads folder.",
                "module": "automations.fiber_activations.captain_run",
                "args_fn": lambda: [],
            },
            {
                "label": "Run + upload to Drive",
                "icon": "☁",
                "primary": False,
                "help": "Same as Run Today's Fill, plus upload the PNGs to the Drive folder (needs the Drive API enabled; failures are non-fatal).",
                "module": "automations.fiber_activations.captain_run",
                "args_fn": lambda: ["--drive"],
            },
        ],
    },
    {
        "id": "captainship-drafts",
        "name": "Captainship Reports",
        "creator": "Eve & Claude",
        "emoji": "✉️",
        "color": "#8E7CC3",
        "category": "📊 Metrics",
        # TWO-PHASE card (Megan 2026-08-03): phase 1 = the 4am build of the 12
        # previews (report captainship-drafts), phase 2 = the Slack review post
        # + send-on-checkmark (report captainship_drafts_review). Same shape as
        # the Country Sales Board card: the pill is orange after the build and
        # turns green once the reports send. The two reports still run
        # separately — this only merges the Hub display. Was two cards
        # ("Captainship Report Drafts (12)" + the auto-registered "Captainship
        # Reports (a revisión)" library card, now hidden via the skip-set in
        # _read_shared_library).
        "description": "One card, two phases. **Build (4am):** renders the Captainship Report emails (Rafael + 5 fiber + 4 B2B + 3 NDS) as previews, in blocks — nothing sends. **Review (Slack):** each BLOCK posts its own PDF link inside the day's *Captainship Reports* thread in #revision-emails; a ✅ on a block mails that block's exact reviewed files, so a tanda goes out without waiting for the rest. Pill ramps as it goes: orange after the build, 🟣 **purple while it waits for the ✅s**, green once every block is approved.",
        "breakdown": (
            "PHASE 1 — BUILD (4am flow)\n"
            "**•** Builds every preview to output/, block by block (Fiber 1: "
            "Rafael → Fiber 2: Wayne, Starr → Fiber 3: Tony, Chan, Sahil → "
            "B2B → NDS) — Product Summary + "
            "Captainship Units, the churn buckets, and each captain's metric "
            "boxes (cancel rate, activation rate, ABP %, 6+ days out). Fiber "
            "adds the Fiber Activations PNG; B2B/NDS add the Team Stats "
            "Breakout shot.\n"
            "**•** Sends nothing. Re-running **replaces** that captain's "
            "preview for the day — no duplicates.\n\n"
            "DATES (deliberate split)\n"
            "**•** Sales / Captainship Units → the **PRIOR day** (a Tuesday run "
            "reports Monday).\n"
            "**•** Churn / Fiber Activations → **TODAY**.\n"
            "Don't pass a back-dated `--date` — it walks every section back a "
            "day.\n\n"
            "PHASE 2 — REVIEW + SEND (Slack), ONE BLOCK AT A TIME\n"
            "**•** Each block prints to its OWN PDF; **Lucy opens the day's "
            "*Captainship Reports* thread in #revision-emails and posts one "
            "link per block inside it** — a block is up for review as soon as "
            "it is built, not when the last one is.\n"
            "**•** A **✅ on a block** sends THAT block's exact files "
            "(mini's watcher, within 15 min) — what goes out can't differ "
            "from what was approved, and the other blocks keep waiting on "
            "their own ✅.\n"
            "**•** Pill: **orange** after the build, 🟣 **purple** once the "
            "links are posted and waiting, **green** only when EVERY block "
            "has been ticked. A day nobody approves never goes green.\n"
            "**•** **Send now — override** is the fallback if no ✅ comes.\n\n"
            "WHEN IT RUNS\n"
            "Tue–Sun, after the Sales Board fill, both churn runs, and the "
            "per-captain metric fills — never off a half-built board. Either "
            "phase failing fires the orchestrator alert.\n\n"
            "IF A SECTION IS BLANK\n"
            "*'Could not be captured on this run'* = the Sales Board render is "
            "signed out on the runner. Fix: `sheets_login check --machine "
            "\"Lucy 3\"`, then `sheets_login` (a human clears Google 2FA "
            "there). The runner is LUCY 3 since 2026-08-25 — not the mini."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2_iCFDdmBBLPQNQ8x8xLQPTUOJcxHOMRj5RWu6E/edit"),
        "assignees": ["Lucy 3"],
        # Phase 2 posts to Slack AS LUCY — route Hub-triggered runs to a Lucy so
        # a manual "Post to Slack" click can't post from a laptop under the
        # wrong user (same reason Country Sales Board pins run_machine).
        #
        # LUCY 1 -> LUCY 3 (2026-08-25), with captainship_knocks + captainship_
        # drafts. run_machine is a HARD PIN and does NOT follow schedule_config
        # the way `assignees` does (dashboard._machine_card_assignments only
        # rewrites assignees), so it has to be moved by hand or every Hub button
        # on this card keeps firing on Lucy 1 — where there is now no knock
        # manifest and no output/*.eml, so "Build the 12" would silently do the
        # 2h pull again and "Send now" would find nothing to mail.
        "run_machine": "Lucy 3",
        # THIRD PHASE = THE APPROVAL (Megan 2026-08-10: "a phase hub card that
        # goes green on approval so we have visual on it"). The first two rows
        # are both written by machines the moment they exit 0 — the build, then
        # the review POST — so the card used to turn green at ~4am with nobody
        # having read a thing. "captainship-drafts-approved" is written only
        # when review_gate --check finds Evelyn's ✅
        # (shared/review_approval.py), so the tile now sits PURPLE
        # "awaiting ✅" from the post until the approval, and only then greens.
        "phases": ["captainship-drafts", "captainship_drafts_review",
                   "captainship-drafts-approved"],
        "approval_phase": "captainship-drafts-approved",
        "schedule": {"frequency": "daily", "weekdays": [1, 2, 3, 4, 5, 6],
                     "time": "4 AM flow (when data's ready)", "estimated_minutes": 12},
        "checklist": [],
        "post_run": {
            "message_success": "✅ Built — the previews are in output/ as .html, grouped by block. Open them, check the numbers, then press 'Post to Slack for approval' (or let the 4am flow post them). Each block gets its own link and its own ✅.",
            "message_failed": "❌ Run failed. If §1 is blank the Sales Board render is signed out — run `sheets_login --machine \"Lucy 3\"` (the runner moved off the mini on 2026-08-25).",
        },
        "actions": [
            {
                "label": "1. Build + review them all",
                "icon": "👁",
                "primary": True,
                "help": "Builds every report, block by block (Fiber 1 → Fiber 2 → Fiber 3 → B2B → NDS), and writes them to output/ as .html you can open in a browser. Sends nothing and posts nothing. Check the numbers here first.",
                "module": "automations.captainship_drafts.run",
                "args_fn": lambda: ["--dry-run"],
            },
            {
                "label": "2. Post to Slack for approval",
                "icon": "📮",
                "primary": False,
                "help": "Prints ONE PDF PER BLOCK, drops each in Drive, and posts its link inside the day's Captainship Reports thread in #revision-emails. A ✅ on a block is what mails that block; a block already posted is left alone. Posts as Lucy from LUCY 3 (the runner since 2026-08-25) — the card routes there for you; don't run it from a laptop or it posts under your own account.",
                "module": "automations.captainship_drafts.review_gate",
                "args_fn": lambda: ["--post"],
            },
            {
                "label": "Send now — override",
                "icon": "📧",
                "primary": False,
                "help": "Skips the Slack ✅ and mails the EXACT files you just reviewed to every captain list (145 people) right now — every block at once. Rebuilds nothing. The fallback for a day the checkmarks never come — only press it once the numbers look right.",
                "module": "automations.captainship_drafts.run",
                "args_fn": lambda: ["--send-reviewed"],
            },
            {
                "label": "Send a test to myself",
                "icon": "🧪",
                "primary": False,
                "help": "Mails the reviewed reports to alphaletereporting@gmail.com instead of the real lists, so you can see exactly what the captains would get.",
                "module": "automations.captainship_drafts.run",
                "args_fn": lambda: ["--send-reviewed", "--to",
                                    "alphaletereporting@gmail.com"],
            },
        ],
    },
    {
        "id": "captainship-new-internet-wireless-churn",
        "name": "Captainship - New Internet & Wireless Churn",
        "creator": "Megan",
        "emoji": "🧭",
        "color": "#F59E0B",
        "category": "📊 Metrics",
        "description": "Daily fill of Raf's Captainship per-ICD churn rates (4 buckets: 0-30 / 30 / 60 / 90 day) for BOTH the Captainship New Internet and Wireless tabs. Pulls overall ICD churn (one row per ICD owner), not per-rep. No Slack post — sheet fill only.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills Raf's Captainship per-ICD churn rates "
            "(\"AT&T Fiber Metrics Report\" Google Sheet) "
            "on both the Captainship New Internet and Captainship "
            "Wireless tabs.\n\n"
            "TABS FILLED (on the AT&T Fiber Metrics Report sheet)\n"
            "• Captainship - New Internet Churn\n"
            "• Captainship - Wireless Churn\n\n"
            "WHEN IT RUNS\n"
            "Daily."
        ),
        # Deep-links to the Captainship churn tab this run fills.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8/edit"
                      "?gid=1564052763#gid=1564052763"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship Churn done — both tabs filled, sections sorted, blank-today rows hidden.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Captainship Churn (Both Tabs)",
                "icon": "▶",
                "primary": True,
                "help": "Pulls both Captainship Churn Crosstabs in one Tableau session + fills both tabs (skips today if already filled — pass --force-insert in CLI to override).",
                "module": "automations.captainship_churn.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "captainship-cancel-rate",
        "name": "Captainship - Cancel Rate (ATT Fiber)",
        "creator": "Eve",
        "emoji": "🚫",
        "color": "#F59E0B",
        "category": "📊 Metrics",
        "description": "Daily 0-30 and 30-60 day New Internet CANCEL rates per ICD owner, one tab per ATT Fiber captain (Wayne / Starr / Chan / Tony / Sahil). Runs right after the Captainship Churn fill. Cancel rate is a different metric from churn rate — this fills the Cancel Rate workbook, not the churn tabs. No Slack post — sheet fill only.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills each ATT Fiber captain's tab on the \"Captainship Metrics "
            "Report - Cancel Rate\" Google Sheet with today's cancel rates — "
            "the Captainship Avg plus one row per ICD owner. Today's column "
            "is inserted at B; the history shifts right.\n\n"
            "TABS FILLED\n"
            "• Cancel Rate - Wayne (ATT Fiber)\n"
            "• Cancel Rate - Starr (ATT Fiber)\n"
            "• Cancel Rate - Chan (ATT Fiber)\n"
            "• Cancel Rate - Tony (ATT Fiber)\n"
            "• Cancel Rate - Sahil (ATT Fiber)\n\n"
            "WHEN IT RUNS\n"
            "Daily, right after the Captainship Churn fill."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1P95BxzlmLKkuvcL0gqjD9EfEHPLniGN-m4eE9UsPe_E/edit"
                      "?gid=2129685820#gid=2129685820"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Cancel Rate done — all 5 captain tabs filled with today's column.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Cancel Rate (all 5 captains)",
                "icon": "▶",
                "primary": True,
                "help": "One Tableau session, one Metrics crosstab, all 5 captain tabs. Re-running the same day refreshes today's column instead of adding a second one.",
                "module": "automations.captainship_cancel_rate.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "owners-metrics-churn",
        "name": "Captainship Churn - Owners Metrics Report",
        "creator": "Megan",
        "emoji": "📑",
        "color": "#F59E0B",
        "category": "📊 Metrics",
        "description": "Daily per-ICD churn fills across the Owners Metrics Report sheet — one tab per captainship. Covers ATT Fiber (Wayne / Starr Rodenhurst / Chan Park / Tony Chavez / Sahil Multani), B2B (Carlos Hidalgo / Eveliz Wright / Luis Salazar), and NDS (Khalil Mansour / Colten Wright / Jairo Ruiz).",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills per-ICD churn rates on every captainship tab of "
            "the Owners Metrics Report Google Sheet.\n\n"
            "TABS FILLED — ATT Fiber (4 buckets: 0-30 / 30 / 60 / 90)\n"
            "• Churn - Wayne (ATT Fiber)\n"
            "• Churn - Starr Rodenhurst (ATT Fiber)\n"
            "• Churn - Chan Park (ATT Fiber)\n"
            "• Churn - Tony Chavez (ATT Fiber)\n"
            "• Churn - Sahil Multani (ATT Fiber)\n\n"
            "TABS FILLED — B2B (5 buckets: 0-30 / 30 / 60 / 90 / 120)\n"
            "• Churn - Carlos Hidalgo (B2B)\n"
            "• Churn - Eveliz Wright (B2B)\n"
            "• Churn - Luis Salazar (B2B)\n\n"
            "TABS FILLED — NDS (4 buckets: 0-30 / 30 / 60 / 90)\n"
            "• Churn - Khalil Mansour (NDS)\n"
            "• Churn - Colten Wright (NDS)\n"
            "• Churn - Jairo Ruiz (NDS)\n\n"
            "WHEN IT RUNS\n"
            "Daily at 7:00 AM CST."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1uFrT0EkkGT0QqlYTxw_uevZD3ObKxaVjWsvZAUDxK6c/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Owners Metrics Churn done — all Fiber tabs filled, sections sorted, blank-today + 5-zero rows hidden.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Owners Metrics Churn",
                "icon": "▶",
                "primary": True,
                "help": "Pulls all captainship Crosstabs in one Tableau session + fills each tab (skips today's INSERT if already filled — pass --force-insert in CLI to override).",
                "module": "automations.owners_metrics_churn.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "captainship-activation-rate",
        "name": "Captainship Activation Rate (per-captain)",
        "creator": "Eve",
        "emoji": "📈",
        "color": "#10B981",
        "category": "📊 Metrics",
        "description": "Daily activation rates on each fiber captain's Activation Rate tab of the Captainship Metrics Report sheet — Wayne / Starr / Chan / Tony / Sahil. Two boxes per tab: 0-30 days (Rolling 4 Weeks) and 30-60 days.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Adds one dated column per day to both activation boxes on "
            "every fiber captain's tab — the Captainship Avg plus a row "
            "per ICD owner.\n\n"
            "TABS FILLED\n"
            "• Activation Rate - Wayne (ATT Fiber)\n"
            "• Activation Rate - Starr (ATT Fiber)\n"
            "• Activation Rate - Chan (ATT Fiber)\n"
            "• Activation Rate - Tony (ATT Fiber)\n"
            "• Activation Rate - Sahil (ATT Fiber)\n\n"
            "WHERE THE NUMBERS COME FROM\n"
            "Tableau → ATTTRACKER2_1-D2D → Metrics view → worksheet "
            "'Metrics Call Last week data (Internet)', filtered by "
            "Captain's Bonus Teams.\n"
            "• Box 'ACTIVATION 0-30 DAYS'   → column 'Rolling 4 Weeks'\n"
            "• Box 'ACTIVATION RATE 30-60 DAYS' → column '30-60 day New "
            "Internet activation rate'\n"
            "• Captainship Avg → that team's own 'Total' row (never an "
            "average of the owner cells — these are rates over different "
            "denominators).\n\n"
            "ONE PULL, FIVE TABS\n"
            "The Metrics crosstab is already grouped by captainship, so "
            "the run downloads it once and slices it per captain — this "
            "workbook has no per-captain views.\n\n"
            "WHEN IT RUNS\n"
            "Daily, right after the other per-captain metrics."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1P95BxzlmLKkuvcL0gqjD9EfEHPLniGN-m4eE9UsPe_E/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship Activation Rate done — today's column added to both boxes on all 5 fiber tabs.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Captainship Activation Rate",
                "icon": "▶",
                "primary": True,
                "help": "One Metrics crosstab pull, sliced per captainship, then fills both activation boxes on all 5 tabs (refreshes today's column in place if it's already open — pass --force-insert in CLI to add another).",
                "module": "automations.captainship_activation_rate.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "captainship-abp-6days",
        "name": "Captainship ABP & 6 Days Out (per-captain)",
        "creator": "Eve",
        "emoji": "📐",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "description": "Daily ABP % and % of ongoing 6+ days out sales on each fiber captain's tab of the 'Captainship Metrics Report - ABP and 6 days out' sheet — Wayne / Starr / Chan / Tony / Sahil. Two boxes per tab.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Adds one dated column per day to both boxes on every fiber "
            "captain's tab — the Captainship Avg plus a row per ICD "
            "owner.\n\n"
            "TABS FILLED\n"
            "• ABP & 6 days out - Wayne (ATT Fiber)\n"
            "• ABP & 6 days out - Starr (ATT Fiber)\n"
            "• ABP & 6 days out - Chan (ATT Fiber)\n"
            "• ABP & 6 days out - Tony (ATT Fiber)\n"
            "• ABP & 6 days out - Sahil (ATT Fiber)\n\n"
            "WHERE THE NUMBERS COME FROM\n"
            "Tableau → ATTTRACKER2_1-D2D → Metrics view → worksheet "
            "'Metrics Call Last week data (Internet)', filtered by "
            "Captain's Bonus Teams.\n"
            "• Box 'ABP %' → column 'New Internet ABP Mix % (Metrics)'\n"
            "• Box '% of Ongoing 6+ Days Sales' → column '% of sales "
            "scheduled 6+ days out (4 wks)'. That is the percentage "
            "Tableau shows in the TOOLTIP of the visible 6+-days count "
            "column — tooltip measures ship in the crosstab export, so no "
            "hovering is needed. It cannot be derived from the count.\n"
            "• Captainship Avg → that team's own 'Total' row (never an "
            "average of the owner cells — these are rates over different "
            "denominators).\n\n"
            "ONE PULL, EVERY TAB\n"
            "The Metrics crosstab is already grouped by captainship, so "
            "the run downloads it once and slices it per captain.\n\n"
            "WHEN IT RUNS\n"
            "Daily, right after the other per-captain metrics."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1XlHdh3OIQYmyY7VGTZWc-OK-rIlz6ClomLULyR5I0y0/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship ABP & 6 Days Out done — today's column added to both boxes on all 5 fiber tabs.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Captainship ABP & 6 Days Out",
                "icon": "▶",
                "primary": True,
                "help": "One Metrics crosstab pull, sliced per captainship, then fills the ABP % and 6+-days-out boxes on all 5 tabs (refreshes today's column in place if it's already open — pass --force-insert in CLI to add another).",
                "module": "automations.captainship_abp_6days.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "captainship-raf-metrics",
        "name": "Captainship Metrics - Rafael",
        "creator": "Eve",
        "emoji": "🧭",
        "color": "#E8612A",
        "category": "📊 Metrics",
        "description": "Daily cancel rate (0-30 / 30-60), activation rate (0-30 / 30-60) and 6+-days-out % for RAFAEL's captainship, on the three 'Captainship - …' tabs of his AT&T Fiber Metrics Report sheet. Same metrics the five fiber captains get, sliced to Raf's Team.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Adds one dated column PAIR per day (% + count) to every box on "
            "Rafael's three captainship tabs — the Captainship Avg plus a row "
            "per ICD owner on his team.\n\n"
            "TABS FILLED\n"
            "• Captainship - Cancel Rate (0-30 and 30-60 boxes)\n"
            "• Captainship - Activation Rate (0-30 and 30-60 boxes)\n"
            "• Captainship - 6 days out\n\n"
            "WHERE THE NUMBERS COME FROM\n"
            "Tableau → ATTTRACKER2_1-D2D → Metrics view → worksheet "
            "'Metrics Call Last week data (Internet)', rows where Captain's "
            "Bonus Teams = \"Raf's Team\", read at each owner's subtotal row.\n"
            "• Cancel 0-30 → '0-30 day New Internet cancel rate'\n"
            "• Cancel 30-60 → 100% − '30-60 day New Internet activation "
            "rate' (the workbook carries no 30-60 cancel column). A blank "
            "activation rate stays blank — no data is not a 100% cancel.\n"
            "• Activation 0-30 → 'Rolling 4 Weeks'\n"
            "• Activation 30-60 → '30-60 day New Internet activation rate'\n"
            "His 'Captainship - ABP' tab is NOT filled here — Rafael is a "
            "slug of the Captainship ABP & 6 Days Out report, which fills "
            "it off the same crosstab in the same pass.\n"
            "• 6+ days out → '% of sales scheduled 6+ days out (4 wks)', the "
            "tooltip measure — it cannot be derived from the visible count.\n"
            "• Captainship Avg → the team's own 'Total' row, never an average "
            "of the owner cells (rates over different denominators).\n\n"
            "THE 'units' COLUMN\n"
            "Counts come from the crosstab: cancels for the 0-30 cancel box, "
            "activations for the 0-30 activation box, the 6+-days count for "
            "that one. Tableau publishes NO count behind either 30-60 rate, "
            "so those units cells are left blank on purpose. Whether a tab "
            "HAS a units column at all is read off the tab each run, never "
            "assumed.\n\n"
            "FORMATTING\n"
            "The day's pair is re-stamped from the module's own style table "
            "instead of copying yesterday's column, so the borders can never "
            "drift the way the ABP tab's did.\n\n"
            "WHEN IT RUNS\n"
            "Daily, right after the per-captain fiber metrics."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Rafael's Captainship metrics done — today's column pair added to all three tabs.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Captainship Metrics - Rafael",
                "icon": "▶",
                "primary": True,
                "help": "One Metrics crosstab pull, sliced to Raf's Team, then fills all five boxes across the three tabs (refreshes today's pair in place if it's already open — pass --force-insert in CLI to add another).",
                "module": "automations.captainship_raf_metrics.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Re-stamp the formatting",
                "icon": "🎨",
                "help": "Repair pass: re-applies the house style to EVERY day pair already on the three tabs. No Tableau pull, no new column.",
                "module": "automations.captainship_raf_metrics.run",
                "args_fn": lambda: ["--reformat"],
            },
        ],
    },
    {
        "id": "ongoing-1st-round-recruiter-retention",
        "name": "Ongoing 1st Round Recruiter Retention",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#2563EB",
        "category": "🎯 Recruiting",
        "description": "Weekly per-recruiter 1st-round retention for Raf's office — Scheduled / Showed Up / Retention % (Showed ÷ Scheduled) per week on the '1st rd Recruiter %' tab. Columns are week-ending Sundays; % color-coded (<45% red, 45–49.9% grey, ≥50% green); active schedulers highlighted.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls AppStream's Retention Report (admin breakdown) for Raf's "
            "office and fills one block per week per recruiter: Scheduled (Sch), "
            "Showed Up (SU), and Retention % (Showed ÷ Scheduled).\n\n"
            "WEEKS\n"
            "Each column is a week ENDING on Sunday. AppStream only reports "
            "Sun–Sat weeks, so a column uses the AppStream week that ends the day "
            "before it — a ~1-week shift (Sundays are near-zero, so the weekly "
            "totals line up).\n\n"
            "COLORS & HIGHLIGHTS\n"
            "• Retention %: under 45% red, 45–49.9% grey, 50%+ green.\n"
            "• A recruiter's NAME turns yellow if they scheduled an interview in "
            "the latest week (active schedulers that week).\n"
            "• AI Messaging and Self Scheduled rows are tinted — interviews not "
            "booked by a person.\n\n"
            "ROWS\n"
            "Recruiters who scheduled an interview in the last 2 weeks sit on top, "
            "sorted by the latest week's retention (high → low). Those with none "
            "in the last 2 weeks drop to the bottom and are hidden.\n\n"
            "WHEN IT RUNS\n"
            "Mondays. Each run fills the latest week and catches up any missed "
            "weeks; existing history stays as-is."
        ),
        # Deep-links to the tab this run writes to, not the workbook root.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=2024676935#gid=2024676935"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 10,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Recruiter retention updated — week totals filled, recruiters sorted by retention, inactive rows hidden.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Recruiter Retention",
                "icon": "▶",
                "primary": True,
                "help": "Pull AppStream + fill all weeks on the Ongoing tab (week totals).",
                "module": "automations.recruiter_retention.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "daily-1st-round-recruiter-percent",
        "name": "Daily Recruiter 1st Round Retention",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#2563EB",
        "category": "🎯 Recruiting",
        "description": "Daily Mon–Fri recruiter scorecards for Raf's office on the 'Daily 1st rd Recruiter %' tab — Booked / Scheduled / Showed / Retention % per day + Total, with current week (Mon→today) and last week side by side. Alphabetized; inactive recruiters recycle to a hidden bottom; % color-coded.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls AppStream's Retention Report (admin breakdown) for Raf's "
            "office and fills a daily Mon–Fri scorecard per recruiter.\n\n"
            "TWO CARDS PER RECRUITER\n"
            "• Left = current week, filled Monday → today (days after today "
            "stay blank).\n"
            "• Right = last week, full Mon–Fri.\n"
            "The day-header dates auto-update to the current week each run.\n\n"
            "COLORS\n"
            "Retention %: under 45% red, 45–49.9% grey, 50%+ green.\n\n"
            "ROWS / RECYCLING\n"
            "Recruiters are alphabetized. Anyone with no Booked/Scheduled/Showed "
            "for two weeks straight drops to the bottom and is hidden (never "
            "deleted) — they resurface at the top automatically when they get "
            "activity again. Manual Weekly/Daily goals in columns A/B travel with "
            "each recruiter, so they're never erased or misaligned.\n\n"
            "WHEN IT RUNS\n"
            "Monday–Friday, 8 AM."
        ),
        # Deep-links to the tab this run writes to, not the workbook root.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=732929068#gid=732929068"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "weekdays": [0, 1, 2, 3, 4],   # Mon–Fri only
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Daily recruiter % updated — Mon→today + last week filled, alphabetized, inactive recycled to the hidden bottom.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Daily Recruiter %",
                "icon": "▶",
                "primary": True,
                "help": "Pull AppStream + fill the daily Mon–Fri scorecards (this week + last week).",
                "module": "automations.recruiter_retention.daily",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "country-metrics",
        "name": "Country Metrics",
        "creator": "Eve",
        "emoji": "🌎",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "description": "Weekly New Internet Country Metrics + Sales/breakdown per captainship (Raf / Starr / Aron / Pat / Wayne / Sam / Chan / Tony / Sahil) on the 'Country Metrics' tab.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls New Internet Country Metrics and Sales + Breakdown per "
            "Captainship.\n\n"
            "WHEN IT RUNS\n"
            "Thursdays. Each run fills the most recently finished week."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE/edit#gid=1044031962"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [3],  # Thursday
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Country Metrics done — all 10 sections (COUNTRY + 9 captainships) filled for the latest weekending.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recently finished week's column (run Thursdays).",
                "module": "automations.country_metrics.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "int-wow-penetration",
        "name": "Int WoW Report - Penetration %",
        "creator": "Eve",
        "emoji": "📶",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "description": "Weekly Fiber Lead penetration % per owner on the Int WoW Report sheet. Each Tuesday inserts a new weekending column (newest first) in the 'Penetration %' table from Tableau's Fiber Lead Performance view.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls per-owner Fiber Lead penetration % from Tableau (ATT "
            "Tracker 2.1 - D2D / Fiber Lead Performance) and inserts a new "
            "weekending column at the LEFT (B) of the 'Penetration %' table "
            "— newest week first, older weeks shift right.\n\n"
            "WHEN IT RUNS\n"
            "**Tuesdays.** The weekending is the previous Sunday (Central).\n\n"
            "OWNER MATCHING\n"
            "Owner names are matched to the sheet through the ICD Aliases "
            "sheet, so spelling variants collapse to one person. Owners on "
            "the sheet that Tableau didn't report get '-%'. New owners are "
            "inserted alphabetically; look-alike names are logged (not "
            "inserted) so you can add an alias.\n\n"
            "TOTAL ROW\n"
            "The NATIONAL row = Tableau's 'Total general' Assigned Fiber Lead "
            "Penetration with Owner = (All).\n\n"
            "WATCH FOR\n"
            "Any % above 50% is logged as a WARNING (likely a Tableau glitch) "
            "but still written."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit#gid=1630583673"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1],  # Tuesday
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Int WoW Penetration % done — new weekending column inserted at B, owners matched, '-%' filled, NATIONAL total set.",
            "message_failed": "❌ Run failed. Check the log above (a stale Tableau/ownerville session usually clears on a retry), then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Pulls Fiber Lead Performance from Tableau and inserts this week's column (weekending = last Sunday). Re-running the same week overwrites that column.",
                "module": "automations.int_wow_penetration.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Run a Specific Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick any date in the target week; the weekending Sunday is computed automatically.",
                "module": "automations.int_wow_penetration.run",
                "args_fn": lambda d: ["--date", d.isoformat()],
            },
        ],
    },
    {
        "id": "org-sales-board",
        "name": "Alphalete Org Sales Board (Copy Tab)",
        "creator": "Megan",
        "emoji": "🏆",
        "color": "#10B981",
        "category": "📊 Metrics",
        "description": "Fills the Alphalete Org Sales Board COPY TAB — 7 daily product sections (Retail NL/Internet, Fiber, NDS, B2B, BOX, Retail JE) + all 10 captainship leaderboards from Tableau. Writes ONLY to the copy tab, never the live VA tab. The VAs no longer key their own tab, so this copy is the working board now.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills the Alphalete Org Sales Board: all 7 "
            "daily product sections (Retail NL, Retail Internet, ATT Fiber, "
            "ATT NDS, B2B, BOX, Retail JE) and all 10 captainship "
            "leaderboards.\n\n"
            "WHERE IT WRITES\n"
            "The **\"Alphalete ORG Sales Board\"** tab — the one and only board. "
            "It began as a sandbox copy of a tab the VAs keyed by hand; they "
            "stopped, so on 8/19 that old tab was archived + hidden and this "
            "one took the plain name. The daily board email + screenshots "
            "render from it.\n\n"
            "WHEN IT RUNS\n"
            "**Daily.** Only completed days fill; today + future stay blank.\n"
            "The weekly rollover fires **automatically on Tuesday** (the first "
            "run that day) — it freezes the finished week and shifts the 4-week "
            "history, then fills. It's keyed to the reporting week, so if "
            "**Tuesday's run is missed the next run rolls instead** (Wed, etc.) "
            "and still backfills every completed day. Nothing extra to do; "
            "re-running is safe (a no-op once that week is rolled).\n\n"
            "STILL MANUAL (not yet automated)\n"
            "Only **Frontier** (Verizon PDF) is keyed by hand now. **Retail JE** "
            "is automated — it pulls from Just Energy (Daily Sales by ICD) and "
            "auto-rolls to the current week (filled for the ICDs already on the "
            "board).\n\n"
            "ZERO-SALES ICDs\n"
            "An ICD with no sales this week shows **NS** — that's correct, and "
            "it fills the moment they sell."
        ),
        # Deep-links to the Alphalete ORG Sales Board tab this run fills.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"
                      "?gid=129523613#gid=129523613"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 20,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Org Sales Board (copy tab) filled — 7 daily sections + 10 captainships, by program.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Daily Fill (Copy Tab)",
                "icon": "▶",
                "primary": True,
                "help": "Fills the copy tab's 7 daily sections + 10 captainships for the completed days this week. On Tuesdays it rolls the week over first automatically. Copy tab only — never the live VA tab.",
                "module": "automations.org_sales_board.run",
                "args_fn": lambda: ["--step", "daily", "--with-captainships",
                                    "--skip-compare"],
            },
        ],
    },
    {
        "id": "sales-board-screenshot-email",
        "name": "Org. Sales Board Email",
        "creator": "Megan",
        "emoji": "📧",
        "color": "#DC2626",
        "category": "📊 Metrics",
        "description": "Emails exact-sheet screenshots of the Org Sales Board (copy tab) — Product Summary, the RAF ORG current-vs-prior summary, the ALPHALETE ORG leaderboard, the daily sections, every in-org captainship, and the RAF/CARLOS/COLTEN/BEN ORG summaries. Rendered via the Sheets PDF export (no browser). Automated + review-gated: builds the preview, posts it to #revision-emails as Lucy, and sends only on a ✅ from Evelyn.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Emails the Org Sales Board as clean, exact-sheet screenshots "
            "(colors/fonts/borders match the sheet). Rendered from the COPY tab "
            "via the Google Sheets PDF-export endpoint — no browser, runs from "
            "any machine.\n\n"
            "STATUS — LIVE, REVIEW-GATED (Eve, 7/29)\n"
            "Runs on the scheduler again. The automated run does NOT send: it "
            "builds the day's preview, prints the PDF, drops it in Drive, and "
            "posts the link in #revision-emails as Lucy. The email goes out only "
            "when Evelyn ✅'s that post — the org-board-email-review "
            "agent (9am-8pm) then mails the already-captured images. A partial "
            "board never sends (data-gated).\n\n"
            "RECIPIENTS\n"
            "Proving list (Rafael + Megan). Full distro (three Gmail groups — "
            "Alphalete Org Owners, Carlos' Captain Team, Raf's Captain Team) is "
            "flipped on by adding --distro to the review checker's args, not "
            "here.\n\n"
            "WHEN IT RUNS\n"
            "Tue-Sun, right after the morning Sales Board fill (fresh numbers). "
            "Monday runs in the afternoon at 2:30pm via the board catch-up job — "
            "Sunday's numbers only fully arrive Monday afternoon. It never runs "
            "in the 4am batch, so it lives under ⏰ TIME SET REPORTS.\n\n"
            "PILL — THREE PHASES\n"
            "One card for the whole chain: phase 1 = the board fill, phase 2 = "
            "this email posted for review, phase 3 = the ✅. The pill sits "
            "ORANGE once the fill lands, goes 🟣 PURPLE while the PDF waits in "
            "#revision-emails, and turns GREEN only on an approver's "
            "checkmark. A failed fill or a day with no ✅ never shows green."
        ),
        # Deep-links to the Alphalete ORG Sales Board tab this email renders.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"
                      "?gid=129523613#gid=129523613"),
        "assignees": ["Lucy 1"],
        # TWO-PHASE card (Megan 2026-08-03), same shape as Country Sales Board
        # Email: phase 1 = the board FILL (org-sales-board), phase 2 = THIS email
        # (sales-board-screenshot-email). Pill is ORANGE after the fill lands and
        # turns GREEN once the email actually sends (screenshot_email._publish_sent
        # → success row on the card's own id). Both reports still run separately;
        # this only merges the Hub display + drives the phase colors.
        # THIRD PHASE = THE APPROVAL (Megan 2026-08-10). The email row lands
        # when the gate POSTS the day's PDF for review, hours before anyone
        # reads it, so green used to mean "posted", not "sent".
        # "…-approved" is written only when review_gate --check finds an
        # authorised ✅ (shared/review_approval.py): PURPLE while it waits on
        # Evelyn, green on the checkmark that actually mails it.
        "phases": ["org-sales-board", "sales-board-screenshot-email",
                   "sales-board-screenshot-email-approved"],
        "approval_phase": "sales-board-screenshot-email-approved",
        # self_scheduled → renders under ⏰ TIME SET REPORTS (not the 4am MORNING
        # BATCH) because it never runs at 4am: Tue-Sun it posts mid-morning after
        # the board fill, and MONDAY it runs at 2:30pm via board-catchup (Sunday's
        # numbers only land Monday afternoon). Weekday-keyed time_label carries
        # each day's real timing on the tile — Mon shows 2:30 PM, Tue-Sun the AM
        # flow. All 7 keys set so the pill never falls back to the "· CST" default.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "~7:00 AM (send on Eve's checkmark)",   # real cadence since Eve's 8/12 rework — card said 9:30 (stale, Megan 2026-08-22)
            "time_label": {
                "0": "Mon 2:30 PM CST",
                "1": "AM flow · sends on ✅",
                "2": "AM flow · sends on ✅",
                "3": "AM flow · sends on ✅",
                "4": "AM flow · sends on ✅",
                "5": "AM flow · sends on ✅",
                "6": "AM flow · sends on ✅",
            },
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Sales Board screenshot email sent.",
            "message_failed": "❌ Send failed — check the log above, fix, then re-run.",
        },
        "actions": [
            {
                "label": "Send Email (Rafael + Megan)",
                "icon": "▶",
                "primary": True,
                "help": "Manual override — renders every section of the copy tab to exact-sheet images and emails them to the proving list (Rafael, Megan) right now, bypassing BOTH the fill-complete guard and the #revision-emails review checkmark. The normal automated run is review-gated; use this only when you want to push the day's email by hand. Takes a couple of minutes.",
                "module": "automations.org_sales_board.screenshot_email",
                "args_fn": lambda: ["--force"],
            },
        ],
    },
    # RETIRED 2026-07-21 (Megan): the "Org Sales Board — VA Compare" card was
    # pulled from the Hub. Eve now hand-verifies that the automation is correct
    # and isn't writing into the VA tab, so the 9am machine compare is redundant
    # — and it was crying wolf on rollover-day formula-drift (see compare.py).
    # The compare module (automations.org_sales_board.compare) is kept for manual
    # runs; only the tile + the 'board_compare' scheduler entry were removed.
    {
        "id": "org-sales-board-slack",
        # Name carries the DESTINATION CHANNEL; the tile appends "· 8:30 AM CST"
        # from `schedule`, so the card reads:
        #   "Org Sales Board → #top-leaders-alphalete-org · 8:30 AM CST"
        "name": "Org Sales Board → #top-leaders-alphalete-org",
        "creator": "Megan",
        "emoji": "📸",
        "color": "#0EA5E9",
        # 📊 Metrics (not Ops) so it lands in ⏰ TIME SET REPORTS with the other
        # self-scheduled runs rather than the OPS divider.
        "category": "📊 Metrics",
        "description": "Posts the daily Org Sales Board image to #top-leaders-alphalete-org as Lucy — the post Jolie used to make by hand every morning. Screenshots the live board (all 8 sections) exactly as it looks on the sheet and titles it with yesterday's date.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Reads the **live** `Alphalete ORG Sales Board` tab and finds "
            "the 8 daily sections (Retail NL → Retail Internet) automatically.\n"
            "**•** Renders them as **one image**, exactly as the sheet looks "
            "(same colors, Running/Last/Previous week columns).\n"
            "**•** Posts to **#top-leaders-alphalete-org** as Lucy, titled with "
            "**yesterday's** date — e.g. `• *Org Sales Board 7/17*`.\n"
            "**•** Posts **once per day**; the later passes do nothing.\n\n"
            "WHEN IT RUNS\n"
            "**Every day at 8:30am CST**, including weekends, retrying every "
            "25 min as a safety net.\n\n"
            "SAFETY GATE\n"
            "Holds only if yesterday is **entirely empty** across every section "
            "(board never updated). It does NOT wait for 100% — Retail JE and "
            "Frontier legitimately lag a day and the board still posts."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"
                      "?gid=388012799#gid=388012799"),
        "assignees": ["Lucy 1"],
        # Runs on the mini — that's where Lucy's Slack token lives. A play from
        # any machine routes there (a laptop run would post as Megan, not Lucy).
        "run_machine": "Lucy 1",
        "run_rerun_id": "org_board_slack",
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "~6:55 AM (after fill + Box)",   # real cadence since Eve's 8/12 rework — card said 8:30 (stale, Megan 2026-08-22)
            "estimated_minutes": 2,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Org Sales Board posted to #top-leaders-alphalete-org.",
            "message_failed": "❌ Run failed. Check the log above, then run again.",
        },
        "actions": [
            {
                "label": "Post Now",
                "icon": "▶",
                "primary": True,
                "help": "Renders today's board and POSTS it to #top-leaders-alphalete-org as Lucy.",
                "module": "automations.org_sales_board.slack_post",
                "args_fn": lambda: ["--post"],
            },
        ],
    },
    # The two board EMAILS (Eve 2026-07-30). Same machinery as the Org Sales
    # Board email above — capture, post for review, send on a checkmark — but
    # one module (automations.board_emails) driving both boards.
    {
        "id": "all-units-board",
        "name": "All Units Org Sales Board",
        "creator": "Eve & Claude",
        "emoji": "📦",
        "color": "#7C3AED",
        "category": "📊 Metrics",
        "description": "Fills the 'All Campaigns Org Sales Board' tab: every rep's daily units summed across ALL campaigns, one line per person. Its screenshot rides in the Org Sales Board email — this board no longer sends a mail of its own.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads the eight campaign daily sections off the ORG board's Copy "
            "tab, sums each rep across all of them, and writes the Mon-Sun day "
            "values into this board's 'All Units' section. Everything else on "
            "the tab is formula-driven and auto-derives: running week total, "
            "the weekly leaderboard column, Product Summary, vs-Prior and the "
            "Grand Total.\n\n"
            "SHEET-DRIVEN\n"
            "Fills every rep row already on the board (0 if they had no sales) "
            "and never transcribes the source name list. A rep who sold on a "
            "campaign but has NO row here is FLAGGED, not silently dropped, so "
            "a new rep can't vanish from the ranking.\n\n"
            "ITS EMAIL LIVES IN THE ORG BOARD EMAIL (2026-07-31)\n"
            "This board used to mail Rafael + Maud on its own, behind its own "
            "#revision-emails gate. Eve merged the two: its four blocks are now "
            "a second section of the Alphalete Org Sales Board email, under a "
            "divider, and one checkmark releases both. Use the Org Sales Board "
            "Email card to build or send it — there is nothing to send "
            "here.\n\n"
            "RUNS AFTER THE ORG BOARD\n"
            "It reads what the ORG board's fill just wrote, so it is scheduled "
            "behind it and would show yesterday's numbers if run first."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/"
                      "edit?gid=546263838"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Board filled. Its screenshot goes out inside the Org Sales Board email.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Fill the board",
                "icon": "▶",
                "primary": True,
                "help": "Writes today's per-rep day values to the board (and rolls the week over on a Tuesday).",
                "module": "automations.all_campaigns_board.run",
                "args_fn": lambda: ["--apply", "--enable-rollover"],
            },
            {
                "label": "Preview only (no writes)",
                "icon": "👁",
                "help": "Shows exactly what would be written and touches nothing. This is the module's default.",
                "module": "automations.all_campaigns_board.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "reps-gross-paycheck",
        "name": "Reps Gross Paycheck records",
        "creator": "Eve & Claude",
        "emoji": "💵",
        "color": "#15803D",
        "category": "📊 Metrics",
        "description": "Fills each rep's 'Gross Paycheck' row in the Rep Records workbook from 'Got Paid' in Raf PNL 2026 — always ONE WEEK behind, because Thursday's paycheck is last week's settlement. Adds tabs for new reps, removes them for terminated ones.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Puts each rep's paycheck in the column headed with **this "
            "week's Sunday**, taking it from the PNL's **previous** Sunday. "
            "Run it Thursday **8/6** and the **8/9** column gets the PNL's "
            "**8/2** 'Got Paid' — what they collect that Thursday is what "
            "settled the week before.\n"
            "**•** A rep with **no money** that week gets a **'-'**, never a "
            "blank, so \"checked, nothing to pay\" can't be mistaken for "
            "\"nobody ran it\".\n"
            "**•** **New reps get a tab.** The signal is **Field Status = "
            "2nd Wk** on the newest sales board. The tab is cloned from the "
            "most recent rep tab, so it matches the ones beside it.\n"
            "**•** **Terminated reps lose theirs**, on **two** signals: a "
            "filled **Termination Date** on the sales board (*not* Field "
            "Status, which never says 'Terminated'), or a row in the PNL "
            "workbook's **Terminated Reps** log for someone who's also off the "
            "newest board. Neither list is complete alone — the board leaves "
            "the date blank for people who just stop showing up, and the log "
            "keeps a stale row for anyone who came back. Their cells are left "
            "untouched and the tab is saved to a CSV in "
            "**output/reps_gross_paycheck/deleted/** before it goes.\n"
            "**•** A tab that has run out of week columns grows by one "
            "'=previous+7', so the header dates stay in step.\n\n"
            "WHEN IT RUNS\n"
            "**Thursday, 9:00 AM Central.**\n\n"
            "IT NEVER OVERWRITES\n"
            "A cell that already carries something is left alone and counted "
            "in the summary. Re-running the same Thursday changes nothing.\n\n"
            "CATCHING UP\n"
            "**Backfill** fills every week from **6/28** through this one in a "
            "single pass — use it after a stretch of missed Thursdays.\n\n"
            "NAMES THAT DON'T MATCH\n"
            "A rep whose PNL spelling differs from their tab quietly fills "
            "'-'. Every one of those is listed at the end of the run with the "
            "closest PNL name; one row in "
            "**automations/reps_gross_paycheck/aliases.json** fixes it "
            "permanently."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1einjzUF1C4MzosbZPxDsAKpGZCi2ud4ckaD8L2gqaXM/edit"),
        "assignees": ["Lucy 1"],
        "run_rerun_id": "reps_gross_paycheck",
        "schedule": {
            "frequency": "weekly",
            "weekdays": [3],            # Thursday
            "time": "9:00 AM",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Paychecks written. Check the log for any '-' that should have been a number — that's a name spelling drift.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Preview (no writes)",
                "icon": "👁",
                "primary": True,
                "help": "Reads all three workbooks and prints exactly what would change — every cell, every tab it would add, every tab it would delete. Writes nothing.",
                "module": "automations.reps_gross_paycheck.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Fill This Week",
                "icon": "▶",
                "help": "Writes this week's column on the real workbook and adds tabs for the new (2nd Wk) reps. Terminated tabs are listed but NOT deleted.",
                "module": "automations.reps_gross_paycheck.run",
                "args_fn": lambda: ["--real", "--i-mean-it"],
            },
            {
                "label": "Fill + Remove Terminated",
                "icon": "🗑",
                "help": "The same fill, and it also DELETES the tabs of reps with a Termination Date on the sales board. Each deleted tab is saved to output/reps_gross_paycheck/deleted/ as a CSV first — that snapshot is the only way back. Preview it before using this.",
                "module": "automations.reps_gross_paycheck.run",
                "args_fn": lambda: ["--real", "--i-mean-it", "--delete-terminated"],
            },
            {
                "label": "Backfill from 6/28",
                "icon": "⏪",
                "help": "Fills every week from 6/28 through this one, plus a tab for every rep on the newest sales board who hasn't got one. Cells that already carry something are left alone.",
                "module": "automations.reps_gross_paycheck.run",
                "args_fn": lambda: ["--real", "--i-mean-it", "--backfill",
                                    "--all-missing-tabs"],
            },
        ],
    },
    {
        "id": "alphalete-sales-board",
        # Named for what a person SEES it do: it texts the chats. "Alphalete
        # Sales Board sweep" read like a board fill and nobody could place it
        # when its alert appeared in #claudecorrections (Megan 2026-08-26).
        # The card ID is unchanged — it keys the Ops pill CSS and the Hub
        # Activity rows.
        "name": "Sales Text Updates",
        "creator": "Claude",
        # Ops, not Metrics: this is an always-on background job (every 5 min,
        # 10:00-21:30) like rc-autoread and sara-plus-issues, not a report that
        # runs once and is read. The category is what puts it under the OPS
        # divider; the amber pill is a SEPARATE per-card-id CSS rule in
        # dashboard.py -- `color` here does not drive the tile.
        "emoji": "\U0001F4C8",
        "color": "#F59E0B",
        "category": "\U0001F4F2 Ops",
        "description": (
            "Every 5 minutes of the selling day, reads SaraPlus for today's "
            "sales and fills the day's Int / Int Up / DTV / NL on the current "
            "'Sales Board WE m.d' tab \u2014 then texts the leaderboard and "
            "posts the hype in #alphalete-sales when something new lands."
        ),
        "breakdown": (
            "WHERE THE NUMBERS COME FROM \u2014 three SaraPlus passes\n"
            "**\u2022** ui.saraplus.com \u2192 **ReportingHub** \u2192 Order "
            "Dashboard, dated to the ONE day, read three times because no "
            "single Service filter carries everything: **AT&T** gives Internet "
            "/ Upgrades / AIA / Wireless Lines, **All** is the only view with "
            "**DTV**, and **AT&T Internet** gives **Records** (credit checks).\n"
            "**\u2022** The board's four columns are worked out from those: "
            "**Int** = Internet \u2212 Upgrades \u2212 AIA, **Int Up** = "
            "Upgrades + AIA, **DTV**, **NL** = Wireless Lines. SaraPlus's "
            "Internet total already contains the upgrades, so adding instead "
            "of subtracting would count each upgrade twice.\n\n"
            "WHAT IT WILL NOT TOUCH\n"
            "**Apps** (a formula) and **Roll Call**, any day that carries a "
            "roll-call letter (X / T / RT / STF \u2026), any day but **today**, "
            "and it never blanks a cell that holds a number \u2014 a short "
            "SaraPlus export is not evidence a sale didn't happen.\n\n"
            "WHO HEARS ABOUT IT\n"
            "**\u2022** **Alphalete Partners** \u2014 the full leaderboard on "
            "every sweep that finds a new sale, so the owners watch the day "
            "fill in. This is also the only chat told when a rep sold with no "
            "row on the board, or was added to one.\n"
            "**\u2022** **Alphalete lvl 1's** *and* **Alphalete A-Team Chat** "
            "\u2014 the same leaderboard once a day at the end of selling, "
            "Mon\u2013Fri **8:00pm** / Sat **4:00pm**. Same numbers, without "
            "the roster paperwork.\n"
            "**\u2022** **#alphalete-sales** \u2014 a hype line per sale, "
            "sized to the sale (an Int plus 5+ new lines shouts louder than a "
            "single unit), **and a credit-check heads-up**: "
            "*\u201cEdgar Camunez just ran 1 credit check (5 today).\u201d* A "
            "credit check is one step BEFORE a confirmed sale \u2014 early "
            "news only, and never written to the board.\n\n"
            "NEW MEANS AN INCREASE\n"
            "SaraPlus is cumulative within a day, so a sale is a count going "
            "UP against the previous sweep. A number that drops is treated as "
            "no news \u2014 not as a reset \u2014 so a hiccup can't "
            "re-announce the whole day.\n\n"
            "RUNS ON LUCY 1\n"
            "Not on load \u2014 Lucy 1 is the busiest box \u2014 but because "
            "the two iMessage groups only exist in its Messages. The load is "
            "fenced instead: its own Chrome profile, headless, nothing before "
            "7:00am, and a pid lock so a slow sweep is skipped rather than "
            "stacked. The Hub pill is painted by the first good sweep of the "
            "day, not by all 150."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc/edit"),
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "alphalete_sales_board",
        "schedule": {
            "frequency": "daily",
            "estimated_minutes": 2,
        },
        "checklist": [],
        "post_run": {
            "message_success": "\u2705 Sweep done \u2014 today's block is up to date on the sales board.",
            "message_failed": "\u274C Sweep failed. `lucy logtail alphalete-sales-board` on Lucy 1 to see why.",
        },
        "actions": [
            {
                "label": "Preview (no writes)",
                "icon": "\U0001F441",
                "primary": True,
                "help": "Reads SaraPlus and prints the cells that WOULD change and the messages that WOULD go out. Writes nothing, texts nobody.",
                "module": "automations.alphalete_sales_board.run",
                "args_fn": lambda: ["--force"],
            },
            {
                "label": "Sweep now (write the board)",
                "icon": "\u25B6",
                "help": "Runs one sweep for real: fills today's Int / Int Up / DTV / NL. Sends no texts and no Slack.",
                "module": "automations.alphalete_sales_board.run",
                "args_fn": lambda: ["--apply", "--force"],
            },
            {
                "label": "Sweep now + notify",
                "icon": "\U0001F4E3",
                "help": "One full sweep: writes the board AND sends the leaderboard text plus the Slack hype for anything new since the last sweep.",
                "module": "automations.alphalete_sales_board.run",
                "args_fn": lambda: ["--apply", "--send", "--force"],
            },
        ],
    },
    {
        "id": "gap-alerts",
        "name": "Rep Gap Alerts (15-min gaps)",
        "creator": "Claude",
        "emoji": "\u23F1\uFE0F",
        "color": "#B91C1C",
        "category": "\U0001F4CA Metrics",
        "description": (
            "Every 5 minutes of the selling day, texts the "
            "\u201cReps Over 15 Min Gap\u201d card for Raf\u2019s office into "
            "the **Alphalete Partners** chat \u2014 who has gone quiet, how "
            "long, and when they last knocked. Nothing else: no activity "
            "panel, no Slack, no thread."
        ),
        "breakdown": (
            "WHERE THE NUMBERS COME FROM\n"
            "**\u2022** v2.ownerville.com \u2192 **Time Tracker (p=510)** "
            "\u2192 its own JSON feed "
            "(`report_timeTracker.cfc?method=getTimeTrackingData`), dated to "
            "TODAY, campaign pinned to **RES AT&T** "
            "(`invD2DClientId=3`).\n"
            "**\u2022** A rep is on the card when **minutesSinceLastKnock > "
            "15** \u2014 the same threshold Carlos\u2019s B2B card has used "
            "since July, so both offices mean the same thing by "
            "\u201cinactive\u201d.\n"
            "**\u2022** The card is REDRAWN from that data, not screenshotted: "
            "OwnerVille\u2019s live gap widget never renders under the "
            "automation browser (only a hidden template loads).\n\n"
            "SORTED BY WHO HAS BEEN DARK LONGEST\n"
            "Not alphabetically like the B2B card. On a five-minute tick the "
            "rep who has been quiet two hours is the point of the message, and "
            "a phone shows the top of a picture.\n\n"
            "NEVER TWO CARDS BACK TO BACK\n"
            "A card is refused if the chat got one less than **4 minutes** ago, "
            "whoever asked for it. The 5-minute cadence is not the risk \u2014 "
            "a launchd job fires the moment it is reloaded and again after a "
            "wake, and the button above runs on top of whatever the schedule is "
            "already doing. Two near-identical cards two minutes apart is how a "
            "room learns to stop reading them.\n\n"
            "IT WILL NOT TEXT AN EMPTY CARD\n"
            "Nobody over the threshold is good news, not news \u2014 and a "
            "\u201cno reps over 15 min gap\u201d picture every five minutes "
            "is how a room learns to mute the alert that matters.\n\n"
            "THE DAY\n"
            "**\u2022** **Mon\u2013Fri 1:30pm \u2013 8:30pm**\n"
            "**\u2022** **Saturday 10:00am \u2013 5:00pm** \u2014 its own "
            "START, not just its own end: Saturday is the one day the field is "
            "out in the morning.\n"
            "**\u2022** **Sunday** off entirely.\n"
            "The end matters more than the start: once the field stops "
            "knocking EVERY rep reads \u201cinactive 90 min ago\u201d and the "
            "card degenerates into the whole roster.\n\n"
            "RUNS ON LUCY 1\n"
            "Because that is the machine iMessage is set up on \u2014 the "
            "Partners chat exists only in its Messages. The room is resolved "
            "by NAME on every send, never a stored chat id, so a failure reads "
            "as \u201cLucy was removed from the chat\u201d. Load is fenced: "
            "its own browser profile, headless, one JSON call a tick, a pid "
            "lock so a slow tick is skipped rather than stacked. The Hub pill is "
            "painted by the first good tick of "
            "the day, not by all 96."
        ),
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "gap_alerts",
        "schedule": {
            "frequency": "daily",
            "estimated_minutes": 1,
        },
        "checklist": [],
        "post_run": {
            "message_success": "\u2705 Tick done \u2014 the gap card is current.",
            "message_failed": "\u274C Tick failed. `lucy logtail gap-alerts` on Lucy 1 to see why.",
        },
        "actions": [
            {
                "label": "Preview (texts nobody)",
                "icon": "\U0001F441",
                "primary": True,
                "help": "Pulls the Time Tracker, renders the card, and resolves the Alphalete Partners chat so you can see it is still reachable. Sends nothing.",
                "module": "automations.gap_alerts.run",
                "args_fn": lambda: ["--force"],
            },
            {
                "label": "Text it now",
                "icon": "\U0001F4E3",
                "help": "One tick for real: renders the current gap card and texts it to the Alphalete Partners chat. Skips if nobody is over 15 minutes, or if the chat already got a card in the last 4 minutes.",
                "module": "automations.gap_alerts.run",
                "args_fn": lambda: ["--send", "--force"],
            },
            {
                "label": "Show the raw rows",
                "icon": "\U0001F50E",
                "help": "READ-ONLY: dumps what the Time Tracker feed returns right now (name, minutes since last knock, last knock time). For when the card looks wrong or comes back empty.",
                "module": "automations.gap_alerts.run",
                "args_fn": lambda: ["--probe"],
            },
        ],
    },
    {
        "id": "terminated-reps",
        "name": "Terminated Reps",
        "creator": "Eve & Claude",
        "emoji": "🚪",
        "color": "#B45309",
        "category": "📊 Metrics",
        "description": (
            "Reads this week's tab on the Alphalete SALES BOARD 2025, files "
            "every newly-terminated rep into 'Terminated Reps' on the Raf "
            "tracker, and posts the day's list in #revision-emails inside that "
            "week's thread. Live on the real tab."
        ),
        "breakdown": (
            "WHERE THE TERMINATIONS COME FROM — two places, marked two ways\n"
            "**•** **The roster** (top of the tab): terminated = the rep's "
            "**Termination Date** column is filled in. **# Days Worked** is "
            "read from the board's own formula, never recomputed.\n"
            "**•** **The 'New Starts/Raf' box** (bottom): terminated = the "
            "first weekday roll-call cell reading **Terminated**. That "
            "weekday gives both the date and the day count — a new start's "
            "week begins Monday.\n"
            "Miss either one and half the terminations go unfiled: the roster "
            "never says the word 'Terminated', and new starts never get a "
            "Termination Date.\n\n"
            "WHAT IT WRITES\n"
            "**Rep Name**, **Lead Rep** (always *Raf*), **# Days Worked**, "
            "**Termination Date**, **Year**. It does **not** touch "
            "**Ownerville** or **Slack Deact** — those checkboxes record that "
            "a human went and deactivated the accounts, so they stay unticked "
            "for you.\n\n"
            "WHERE IT APPENDS\n"
            "Straight after the **last filled name**. The tab has thousands of "
            "pre-seeded checkbox rows below that, plus one hole mid-history "
            "(row 1979, a cleared name), and both would swallow an append that "
            "just looked for the first empty row.\n\n"
            "THE SLACK THREAD\n"
            "One parent per week in **#revision-emails** — **'Terminated Reps WE 8.9'** — with each "
            "day's terminations posted as a reply inside it. The post lists what the BOARD says was terminated that day, not what the run happened to file, so a row you entered by hand still shows up. A new week starts "
            "a new thread. A day with nobody terminated posts nothing, and a "
            "week with nobody never opens a thread.\n\n"
            "IT READS TWO WEEK TABS\n"
            "A new week tab appears every **Monday**, and the weekend's "
            "roll-call keeps being filled in on the **old** one afterwards — "
            "so the previous tab is read too (bounded to the last 4 days). "
            "Without it, a rep marked on Monday against Saturday is never "
            "filed by anyone.\n\n"
            "RUNNING IT TWICE IS FREE\n"
            "Rows are deduped on **name + termination date**, ±1 day (the same "
            "person can legitimately appear twice — rehired, then let go "
            "again — but never twice inside a day), and the Slack reply skips "
            "anyone already named in this week's thread. A second pass the "
            "same day writes nothing and posts nothing."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=835099438#gid=835099438"),
        "assignees": ["Lucy 1"],
        "run_rerun_id": "terminated_reps",
        "schedule": {
            "frequency": "daily",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Terminated Reps read — anything new is filed and the day is posted in #revision-emails.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Files any new terminations into the REAL 'Terminated Reps' tab and posts the day in #revision-emails. Safe to click twice — it dedupes against both the tab and the thread.",
                "module": "automations.terminated_reps.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Preview (no writes)",
                "icon": "👁",
                "help": "Reads the board and prints who WOULD be filed and the message that would go to #revision-emails. Writes nothing, posts nothing.",
                "module": "automations.terminated_reps.run",
                "args_fn": lambda: ["--dry-run"],
            },
            {
                "label": "Run on the sandbox tab",
                "icon": "🧪",
                "help": "Writes to a duplicate 'Terminated Reps SANDBOX' tab in the same workbook (created on first use) and doesn't post to Slack. For testing a change before it goes near the real tab.",
                "module": "automations.terminated_reps.run",
                "args_fn": lambda: ["--sandbox"],
            },
        ],
    },
    {
        "id": "mobrium-list",
        "name": "Mobrium List",
        "creator": "Eve & Claude",
        "emoji": "⭐",
        "color": "#7C3AED",
        "category": "📊 Metrics",
        "description": (
            "Friday 10am: drops the reps who are gone off the 'Mobrium List' "
            "tab and adds the week's new starts, with their email and phone "
            "pulled from OwnerVille. Live on the real tab."
        ),
        "breakdown": (
            "WHO COMES OFF\n"
            "Anyone the **'Terminated Reps'** tab or this week's **SALES "
            "BOARD** names as terminated — unless one of two things says "
            "otherwise:\n"
            "**•** Their tracker **Notes** say **FFP**. Those stay, by your "
            "rule.\n"
            "**•** OwnerVille still lists them as an active rep **and** the "
            "termination is at least a week old. That's a rehire — Tadana "
            "Manyangadze was let go in May and is training new starts now.\n"
            "The one-week floor is what stops a same-day termination from "
            "reading as a rehire: OwnerVille takes a day or two to retire "
            "somebody, so for a few hours they look terminated *and* active.\n\n"
            "WHO GOES ON\n"
            "Everybody in the board's **'New Starts/Raf'** box who isn't on "
            "the list yet and isn't already terminated. They're **inserted in "
            "first-name order**, not appended — the tab is sorted and an "
            "append would show.\n\n"
            "WHERE THE EMAIL AND PHONE COME FROM\n"
            "**OwnerVille → Sales Reps** (the p=20 page), which is the only "
            "place the phone numbers exist and the only trustworthy place for "
            "the email. The board's own email column **drifts out of step "
            "with its names** — on WE 8.9, David Redmon's row carried Carlo "
            "Ferrino's address — so it's only used for someone OwnerVille has "
            "never heard of, and only when the address plausibly belongs to "
            "them. Anyone left without details is still added, and named at "
            "the end of the run so you can fill them in.\n\n"
            "RUNNING IT TWICE IS FREE\n"
            "A second pass the same day finds nothing to remove and nobody "
            "new, and says so. Every run — preview included — writes the "
            "tab's before-state to **output/mobrium_list/**, which is the only "
            "undo for a deleted row."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=1978603621#gid=1978603621"),
        "assignees": ["Lucy 1"],
        "run_rerun_id": "mobrium_list",
        "schedule": {
            "frequency": "weekly",
            "day": "Friday",
            "time": "10:00 AM",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Mobrium List updated — terminated reps removed, this week's new starts added.",
            "message_failed": "❌ Run failed. Check the log above — nothing was written unless it says otherwise.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Updates the REAL 'Mobrium List' tab: removes the terminated, adds this week's new starts. Rows get DELETED — the before-state is saved to output/mobrium_list/ first. Safe to click twice.",
                "module": "automations.mobrium_list.run",
                "args_fn": lambda: ["--real", "--i-mean-it"],
            },
            {
                "label": "Preview (no writes)",
                "icon": "👁",
                "help": "Prints exactly who would come off, who would go on, and where each email and phone came from. Touches nothing.",
                "module": "automations.mobrium_list.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Run on the sandbox tab",
                "icon": "🧪",
                "help": "Does the whole job for real on a duplicate 'Mobrium List SANDBOX' tab in the same workbook. The only way to actually watch it delete and insert without risking the live list.",
                "module": "automations.mobrium_list.run",
                "args_fn": lambda: ["--sandbox", "--fresh-sandbox"],
            },
        ],
    },
    {
        "id": "country-sales-board",
        "name": "Country Sales Board",
        "creator": "Eve & Claude",
        "emoji": "🌎",
        "color": "#0D9488",
        "category": "📊 Metrics",
        "description": "Two phases on one card: (1) the 4am fill writes the Country Sales Board tab from Tableau and rolls the week over every Tuesday — the REAL tab the country reads; (2) at 9:30 AM an exact-sheet screenshot is emailed to Rafael & Maud, after Evelyn ✅s it in #revision-emails. The pill is orange after the fill, 🟣 purple while it waits for the ✅, and green only on the approval.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls the D2D **'This Week'** crosstab and writes only the "
            "**Mon-Sun day cells** on the real Country Sales Board tab. "
            "Everything else (leaderboard, totals, summary) is formula-driven. "
            "A rep with no sales gets a real **0**, never a blank.\n\n"
            "WHEN IT RUNS\n"
            "**Daily in the 4am flow**, right after the Org Sales Board fill "
            "(completed days only). On **Tuesday** the first run **auto-rolls "
            "the week** — "
            "snapshotting to a backup tab first; if Tuesday is missed the next "
            "run rolls instead, and re-running is safe. ⚠️ The VAs must **not** "
            "also roll this tab — two rollovers corrupt the leaderboard; restore "
            "from the backup tab if it happens.\n\n"
            "SELF-CHECK\n"
            "After writing, it confirms **yesterday** carries numbers; a "
            "blank/zero day **fails on purpose** so you get an alert, not a "
            "silently empty board. Unmatched names fill **0** and are flagged — "
            "fix a selling rep's spelling drift on the **ICD Aliases** sheet.\n\n"
            "PHASE 2 — 9:30 AM EMAIL\n"
            "After the fill, a second step emails an exact-sheet screenshot "
            "(board + per-day delta chart) to **Rafael + Maud**. It posts the "
            "day's image in **#revision-emails** (not before 9:30) and sends "
            "nothing until **Evelyn** ✅s it — the mini's watcher picks "
            "up the approval within 15 min and mails exactly what was approved. "
            "The card's pill turns **green** on that ✅; while the image is "
            "posted and waiting it sits 🟣 **purple** (*awaiting ✅*), and it is "
            "**orange** before that (fill done, nothing posted yet)."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE/edit"
                      "?gid=1121646560#gid=1121646560"),
        "assignees": ["Lucy 1"],
        # Needs the warm ownerville/Tableau session, which lives on the runner.
        "run_machine": "Lucy 1",
        "run_rerun_id": "country_sales_board",
        # TWO-PHASE card (Megan 2026-08-02): phase 1 = the 4am fill, phase 2 =
        # the 9:30am screenshot email. One card for the chained pair instead of
        # two. Reports still run separately; this only merges the Hub display.
        # Phase 2's id is the UNDERSCORE form `country_sales_board_email` — that is
        # what the email actually publishes to Hub Activity since it became an
        # orchestrator-materialized card (verified 2026-08-07: it stores underscore,
        # last hyphen row was 8/2). With the old hyphen here the phase never matched
        # and the pill sat stuck at 1/2 (orange) even after a clean send. The
        # phase-list string must match the stored Report ID EXACTLY — there is no
        # normalization in _week_run_statuses. (Megan 2026-08-07)
        # THIRD PHASE = THE APPROVAL (Megan 2026-08-10) — same shape as the Org
        # board card. Phase 2 lands when the day's image is POSTED for review,
        # so green used to mean "posted". "…-approved" is written only when
        # review_gate --check finds Evelyn's ✅
        # (shared/review_approval.py): PURPLE while it waits, green on the ✅.
        # This one IS hyphenated and that is not an oversight — the gate writes
        # it straight to Hub Activity (no resolve_card in the path), so the
        # stored id is exactly `<board.report_id>-approved`.
        "phases": ["country-sales-board", "country_sales_board_email",
                   "country-sales-board-email-approved"],
        "approval_phase": "country-sales-board-email-approved",
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Country Sales Board filled — day cells written, leaderboard and summary re-derived.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Daily Fill",
                "icon": "▶",
                "primary": True,
                "help": "Pulls the D2D 'This Week' crosstab and fills the completed days on the real Country Sales Board tab. On Tuesdays it rolls the week over first (snapshotting the tab beforehand).",
                "module": "automations.country_sales_board.run",
                "args_fn": lambda: ["--real", "--i-mean-it", "--enable-rollover"],
            },
        ],
    },
    {
        "id": "att-owners-list",
        "name": "ATT Owners List (weekly roster)",
        "creator": "Eve & Claude",
        "emoji": "🧾",
        "color": "#7C3AED",
        "category": "📊 Metrics",
        "description": "Every Friday: fills last week's column on the 'ATT owners list' tab from Tableau, marks who joined the program and who didn't sell, posts the summary in #revision-emails, and seeds any new owner into all three Country Sales Board boxes.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Downloads the crosstab from **ATT Tracker 2.1 - D2D / "
            "D2D 1-PAGERV2 (Internet Only)** — the worksheet behind the "
            "**'D2D PAGE 2 LAST WEEK'** page — so it always reads the week that "
            "CLOSED, never the one in progress.\n"
            "**•** Fills that week's column on the **ATT owners list** tab: the "
            "person's name where they sold, a **red** blank where they didn't, "
            "and a brand-new **yellow** row for anyone who has never been on "
            "the list.\n"
            "**•** Posts to **#revision-emails**: who joined, who came back "
            "after a gap, and who had no sales.\n"
            "**•** Adds every brand-new owner to **all three Country Sales "
            "Board boxes** (leaderboard, daily breakdown, delta chart) so their "
            "sales have a row to land in the next morning.\n\n"
            "THE COLOURS MEAN SOMETHING\n"
            "**Yellow** = not in the program yet / the week they joined. "
            "**Red** = was in the program, no sales this week. Nobody is ever "
            "removed — the weeks beside a red cell are how you tell a quiet "
            "week from someone who left.\n\n"
            "WHEN IT RUNS\n"
            "**Fridays**, for the week ending the previous Sunday. Re-running "
            "the same week is safe: it rewrites the same column and says so.\n\n"
            "IT REFUSES RATHER THAN GUESS\n"
            "The Tableau worksheet is pinned to a RELATIVE week, so the run "
            "reads the dates back out of the export and **stops** if they "
            "aren't the week it meant to fill. It also stops if the column "
            "already holds different names than the pull — that means somebody "
            "filled it by hand (`--overwrite` to replace it anyway).\n\n"
            "THE HISTORY HAD A CROOKED PATCH\n"
            "The 4/19 and 4/26 columns were once pasted one row low, which left "
            "56 rows holding two different people. **Realign history** fixes it "
            "losslessly — it re-lays the same names so every row is one person "
            "and refuses to write unless every column's name set comes out "
            "identical."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE/edit"
                      "?gid=601599943#gid=601599943"),
        "assignees": ["Lucy 1"],
        # Needs the warm ownerville/Tableau session, which lives on the runner.
        "run_machine": "Lucy 1",
        "run_rerun_id": "att_owners_list",
        "schedule": {
            "frequency": "weekly",
            "day": "Friday",
            "time": "8:00 AM",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ ATT Owners List filled — new owners marked yellow, non-sellers red, note posted in #revision-emails.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run the week",
                "icon": "▶",
                "primary": True,
                "help": "Fills last week's column on the REAL tab, adds new owners to the Country Sales Board, and posts the summary in #revision-emails.",
                "module": "automations.att_owners_list.run",
                "args_fn": lambda: ["--post"],
            },
            {
                "label": "Preview (no writes, no post)",
                "icon": "👁",
                "help": "Same Tableau pull, but prints the planned column and the Slack message instead of writing or sending. Safe any time.",
                "module": "automations.att_owners_list.run",
                "args_fn": lambda: ["--dry-run"],
            },
            {
                "label": "Run on a sandbox copy",
                "icon": "🧪",
                "help": "Duplicates the tab to 'ATT owners list (sandbox)' (created on first use) and writes there instead, plus the sandbox Country Sales Board. Still only prints the Slack message.",
                "module": "automations.att_owners_list.run",
                "args_fn": lambda: ["--sandbox"],
            },
            {
                "label": "Realign history (one-off)",
                "icon": "🩹",
                "help": "Re-lays the whole tab so every row is ONE person, fixing the 4/19-4/26 paste damage. Backs up to output/ first and refuses if any column's name set would change.",
                "module": "automations.att_owners_list.run",
                "args_fn": lambda: ["--rebuild", "--overwrite"],
            },
        ],
    },
    {
        "id": "sci-campaigns",
        "name": "SCI Campaigns",
        "creator": "Eve & Claude",
        "emoji": "📡",
        "color": "#B91C1C",
        "category": "📊 Metrics",
        "description": "Fills the SCI Campaigns tab from Adriana Nowrouzi's weekly 'Residential Telecom Tracker – RANKED' email — one column per week ending, 13 campaign rows. Writes the REAL tab and posts a 'SCI Campaigns - WE M/D Complete' note in #l10-alphalete (tagging Raf & Maud) when the week lands.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills the SCI Campaigns tab from Adriana's weekly **'Residential "
            "Telecom Tracker – RANKED'** email — one column per week-ending, all "
            "**13 campaign rows** (pulled from the email's two PDFs). When a week "
            "lands it posts **'SCI Campaigns - WE M/D Complete'** in "
            "**#l10-alphalete** and tags **Raf & Maud** in a reply (moved off the "
            "group DM at Raf's request, 2026-08-04).\n\n"
            "WHEN IT RUNS\n"
            "**Friday, Saturday & Sunday.** It reads the week off the email "
            "subject and fills any tracker week not yet on the tab — so a late "
            "email heals itself on the next run, and re-running is safe. Sunday "
            "is there because Adriana's send has twice landed on one."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"
                      "?gid=1118523233#gid=1118523233"),
        "assignees": ["Lucy 1"],
        # Week-grid blue 'scanned' pill wording: this card's scan is an inbox
        # check for Adriana's tracker email, so an empty scan means no new email
        # (either none arrived or every week it holds is already on the tab).
        "scan_empty_label": "no new email",
        # The 'complete' note posts to #l10-alphalete as Lucy via the xoxp user
        # token, which on the mini IS Lucy — so the run has to happen there or the
        # post lands under whoever clicked Run instead.
        "run_machine": "Lucy 1",
        "run_rerun_id": "sci_campaigns",
        "schedule": {
            "frequency": "weekly",
            # Fri + Sat + Sun: a late send gets two more shots. Sunday added
            # 2026-07-31 — WE 6.27 arrived Sun 7/5 and WE 7.18 Sun 7/26, and a
            # Fri+Sat cadence can't see either until the NEXT Friday.
            "weekdays": [4, 5, 6],
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ SCI Campaigns filled — every tracker week in the inbox is on the tab.",
            "message_failed": "❌ Run failed. Check the log above — a missing PDF attachment is the usual cause.",
        },
        "actions": [
            {
                "label": "Run Weekly Fill",
                "icon": "▶",
                "primary": True,
                "help": "Fills every tracker week not yet on the real tab, then posts 'SCI Campaigns - WE M/D Complete' in #l10-alphalete and tags Raf & Maud in a reply. Safe to re-run — already-filled weeks are skipped and no note is posted for them.",
                "module": "automations.sci_campaigns.run",
                "args_fn": lambda: ["--real", "--i-mean-it", "--notify"],
            },
            {
                "label": "What's in the inbox?",
                "icon": "📥",
                "help": "Lists every tracker week Adriana has sent, the tab column it maps to, and whether it's filled yet.",
                "module": "automations.sci_campaigns.run",
                "args_fn": lambda: ["--real", "--i-mean-it", "--list"],
            },
        ],
    },
    {
        "id": "dd-bulletin",
        # Thursday's bulletin, so it sits directly before the Friday Override
        # Bulletin — which in turn stays adjacent to the PNL card below it.
        "name": "DD Bulletin → #alphalete-sales + #alphalete-lvl1-chat",
        "creator": "Megan & Claude",
        "emoji": "\U0001F3C6",
        # Same gold as the Override Bulletin — they are the same artwork family.
        "color": "#B45309",
        "category": "\U0001F4CA Metrics",
        "description": "Builds the weekly two-page Organization Bulletin from the Org DDs Ongoing Report — the ORG. TOTAL DD headline, the Alphalete Organizational Leaders podium, average DD, active owners, and the full by-ICD breakdown — with the week's Credico direct deposits folded in.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Builds the weekly two-page Org DD Bulletin from the **Org DDs "
            "Ongoing Report** — the ORG TOTAL DD headline, the leader podium, "
            "average DD, active owners, and the by-ICD breakdown, with each "
            "owner's **Credico** deposits folded in. The build itself only "
            "*reads* the tab; anyone outside the org total is still shown with "
            "the reason.\n\n"
            "FILLS THE TAB FIRST\n"
            "As of **8/6** two upstream steps write the tab automatically each "
            "Thursday — no more VA hand-fill: one opens the new week-ending "
            "column, the next fills every active owner's DD from our Tableau "
            "pull (Credico folded in). The bulletin then builds off that column.\n\n"
            "WHEN IT RUNS\n"
            "**Thursday mornings.** The tab fills by 10am CST; the review link "
            "posts to **#revision-emails** at **10:30am CST**, and the send goes "
            "out on the next pass after Evelyn's ✅ (it re-checks every 25 "
            "minutes until **1:00pm CST**).\n\n"
            "WHERE IT GOES\n"
            "Slack: **#alphalete-sales**, **#alphalete-lvl1-chat**, and "
            "**#11280-alphalete-marketing-inc-rafael-hidalgo**. Email (the PNG pages, from "
            "alphaletereporting@gmail.com): the **Alphalete Org Owners** and "
            "**Bulletins** contact groups.\n\n"
            "SAFETY\n"
            "Nothing sends on its own — building and sending are separate steps. "
            "It **refuses to send** while any number on the page is known wrong."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"
                      "?gid=423082205#gid=423082205"),
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "dd_bulletin",
        "self_scheduled": True,
        # Two-phase pill: PURPLE once the review link is posted for Evelyn, GREEN
        # once she approves and it emails. Modelled as daily_runs:2 (like BG Check
        # Sync) — BOTH phases publish success under the SAME card id, so 1 success
        # = 1/2 (purple, "posted, waiting on the ✅") and 2 = green. A Thursday
        # that ends unapproved stays on the miss colours, not a false green. Same-day window, so
        # the per-day count is correct. daily_runs (not `phases`) because a chain
        # of two DIFFERENT ids auto-registers a phantom library card for the
        # second id. (Megan 2026-08-07)
        "daily_runs": 2,
        # The pass still owed after 1/2 is Evelyn's ✅, not a machine — so the
        # mid state shows PURPLE "awaiting ✅" like the phased review-gated
        # cards, not the orange work-in-progress ramp. (Megan 2026-08-20)
        "approval_final_run": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [3],   # Thursday (Mon=0 … Thu=3)
            # First LaunchAgent pass (com.alphalete.dd-bulletin-thu). The send
            # itself lands after Evelyn's ✅, re-checked q25m until 1:00pm CT.
            "time": "10:30 AM",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Both bulletin pages built. Check anything flagged above before it goes out.",
            "message_failed": "❌ Build failed. Check the log above, then run again.",
        },
        "actions": [
            {
                "label": "Build Both Pages",
                "icon": "\U0001F5BC",
                "primary": True,
                "help": "Reads the DD tab and the leader lists, folds in Credico, and renders both bulletin pages. Sends nothing and writes to no tab.",
                "module": "automations.override_bulletin.dd_build",
                "args_fn": lambda: ["--png"],
            },
            {
                "label": "Preview the Send (no send)",
                "icon": "\U0001F4E7",
                "primary": False,
                "help": "Builds both pages, then shows the subject line, the three Slack channels and every email address it would go to. Sends nothing.",
                "module": "automations.override_bulletin.send",
                "args_fn": lambda: ["--dd"],
            },
            {
                "label": "Check the Numbers Only",
                "icon": "\U0001F50E",
                "primary": False,
                "help": "Prints the headline, every leader's figure against the one the bulletin published, and everything tracked outside the total. No images, no sending.",
                "module": "automations.override_bulletin.dd_data",
                "args_fn": lambda: [],
            },
            {
                "label": "Get This Week's Credico",
                "icon": "⬇",
                "primary": False,
                "help": "Downloads this week's Credico Fee Report files on Lucy 1 so the bulletin can include them. Read-only on Credico's side.",
                "module": "automations.credico.report",
                "args_fn": lambda: ["--fetch"],
            },
        ],
    },
    {
        "id": "override-bulletin",
        # Sits directly before the PNL card: the bulletin goes out first, then
        # PNL for the Office posts right after (same Friday 10am slot, Lucy 1).
        "name": "Override Bulletin \u2192 #alphalete-sales + both recruiting rooms",
        "creator": "Megan & Claude",
        "emoji": "\U0001F3C6",
        # Gold \u2014 matches the black/gold bulletin artwork.
        "color": "#B45309",
        "category": "\U0001F4CA Metrics",
        "description": "Fills our own copy of the Org Overrides Ongoing Report from the override sources, then renders the black/gold Override Bulletin (top-5 leader cards + the two override tables). GATED: Lucy posts the week's link in #revision-emails and it goes to the full org only after Eve approves it with a \u2705.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Assembles each **active ICD's** weekly override \u2014 regular + "
            "captain/special, pulled from five sources \u2014 and renders the "
            "black/gold bulletin from OUR own fill (the sandbox copy tab), not "
            "the VA's live tab.\n\n"
            "WHEN IT RUNS\n"
            "**Fridays ~10am CST** for the week that just ended: the fill runs "
            "first, then the review gate posts the link.\n\n"
            "SENDING (Eve approves \u2014 mirrors the DD bulletin)\n"
            "Lucy posts the week's bulletin link in **#revision-emails** and "
            "@-mentions Eve. **Nothing goes out until Eve reacts "
            ":white_check_mark:** \u2014 then it posts to **#alphalete-sales + "
            "#11280-alphalete-marketing-inc-rafael-hidalgo** and emails both contact groups "
            "(Owners/Bulletins). It **holds** if the week isn't filled yet and "
            "**never double-sends**. A checkmark from anyone but Eve does "
            "nothing.\n\n"
            "IF THE NUMBERS ARE CORRECTED after the link went out, "
            "`override_gate.py --refresh` rebuilds the PDF in place on the SAME "
            "link \u2014 no second post. A gap (a captain/program figure not "
            "sourced yet) is shown in the post as a heads-up, not a blocker: it "
            "still sends, matching the VA, and flags the gap to "
            "#claudecorrections."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit?gid=930186902#gid=930186902"),
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "override_bulletin",
        "self_scheduled": True,
        # Two-phase pill (mirrors the DD bulletin): PURPLE once the review link is
        # posted for Eve, GREEN once she approves and it sends. Modelled as
        # daily_runs:2 — BOTH the post pass and the send pass publish success under
        # THIS card's id, so 1 success = 1/2 (purple, "posted, waiting on the ✅")
        # and 2 = green. A week that is never approved stays on the miss colours,
        # not a false green. daily_runs (not `phases`) so no phantom sub-card is auto-created.
        # (Megan 2026-08-07)
        "daily_runs": 2,
        # 1/2 = posted, waiting on Eve's ✅ → PURPLE, same as the DD bulletin.
        "approval_final_run": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [4],   # Friday (Mon=0 \u2026 Fri=4)
            "time": "10:00 AM",
            "estimated_minutes": 6,
        },
        "checklist": [],
        "post_run": {
            "message_success": "\u2705 Override numbers assembled. Check the week filled + anyone listed as not found before it goes out.",
            "message_failed": "\u274c Run failed. Check the log above, then run again.",
        },
        "actions": [
            {
                "label": "Fill This Week's Numbers",
                "icon": "\u25B6",
                "primary": True,
                "help": "Writes the assembled numbers into the 'Copy of Org Overrides Ongoing Report' tab (our fill from the real sources). The live tab is refused. Do this first.",
                "module": "automations.override_bulletin.run",
                "args_fn": lambda: ["--write"],
            },
            {
                "label": "Post for Eve's Approval",
                "icon": "\U0001F4E4",
                "primary": False,
                "help": "Builds the bulletin PDF and posts the link in #revision-emails, @-mentioning Eve. Sends NOTHING to the org \u2014 it waits for her \u2705. Holds if the week isn't filled yet.",
                "module": "automations.override_bulletin.override_gate",
                "args_fn": lambda: ["--post"],
            },
            {
                "label": "Send Now (after Eve's \u2705)",
                "icon": "\U0001F680",
                "primary": False,
                "help": "Checks for Eve's checkmark and, if it's there, sends the full distro: #alphalete-sales + #11280-alphalete-marketing-inc-rafael-hidalgo + both contact groups. Does nothing until she has approved.",
                "module": "automations.override_bulletin.override_gate",
                "args_fn": lambda: ["--check", "--send", "--distro"],
            },
            {
                "label": "Preview PDF (no post, no send)",
                "icon": "\U0001F50E",
                "primary": False,
                "help": "Builds the bulletin page + PDF and stops. Nothing uploaded, posted, or emailed \u2014 safe to run any time to eyeball the numbers.",
                "module": "automations.override_bulletin.override_gate",
                "args_fn": lambda: ["--pdf-only"],
            },
        ],
    },
    {
        "id": "pnl-office",
        # Two destination channels; tile appends "· 10:00 AM CST".
        "name": "PNL for the Office → #top-leaders + #alphalete-lvl1-chat",
        "creator": "Megan",
        "emoji": "📸",
        "color": "#16A34A",
        "category": "📊 Metrics",
        "description": "Posts the weekly office P&L summary (Total Loss – Reps, Total Loss – Other, Total Profit, Gross Profit) to #top-leaders-alphalete-org and #alphalete-lvl1-chat as Lucy, for the previous fully completed week.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Posts a screenshot of the office **P&L summary** (Total Loss – "
            "Reps, Total Loss – Other, Total Profit, and the TOTAL) for the "
            "previous completed week to **#top-leaders-alphalete-org** and "
            "**#alphalete-lvl1-chat** as Lucy. Once per week.\n\n"
            "WHEN IT RUNS\n"
            "**Fridays 10am CST** — it holds and retries until the week's "
            "numbers are in, so it never posts an empty P&L."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=1537448816#gid=1537448816"),
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "pnl_office",
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [4],   # Friday (Mon=0 … Fri=4) — surfaces on Friday's tile
            "time": "10:00 AM",
            "estimated_minutes": 2,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ PNL for the Office posted to #top-leaders-alphalete-org + #alphalete-lvl1-chat.",
            "message_failed": "❌ Run failed. Check the log above, then run again.",
        },
        "actions": [
            {
                "label": "Post Now",
                "icon": "▶",
                "primary": True,
                "help": "Builds the previous completed week's P&L image and POSTS it to both channels as Lucy.",
                "module": "automations.pnl_office.run",
                "args_fn": lambda: ["--post"],
            },
        ],
    },
    {
        "id": "vantura-slack-sales",
        # The tile appends "· 5:00 AM CST" from `schedule`; the evening passes
        # are spelled out in the breakdown.
        "name": "Sales Board Fill ← #alphalete-gp-sales",
        "creator": "Megan",
        "emoji": "⚡",
        "color": "#F59E0B",
        # 📊 Metrics (not Ops) so it lands in ⏰ TIME SET REPORTS.
        "category": "📊 Metrics",
        "description": "Counts every Base, BOX and AT&T sale the reps post in #alphalete-gp-sales and fills the day column on the Vantura Sales Board — the hand-count the VA used to do each morning.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads the sales reps post in **#alphalete-gp-sales** — counting "
            "**Base, BOX and AT&T** per rep — and fills that day's column on "
            "the Vantura **Sales Board**. This feeds the 5:10am Sales Boards "
            "post, so it has to fill the board first.\n\n"
            "WHEN IT RUNS\n"
            "**Every hour 4–9pm** (board stays live through the evening), then "
            "a **5am** close-out sweep. Every pass recounts the whole day, so "
            "late / next-morning posts get picked up on their own.\n\n"
            "SAFETY\n"
            "Only ever **raises** a rep's count (never lowers), only writes "
            "reps who actually posted, and never touches the **TOTAL** rows. "
            "Anything that doesn't add up is **flagged**, not guessed."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY/edit?gid=1898586497#gid=1898586497"),
        # Lucy 2 — #alphalete-gp-sales is Carlos's channel and it's his board.
        "assignees": ["Lucy 2"],
        "run_machine": "Lucy 2",
        "run_rerun_id": "vantura_slack_sales",
        "self_scheduled": True,
        # Fires 7x a day (5:00am + hourly 4:00-9:00pm). Without this the tile
        # would go green on the 5am pass with all six evening passes still to
        # come — and an evening the board never got filled would look identical
        # to a good day. Amber "N/7" until the 9pm pass lands.
        "daily_runs": 7,
        "schedule": {
            "frequency": "daily",
            # Sortable START of the day's passes; time_label carries the real
            # cadence, since a bare "5:00 AM" reads as if it fires once.
            "time": "5:00 AM",
            "time_label": "5 AM + 4–9 PM hourly CST",
            # Measured on Lucy 2: ~3s end to end (Slack read + sheet write).
            "estimated_minutes": 2,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Sales Board filled from #alphalete-gp-sales.",
            "message_failed": "❌ Run failed. Check the log above, then run again.",
        },
        "actions": [
            {
                "label": "Fill the Board",
                "icon": "▶",
                "primary": True,
                "help": "Counts today's posts (or yesterday's, before 10am) and writes the day column on the Sales Board.",
                "module": "automations.vantura_slack_sales.run",
                "args_fn": lambda: ["--fill", "--yes"],
            },
            # No secondary actions on purpose — the "⚙️ More actions" expander
            # only renders when one exists, so the card stays a single button
            # (Megan 2026-07-18). Preview is still available via
            # `python -m automations.vantura_slack_sales.run --fill` (no --yes).
        ],
    },
    {
        "id": "sales-boards",
        # Channel in the name; the tile appends "· 5:10 AM CST" from `schedule`.
        "name": "Sales Boards → #alphalete-gp-sales",
        "creator": "Megan",
        "emoji": "📸",
        "color": "#7C3AED",
        # 📊 Metrics (not Ops) so it lands in ⏰ TIME SET REPORTS.
        "category": "📊 Metrics",
        "description": "Posts the daily Vantura Production thread as Lucy to #alphalete-gp-sales AND #a-players-b2b — the program Sales Boards (B2B, BOX) the VA used to post by hand each morning, two images each. The A-Players copy also carries the Zero Streak callout.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Posts a dated **Vantura Production** thread each morning with the "
            "**B2B and BOX Sales Boards** (two images each), as Lucy — "
            "to **#alphalete-gp-sales** and **#a-players-b2b**. The A-Players "
            "copy also gets a **Zero Streak** callout (reps on a 0-sales "
            "streak, up to 7 days); that never posts to #alphalete-gp-sales.\n\n"
            "WHEN IT RUNS\n"
            "**Every day at 5:10am CST**, right after the Sales Board fill. It "
            "won't post the wrong week — it holds and retries until the board "
            "shows the right week, and never double-posts."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY/edit"
                      "?gid=1898586497#gid=1898586497"),
        # Lucy 2 (Carlos's machine — #alphalete-gp-sales is his channel). The
        # Lucy Slack token was installed + verified there 2026-07-18, so the
        # earlier "runs on Lucy 1, no token" workaround is retired.
        "assignees": ["Lucy 2"],
        "run_machine": "Lucy 2",
        "run_rerun_id": "sales_boards",
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "5:10 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Sales Boards posted to #alphalete-gp-sales + #a-players-b2b.",
            "message_failed": "❌ Run failed. Check the log above, then run again.",
        },
        "actions": [
            {
                "label": "Post Now",
                "icon": "▶",
                "primary": True,
                "help": "Builds every image and POSTS today's thread to #alphalete-gp-sales and #a-players-b2b as Lucy.",
                "module": "automations.sales_boards.run",
                "args_fn": lambda: ["--post"],
            },
        ],
    },
    {
        "id": "box-order-log",
        # Channels in the name; the tile appends "· 7:00 AM CST" from `schedule`.
        "name": "BOX Order Log → #alphalete-gp-sales + #a-players-b2b",
        "creator": "Megan",
        "emoji": "📦",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "description": "Carlos's B2B counterpart to Raf's Fiber order log — keeps a rolling 6-week log on the Vantura Master Sales Board and posts the daily workbook + payout image + pending-orders worklist + Box Tier Bonus Rep Level board to #alphalete-gp-sales AND #a-players-b2b.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Pulls Carlos's **Box Order Log** Tableau view and collapses "
            "it — the export gives one row per *status change*, not one per "
            "sale, so a single deal shows up 3-4 times as it moves.\n"
            "**•** Updates the **Lucy Box Order Log** tab on the Vantura "
            "Master Sales Board.\n"
            "**•** Posts one dated thread to **#alphalete-gp-sales** AND "
            "**#a-players-b2b** — each channel gets its own thread — carrying "
            "the workbook, a payout image showing last week and this week, a "
            "**Pending Orders** image, and the **Box Tier Bonus Rep Level** "
            "board from Tableau, which shows where each of Carlos's reps "
            "lands on the tier ladder this week (Carlos, 2026-08-15).\n"
            "**•** **Pending Orders** (Carlos, 2026-08-25) is the workbook's "
            "pending tab as a picture — every deal still open, grouped by "
            "rep, with what has to happen next on each one, so nobody has to "
            "open the spreadsheet to work the list.\n\n"
            "EMAILED COPIES (per owner)\n"
            "**•** **Roshan Amin Ahmad** and **Abel Draper** each get their "
            "**own office's** BOX order log **by email** (not Slack) — their "
            "production only, same 7-8am window, and it also fills their own "
            "metrics sheet. They get the **same three artifacts** Carlos's "
            "thread carries: workbook, payout image, pending orders.\n\n"
            "WHEN IT RUNS\n"
            "**Twice a day, 7:00am and 8:30am CST.** "
            "**Only the 7:00 run posts** — 8:30 just refreshes the sheet. If "
            "the 7:00 run fails before posting, 8:30 posts instead, so there "
            "is always exactly one post a day.\n\n"
            "TWO DATES, ON PURPOSE\n"
            "**•** The **log** is grouped by the week a deal was **sold**.\n"
            "**•** The **payout** is grouped by the week the supplier "
            "**accepted** it — that's the week it pays. The two will not "
            "match, and that's correct.\n\n"
            "READING THE PAYOUT IMAGE\n"
            "**•** **Accepted by Supplier** and **Cancelled** are that "
            "week's figures. **Still Open** is not — it's every deal of that "
            "rep's still waiting on acceptance, whatever week it sold, so it "
            "reads the same in both tables.\n"
            "**•** **Submitted to Supplier** (Carlos, 2026-08-25) is a "
            "**slice of Still Open**, not a column beside it — a submitted "
            "deal is counted in **both**. The columns are not meant to add "
            "up.\n\n"
            "SAFETY GATES\n"
            "**•** The sheet is **merged, never overwritten** — the Tableau "
            "view only reaches back ~44 days, so a straight rewrite would "
            "silently drop the oldest week.\n"
            "**•** Refuses to run if the pull comes back empty, rather than "
            "blanking the tab.\n"
            "**•** The **Box Tier Bonus Rep Level** board is sliced to "
            "Carlos's office, which is also what keeps it to one readable "
            "image — the full board (every office) is too tall and Tableau "
            "cuts it off mid-row.\n\n"
            "IF SOMETHING FAILS, SLACK HEARS ABOUT IT\n"
            "Every failure lands in **#claudecorrections-and-requests**, "
            "because all of them look fine from the channel:\n"
            "**•** The tier board missing, or grown too tall to fit in one "
            "image — the log still posts, the gap is flagged.\n"
            "**•** One channel posting and the other not.\n"
            "**•** A capped Tableau pull — the post is suppressed rather than "
            "sent with numbers that undercount.\n"
            "**•** The whole run dying (pull, workbook, timeout) on the "
            "**8:30** pass, meaning no thread at all that day. A 7:00 failure "
            "stays quiet on purpose — that's what the 8:30 fallback is for."
        ),
        # Deep-links to the 'Lucy Box Order Log' tab this run writes to.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY/edit"
                      "?gid=211356769#gid=211356769"),
        "assignees": ["Lucy 2"],
        "run_machine": "Lucy 2",
        "run_rerun_id": "box_order_log",
        "self_scheduled": True,
        # Fires 2x a day (7:00 + 8:30). The tile stays amber after the 7:00
        # pass and only turns green once 8:30 lands — otherwise it would read
        # "done for the day" at 7am with a pass still to come. Both runs
        # report themselves via automations.shared.hub_activity; without that
        # a launchd run is invisible to the Hub and nothing would count.
        "daily_runs": 2,
        "schedule": {
            "frequency": "daily",
            # Runs TWICE (7:00 + 8:30). time_label carries both on the tile;
            # `time` stays the sortable 7:00 start so it still orders first.
            "time": "7:00 AM",
            "time_label": "7 AM + 8:30 AM CST",
            # Measured on Lucy 2: was 83s/89s; a posting run is ~2m45s since it
            # also captures the tier board and posts a second channel (timed
            # 2026-08-15). Sheet-only passes are still the shorter ones.
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ BOX Order Log updated.",
            "message_failed": "❌ Run failed. Check the log above, then run again.",
        },
        # The primary button is the SAFE one on purpose — a mis-click on a
        # card whose other action posts into both of Carlos's channels
        # shouldn't be able to post. Both full-run and sheet-only also sit
        # under More actions so either can be picked deliberately.
        "actions": [
            {
                "label": "Update Sheet",
                "icon": "▶",
                "primary": True,
                "help": "Pulls Tableau and refreshes the rolling 6-week log on "
                        "the Vantura board. Does NOT post to Slack.",
                "module": "automations.box_order_log.run",
                "args_fn": lambda: ["--sheet", "--xlsx"],
            },
            {
                "label": "Full run — update sheet + post to Slack",
                "icon": "📣",
                "help": "Everything the 7:00am run does: refreshes the "
                        "6-week log on the sheet, then posts today's thread "
                        "(workbook + payout image + pending orders + Box Tier "
                        "Bonus Rep Level board) to #alphalete-gp-sales AND "
                        "#a-players-b2b.",
                "module": "automations.box_order_log.run",
                "args_fn": lambda: ["--sheet", "--xlsx", "--post"],
            },
        ],
    },
    {
        "id": "brand-health-audit",
        # No cadence in the name — self_scheduled, so the tile appends
        # "· 12:00 PM CST" itself (it read "(12 CST Daily) · 12:00 PM CST").
        # NBSPs keep the title from wrapping mid-phrase.
        "name": "Brand Health Audit",
        "creator": "Megan",
        "emoji": "🩺",
        "color": "#6366F1",
        "category": "🩺 Brand Health",
        "description": "Daily reputation + brand scan for Alphalete Marketing — Google reviews, search results, Reddit, website, and public social — posted to the Brand Health Slack channel. Auto-replies to Google reviews, and every Sunday DMs the week's rep shout-out list (reps named in new Google reviews) + writes them to the Monday ATMO print.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Runs every brand collector for **Alphalete Marketing** (Google "
            "reviews, search results, Reddit mentions, website, reputation "
            "sites, public social) and posts the results in the **Brand "
            "Health Slack Channel**. It also **auto-replies to Google reviews** "
            "(4–5★ thank-yous post straight to Google, throttled; 1–3★ queue to "
            "the channel for approve/redo).\n\n"
            "REP SHOUT-OUTS (Sundays)\n"
            "Every **Sunday** it tallies the reps **named in the last 7 days "
            "of Google reviews** — one point per review, highest first, ties "
            "flagged for rock-paper-scissors — DMs the **“Google Review WE "
            "x.x”** list to Bas + Raf + Megan, and writes the names as bullets "
            "under **“Google Review S/O’s & Money!”** on the Monday ATMO print "
            "(Fiber Local Office Checklist doc). Empty weeks post **“No New "
            "Reviews for this week”** so the group always hears back.\n\n"
            "WHEN IT RUNS\n"
            "**Every day at noon (Central)**, via a launchd timer on the Mac "
            "mini (LUCY); the rep shout-out rides that same noon run on "
            "Sundays. The **Run Now** button here triggers an extra pass "
            "any time."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1zoRQRhvkpu7Vvw4TsC60ufja9XwpUR8hHvV7FyzezMY/edit"),
        # Runs on Lucy 1 / the Hub. (Was swept to Lucy 2 by e3f1893 "sales boards:
        # move to Lucy 2", which flipped this neighbouring card too.)
        "assignees": ["Lucy 1"],
        # Self-running background job (noon launchd) — keep it out of the "due
        # today / not completed" tallies; it doesn't report completion to the Hub.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "12:00 PM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Brand Health scan complete — scorecard written and any new findings alerted to Slack.",
            "message_failed": "❌ Run failed. Check the log above (usually an API key or rate-limit issue), then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Run the full brand scan for Alphalete Marketing and post any new findings.",
                "module": "automations.brand_audit.run",
                "args_fn": lambda: ["--company", "Alphalete Marketing"],
            },
        ],
    },
    {
        "id": "headshot-bot",
        "name": "Headshot Bot",
        "creator": "Megan",
        "emoji": "\U0001F4F8",
        "color": "#0EA5E9",
        # \U0001F3AF Recruiting, next to blueink-docs: same workbook, same
        # weekly new-start cohort, same Slack room.
        "category": "\U0001F3AF Recruiting",
        "description": (
            "Collects new-start headshots in a Monday Slack thread, cuts each "
            "one onto a white background, uploads it to their OwnerVille "
            "profile, and ticks Headshot Photo on the OBCL tab."),
        "breakdown": (
            "WHAT IT DOES\n"
            "Every **Monday 8:30am** Lucy posts a *Headshot Submissions* "
            "thread in **#11280-alphalete-marketing-inc-rafael-hidalgo**. "
            "Anyone replies with a photo and the person's first and last name "
            "in the same message. Within 5 minutes the bot:\n"
            "**\u2022** removes the background and crops to head-and-shoulders "
            "on pure white (1200\u00d71500), no text on the photo;\n"
            "**\u2022** posts the finished headshot back in the thread and "
            "\u2705 the submission;\n"
            "**\u2022** uploads it to that person's **OwnerVille** profile "
            "(Onboard \u2192 View Progress \u2192 Edit \u2192 Upload "
            "Documents \u2192 Save Changes);\n"
            "**\u2022** ticks **Headshot Photo** on that week's "
            "**`D2D OBCL <m.d>`** tab and tints the cell light green.\n\n"
            "WHEN IT RUNS\n"
            "The Monday post is its own 8:30am timer on Lucy 3. The processing "
            "tick runs **every 5 minutes, all week**, and also watches LAST "
            "week's thread so weekend stragglers still get handled.\n\n"
            "NAMES DON'T HAVE TO BE PERFECT\n"
            "Typos are forgiven \u2014 *Anna Griffin* finds *Ana Griffin*, "
            "*Thomes Crenshawe* finds *Thomas Crenshaw*. When two people are "
            "too close to tell apart (Ana Gonzalez vs Ana Griffin) it refuses "
            "to guess and says so instead. Whenever a typo is forgiven, the "
            "thread reply names who it actually matched.\n\n"
            "WHAT IT WILL NOT DO\n"
            "**\u2022** Overwrite a photo already on someone's OwnerVille "
            "profile \u2014 it reports *already on their profile* and leaves "
            "it.\n"
            "**\u2022** Touch anything on the OBCL tab but that one Headshot "
            "Photo cell.\n"
            "**\u2022** Process the same reply twice.\n\n"
            "WHEN SOMETHING DOESN'T FIT\n"
            "Each thread reply carries a line per step, so a miss is visible "
            "immediately: *Not found on OBCL Sheet* (nobody by that name on "
            "the tab \u2014 normal for people who aren't new starts, nothing "
            "to do), or a \u26a0\ufe0f asking for a manual OwnerVille upload. "
            "A photo posted with no name gets asked once, in the thread."),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=1430069873#gid=1430069873"),
        "assignees": ["Lucy 3"],
        # Two launchd timers of its own (the Monday post + the 5-min tick), so
        # it self-reports rather than sitting in the due-today tallies \u2014
        # same shape as blueink-docs and bg-check-sync.
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],   # Monday post; the tick then runs all week
            "time": "8:30 AM",
            "time_label": "Raf's Office \u00b7 Mon 8:30am, then every 5 min",
            "estimated_minutes": 2,
        },
        "checklist": [],
        "post_run": {
            "message_success": "\u2705 Headshots processed \u2014 posted in the thread, uploaded to OwnerVille, and ticked on the OBCL tab.",
            "message_failed": "\u274C Run failed. Most often the OwnerVille session on Lucy 3 has gone stale \u2014 the photos still posted in Slack; re-run once the session is warm.",
        },
        "actions": [
            {
                "label": "Check for New Photos",
                "icon": "\U0001F441",
                "primary": True,
                "help": "Run one pass now instead of waiting for the 5-minute tick: process any new replies, upload them, and tick the sheet.",
                "module": "automations.headshots.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Post This Week's Thread",
                "icon": "\U0001F4E2",
                "help": "Post the Monday Headshot Submissions thread now \u2014 for a missed or deleted Monday. Will not post twice in the same week.",
                "module": "automations.headshots.weekly_thread",
                "args_fn": lambda: ["--force"],
            },
            {
                "label": "Why Was A Photo Skipped?",
                "icon": "\U0001F50D",
                "help": "Read-only: show what the bot decided about every reply in the current thread, and why. Changes nothing.",
                "module": "automations.headshots.run",
                "args_fn": lambda: ["--diag"],
            },
        ],
    },
    {
        "id": "digi-docs",
        "name": "Digi Docs",
        "creator": "Megan",
        "emoji": "\U0001F5C2️",
        "color": "#7C3AED",
        # \U0001F3AF Recruiting, next to blueink-docs and headshot-bot: same
        # workbook, same weekly new-start cohort, same Slack room.
        "category": "\U0001F3AF Recruiting",
        "description": (
            "Adds each week's new starts to OwnerVille, then generates their "
            "document bundle — which is what mails it — and tints "
            "Digi Docs on the OBCL tab."),
        "breakdown": (
            "WHAT IT DOES\n"
            "Two passes on Monday over the newest dated **`D2D OBCL <m.d>`** "
            "tab (every **chart** on it — Monday's has two):\n"
            "**1. Add — 8:00am.** Anyone eligible who isn't in **OwnerVille** "
            "yet is added (Onboard → View Progress → + Add Sales Rep). "
            "This pass mails nobody and ticks nothing, which is why it can run "
            "early.\n"
            "**2. Send — 30 minutes before each person's own start time.** "
            "Read from the **Start Time** column, so somebody starting at 1:00 "
            "gets their bundle at 12:30. A tick checks every 5 minutes through "
            "the morning. For each rep still showing **Onboarding Documents = "
            "REQUIRED ACTION**, it opens their Digital Doc Portal, picks the "
            "**Base (Door to Door/Business to Business)** bundle type and the "
            "**Door to Door- General 1** bundle, ticks the AT&T Door to Door "
            "commission grid, and hits Generate Document. **That is the "
            "send** — OwnerVille mails the nine-document packet itself. "
            "It then ticks the background-check and drug-test attestations, "
            "sets Service to RES-ATT, saves, and tints the **Digi Docs** cell "
            "light green.\n\n"
            "WHY TWO PASSES AND NOT ONE PER PERSON\n"
            "The two live on different pages, so doing a full cycle per "
            "person pays the expensive transition once per rep instead of "
            "once. It also means that if the send pass stalls halfway, "
            "everyone still EXISTS in OwnerVille rather than the roster being "
            "half-added.\n\n"
            "WHAT IT WILL NOT DO\n"
            "**•** Tick the **Digi Docs checkbox** — ever. The tint "
            "is this automation saying *I sent it*; the tick is a person "
            "saying *this is complete*, and those are different claims.\n"
            "**•** Tint the name. Blue Ink does; this one marks only its "
            "own cell.\n"
            "**•** Send twice. Anyone not showing REQUIRED ACTION is "
            "skipped, so a re-run after a stall is quiet.\n"
            "**•** Send a half-filled contract. Every required field is "
            "read back before submitting; a blank one refuses that rep "
            "instead.\n"
            "**•** Pick a bundle from a list that grew. The Select "
            "Bundle dropdown must hold exactly one option, or the run refuses "
            "rather than guess which contract someone gets.\n\n"
            "ONBOARDING QUIZZES IS NOT AUTOMATED\n"
            "The six training and compliance courses are the rep's own "
            "coursework. Nothing here watches or ticks them — that "
            "column stays a human one.\n\n"
            "WHEN SOMETHING DOESN'T FIT\n"
            "Whoever still needs doing by hand is posted to "
            "**#11280-alphalete-marketing-inc-rafael-hidalgo** at the end of "
            "the run, with the reason. The most common one is a rep "
            "OwnerVille can't find under any campaign."),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=1430069873#gid=1430069873"),
        "assignees": ["Lucy 3"],
        # Its own launchd timers, so it self-reports rather than sitting in the
        # due-today tallies — same shape as blueink-docs and headshot-bot.
        "self_scheduled": True,
        # ONE card, two passes (Megan 2026-08-26). The 8am add and the day's
        # sends BOTH publish success under this same card id, so 1 success = 1/2
        # (the adds are in, the sends are still coming) and 2 = green. Modelled
        # as daily_runs, NOT `phases`: a chain of two different ids
        # auto-registers a phantom library card for the second one.
        "daily_runs": 2,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],
            "time": "8:00 AM",
            "time_label": "Raf's Office · Mon 8am, then 30 min before each start",
            "estimated_minutes": 25,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Digi Docs sent — bundles generated in OwnerVille, attestations ticked, and the Digi Docs cells tinted.",
            "message_failed": "❌ Run failed. Most often the OwnerVille session on Lucy 3 has gone stale — anyone already sent keeps their bundle; re-run once the session is warm and it skips them.",
        },
        "actions": [
            {
                "label": "Preview Bundles",
                "icon": "\U0001F441",
                "primary": True,
                "help": "Show who WOULD be sent to this week, and who wouldn't and why. Sends nothing.",
                "module": "automations.digi_docs.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Send Bundles Now",
                "icon": "▶",
                "help": "Add anyone missing to OwnerVille, then generate and mail this week's document bundles. Cannot be undone.",
                "module": "automations.digi_docs.run",
                "args_fn": lambda: ["--both", "--live"],
            },
            {
                "label": "Add To OwnerVille Only",
                "icon": "➕",
                "help": "Mails nobody. Adds this week's new starts to OwnerVille so they exist before the bundles go out.",
                "module": "automations.digi_docs.run",
                "args_fn": lambda: ["--add-only", "--live"],
            },
        ],
    },
    {
        "id": "slack-skool-email",
        "name": "Slack / Skool Email",
        "creator": "Megan",
        "emoji": "\U0001F4E7",
        "color": "#0EA5E9",
        # \U0001F3AF Recruiting, beside blueink-docs and headshot-bot: same
        # workbook, same weekly new-start cohort, same Slack room.
        "category": "\U0001F3AF Recruiting",
        "description": (
            "Emails this week's new starts their Slack and Skool join links "
            "the morning of orientation \u2014 BCC, from "
            "alphaletereception@gmail.com, with the Slack invite read live "
            "out of Slack so nobody has to paste it."),
        "breakdown": (
            "WHAT IT DOES\n"
            "Every **Monday 8:00am** on Lucy 1 it reads the newest dated "
            "**`D2D OBCL <m.d>`** tab \u2014 every **chart** on it, and "
            "Monday's has two \u2014 takes the **Email** column, and sends "
            "ONE email from **alphaletereception@gmail.com** with everybody "
            "in **BCC**. It tells them to install **Slack**, **Skool** and "
            "**TeleMapper 3**, and that their **Blueink** packet is coming "
            "separately.\n\n"
            "This replaces what reception did by hand every Monday: open the "
            "checklist, copy the email column, paste it into BCC, paste last "
            "week's message, swap in a fresh Slack invite link, send.\n\n"
            "THE SLACK LINK IS FETCHED, NOT PASTED\n"
            "Slack caps an invite link at **30 days and 400 uses** and offers "
            "no API for one, so a pasted link would be a weekly chore wearing "
            "an automation's clothes. Instead the run opens Slack as **Lucy**, "
            "reads the current invite link off the workspace menu, and uses "
            "it \u2014 the same click a person makes. It **copies**, never "
            "resets: resetting mints a new link and strands anyone midway "
            "through joining.\n\n"
            "WHO DOESN'T GET IT\n"
            "Exactly who **Blue Ink** skips, read from the same module rather "
            "than a second copy of the rule \u2014 anyone whose **Final "
            "Status** says they quit, failed, were terminated, no-showed or "
            "rescheduled; a failed or adverse-action **BG Status**; or a "
            "declined **Friday Confirmation**. Someone who isn't starting "
            "shouldn't be told *see you at orientation today*.\n\n"
            "WHAT THE CHANNEL GETS\n"
            "A one-line post in "
            "**#11280-alphalete-marketing-inc-rafael-hidalgo**, detail in the "
            "thread: how many were emailed and off which tab. If anyone was "
            "**unreachable** \u2014 nobody excluded them, the sheet just has "
            "no usable address \u2014 they are **named**, with their row, and "
            "Tiff / Aimee / Alisson are tagged to fix it. A clean week says "
            "nothing extra and pings nobody.\n\n"
            "WHAT IT REFUSES TO DO\n"
            "**\u2022** Send off a tab that isn't dated for **today**. The "
            "run reads the NEWEST tab, which is right every week the lineup "
            "gets built and catastrophic the week it doesn't \u2014 *newest* "
            "would be LAST week's, and people who started a week ago would be "
            "told orientation is today.\n"
            "**\u2022** Send with a missing, wrong-service or expiring "
            "link.\n"
            "**\u2022** Send from the wrong mailbox \u2014 it verifies the "
            "token really is reception's first.\n"
            "**\u2022** Send twice in a day. It checks reception's own Sent "
            "mail, so a hand-send at 7:50 stops the 8:00 run.\n"
            "**\u2022** Mail an empty cohort.\n\n"
            "WHY THERE'S NO BLUEINK LINK IN IT\n"
            "A Blueink signing URL is bound to ONE signer's packet, so a link "
            "that worked for everybody would let anyone sign as anyone. The "
            "Slack and Skool links are identical for all recipients \u2014 "
            "that is what makes a single BCC send legitimate.\n\n"
            "NO IMAGES, NO ATTACHMENTS\n"
            "Fifty-odd BCC recipients from a personal Gmail is already the "
            "shape spam filters watch, and an unexpected attachment from an "
            "address they've never seen reads as phishing to the people least "
            "equipped to tell. The links sit on the words *Slack* and *Skool*; "
            "the plain-text version spells the URLs out."),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=1430069873#gid=1430069873"),
        "assignees": ["Lucy 1"],
        # Its own Monday launchd timer (com.alphalete.slack-skool-email,
        # installed 2026-08-26), so it self-reports rather than sitting in the
        # due-today tallies -- same shape as blueink-docs.
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],   # Monday
            "time": "8:00 AM",
            "time_label": "Raf's Office \u00b7 8:00am CST",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "\u2705 Slack + Skool links emailed to this week's new starts, summary posted to #11280.",
            "message_failed": "\u274C Run failed \u2014 nothing was sent. Usual causes: this week's D2D OBCL tab hasn't been built yet, or the Slack session on Lucy 1 has expired (re-seed with `slack_invite --login` at that machine). The run says which.",
        },
        "actions": [
            {
                "label": "Preview",
                "icon": "\U0001F441",
                "primary": True,
                "help": "Show who WOULD get it, who wouldn't and why, and the exact message. Sends nothing.",
                "module": "automations.slack_skool_email.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Make A Draft",
                "icon": "\U0001F4DD",
                "help": "Sends nothing. Puts the finished email in reception's Gmail Drafts so a person can read it and press send.",
                "module": "automations.slack_skool_email.run",
                "args_fn": lambda: ["--draft"],
            },
            {
                "label": "Check Gmail + Slack",
                "icon": "\U0001FA7A",
                "help": "Preflight. Proves this machine's Gmail token works and is reception's, and that the re-send guard can read Sent mail. Sends nothing.",
                "module": "automations.slack_skool_email.run",
                "args_fn": lambda: ["--check-mailbox"],
            },
            {
                "label": "Send Now",
                "icon": "\u25B6",
                "help": "Email this week's new starts for real, then post the summary to Slack. Cannot be undone.",
                "module": "automations.slack_skool_email.run",
                "args_fn": lambda: ["--send", "--slack"],
            },
        ],
    },
    {
        "id": "blueink-docs",
        "name": "Blue Ink New Start Docs",
        "creator": "Megan",
        "emoji": "\U0001F58A\uFE0F",
        "color": "#2563EB",
        # \U0001F3AF Recruiting, next to bg-check-sync: same workbook, same
        # weekly new-start cohort, same Slack room.
        "category": "\U0001F3AF Recruiting",
        "description": (
            "Sends each week's new starts their Blue Ink onboarding packet "
            "(I-9, W-4, Direct Deposit), skips anyone who isn't starting or "
            "already has one, and posts who still needs doing by hand."),
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads the newest dated **`D2D OBCL <m.d>`** tab \u2014 every "
            "**chart** on it, and Monday's has two \u2014 and sends each "
            "eligible new start "
            "their packet through the Blue Ink **web app**, then tints their "
            "first name light green in column D and logs the send to the "
            "**Blue Ink Log** tab.\n\n"
            "WHEN IT RUNS\n"
            "**Monday 7:30am CST** on Lucy 2, its own launchd timer. A full "
            "week takes about an hour \u2014 roughly a minute a person.\n\n"
            "WHO IT SKIPS\n"
            "**\u2022** Any **Final Status** meaning they aren't starting "
            "(quit, failed BGC, terminated, no show, rescheduling).\n"
            "**\u2022** **BG Status** of Failed or Adverse Action.\n"
            "**\u2022** **Friday Confirmation** of Declined or Failed "
            "Background.\n"
            "**\u2022** Anyone who already has a packet \u2014 matched on "
            "email **and name**, whoever sent it, so a hand-send is never "
            "duplicated.\n\n"
            "GOOD TO KNOW\n"
            "**\u2022** It sends through the web app on purpose: API sends "
            "bill as **Bulk Envelopes**, capped at 50/YEAR on this plan and "
            "long spent. Web-app sends draw on the unlimited bucket.\n"
            "**\u2022** That means it needs a **browser session** on Lucy 2. "
            "When it expires the run refuses to send and says so \u2014 a "
            "human re-seeds with `session.py --login` at that machine.\n"
            "**\u2022** A **wrong email on the sheet** doesn't cause a bad "
            "send; the name check holds that person back and names them in "
            "Slack instead.\n\n"
            "THE \u201cBLUE INK\u201d COLUMN\n"
            "That one cell carries two different facts:\n"
            "**\u2022** **Light green background** \u2014 we sent it.\n"
            "**\u2022** **Checkbox ticked** \u2014 they have SIGNED it. A "
            "separate pass re-reads Blue Ink's Completed list (last 7 days) "
            "and ticks whoever has finished since. It only ever ticks ON, so a "
            "box someone checked by hand is never cleared.\n"
            "**\u2022** If the column is missing the run says so in Slack and "
            "**still sends** \u2014 paperwork beats a marking.\n\n"
            "AFTER IT RUNS\n"
            "Posts **Blueink Status Update** to "
            "**#11280-alphalete-marketing-inc-rafael-hidalgo**: how many went "
            "out, and a bullet per person who still needs doing by hand, "
            "tagging Tiff, Aimee and Alisson. The correct skips aren't listed "
            "\u2014 they'd bury the names that need acting on."),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=1430069873#gid=1430069873"),
        "assignees": ["Lucy 2"],
        # Its own Monday launchd timer, so it self-reports rather than sitting
        # in the due-today tallies \u2014 same shape as bg-check-sync.
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],   # Monday
            "time": "7:30 AM",
            # No weekday here: the card already sits on Monday's tile, so
            # "Mon" was just noise. The office DOES need saying -- these tabs
            # are Raf's, and other offices will want their own card.
            "time_label": "Raf's Office \u00b7 7:30am CST",
            "estimated_minutes": 60,
        },
        "checklist": [],
        "post_run": {
            "message_success": "\u2705 Packets sent, names tinted green, and the status summary posted to #11280.",
            "message_failed": "\u274C Run failed. Usually the Blue Ink session on Lucy 2 has expired \u2014 someone at that machine runs `python -m automations.blueink_docs.session --login`. Nothing was sent.",
        },
        "actions": [
            {
                "label": "Preview",
                "icon": "\U0001F441",
                "primary": True,
                "help": "Show who WOULD be sent to this week, and who wouldn't and why. Sends nothing.",
                "module": "automations.blueink_docs.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Send Now",
                "icon": "\u25B6",
                "help": "Send this week's packets for real, then post the summary to Slack. Cannot be undone.",
                "module": "automations.blueink_docs.run",
                "args_fn": lambda: ["--send", "--slack"],
            },
            {
                "label": "Refresh Signed",
                "icon": "\u2705",
                "help": "Sends nothing. Just ticks the Blue Ink checkbox for anyone whose packet has been signed since the last run.",
                "module": "automations.blueink_docs.run",
                "args_fn": lambda: ["--sync-completed"],
            },
        ],
    },
    {
        "id": "bg-check-sync",
        "name": "BG Check Sync",
        "creator": "Raf",
        "emoji": "🪪",
        "color": "#F59E0B",
        # 🎯 Recruiting (not Ops): Ops cards are routed to the OPS section, which
        # kept this out of ⏰ TIME SET REPORTS. It syncs new-hire background
        # checks, so Recruiting is the right home and it sorts at its 11:30am start.
        "category": "🎯 Recruiting",
        # Fires 2× a day (11:30am / 4pm). The tile stays amber showing "N/2"
        # until the 4pm pass lands, then turns green. TWO passes not three: the
        # nightly schedule_guard only self-heals jobs with <=2 launchd entries,
        # so a 3rd run would drop guard coverage (that caused the 7/20-22 stall).
        "daily_runs": 2,
        "description": "Reads the Sterling/First Advantage background-check emails and updates the BG Status column on both D2D OBCL tabs, corrects each new start's name to the one Sterling ran their check under — on the checklist AND in their OwnerVille profile — and posts a weekly new-starts status thread to #11280-alphalete-marketing-inc-rafael-hidalgo.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads the **Sterling / First Advantage** BG-check emails (raffi127 "
            "inbox) and updates **column K “BG Status”** for the week's new "
            "starts on both `D2D OBCL` tabs. Then posts a weekly "
            "thread in "
            "**#11280-alphalete-marketing-inc-rafael-hidalgo**, grouping everyone into Passed / "
            "Taken-Pending / Failed / Unperformable / Invited-not-taken (one "
            "edited-in-place reply, so the thread never grows).\n\n"
            "NAMES (added 2026-08-26)\n"
            "Applicants type their **legal** name into Sterling; the recruiter "
            "types what they were told onto the checklist. When those differ, "
            "the result never matches the row and somebody ends up emailing "
            "activations. So **Sterling's spelling wins** and gets written to "
            "**both** places:\n"
            "**•** the checklist (cols D/E), and\n"
            "**•** their **OwnerVille profile** (Sales Reps → the profile page).\n"
            "A name confirmed against a real check is **tinted green** on every "
            "tab that person appears on.\n\n"
            "WHEN IT ASKS INSTEAD\n"
            "If the two names share only a surname (“Nikki” vs Shuminique), "
            "identity is a guess — so it asks. It first checks **OwnerVille**: a "
            "profile on the same **phone or email** already carrying Sterling's "
            "name settles it with nobody involved. Only what OV can't prove is "
            "posted in that week's BG thread for **Alisson / Tiff / Aimee** — "
            "✅ same person (it fixes both systems on the next pass) or "
            "❌ different person (it never asks again and flags it). No "
            "reaction changes nothing.\n\n"
            "WHEN IT RUNS\n"
            "**11:30am / 4pm CST** on the mini. Monday 11:30 starts the "
            "new week's thread.\n\n"
            "GOOD TO KNOW\n"
            "**•** **Passed** only from an explicit “Score PASS” email; "
            "forward-only (never downgrades or overwrites a hand-set status).\n"
            "**•** A **“Passed but no matching email”** flag is usually a name "
            "mismatch — compound surnames auto-match under `[fuzzy-match]`.\n"
            "**•** The OwnerVille form won't save without a **role** and the "
            "**Over 18** box, so a blank one gets **Entry Level** / ticked — "
            "never an answer somebody already gave.\n"
            "**•** Names are corrected from the **next** start week onward; the "
            "week in flight is left as the team hand-fixed it."
        ),
        # Deep-links to the D2D OBCL tab this run updates.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"
                      "?gid=963403896#gid=963403896"),
        "assignees": ["Lucy 1"],
        # Own launchd timer, 2x a day — hide the DUE-TODAY + schedule pills and
        # keep it out of the "due today / not completed" tallies (same as
        # rc-autoread). Cadence lives in the breakdown.
        "hide_schedule": True,
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            # Sortable START time; time_label shows the real cadence at a glance.
            "time": "11:30 AM",
            "time_label": "11:30am / 4pm CST",
            # Was 1 when this only read email. The OwnerVille pass drives a
            # browser through the rep table for anybody it hasn't checked yet,
            # so a run that meets a new cohort takes minutes; checked profiles
            # are remembered and skipped after that.
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ BG statuses synced to both D2D OBCL tabs, names matched to Sterling (checklist + OwnerVille), and the weekly Slack thread updated.",
            "message_failed": "❌ Run failed. Check the log above — usually the Gmail app password (IMAP) or Lucy not being in #11280-alphalete-marketing-inc-rafael-hidalgo. An OwnerVille session that won't open is reported per rep, never a failed run.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Re-read the BG emails, update both tabs, match names to Sterling (checklist + OwnerVille), and refresh the Slack thread.",
                "module": "automations.bg_check_sync.run",
                "args_fn": lambda: ["--post", "--since-days", "30",
                                    "--ov", "--ov-apply"],
            },
        ],
    },
    {
        "id": "new-start-followup",
        "name": "New-Start Follow-Up",
        "creator": "Raf",
        "emoji": "📣",
        "color": "#0EA5E9",
        # 🎯 Recruiting, same as BG Check Sync — it works the same new-start
        # cohort out of the same OBCL tab and posts to the same channel.
        "category": "🎯 Recruiting",
        "description": "Nudges the 2nd-round interviewers to text their Monday new starts, then posts the Sunday ✅ checklist of who sent and who didn't.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Every new start should get a text from **the person who ran their "
            "2nd-round interview** before Monday. This chases that — it reads "
            "who owes a text (**Aisha's Friday roster screenshot** in the "
            "**#11280-alphalete-marketing-inc-rafael-hidalgo** thread) against "
            "who's replied **Sent**, and chases whoever's still out by Slack "
            "tag AND a personal iMessage that lists each new start's **name + "
            "number** (off the OBCL sheet). A leader Lucy has **no number** "
            "for gets posted in the thread @Raf @Aisha — anyone's reply with "
            "the number turns into a sent text **within the hour**. OBCL rows "
            "marked **Terminated** @Raf with a needs-a-leader count; "
            "interviewers with no Slack account are named for a manual "
            "reach-out.\n\n"
            "WHEN IT RUNS\n"
            "**Saturday 8am** — numbered roll call; **8:30am** — the texts + "
            "a reminder in the *Alphalete lvl 1's* iMessage group + "
            "**#alphalete-lvl1-chat** + the numbers-needed post; **hourly "
            "9am–6pm Sat & Sun** — number-reply scan; **Sat 1pm** — reminder "
            "tagging only who hasn't replied. **Sunday 1pm** — the numbered "
            "✅ roll-up. **Tue–Fri 9am** — the \"text the new starts you "
            "closed yesterday\" ping (both lvl-1 chats; no Monday — nobody "
            "closes Sunday — and Saturday's 8:30 reminder already covers it)."
        ),
        "assignees": ["Lucy 1"],
        # Pinned to Lucy 1 (same as bg-check-sync): that's where Lucy's Slack
        # user token, the thread state, AND Lucy's iMessage account
        # (alphaletereporting@) live — texting un-parked 2026-08-23 (Raf).
        "run_machine": "Lucy 1",
        "run_rerun_id": "new_start_followup",
        # Own launchd timers — hide the DUE-TODAY + schedule pills and keep it
        # out of the "due today" tallies, same as bg-check-sync.
        "hide_schedule": True,
        "self_scheduled": True,
        # Pill climbs as each pass lands: Saturday = 3 (roll-call 8am +
        # sat-texts 8:30 + the 1pm nudge); Sunday = the 1pm checklist;
        # Tue-Fri = the 9am group reminder. NO MONDAY (nobody closes Sunday)
        # and NO SATURDAY daily ping (sat-texts' 8:30 group reminder covers
        # it) — Raf via Megan 2026-08-23. Weekday-keyed (weekday(): Mon=0 …
        # Sun=6). Each live pass records itself via hub_publish
        # (new_start_followup -> this card).
        "daily_runs": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 3, "6": 1},
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1, 2, 3, 4, 5, 6],
            "time": "8:00 AM",
            # Weekday-keyed: each day's pill shows only its own times.
            "time_label": {"1": "9am CST", "2": "9am CST",
                           "3": "9am CST", "4": "9am CST",
                           "5": "8am/8:30am/1pm CST", "6": "1pm CST"},
            "estimated_minutes": 1,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Checked the new-start thread — see who's still out above.",
            "message_failed": "❌ Run failed. Usually means Aisha hasn't posted Friday's new-starts thread yet, or the Saturday @-tag roll call isn't up.",
        },
        "actions": [
            {
                "label": "Who's Sent?",
                "icon": "👀",
                "primary": True,
                "help": "Print the current checklist without posting anything to Slack.",
                "module": "automations.new_start_followup.run",
                "args_fn": lambda: ["--mode", "status"],
            },
            {
                "label": "Post Roll Call",
                "icon": "📣",
                "help": "Tag every leader who has a new start, with their count. No-ops if one is already posted.",
                "module": "automations.new_start_followup.run",
                "args_fn": lambda: ["--mode", "rollcall", "--live"],
            },
            {
                "label": "Post Reminder",
                "icon": "⏰",
                "help": "Reply in the thread tagging only the leaders who still haven't sent.",
                "module": "automations.new_start_followup.run",
                "args_fn": lambda: ["--mode", "nudge", "--when", "auto", "--live"],
            },
            {
                "label": "Post Checklist",
                "icon": "📋",
                "help": "Post the numbered ✅ roll-up to the thread.",
                "module": "automations.new_start_followup.run",
                "args_fn": lambda: ["--mode", "checklist", "--live"],
            },
            {
                "label": "Text The Leaders",
                "icon": "📱",
                "help": "iMessage every leader still owing a text + post the "
                        "lvl-1 group reminders. Only works on Lucy 1 (that's "
                        "where Lucy's iMessage lives).",
                "module": "automations.new_start_followup.run",
                "args_fn": lambda: ["--mode", "sat-texts", "--live"],
            },
            {
                "label": "Preview Texts",
                "icon": "👀",
                "help": "Show exactly who'd be texted and the message, without "
                        "sending anything.",
                "module": "automations.new_start_followup.run",
                "args_fn": lambda: ["--mode", "sat-texts"],
            },
            {
                "label": "Scan Number Replies",
                "icon": "🔁",
                "help": "Check the numbers-needed post right now instead of "
                        "waiting for the hourly scan — texts any leader whose "
                        "number just got replied. Lucy 1 only.",
                "module": "automations.new_start_followup.run",
                "args_fn": lambda: ["--mode", "number-replies", "--live"],
            },
        ],
    },
    {
        "id": "rc-autoread",
        # The name uses non-breaking spaces ( ) inside "RingCentral Auto-Read"
        # and "(Q 10 Min)" so the cadence wraps as one clean unit onto line 2 of
        # the This Week strip pill instead of breaking mid-phrase.
        "name": "RingCentral Auto-Read (Q 10 Min)",
        "creator": "Dylan",
        "emoji": "📲",
        "color": "#F59E0B",
        "category": "📲 Ops",
        "description": "Marks RingCentral SMS conversations read once they hit a known wrap-up message (installs, DirecTV/cell hand-offs, fiber reminders), leaving customer-reply threads unread.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Scans the RingCentral extension for **unread SMS** and marks a "
            "conversation read once it has reached a known **wrap-up** "
            "message. Threads where the **customer replied after** the "
            "wrap-up are left unread so a human still sees them.\n\n"
            "WHEN IT RUNS\n"
            "**Every ~10 minutes, 7 AM–midnight Central**, via a launchd "
            "timer on the Mac mini (LUCY). The **Run "
            "Now** button here triggers an extra pass any time.\n\n"
            "IF A THREAD ISN'T CLEARING\n"
            "Its wrap-up wording probably isn't in the phrase list — add the "
            "phrase to WRAP_UP_PHRASES in automations/rc_autoread/run.py."
        ),
        # No Google Sheet — RingCentral API only.
        "assignees": ["Lucy 1"],
        # Runs on its own 10-min launchd timer — hide the DUE-TODAY + schedule
        # pills on the report page (cadence is in the breakdown).
        "hide_schedule": True,
        # Self-running background job: never reports a per-day completion to the
        # Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            # Runs every ~10 min across a WINDOW, so a bare "7:00 AM" reads as if
            # it fires once. time_label shows the real window at a glance (Megan
            # 2026-07-14); schedule.time stays the sortable START time so
            # _report_time_minutes still orders the card at 7am.
            "time": "7:00 AM",
            "time_label": "7am–12am CST",
            "estimated_minutes": 1,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Auto-read pass complete — wrapped-up threads marked read, customer-reply threads left unread.",
            "message_failed": "❌ Run failed. Check the log above (usually a RingCentral auth/token or rate-limit issue), then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Scan the extension and mark wrapped-up threads read.",
                "module": "automations.rc_autoread.run",
                "args_fn": lambda: [],
            },
        ],
    },
    # ── Applicant Push — Resume Pushing + OAT merged into one flow ────────
    # The unified office-11580 push: batch send + OAT leftovers cleanup on ONE
    # warm real-Chrome/CDP session. Supersedes the two cards above/below
    # (resume-pushing + the auto-registered oat-processing) — hide those at
    # cutover once this is validated live on Lucy 2. Uses NORMAL calstat pills
    # (its wrapper publishes real success/failed to the Hub), so no forced pill.
    {
        "id": "applicant-push",
        # ~10 min, not 5, since 2026-08-26: the one q5min job now alternates
        # Carlos's office and Atef's, one office per pass.
        "name": "Applicant Push (Q 10 Min)",
        "creator": "Carlos",
        "emoji": "📲",
        "color": "#F59E0B",
        "category": "📲 Ops",
        "description": "Carlos's ApplicantStream office (11580) applicant push, all in one (Resume Pushing + OAT merged): every ~10 minutes it works the leftover applicant queue — sends the ones with a phone to the AI call list, removes duplicates, re-texts quiet applicants — and at noon & 4 PM posts a Slack to-do of who still needs a number pulled from Indeed.",
        "breakdown": (
            "WHAT IT DOES\n"
            "One warm browser session for **Carlos's office (11580)** works the "
            "**One-App-at-a-time** leftover queue on every pass:\n"
            "**•** Fresh applicants **with a phone** → **sent to the AI call "
            "list**.\n"
            "**•** Duplicates / past-interviews / already-sent → **removed**.\n"
            "**•** Quiet applicants (>1 week) whose text thread is still visible → "
            "**re-texted** the FOR LUCY message, then removed.\n"
            "**•** **No number on file** → it opens their resume to read one; if "
            "it can't (Indeed blocks it), they're **flagged for a human to pull "
            "the number from Indeed by hand** — each resume is read once, never "
            "reopened.\n"
            "**•** Quiet applicants whose thread is **too old to see** → flagged "
            "for a **manual text**.\n\n"
            "TWICE-A-DAY SLACK POST\n"
            "At **noon and 4 PM** it posts to **#alphaletegp-recruiting** (one "
            "thread per day) the to-do list of who still needs a hand — **who "
            "needs a number pulled from Indeed** and **who needs a manual text** "
            "— **grouped by account**, with **how many days** each has been "
            "sitting (🚨 at 2+ days).\n\n"
            "WHEN IT RUNS\n"
            "**Every ~10 minutes, 7 AM–10 PM Central, every day**, on "
            "**Lucy 2**. The job wakes every 5 minutes and works **one office "
            "per pass** — Carlos, then Atef (office 23467, added 2026-08-26), "
            "then Carlos — so each office gets its own clean browser session "
            "and neither can stall the other.\n\n"
            "HOW IT RUNS\n"
            "Drives a **real Google Chrome** on a copy of **Lucy 2's** everyday "
            "browser profile. It signs in with the **shared 'Raf – Captain' "
            "ApplicantStream login** (the same master session the rest of the "
            "fleet uses — *not* a personal login of Carlos's) and then **switches "
            "into office 11580**, so everything it does happens inside Carlos's "
            "office and only there. A session-holder keeps that login warm.\n"
            "Sends, removes and re-texts are **irreversible**. The batch "
            "resume-extract half is **on hold** — Indeed blocks the automated "
            "resume pulls, so those numbers go on the twice-daily to-do list for "
            "a human instead.\n"
            "When a resume **can't be opened** (Cloudflare, or Indeed's sign-in "
            "wall) that's now told apart from a resume that genuinely has no "
            "number: the blocked ones get **retried up to 3 times a day, 45 "
            "minutes apart**, and only then go on the manual list."
        ),
        # No Google Sheet — ApplicantStream action bot only.
        "assignees": ["Lucy 2"],
        # Needs Lucy 2's warm AppStream session (the shared 'Raf – Captain' login,
        # switched into office 11580 — NOT a personal Carlos login; his CarlosNLR
        # account was retired 2026-08-21). A Hub "play" from any machine routes to
        # Lucy 2 via mini-control (run_rerun_id = schedule id).
        "run_machine": "Lucy 2",
        "run_rerun_id": "applicant_push",
        "hide_schedule": True,
        "self_scheduled": True,
        "schedule": {
            # Runs EVERY day across a window. 'daily' shows all 7 days on the This
            # Week strip; time = window start (sorts the card at 7am); time_label =
            # what the tile shows (it runs q5min across the window, not once).
            "frequency": "daily",
            "time": "7:00 AM",
            "time_label": "7am–10pm CST",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Applicant Push complete — the leftovers queue was worked (sent to the AI call list, removed, re-texted).",
            "message_failed": "❌ Run failed. Check the log above (usually an expired AppStream session or Cloudflare on office 11580), then run again.",
        },
        "actions": [
            {
                "label": "Run",
                "icon": "▶",
                # This button passes NO args, and applicant_push.run defaults to
                # dry-run — so it's a safe PREVIEW, not a live pass. The live pass is
                # the q5min agent (its wrapper injects --live --oat-only). Said plainly
                # here because the help used to promise real sends and deliver none.
                "primary": True,
                "help": "Preview pass — walks Carlos's queue and prints what it WOULD do. Nothing is sent, removed or re-texted; the live pass is the every-5-minutes agent.",
                "module": "automations.applicant_push.run",
                "args_fn": lambda: [],
            },
        ],
    },
    # ── Applicant Push — Atef's office (23467) ────────────────────────────
    # The SAME module and flow as the card above, pointed at a second office
    # (--office 23467). Carlos asked 2026-08-26 for Atef's resumes to be pushed
    # on the same schedule as his. There is NO second LaunchAgent: the one q5min
    # job alternates offices tick by tick, so each office gets a pass every
    # ~10 min. Separate card so a wedge on one office never shows the other green.
    {
        "id": "applicant-push-atef",
        "name": "Applicant Push — Atef (Q 10 Min)",
        "creator": "Carlos",
        "emoji": "📲",
        "color": "#F59E0B",
        "category": "📲 Ops",
        "description": "Atef's ApplicantStream office (23467, Domin8 Acquisitions) applicant push — the same flow as Carlos's, on the same schedule: it works the leftover applicant queue, sends the ones with a phone to the AI call list, removes duplicates, re-texts quiet applicants, and at noon & 4 PM posts a Slack to-do of who still needs a number pulled from Indeed.",
        "breakdown": (
            "WHAT IT DOES\n"
            "One warm browser session for **Atef's office (23467 — Domin8 "
            "Acquisitions)** works the **One-App-at-a-time** leftover queue on "
            "every pass:\n"
            "**•** Fresh applicants **with a phone** → **sent to the AI call "
            "list**.\n"
            "**•** Duplicates / past-interviews / already-sent → **removed**.\n"
            "**•** Quiet applicants (>1 week) whose text thread is still visible → "
            "**re-texted** the FOR LUCY message, then removed.\n"
            "**•** **No number on file** → it opens their resume to read one; if "
            "it can't (Indeed blocks it), they're **flagged for a human to pull "
            "the number from Indeed by hand** — each resume is read once, never "
            "reopened.\n"
            "**•** Quiet applicants whose thread is **too old to see** → flagged "
            "for a **manual text**.\n\n"
            "TWICE-A-DAY SLACK POST\n"
            "At **noon and 4 PM** it posts to **Atef's own recruiting channel** "
            "(#23467-domin8-acquisitions-inc-atef-choudhury, one thread per day) "
            "the to-do list of who still needs a hand — **who needs a number "
            "pulled from Indeed** and **who needs a manual text** — **grouped by "
            "account**, with **how many days** each has been sitting (🚨 at 2+ "
            "days). Atef's names never go to Carlos's channel.\n\n"
            "WHEN IT RUNS\n"
            "**Every ~10 minutes, 7 AM–10 PM Central, every day**, on **Lucy 2** "
            "— the same every-5-minutes job that runs Carlos's office, taking "
            "**one office per pass** (Carlos, then Atef, then Carlos…). Carlos's "
            "office is unaffected: it keeps its own browser profile, its own "
            "files and its own card.\n\n"
            "HOW IT RUNS\n"
            "Drives a **real Google Chrome** on a copy of **Lucy 2's** everyday "
            "browser profile. It signs in with the **shared 'Raf – Captain' "
            "ApplicantStream login** (the same master session the rest of the "
            "fleet uses — **no new login was needed for Atef**) and then "
            "**switches into office 23467**, so everything it does happens inside "
            "Atef's office and only there.\n"
            "Sends, removes and re-texts are **irreversible**. The batch "
            "resume-extract half is **on hold** — Indeed blocks the automated "
            "resume pulls, so those numbers go on the twice-daily to-do list for "
            "a human instead."
        ),
        # No Google Sheet — ApplicantStream action bot only.
        "assignees": ["Lucy 2"],
        "run_machine": "Lucy 2",
        "run_rerun_id": "applicant_push_atef",
        "hide_schedule": True,
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "time_label": "7am–10pm CST",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Applicant Push (Atef) complete — the leftovers queue was worked (sent to the AI call list, removed, re-texted).",
            "message_failed": "❌ Run failed. Check the log above (usually an expired AppStream session or Cloudflare on office 23467), then run again.",
        },
        "actions": [
            {
                "label": "Run",
                "icon": "▶",
                # Same as Carlos's card: NO args beyond the office, and
                # applicant_push.run defaults to dry-run — a safe PREVIEW, not a
                # live pass. The live pass is the every-5-minutes agent.
                "primary": True,
                "help": "Preview pass — walks Atef's queue and prints what it WOULD do. Nothing is sent, removed or re-texted; the live pass is the scheduled agent.",
                "module": "automations.applicant_push.run",
                "args_fn": lambda: ["--office", "23467"],
            },
        ],
    },
    # ── ApplicantStream → Applicant Tracker (Francia; consolidated) ───────
    # ONE module (automations.applicant_tracker.run) drives all four of
    # Francia's ApplicantStream reports as two phases that share ONE login:
    #   morning (reads yesterday) = Call List + 2R Status   → own ~6:45am timer
    #   evening (reads today)     = 2R Retention + First-Day → 8pm launchd
    # Pill: orange after the morning pass, green after the evening pass
    # (daily_runs: 2). First-Day (col R) stays DRY until verified (FIRST_DAY_LIVE).
    {
        "id": "applicant-tracker-sync",
        "name": "Applicant Tracker Sync",
        "creator": "Francia",
        "emoji": "📇",
        "color": "#0EA5E9",
        "category": "🎯 Recruiting",
        "description": "One login syncs all of ApplicantStream into the Applicant Tracker — morning appends the Call List + updates 2R status (reads yesterday), evening appends 2R Retention + marks first-day show-up (reads today), across 17 offices.",
        "breakdown": (
            "WHAT IT DOES\n"
            "🌅 **MORNING** — reads **yesterday**, runs in the **4am flow** "
            "(right after Daily Recruiting Focus):\n"
            "**•** **Export Call List** → Call List tab (owner **A**, data "
            "**B–H**). Appends; no de-dupe.\n"
            "**•** **Update 2R Status** → 2R tab, on rows already there: Offered "
            "**H**, Follow-up **I** (no-show / BOB), BOB date **J**.\n\n"
            "🌙 **EVENING** — reads **today**, runs **~8pm**:\n"
            "**•** **Export 2R Retention** → 2R tab (owner **AT**, 9 cols "
            "**AU–BC**). Appends; no de-dupe.\n"
            "**•** **Confirm First-Day** → 2R **col R** = Y/N. ⚠️ **Dry until "
            "verified** on a real first-day-of-training day.\n\n"
            "HOW IT RUNS\n"
            "On **Lucy 1** as **rcaptain**. Any office that doesn't sync (error "
            "or no access) is posted to **#claudecorrections-and-requests**."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo/edit"
                      "?gid=792099299#gid=792099299"),
        "assignees": ["Lucy 1"],
        "run_machine": "Lucy 1",
        "run_rerun_id": "applicant_sync",
        "self_scheduled": True,
        "daily_runs": 2,
        # The 2 runs are the morning and evening PHASES, not two passes of the
        # same job, so count them by name: re-running the morning must not tick
        # the evening's box. Without this the card went green at 10:55am on
        # 2026-08-18 off two morning re-runs (Megan). See _week_run_phases.
        "phase_runs": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0, 1, 2, 3, 4, 5],
            # Morning phase moved into the 4am orchestrator flow (after
            # daily_focus) 2026-07-28; evening stays its own 8pm launchd.
            "time": "4:00 AM",
            "time_label": "4 AM flow + 8 PM CST · Mon–Sat",
            "estimated_minutes": 12,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Applicant Tracker synced.",
            "message_failed": "❌ Run failed — check the log (usually an expired ApplicantStream session on Lucy 1), then run again.",
        },
        "actions": [
            {
                "label": "Run morning phase",
                "icon": "🌅",
                "primary": True,
                "help": "Live: appends the Call List + updates 2R status for YESTERDAY (all 17 offices). Re-run if the 4am pass missed it.",
                "module": "automations.applicant_tracker.run",
                "args_fn": lambda: ["morning"],
            },
            {
                "label": "Run evening phase",
                "icon": "🌙",
                "help": "Live: appends 2R Retention for TODAY (owner AT, AU–BC). First-Day (col R) is computed but not written until verified.",
                "module": "automations.applicant_tracker.run",
                "args_fn": lambda: ["evening"],
            },
        ],
    },
    {
        "id": "social-media-posting",
        # Non-breaking spaces keep "(12 + 4 CST Daily)" together so the cadence
        # wraps as one clean unit onto line 2 of the strip pill (same trick as
        # rc-autoread's "(Q 10 Min)" and the Brand Health card).
        "name": "Alphalete social media posting",
        "creator": "Megan",
        "emoji": "📣",
        "color": "#EC4899",
        "category": "📸 Social",
        "description": "Turns photos reps drop in #alphaletesocialmedia into brand-safe, captioned social posts — screens the photo, auto-edits it, drafts a caption, collects ✅/❌ approvals, then schedules the approved post.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Watches **#alphaletesocialmedia**. When a rep drops a photo, Lucy:\n"
            "**•** **Brand-safety screens** it (flags alcohol / profanity / "
            "anything unprofessional).\n"
            "**•** **Auto-edits** it (enhance + crop) and **drafts a caption** "
            "in our voice.\n"
            "**•** Collects the approvers' ✅ / ❌ on the photo + caption, then "
            "once both pass, **schedules the post** (Zoho).\n\n"
            "WHEN IT RUNS\n"
            "**Noon and 4 PM CST** on the mini. **Run Now** triggers an extra "
            "pass.\n\n"
            "GOOD TO KNOW\n"
            "**•** One approval round-trip per run (propose → react → next run "
            "collects & schedules), so the two daily passes move a photo ~twice "
            "as fast. **Run Now** pushes it through once people have reacted.\n"
            "**•** Each photo is tracked by its Slack timestamp and handled "
            "once — a lock stops runs from colliding on the same photo."
        ),
        # No Google Sheet — Slack + Anthropic + Zoho APIs only.
        "assignees": ["Lucy 1"],
        # Runs on its own launchd timer (noon + 4 PM) — hide the DUE-TODAY +
        # schedule pills on the report page (cadence is in the breakdown).
        "hide_schedule": True,
        # Self-running background job: never reports a per-day completion to the
        # Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": True,
        # Fires 2× a day (12 PM + 4 PM). The tile stays amber showing "N/2"
        # until the 4 PM pass lands, then turns green — instead of reading
        # done at noon with the 4 PM post still due.
        "daily_runs": 2,
        "schedule": {
            "frequency": "daily",
            # Runs TWICE (12 + 4). time_label carries both on the tile; `time`
            # stays the sortable 12:00 start so it still orders at noon.
            "time": "12:00 PM",
            "time_label": "12 PM + 4 PM CST",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Scan complete — new photos screened + proposed, ready approvals scheduled. (Approvals advance one round-trip per run; use Run Now to advance faster.)",
            "message_failed": "❌ Run failed. Check the log above (usually a Slack or Anthropic API / rate-limit issue), then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Do an extra pass now — screen + propose new photos and schedule any that are fully approved.",
                "module": "automations.brand_audit.social_inbox",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "vantura-payroll",
        "name": "Vantura Weekly Payroll (prep)",
        "creator": "Carlos",
        "emoji": "🧾",
        "color": "#2E86AB",
        "category": "📊 Metrics",
        "description": "Preps the week on the Vantura Master Sales Board so Carlos only enters judgement inputs: downloads the ICD dd Detail crosstab itself from Tableau (Direct Deposit ICD VIEW → DD DETAIL), loads it into RAW with the week stamp, sets Commission!B1, re-points the per-campaign P&L, refreshes, and DMs Carlos as Lucy.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Downloads the **ICD dd Detail** crosstab straight from "
            "Tableau — no manual export needed (real-Chrome CDP pull, same "
            "route as the churn report).\n"
            "**•** Appends the week's rows to **RAW** (cols A–H; the "
            "Commission ARRAYFORMULA in col I computes itself) and stamps "
            "the week number in col A.\n"
            "**•** Sets **Commission!B1** to the new week.\n"
            "**•** Re-points the per-campaign **P&L** formulas, triggers "
            "**Refresh commission sheets**, and runs the read-only checks.\n"
            "**•** DMs **Carlos** as Lucy: week loaded, RAW row range, sync "
            "summary, what's left to do by hand.\n\n"
            "WHAT STAYS HUMAN\n"
            "Bonuses / no-pay / rate changes, final verify, and printing the "
            "commission pack. The week auto-locks Thursday ~11am via the "
            "board's own Apps Script trigger.\n\n"
            "WHEN IT RUNS\n"
            "**Wednesdays 11:00 AM** on Lucy 2. Currently DRY-RUN gated: it "
            "pulls and previews everything but writes nothing until the run "
            "is sandbox-verified and the wrapper is flipped to --live."
        ),
        # Deep-links to the RAW tab this run appends the week's rows to
        # (sh.worksheet("RAW") in vantura_payroll/run.py).
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY/edit"
                      "?gid=1425857248#gid=1425857248"),
        "assignees": ["Lucy 2"],
        # Runs on Lucy 2 — its warm Tableau session + the Wednesday 11am launchd
        # job (com.alphalete.vantura-payroll-wed) live there. A Hub "play" from
        # ANY machine routes the run to Lucy 2 via the mini-control queue.
        "run_machine": "Lucy 2",
        "run_rerun_id": "vantura_payroll",
        # Self-running weekly launchd job: it doesn't report a per-day completion
        # to the Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [2],  # Wednesday
            "time": "11:00 AM",
            "estimated_minutes": 10,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Payroll prep done — crosstab pulled, week loaded into RAW, Commission!B1 set, P&L refreshed. Check the log for the RAW row range and the checks, then enter bonuses/no-pay/rates, verify, and print.",
            "message_failed": "❌ Run failed. Check the log above (usually the Tableau pull or a RAW column-map mismatch), fix, then run again.",
        },
        "actions": [
            {
                "label": "Run Prep",
                "icon": "▶",
                "primary": True,
                "help": "Pulls the DD Detail crosstab from Tableau and preps the week (DRY-RUN while the scaffold is unverified — previews everything, writes nothing).",
                "module": "automations.vantura_payroll.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "vantura-churn",
        "name": "Vantura Churn & Activations (daily board refresh)",
        "creator": "Carlos",
        "emoji": "📉",
        "color": "#2E86AB",
        "category": "📊 Metrics",
        "description": "Refreshes the Vantura Master Sales Board every morning: pulls each owner's 60-day Order Log, the Churn Rates dashboard and the Activation Rates view from Tableau, computes the 0-30 bases/disconnects and the 0-30 / 31-60 activation rates, reconciles both against their dashboards, writes Carlos's LUCY CHURN + Activations tabs and Atef's Churn tab. As of 2026-07-20 it only REFRESHES the board (runs --no-post); the B2B Metrics run (7:45am) takes the churn screenshots from that board and posts them.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Pulls the **Order Log**, the **Churn Rates** crosstab "
            "and the **Activation Rates** view.\n"
            "**•** Computes per-product activation bases + 0-30 disconnects, "
            "and the office **0-30 / 31-60 activation rates**.\n"
            "**•** Builds a **per-rep 0-30 activation-rate list** (ranked, "
            "reps with data only). The 0-30 bucket doesn't exist in Tableau "
            "— it's rebuilt by summing the 0-7 / 8-14 / 15-30 buckets.\n"
            "**•** **Reconciles before writing** — churn base/rate vs CHURN "
            "RATES, and the per-rep rates vs the office totals. Normal "
            "Tableau refresh drift is tolerated (base ±10%, churn ±0.5pp) "
            "and logged; a bigger gap writes NOTHING and emails Megan.\n\n"
            "WHEN IT RUNS\n"
            "**Daily 7:00 AM** on Lucy 2 (refresh only). The B2B Metrics run "
            "posts from it at **7:45 AM**."
        ),
        # Deep-links to the LUCY CHURN tab this run refreshes.
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY/edit"
                      "?gid=1629055677#gid=1629055677"),
        "assignees": ["Lucy 2"],
        # Runs on Lucy 2 — its warm Tableau session + the daily 7am launchd
        # job (com.alphalete.vantura-churn-daily) live there. A Hub "play"
        # from ANY machine routes the run to Lucy 2 via the mini-control queue.
        "run_machine": "Lucy 2",
        "run_rerun_id": "vantura_churn",
        # Self-running daily launchd job: it doesn't report a per-day
        # completion to the Hub, so keep it out of "due today" tallies.
        "self_scheduled": False,
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 15,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Board refreshed — bases, disconnect rolloff, and activations written; numbers reconciled against the Churn Rates dashboard before any write.",
            "message_failed": "❌ Run failed — the board was NOT written, so it's showing the previous run's numbers (stale, not wrong). Don't just re-run: the reconcile gate already tolerates normal Tableau refresh drift (base ±10%, churn ±0.5pp), so a mismatch means the Order Log and the CHURN RATES dashboard genuinely disagree by more than that. Check the Order Log pull (owner filter / 60-day window), then whether CHURNRATES has finished refreshing, before re-running or touching the sheet by hand. A failure is flagged in #claudecorrections-and-requests.",
        },
        "actions": [
            {
                "label": "Refresh Now",
                "icon": "▶",
                "primary": True,
                "help": "Full refresh: pull, compute, reconcile, write. The reconcile gate means a bad pull can never write the board.",
                "module": "automations.vantura_churn.run",
                "args_fn": lambda: [],
            },
            # No secondary actions on purpose — the "⚙️ More actions" expander
            # only renders when one exists, so the card stays a single button
            # (Megan 2026-07-18). Dry runs are still available via
            # `lucy rerun vantura_churn --dry-run`.
        ],
    },
    {
        "id": "att-churn",
        "name": "B2B Churn — Wireless / New INT / AIR tabs (all offices)",
        "creator": "Carlos",
        "emoji": "📉",
        "color": "#8E44AD",
        "category": "📊 Metrics",
        "description": "Fills the 'Lucy Wireless Churn', 'Lucy New INT Churn' and 'Lucy AIR Churn' tabs on EVERY B2B office's board — the persistent, dated, per-rep churn report Carlos wanted these three products to have (built 2026-07-19 to 'act like the D2D fiber-office metrics report'). Currently Carlos (Vantura Master Sales Board) + Atef/Domin8 (All In One - Atef); adding an office is one config row, no new Tableau view. Crosstab-pulls three ALL-TEAM CHURNRATES views (CarlosTEAMWireless / CarlosTEAMNewINTEXP / CarlosTEAMAIREXP) ONCE each, then slices every office's owner out in code and runs the D2D new_internet_churn fill (dated column, missing reps, colours, dark-rep hide). Posts nothing — the B2B Metrics run (7:45am) posts its own churn SCREENSHOTS separately; these are the maintained sheet tabs.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills the **Lucy Wireless / New INT / AIR churn** tabs on every "
            "B2B office's board — a dated per-rep churn column each morning "
            "(ranked, coloured, missing reps added). It pulls the three "
            "all-team churn views once and slices each office out in code, so "
            "adding an office is one config row. Writes the tabs only — **posts "
            "nothing** (the B2B Metrics run posts the churn screenshots).\n\n"
            "OFFICES\n"
            "Carlos (Vantura Master Sales Board) + Atef/Domin8 (All In One - "
            "Atef).\n\n"
            "WHEN IT RUNS\n"
            "In the **4am flow** on Lucy 2, right after Vantura Churn (they "
            "share one Chrome session, so it runs after Vantura finishes). A "
            "failed pull keeps the previous numbers and is flagged in "
            "**#claudecorrections-and-requests**."
        ),
        # Deep-links to the Lucy Wireless Churn tab (New INT gid 916425770,
        # AIR gid 866551208 are the sibling tabs in the same workbook).
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY/edit"
                      "?gid=2062141872#gid=2062141872"),
        "assignees": ["Lucy 2"],
        # Runs on Lucy 2 — Carlos's Tableau identity owns these custom views,
        # and the daily 7:15am launchd job (com.alphalete.att-churn-daily) lives
        # there. A Hub "play" from ANY machine routes to Lucy 2 via mini-control.
        "run_machine": "Lucy 2",
        "run_rerun_id": "att_churn",
        # Runs in Lucy 2's 4am orchestrator flow, sequenced `after` vantura_churn
        # (they share the CDP Chrome; the port-9246 lock serializes them). Moved
        # off the standalone 7:15am launchd 2026-07-28.
        "schedule": {
            "frequency": "daily",
            "time": "4 AM flow (when data's ready)",
            "estimated_minutes": 12,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Tabs filled — Wireless, New INT and AIR churn each got today's dated column (per-rep, ranked, coloured).",
            "message_failed": "❌ Run failed — one or more of the three churn tabs did NOT update, so they're showing the previous run's numbers (stale). Usual cause on Lucy 2: the CDP Chrome/Tableau session (TargetClosedError = a human's Chrome or a crash mid-pull), or a CHURNRATES view that hasn't refreshed. A failure is flagged in #claudecorrections-and-requests.",
        },
        "actions": [
            {
                "label": "Fill Now",
                "icon": "▶",
                "primary": True,
                "help": "Pull all three products and write the tabs. Preview (no write) via `lucy --machine \"Lucy 2\" rerun att_churn` (drop --fill).",
                "module": "automations.att_order_log.churn_run",
                "args_fn": lambda: ["--fill"],
            },
        ],
    },
]
