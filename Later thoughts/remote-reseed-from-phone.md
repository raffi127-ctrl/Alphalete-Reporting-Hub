# Remote desktop to the mini — phone reseed backstop

Parked 2026-06-30 (Megan). · **ON HOLD 2026-06-30 — likely moot: Cloudflare
bypass now works** (built in a parallel chat). The whole point of this note was
to get a human to the mini to clear the Cloudflare "verify you're human" check;
if that check no longer blocks the session, there's nothing to clear remotely.
KEEP as a backstop only until the bypass is proven durable/allowed — if it turns
out flaky, this phone-reseed path is the fallback. Revisit then; otherwise close.

**Idea:** set up remote desktop on the central Mac mini + Megan's phone — **AnyDesk**
(free, iOS/Android apps, works off-network) is the most phone-friendly; TeamViewer
or macOS Screen Sharing are alternatives.

**Why:** the session-staleness watchdog (see [[project_session_staleness_fix]])
keeps Lucy (the ownerville/Tableau session) warm and self-heals a dead browser or
a reboot. The ONE event it can't self-heal is a **true Cloudflare "verify you're
human" reseed** (cookies fully expired) — that needs a real screen + a click,
which no script and not the lucy poller can do. The 3am/6pm health alert DMs when
a reseed is needed; **remote desktop is how you'd actually do it from your phone**
in ~30 seconds, from anywhere. Lucy is a DAILY dependency (Rashad metrics every
morning + Leaders Call Mondays), so a reseed-need can surface any day.

**Scope when picked up (~5-10 min):** install AnyDesk on the mini, set an
unattended-access password, install the phone app, test connecting from the
phone, and confirm you can see the screen + click (clear a Cloudflare box).
