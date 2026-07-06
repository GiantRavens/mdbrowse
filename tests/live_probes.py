"""Live network probes — the test suite for truths that need the real web.

The fixture corpus (mdb --selftest) tests emit/classify OFFLINE and stays
deterministic. These probes test the parts that only fail against real
infrastructure: hostile CDNs, WAF tarpits, redirect chains. Run manually
(network-dependent by nature, so not part of selftest):

    .venv/bin/python tests/live_probes.py

Each probe records why it exists. Add one whenever the live web teaches
a lesson — the probe is the lesson's regression guard.
"""

import sys
import time

sys.path.insert(0, "src")


def probe_hostile_cdn_image_preview():
    """panerai.com (Richemont/luxury WAF) tarpits httpx's TLS fingerprint:
    image preview timed out for the captain (2026-07-05). The fix is the
    engine-fetch fallback — this probe fails if that chain regresses."""
    from mdb.capture import Engine
    from mdb.reader import _fetch_image
    import os

    with Engine() as eng:
        b = eng.capture("https://www.panerai.com")
        imgs = []
        for blk in b["doc"]["blocks"]:
            imgs += blk.get("images") or []
            if blk.get("kind") == "img" and blk.get("src"):
                imgs.append(blk["src"])
        imgs = [u for u in dict.fromkeys(imgs) if "panerai" in u]
        assert imgs, "no images captured from panerai.com"
        t0 = time.time()
        path, note = _fetch_image(imgs[0], referer="https://www.panerai.com/",
                                  engine=eng)
        dt = time.time() - t0
    assert path, f"preview fetch failed: {note}"
    size = os.path.getsize(path)
    os.unlink(path)
    assert size > 10_000, f"suspiciously small image ({size} bytes)"
    return f"ok ({note.strip()}, {dt:.1f}s)"


def probe_plain_image_httpx_path():
    """The fast path must stay fast: a friendly host serves via httpx
    directly (no engine involved), well under the 6s budget."""
    from mdb.reader import _fetch_image
    import os
    t0 = time.time()
    path, note = _fetch_image("https://picsum.photos/300/200")
    dt = time.time() - t0
    assert path, f"httpx image path failed: {note}"
    os.unlink(path)
    assert "via engine" not in note, "friendly host should not need the engine"
    assert dt < 6.0, f"fast path took {dt:.1f}s"
    return f"ok ({note.strip()}, {dt:.1f}s)"


def probe_dns_preflight_speed():
    """A resolvable host must preflight in well under a second — the 3s
    cap is for black holes, not the happy path."""
    from mdb.capture import _dns_preflight
    t0 = time.time()
    v = _dns_preflight("example.com")
    dt = time.time() - t0
    assert v == "ok" and dt < 1.0, f"verdict={v} in {dt:.2f}s"
    return f"ok ({dt:.2f}s)"


def probe_capture_watchdog():
    """page.evaluate has no timeout at any layer, and a wedged evaluate
    left the reader on a blank page forever (captain's report,
    2026-07-05: `mdb apple.com`, nondeterministic, fleet congestion).
    The in-engine watchdog must kill the browser past the deadline,
    raise a classified error, and leave the engine able to self-heal.
    Wedge is forced with an in-page infinite loop — deterministic, no
    network beyond the recovery fetch."""
    import time
    from mdb.capture import Engine

    with Engine(timeout=2) as eng:          # watchdog deadline = 17s
        t0 = time.time()
        try:
            eng.capture("data:text/html,<title>t</title><p>hello</p>"
                        "<script>setTimeout(()=>{for(;;);},800)</script>")
            raise AssertionError("wedged capture returned instead of raising")
        except RuntimeError as e:
            dt = time.time() - t0
            assert "watchdog" in str(e), f"unclassified: {e}"
            assert dt < 30, f"watchdog too slow: {dt:.1f}s"
        t0 = time.time()
        b = eng.capture("https://example.com")
        assert b["doc"]["blocks"], "engine did not self-heal after the kill"
        return f"ok (fired, classified, healed in {time.time() - t0:.1f}s)"


def probe_reader_link_following():
    """Click a few links, like a reader session — the test the captain
    asked for. It exists because the threaded-loader UX regression bound
    the engine to a fresh thread per nav; the SECOND link raised 'cannot
    switch to a different thread'. So: load a page, follow real links
    through the reader's own load path across several hops, and assert
    every hop returns a page (not an error). Uses the reader's engine
    executor exactly as the TUI does — the layer bare-Engine tests skip."""
    import re
    from concurrent.futures import ThreadPoolExecutor
    from mdb.reader import Reader

    r = Reader("https://www.starringthecomputer.com/computers.html")
    hops, followed = [], 0
    try:
        page = r._exec.submit(r.load, r.start_url).result()
        assert page.focusables, "start page had no links to follow"
        hops.append(page.url)
        # Follow up to 3 distinct in-site links, each through r.load —
        # the same call the reader makes, on the same engine thread.
        seen = {page.url}
        for f in page.focusables:
            if followed >= 3:
                break
            href = getattr(f, "href", "")
            if not href or href in seen or "starringthecomputer" not in href:
                continue
            seen.add(href)
            nxt = r._exec.submit(r.load, href).result()
            assert nxt.bundle is not None, f"link {href} yielded no bundle"
            assert "Couldn't load" not in nxt.body[:40], \
                f"link {href} errored: {nxt.body[:80]}"
            hops.append(nxt.url)
            followed += 1
        assert followed >= 2, f"only followed {followed} links (need >=2 to " \
            "exercise the cross-nav engine-thread reuse)"
    finally:
        try:
            r._exec.submit(r.engine.close).result(timeout=10)
        except Exception:
            pass
        r._exec.shutdown(wait=False)
    return f"ok ({followed} links followed, no thread error)"


PROBES = [probe_hostile_cdn_image_preview,
          probe_plain_image_httpx_path,
          probe_dns_preflight_speed,
          probe_capture_watchdog,
          probe_reader_link_following]

if __name__ == "__main__":
    failures = 0
    for probe in PROBES:
        name = probe.__name__
        try:
            result = probe()
            print(f"  {name:40} {result}")
        except Exception as e:
            failures += 1
            print(f"  {name:40} FAIL: {type(e).__name__}: {str(e)[:100]}")
    print(f"live probes: {len(PROBES) - failures}/{len(PROBES)} passing")
    sys.exit(1 if failures else 0)
