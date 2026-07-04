---
id: 17
title: 'Port Safari start page: bare mdb opens homepage + bookmarks + reading list'
state: DONE
priority: 2
created_at: 2026-07-04T10:25:06.555209-05:00
updated_at: 2026-07-04T11:17:19.544525-05:00
started_at: 2026-07-04T11:08:04.146562-05:00
completed_at: 2026-07-04T11:17:19.544521-05:00
---

# Port Safari start page: bare mdb opens homepage + bookmarks + reading list

## Notes

- 2026-07-04T15:38:04Z: Scope extended per captain: also WRITE direction — B key in reader adds current page to Safari Reading List. Write path MUST be AppleScript ('tell app Safari to add reading list item URL') — never write Bookmarks.plist directly (iCloud sync clobbers/corrupts). Read direction stays plist read-only as in legacy.

- 2026-07-04T16:17:19Z: Shipped src/mdb/safari.py: read (Bookmarks.plist -> start/bookmarks/reading pseudo-pages; FDA error page) + write (add_reading_list via AppleScript, compile-checked, never touches plist). Bare mdb = Safari start page (no engine launch, instant); --start/--bookmarks/--reading-list flags; safari: URLs in reader ':' prompt; B key adds page to Reading List (live-untested by design — mutates user state; first use triggers Terminal->Safari Automation prompt). PTY verified: 331 bookmarks + 1 RL item render, 327 focusables, heading jumps between sections.

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T16:08:04Z: State changed from TODO to BEGUN

- 2026-07-04T16:17:19Z: State changed from BEGUN to DONE
