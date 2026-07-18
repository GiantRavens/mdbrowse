# Conventions

- Keep CLI/MCP/reader as thin frontends over shared functions; avoid duplicating capture/classify/emit logic.
- Tests and gates favor manifest-style structural checks and classified failure reasons over raw pass counts.
- Preserve env var overrides for user paths and behavior; defaults should be platform-aware and not spill visible state into `$HOME`.
- Archive/watch behavior stores user data; avoid destructive migration or deleting old user stores without explicit user action.
- Code style is simple stdlib-heavy Python with type hints used where helpful, module constants for stable paths/options, and concise comments for non-obvious failure history.