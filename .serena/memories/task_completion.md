# Task Completion

- For path/config-only changes, run focused tests first, then `.venv/bin/python tests/checkin.py --offline-only` when affordable.
- For capture/classify/emit changes, run `./mdb --selftest` or `.venv/bin/python tests/checkin.py --offline-only`; use full `tests/checkin.py` only when network/browser behavior changed.
- Report any skipped live/browser verification explicitly.
- After onboarding/memory changes, user can run `serena memories check` from the project root to validate memory references.