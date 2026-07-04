---
id: 15
title: 'Add lynx mode phase 1: :ddg search shortcut + mdb ddg CLI (html.duckduckgo.co...'
state: DONE
priority: 2
created_at: 2026-07-04T10:25:06.546395-05:00
updated_at: 2026-07-04T11:38:20.448196-05:00
started_at: 2026-07-04T11:34:35.879855-05:00
completed_at: 2026-07-04T11:38:20.448192-05:00
---

# Add lynx mode phase 1: :ddg search shortcut + mdb ddg CLI (html.duckduckgo.com endpoints)

## Notes

- 2026-07-04T16:38:20Z: Shipped src/mdb/search.py: :ddg / :s prompts in reader, mdb ddg / mdb search CLI (argv-rewrite dispatch so all flags work). Reality: DDG anomaly-blocks headless engines (202 challenge on /html/ + /lite/) from this IP — ddg kept wired for friendlier networks; 's' defaults to Mojeek (verified live: clean one-bullet-per-result), MDBROWSE_SEARCH_URL template overrides. Corpus grown 5->8 fixtures (bbc-front feed 0.9, nasa-front feed 0.9, search-results page), selftest 8/8.

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T16:34:35Z: State changed from TODO to BEGUN

- 2026-07-04T16:38:20Z: State changed from BEGUN to DONE
