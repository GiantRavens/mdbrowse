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


def _wayback_snapshot(url: str) -> str | None:
    """The closest Wayback Machine snapshot URL, or None. Uses the `id_` modifier so the
    archived ORIGINAL bytes are served (no Wayback toolbar/link-rewriting to extract around)."""
    import json
    import re as _re
    import urllib.parse
    import urllib.request
    try:
        api = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
        req = urllib.request.Request(api, headers={"User-Agent": "mdbrowse/2"})
        with urllib.request.urlopen(req, timeout=6) as r:   # fail fast if archive.org is down/blocked
            data = json.load(r)
        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            u = snap["url"].replace("http://", "https://")
            return _re.sub(r"/web/(\d+)/", r"/web/\1id_/", u)
    except Exception:
        return None
    return None


def _emit_doc(url: str, private: bool, wait: str | None,
              max_chars: int, start_char: int) -> str:
    bundle = _get_bundle(url, private, wait)
    manifest = classify(bundle)
    note = ""
    # WALL -> WAYBACK: a live page that bot-walls (or is IP-blocked) is often archived and
    # served freely by the Wayback Machine. Auto-fall back to the snapshot rather than fail.
    if manifest.shape == "wall" and "web.archive.org" not in url:
        snap = _wayback_snapshot(url)
        if snap:
            b2 = _get_bundle(snap, private, wait)
            m2 = classify(b2)
            if m2.shape != "wall":
                bundle, manifest = b2, m2
                note = (f"> _Live page was blocked (a bot wall); showing the Wayback Machine "
                        f"snapshot instead — {snap}_\n\n")
    doc = note + emit(bundle, manifest)
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
def fetch_archived(url: str, max_chars: int = 80000, start_char: int = 0) -> str:
    """Fetch a page from the Wayback Machine (archive.org) instead of live. Recovers pages the
    live fetch can't get — bot walls, IP-blocked sites, dead links, or content that changed.
    Returns the archived snapshot as clean markdown, tagged with its capture date. Reach for
    this when fetch_page returns a wall, or when you want the historical version of a page.
    """
    snap = _wayback_snapshot(_normalize(url))
    if not snap:
        return f"no Wayback Machine snapshot found for {url}"
    return _emit_doc(snap, False, None, max_chars, start_char)


@mcp.tool()
def search_web(query: str, private: bool = False, max_chars: int = 40000) -> str:
    """Search the web; results come back as markdown, one linked line per
    result. Uses the user's configured engine (DuckDuckGo by default;
    MDBROWSE_SEARCH_ENGINE or MDBROWSE_SEARCH_URL overrides — e.g. Kagi
    with the user's session, since searches ride Safari cookies like any
    page). Follow up with fetch_page on the results worth reading.
    """
    from .search import search_url
    return _emit_doc(search_url(query), private, None, max_chars, 0)


@mcp.tool()
def download_document(url: str, dest_dir: str = "", referer: str = "",
                      private: bool = False) -> str:
    """Download a linked file directly to disk — a PDF, spec sheet, dataset, image,
    archive, anything. Fetches through the user's session (Safari cookies + a browser
    UA + optional Referer ride along), so session-gated and hotlink-protected files
    come through, and names the file from Content-Disposition or the URL.

    Use this when a page LINKS a document worth keeping rather than reading inline —
    e.g. a solution-brief PDF found via fetch_page/page_links. Pass `referer` as the
    page the link was on for hotlink-protected hosts. Saves to ~/Downloads by default
    (override with dest_dir, or the MDBROWSE_DOWNLOADS env var). Returns the saved
    path, size, and type. If a hostile WAF tarpits the direct fetch, open the page in
    the reader and press `d` (that path fetches through the live browser engine).
    """
    import mimetypes

    from .download import download
    u = _normalize(url)
    try:
        path, size = download(u, private=private, referer=(referer or None),
                              dest_dir=(dest_dir or None))
    except Exception as e:
        return (f"download failed: {type(e).__name__}: {e}\n"
                "(WAF-tarpitted host? Open the page in the reader and press `d` for a "
                "browser-backed fetch.)")
    ct = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"downloaded: {path}\nsize: {size / 1024:.0f} KB\ntype: {ct}"


@mcp.tool()
def download_video(url: str, dest_dir: str = "", audio_only: bool = False) -> str:
    """Download a video (or just its audio) from a page or media URL via yt-dlp — which
    handles what a plain file download can't: direct mp4/webm, HLS/DASH manifests
    (.m3u8/.mpd), and YouTube/Vimeo/embedded players resolved from the page URL.

    Muxes best video+audio to mp4, or extracts m4a with audio_only=true. Saves to
    ~/Downloads by default (override with dest_dir or MDBROWSE_DOWNLOADS). Returns the
    saved path. For gated video, set MDBROWSE_YTDLP_BROWSER (e.g. 'chrome'/'safari') to
    ride your browser cookies; it retries anonymously if the cookie backend fails. Use
    this for a <video>/embed a user wants to keep; use download_document for a plain
    file (PDF, image, dataset).
    """
    import os
    import shutil
    import subprocess
    if not shutil.which("yt-dlp"):
        return "download_video: yt-dlp is not on PATH"
    u = _normalize(url)
    dest = os.path.expanduser(dest_dir or os.environ.get("MDBROWSE_DOWNLOADS", "~/Downloads"))
    os.makedirs(dest, exist_ok=True)
    out_tmpl = os.path.join(dest, "%(title).120s [%(id)s].%(ext)s")
    base = ["yt-dlp", "--no-playlist", "--restrict-filenames", "-o", out_tmpl,
            "--no-progress", "--print", "after_move:filepath"]
    base += (["-x", "--audio-format", "m4a"] if audio_only
             else ["-f", "bv*+ba/b", "--merge-output-format", "mp4"])
    browser = os.environ.get("MDBROWSE_YTDLP_BROWSER", "")
    attempts = ([base + ["--cookies-from-browser", browser, u]] if browser else []) + [base + [u]]
    last = ""
    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return "download_video: timed out (600s) — try audio_only or a shorter clip"
        if r.returncode == 0:
            path = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
            size = os.path.getsize(path) / 1e6 if path and os.path.exists(path) else 0
            return f"downloaded: {path}\nsize: {size:.1f} MB"
        last = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        last = last[0]
    return f"download_video failed: {last[:200]}"


@mcp.tool()
def page_forms(url: str, private: bool = False) -> list:
    """List the fillable forms on a page — each form's method, action, submit-button
    label, and fields (name, type, placeholder, label, select options), plus loose
    search boxes not wrapped in a <form>. The OBSERVE step before submit_form: call this
    to learn the field names to fill.

    Note: site search often needs no form at all — a GET form just puts the query in the
    URL, so fetch_page("site.com/search?q=...") (with the field's real name) is simpler
    when the method is GET.
    """
    return _worker.list_forms(_normalize(url), private)


@mcp.tool()
def submit_form(url: str, fields: dict, submit: str = "", private: bool = False,
                wait_selector: str = "", max_chars: int = 80000) -> str:
    """Fill a form on `url` and return the RESULT page as clean markdown (same pipeline
    as fetch_page). `fields` maps each field's name / label / placeholder to a value,
    e.g. {"q": "wireless headphones"} or {"From": "SFO", "To": "JFK"}. `submit` is a
    button's visible text; if omitted, Enter is pressed in the last filled field (the
    search-box convention). Rides the user's session, so site search, filters, and
    logged-in forms work.

    Discover field names first with page_forms(url). This unlocks site search, faceted
    browsing, and any GET/POST/JS form. For a simple GET search, fetch_page with the
    query in the URL is lighter.
    """
    bundle = _worker.submit_form(_normalize(url), dict(fields or {}),
                                 submit or None, wait_selector or None, private)
    doc = emit(bundle, classify(bundle))
    if len(doc) > max_chars:
        doc = doc[:max_chars] + f"\n\n_[result truncated at {max_chars} chars]_\n"
    return doc


@mcp.tool()
def curate_to_corpus(url: str, corpus_root: str = "", private: bool = False) -> str:
    """Capture a page and FILE it into document-forge — the 'read it, keep it' bridge. The
    clean markdown (with provenance front-matter: source URL, retrieval time, content hash)
    lands as a searchable document in the corpus, so a page you read today is recallable
    later from your own substrate.

    corpus_root defaults to $MDBROWSE_CORPUS_ROOT or /mnt/herfjotur/work; the df CLI path is
    $MDBROWSE_DF or the notebook default. Use after fetch_page when a page is worth KEEPING,
    not just reading. For a linked file (PDF/dataset) use download_document instead.
    """
    import hashlib
    import os
    import re
    import subprocess
    import tempfile
    from urllib.parse import urlparse

    u = _normalize(url)
    bundle = _get_bundle(u, private)
    md = emit(bundle, classify(bundle))
    doc = bundle["doc"]
    title = (doc.get("title") or "").strip() or (urlparse(u).netloc or "page")
    h = hashlib.sha256(md.encode("utf-8")).hexdigest()[:6]
    stem = (re.sub(r"[^\w.\- ]+", "-", title)[:80].strip() or "page")
    stage = tempfile.mkdtemp(prefix="mdb-curate-")
    fpath = os.path.join(stage, f"{stem} [{h}].md")
    with open(fpath, "w") as f:
        f.write(md)

    df = os.path.expanduser(os.environ.get(
        "MDBROWSE_DF", "~/Desktop/notebook/code/forge/document-forge/df"))
    if not os.path.exists(df):
        return (f"wrote {fpath}\nbut document-forge CLI not found at {df} "
                f"(set $MDBROWSE_DF). Ingest it with: df ingest '{stage}'")
    root = corpus_root or os.environ.get("MDBROWSE_CORPUS_ROOT", "/mnt/herfjotur/work")
    env = dict(os.environ, DF_CORPUS_ROOT=root)
    try:
        r = subprocess.run([df, "ingest", stage], cwd=os.path.dirname(df), env=env,
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return f"curate timed out (300s); file staged at {fpath}"
    tail = " | ".join([x.strip() for x in (r.stdout + r.stderr).splitlines() if x.strip()][-3:])
    if r.returncode == 0:
        return f"curated '{title}' → {root} (document-forge)\n{tail}"
    return f"curate ingest rc={r.returncode}: {tail}\n(file staged at {fpath})"


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
    provenance front-matter (to the mdbrowse app-data archive, or
    $MDBROWSE_ARCHIVE).

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


def _in_thread(fn, *args, **kwargs):
    """Watch verbs that capture own their own sync-Playwright engines,
    and FastMCP executes tools on the asyncio loop, where sync
    Playwright refuses to run. Give them a plain thread (no running
    loop) and join. Found by the first live smoke test over the wire —
    the agent probes call these functions from a loop-free main thread,
    which is exactly why they passed while the transport failed."""
    import threading
    box = {}

    def work():
        try:
            box["v"] = fn(*args, **kwargs)
        except BaseException as e:      # SystemExit included
            box["e"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join()
    if "e" in box:
        e = box["e"]
        raise RuntimeError(str(e)) if isinstance(e, SystemExit) else e
    return box.get("v")


@mcp.tool()
def watch_add(url: str, name: str = "", private: bool = False) -> dict:
    """Start watching a URL for real content change. Takes the first
    snapshot now (git-committed to the watch store); later watch_scan
    calls fire only when visible text changes — link-token churn never
    false-fires. Name defaults to a slug of the URL.
    """
    from . import watch
    watch_name = _in_thread(watch.add, _normalize(url), name or None, private)
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
    return _in_thread(watch.scan_readings, names or None)


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
