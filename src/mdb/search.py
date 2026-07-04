"""Search shortcuts — lynx mode, phase 1.

Most "I need the form" moments are search, and DuckDuckGo ships
endpoints designed for exactly this client: html.duckduckgo.com is
server-rendered, no JS wall, results as plain anchors. So search needs
zero new architecture — it's URL construction.

Reality check (2026-07): DDG currently anomaly-blocks headless engines
(202 challenge on /html/ and /lite/), so the generic 's' verb defaults
to Mojeek — independent, server-rendered, renders as clean one-line
results through our pipeline. 'ddg' stays wired: it may recover, and it
works from friendlier networks. MDBROWSE_SEARCH_URL (template with {q},
e.g. "https://kagi.com/search?q={q}") overrides the 's' engine.
"""

import os
from urllib.parse import quote_plus

DDG_HTML = "https://html.duckduckgo.com/html/?q={q}"
SEARCH_DEFAULT = "https://www.mojeek.com/search?q={q}"


def ddg_url(query: str) -> str:
    return DDG_HTML.format(q=quote_plus(query.strip()))


def search_url(query: str) -> str:
    template = os.environ.get("MDBROWSE_SEARCH_URL", SEARCH_DEFAULT)
    return template.format(q=quote_plus(query.strip()))


def resolve_prompt(text: str):
    """Reader ':' prompt sugar: 'ddg terms' / 's terms' -> a results URL.
    Returns None when the input isn't a search."""
    t = text.strip()
    if t.lower().startswith("ddg ") and t[4:].strip():
        return ddg_url(t[4:])
    if t.lower().startswith("s ") and t[2:].strip():
        return search_url(t[2:])
    return None
