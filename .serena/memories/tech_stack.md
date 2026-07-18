# Tech Stack

- Python >=3.11 package using hatchling build backend.
- Runtime dependencies in `pyproject.toml`: `httpx`, `rich`, `playwright`, `mcp`.
- Browser capture depends on Playwright Chromium installed inside the local venv.
- User preference for this workspace: use `uv` for venv creation and package installs.
- No central pytest config observed; primary gates are project scripts (`mdb --selftest`, `tests/checkin.py`).