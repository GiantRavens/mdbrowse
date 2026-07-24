"""mdb — web -> deterministic markdown compiler.

Pipeline: capture (in-browser IR) -> classify (shape manifest) -> emit
(per-shape markdown). Frontends consume the stages: CLI, TUI reader,
archive store, MCP server.
"""

__version__ = "2.1.0"
EXTRACTOR_VERSION = __version__
