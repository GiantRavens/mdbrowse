---
id: 8
title: Retire legacy mdbrowse.py once new path beats it on corpus
state: DONE
priority: 5
created_at: 2026-07-03T15:44:55.219112-05:00
updated_at: 2026-07-04T15:24:15.826715-05:00
started_at: 2026-07-04T15:22:49.550437-05:00
completed_at: 2026-07-04T15:24:15.826709-05:00
---

# Retire legacy mdbrowse.py once new path beats it on corpus

## Notes

- 2026-07-04T20:24:15Z: Retired per doctrine — replacement passed its scans first. Evidence: 8-fixture corpus green, oracle 9-10/10 (article/HN), v2 feature-superset (watch/MCP/speak/search/forms/RSS/downloads/assist/daemon/oracle — v1 had none). mdbrowse.py + requirements.txt removed from tree (alive in git history via ee3b830 lineage); README rewritten for v2; CHANGELOG retirement entry; notebook registry row updated (v1 reference dropped). Best v1 parts live on inside v2: settle heuristic, binarycookies parser, Safari integration, tracker lists.

## Log

- 2026-07-03T20:44:55Z: Created task

- 2026-07-04T20:22:49Z: State changed from TODO to BEGUN

- 2026-07-04T20:24:15Z: State changed from BEGUN to DONE
