---
id: 16
title: 'Add lynx mode phase 2: walker captures GET forms as focusables, status-bar in...'
state: DONE
priority: 3
created_at: 2026-07-04T10:25:06.550731-05:00
updated_at: 2026-07-04T14:25:51.91173-05:00
started_at: 2026-07-04T14:23:15.397552-05:00
completed_at: 2026-07-04T14:25:51.911726-05:00
---

# Add lynx mode phase 2: walker captures GET forms as focusables, status-bar input, submit-as-navigate

## Notes

- 2026-07-04T19:25:51Z: Shipped lynx mode phase 2: walker captures GET forms (kind=form blocks: action/param/label/hidden params; password forms skipped — login is Safari's job; XML tree unaffected since emit ignores forms — documents stay content-only, forms are affordances). Reader: page hint 'search form: f' (combined with RSS hint), f prompts with the form's OWN label, submit = GET navigation. Verified: wikipedia (incl hidden title param), HN algolia footer form, mojeek; pty E2E f->'Search Wikipedia:'->query->results. Extractor a4, 8 fixtures recaptured, 8/8. Ops lesson: zsh does not word-split unquoted vars — 'set -- $pair' silently gave empty $2 and mdb fell through to the start page; use read -r loops.

## Log

- 2026-07-04T15:25:06Z: Created task

- 2026-07-04T19:23:15Z: State changed from TODO to BEGUN

- 2026-07-04T19:25:51Z: State changed from BEGUN to DONE
