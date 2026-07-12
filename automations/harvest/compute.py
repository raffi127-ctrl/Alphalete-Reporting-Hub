"""Bounded-parallel compute model — once data is in the dated cache, reports are
browser-free (parse TSV -> write Google Sheet -> post Slack) and run concurrently.

SHADOW-ONLY. Nothing on the live 4am path imports this. See README.md.

This is the Phase-2 execution model (design §7). It is INERT — provided so the
cutover has a ready worker pool, but nothing calls it yet.

Why bounded + per-spreadsheet lock:
  * gspread 429s on the SAME spreadsheet -> reports writing one workbook are
    serialized by a per-spreadsheet lock; different workbooks run free.
  * Slack rate-limits per channel.
Threads (not processes): the work is IO-bound and cross-platform.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from automations.harvest import config


@dataclass
class ComputeTask:
    label: str
    fn: Callable[[], object]
    spreadsheet_key: Optional[str] = None   # None -> no serialization


@dataclass
class ComputeOutcome:
    label: str
    ok: bool
    result: object = None
    error: Optional[str] = None


def run_compute_pool(tasks: List[ComputeTask],
                     *,
                     max_workers: Optional[int] = None,
                     logfn: Callable[[str], None] = print) -> List[ComputeOutcome]:
    """Run browser-free compute tasks concurrently, serializing tasks that share
    a spreadsheet_key. Returns one outcome per task (a failing task is captured,
    never aborts the pool)."""
    max_workers = max_workers or int(config.COMPUTE_MAX_WORKERS)
    locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)

    def _run(task: ComputeTask) -> ComputeOutcome:
        try:
            if task.spreadsheet_key is None:
                return ComputeOutcome(task.label, True, task.fn())
            with locks[task.spreadsheet_key]:
                return ComputeOutcome(task.label, True, task.fn())
        except Exception as e:  # noqa: BLE001
            return ComputeOutcome(task.label, False, error=f"{type(e).__name__}: {e}")

    outcomes: List[ComputeOutcome] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_run, t): t for t in tasks}
        for fut in as_completed(futs):
            oc = fut.result()
            outcomes.append(oc)
            logfn(f"  [compute] {'ok ' if oc.ok else 'ERR'} {oc.label}"
                  + ("" if oc.ok else f" — {oc.error}"))
    return outcomes
