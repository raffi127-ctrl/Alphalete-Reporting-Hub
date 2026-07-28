"""Guard the embedded-image contract of a Captainship draft.

Run this after ANY change to email_build.py, before a live batch:

    .venv\\Scripts\\python.exe automations/captainship_drafts/test_email_build.py

Why this test exists (2026-07-27). Eve: "all the captainship drafts look wrong,
the images swapped places and got mixed up, even in the mails already sent."
Everything we generated was in fact correct — but the drafts came back from
Gmail mangled: Luis' 7/26 draft had its 8 images bound in the order
1,2,7,5,8,4,3,6 with one Content-ID used TWICE, so one chart rendered twice and
another disappeared. Opening a draft in the Gmail web UI makes Gmail hoist the
inline images into its own attachment store and re-anchor every <img>; on our
old make_msgid() Content-IDs (all sharing a ~14-char timestamp+pid prefix and a
machine-name domain, differing only in a random tail, and on nameless parts)
that re-anchor collided. Sending the draft baked the scramble in.

So the invariants below are not style preferences — each one is load-bearing:
  * short, semantic, non-prefix-sharing Content-IDs   -> Gmail can't collide them
  * parts INLINE and UNNAMED                          -> they stay real inline
      images. Naming them was tried on 2026-07-27 and broke sending outright:
      Gmail read a named part as a file attachment and moved all 9 images out
      of multipart/related into a multipart/mixed, so the sent mail arrived as
      body text + broken images. The compose window looked fine, which is
      exactly why this is asserted and not eyeballed.
  * HTML <img> order == MIME part order               -> reading order is the
      order the sections were built in

Gmail reorders the MIME parts on its own once a draft is opened, and that is
fine — distinct Content-IDs mean each <img> still resolves. Don't "fix" the
order.
This test does NOT talk to Gmail; it checks the message we hand Gmail.
"""
import datetime as dt
import io
import re
import sys
import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from automations.captainship_drafts import config, email_build  # noqa: E402


def _png(tmp: Path, name: str) -> Path:
    from PIL import Image
    p = tmp / f"{name}.png"
    if not p.exists():
        buf = io.BytesIO()
        Image.new("RGB", (40, 12), "white").save(buf, format="PNG")
        p.write_bytes(buf.getvalue())
    return p


def _bundle(tmp: Path, captain) -> dict:
    """A maximal bundle: every section populated, so one captain exercises
    every image slot the builder knows about."""
    k = captain.key
    return {
        "product_summary": _png(tmp, f"{k}_ps"),
        "units": [(f"chart {i}", _png(tmp, f"{k}_u{i}")) for i in range(2)],
        "churn_ni": [(f"ni {i}", _png(tmp, f"{k}_ni{i}")) for i in range(4)],
        "churn_wireless": [(f"wl {i}", _png(tmp, f"{k}_wl{i}")) for i in range(4)],
        "cancel_tableau": _png(tmp, f"{k}_cancel"),
        "teamstats_tableau": _png(tmp, f"{k}_stats"),
        "fiber_activation": _png(tmp, f"{k}_fiber"),
    }


def check(captain, tmp: Path) -> list:
    msg = email_build.build(captain, _bundle(tmp, captain), dt.date(2026, 7, 27))
    parsed = BytesParser(policy=policy.default).parsebytes(bytes(msg))

    html, parts = None, []
    for part in parsed.walk():
        if part.get_content_type() == "text/html" and html is None:
            html = part.get_content()
        if part.get_content_type().startswith("image/"):
            parts.append((
                (part.get("Content-ID") or "").strip()[1:-1],
                str(part.get("Content-Disposition") or ""),
                part.get_filename(),
            ))

    refs = re.findall(r'src="cid:([^"]+)"', html or "")
    ids = [c for c, _, _ in parts]
    names = [n for _, _, n in parts]
    bad = []

    if not parts:
        bad.append("no image parts at all")
    if len(set(ids)) != len(ids):
        bad.append("duplicate Content-IDs (one image would render twice)")
    if any(names):
        bad.append(f"parts are NAMED ({next(n for n in names if n)!r}) — a "
                   f"filename makes Gmail treat them as attachments and the "
                   f"sent mail arrives with broken images")
    if refs != ids[:len(refs)]:
        bad.append(f"HTML order != MIME order ({refs[:3]} vs {ids[:3]})")
    if any(r not in ids for r in refs):
        bad.append("an <img> points at a cid with no matching part")
    for cid, disp, _ in parts:
        if not disp.startswith("inline"):
            bad.append(f"{cid} is '{disp.split(';')[0]}', not inline")
            break
    # The exact shape that let Gmail confuse two images with each other.
    for a in ids:
        for b in ids:
            if a != b and a[:6] == b[:6]:
                bad.append(f"cids share a 6-char prefix ({a[:6]}…)")
                break
        else:
            continue
        break
    return bad


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="captainship_email_test_"))
    failures = 0
    for captain in config.CAPTAINS:
        bad = check(captain, tmp)
        failures += bool(bad)
        if bad:
            print(f"FAIL {captain.key:<8} ({captain.flavor})")
            for b in bad:
                print(f"       - {b}")
        else:
            print(f"ok   {captain.key:<8} ({captain.flavor})")
    print()
    if failures:
        print(f"✗ {failures}/{len(config.CAPTAINS)} captains build a bad message "
              f"— do NOT run a live batch until this is green.")
        return 1
    print(f"✓ all {len(config.CAPTAINS)} captains: images inline, unnamed, "
          f"uniquely addressed, in document order.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
