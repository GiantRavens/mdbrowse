---
id: 19
title: 'Add RSS feed mode: auto-discover feed link, F to switch, render as feed shape'
state: DONE
priority: 3
created_at: 2026-07-04T10:25:06.563648-05:00
updated_at: 2026-07-04T14:00:43.24819-05:00
started_at: 2026-07-04T13:56:57.893522-05:00
completed_at: 2026-07-04T14:00:43.248186-05:00
---

# Add RSS feed mode: auto-discover feed link, F to switch, render as feed shape

## Notes

- 2026-07-04T19:00:43Z: Shipped src/mdb/rss.py: static httpx fetch (XML would only give the engine its tree viewer) + ElementTree parser for RSS 2.0 AND Atom, HTML-in-summary stripped, dates tidied; emits feed-shape markdown directly (loose linked bullets: title — date — summary). Discovery: walker captures link[rel=alternate] rss/atom (feeds[] in bundle meta); reader hints 'RSS available — press F' and F opens feed:URL; feed: works at : prompt and as mdb feed URL CLI (all flags compose: --speak, --raw...). Live: BBC RSS + xkcd Atom render clean; pty hint->F->feed->H verified. Note: bbc.co.uk homepage no longer advertises feeds — discovery only sees what pages declare.

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T18:56:57Z: State changed from TODO to BEGUN

- 2026-07-04T19:00:43Z: State changed from BEGUN to DONE
