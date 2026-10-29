# Manager Agent

A delegation-only AI agent. The Manager never does a task itself — every job gets
decomposed into dedicated sub-agents (one per area), which run in parallel lanes
with web search/fetch access. The Manager coordinates and reports back.

## Setup (one time)

1. Get an API key at https://platform.claude.com (API Keys section).
2. Copy `.env.example` to `.env` and paste your key in.

## Run

```sh
cd ~/Desktop/manager-agent
./venv/bin/uvicorn server:app --port 8765
```

Then open http://localhost:8765 in your browser.

## How it works

- `server.py` — FastAPI backend. The Manager (Claude Opus 4.8) has exactly one
  tool, `spawn_subagent`. Each call spins up a fresh sub-agent with its own
  system prompt plus web search + web fetch. Parallel tool calls run as
  parallel lanes via `asyncio.gather`.
- `static/index.html` — live UI: manager narration on top, one card per
  sub-agent lane streaming underneath.
