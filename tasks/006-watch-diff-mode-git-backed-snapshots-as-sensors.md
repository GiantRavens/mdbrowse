---
id: 6
title: 'Watch/diff mode: git-backed snapshots as sensors'
state: DONE
priority: 4
created_at: 2026-07-03T15:44:55.211303-05:00
updated_at: 2026-07-04T09:25:23.184636-05:00
started_at: 2026-07-04T09:23:11.260911-05:00
completed_at: 2026-07-04T09:25:23.184632-05:00
---

# Watch/diff mode: git-backed snapshots as sensors

## Notes

- 2026-07-04T14:25:23Z: Shipped src/mdb/watch.py: mdb watch add/rm/ls/scan/diff/log. Git-backed store (~/mdbrowse-watch, ) — one .md per watch, rewritten ONLY on content change, committed; git log -p = page history. Change trigger = text hash (URLs stripped) so HN-style per-session auth tokens never false-fire; verified by unit test. Scan = sensor readings (ok/CHANGED/error) with front-matter-filtered diff sample, --json for automation, exit 2 on errors. Live-tested full cycle: add, ok-scan, forced change fires + commits, log/diff/rm.

## Log

- 2026-07-03T20:44:55Z: Created task

- 2026-07-04T14:23:11Z: State changed from TODO to BEGUN

- 2026-07-04T14:25:23Z: State changed from BEGUN to DONE
