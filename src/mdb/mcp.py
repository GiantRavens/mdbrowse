"""MCP frontend: the live web as deterministic markdown for agent sessions.

Exposes the capture -> classify -> emit pipeline over stdio MCP. Browses
with the user's Safari session by default (logged-in and paywalled-to-you
pages render as they would in Safari); `private=True` sends no cookies.

Playwright's sync API is thread-bound, so a single dedicated worker thread
owns the warm browser engines (one authenticated, one private) and serves
capture jobs from a queue — every tool call after the first reuses a hot
Chromium, and MCP's own thread pool never touches Playwright objects.

A short-TTL bundle cache lets fetch_page / page_links / archive_page on the
same URL share one capture instead of re-rendering.
"""

import threading
import time

from mcp.server.fastmcp import FastMCP

from . import EXTRACTOR_VERSION
from .archive import save_archive
from .bundle import content_hash
from .capture import EngineWorker
from .classify import classify
from .emit import emit, emit_body

mcp = FastMCP("mdbrowse")

_CACHE_TTL = 60.0          # seconds; just long enough to share one capture

_worker = EngineWorker()   # shared thread-owns-Playwright pattern (capture.py)
_cache = {}          # (url, private) -> (timestamp, bundle)
_cache_lock = threading.Lock()


def _normalize(url: str) -> str:
    import re
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def _get_bundle(url: str, private: bool, wait: str | None = None) -> dict:
    url = _normalize(url)
    key = (url, private)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    bundle = _worker.capture(url, private, wait)
    with _cache_lock:
        _cache[key] = (time.monotonic(), bundle)
        if len(_cache) > 16:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            del _cache[oldest]
    return bundle


@mcp.tool()
def fetch_page(url: str, private: bool = False, wait_selector: str = "",
               max_chars: int = 80000) -> str:
    """Fetch a web page as clean, deterministic markdown with provenance.

    Renders the page in a headless browser (JS/SPA content included),
    classifies its shape (article / feed / page / app), and emits
    hierarchically clean markdown. The YAML front-matter carries title,
    source URL, retrieval timestamp, auth mode, shape verdict with
    confidence, and a content hash of the body — the same page state
    always produces the same body, so hashes and diffs are meaningful.

    Browses with the user's Safari cookies by default (logged-in pages
    render as the user sees them); set private=true for an anonymous
    fetch. Use wait_selector (a CSS selector) only for SPAs that paint
    late. Feed/listing pages (HN, news fronts) come back as one linked
    line per story; article pages as clean prose with inline links.
    """
    bundle = _get_bundle(url, private, wait_selector or None)
    doc = emit(bundle, classify(bundle))
    if len(doc) > max_chars:
        doc = doc[:max_chars] + f"\n\n_[truncated at {max_chars} chars]_\n"
    return doc


@mcp.tool()
def page_links(url: str, private: bool = False, max_links: int = 200) -> list:
    """List a page's links as [{text, href}, ...] in document order.

    Cheaper to reason over than full markdown when deciding where to
    navigate next. Shares the capture with fetch_page on the same URL
    (60s cache), so calling both costs one page render.
    """
    bundle = _get_bundle(url, private)
    seen, out = set(), []
    for b in bundle["doc"].get("blocks", []):
        for l in b.get("links") or []:
            if l["href"] in seen:
                continue
            seen.add(l["href"])
            out.append({"text": l["text"], "href": l["href"]})
            if len(out) >= max_links:
                return out
    return out


@mcp.tool()
def archive_page(url: str, private: bool = False) -> dict:
    """Fetch a page and save a timestamped markdown archive with
    provenance front-matter (to ~/mdbrowse-archive or $MDBROWSE_ARCHIVE).

    Returns {path, title, shape, hash}. The hash covers the body only,
    so re-archiving an unchanged page yields the same hash — compare
    hashes to detect real content changes without diffing.
    """
    bundle = _get_bundle(url, private)
    manifest = classify(bundle)
    doc = emit(bundle, manifest)
    title = bundle["doc"].get("title") or bundle["meta"]["url"]
    path = save_archive(doc, title, bundle["meta"]["url"])
    return {
        "path": path,
        "title": title,
        "shape": manifest.shape,
        "hash": content_hash(emit_body(bundle, manifest)),
        "extractor": EXTRACTOR_VERSION,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
