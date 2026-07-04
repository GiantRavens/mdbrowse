---
id: 5
title: 'MCP server frontend: fetch_page(url) -> markdown with provenance'
state: DONE
priority: 3
created_at: 2026-07-03T15:44:55.207303-05:00
updated_at: 2026-07-04T08:48:25.190325-05:00
started_at: 2026-07-04T08:46:02.483633-05:00
completed_at: 2026-07-04T08:48:25.19032-05:00
---

# MCP server frontend: fetch_page(url) -> markdown with provenance

## Notes

- 2026-07-04T13:48:25Z: Shipped src/mdb/mcp.py (FastMCP, stdio): fetch_page / page_links / archive_page. Playwright sync API is thread-bound -> dedicated worker thread owns warm engines (auth+private), jobs via queue; 60s bundle cache shares one capture across tools. Registered user-scope via claude mcp add (Mac ~/.claude.json), verified Connected; registry row added to tools/MCP_AND_TOOLS.md. E2E stdio client test: cold 4.1s, warm HN 1.0s, cache hit 0.00s; example.com body hash identical across days.

## Log

- 2026-07-03T20:44:55Z: Created task

- 2026-07-04T13:46:02Z: State changed from TODO to BEGUN

- 2026-07-04T13:48:25Z: State changed from BEGUN to DONE
