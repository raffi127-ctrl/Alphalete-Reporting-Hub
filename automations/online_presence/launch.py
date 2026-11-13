"""Launch an office's logo, website + company email (Megan
2026-11-12: "start 1 and 2" -- the sign-up launch questions + one launch step).

    python -m automations.online_presence.launch kash                       # what's ready / missing
    python -m automations.online_presence.launch kash --make-logos --post    # 6 logo options, sent to their channel
    python -m automations.online_presence.launch kash --pick-logo 3           # keep #3; the site builds from it
    python -m automations.online_presence.launch kash --ask-photos           # post the 10-15 photo ask in their channel
    python -m automations.online_presence.launch kash --collect-photos       # save the photos they sent
    python -m automations.online_presence.launch kash --domain kashsales.com --go     # build + put it live
    python -m automations.online_presence.launch kash --domain kashsales.com --google-code "google-site-verification=..."

ALPHALETE OWNS EVERY DOMAIN (Megan 2026-11-12): the domain is bought in the
Alphalete Cloudflare account first (a person clicks buy -- Lucy never buys).
Then this:
  1. builds the site from the office's sign-up + site.json + photos
  2. puts it live on Cloudflare Pages (project "<key>-site")
  3. attaches the domain (and www) and points them at the site -- https is automatic
  4. with --google-code: adds Google Workspace's verification + mail records,
     so careers@<domain> works once the inbox is made in Lucy's Workspace
  5. saves the domain as the office's website, so Lucy's weekly audit checks it

Every step is safe to re-run.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, List

PHOTO_ASK = ("📸 *Launch photos*: reply in this thread with *10–15 photos* for your new website "
             "and social pages. Team shots, the office, wins, team nights. Clear and well-lit is "
             "best; no screenshots. Lucy uses every one.")
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".heic", ".webp")


def _office(key: str):
    from automations.online_presence import offices
    rows = {"alphalete": offices.alphalete(), **offices.load()}
    p = rows.get(key.lower())
    if not p:
        raise SystemExit(f"✗ no online-presence office {key!r} (run setup add first)")
    return p


def _state(p) -> Dict:
    try:
        return json.loads(p.path("launch.json").read_text())
    except Exception:
        return {}


def _save_state(p, st: Dict) -> None:
    f = p.path("launch.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(st, indent=1))


# ---- photos (from the office's own Slack channel) ---------------------------
def ask_photos(p) -> str:
    from automations.shared import slack_metrics_post as smp
    r = smp._client().chat_postMessage(channel=p.slack_channel, text=PHOTO_ASK)
    st = _state(p)
    st["photo_thread"] = r["ts"]
    _save_state(p, st)
    return r["ts"]


def collect_photos(p) -> List[str]:
    """Download every photo replied in the launch-photo thread into the
    office's site_photos/ folder and list them in site.json."""
    import requests
    from automations.shared import slack_metrics_post as smp
    ts = _state(p).get("photo_thread")
    if not ts:
        raise SystemExit("✗ no photo ask yet: run with --ask-photos first")
    cl = smp._client()
    folder = p.path("site_photos")
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for m in cl.conversations_replies(channel=p.slack_channel, ts=ts, limit=200)["messages"][1:]:
        for f in m.get("files") or []:
            name = f.get("name") or f["id"]
            if not name.lower().endswith(PHOTO_EXT):
                continue
            dest = folder / f"{f['id']}{Path(name).suffix.lower()}"
            if not dest.exists():
                r = requests.get(f["url_private_download"], timeout=60,
                                 headers={"Authorization": f"Bearer {cl.token}"})
                r.raise_for_status()
                if Path(name).suffix.lower() == ".heic":      # browsers can't show HEIC
                    from automations.brand_audit import photo_edit
                    dest = dest.with_suffix(".jpg")
                    dest.write_bytes(photo_edit.process_bytes(r.content))
                else:
                    dest.write_bytes(r.content)
            saved.append(str(dest))
    sj = p.path("site.json")
    try:
        x = json.loads(sj.read_text())
    except Exception:
        x = {}
    x["photos"] = saved
    sj.write_text(json.dumps(x, indent=1))
    return saved


# ---- logo first (Megan 2026-11-12: start with the name, make them a logo, build from it)
def make_logos(p, post: bool = False, shields: bool = True, ideas: str = "") -> str:
    from automations.online_presence import logo_maker as LM
    r = LM.make_options(p.business_name, p.path("logo_options"), shields=shields, ideas=ideas)
    st = _state(p)
    st["logo_shields"] = shields
    _save_state(p, st)
    if post:
        from automations.shared import slack_metrics_post as smp
        smp._client().files_upload_v2(
            channel=p.slack_channel, file=r["sheet"], filename="logo options.png",
            initial_comment="🎨 *Pick your logo*: reply in this thread with its number (1–6). "
                            "Your website and social pages are built from the one you pick.")
    return r["sheet"]


def pick_logo(p, n: int) -> Dict:
    """Keep option n: every format goes to the office's brand/ folder, and the
    website takes its colors, look and mark."""
    import shutil
    from automations.online_presence import logo_maker as LM
    src = p.path("logo_options") / f"option-{n}"
    if not src.exists():
        raise SystemExit(f"✗ no logo option {n} yet: run with --make-logos first")
    brand = p.path("brand")
    if brand.exists():
        shutil.rmtree(brand)
    shutil.copytree(src, brand)
    sj_ = p.path("logo_options") / "styles.json"
    st = dict((json.loads(sj_.read_text()) if sj_.exists()
               else LM.styles_for(_state(p).get("logo_shields", True)))[n - 1],
              icon=str(brand / "icon.png"), logo=str(brand / "logo.png"))
    sj = p.path("site.json")
    try:
        x = json.loads(sj.read_text())
    except Exception:
        x = {}
    x.update(LM.site_extras_for(st))
    sj.parent.mkdir(parents=True, exist_ok=True)
    sj.write_text(json.dumps(x, indent=1))
    state = _state(p)
    state["logo"] = n
    _save_state(p, state)
    return {"folder": str(brand), "files": sorted(f.name for f in brand.iterdir())}


# ---- domain + email ---------------------------------------------------------
def _zone(domain: str) -> str:
    from automations.online_presence import site_deploy as D
    k = D._keys()
    found = D._call("GET", f"{D.API}/zones?name={domain}", k["cloudflare_api_token"])["result"]
    if not found:
        raise SystemExit(f"✗ {domain} isn't in the Alphalete Cloudflare account yet: buy it there first "
                         "(Domain Registration -> Register Domains), then re-run")
    return found[0]["id"]


def _record(zone: str, rtype: str, name: str, content: str, **extra) -> str:
    """Add a DNS record unless the same one is already there."""
    from automations.online_presence import site_deploy as D
    tok = D._keys()["cloudflare_api_token"]
    have = D._call("GET", f"{D.API}/zones/{zone}/dns_records?type={rtype}&name={name}", tok)["result"]
    if any(r.get("content", "").strip('"') == content.strip('"') for r in have):
        return "already there"
    D._call("POST", f"{D.API}/zones/{zone}/dns_records", tok,
            json={"type": rtype, "name": name, "content": content, "ttl": 1, **extra})
    return "added"


def put_live(p, domain: str, project: str) -> List[str]:
    from automations.online_presence import site_deploy as D
    zone = _zone(domain)
    out = []
    for host in (domain, f"www.{domain}"):
        try:
            D.attach_domain(project, host)
            out.append(f"{host}: attached")
        except RuntimeError as e:
            out.append(f"{host}: {'already attached' if 'already' in str(e).lower() else str(e)[:80]}")
        out.append(f"{host} -> site: " + _record(zone, "CNAME", host, f"{project}.pages.dev", proxied=True))
    return out


def google_mail(domain: str, code: str) -> List[str]:
    """Google Workspace's records for this domain (verification + Gmail)."""
    zone = _zone(domain)
    code = code.strip().strip('"')
    if not code.startswith("google-site-verification="):
        code = f"google-site-verification={code}"
    return [f"Google verification: {_record(zone, 'TXT', domain, code)}",
            f"Gmail (MX smtp.google.com): {_record(zone, 'MX', domain, 'smtp.google.com', priority=1)}",
            f"Sender check (SPF): {_record(zone, 'TXT', domain, 'v=spf1 include:_spf.google.com ~all')}"]


# ---- the whole launch -------------------------------------------------------
def status(p) -> List[str]:
    from automations.online_presence import site_builder as SB
    st, x = _state(p), SB.extras(p)
    rows = [("Logo picked", bool(st.get("logo"))),
            ("Sign-up saved (address, phone, Google link)", bool(p.address and p.phone and p.google_link)),
            ("Owner's story answers", bool(x.get("answers"))),
            (f"Photos ({len(x.get('photos') or [])} of 10–15)", len(x.get("photos") or []) >= 10),
            ("Domain bought + site live", bool(st.get("live_domain"))),
            ("Company email records (Google)", bool(st.get("google_mail")))]
    return [f"{'✅' if ok else '⬜'} {label}" for label, ok in rows]


def go(p, domain: str) -> Dict:
    from automations.online_presence import offices, site_builder as SB, site_deploy as D
    domain = domain.lower().strip().removeprefix("https://").removeprefix("http://").strip("/")
    _zone(domain)                                   # bought? (fails fast, before building)
    p = replace(p, website=f"https://{domain}")
    out = SB.build(p, extra={**SB.extras(p), "noindex": False})
    project = f"{p.key}-site".replace("_", "-").lower()
    url = D.deploy(out, project)
    steps = [f"site uploaded: {url}"] + put_live(p, domain, project)
    if p.key != "alphalete":
        offices.save(p)                             # the audit now checks the new site
    st = _state(p)
    st.update({"live_domain": domain, "project": project})
    _save_state(p, st)
    return {"url": f"https://{domain}", "steps": steps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="online_presence.launch")
    ap.add_argument("office")
    ap.add_argument("--make-logos", action="store_true", help="make 6 logo options (+ --post to send them)")
    ap.add_argument("--post", action="store_true", help="with --make-logos: post the options in their channel")
    ap.add_argument("--no-shields", action="store_true", help="office outside the Alphalete org (no shield logos)")
    ap.add_argument("--pick-logo", type=int, default=0, help="keep logo option N (1-6)")
    ap.add_argument("--ask-photos", action="store_true")
    ap.add_argument("--collect-photos", action="store_true")
    ap.add_argument("--domain", default="")
    ap.add_argument("--go", action="store_true", help="build + put the site live on --domain")
    ap.add_argument("--google-code", default="", help="Google Workspace's verification code for --domain")
    a = ap.parse_args(argv)
    p = _office(a.office)
    if a.make_logos:
        print(f"✓ logo options: {make_logos(p, post=a.post, shields=not a.no_shields)}")
    if a.pick_logo:
        r = pick_logo(p, a.pick_logo)
        print(f"✓ logo {a.pick_logo} kept in {r['folder']}: {', '.join(r['files'])}")
    if a.ask_photos:
        print(f"✓ photo ask posted in {p.slack_channel} (thread {ask_photos(p)})")
    if a.collect_photos:
        print(f"✓ {len(collect_photos(p))} photo(s) saved")
    if a.go:
        if not a.domain:
            print("✗ --go needs --domain")
            return 1
        r = go(p, a.domain)
        for s in r["steps"]:
            print(f"  · {s}")
        print(f"✓ live: {r['url']} (https turns on within a few minutes)")
    if a.google_code:
        if not a.domain:
            print("✗ --google-code needs --domain")
            return 1
        for s in google_mail(a.domain, a.google_code):
            print(f"  · {s}")
        st = _state(p)
        st["google_mail"] = a.domain
        _save_state(p, st)
    print(f"\n{p.business_name} launch:")
    for line in status(p):
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
