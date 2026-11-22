"""Asking for one person's Digi Docs -- and the asks that must not become sends.

python -m pytest automations/icd_onboarding/test_digi_docs_request.py

Generating a bundle IS the send and there is no unsend, so nearly all of this
is about refusing.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.icd_onboarding import board as B
from automations.icd_onboarding import digi_docs_request as R

WEEK = dt.date(2026, 11, 16)
HEAD = ["Queued At", "Action", "Args", "By", "Status", "Result", "Finished At"]


class _WS:
    def __init__(self, rows):
        self._rows = rows
        self.appended = []

    def get_all_values(self):
        return [list(r) for r in self._rows]

    def append_row(self, row, value_input_option=None):
        self.appended.append(list(row))
        self._rows.append(list(row))


class _SS:
    def __init__(self, ws=None, missing=False):
        self._ws, self._missing = ws, missing

    def worksheet(self, title):
        if self._missing:
            raise RuntimeError("no such tab")
        return self._ws

    def add_worksheet(self, title=None, rows=None, cols=None):
        self._ws = _WS([])
        return self._ws


class _GC:
    def __init__(self, ss):
        self._ss = ss

    def open_by_key(self, key):
        return self._ss


def _wire(monkeypatch, *, cell="", queue_rows=(), machine="Lucy 3"):
    """Board cell for our person, and whatever is already on the queue."""
    monkeypatch.setattr(R, "_report_machine", lambda: machine)
    ws = _WS([list(HEAD)] + [list(r) for r in queue_rows])
    gc = _GC(_SS(ws))
    monkeypatch.setattr(R, "_client", lambda: gc)
    monkeypatch.setattr(R, "board_state", lambda o, w, n: cell)
    return ws


class TestTheArgs:
    def test_a_surname_with_a_space_survives_as_one_argument(self):
        """rerun splits with shlex, so an unquoted two-word name would arrive
        as two arguments and digi_docs would look for the wrong person."""
        got = R.args_for("Cristobal Saravia Ortez")
        assert got == "digi_docs --only 'Cristobal Saravia Ortez'"
        import shlex
        assert shlex.split(got) == ["digi_docs", "--only",
                                    "Cristobal Saravia Ortez"]

    def test_it_names_the_report_rerun_will_resolve(self):
        assert R.args_for("Ada Fournier").startswith(R.REPORT_ID + " ")

    def test_padding_does_not_become_part_of_the_name(self):
        assert R.args_for("  Ada Fournier  ") == "digi_docs --only 'Ada Fournier'"


class TestRefusals:
    def test_a_filled_cell_is_never_asked_again(self, monkeypatch):
        """The board says the documents went. A second ask is a second send."""
        _wire(monkeypatch, cell="11/22/2026")
        got = R.request("raf", "Ada Fournier", WEEK, dry_run=False,
                        log=lambda *a: None)
        assert got["ok"] is False
        assert got["why"] == "already sent"

    def test_an_already_queued_person_is_refused(self, monkeypatch):
        ws = _wire(monkeypatch, queue_rows=[
            ["now", "rerun", "digi_docs --only 'Ada Fournier'", "board",
             "queued", "", ""]])
        got = R.request("raf", "Ada Fournier", WEEK, dry_run=False,
                        log=lambda *a: None)
        assert got["ok"] is False and got["why"] == "already queued"
        assert ws.appended == [], "a second row is a second send"

    def test_a_running_row_counts_too(self, monkeypatch):
        _wire(monkeypatch, queue_rows=[
            ["now", "rerun", "digi_docs --only 'Ada Fournier'", "board",
             "running", "", ""]])
        got = R.request("raf", "Ada Fournier", WEEK, dry_run=False,
                        log=lambda *a: None)
        assert got["why"] == "already queued"

    def test_a_finished_row_does_not_block_a_new_ask(self, monkeypatch):
        """Someone whose last send FAILED has a done row and a blank cell --
        that is exactly when a person needs to be able to ask again."""
        ws = _wire(monkeypatch, queue_rows=[
            ["then", "rerun", "digi_docs --only 'Ada Fournier'", "board",
             "done", "sent 0", "then"]])
        got = R.request("raf", "Ada Fournier", WEEK, dry_run=False,
                        log=lambda *a: None)
        assert got["ok"] is True and got["queued"] is True
        assert len(ws.appended) == 1

    def test_somebody_elses_queued_row_does_not_block_us(self, monkeypatch):
        ws = _wire(monkeypatch, queue_rows=[
            ["now", "rerun", "digi_docs --only 'Bruno Castell'", "board",
             "queued", "", ""]])
        got = R.request("raf", "Ada Fournier", WEEK, dry_run=False,
                        log=lambda *a: None)
        assert got["ok"] is True
        assert len(ws.appended) == 1

    def test_another_report_queued_does_not_block_us(self, monkeypatch):
        _wire(monkeypatch, queue_rows=[
            ["now", "rerun", "daily_focus", "board", "queued", "", ""]])
        got = R.request("raf", "Ada Fournier", WEEK, dry_run=False,
                        log=lambda *a: None)
        assert got["ok"] is True

    def test_no_name_is_refused_before_anything_is_read(self, monkeypatch):
        got = R.request("raf", "   ", WEEK, dry_run=False, log=lambda *a: None)
        assert got["ok"] is False and got["why"] == "no name"


class TestDryByDefault:
    def test_nothing_is_queued_without_being_asked(self, monkeypatch):
        ws = _wire(monkeypatch)
        got = R.request("raf", "Ada Fournier", WEEK, log=lambda *a: None)
        assert got["ok"] is True and got["queued"] is False
        assert ws.appended == []

    def test_the_dry_answer_still_says_what_it_would_do(self, monkeypatch):
        _wire(monkeypatch, machine="Lucy 3")
        got = R.request("raf", "Ada Fournier", WEEK, log=lambda *a: None)
        assert got["machine"] == "Lucy 3"
        assert got["args"] == "digi_docs --only 'Ada Fournier'"


class TestTheQueuedRow:
    def test_it_is_a_rerun_of_the_report(self, monkeypatch):
        ws = _wire(monkeypatch)
        R.request("raf", "Ada Fournier", WEEK, by="board", dry_run=False,
                  log=lambda *a: None)
        row = ws.appended[0]
        assert row[HEAD.index("Action")] == "rerun"
        assert row[HEAD.index("Args")] == "digi_docs --only 'Ada Fournier'"
        assert row[HEAD.index("Status")] == "queued"
        assert row[HEAD.index("By")] == "board"


class TestTheMachineIsNotWrittenDown:
    def test_it_comes_from_the_report_s_own_config(self):
        """The OwnerVille session is per-machine, so the pin belongs to the
        report's config and not to this module."""
        import inspect
        src = inspect.getsource(R)
        assert "resolve_report" in src
        assert "Lucy 3" not in src, "the machine must not be hardcoded here"

    def test_a_report_that_is_gone_is_said_out_loud(self, monkeypatch):
        from automations.day_orchestrator import registry
        monkeypatch.setattr(registry, "resolve_report", lambda c, i: None)
        monkeypatch.setattr(registry, "load_config", lambda: object())
        with pytest.raises(RuntimeError, match="nothing to queue"):
            R._report_machine()


class TestTheBoardIsRead:
    def test_a_name_not_on_the_board_is_refused_loudly(self, monkeypatch):
        from automations.icd_onboarding import sheet as S

        class _Tab:
            title = "OBCL 11.16"

            def get_all_values(self):
                return [list(B.COLUMNS), ]

        monkeypatch.setattr(S, "board_for", lambda *a, **k: _Tab())
        with pytest.raises(RuntimeError, match="not on"):
            R.board_state("raf", WEEK, "Nobody Here")

    def test_somebody_marked_off_is_refused(self, monkeypatch):
        from automations.icd_onboarding import sheet as S
        head = list(B.COLUMNS) + list(S.PAST_THE_CHART)
        row = [""] * len(head)
        row[head.index("Name")] = "Ada"
        row[head.index("Last Name")] = "Fournier"
        row[head.index(B.TERMINATED_AT)] = "11/20/2026"

        class _Tab:
            title = "OBCL 11.16"

            def get_all_values(self):
                return [head, row]

        monkeypatch.setattr(S, "board_for", lambda *a, **k: _Tab())
        with pytest.raises(RuntimeError, match="marked off"):
            R.board_state("raf", WEEK, "Ada Fournier")

    def test_no_board_for_the_week_is_refused(self, monkeypatch):
        from automations.icd_onboarding import sheet as S
        monkeypatch.setattr(S, "board_for", lambda *a, **k: None)
        with pytest.raises(RuntimeError, match="no board"):
            R.board_state("raf", WEEK, "Ada Fournier")


class TestWhatItNeverDoes:
    def test_it_presses_nothing_itself(self):
        """OwnerVille's own section state is the gate on a send, never this.
        If this module ever drives a browser, that rule has been broken."""
        import inspect
        src = inspect.getsource(R)
        for forbidden in ("ownerville_session", "generate_bundle",
                          "open_set_status", "patchright"):
            assert forbidden not in src, forbidden
