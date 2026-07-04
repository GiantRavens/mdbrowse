---
id: 23
title: 'Walker inlineMD: pad adjacent inline element boundaries when source has no wh...'
state: DONE
priority: 2
created_at: 2026-07-04T11:38:20.437913-05:00
updated_at: 2026-07-04T12:06:59.19704-05:00
started_at: 2026-07-04T11:44:44.523088-05:00
completed_at: 2026-07-04T12:06:59.197036-05:00
---

# Walker inlineMD: pad adjacent inline element boundaries when source has no whitespace (BBC 'U-turn](url)England's' glue class — legacy fixed via '> <' insertion)

## Notes

- 2026-07-04T17:06:59Z: Shipped: needsPad() in walker inlineMD — pads element boundaries (text/A/IMG/STRONG/EM/CODE) only when BOTH sides lack separation; openers/closers stay tight. Kills the BBC 'headline](url)summary' glue class at the source. Extractor 2.0.0a3 (bundles change). All 8 fixtures recaptured, 8/8 green, zero over-padding artifacts. Ops lesson: 8-capture chain hung 20min on BBC with THREE concurrent Chromium fleets running (captain was live-browsing) — solo capture takes 1.75s; page.evaluate has no timeout, so concurrent-engine contention can wedge it. If it recurs, add a capture watchdog.

## Log

- 2026-07-04T16:38:20Z: Created task

- 2026-07-04T16:44:44Z: State changed from TODO to BEGUN

- 2026-07-04T17:06:59Z: State changed from BEGUN to DONE
