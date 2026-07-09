"""Search shortcuts — lynx mode, phase 1.

Most "I need the form" moments are search. The reader's `:s terms`
path stays URL-shaped so it can reuse the normal capture pipeline, but
the provider is deliberately user-selectable:

    MDBROWSE_SEARCH_ENGINE=duckduckgo|mojeek|ddg-html
    MDBROWSE_SEARCH_URL="https://kagi.com/search?q={q}"

The named engine keeps the common case readable; the URL template is the
escape hatch for anything with a `q`-style query parameter.
"""

import os
import re
from urllib.parse import quote_plus

SEARCH_ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "ddg": "https://duckduckgo.com/?q={q}",
    "ddg-html": "https://html.duckduckgo.com/html/?q={q}",
    "mojeek": "https://www.mojeek.com/search?q={q}",
}
SEARCH_DEFAULT_ENGINE = "duckduckgo"


def _template_for(engine: str) -> str:
    return SEARCH_ENGINES.get(engine.strip().lower(),
                              SEARCH_ENGINES[SEARCH_DEFAULT_ENGINE])


def ddg_url(query: str) -> str:
    return provider_url("duckduckgo", query)


def provider_url(engine: str, query: str) -> str:
    return _template_for(engine).format(q=quote_plus(query.strip()))


def search_url(query: str) -> str:
    template = os.environ.get("MDBROWSE_SEARCH_URL")
    if not template:
        engine = os.environ.get("MDBROWSE_SEARCH_ENGINE",
                                SEARCH_DEFAULT_ENGINE)
        template = _template_for(engine)
    return template.format(q=quote_plus(query.strip()))


def resolve_prompt(text: str):
    """Prompt sugar: 'ddg terms' / 'mojeek terms' / 's terms' -> a results URL.
    Returns None when the input isn't an explicit search."""
    t = text.strip()
    lower = t.lower()
    for engine in sorted(SEARCH_ENGINES, key=len, reverse=True):
        prefix = engine + " "
        if lower.startswith(prefix) and t[len(prefix):].strip():
            return provider_url(engine, t[len(prefix):])
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
