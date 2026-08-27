"""Build the outgoing email: HTML with the link on the word, plain text with
the URL spelled out, as one multipart/alternative message.

ONE template in config.BODY renders BOTH parts, so the two can never drift --
the classic HTML-email bug is a link fixed in one part and stale in the other.

The plain-text part keeps the bare URL deliberately. It is what a text-only
client shows and what a cautious reader checks, and to fifty people who have
never had an email from reception before, a visible destination reads as more
trustworthy than a naked hyperlink.

BCC-only, no To: header -- exactly how reception sends it by hand, and the
reason the whole cohort can share one message. Every recipient sees only their
own address, so nobody gets a list of the other new starts' emails.

That BCC shape is also why this email can never carry a Blueink link: a Blueink
signing URL is bound to ONE signer's packet, so a link that worked for
everybody would let anyone sign as anyone. The Slack and Skool links are the
same for all recipients; that is what makes one send legitimate.
"""
from __future__ import annotations

import html as _html
import re
from email.message import EmailMessage
from email.utils import formataddr
from typing import List

from automations.slack_skool_email import config

# [[Slack->slack]] -- the word the reader sees, and which link it points at.
_LINK_RE = re.compile(r"\[\[([^\]|>]+)->(slack|skool)\]\]")


class CopyError(RuntimeError):
    pass


def _links(slack_link: str, skool_link: str) -> dict:
    slack = slack_link or config.slack_invite_link()
    skool = skool_link or config.skool_link()
    if not slack or not skool:
        raise CopyError(
            "one of the links is empty, so the email would ship a dead link "
            "where a live one should be. See config.link_problems().")
    return {"slack": slack, "skool": skool}


def _check_markers(body: str) -> None:
    """Both links must still be referenced somewhere in the copy."""
    used = {m.group(2) for m in _LINK_RE.finditer(body)}
    missing = {"slack", "skool"} - used
    if missing:
        raise CopyError(
            "config.BODY no longer links to: {}. The link would be dropped "
            "silently and the email would still look sent. Put the "
            "[[Word->{}]] marker back."
            .format(", ".join(sorted(missing)), sorted(missing)[0]))


def render_text(*, slack_link: str = "", skool_link: str = "") -> str:
    """The plain-text part. `[[Slack->slack]]` -> `Slack <https://...>`."""
    body = config.BODY
    _check_markers(body)
    urls = _links(slack_link, skool_link)
    out = _LINK_RE.sub(
        lambda m: "{} <{}>".format(m.group(1), urls[m.group(2)]), body)
    if "[[" in out:
        raise CopyError("unrendered link marker left in the body: {!r}"
                        .format(out[out.index("[["):][:40]))
    return out


def render_html(*, slack_link: str = "", skool_link: str = "") -> str:
    """The HTML part. `[[Slack->slack]]` -> `<a href="...">Slack</a>`.

    Deliberately bare: no images, no CSS, no tracking. This email's only real
    failure mode is not being seen, and a 52-recipient BCC from a personal
    Gmail is already the shape spam filters watch -- decoration would push it.
    """
    body = config.BODY
    _check_markers(body)
    urls = _links(slack_link, skool_link)

    # Escape FIRST, then substitute, so a stray < or & in the copy can't break
    # the markup and a URL can't inject any.
    escaped = _html.escape(body)
    marker = re.compile(r"\[\[([^\]|&]+?)-&gt;(slack|skool)\]\]")

    def _anchor(m):
        return '<a href="{}">{}</a>'.format(
            _html.escape(urls[m.group(2)], quote=True), m.group(1))

    linked = marker.sub(_anchor, escaped)
    if "[[" in linked:
        raise CopyError("unrendered link marker left in the HTML body")

    paragraphs = [p.strip() for p in linked.split("\n\n") if p.strip()]
    return (
        "<html><body style=\"font-family:Arial,Helvetica,sans-serif;"
        "font-size:14px;line-height:1.5;color:#111\">\n"
        + "\n".join("<p>{}</p>".format(p.replace("\n", "<br>"))
                    for p in paragraphs)
        + "\n</body></html>")


# Kept as the old name so callers and tests that only want the readable body
# don't have to care which part they're looking at.
render_body = render_text


def build(recipients: List[str], *, slack_link: str = "",
          skool_link: str = "") -> EmailMessage:
    """One multipart/alternative message, every recipient in BCC."""
    if not recipients:
        raise CopyError("no recipients -- refusing to build an empty send")

    msg = EmailMessage()
    msg["From"] = formataddr((config.FROM_NAME, config.FROM_ACCOUNT))
    msg["Subject"] = config.SUBJECT
    # No To: header on purpose -- see the module docstring.
    msg["Bcc"] = ", ".join(recipients)
    msg.set_content(render_text(slack_link=slack_link, skool_link=skool_link))
    msg.add_alternative(
        render_html(slack_link=slack_link, skool_link=skool_link),
        subtype="html")
    return msg
