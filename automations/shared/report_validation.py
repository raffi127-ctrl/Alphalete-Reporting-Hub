"""Report validation engine — the always-on gate every report passes before it
goes live (Megan 2026-05-25).

Every upload runs through `validate_report()` at the single choke point
(`_save_uploaded_report` in dashboard.py). Megan's decisions:
  • HARD BLOCK — can't upload until all 'block' auto-checks pass AND every
    attestation is ticked.
  • Windows compatibility is an AUTO-check (statically catches the known
    killers), NOT a trust-me tick-box.
  • Applies to ALL reports (built-in + uploaded) — `audit_reports()` re-checks
    each report against every rule, so adding a rule instantly flags which
    existing reports now fail it.
  • On failure the caller must either tell the user EXACTLY which checks failed
    and why (`ValidationReport.why()`), or get approval to auto-fix.

Extending it: add ONE `Rule` to RULES. Auto-rules prove something from the
script text / metadata; attestation rules are things a computer can't verify
(a clean full run, a single-owner preview) and render as required checkboxes.
This module is pure logic — no I/O, no browser, no Streamlit — so it's trivial
to unit-test and safe to import anywhere.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class CheckResult:
    rule_id: str
    label: str
    kind: str          # "auto" | "attest"
    severity: str      # "block" | "warn"
    passed: bool
    detail: str = ""   # plain-English reason, especially on failure


@dataclass
class Rule:
    id: str
    label: str
    kind: str                  # "auto" | "attest"
    severity: str = "block"    # "block" (must pass) | "warn" (advisory)
    # auto rules only: (script_text, metadata) -> (passed, detail)
    check: Optional[Callable[[str, dict], Tuple[bool, str]]] = None
    help: str = ""             # shown to the uploader (especially attestations)


# --------------------------------------------------------------- auto-checks

def _chk_syntax(script: str, meta: dict) -> Tuple[bool, str]:
    try:
        ast.parse(script)
        return True, ""
    except SyntaxError as e:
        return False, f"Python syntax error on line {e.lineno}: {e.msg}"


def _chk_size(script: str, meta: dict) -> Tuple[bool, str]:
    n = len(script)
    if n > 49000:
        return False, (f"Script is {n:,} characters; the shared library caps a "
                       "cell at ~49,000. Split it or trim it.")
    return True, ""


# Windows-compat: the known cross-platform killers, caught statically. Can't
# PROVE a Windows run without Windows, but these are the things that actually
# break (Megan 2026-05-25: "you should be able to see if it runs on Windows").
_MAC_PATH_RE = re.compile(r"\.venv/bin/python|['\"]/(?:Users|Applications)/")
_MAC_STRFTIME_RE = re.compile(r"%-[IdmHejlpSMy]")   # %-I %-d ... glibc/BSD only
_POSIX_ONLY_IMPORTS = ("fcntl", "termios", "posix", "pwd", "grp", "resource")


def _chk_windows(script: str, meta: dict) -> Tuple[bool, str]:
    problems: List[str] = []
    m = _MAC_PATH_RE.search(script)
    if m:
        problems.append(f"hardcoded macOS path ({m.group(0)!r}) — use sys.executable / pathlib")
    if _MAC_STRFTIME_RE.search(script):
        problems.append("Mac/Linux-only date format (e.g. %-I, %-d) — fails on Windows; "
                        "use %I/%d and strip the leading zero in Python")
    for mod in _POSIX_ONLY_IMPORTS:
        if re.search(rf"^\s*(?:import|from)\s+{mod}\b", script, re.M):
            problems.append(f"POSIX-only import {mod!r} (not available on Windows)")
    if problems:
        return False, "Won't run on Windows — " + "; ".join(problems[:5])
    return True, ""


def _chk_metadata(script: str, meta: dict) -> Tuple[bool, str]:
    missing: List[str] = []
    if not str(meta.get("name") or "").strip():
        missing.append("name")
    if not str(meta.get("sheet_url") or meta.get("sheet_link") or "").strip():
        missing.append("Sheet URL")
    if not meta.get("schedule"):
        missing.append("schedule")
    if "needs_login" not in meta:
        missing.append("'needs a browser login?' flag")
    _assignees = meta.get("assignees")
    _has_assignee = (bool(_assignees) if isinstance(_assignees, (list, tuple))
                     else bool(str(_assignees or "").strip())) \
        or bool(str(meta.get("assignee") or "").strip())
    if not _has_assignee:
        missing.append("assignee")
    if missing:
        return False, "Missing required info: " + ", ".join(missing)
    return True, ""


def _chk_estimated_minutes(script: str, meta: dict) -> Tuple[bool, str]:
    if re.search(r"ESTIMATED_MINUTES\s*=\s*\d+", script):
        return True, ""
    return False, "No `ESTIMATED_MINUTES = N` declared — the run-time estimate falls back to 10."


def _chk_breakdown(script: str, meta: dict) -> Tuple[bool, str]:
    if re.search(r"REPORT_BREAKDOWN\s*=", script) or str(meta.get("breakdown") or "").strip():
        return True, ""
    return False, "No `REPORT_BREAKDOWN` / breakdown text (the 'how this report works' cheat-sheet)."


# The single source of truth. Append a Rule to extend the checklist.
RULES: List[Rule] = [
    Rule("syntax",   "Valid Python",                                  "auto", "block", _chk_syntax),
    Rule("size",     "Fits the shared library (<49k chars)",          "auto", "block", _chk_size),
    Rule("windows",  "Runs on Windows (no Mac-only paths/dates/imports)", "auto", "block", _chk_windows),
    Rule("metadata", "Has name, Sheet URL, schedule, assignee, login flag", "auto", "block", _chk_metadata),
    Rule("est_min",  "Declares a run-time estimate",                  "auto", "warn",  _chk_estimated_minutes),
    Rule("breakdown","Has a 'how it works' breakdown",                "auto", "warn",  _chk_breakdown),
    # Attestations — a computer can't prove these; the uploader ticks them.
    Rule("clean_run", "I ran it end-to-end with ZERO errors", "attest", "block",
         help="A full run completed and filled correctly — no errors, no unexplained blank metrics."),
    Rule("preview", "I previewed it on ONE owner/tab first", "attest", "block",
         help="Scoped to a single owner (e.g. Marcellus) and checked the numbers before rolling out to all tabs."),
    Rule("names_checked", "Owner names checked against the alias list", "attest", "block",
         help="Every owner/ICD name the report matches on is in the shared ICD alias sheet — catches silent blank tabs."),
    Rule("access_gaps", "Access gaps reviewed + requests sent", "attest", "block",
         help="If any owner/ICD can't be scraped yet (no access), the gap list "
              "was reviewed and the access requests were actually sent. Tick it "
              "if the report has no access gaps."),
]


@dataclass
class ValidationReport:
    results: List[CheckResult]

    @property
    def auto_failures(self) -> List[CheckResult]:
        return [r for r in self.results
                if r.kind == "auto" and r.severity == "block" and not r.passed]

    @property
    def warnings(self) -> List[CheckResult]:
        return [r for r in self.results if r.severity == "warn" and not r.passed]

    @property
    def attestations(self) -> List[CheckResult]:
        return [r for r in self.results if r.kind == "attest"]

    @property
    def unticked_attestations(self) -> List[CheckResult]:
        return [r for r in self.attestations if not r.passed]

    @property
    def blocked(self) -> bool:
        """Hard block: any block-level auto-check failed, or any attestation
        isn't ticked."""
        return bool(self.auto_failures) or bool(self.unticked_attestations)

    def why(self) -> List[str]:
        """Plain-English list of everything standing between this report and
        going live — what the caller shows the user."""
        lines = [f"✗ {r.label}: {r.detail}" for r in self.auto_failures]
        lines += [f"☐ {r.label} — you must confirm this" for r in self.unticked_attestations]
        return lines


def validate_report(script_text: str, metadata: dict,
                    attestations: Optional[dict] = None) -> ValidationReport:
    """Run every rule against one report. `attestations` is {rule_id: bool} of
    the human checks the uploader ticked. Returns a ValidationReport whose
    `.blocked` says whether the upload should be stopped."""
    attestations = attestations or {}
    results: List[CheckResult] = []
    for rule in RULES:
        if rule.kind == "auto":
            try:
                passed, detail = rule.check(script_text or "", metadata or {})
            except Exception as e:   # a buggy check must never crash the gate
                passed, detail = False, f"validation check errored: {type(e).__name__}: {e}"
            results.append(CheckResult(rule.id, rule.label, rule.kind,
                                       rule.severity, passed, detail))
        else:  # attestation
            ticked = bool(attestations.get(rule.id))
            results.append(CheckResult(rule.id, rule.label, rule.kind, rule.severity,
                                       ticked, "" if ticked else rule.help))
    return ValidationReport(results)


def audit_reports(reports: List[Tuple[str, str, dict]]) -> dict:
    """Re-check many reports against the AUTO rules (attestations can't be
    re-derived after the fact). `reports` is a list of (name, script_text,
    metadata). Returns {name: ValidationReport}. Use this when a new rule is
    added to see which existing reports now fail it."""
    return {name: validate_report(script or "", meta or {}, attestations=None)
            for name, script, meta in reports}


if __name__ == "__main__":
    # Quick self-check of the engine against a couple of fixtures.
    good = "ESTIMATED_MINUTES = 5\nREPORT_BREAKDOWN = 'does a thing'\nimport sys\nprint(sys.executable)\n"
    bad = "import fcntl\np = '/Users/megan/x'\nt = d.strftime('%-I %p')\n"
    gmeta = {"name": "X", "sheet_url": "http://s", "assignees": ["Eve"],
             "schedule": {"frequency": "weekly"}, "needs_login": False}
    print("GOOD report:")
    rg = validate_report(good, gmeta, attestations={
        "clean_run": True, "preview": True, "names_checked": True,
        "access_gaps": True})
    print("  blocked:", rg.blocked, "| warnings:", [w.label for w in rg.warnings])
    print("BAD report (no attestations):")
    rb = validate_report(bad, {})
    print("  blocked:", rb.blocked)
    for line in rb.why():
        print("   ", line)
