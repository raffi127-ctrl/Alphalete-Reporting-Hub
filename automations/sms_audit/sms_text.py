# -*- coding: utf-8 -*-
"""How a text actually goes out on the wire: encoding and segment count.

Megan 2026-10-01 hit AppStream's own warning while editing a custom
message: "Message contains non-standard characters that may not render
correctly on all phones: right double curly quote." It is worth auditing
because it is not cosmetic.

A text is sent in the GSM-7 alphabet at 160 characters per segment (153
once it splits). ONE character outside that alphabet - a curly apostrophe
pasted from Word, an em dash, an ellipsis - forces the whole message into
UCS-2, where a segment is 70 characters (67 once it splits). So a single
quote mark can take a 128-character message from one segment to two, and
a 182-character one from two to three.

That matters here beyond cost: this office already loses 11% of its texts,
and the failure rate climbs with every extra text to the same person. More
segments is more of the same exposure.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import unicodedata

# The GSM 03.38 basic set.
GSM = set(
    "@£$¥èéùìòÇ\nØø\r"
    "ÅåΔ_ΦΓΛΩΠΨΣΘ"
    "ΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà")
# These are sendable but cost two characters each.
EXT = set("^{}\\[~]|€")

# What people actually paste, and what to put instead.
SWAPS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
    "•": "-", "´": "'", "ʼ": "'",
}


def measure(body):
    """{chars, units, segments, unicode, bad} for one message body."""
    s = " ".join((body or "").split())
    bad = sorted({c for c in s if c not in GSM and c not in EXT})
    if bad:
        # UCS-2: 70 in a single segment, 67 each once it splits.
        segs = 1 if len(s) <= 70 else (len(s) + 66) // 67
        units = len(s)
    else:
        units = sum(2 if c in EXT else 1 for c in s)
        segs = 1 if units <= 160 else (units + 152) // 153
    return {"chars": len(s), "units": units, "segments": segs,
            "unicode": bool(bad), "bad": bad}


def clean(body):
    """The same message with the usual offenders swapped for plain ASCII."""
    out = []
    for c in (body or ""):
        out.append(SWAPS.get(c, c))
    return "".join(out)


def describe(bad):
    return ", ".join("{} ({})".format(c, unicodedata.name(c, "?").lower())
                     for c in bad)


def findings(where, body, max_segments=2):
    """[(kind, text)] for one message — shared by the template audit and
    the AI escalation audit, so both say the same thing."""
    m = measure(body)
    out = []
    if m["unicode"]:
        fixed = measure(clean(body))
        saved = ""
        if fixed["segments"] < m["segments"]:
            saved = " Swapping them for plain ones takes it from {} " \
                    "segments to {}.".format(m["segments"], fixed["segments"])
        out.append((
            "NOT PLAIN TEXT",
            "{}: contains {} — which forces the whole text into Unicode, "
            "where a segment is 70 characters instead of 160.{}".format(
                where, describe(m["bad"]), saved)))
    elif m["segments"] > max_segments:
        out.append((
            "TOO LONG",
            "{}: {} characters, {} segments.".format(
                where, m["chars"], m["segments"])))
    return out
