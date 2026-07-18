# Core

- Python package `mdb` under `src/mdb`; repo-root `./mdb` is the local launcher.
- Main CLI entrypoint: `src/mdb/cli.py::main`; package scripts are `mdb` and `mdb-mcp` in `pyproject.toml`.
- Pipeline shape: capture browser/page state -> classify manifest -> emit deterministic markdown; reader, archive, watch, MCP are frontends over that core.
- Fixture corpus lives in `tests/fixtures` as `*.bundle.json` + `*.golden.md`.
- Project task history is markdown punchlist files under `tasks/`; use `pin` from repo root for active work state.
- Read `mem:tech_stack` for dependencies/tooling, `mem:conventions` for code patterns, `mem:suggested_commands` for common commands, and `mem:task_completion` before closing coding tasks.