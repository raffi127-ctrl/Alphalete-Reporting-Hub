# Let the Apex run carry on in a background tab

**Parked 2026-09-17** (Megan: "I can't go to another tab?" — yes, come back to this.)

## The problem

The whole-week run lives in the page's JavaScript and paces itself with
`await sleep(ms)` — `setTimeout` under the hood. Chrome throttles timers in
**hidden** tabs: clamped to ~1/second, and after a few minutes a background tab
can be squeezed to roughly one timer per minute.

The run does not die. It crawls. Our waits are 300–1800ms each and there are
several per page, three pages per person, so a 17-person pass that takes minutes
in front could take hours behind another tab. In practice that means somebody
has to sit and watch the tab for the length of the run, which is the one part of
this that still costs a person their time.

## The fix worth trying

Drive the waits from a **dedicated Web Worker** instead of the page's own
timers. Worker timers are not subject to the same background-tab throttling, so
a worker that posts a tick after N ms keeps the run moving at full speed while
the tab is hidden. The DOM work still happens on the main thread, woken by the
worker's message.

Shape of it:

- one `Worker` made from a blob URL (Apex serves no CSP, so a blob worker is
  allowed — same reason `new Function()` works there)
- `sleep(ms)` becomes: post `{wait: ms}` to the worker, resolve the promise when
  the matching message comes back
- keep the current `setTimeout` version as the fallback if `Worker` or
  `createObjectURL` is unavailable, so nothing breaks where it is not

## Why it was not done on the day

It replaces the single primitive every other part of the run engine is built on
(`sleep` is in the lookup, the filter settle, the page waits, the save wait),
and it came up mid-run on a Thursday with 17 people going in. Not the moment.

## Check it actually worked

Not by reasoning about it — by running a week with the tab behind another one
and timing it against a run in front. If the two are within a few seconds of
each other, it works. Chrome's throttling rules change; a test that asserts
"Worker timers are not throttled" would be asserting Chrome's behaviour, not
ours.

## Where the code is

`automations/apex_new_starts/filler.py` — `function sleep(ms)`, near the top of
`_JS`.
