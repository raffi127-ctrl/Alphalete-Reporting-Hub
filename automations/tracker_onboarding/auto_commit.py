"""Auto-commit confirmed enrollments (trackers, metrics AND dispositions) so
they survive the morning pull.

The gap this closes: a confirmed enrollment is applied into the RUNNER'S
WORKING TREE only (posts start next morning), but the morning orchestrator
self-update resets uncommitted registry drift when main has also moved those
files — which can silently drop a confirmed office from the runs (the jamis
lesson; nii + drew had to be hand-committed). Committing the registries to
origin/main is the durable state.

What it does (idempotent, safe to run any time):
  1. Tracker leg — reads the 'Tracker Onboarding' tab (WIRED rows only;
     pending requests are hard-skipped) and regenerates
     automations/tableau_screenshots/onboarded_trackers.json.
  1b. Dispositions leg — reads the 'Disposition Signup' tab (WIRED rows only)
     and regenerates automations/gap_alerts/onboarded_offices.json, so an
     office that signed itself up for the KNOCKS & DISPOSITIONS board keeps
     getting it after the next `lucy update`.
  2. Metrics leg — reads the 'Office Onboarding' tab and regenerates
     automations/office_metrics/onboarded_offices.json +
     automations/b2b_metrics/onboarded_offices.json via
     office_onboarding.apply --registry-only (schedule_config.json is HOT on
     the runners and is deliberately never auto-committed — schedule entries
     keep flowing through onboard_apply, status quo).
  3. Schedule self-heal — a registry office with NO entry at all in the
     committed schedule_config.json is INVISIBLE to the 4am flow and nothing
     alerts (the nii/drew failure: their mini-only working-tree entries were
     wiped by the 2026-08-20 master-sequence pull and both Metrics threads
     silently stopped). For each clean onboarding whose report_id is missing
     from the schedule, re-add the entry (office_onboarding.apply's own
     _schedule_entry) and commit it with the registries. ADD-ONLY: an entry
     that exists is never touched (hand-tuned fields stay), so on a normal
     day this leg is a no-op and the hot 335KB file is not rewritten. To
     deliberately disable an office, set its entry's on_scheduler to false —
     don't delete the entry (deletion reads as a wipe and gets healed back).
  4. If — and only if — those files changed, commits JUST them and
     pushes (pull --rebase --autostash first). Other sessions' work-in-
     progress in the tree is never staged.
  4b. DELETION GUARD — before staging, each changed file is compared to HEAD
     structurally. A regeneration that REMOVES a non-empty value refuses to
     commit and exits 1; adds and edits go through as normal. This exists
     because on 2026-09-04 this job pushed away Jamis's and Sabrina's B2B churn
     view URLs (`per_office_views: {}`) under the generic "regenerated from the
     tabs" message, and b2b_metrics dropped three sections the next morning
     looking like a bug rather than a deleted fix. Replayed against all eight
     historical auto-commits, that one is the ONLY one the guard stops.
     Override a genuine removal with `--allow-deletions`; the LaunchAgent
     passes no args, so it can never take that path by itself. The commit
     message now names what changed per file (+added ~edited -removed).

Runs on LUCY 1 (always-on) as the com.alphalete.tracker-auto-commit
LaunchAgent, daily 03:15 + 17:30 — the laptop isn't reliably awake (Megan,
2026-08-20). Needs Google creds (~/.config/recruiting-report/oauth-token.json,
same file the poller uses) + git push access (one-time mini_control
`git_push_setup`). Also runs fine by hand from the laptop:
  .venv/bin/python -m automations.tracker_onboarding.auto_commit
Exit 0 = committed or nothing to do; 1 = a leg was blocked/failed (message
says why; a blocked leg never stops the other from committing).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_CONFIG = "automations/day_orchestrator/schedule_config.json"
TARGETS = [
    "automations/tableau_screenshots/onboarded_trackers.json",
    "automations/office_metrics/onboarded_offices.json",
    "automations/b2b_metrics/onboarded_offices.json",
    # apply pins owner -> OwnerVille account number here (knocks/Time Gaps
    # office resolution) — same durability need as the registries.
    "automations/recruiting_report/icd_office_mappings.json",
    # the dispositions sign-up's registry — same story as the two above.
    "automations/gap_alerts/onboarded_offices.json",
    # only ever changed by the ADD-ONLY schedule self-heal (leg 3).
    SCHEDULE_CONFIG,
]


def _client():
    """gspread client from the runner's oauth token (same fallback the forms
    use). Raises with a clear message if creds are missing."""
    import gspread
    from google.oauth2.credentials import Credentials

    tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
    if not tok.exists():
        raise RuntimeError(f"no Google creds at {tok} — run on a machine "
                           "with the reporting oauth token")
    o = json.loads(tok.read_text())
    creds = Credentials(
        token=o.get("token"), refresh_token=o.get("refresh_token"),
        token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=o.get("client_id"), client_secret=o.get("client_secret"),
        scopes=list(o.get("scopes")
                    or ["https://www.googleapis.com/auth/spreadsheets"]))
    return gspread.authorize(creds)


def _git(*args: str) -> "subprocess.CompletedProcess":
    return subprocess.run(["git", *args], cwd=REPO_ROOT, text=True,
                          capture_output=True)


# ---------------------------------------------------------------------------
# THE DELETION GUARD (2026-09-05)
# ---------------------------------------------------------------------------
# WHY THIS EXISTS. These registries are GENERATED from the onboarding tabs and
# also COMMITTED, so anything hand-authored in them lives exactly until the next
# regeneration. On 2026-09-04 Jamis's three B2B churn view URLs were pointed at
# ALLTEAMWireless (c10f46e) because the shared team view returns nothing for his
# Owner & Office; Sabrina got the same three. At 17:30 an unrelated enrollment
# ran this job, `office_onboarding.apply` regenerated both offices with
# `per_office_views: {}` — the form has no column for those URLs — and this
# function's caller committed and pushed the erasure as
#
#     enrollments: auto-commit confirmed offices
#     - regenerated from the Tracker Onboarding + Office Onboarding tabs
#
# The next morning b2b_metrics dropped `jamis: churn_wireless / churn_int /
# churn_air` and the channel read it as the bug coming back, not as a fix being
# deleted. Two things made it silent, and both are fixed:
#
#   1. apply._merge_json now MERGES instead of overwriting, so a regenerated
#      empty value can no longer blank a value that is already there (3e23070).
#      That closes the specific hole.
#   2. This guard closes the CLASS. Any future generator bug that deletes a
#      real value stops here instead of being pushed to main at 17:30 — because
#      the message above is identical whether this job added an office or
#      removed six URLs, and the diff it prints goes to a log on Lucy 1 that
#      nobody reads at half past five.
#
# A deletion BLOCKS; an add or an edit does not. Deleting a value nobody asked
# to delete is the failure mode; changing one is ordinary enrollment traffic.
# `--allow-deletions` is the escape hatch for a real removal, and it is a FLAG
# rather than a config so the LaunchAgent (which passes no args) can never take
# that path on its own.
_IDENTITY_FIELDS = ("key", "report_id", "id")


def _is_empty(v) -> bool:
    """Empty = absent-ish. Deliberately NOT falsy: `0` and `False` are real
    values here (`on_scheduler: false` is the documented off switch), and
    calling them deletions would block every office anyone turns off."""
    return v is None or (isinstance(v, (str, dict, list, tuple)) and len(v) == 0)


def _keyed(seq):
    """A list of dicts -> {identity: item}, or None if it isn't that shape.

    The registries are LISTS of office records, so a plain positional compare
    would call every office after an insertion "changed" and could read a
    re-ordering as a mass deletion. Match on the record's own id instead."""
    if not isinstance(seq, list) or not seq:
        return None
    if not all(isinstance(x, dict) for x in seq):
        return None
    for field in _IDENTITY_FIELDS:
        vals = [x.get(field) for x in seq]
        if all(isinstance(v, str) and v for v in vals) and len(set(vals)) == len(vals):
            return {v: x for v, x in zip(vals, seq)}
    return None


def _walk(before, after, path, out) -> None:
    """Collect ('added'|'changed'|'deleted', path) into `out`.

    A container that collapses to EMPTY is reported as one deletion at the
    container, not one per key — `jamis.per_office_views` reads as the thing
    that happened, where three sibling lines about each URL bury it. A PARTIAL
    removal still names the individual key, because there the key is the news."""
    if not _is_empty(before) and _is_empty(after):
        out.append(("deleted", path or "(entire file)"))
        return
    if _is_empty(before) and not _is_empty(after):
        out.append(("added", path or "(entire file)"))
        return

    b_map, a_map = _keyed(before), _keyed(after)
    if b_map is not None and a_map is not None:
        before, after = b_map, a_map

    if isinstance(before, dict) and isinstance(after, dict):
        for k in before:
            sub = f"{path}.{k}" if path else str(k)
            if k not in after:
                if not _is_empty(before[k]):
                    out.append(("deleted", sub))
            else:
                _walk(before[k], after[k], sub, out)
        for k in after:
            if k not in before and not _is_empty(after[k]):
                out.append(("added", f"{path}.{k}" if path else str(k)))
        return

    if before != after:
        out.append(("changed", path or "(entire file)"))


def registry_changes(before_text: str, after_text: str) -> dict:
    """{'added': [...], 'changed': [...], 'deleted': [...], 'note': str} for one
    JSON registry, HEAD vs working tree.

    A file that is NEW (no HEAD version) is all-additions — nothing can have
    been deleted from a file that did not exist. Unparseable NEW content blocks
    on purpose: a registry we cannot read is not one we should push. Unparseable
    OLD content cannot be compared, so it degrades to "allow, and say so" — the
    old behaviour, never worse."""
    out = {"added": [], "changed": [], "deleted": [], "note": ""}
    try:
        after = json.loads(after_text)
    except ValueError as e:
        out["deleted"].append(f"(file no longer parses as JSON: {e})")
        return out
    if not (before_text or "").strip():
        out["note"] = "new file"
        return out
    try:
        before = json.loads(before_text)
    except ValueError:
        out["note"] = "previous version did not parse — not compared"
        return out
    acc = []
    _walk(before, after, "", acc)
    for kind, p in acc:
        out[kind].append(p)
    return out


def _summarize(path: str, d: dict, limit: int = 6) -> str:
    """One commit-message line naming what actually changed in this file."""
    bits = []
    for sign, kind in (("+", "added"), ("~", "changed"), ("-", "deleted")):
        items = d.get(kind) or []
        if not items:
            continue
        shown = ", ".join(items[:limit])
        if len(items) > limit:
            shown += f", +{len(items) - limit} more"
        bits.append(f"{sign}{shown}")
    detail = "; ".join(bits) or (d.get("note") or "no structural change")
    return f"- {Path(path).name}: {detail}"


def heal_schedule(apply_mod) -> list:
    """ADD-ONLY schedule reconcile: give every clean onboarded office whose
    report_id has NO entry in schedule_config.json the standard entry apply
    would have written, and return the added report_ids ([] = file untouched).
    Existing entries are never modified — on_scheduler:false is respected as
    the deliberate off switch. Fractional orders after the office-metrics
    block (36.x) keep Megan's integer 1-60 master sequence unrenumbered."""
    path = REPO_ROOT / SCHEDULE_CONFIG
    raw = json.loads(path.read_text())
    reports = raw.setdefault("reports", {})
    healed = []
    for i, p in enumerate(apply_mod.plan()):
        if p["problems"]:
            continue
        rec = p["rec"]
        rid = rec.report_id()
        if rid in reports:
            continue                      # exists (even disabled) -> hands off
        entry = apply_mod._schedule_entry(rec, 36.5 + i * 0.01)
        entry["_note"] += (" RE-ADDED by tracker_onboarding.auto_commit "
                           "schedule self-heal: the entry was missing from "
                           "the committed schedule (never committed, or "
                           "wiped by a pull).")
        reports[rid] = entry
        healed.append(rid)
    if healed:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, indent=2))
        tmp.replace(path)
    return healed


def main(argv: list = None) -> int:
    """_run + a Hub Activity row on every exit path.

    Standing rule: LaunchAgent reports publish to the Hub. This job had never
    logged a run, so its card sat on "no run logged" every single day — on
    2026-08-21 the 03:15 run had provably happened (its commit was in git) while
    the Hub said it hadn't run at all. The id must match the library card
    (automations/uploaded/_shared/tracker_auto_commit.py)."""
    import datetime as _dt
    import os
    started_at = _dt.datetime.now()
    rc = 1
    try:
        rc = _run(allow_deletions="--allow-deletions" in
                  (sys.argv[1:] if argv is None else list(argv)))
        return rc
    finally:
        if not os.environ.get("HUB_REPORT_ID"):
            try:
                from automations.shared import hub_activity
                hub_activity.log_completed(
                    "tracker_auto_commit", "Tracker Auto Commit",
                    status=("success" if rc == 0 else "failed"),
                    started_at=started_at)
            except Exception as e:                    # noqa: BLE001
                print(f"(activity log skipped: {type(e).__name__}: {e})")


def _run(allow_deletions: bool = False) -> int:
    blocked = []

    # --- tracker leg -----------------------------------------------------
    try:
        from automations.tracker_onboarding import apply as TA, store as TS
        TS.set_client(_client())
        if TA.main(["--write"]) != 0:
            blocked.append("trackers: apply refused (validation problems "
                           "above)")
    except Exception as e:                            # noqa: BLE001
        blocked.append(f"trackers: {type(e).__name__}: {e}")

    # --- metrics leg (registries only — NEVER schedule_config.json) ------
    try:
        from automations.office_onboarding import apply as MA, store as MS
        MS.set_client(_client())
        if MA.main(["--write", "--registry-only"]) != 0:
            blocked.append("metrics: apply refused (validation problems "
                           "above)")
    except Exception as e:                            # noqa: BLE001
        blocked.append(f"metrics: {type(e).__name__}: {e}")

    # --- dispositions leg ------------------------------------------------
    # The KNOCKS & DISPOSITIONS sign-up (disposition_signup) materializes into
    # gap_alerts/onboarded_offices.json. Same durability need as the other two:
    # a confirmed office lives only in the runner's working tree until it is
    # committed, and `lucy update` autostashes that away — which is exactly how
    # nii and drew silently dropped out of the metrics runs.
    try:
        from automations.disposition_signup import apply as DA, store as DS
        DS.set_client(_client())
        if DA.main(["--write"]) != 0:
            blocked.append("dispositions: apply refused (validation problems "
                           "above)")
    except Exception as e:                            # noqa: BLE001
        blocked.append(f"dispositions: {type(e).__name__}: {e}")

    # --- schedule self-heal leg (add-only; no-op when nothing is missing) --
    # RETRY, and do not let a rate limit fail the run. The 17:30 pass failed
    # every day (8/27, 8/28) on a Sheets 429 "Read requests per minute per user"
    # while the 03:15 pass always succeeded — the evening slot lands in the busy
    # window (pushes writing walk diags every 5 min, the 2-hourly ad board, the
    # 17:00 source report) and simply runs out of read quota. Nothing was wrong
    # with the data.
    #
    # A quota miss is also HARMLESS here: this leg is add-only and a no-op when
    # nothing is missing, so skipping it costs one cycle and the next run heals.
    # Reporting it as BLOCKED made a daily red row for a transient condition,
    # which is how real failures get ignored. Any OTHER exception still blocks.
    try:
        from automations.office_onboarding import apply as MA
        from automations.recruiting_report.fill import _retry
        healed = _retry(heal_schedule, MA, attempts=3)
        if healed:
            print(f"schedule self-heal: re-added missing entries "
                  f"{', '.join(healed)}")
    except Exception as e:                            # noqa: BLE001
        _status = getattr(getattr(e, "response", None), "status_code", None)
        if _status == 429 or "quota exceeded" in str(e).lower():
            print("SKIP — schedule-heal: Sheets read quota exhausted after "
                  "retries; add-only leg skipped, next run heals it")
        else:
            blocked.append(f"schedule-heal: {type(e).__name__}: {e}")

    for b in blocked:
        print(f"BLOCKED — {b}")

    changed = [t for t in TARGETS
               if _git("status", "--porcelain", "--", t).stdout.strip()]
    if not changed:
        print("No enrollment changes — everything confirmed is already "
              "committed. Nothing to do.")
        return 1 if blocked else 0

    for t in changed:
        print(f"--- {t} changed ---\n{_git('diff', '--', t).stdout}\n---")

    # DELETION GUARD — see registry_changes above for the 2026-09-04 case this
    # exists to stop. Compare HEAD to the working tree STRUCTURALLY (a textual
    # diff can't tell a re-ordering from a removal) and refuse to push anything
    # that removes a value somebody actually put there.
    diffs = {}
    for t in changed:
        head = _git("show", f"HEAD:{t}")
        diffs[t] = registry_changes(
            head.stdout if head.returncode == 0 else "",
            (REPO_ROOT / t).read_text(encoding="utf-8"))

    destructive = {t: d["deleted"] for t, d in diffs.items() if d["deleted"]}
    if destructive and not allow_deletions:
        print("\nREFUSING TO COMMIT — this regeneration DELETES values that "
              "are in main:")
        for t, gone in destructive.items():
            for p in gone[:20]:
                print(f"    - {t}: {p}")
            if len(gone) > 20:
                print(f"    - {t}: … and {len(gone) - 20} more")
        print("\nNothing was staged, committed or pushed; the working tree is "
              "untouched, so the regenerated files are still there to inspect "
              "(`git diff`).\n"
              "A generated registry is not where a hand-authored value should "
              "live — if one of these was a fix, the fix needs a home the "
              "onboarding form can reproduce.\n"
              "If the deletion is REAL (an office genuinely offboarded, a "
              "field deliberately cleared), re-run with --allow-deletions.")
        # One summary line last, so a log tail shows the verdict without
        # scrolling. Not appended to `blocked` — that list is printed further
        # up, before this point is reached, and every target is staged together
        # so one destructive file has to stop the whole commit.
        print("\nBLOCKED — deletion guard: {} file(s) would lose {} value(s). "
              "Exit 1.".format(len(destructive),
                               sum(len(v) for v in destructive.values())))
        return 1

    _git("add", "--", *changed)
    # NAME WHAT CHANGED. The old message was the same three generic lines
    # whether this job added an office or removed six view URLs, so the one
    # place a wipe would have been visible to a human — `git log -p <file>` —
    # read as routine enrollment traffic.
    msg = ("enrollments: auto-commit confirmed offices\n\n"
           + "\n".join(_summarize(t, diffs[t]) for t in changed)
           + "\n\n- regenerated from the Tracker Onboarding + Office "
             "Onboarding tabs\n"
             "- committed so the enrollment survives the morning self-update"
           + ("\n- --allow-deletions was passed: removals above are "
              "deliberate" if (destructive and allow_deletions) else "")
           + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    # Explicit committer identity so a runner machine with no git config
    # (Lucy 1/2, the mini) can still commit.
    r = _git("-c", "user.name=Alphalete Runner",
             "-c", "user.email=alphaletereporting@gmail.com",
             "commit", "-m", msg)
    if r.returncode != 0:
        print(f"FAILED to commit:\n{r.stdout}\n{r.stderr}")
        return 1
    r = _git("pull", "--rebase", "--autostash", "origin", "main")
    if r.returncode != 0:
        print(f"FAILED to rebase onto origin/main:\n{r.stdout}\n{r.stderr}\n"
              "The commit exists locally — resolve and push by hand.")
        return 1
    r = _git("push", "origin", "main")
    if r.returncode != 0:
        print(f"FAILED to push:\n{r.stdout}\n{r.stderr}\n"
              "The commit exists locally — push by hand.")
        return 1
    head = _git("log", "--oneline", "-1").stdout.strip()
    print(f"✓ Committed + pushed: {head}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
