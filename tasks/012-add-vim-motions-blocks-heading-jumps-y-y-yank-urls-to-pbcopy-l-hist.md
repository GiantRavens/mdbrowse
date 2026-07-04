---
id: 12
title: 'Add vim motions: {} blocks, () heading jumps, y/Y yank URLs to pbcopy, L hist...'
state: DONE
priority: 1
created_at: 2026-07-04T10:25:06.529426-05:00
updated_at: 2026-07-04T10:42:02.582206-05:00
started_at: 2026-07-04T10:38:38.486211-05:00
completed_at: 2026-07-04T10:42:02.582202-05:00
---

# Add vim motions: {} blocks, () heading jumps, y/Y yank URLs to pbcopy, L history-forward, zz center

## Notes

- 2026-07-04T15:42:02Z: Shipped: {}/() block+heading motions, y yank focused URL / Y page URL via pbcopy, L forward (proper forward stack, cleared on new go), zz center-focus. Chord state unified (pending 'g'/'z' — z-then-g no longer false-fires gg). HELP updated. PTY+pyte verified: heading jumps land on real sections, pbpaste round-trip, go/back/forward cycle.

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T15:38:38Z: State changed from TODO to BEGUN

- 2026-07-04T15:42:02Z: State changed from BEGUN to DONE
