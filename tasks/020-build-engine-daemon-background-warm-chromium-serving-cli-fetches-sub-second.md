---
id: 20
title: 'Build engine daemon: background warm Chromium serving CLI fetches sub-second'
state: DONE
priority: 4
created_at: 2026-07-04T10:25:06.567721-05:00
updated_at: 2026-07-04T14:57:21.604346-05:00
started_at: 2026-07-04T14:54:32.379642-05:00
completed_at: 2026-07-04T14:57:21.604342-05:00
---

# Build engine daemon: background warm Chromium serving CLI fetches sub-second

## Notes

- 2026-07-04T19:57:21Z: Shipped src/mdb/daemon.py: Unix socket ~/.mdb/engine.sock, one JSON request per connection, auto-spawn on first CLI capture, idle exit 1800s (MDBROWSE_DAEMON_IDLE), MDBROWSE_DAEMON=off opt-out, mdb daemon start/stop/status/run (run = launchd-friendly foreground). EngineWorker extracted to capture.py, shared with MCP. Page errors propagate (DNS preflight diagnosis intact through daemon). Bonus: settle skips the 2.5s SPA-shell wait on scriptless pages (can't hydrate). Timings: cold 3.7s -> warm 0.73s example / 0.99s HN. Clean shutdown verified — surviving chromiums were the captain's own 4 open reader sessions (two ~4h old).

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T19:54:32Z: State changed from TODO to BEGUN

- 2026-07-04T19:57:21Z: State changed from BEGUN to DONE
