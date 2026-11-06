"""Runs INSIDE the 2nd-round audit bot's own venv, with cwd = the bot's
.runtime folder (Lucy 1: ~/2nd-rd-audits/.runtime). Prints one JSON blob on
stdout and changes nothing.

Why a separate process: who uploaded each recording is only known through the
bot's own Slack app (scorecards._enrich_with_slack_uploaders), and its token
lives in the bot's .env. Reusing the bot's code keeps these numbers identical
to the scorecard Raf already sees.

Keep this file stdlib + bot modules only - it is NOT run with the Hub's venv.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

try:
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env")
except Exception:  # noqa: BLE001
    pass

import scorecards  # noqa: E402
from rosters import load_owners, load_reps  # noqa: E402


def _score(rec):
    md = rec.get("report_md")
    if not md:
        return None
    p = Path(md)
    if not p.exists():
        alt = scorecards.REPORTS_DIR / p.name
        if not alt.exists():
            return None
        p = alt
    return scorecards._extract_overall_score(p)


def _slack_name(uid, cache):
    if uid in cache:
        return cache[uid]
    name = ""
    try:
        from slack_watcher import web
        prof = web.users_info(user=uid)["user"].get("profile", {})
        name = (prof.get("real_name") or prof.get("display_name") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    cache[uid] = name
    return name


def main():
    recs = scorecards._enrich_with_slack_uploaders(scorecards._load_all_completions())
    reps = load_reps()
    out_recs, names = [], {}
    for r in recs:
        if r.get("rejected"):
            continue
        audio = r.get("audio_filename", "") or ""
        if not audio.startswith("slack-"):
            continue
        uid = r.get("_uploader_user_id") or ""
        out_recs.append({"ts": r.get("ts", ""), "uid": uid, "score": _score(r)})
        if uid and uid not in names:
            info = reps.get(uid) or {}
            nm = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
            if len(nm.split()) < 2:
                nm = _slack_name(uid, {}) or nm
            names[uid] = nm
    print(json.dumps({
        "records": out_recs,
        "reps": reps,
        "names": names,
        "owners": load_owners(),
    }))


if __name__ == "__main__":
    main()
