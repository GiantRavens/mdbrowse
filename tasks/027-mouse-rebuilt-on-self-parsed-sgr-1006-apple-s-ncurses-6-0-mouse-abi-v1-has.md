---
id: 27
title: 'Mouse rebuilt on self-parsed SGR-1006: Apple''s ncurses 6.0 (mouse ABI v1) has...'
state: DONE
created_at: 2026-07-04T17:51:21.437356-05:00
updated_at: 2026-07-04T17:51:21.437544-05:00
---

# Mouse rebuilt on self-parsed SGR-1006: Apple's ncurses 6.0 (mouse ABI v1) has BUTTON5_PRESSED=0x0 — wheel-DOWN never existed as a curses event (why iTerm2 felt broken vs Ghostty's wheel->arrows translation). Now: wheel both directions everywhere, click coords past col 223 (X10 limit gone), never mode 1003 (Terminal.app safe), Home/End keys for scroll/switch devices, and mouse events are pty-TESTABLE (synthesized SGR bytes: wheel down/up + click-to-navigate all verified)

## Log

- 2026-07-04T22:51:21Z: Created task
