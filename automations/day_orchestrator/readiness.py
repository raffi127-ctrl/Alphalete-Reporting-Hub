"""Readiness — is a report's data actually available yet?

Locked design (Megan 2026-06-23):
  * TABLEAU only gets a readiness gate. The probe asks "are today's rows actually
    present in the extract?" — a date-coverage check, NOT a clock time.
  * AppStream is always up to date → no probe, immediately ready.
  * pure-API → ready.
  * upload-gated → MANUAL (handled by the loop, not probed here).

Per-source, cached per pass, MONOTONIC: once a Tableau source has today's data it
never un-refreshes, so a READY verdict sticks and we stop probing it.

Session gate: every Tableau/AppStream probe first checks the ownerville session
is warm (the holder exports cookies every few minutes). If stale, the source is
NOT ready with reason 'ownerville session stale' — fail closed, never run with a
dead session (design §8).
"""
from __future__ import annotations

import datetime as dt
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from automations.day_orchestrator import registry


@dataclass
class Readiness:
    ready: bool
    reason: str


# ---------------- session warmth ----------------

def session_status(stale_after_minutes: int = 20) -> Tuple[bool, float, str]:
    """(warm, age_minutes, reason). Warm = the holder's exported ownerville
    storage_state file was refreshed within `stale_after_minutes`. The holder
    re-exports every few minutes while the session is live; a stale file means
    the session went down and needs a re-seed on the mini."""
    try:
        from automations.shared.tableau_patchright import OWNERVILLE_STORAGE_STATE as ov
    except Exception as e:  # import shouldn't fail, but never crash the probe
        return False, float("inf"), f"cannot import storage_state path ({e})"
    p = Path(ov)
    if not p.exists():
        return False, float("inf"), (
            f"no ownerville session yet ({p.name} missing) — seed the holder on the mini")
    age_min = (dt.datetime.now().timestamp() - p.stat().st_mtime) / 60.0
    if age_min > stale_after_minutes:
        return False, age_min, (
            f"ownerville session stale ({age_min:.0f}m since last export; "
            f"holder may be down) — re-seed the mini")
    return True, age_min, "warm"


# ---------------- per-source probe cache (monotonic) ----------------

class ReadinessCache:
    """One per orchestrator run. Caches a source's verdict for the whole day:
    once READY, sticky (never re-probe). NOT-ready is re-probed each pass."""

    def __init__(self, cfg: registry.Config, *, dry_run: bool, target_date: dt.date,
                 stale_after_minutes: int = 20, verbose: bool = True,
                 gate_unprobed: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run
        self.target_date = target_date
        self.stale_after = stale_after_minutes
        self.verbose = verbose
        self.gate_unprobed = gate_unprobed
        self._ready: Dict[str, Readiness] = {}   # sticky READY verdicts

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [readiness] {msg}", flush=True)

    def source_ready(self, source_id: str) -> Readiness:
        if source_id in self._ready:
            return self._ready[source_id]            # sticky
        r = self._probe_source(source_id)
        if r.ready:
            self._ready[source_id] = r               # cache only READY (monotonic)
        return r

    def report_ready(self, rpt: registry.Report) -> Readiness:
        """A report is ready when ALL its data sources are ready. AppStream/API
        are immediately ready; upload is never gated here."""
        if rpt.source_type in ("appstream", "api"):
            return Readiness(True, f"{rpt.source_type} — immediately ready (no probe)")
        if rpt.source_type == "upload":
            return Readiness(True, "upload — manual (not gated)")
        if rpt.source_type == "email":
            return self._probe_email(rpt)
        # tableau: require a warm session, then every source ready.
        warm, age, why = session_status(self.stale_after)
        if not warm:
            return Readiness(False, why)
        for sid in rpt.data_sources:
            r = self.source_ready(sid)
            if not r.ready:
                return Readiness(False, f"{sid}: {r.reason}")
        return Readiness(True, "all sources ready")

    # ---- email-fed reports: ready when this week's source email has landed ----
    def _probe_email(self, rpt: registry.Report) -> Readiness:
        """No clock gate — ready only once the report's weekly source email is in.
        residential_rep_count waits for Archey's xlsx (reusing the report's OWN
        _expected_week_ending + email_source.latest_week_ending, so the gate and
        the report agree). Other email reports have no probe yet → run on schedule.
        Fail-OPEN on a probe error (IMAP hiccup) so a transient blip can't block
        forever — the report itself still refuses to fill from a missing email."""
        try:
            if rpt.report_id == "residential_rep_count":
                from automations.residential_rep_count import email_source
                from automations.residential_rep_count.run import _expected_week_ending
                expected = _expected_week_ending(self.target_date)
                latest = email_source.latest_week_ending()
                if latest and latest >= expected:
                    return Readiness(True, f"Archey email WE {expected.month}/{expected.day} is in")
                seen = f"latest WE {latest.month}/{latest.day}" if latest else "none found"
                return Readiness(
                    False, f"waiting on Archey's WE {expected.month}/{expected.day} email ({seen})")
            if rpt.report_id == "frontier_opt":
                # Ready once the two DAILY Events PDFs (by-store + events) have
                # landed — they carry the sales/percentages. The quality
                # scorecard lags ~2wk and the report forces it to the run week,
                # so it isn't a gate. Partial-safe either way.
                from automations.alphalete_org_report import frontier_email_source as fes
                avail = fes.latest_available()
                dailies = sum(1 for g in avail if "Daily Sales" in g)
                if dailies >= 2:
                    return Readiness(True, f"Frontier Events PDFs in ({len(avail)}/3)")
                return Readiness(
                    False, f"waiting on Frontier Events daily PDFs ({dailies}/2 in)")
            if rpt.report_id == "financial_report":
                # 3 senders land across Tue–Wed (hubtruth Tue PM, melissab Wed,
                # jsanchez Mon/Tue); a Thursday run should see all 3. Ready once
                # >=2 are in (the dominant hubtruth + at least one more). The
                # report is incremental/partial-safe, so this only avoids a
                # too-early empty run — a missing sender is filled next run.
                from automations.financial_report import email_source as fes
                n = fes.any_available(since_days=7)
                if n >= 2:
                    return Readiness(True, f"Financial workbooks in ({n}/3 senders)")
                return Readiness(
                    False, f"waiting on this week's Financial workbooks ({n}/3 senders in)")
            if rpt.report_id == "sci_campaigns":
                # Ready once the inbox holds a tracker week the tab does NOT yet
                # have. Keyed off the EMAIL's own week (its subject), never the
                # clock: Adriana's email for a Saturday week-ending arrives the
                # FOLLOWING Friday, usually late in the day, and has slipped to
                # a Sunday twice. A date-based gate would fire at 4am against an
                # inbox that won't get the mail for another 12 hours.
                # "Everything already filled" is also NOT-ready — there is
                # genuinely nothing to do, and saying so keeps the orchestrator
                # circling back until the week's email actually lands.
                from automations.sci_campaigns import email_source as ses
                from automations.sci_campaigns import run as scr
                from automations.sci_campaigns import fill as scf
                from automations.recruiting_report.fill import open_by_key, _retry
                inbox = ses.available_weeks()
                if not inbox:
                    return Readiness(False, "no tracker email found at all")
                sh = open_by_key(scr.SHEET_ID)
                tab = scr.PROD_TAB if "--real" in rpt.base_args else scr.SANDBOX_TAB
                grid = _retry(scr._find_ws(sh, tab).get_all_values)
                cols = scf.week_columns(grid)
                have = scr._filled_weeks(grid)
                todo = sorted(w for w in inbox if w >= scr.DEFAULT_SINCE
                              and scf.snap_to_column(w, cols) not in have)
                if todo:
                    return Readiness(
                        True, f"{len(todo)} unfilled tracker week(s) in the "
                              f"inbox (newest WE {ses.we_label(todo[-1])})")
                return Readiness(
                    False, f"no new tracker email — {tab!r} is current through "
                           f"WE {ses.we_label(max(inbox))}")
            return Readiness(True, "email — no probe wired; running on schedule")
        except Exception as e:  # noqa: BLE001 — fail open; the report self-guards
            return Readiness(
                True, f"email probe error ({type(e).__name__}) — running; report self-guards")

    # ---- the actual Tableau probe ----
    def _probe_source(self, source_id: str) -> Readiness:
        scfg = self.cfg.sources.get(source_id, {})
        probe = scfg.get("probe", {})
        ptype = probe.get("type", "not_configured")

        if ptype == "not_configured":
            # No real readiness probe wired for this source yet. Default: just
            # run on the report's not_before schedule (like the manual process
            # did) — the report's own Tableau pull + the circle-back retry handle
            # a not-yet-refreshed extract. Set settings.gate_unprobed_sources=true
            # to instead BLOCK until a real probe is wired (hardening later).
            if self.gate_unprobed:
                return Readiness(False, "no readiness probe wired (gated)")
            return Readiness(True, "no readiness probe — running on schedule")

        if ptype == "tableau_date_coverage":
            return self._probe_tableau_date_coverage(source_id, probe)

        if ptype == "box_daily":
            return self._probe_box_daily(source_id, probe)

        if ptype == "tracker_extract":
            return self._probe_tracker_extract(source_id, probe)

        if ptype == "att_orderlog":
            return self._probe_att_orderlog(source_id, probe)

        if ptype == "captainship_bonus":
            return self._probe_captainship_bonus(source_id, probe)

        if ptype == "org_board_filled":
            return self._probe_org_board_filled(source_id, probe)

        if ptype == "dd_week":
            return self._probe_dd_week(source_id, probe)

        return Readiness(False, f"unknown probe type {ptype!r}")

    def _probe_dd_week(self, source_id: str, probe: dict) -> Readiness:
        """Ready when the ORG DD Detail extract has THIS WEEK's deposits — so the
        DD bulletin runs on the current week's numbers, never last week's (the
        7/30 miss). DD is weekly (cl.DD Week = Sat/Sun deposit dates), so we can't
        use the generic day-coverage probe (its target is 'today'); we compare the
        extract's newest DD week against the week that just ended.

        Copies the VA exactly: she does it Thursday morning and sends by 10am with
        whatever's posted. So this HOLDS until the week is in, but FAILS OPEN at
        `fallback_hhmm` (default 09:30) — past it, run anyway so the send still
        lands by her 10am deadline. The hard_block in dd_data is the final net: if
        it fails open onto a still-empty week, the send refuses rather than post a
        blank one."""
        import datetime as _dt
        fallback = str(probe.get("fallback_hhmm", "09:30"))
        try:
            fb_h, fb_m = (int(x) for x in fallback.split(":"))
            now = _dt.datetime.now()
            if (now.hour, now.minute) >= (fb_h, fb_m):
                return Readiness(True, f"past {fallback} — running to hit the 10am "
                                       f"deadline (dd_data hard_block still guards "
                                       f"an empty week)")
        except Exception:  # noqa: BLE001
            pass

        view_url = probe.get("view_url")
        crosstab_sheet = probe.get("crosstab_sheet", "ORG DD Detail")
        date_col = probe.get("date_col", "cl.DD Week")
        min_rows = int(probe.get("min_rows", 20))
        if not view_url:
            return Readiness(False, "dd_week probe misconfigured (need view_url)")
        try:
            from automations.shared.tableau_patchright import download_crosstab_patchright
            from automations.override_bulletin.dd_data import week_just_ended
        except Exception as e:  # noqa: BLE001
            return Readiness(False, f"cannot import dd_week deps ({e})")

        due = week_just_ended()
        out = Path(tempfile.gettempdir()) / f"probe_{source_id.replace(':', '_')}.csv"
        try:
            download_crosstab_patchright(view_url, crosstab_sheet, out, verbose=False)
        except Exception as e:  # noqa: BLE001
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"DD extract not pullable yet ({line})")

        import csv as _csv
        try:
            with open(out, newline="", encoding="utf-8-sig") as f:
                rows = list(_csv.DictReader(f))
        except Exception as e:  # noqa: BLE001
            return Readiness(False, f"cannot read DD probe CSV ({e})")
        if len(rows) < min_rows:
            return Readiness(False, f"DD extract thin ({len(rows)} rows) — still filling")
        # newest deposit date -> its week-ending Sunday
        newest = None
        for r in rows:
            d = _parse_date(r.get(date_col, ""))
            if d and (newest is None or d > newest):
                newest = d
        if newest is None:
            return Readiness(False, f"no parseable dates in {date_col!r}")
        newest_we = newest + dt.timedelta(days=(6 - newest.weekday()))  # -> Sunday
        if newest_we >= due:
            return Readiness(True, f"DD week {newest_we.isoformat()} is in "
                                   f"(need >= {due.isoformat()})")
        return Readiness(False, f"DD extract only through week {newest_we.isoformat()}, "
                                f"waiting on {due.isoformat()}")

    def _probe_org_board_filled(self, source_id: str, probe: dict) -> Readiness:
        """Not a Tableau extract — the BOARD ITSELF. Ready once yesterday's column
        on the copy tab is filled for every daily section except the known
        day-behind ones (Retail JE, Frontier), or once the send-anyway hour
        passes. Gating the board EMAIL here rather than inside the module means an
        unfilled board leaves it PENDING/STILL_TRYING — circled back every pass,
        no burnt retries, no failure alert — instead of exiting non-zero three
        times and going red for a board that was merely late (Eve 2026-07-29)."""
        from automations.org_sales_board import data_gate
        yday = self.target_date - dt.timedelta(days=1)
        kw = {}
        if probe.get("send_anyway_after"):
            kw["send_anyway_after"] = probe["send_anyway_after"]
        ok, why = data_gate.gate(yday=yday, **kw)
        return Readiness(ok, why)

    def _probe_captainship_bonus(self, source_id: str, probe: dict) -> Readiness:
        """Is the just-ended week's CaptainsBonus / Captain Team activation data
        in the Tableau extract yet? These weekly per-rep crosstabs have NO per-day
        date column (already week-filtered), and a 0-activation week still LISTS
        every roster rep — so the real 'week is populated' signal is the Grand
        Total activations > 0. Pull the light activations crosstab (the report's
        own `probe_ready`) and gate on that.

        FAIL-OPEN at `fallback_hhmm` (default 10:00 — the old send time): past it,
        or on an import/pull error, RUN ANYWAY so a bonus report is never later
        than it used to be. The report's own zero-rep abort is the final net.
        `team` selects raf (Lucy 1) vs carlos (Lucy 2)."""
        team = str(probe.get("team", "raf")).lower()
        fallback = str(probe.get("fallback_hhmm", "10:00"))
        try:
            fb_h, fb_m = (int(x) for x in fallback.split(":"))
            now = dt.datetime.now()
            if (now.hour, now.minute) >= (fb_h, fb_m):
                return Readiness(True, f"past {fallback} fallback — running "
                                       "(bonus never held past its old send time)")
        except Exception:  # noqa: BLE001 — a bad fallback string must not break the gate
            pass
        try:
            if team == "carlos":
                from automations.carlos_captainship_bonus import tableau_pull as _tp
            else:
                from automations.raf_captainship_bonus import tableau_pull as _tp
        except Exception as e:  # noqa: BLE001 — code problem, not data: fail-open
            return Readiness(True, f"{team} bonus probe import failed ({e}) — running")
        try:
            grand, nreps = _tp.probe_ready(self.target_date)
        except Exception as e:  # noqa: BLE001 — not pullable yet: re-probe (floor backstops)
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"{team} CaptainsBonus not pullable yet ({line})")
        min_grand = int(probe.get("min_grand", 1))
        if grand >= min_grand:
            return Readiness(True, f"{team} week populated (grand activations "
                                   f"{grand}, {nreps} reps)")
        return Readiness(False, f"{team} week not in yet (grand activations {grand} "
                                f"< {min_grand}, {nreps} reps) — extract not refreshed")

    def _probe_att_orderlog(self, source_id: str, probe: dict) -> Readiness:
        """Is Carlos's ATT B2B ORDERLOG extract in for the target day? Fetches a
        NARROW window of the same .csv att_order_log pulls (via its real-Chrome
        CDP auth — a patchright session gets the wrong Tableau identity) and
        checks the max `sp.Order Date (copy)` reaches the target.

        FAIL-OPEN like box_daily — this gate must NEVER keep Carlos's log from
        posting: past `fallback_hhmm`, or on an import error, RUN ANYWAY. A
        genuine not-yet-pullable extract returns not-ready so the pass circles
        back and re-probes, with the floor as the backstop. Until it's
        live-verified on Lucy 2 the floor carries it (= the old clock)."""
        fallback = str(probe.get("fallback_hhmm", "05:30"))
        try:
            fb_h, fb_m = (int(x) for x in fallback.split(":"))
            now = dt.datetime.now()
            if (now.hour, now.minute) >= (fb_h, fb_m):
                return Readiness(True, f"past {fallback} fallback — running "
                                       "(never hold the order log)")
        except Exception:  # noqa: BLE001 — a bad fallback string must not break the gate
            pass
        min_rows = int(probe.get("min_rows", 1))
        try:
            from automations.att_order_log import freshness as _fr
        except Exception as e:  # noqa: BLE001 — code problem, not data: fail-open
            return Readiness(True, f"orderlog probe import failed ({e}) — running")
        out = Path(tempfile.gettempdir()) / f"probe_{source_id.replace(':', '_')}.csv"
        try:
            _fr.fetch_narrow_csv(self.target_date, out)
        except Exception as e:  # noqa: BLE001 — not pullable yet: re-probe (floor backstops)
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"ORDERLOG not pullable yet ({line})")
        # The extract refreshes OVERNIGHT with the prior day's finalised orders,
        # so "ready" = it reaches the latest COMPLETED day (yesterday by default),
        # NOT today — same-day B2B orders don't post until business hours, so
        # gating on today would report not-ready all morning and just hit the
        # floor. days_back tunes it; the fail-open floor covers a genuine
        # no-orders day (max date never reaches the check).
        check = self.target_date - dt.timedelta(days=int(probe.get("days_back", 1)))
        return Readiness(*_csv_covers_date(out, _fr.DATE_COL, check, min_rows))

    def _probe_tracker_extract(self, source_id: str, probe: dict) -> Readiness:
        """Is the Tableau EXTRACT behind a set of daily country tracker boards
        refreshed for the latest completed reporting day?

        Closes the gap Megan hit 2026-07-29 ("trackers were sent out today
        without being updated and we ran them anyway"): tableau_screenshots
        carried `data_sources: []`, and an empty list makes report_ready() check
        session warmth and then answer "all sources ready" — so nothing gated the
        boards on data at all. The boards are captured as IMAGES, so there is no
        crosstab in the run to inspect; this probe pulls the crosstab that
        org_sales_board already pulls off the same workbook every morning (same
        view, same worksheet, same parser, week-pinned + :refresh=yes) and checks
        its max date reaches the completed day.

        All of the config lives in automations.tableau_screenshots.freshness —
        one entry per EXTRACT, not per board, because a refresh is workbook-wide
        (3 pulls cover 8 boards). FAIL-OPEN past `fallback_hhmm` and on any error,
        like every other gate here: it may hold the run for a couple of hours, it
        may never skip it. A board whose extract is still stale when the run
        proceeds is held out of the thread and flagged by run.py, not posted as
        though it were fresh."""
        extract_id = probe.get("extract") or source_id
        try:
            from automations.tableau_screenshots import freshness as _fr
        except Exception as e:  # noqa: BLE001 — code problem, not data: fail-open
            return Readiness(True, f"tracker freshness import failed ({e}) — running")
        ok, why = _fr.extract_ready(extract_id, self.target_date)
        return Readiness(ok, why)

    def _probe_box_daily(self, source_id: str, probe: dict) -> Readiness:
        """Box (B2BBOXEnergyTracker/BoxDailyTracker) is the ORG Sales Board's
        LAST-landing source — its extract refreshes ~7-8am with the prior day's
        final numbers, so a board run before that writes incomplete Box columns.
        That's why the board used to sit on a hard cadence.not_before='08:00'
        (Megan 2026-07-11: replace the clock with a real readiness gate so it runs
        in its order the moment Box is in). This probe pulls the Box weekday-
        crosstab and confirms its max date has reached the latest COMPLETED
        reporting day — using the board's OWN week.completed_days (rollover-safe:
        Tue→[Mon], Mon→last Sun, Sat→Fri) and its OWN pull+parse, so the gate
        matches exactly what the fill reads. `min_rows` floors out a garbage/partial
        pull. The session-warmth gate already ran in report_ready(), so the warm
        ownerville cookies are reused (no fresh login).

        FAIL-OPEN (Megan 2026-07-13): this gate must NEVER skip the board. Box is
        reliably in by `fallback_hhmm` (the old not_before time), so if readiness
        can't be confirmed by then — a no-Box-sales target day (the 7/13 Monday skip:
        target was Sunday, which has no Box row, so max date never reached it), or a
        flaky probe pull — RUN ANYWAY rather than hold forever. Keeps the run-early-
        when-ready benefit but restores the old 8am reliability as a floor."""
        fallback = str(probe.get("fallback_hhmm", "08:00"))
        try:
            fb_h, fb_m = (int(x) for x in fallback.split(":"))
            now = dt.datetime.now()
            if (now.hour, now.minute) >= (fb_h, fb_m):
                return Readiness(True, f"past {fallback} fallback — running "
                                       f"(Box gate not held this late; never skip)")
        except Exception:  # noqa: BLE001 — a bad fallback string must not break the gate
            pass
        min_rows = int(probe.get("min_rows", 5))
        try:
            from automations.org_sales_board import section_pull as _sp
            from automations.org_sales_board import week as _wk
            from automations.shared.tableau_patchright import download_crosstab_patchright
        except Exception as e:  # noqa: BLE001
            return Readiness(False, f"cannot import Box pull ({e})")
        completed = _wk.completed_days(self.target_date)
        if not completed:
            return Readiness(True, "no completed reporting day to gate on — running")
        target = max(completed)
        spec = _sp.BOX_SPEC
        out = Path(tempfile.gettempdir()) / f"probe_{source_id.replace(':', '_')}.csv"
        try:
            download_crosstab_patchright(spec.view_url, spec.crosstab_sheet, out,
                                         verbose=False)
        except Exception as e:  # noqa: BLE001
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"Box extract not pullable yet ({line})")
        try:
            parsed = _sp.parse_crosstab_byday(spec, out, self.target_date)
        except Exception as e:  # noqa: BLE001
            return Readiness(False, f"Box crosstab not parseable yet ({str(e)[:100]})")
        owners = [o for o, m in parsed.items() if m.get(spec.metric)]
        if len(owners) < min_rows:
            return Readiness(False, f"Box crosstab thin ({len(owners)} owners "
                                    f"< {min_rows}) — extract not refreshed")
        maxd = max(d for o in owners for d in parsed[o][spec.metric])
        if maxd >= target:
            return Readiness(True, f"Box fresh through {maxd.isoformat()} "
                                   f"(need ≥ {target.isoformat()})")
        return Readiness(False, f"Box only through {maxd.isoformat()}, need "
                                f"{target.isoformat()} — extract not refreshed")

    def _probe_tableau_date_coverage(self, source_id: str, probe: dict) -> Readiness:
        """Lightweight: pull the source view's crosstab and confirm the target
        day's rows are present (max date >= target) with a row-count floor.
        Reuses the report stack's own patchright crosstab download — no fresh
        login (warm session), retried internally by the helper."""
        view_url = probe.get("view_url")
        crosstab_sheet = probe.get("crosstab_sheet")
        date_col = probe.get("date_col")
        min_rows = int(probe.get("min_rows", 1))
        if not (view_url and crosstab_sheet and date_col):
            return Readiness(False, "probe misconfigured (need view_url/crosstab_sheet/date_col)")

        try:
            from automations.shared.tableau_patchright import download_crosstab_patchright
        except Exception as e:
            return Readiness(False, f"cannot import tableau helper ({e})")

        out = Path(tempfile.gettempdir()) / f"probe_{source_id.replace(':', '_')}.csv"
        try:
            download_crosstab_patchright(view_url, crosstab_sheet, out, verbose=False)
        except Exception as e:
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"extract not pullable yet ({line})")

        ok, why = _csv_covers_date(out, date_col, self.target_date, min_rows)
        return Readiness(ok, why)


def _csv_covers_date(csv_path: Path, date_col: str, target: dt.date,
                     min_rows: int) -> Tuple[bool, str]:
    """True when the CSV has >= min_rows data rows and its max date in `date_col`
    reaches `target`. Tolerant date parsing; if no date parses, NOT ready."""
    import csv as _csv

    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
    except Exception as e:
        return False, f"cannot read probe CSV ({e})"

    if len(rows) < min_rows:
        return False, f"only {len(rows)} row(s) (< {min_rows} floor) — extract still filling"

    max_date = None
    for r in rows:
        d = _parse_date(r.get(date_col, ""))
        if d and (max_date is None or d > max_date):
            max_date = d
    if max_date is None:
        return False, f"no parseable dates in column {date_col!r}"
    if max_date >= target:
        return True, f"data through {max_date.isoformat()} (>= {target.isoformat()})"
    return False, f"data only through {max_date.isoformat()} (need {target.isoformat()})"


def _parse_date(s: str) -> Optional[dt.date]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%-m/%-d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
