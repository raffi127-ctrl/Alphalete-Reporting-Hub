"""Native dialog boxes, so nobody has to read a Terminal.

IT LIVES IN THE PACKAGE, not beside the installer, because the installer is
not the only thing that has to ask. SaraPlus rotates passwords often (Megan
2026-09-12), so the agent itself has to be able to ask for a new one months
after setup -- and it only has what was copied onto the machine.

A NON-TECHNICAL OWNER SHOULD NEVER BE TYPING A PASSWORD INTO A TERMINAL
(Megan 2026-09-11: "they need to see what they're doing and the terminal is
too high level"). Worse, a terminal hides the typing completely when it asks
for a password -- no dots, no cursor movement -- which reads as a frozen
computer to anyone who has not seen it before.

NO DEPENDENCIES, ON PURPOSE. macOS gets AppleScript through osascript and
Windows gets a WinForms box through PowerShell; both ship with the operating
system. tkinter would have been the obvious choice and is exactly the wrong
one: it is missing or broken on several stock macOS Pythons, and finding that
out on somebody else's laptop is not a debugging session anyone can have.

EVERY FUNCTION FALLS BACK TO THE TERMINAL if the dialog cannot be shown -- over
SSH, on a stripped-down box, or if osascript is unavailable. A prompt that
looks worse is survivable; a prompt that never appears is not.
"""
from __future__ import annotations

import platform
import subprocess

IS_MAC = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
TITLE = "Lucy Reports"


def _osascript(script: str) -> str:
    proc = subprocess.run(["osascript", "-e", script],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace").strip()


def _powershell(script: str) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace").strip()


def _esc_applescript(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _esc_powershell(s: str) -> str:
    return s.replace("'", "''")


class Cancelled(Exception):
    """They pressed Cancel. Not an error -- a decision."""


def _ask(prompt: str, hidden: bool) -> str:
    if IS_MAC:
        script = (
            'display dialog "%s" default answer "" with title "%s" '
            'buttons {"Cancel", "OK"} default button "OK"%s\n'
            'return text returned of result'
            % (_esc_applescript(prompt), TITLE,
               " with hidden answer" if hidden else " with icon note"))
        try:
            return _osascript(script)
        except RuntimeError as e:
            if "-128" in str(e):        # the documented "user cancelled" code
                raise Cancelled()
            raise
    if IS_WINDOWS:
        char = "'*'" if hidden else "$null"
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
            "$f=New-Object Windows.Forms.Form;"
            "$f.Text='%s';$f.Width=460;$f.Height=190;"
            "$f.StartPosition='CenterScreen';$f.TopMost=$true;"
            "$l=New-Object Windows.Forms.Label;$l.Text='%s';"
            "$l.SetBounds(12,15,430,40);$l.AutoSize=$false;"
            "$t=New-Object Windows.Forms.TextBox;$t.SetBounds(12,62,420,24);"
            "if(%s -ne $null){$t.PasswordChar=%s};"
            "$o=New-Object Windows.Forms.Button;$o.Text='OK';"
            "$o.SetBounds(250,105,85,28);$o.DialogResult='OK';"
            "$c=New-Object Windows.Forms.Button;$c.Text='Cancel';"
            "$c.SetBounds(347,105,85,28);$c.DialogResult='Cancel';"
            "$f.AcceptButton=$o;$f.CancelButton=$c;"
            "$f.Controls.AddRange(@($l,$t,$o,$c));"
            "if($f.ShowDialog() -eq 'OK'){Write-Output $t.Text}else{exit 2}"
            % (TITLE, _esc_powershell(prompt), char, char))
        try:
            return _powershell(script)
        except RuntimeError:
            raise Cancelled()
    raise RuntimeError("no dialog available")


def text(prompt: str) -> str:
    """Ask for something visible. Falls back to the terminal."""
    try:
        return _ask(prompt, hidden=False)
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001
        return input("      %s " % prompt).strip()


def password(prompt: str) -> str:
    """Ask for a password. The dialog shows dots; the terminal shows nothing,
    which is why the dialog is worth this much trouble."""
    try:
        return _ask(prompt, hidden=True)
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001
        import getpass
        return getpass.getpass("      %s " % prompt)


def choose(prompt: str, options):
    """Pick one of a fixed set. A LIST, never a typed answer.

    Anything with a fixed set of valid answers has to be a list: a free-text
    box invites "hourly-ish", "end of night", "same as before" -- all perfectly
    clear to a person and none of them something the code can act on. The
    picker also means nobody has to be told the options in advance.
    """
    options = list(options)
    if IS_MAC:
        items = ", ".join('"%s"' % _esc_applescript(o) for o in options)
        script = ('choose from list {%s} with prompt "%s" with title "%s" '
                  'default items {"%s"}'
                  % (items, _esc_applescript(prompt), TITLE,
                     _esc_applescript(options[0])))
        out = _osascript(script)
        if out == "false":                # they pressed Cancel
            raise Cancelled()
        return out
    if IS_WINDOWS:
        items = ",".join("'%s'" % _esc_powershell(o) for o in options)
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
            "$f=New-Object Windows.Forms.Form;$f.Text='%s';"
            "$f.Width=480;$f.Height=200;$f.StartPosition='CenterScreen';"
            "$f.TopMost=$true;"
            "$l=New-Object Windows.Forms.Label;$l.Text='%s';"
            "$l.SetBounds(12,15,445,40);"
            "$c=New-Object Windows.Forms.ComboBox;$c.SetBounds(12,62,440,24);"
            "$c.DropDownStyle='DropDownList';$c.Items.AddRange(@(%s));"
            "$c.SelectedIndex=0;"
            "$o=New-Object Windows.Forms.Button;$o.Text='OK';"
            "$o.SetBounds(270,110,85,28);$o.DialogResult='OK';"
            "$x=New-Object Windows.Forms.Button;$x.Text='Cancel';"
            "$x.SetBounds(367,110,85,28);$x.DialogResult='Cancel';"
            "$f.AcceptButton=$o;$f.CancelButton=$x;"
            "$f.Controls.AddRange(@($l,$c,$o,$x));"
            "if($f.ShowDialog() -eq 'OK'){Write-Output $c.SelectedItem}else{exit 2}"
            % (TITLE, _esc_powershell(prompt), items))
        try:
            return _powershell(script)
        except RuntimeError:
            raise Cancelled()

    # No dialogs available: a numbered list is the honest fallback.
    print("\n      %s" % prompt)
    for i, o in enumerate(options, 1):
        print("        %d) %s" % (i, o))
    while True:
        raw = input("      Enter 1-%d: " % len(options)).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]


def message(body: str, *, error: bool = False) -> None:
    """Tell them something in a box they cannot miss. Never raises."""
    try:
        if IS_MAC:
            _osascript('display dialog "%s" with title "%s" buttons {"OK"} '
                       'default button "OK" with icon %s'
                       % (_esc_applescript(body), TITLE,
                          "stop" if error else "note"))
            return
        if IS_WINDOWS:
            _powershell(
                "Add-Type -AssemblyName System.Windows.Forms;"
                "[Windows.Forms.MessageBox]::Show('%s','%s','OK','%s')"
                % (_esc_powershell(body), TITLE,
                   "Error" if error else "Information"))
            return
    except Exception:  # noqa: BLE001
        pass
    print("\n" + body + "\n")
