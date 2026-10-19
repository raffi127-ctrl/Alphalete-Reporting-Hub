"""The review-post lookups read #revision-emails in PAGES, never one limit=100
call: on the mini that single read truncated (IncompleteRead) at 66-75 KB on
every attempt 2026-10-15/16 and killed the DD + Override gates. Offline: a fake
client, nothing touches Slack."""
from automations.override_bulletin import override_gate as OG
from automations.override_bulletin import review_gate as RG


class _FakeClient:
    def __init__(self, msgs):
        self.msgs, self.calls = msgs, []

    def conversations_history(self, channel, limit, cursor=None):
        self.calls.append(limit)
        start = int(cursor or 0)
        page = self.msgs[start:start + limit]
        nxt = str(start + limit) if start + limit < len(self.msgs) else ""
        return {"messages": page, "response_metadata": {"next_cursor": nxt}}


def _run(monkeypatch, fn, title):
    msgs = [{"text": "noise %d" % i} for i in range(60)] + [{"text": "*" + title + " link"}]
    fake = _FakeClient(msgs)
    monkeypatch.setattr(RG, "_client", lambda: fake)
    monkeypatch.setattr(RG, "_channel", lambda c=None: "C1")
    out = fn()
    assert max(fake.calls) <= 25, fake.calls          # never one big read
    assert [m["text"] for m in out] == ["*" + title + " link"]  # found past page 1


def test_dd_gate_reads_paged(monkeypatch):
    monkeypatch.setattr(RG, "_title", lambda today=None: "Organization Bulletin — WE 1.1.26")
    _run(monkeypatch, lambda: RG._all_posts(), "Organization Bulletin — WE 1.1.26")


def test_override_gate_reads_paged(monkeypatch):
    monkeypatch.setattr(OG, "_title", lambda wk: "Override Bulletin — WE " + wk)
    _run(monkeypatch, lambda: OG._all_posts("1.1.26"), "Override Bulletin — WE 1.1.26")
