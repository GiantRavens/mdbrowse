"""Agent-action probes — the test suite for mdb as an LLM agent's web tool.

Each probe is one thing an agent session actually does through the MCP
surface (fetch a docs page, search, follow links, detect change), asserted
against the live web. Where live_probes.py guards infrastructure truths
(hostile CDNs, DNS), this suite guards *task* truths: "when I reach for
this instead of a generic web-fetch tool, does it give me something
strictly better?" Run manually (network-dependent by nature):

    .venv/bin/python tests/agent_probes.py            # all probes
    .venv/bin/python tests/agent_probes.py search     # substring filter

Probes call the MCP tool functions directly (FastMCP registers and returns
the plain function), so this exercises exactly what an agent session gets.
Add a probe whenever agent use teaches a lesson — the probe is the
lesson's regression guard.
"""

import re
import sys
import time

sys.path.insert(0, "src")

DOCS_URL = "https://docs.python.org/3/library/functools.html"
TABLE_URL = "https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml"
FEED_URL = "https://news.ycombinator.com"


def _tools():
    from mdb import mcp as m
    return m


def probe_docs_code_fidelity():
    """Agents read technical docs constantly; extractors usually mangle
    code blocks (line-doubling, dropped fences). A docs page must come
    back article-shaped with intact fenced code."""
    m = _tools()
    doc = m.fetch_page(DOCS_URL, max_chars=200000)
    assert 'shape: "article"' in doc, "docs page should classify as article"
    assert doc.count("```") >= 4, "expected multiple fenced code blocks"
    fence = doc.split("```")[1]
    assert "def factorial" in fence or "@cache" in fence, \
        "first code fence lost its code"
    return f"ok ({doc.count('```') // 2} fences)"


def probe_data_table():
    """Columnar data (registries, comparisons, specs) must keep its
    columns. A pure-table page comes back as pipe tables, not
    space-joined soup."""
    m = _tools()
    doc = m.fetch_page(TABLE_URL, max_chars=200000)
    assert "| --- |" in doc, "no pipe table emitted"
    assert "| 200 | OK |" in doc.replace("  ", " "), \
        "table row lost cell structure"
    return "ok (pipe table with header)"


def probe_search_results():
    """search_web replaces a generic WebSearch: results must be linked
    lines an agent can pick from and fetch."""
    m = _tools()
    doc = m.search_web("rust atomics ordering")
    links = doc.count("](http")
    assert links >= 5, f"only {links} result links"
    return f"ok ({links} linked results)"


def probe_feed_digest():
    """A news front should be a scannable digest: one linked line per
    story, not nav soup. This is the shape-awareness dividend."""
    m = _tools()
    doc = m.fetch_page(FEED_URL, max_chars=200000)
    assert 'shape: "feed"' in doc, "HN should classify as feed"
    items = [l for l in doc.splitlines()
             if l.startswith("- ") and "](http" in l]
    assert len(items) >= 20, f"only {len(items)} feed items"
    return f"ok ({len(items)} items)"


def probe_page_links_filter():
    """Navigation decisions need the link list, not the whole page; the
    pattern filter keeps the token cost proportional to the question."""
    m = _tools()
    links = m.page_links(FEED_URL, pattern=r"item\?id=")
    assert links, "no comment links found"
    assert all("item?id=" in l["href"] for l in links), "filter leaked"
    return f"ok ({len(links)} filtered links)"


def probe_pagination_stitches():
    """Long pages paginate via start_char; two slices must stitch to the
    single-call document (same capture served from cache)."""
    m = _tools()
    full = m.fetch_page(DOCS_URL, max_chars=400000)
    a = m.fetch_page(DOCS_URL, max_chars=3000)
    assert "start_char=3000" in a, "truncation note should name the next slice"
    b = m.fetch_page(DOCS_URL, max_chars=3000, start_char=3000)
    stitched = a.split("\n\n_[showing")[0] + b.split("\n\n_[showing")[0]
    assert stitched == full[:6000], "slices don't stitch to the document"
    return "ok (2 slices == prefix of full doc)"


def probe_hash_stability():
    """Change detection rests on the body hash: two fresh captures of a
    static page must hash identically (determinism is the contract)."""
    import re
    m = _tools()
    hashes = []
    for _ in range(2):
        with m._cache_lock:
            m._cache.clear()          # force a real re-capture
        doc = m.fetch_page("https://example.com")
        hashes.append(re.search(r'hash: "([0-9a-f]+)"', doc).group(1))
    assert hashes[0] == hashes[1], f"hash drift: {hashes}"
    return f"ok ({hashes[0]})"


def probe_watch_lifecycle():
    """Change detection is a first-class agent verb: add a watch, scan
    it (unchanged page reads 'ok'), read its listing, remove it — all
    against a scratch store, never the real one. The capturing verbs
    run INSIDE an asyncio loop, because that is where FastMCP executes
    tools and where sync Playwright refuses to run — the first wire
    smoke test failed exactly there while this probe passed."""
    import asyncio
    import shutil
    import tempfile
    from mdb import watch
    m = _tools()
    tmp = tempfile.mkdtemp(prefix="mdb-watch-probe-")
    real = watch.WATCH_DIR
    watch.WATCH_DIR = tmp

    def in_loop(fn, *a, **kw):
        async def call():
            return fn(*a, **kw)
        return asyncio.run(call())

    try:
        added = in_loop(m.watch_add, "https://example.com", name="probe")
        assert added["name"] == "probe" and tmp in added["snapshot"]
        names = [w["name"] for w in m.watch_list()]
        assert names == ["probe"], f"listing wrong: {names}"
        readings = in_loop(m.watch_scan, ["probe"])
        assert readings and readings[0]["status"] == "ok", \
            f"static page should scan ok: {readings}"
        patch = m.watch_diff("probe")
        assert "commit" in patch, "diff should show the add commit"
        m.watch_remove("probe")
        assert m.watch_list() == [], "remove left residue"
    finally:
        watch.WATCH_DIR = real
        shutil.rmtree(tmp, ignore_errors=True)
    return "ok (add/list/scan/diff/remove)"


def probe_archive_memory():
    """archive_page + archive_search = a personal web memory: what was
    archived must be findable by its words, with provenance intact."""
    import shutil
    import tempfile
    from mdb import archive
    m = _tools()
    tmp = tempfile.mkdtemp(prefix="mdb-archive-probe-")
    real = archive.ARCHIVE_DIR
    archive.ARCHIVE_DIR = tmp
    try:
        saved = m.archive_page("https://example.com")
        assert saved["path"].startswith(tmp)
        # Query with the page's own words (content-agnostic: example.com's
        # copy has changed under a hardcoded query before).
        with open(saved["path"], encoding="utf-8") as f:
            body = f.read().split("---\n", 2)[-1]
        words = [w for w in re.findall(r"[a-z]{7,}", body.lower())
                 if "http" not in w][:3]
        assert len(words) == 3, f"page too thin to derive a query: {words}"
        hits = m.archive_search(" ".join(words))
        assert hits, f"archived page not found by its own words {words}"
        assert hits[0]["source"].startswith("https://example.com")
        assert hits[0]["snippet"], "hit carries no snippet"
        assert m.archive_search("xyzzy-plugh-absent") == []
    finally:
        archive.ARCHIVE_DIR = real
        shutil.rmtree(tmp, ignore_errors=True)
    return "ok (archived page findable with provenance)"


def probe_failure_speed_and_why():
    """A dead hostname must fail fast with the reason, not hang an agent
    for a 30s browser timeout."""
    m = _tools()
    t0 = time.time()
    try:
        m.fetch_page("https://definitely-not-a-real-host-xyzzy.invalid")
    except Exception as e:
        dt = time.time() - t0
        msg = str(e).lower()
        assert dt < 8.0, f"took {dt:.1f}s to fail"
        assert "resolve" in msg or "dns" in msg or "not known" in msg, \
            f"failure lacks the why: {msg[:120]}"
        return f"ok (failed in {dt:.1f}s with reason)"
    raise AssertionError("nonexistent host did not raise")


PROBES = [probe_docs_code_fidelity,
          probe_data_table,
          probe_search_results,
          probe_feed_digest,
          probe_page_links_filter,
          probe_pagination_stitches,
          probe_hash_stability,
          probe_watch_lifecycle,
          probe_archive_memory,
          probe_failure_speed_and_why]

if __name__ == "__main__":
    pick = sys.argv[1] if len(sys.argv) > 1 else ""
    probes = [p for p in PROBES if pick in p.__name__]
    failures = 0
    for probe in probes:
        name = probe.__name__
        try:
            result = probe()
            print(f"  {name:32} {result}")
        except Exception as e:
            failures += 1
            print(f"  {name:32} FAIL: {type(e).__name__}: {str(e)[:120]}")
    print(f"agent probes: {len(probes) - failures}/{len(probes)} passing")
    sys.exit(1 if failures else 0)
