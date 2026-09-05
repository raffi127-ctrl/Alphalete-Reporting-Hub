"""A little box that asks the person at the keyboard for one Social.

WHY THIS EXISTS. Apex will not save an employee profile without a Social
Security number, and this report does not read Socials out of Blue Ink and does
not put them anywhere. Megan's answer (2026-09-05) is the right one: pop up a
window, let the operator type it, and let the rest of the record fill itself.

WHAT THIS GUARANTEES.
  * The number is TYPED BY A PERSON, into a masked box, on their own machine.
    It is never read from a document, never fetched, never inferred.
  * It goes straight from here into the Apex field and nowhere else. It is not
    logged, not printed, not written to output/, not put in the run summary,
    and not kept after the record is saved.
  * `str(...)` of the result is a row of dots, so a stray print or an exception
    that happens to include it cannot spill the number into a terminal, a log
    file or a Slack message.

The window is plain tkinter -- in the standard library, on macOS and Windows
both, no new dependency on a machine that already has enough moving parts.
"""
from __future__ import annotations

import re
from typing import Optional

TITLE = "Alphalete · Apex new start"
SSN_RE = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")


class Secret:
    """A string that refuses to show itself.

    Everything downstream treats values as printable -- the run logs what it
    fills, exceptions quote what they choked on. One `print` of a plain string
    would be a Social in a terminal someone screenshots. So the value is only
    reachable through `.reveal()`, which exists at exactly one call site: the
    moment it is typed into the Apex box.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "•" * 9

    __repr__ = __str__

    def __len__(self) -> int:
        return len(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)


def normalise(raw: str) -> Optional[str]:
    """'123-45-6789' or '123456789' -> '123456789'. None if it isn't one.

    Rejecting a typo here matters more than it looks: a Social that is nine
    digits of the wrong number is indistinguishable from a right one once it is
    saved, and it lands on a real person's tax record.
    """
    text = (raw or "").strip()
    if not SSN_RE.match(text):
        return None
    return text.replace("-", "")


def ask(person: str, *, subtitle: str = "") -> Optional[Secret]:
    """Show the box. Returns the Social, or None if the operator skips.

    Skipping is a first-class answer -- somebody whose number isn't to hand gets
    left for later rather than holding up the other twelve.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:                                    # headless machine
        return None

    result = {"value": None}
    root = tk.Tk()
    root.title(TITLE)
    root.attributes("-topmost", True)                      # over the browser
    root.lift()
    frame = ttk.Frame(root, padding=18)
    frame.grid()

    ttk.Label(frame, text=f"Social Security number for {person}",
              font=("Helvetica", 14)).grid(column=0, row=0, columnspan=2,
                                           sticky="w")
    ttk.Label(frame, text=subtitle or "Everything else on this record is "
                                      "already filled in.",
              foreground="#555").grid(column=0, row=1, columnspan=2,
                                      sticky="w", pady=(2, 10))
    entry = ttk.Entry(frame, show="•", width=24, font=("Helvetica", 16))
    entry.grid(column=0, row=2, columnspan=2, sticky="we")
    entry.focus_set()
    note = ttk.Label(frame, text="9 digits. Not saved anywhere by this report.",
                     foreground="#777")
    note.grid(column=0, row=3, columnspan=2, sticky="w", pady=(6, 12))

    def submit(_event=None):
        clean = normalise(entry.get())
        if not clean:
            note.config(text="That isn't nine digits — check it and try again.",
                        foreground="#b00")
            entry.delete(0, "end")
            return
        result["value"] = Secret(clean)
        root.destroy()

    def skip():
        root.destroy()

    ttk.Button(frame, text="Skip this person",
               command=skip).grid(column=0, row=4, sticky="w")
    ttk.Button(frame, text="Enter",
               command=submit).grid(column=1, row=4, sticky="e")
    entry.bind("<Return>", submit)
    root.bind("<Escape>", lambda _e: skip())
    root.update_idletasks()
    root.mainloop()
    return result["value"]
