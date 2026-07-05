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


def _emit_doc(url: str, private: bool, wait: str | None,
              max_chars: int, start_char: int) -> str:
    bundle = _get_bundle(url, private, wait)
    doc = emit(bundle, classify(bundle))
    total = len(doc)
    if start_char:
        doc = doc[start_char:]
    if len(doc) > max_chars:
        nxt = start_char + max_chars
        doc = (doc[:max_chars]
               + f"\n\n_[showing chars {start_char}-{nxt} of {total}; "
               f"call again with start_char={nxt} for the rest — the 60s "
               f"capture cache makes the continuation free]_\n")
    return doc


@mcp.tool()
def fetch_page(url: str, private: bool = False, wait_selector: str = "",
               max_chars: int = 80000, start_char: int = 0) -> str:
    """Fetch a web page as clean, deterministic markdown with provenance.

    Renders the page in a headless browser (JS/SPA content included),
    classifies its shape (article / feed / page / app), and emits
    hierarchically clean markdown. The YAML front-matter carries title,
    source URL, retrieval timestamp, auth mode, shape verdict with
    confidence, and a content hash of the body — the same page state
    always produces the same body, so hashes and diffs are meaningful.
    Data tables come back as markdown pipe tables.

    Browses with the user's Safari cookies by default (logged-in pages
    render as the user sees them); set private=true for an anonymous
    fetch. Use wait_selector (a CSS selector) only for SPAs that paint
    late. Feed/listing pages (HN, news fronts) come back as one linked
    line per story; article pages as clean prose with inline links.

    Long pages paginate: on truncation the tail says which start_char
    fetches the next slice (served from the capture cache, no re-render).
    """
    return _emit_doc(url, private, wait_selector or None, max_chars, start_char)


@mcp.tool()
def search_web(query: str, private: bool = False, max_chars: int = 40000) -> str:
    """Search the web; results come back as markdown, one linked line per
    result. Uses the user's configured engine (Mojeek by default;
    MDBROWSE_SEARCH_URL overrides — e.g. Kagi with the user's session,
    since searches ride Safari cookies like any page). Follow up with
    fetch_page on the results worth reading.
    """
    from .search import search_url
    return _emit_doc(search_url(query), private, None, max_chars, 0)


@mcp.tool()
def page_links(url: str, private: bool = False, max_links: int = 200,
               pattern: str = "") -> list:
    """List a page's links as [{text, href}, ...] in document order.

    Cheaper to reason over than full markdown when deciding where to
    navigate next. `pattern` (case-insensitive regex) filters on link
    text OR href — e.g. pattern="item\\?id=" for HN comment pages.
    Shares the capture with fetch_page on the same URL (60s cache), so
    calling both costs one page render.
    """
    import re
    rx = re.compile(pattern, re.I) if pattern else None
    bundle = _get_bundle(url, private)
    seen, out = set(), []
    for b in bundle["doc"].get("blocks", []):
        for l in b.get("links") or []:
            if l["href"] in seen:
                continue
            seen.add(l["href"])
            if rx and not (rx.search(l["text"]) or rx.search(l["href"])):
                continue
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


def _no_exit(fn, *args, **kwargs):
    """watch.py's CLI verbs speak SystemExit; over MCP that must become
    a normal error the agent can read and react to."""
    try:
        return fn(*args, **kwargs)
    except SystemExit as e:
        raise RuntimeError(str(e))


@mcp.tool()
def watch_add(url: str, name: str = "", private: bool = False) -> dict:
    """Start watching a URL for real content change. Takes the first
    snapshot now (git-committed to the watch store); later watch_scan
    calls fire only when visible text changes — link-token churn never
    false-fires. Name defaults to a slug of the URL.
    """
    from . import watch
    watch_name = _no_exit(watch.add, _normalize(url), name or None, private)
    return {"name": watch_name, "store": watch.WATCH_DIR,
            "snapshot": f"{watch.WATCH_DIR}/{watch_name}.md"}


@mcp.tool()
def watch_list() -> list:
    """List configured watches: name, url, mode, when last checked and
    last actually changed."""
    from . import watch
    return [{"name": n, "url": w["url"],
             "mode": "private" if w.get("private") else "authenticated",
             "last_checked": w.get("last_checked"),
             "last_changed": w.get("last_changed")}
            for n, w in sorted(watch._load().items())]


@mcp.tool()
def watch_scan(names: list = []) -> list:
    """Re-fetch watches and report one reading each: status ok (no real
    change) / changed (snapshot committed; diff_sample shows what moved)
    / error (with the why). Empty names scans everything. Changes are
    detected on visible text only, so a 'changed' reading means a reader
    would agree the page changed.
    """
    from . import watch
    return watch.scan_readings(names or None)


@mcp.tool()
def watch_diff(name: str) -> str:
    """A watch's most recent change as a git patch (old lines -, new
    lines +). Use after watch_scan reports 'changed' to see exactly
    what moved."""
    from . import watch
    return watch.diff_text(name)


@mcp.tool()
def watch_remove(name: str) -> dict:
    """Stop watching a page. Its snapshot history stays in the store's
    git log."""
    from . import watch
    _no_exit(watch.remove, name)
    return {"removed": name}


@mcp.tool()
def archive_search(query: str, max_results: int = 10) -> list:
    """Search previously archived pages (the personal web memory that
    archive_page writes to). Term-AND full text; returns {path, title,
    source, retrieved, score, snippet} best-first. Read a hit's path
    for the full page as it was when archived."""
    from .archive import search_archive
    return search_archive(query, max_results)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
