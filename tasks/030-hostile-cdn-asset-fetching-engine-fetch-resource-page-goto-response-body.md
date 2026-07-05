---
id: 30
title: 'Hostile-CDN asset fetching: Engine.fetch_resource (page.goto + response.body ...'
state: DONE
created_at: 2026-07-04T20:16:22.29256-05:00
updated_at: 2026-07-04T20:16:22.292784-05:00
---

# Hostile-CDN asset fetching: Engine.fetch_resource (page.goto + response.body — full Chromium identity); preview + download fall back httpx(6s)->engine with 'via engine' telemetry. Root cause: luxury-brand WAFs (panerai/Richemont) tarpit httpx TLS fingerprints. New tier: tests/live_probes.py — network-truth suite (3 probes: hostile CDN, fast path stays fast, preflight speed), 3/3 green

## Log

- 2026-07-05T01:16:22Z: Created task
