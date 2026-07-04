---
id: 7
title: Screenshot fidelity oracle (VLM markdown-vs-pixels scorer)
state: DONE
priority: 4
created_at: 2026-07-03T15:44:55.215132-05:00
updated_at: 2026-07-04T15:08:30.695363-05:00
started_at: 2026-07-04T15:05:16.224513-05:00
completed_at: 2026-07-04T15:08:30.695356-05:00
---

# Screenshot fidelity oracle (VLM markdown-vs-pixels scorer)

## Notes

- 2026-07-04T20:08:30Z: Shipped src/mdb/oracle.py: mdb oracle URL — Engine.capture gained screenshot_path (full-page PNG), judge = claude -p --allowedTools Read comparing pixels vs compiled markdown; structured report (score, shape_verdict, missing/mangled/misordered, verdict). Explicitly instructed not to penalize deliberate drops (chrome/ads/styling). FIRST RUN EARNED ITS KEEP: caught code blocks double-spaced (highlighter line-wrapping doubles innerText newlines) — fixed in walker PRE with alternation heuristic (threshold must be (len-1)/2: perfect alternation is strictly under half — off-by-one caught live). Scores: article 9/10, HN 10/10 ('all 30 stories verbatim in exact order'). Extractor a5.

## Log

- 2026-07-03T20:44:55Z: Created task

- 2026-07-04T20:05:16Z: State changed from TODO to BEGUN

- 2026-07-04T20:08:30Z: State changed from BEGUN to DONE
