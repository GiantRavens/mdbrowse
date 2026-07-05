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
import re
from urllib.parse import quote_plus

DDG_HTML = "https://html.duckduckgo.com/html/?q={q}"
SEARCH_DEFAULT = "https://www.mojeek.com/search?q={q}"


def ddg_url(query: str) -> str:
    return DDG_HTML.format(q=quote_plus(query.strip()))


def search_url(query: str) -> str:
    template = os.environ.get("MDBROWSE_SEARCH_URL", SEARCH_DEFAULT)
    return template.format(q=quote_plus(query.strip()))


def resolve_prompt(text: str):
    """Prompt sugar: 'ddg terms' / 's terms' -> a results URL.
    Returns None when the input isn't an explicit search."""
    t = text.strip()
    if t.lower().startswith("ddg ") and t[4:].strip():
        return ddg_url(t[4:])
    if t.lower().startswith("s ") and t[2:].strip():
        return search_url(t[2:])
    return None


def _is_urlish(t: str) -> bool:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", t):
        return True                      # any scheme: https:, safari:, feed:
    if " " in t:
        return False
    host = t.split("/")[0]
    return "." in host or host.startswith("localhost")


def _local_host(t: str) -> bool:
    host = t.split("/")[0].split(":")[0]
    return bool(re.fullmatch(r"[\d.]+", host)          # IP literal
                or host.endswith(".local")              # mDNS
                or host.startswith("localhost"))


def omnibox(text: str) -> str:
    """The browser address-bar convention: explicit search prefixes win,
    URL-looking input navigates, everything else searches. Local targets
    (IP literals, .local mDNS, localhost) default to http:// — bare-IP
    devices rarely speak TLS."""
    t = text.strip()
    hit = resolve_prompt(t)
    if hit:
        return hit
    if _is_urlish(t):
        if "://" in t or t.startswith(("safari:", "feed:")):
            return t
        return ("http://" if _local_host(t) else "https://") + t
    return search_url(t)
