# Suggested Commands

- Setup: `uv venv && uv pip install -e .`
- Install browser after setup: `.venv/bin/playwright install chromium`
- Local launcher/version: `./mdb --version`
- Offline fixture gate: `.venv/bin/python tests/checkin.py --offline-only`
- Full gate with live probes: `.venv/bin/python tests/checkin.py`
- Direct selftest: `./mdb --selftest`
- Task state: `pin ls`, `pin begun N`, `pin done N`, `pin todo "description" pri:N tags:"{tag}"`.