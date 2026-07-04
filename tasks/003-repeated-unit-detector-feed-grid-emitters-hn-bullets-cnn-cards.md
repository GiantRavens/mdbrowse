---
id: 3
title: 'Repeated-unit detector: feed + grid emitters (HN bullets, CNN cards)'
state: DONE
priority: 2
created_at: 2026-07-03T15:44:55.199142-05:00
updated_at: 2026-07-03T16:43:44.058449-05:00
started_at: 2026-07-03T16:35:39.842209-05:00
completed_at: 2026-07-03T16:43:44.058445-05:00
---

# Repeated-unit detector: feed + grid emitters (HN bullets, CNN cards)

## Notes

- 2026-07-03T20:53:36Z: Feed shape already works for HN (rows) and CNN (anchor-inheritance bullets) via link-led detection. Remaining: geometric repeated-unit detector to merge card fragments (CNN kicker+headline same URL) and group by section.

- 2026-07-03T21:43:44Z: Shipped: units.py — pass 1 groups fragments by shared link target (CNN kicker/headline/deck), pass 2 by signature periodicity (starter class = longest links; attachment classes must recur >= 3x; starter-ness is per-block so Ask HN 1-link rows still lead). Boundaries: short linkless p = section pseudo-heading. Walker: stretched-link cards (empty overlay <a>) inherit href by containment when exactly one target. 5/5 selftest green.

## Log

- 2026-07-03T20:44:55Z: Created task

- 2026-07-03T21:35:39Z: State changed from TODO to BEGUN

- 2026-07-03T21:43:44Z: State changed from BEGUN to DONE
