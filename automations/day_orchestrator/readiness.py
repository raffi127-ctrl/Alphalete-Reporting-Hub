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

import contextlib
import datetime as dt
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from automations.day_orchestrator import registry


# Sources we've already alerted about for an unknown probe type, deduped for the
# life of the process so the circle-back passes don't spam corrections with the
# same misconfiguration.
_UNKNOWN_PROBE_ALERTED: set = set()


@dataclass
class Readiness:
    ready: bool
    reason: str
    # "Not ready" has two very different meanings and the noon backstop needs to
    # tell them apart. The usual one is "the data hasn't landed yet" — if it never
    # lands, that's a MISS and a human should hear about it. The other is "there
    # is genuinely nothing to do" (sci_campaigns: the tab is already current
    # through the newest tracker email Adriana has sent). Both must block the run,
    # but only the first is a failure. Set this on the second — run._apply_backstop
    # then retires the report SKIPPED instead of MISSED_NOT_READY, so a normal
    # quiet week stops posting a red card + a fix-block (Eve 2026-07-31).
    nothing_to_do: bool = False


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

    def known_ready_sources(self):
        """The sources this run has ALREADY proved ready — the sticky set, with
        NO probing. The wave harvest reads this so it can prime a view the moment
        the gate flips without spending a single extra Tableau hit."""
        return set(self._ready)

    @contextlib.contextmanager
    def probe_pass(self):
        """ONE Tableau login for every probe inside this block (Megan 2026-08-18).

        Each probe calls download_crosstab_patchright deep inside a helper module
        (raf_captainship_bonus.tableau_pull, org_sales_board.section_pull, ...)
        with no `page`, so today each one opens its OWN ownerville->Tableau SSO
        login. The ledger measured 16 a day spent this way — buying no data at
        all, just asking "is it there yet". Flipping the env for the duration
        makes them share one context (fresh page each) without threading a page
        through every helper's signature.

        Deliberately NOT a frequency cut: the fallback hours suggest ~187 probes
        a day worst case but only 16 actually happen, so data lands well before
        those floors and probing less often would delay real reports. Cheaper
        probes, not fewer.

        DEFAULT OFF until proven, same gate every report split went through --
        probes that pull the SAME worksheet differing only by URL params would
        leak filter state into each other. (The captainship_bonus pair looks like
        that shape but cannot collide: raf runs on Lucy 1, carlos on Lucy 2.)
        Enable with PROBE_SHARED_SESSION=1."""
        if os.environ.get("PROBE_SHARED_SESSION", "").strip() not in ("1", "on", "true"):
            yield
            return
        prev = os.environ.get("TABLEAU_SHARED_SESSION")
        os.environ["TABLEAU_SHARED_SESSION"] = "1"
        try:
            yield
        finally:
            try:
                from automations.shared.tableau_patchright import close_shared_session
                close_shared_session()      # never hold the profile across passes
            except Exception:               # noqa: BLE001 — teardown is best-effort
                pass
            if prev is None:
                os.environ.pop("TABLEAU_SHARED_SESSION", None)
            else:
                os.environ["TABLEAU_SHARED_SESSION"] = prev

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
                # Always ready since the source went hybrid (2026-08-03): the
                # Double Entry half needs no sender, so there's nothing to wait
                # for and a "0 senders in" hold would now block a run that has
                # 37 offices' worth of real data. The emailed books are still
                # reported here — they carry the ~60 owners Double Entry doesn't
                # expose — but as INFO, not a gate: the fill is incremental, so
                # a book that lands later fills on the next run and never wipes
                # what's already there.
                from automations.financial_report import email_source as fes
                try:
                    n = fes.any_available(since_days=7)
                except Exception:  # noqa: BLE001 — advisory only, never a gate
                    n = -1
                extra = (f"{n}/3 email senders also in" if n >= 0
                         else "email probe skipped")
                return Readiness(True, f"Double Entry always available ({extra})")
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
                # Not ready, but NOT a miss: every week Adriana has sent is
                # already on the tab. She mails a Saturday week-ending the
                # FOLLOWING Friday, usually late in the day, and it has slipped
                # to Sunday twice — so a Friday that ends with nothing to fill is
                # the normal case, not a fault. nothing_to_do keeps the noon
                # backstop from calling it MISSED (Eve 2026-07-31).
                return Readiness(
                    False, f"no new tracker email — {tab!r} is current through "
                           f"WE {ses.we_label(max(inbox))}",
                    nothing_to_do=True)
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

        if ptype == "org_board_posted":
            return self._probe_org_board_posted(source_id, probe)

        if ptype == "dd_week":
            return self._probe_dd_week(source_id, probe)

        # An unknown probe type means the report's CONFIG names a probe this
        # running build doesn't implement — the split that took the Tableau
        # country trackers down on 2026-07-31. schedule_config gated them on
        # 'tracker_extract' one commit BEFORE readiness learned that probe type;
        # the mini had the config but not the handler, so every pass returned
        # NOT-ready. The report circled all morning and was abandoned — no
        # capture, no post, and (because "never became ready" is not "ran and
        # failed") no failure email. A gate silently starved a report to death.
        #
        # FAIL OPEN instead: a gate must never skip a report (Megan's standing
        # rule), and a probe this build can't run is a WIRING bug, not evidence
        # the data is missing. Run ungated and fire a one-shot alert so the
        # misconfiguration is loud, not silent.
        self._alert_unknown_probe(source_id, ptype)
        return Readiness(True, f"MISCONFIGURED: unknown probe type {ptype!r} — "
                               f"running UNGATED (fix {source_id}'s probe wiring)")

    def _alert_unknown_probe(self, source_id: str, ptype: str) -> None:
        """One-shot heads-up that a source names a probe type this build can't
        run, so a config/code split can never again silently starve a report.
        Best-effort and deduped per source for the life of the process — an alert
        must never break the pass it describes."""
        if source_id in _UNKNOWN_PROBE_ALERTED:
            return
        _UNKNOWN_PROBE_ALERTED.add(source_id)
        try:
            from automations.day_orchestrator import notify
            notify.post_alert(
                "",
                ["*Readiness misconfigured — running a report UNGATED*",
                 f"• source `{source_id}` names probe type `{ptype}`, which this "
                 f"build doesn't implement.",
                 "",
                 "Failing open so the report still runs (a gate never skips a "
                 "report), but its data-freshness gate is NOT active until the "
                 "probe handler is deployed. Usually a half-shipped change — the "
                 "config gates on a probe whose code isn't on this machine yet. "
                 "Fix by deploying the handler, or reverting the source's probe "
                 "wiring."],
                tag="readiness-unknown-probe",
                # Per-process dedup only silences the pass we're IN: a
                # half-shipped probe is still misconfigured tomorrow, and it
                # posted again every morning. One thread, repeats inside it.
                incident=f"readiness-probe-{source_id}")
        except Exception as e:  # noqa: BLE001 — an alert must never sink the pass
            print(f"[readiness] unknown-probe alert skipped ({source_id}): {e}",
                  flush=True)

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

        # Tableau serves this crosstab as UTF-16 tab-separated at times and
        # UTF-8 comma at others; read_crosstab auto-detects both. A plain
        # utf-8-sig DictReader choked on the UTF-16 BOM (0xff) and left
        # dd_populate blocked until a lucky retry served UTF-8 (2026-08-06).
        try:
            from automations.override_bulletin.pulls import read_crosstab
            grid = read_crosstab(out)  # list of row-lists, header first
        except Exception as e:  # noqa: BLE001
            return Readiness(False, f"cannot read DD probe CSV ({e})")
        header = grid[0] if grid else []
        data_rows = grid[1:]
        if len(data_rows) < min_rows:
            return Readiness(False, f"DD extract thin ({len(data_rows)} rows) — still filling")
        # locate the date column by header name (case/space-insensitive)
        want = " ".join(str(date_col).lower().split())
        di = next((i for i, h in enumerate(header)
                   if " ".join(str(h).lower().split()) == want), None)
        if di is None:
            return Readiness(False, f"DD probe missing column {date_col!r}")
        # newest deposit date -> its week-ending Sunday
        newest = None
        for r in data_rows:
            d = _parse_date(r[di]) if di < len(r) else None
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

    def _probe_org_board_posted(self, source_id: str, probe: dict) -> Readiness:
        """Ready once the board has actually been POSTED to
        #top-leaders-alphalete-org. The draft for review is a picture of the very
        board the whole org just saw, so the post is what makes it worth
        reviewing (Eve 2026-08-04: "tiene que armarse el draft y enviarse
        automáticamente luego de postearse en #top-leaders-alphalete-org").

        WHAT THIS REPLACED, and why. The draft used to answer to a clock and a
        rule of its own: `not_before 09:30` plus `org_board_filled`, which holds
        until YESTERDAY's column is filled for every section but the day-behind
        ones. The public post clears neither — slack_post.fill_gate posts unless
        yesterday is ENTIRELY empty. So the two could disagree, and on 2026-08-04
        they did: the board went out at 08:33, and at 11:00 the draft had still
        not reached #revision-emails — an hour lost to the clock alone, then a
        completeness bar the board had already been published without. Nobody was
        told, because a report that never becomes ready never runs, never fails,
        and writes no Hub Activity row.

        THE SIGNAL is slack_post's own once-a-day state file, which is written
        only after a real post lands. No Slack call, no Sheets read, and no new
        source of truth: the same file that stops the 25-minute passes reposting
        is what tells the draft the board is out. Both run on the mini, so the
        file the post writes is the file this reads.

        FAILS OPEN at `fallback_hhmm` (default 11:30, deliberately before the
        12:00 orchestrator backstop): if the post never lands, the draft still
        goes up for review, exactly as it did when the data gate opened at 11:30.
        A silent board must not also cost the day's email.
        """
        fallback = str(probe.get("fallback_hhmm", "11:30"))
        try:
            from automations.org_sales_board import slack_post as sp   # heavy: lazy
            posted = sp._already_posted(self.target_date.isoformat())
        except Exception as e:  # noqa: BLE001 — a probe must never sink the report
            return Readiness(True, f"cannot read the board-post marker "
                                   f"({type(e).__name__}) — not holding the draft")
        if posted:
            return Readiness(True, "the board is posted in "
                                   "#top-leaders-alphalete-org — building the draft")
        try:
            fb_h, fb_m = (int(x) for x in fallback.split(":"))
            now = dt.datetime.now()
            if (now.hour, now.minute) >= (fb_h, fb_m):
                return Readiness(True, f"past {fallback} and the board still has not "
                                       f"posted — putting the draft up for review "
                                       f"anyway (a human still has to approve it)")
        except Exception:  # noqa: BLE001 — an unparseable hour just means no
            pass                # fail-open clock; the post itself still opens it
        return Readiness(False, f"the board has not posted to "
                                f"#top-leaders-alphalete-org yet — waiting for it "
                                f"(or {fallback})")

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
            # The SAME url the fill pulls — week-pinned + :refresh=yes. Without
            # the pin this navigated the bare view, which on a Monday is the
            # brand-new week, so max(date) could never reach the completed
            # Sunday and the gate always fell open at the fallback hour
            # (Eve 2026-08-10).
            download_crosstab_patchright(
                _sp.pinned_view_url(spec, self.target_date),
                spec.crosstab_sheet, out, verbose=False)
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
        Reuses the report stack's own patchright crosstab download.

        NOTE: this used to claim "no fresh login (warm session)". That was wrong
        — download_crosstab_patchright with no `page` opens its OWN
        tableau_session(), i.e. a fresh SSO login every probe. The access ledger
        proved it (day_orchestrator: 16 logins on 2026-08-18). See
        ReadinessCache.probe_pass for the shared-login fix."""
        # FAIL-OPEN FLOOR — added 2026-08-25, and the reason is the paragraph in
        # _probe_source about a gate starving a report to death. Every other
        # probe here carries a fallback_hhmm; this one did not, and it is also
        # the one the daily_metrics notes tell the next person to wire when a
        # metric comes out with yesterday's numbers. Wired without a floor, a
        # not-ready verdict has no way out: the pass circles all morning and the
        # report never runs, which is worse than the stale number it was meant
        # to prevent. No source used this probe type when the floor was added,
        # so nothing changed behaviour; the omission was a loaded gun, not a
        # working design. (att_orderlog keeps its own copy of this check — that
        # path is live and was left untouched on purpose.)
        past, why_floor = _past_fallback(probe.get("fallback_hhmm"))
        if past:
            return Readiness(True, why_floor)

        view_url = probe.get("view_url")
        crosstab_sheet = probe.get("crosstab_sheet")
        date_col = probe.get("date_col")
        min_rows = int(probe.get("min_rows", 1))
        # A wiring mistake is NOT evidence the data is missing — same rule as
        # the unknown-probe-type branch. Run UNGATED and say so loudly rather
        # than hold a report on a typo.
        if not (view_url and crosstab_sheet and date_col):
            return Readiness(True, "MISCONFIGURED: probe needs view_url/"
                                   "crosstab_sheet/date_col — running UNGATED")

        try:
            from automations.shared.tableau_patchright import download_crosstab_patchright
        except Exception as e:
            return Readiness(True, f"cannot import tableau helper ({e}) — running")

        out = Path(tempfile.gettempdir()) / f"probe_{source_id.replace(':', '_')}.csv"
        try:
            download_crosstab_patchright(view_url, crosstab_sheet, out, verbose=False)
        except Exception as e:
            line = str(e).splitlines()[0][:120] if str(e) else repr(e)
            return Readiness(False, f"extract not pullable yet ({line})")

        # days_back: which day must the extract reach. 0 (default) = today, the
        # old behaviour. 1 = the latest COMPLETED day, which is what an extract
        # that refreshes overnight with yesterday's finalised rows can actually
        # satisfy — gating such a source on TODAY is unsatisfiable at 4am and
        # just burns the morning down to the floor. att_orderlog learned this
        # the same way and defaults to 1.
        check = self.target_date - dt.timedelta(days=int(probe.get("days_back", 0)))
        ok, why = _csv_covers_date(out, date_col, check, min_rows)
        return Readiness(ok, why)


def _past_fallback(fallback) -> Tuple[bool, str]:
    """Is the clock past a probe's fail-open floor? (False, "") when there is no
    floor configured or the string is unparseable — a bad `fallback_hhmm` must
    never itself decide a gate."""
    if not fallback:
        return False, ""
    try:
        fb_h, fb_m = (int(x) for x in str(fallback).split(":"))
    except Exception:  # noqa: BLE001 — a bad floor string is not a verdict
        return False, ""
    now = dt.datetime.now()
    if (now.hour, now.minute) >= (fb_h, fb_m):
        return True, f"past {fallback} fallback — running ungated"
    return False, ""


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
