---
id: 4
title: Port TUI reader onto new core (structured linkmap, no sentinels)
state: DONE
priority: 3
created_at: 2026-07-03T15:44:55.203142-05:00
updated_at: 2026-07-03T17:15:49.691372-05:00
started_at: 2026-07-03T17:10:52.832677-05:00
completed_at: 2026-07-03T17:15:49.691368-05:00
---

# Port TUI reader onto new core (structured linkmap, no sentinels)

## Notes

- 2026-07-03T22:00:40Z: Captain-approved input model: single focus ring over links AND images in document order (browser-like Tab/Shift-Tab). Enter=go (follow link / activate), Space=peek (Quick Look focused image; page-down only when focus is not an image — modality tied to visible focus, never viewport contents). Full-extent highlight across wrapped lines via (row,col0,col1) segments per focusable. Links bold+reverse on focus; images 🖼 + distinct treatment. Linked images: Enter follows, Space previews. Build on structured linkmap from IR — do NOT retrofit legacy sentinel reader.

- 2026-07-03T22:15:49Z: Shipped src/mdb/reader.py: focus ring over links+images+cards in document order; Enter=go, Space=peek (page-down only when focus isn't previewable); full-extent highlight across wrapped lines via char-attributed word wrap; escape-aware tokenizer over our own deterministic markdown (no sentinels); cards = linked thumbnails with dual verbs; mouse click/wheel; search /nN; warm Engine across navigation. PTY-tested: render, ring, Enter-nav, back, help, quit on example.com + CNN.

## Log

- 2026-07-03T20:44:55Z: Created task

- 2026-07-03T22:10:52Z: State changed from TODO to BEGUN

- 2026-07-03T22:15:49Z: State changed from BEGUN to DONE
