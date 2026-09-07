"""restart_holder — the DISABLED LaunchAgent it used to be unable to fix.

    python -m automations.day_orchestrator.test_restart_holder_disabled

A disabled session-holder and a dead one produce the SAME symptom in the
pre-batch ping ("the holder hasn't re-exported in N minutes"), but a bare
`launchctl kickstart` only fixes the second: launchd keeps the disable flag in
the domain's override database, so the service is not in the domain and
kickstart answers `Could not find service`. Nobody sits at a Lucy, so a fix that
needs three commands typed at its own screen is no fix at all.

No launchctl is ever run: subprocess.run is replaced with a tiny fake launchd
that plays each scenario back.
"""
from __future__ import annotations

from automations.day_orchestrator import mini_control as mc


class _FakeLaunchd:
    """Answers `launchctl` the way the real one does in a given scenario."""

    def __init__(self, *, disabled: bool, in_domain: bool):
        self.disabled = disabled
        # A disabled agent is typically also out of the domain, but the two are
        # independent — model them separately so the ladder is really exercised.
        self.in_domain = in_domain
        self.calls = []             # the launchctl subcommands, in order

    def __call__(self, argv, **kw):
        assert argv[0] == "launchctl", argv
        sub = argv[1]
        self.calls.append(sub)
        rc, out = 0, ""
        if sub == "print-disabled":
            out = ('disabled services = {\n\t"com.apple.something" => false\n'
                   + (f'\t"{mc.SESSION_HOLDER_LABEL}" => true\n' if self.disabled else "")
                   + "}")
        elif sub == "enable":
            self.disabled = False
        elif sub == "bootstrap":
            self.in_domain = True
        elif sub == "kickstart":
            if not self.in_domain:
                rc, out = 113, ("Could not find service "
                                f"“{mc.SESSION_HOLDER_LABEL}” in domain "
                                "for gui")
        return _Proc(rc, out)


class _Proc:
    def __init__(self, rc, out):
        self.returncode, self.stdout = rc, out


def _run(*, plist_installed: bool = True, **scenario):
    """Drive the action against a fake launchd. `os.getuid` and the plist lookup
    are stubbed too, so this runs on Windows as well as on the Lucys."""
    fake = _FakeLaunchd(**scenario)
    real_run = mc.subprocess.run
    real_uid = getattr(mc.os, "getuid", None)
    real_plist = mc._session_holder_plist
    mc.subprocess.run = fake
    mc.os.getuid = lambda: 501
    mc._session_holder_plist = lambda: _FakePlist(plist_installed)
    try:
        ok, msg = mc._action_restart_holder("")
    finally:
        mc.subprocess.run = real_run
        mc._session_holder_plist = real_plist
        if real_uid is None:
            del mc.os.getuid
        else:
            mc.os.getuid = real_uid
    return ok, msg, fake.calls


class _FakePlist:
    """Just enough of a Path for the bootstrap rung."""

    def __init__(self, installed: bool):
        self._installed = installed
        self.name = f"{mc.SESSION_HOLDER_LABEL}.plist"

    def exists(self) -> bool:
        return self._installed

    def __str__(self) -> str:
        return f"/Users/lucy/Library/LaunchAgents/{self.name}"


def _check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))
    return ok


def test_healthy_agent_is_just_kickstarted():
    """The common case must stay a plain restart — enable is idempotent noise,
    bootstrap must NOT run, and nothing may claim it was disabled."""
    ok_, msg, calls = _run(disabled=False, in_domain=True)
    ok = _check("succeeds", ok_, True)
    ok &= _check("no bootstrap", "bootstrap" in calls, False)
    ok &= _check("kickstart ran once", calls.count("kickstart"), 1)
    ok &= _check("does not cry 'disabled'", "DISABLED" in msg, False)
    return ok


def test_disabled_agent_is_enabled_then_kickstarted():
    """The case the old code could not fix: enable clears the override flag,
    bootstrap puts it back in the domain, and the second kickstart lands."""
    ok_, msg, calls = _run(disabled=True, in_domain=False)
    ok = _check("succeeds", ok_, True)
    ok &= _check("enable came before kickstart",
                 calls.index("enable") < calls.index("kickstart"), True)
    ok &= _check("bootstrapped back into the domain", "bootstrap" in calls, True)
    ok &= _check("says it was disabled", "DISABLED" in msg, True)
    return ok


def test_unloaded_but_not_disabled_still_recovers():
    """After a reboot with no login the agent can be absent from the domain
    without any override flag — the bootstrap rung has to fire on the kickstart
    error, not on the disabled reading."""
    ok_, msg, calls = _run(disabled=False, in_domain=False)
    ok = _check("succeeds", ok_, True)
    ok &= _check("bootstrapped", "bootstrap" in calls, True)
    ok &= _check("does not claim it was disabled", "DISABLED" in msg, False)
    return ok


def test_missing_plist_says_so_instead_of_a_bare_kickstart_exit():
    """If the agent was never installed here, say that — the old message was
    just `kickstart exit 113`, which reads like a transient launchd hiccup."""
    ok_, msg, _ = _run(disabled=False, in_domain=False, plist_installed=False)
    ok = _check("fails", ok_, False)
    ok &= _check("names the missing plist", "LaunchAgents" in msg, True)
    return ok


def test_reads_the_flag_before_clearing_it():
    """print-disabled MUST run first — enable erases the evidence, and 'it was
    disabled' is the half of the report a human acts on."""
    _, _, calls = _run(disabled=True, in_domain=True)
    return _check("print-disabled precedes enable",
                  calls.index("print-disabled") < calls.index("enable"), True)


def main() -> int:
    ok = True
    for fn in (test_healthy_agent_is_just_kickstarted,
               test_disabled_agent_is_enabled_then_kickstarted,
               test_unloaded_but_not_disabled_still_recovers,
               test_missing_plist_says_so_instead_of_a_bare_kickstart_exit,
               test_reads_the_flag_before_clearing_it):
        print(f"\n--- {fn.__name__} ---")
        ok &= fn()
    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
