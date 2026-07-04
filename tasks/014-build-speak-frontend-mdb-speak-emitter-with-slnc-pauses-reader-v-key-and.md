---
id: 14
title: 'Build speak frontend: mdb --speak emitter with slnc pauses + reader v key and...'
state: DONE
priority: 2
created_at: 2026-07-04T10:25:06.541847-05:00
updated_at: 2026-07-04T11:31:19.149428-05:00
started_at: 2026-07-04T11:27:17.512518-05:00
completed_at: 2026-07-04T11:31:19.149424-05:00
---

# Build speak frontend: mdb --speak emitter with slnc pauses + reader v key and --announce focus mode

## Notes

- 2026-07-04T16:31:19Z: Shipped src/mdb/speech.py + wiring: from_llines emitter (headings='Section:', items get [[slnc 400]] pauses, code blocks announced+skipped, quotes prefixed; [[ injection sanitized). CLI --speak/--speak-out AUDIO/--voice (MDBROWSE_VOICE); reader v key speaks from focused element (v stops, nav stops), --announce speaks each element on focus. Verified silently: say -o rendered 11s AIFF from example.com; structure/injection unit tests. Live listening = captain's acceptance test.

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T16:27:17Z: State changed from TODO to BEGUN

- 2026-07-04T16:31:19Z: State changed from BEGUN to DONE
