"""Put an office's website live on Cloudflare Pages (Megan 2026-11-11: "A, we
host it"; Cloudflare key installed on Lucy 3 2026-11-12).

    python -m automations.online_presence.site_deploy output/sites/kash --project kash-site
    python -m automations.online_presence.site_deploy output/sites/kash --project kash-site --domain kashmarketing.com

Pages "direct upload" over the plain API, so no Node / wrangler is needed on
the Lucys:
  1. make the Pages project if it's new
  2. ask which files Cloudflare doesn't have yet, upload only those
  3. publish a deployment from the file list
  4. (optional) attach the office's own domain

Uses keys.json -> cloudflare_api_token + cloudflare_account_id. The token is
never printed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import sys
from pathlib import Path
from typing import Dict

API = "https://api.cloudflare.com/client/v4"


def _keys() -> Dict[str, str]:
    p = Path.home() / ".config" / "brand-audit" / "keys.json"
    d = json.loads(p.read_text())
    if not d.get("cloudflare_api_token") or not d.get("cloudflare_account_id"):
        raise RuntimeError("no Cloudflare key on this machine (set_cloudflare_token)")
    return d


def _call(method: str, url: str, token: str, **kw) -> Dict:
    import time
    import requests
    for attempt in range(3):          # Cloudflare's 500 "unknown error" clears on a retry
        r = requests.request(method, url, headers={"Authorization": f"Bearer {token}"}, timeout=60, **kw)
        if r.status_code < 500:
            break
        time.sleep(3 * (attempt + 1))
    try:
        d = r.json()
    except ValueError:
        raise RuntimeError(f"Cloudflare {r.status_code}: {r.text[:200]}")
    if not d.get("success", True) or r.status_code >= 400:
        msg = "; ".join(e.get("message", "") for e in d.get("errors") or []) or r.text[:200]
        raise RuntimeError(f"Cloudflare {r.status_code}: {msg}")
    return d


def _hash(data: bytes, ext: str) -> str:
    # Pages asset keys are 32 hex chars per file (content + extension).
    return hashlib.sha256(base64.b64encode(data) + ext.encode()).hexdigest()[:32]


def ensure_project(name: str, k: Dict) -> Dict:
    acct, tok = k["cloudflare_account_id"], k["cloudflare_api_token"]
    try:
        return _call("GET", f"{API}/accounts/{acct}/pages/projects/{name}", tok)["result"]
    except RuntimeError as e:
        if "404" not in str(e) and "not found" not in str(e).lower():
            raise
    return _call("POST", f"{API}/accounts/{acct}/pages/projects", tok,
                 json={"name": name, "production_branch": "main"})["result"]


def deploy(folder: Path, project: str) -> str:
    """Upload `folder` as the live site of Pages project `project`; returns its URL."""
    k = _keys()
    acct, tok = k["cloudflare_account_id"], k["cloudflare_api_token"]
    proj = ensure_project(project, k)
    files = {}
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.name != "CNAME":
            data = f.read_bytes()
            files["/" + f.relative_to(folder).as_posix()] = (data, _hash(data, f.suffix.lstrip(".")),
                                                             mimetypes.guess_type(f.name)[0] or "application/octet-stream")
    jwt = _call("GET", f"{API}/accounts/{acct}/pages/projects/{project}/upload-token", tok)["result"]["jwt"]
    hashes = sorted({h for _, h, _ in files.values()})
    missing = set(_call("POST", f"{API}/pages/assets/check-missing", jwt, json={"hashes": hashes})["result"])
    batch = [{"key": h, "value": base64.b64encode(d).decode(), "metadata": {"contentType": ct}, "base64": True}
             for d, h, ct in {v[1]: v for v in files.values()}.values() if h in missing]
    for i in range(0, len(batch), 50):
        _call("POST", f"{API}/pages/assets/upload", jwt, json=batch[i:i + 50])
    _call("POST", f"{API}/pages/assets/upsert-hashes", jwt, json={"hashes": hashes})
    manifest = {path: h for path, (_, h, _) in files.items()}
    dep = _call("POST", f"{API}/accounts/{acct}/pages/projects/{project}/deployments", tok,
                files={"manifest": (None, json.dumps(manifest)), "branch": (None, "main")})["result"]
    return f"https://{proj.get('subdomain') or project + '.pages.dev'}" if dep else ""


def attach_domain(project: str, domain: str) -> Dict:
    k = _keys()
    return _call("POST", f"{API}/accounts/{k['cloudflare_account_id']}/pages/projects/{project}/domains",
                 k["cloudflare_api_token"], json={"name": domain})["result"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="online_presence.site_deploy")
    ap.add_argument("folder")
    ap.add_argument("--project", required=True, help="Pages project name (lowercase, dashes)")
    ap.add_argument("--domain", default="", help="attach the office's own domain")
    a = ap.parse_args(argv)
    url = deploy(Path(a.folder), a.project)
    print(f"✓ live: {url}")
    if a.domain:
        r = attach_domain(a.project, a.domain)
        print(f"✓ domain {a.domain}: {r.get('status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
