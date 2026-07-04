---
id: 13
title: 'Add downloads: d key on focused link/image + mdb get URL (authenticated, refe...'
state: DONE
priority: 1
created_at: 2026-07-04T10:25:06.537183-05:00
updated_at: 2026-07-04T10:42:02.591025-05:00
started_at: 2026-07-04T10:38:38.491956-05:00
completed_at: 2026-07-04T10:42:02.591021-05:00
---

# Add downloads: d key on focused link/image + mdb get URL (authenticated, referer-correct)

## Notes

- 2026-07-04T15:42:02Z: Shipped: src/mdb/download.py — Safari-identity fetch (cookies, iPhone UA, Referer), filename from content-disposition -> URL path -> mimetype, dedupe -N suffix. Reader d key downloads focused target (image src for image/card, href for links) with size in status. mdb get URL [--out DIR] [--private] CLI. Live-tested: picsum JPEG named 1081-400x300.jpg, verified by file(1).

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T15:38:38Z: State changed from TODO to BEGUN

- 2026-07-04T15:42:02Z: State changed from BEGUN to DONE
