---
id: 17
title: 'Port Safari start page: bare mdb opens homepage + bookmarks + reading list'
state: TODO
priority: 2
created_at: 2026-07-04T10:25:06.555209-05:00
updated_at: 2026-07-04T10:38:04.637908-05:00
---

# Port Safari start page: bare mdb opens homepage + bookmarks + reading list

## Notes

- 2026-07-04T15:38:04Z: Scope extended per captain: also WRITE direction — B key in reader adds current page to Safari Reading List. Write path MUST be AppleScript ('tell app Safari to add reading list item URL') — never write Bookmarks.plist directly (iCloud sync clobbers/corrupts). Read direction stays plist read-only as in legacy.

## Log

- 2026-07-04T15:25:06Z: Created task
