"""Checkin gate — the suite every commit must pass.

Two phases. Phase 0 re-runs the offline fixture corpus (emit truths,
no network, always gates). Phase 1 sweeps a manifest of real sites,
each chosen because it stresses a different part of the pipeline, and
asserts *structural* expectations (shape, item counts, fences, tables)
rather than content — headlines change hourly; shapes don't.

    .venv/bin/python tests/checkin.py                 # full gate
    .venv/bin/python tests/checkin.py --offline-only  # fixtures only
    .venv/bin/python tests/checkin.py hn apple        # site filter
    .venv/bin/python tests/checkin.py --install-hook  # git pre-commit

Network policy: if the network itself is down, the live sweep is
SKIPPED with a loud warning and the gate passes on fixtures alone —
a checkin gate must not block commits on airplane wifi. When the
network is up, every site failure blocks, classified with the why
(dns / timeout / tls / shape / thin / assert), because "27/30 passed"
without the why is Level-1 telemetry.

Escape hatches: MDB_CHECKIN_SKIP_LIVE=1, or git commit --no-verify.
"""

import os
import re
import socket
import sys
import time

sys.path.insert(0, "src")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ---------------------------------------------------------------- manifest

# Each site earns its slot by stressing something the others don't.
SITES = [
    dict(name="hn", url="https://news.ycombinator.com",
         why="layout tables + repeated-unit detector",
         shape="feed", min_feed_items=20),
    dict(name="cnn", url="https://www.cnn.com",
         why="stretched-link cards + app-shell overlay kill",
         shape="feed", min_feed_items=15),
    dict(name="bbc", url="https://www.bbc.co.uk",
         why="index-card fragment merging, consent chrome",
         shape="feed", min_feed_items=10),
    dict(name="apple", url="https://www.apple.com",
         why="marketing page: lazy images, thin text, heavy nav",
         title_re=r"Apple", min_links=15, min_chars=400),
    dict(name="quantum", url="https://www.quantum.com",
         why="www-retry + the split-DNS afternoon (mdb doctor's origin)",
         title_re=r"(?i)quantum", min_chars=400, env_dns_warn=True),
    dict(name="wiki", url="https://en.wikipedia.org/wiki/Hacker_News",
         why="article shape: dense inline links, citations, infobox",
         shape="article", min_headings=3, min_chars=2000),
    dict(name="pydocs", url="https://docs.python.org/3/library/functools.html",
         why="code-fence fidelity (the line-doubling oracle finding)",
         shape="article", min_fences=4),
    dict(name="iana", url="https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml",
         why="pure data tables -> pipe tables",
         contains=["| --- |"], min_chars=2000),
    dict(name="github", url="https://github.com/anthropics/claude-code",
         why="SPA-ish repo page: README must outweigh the chrome",
         min_chars=1000, min_links=10),
    dict(name="xkcd", url="https://xkcd.com",
         why="RSS auto-discovery + comic image capture",
         has_feed=True, has_image=True),
    dict(name="search", url="https://www.mojeek.com/search?q=lto+tape+capacity",
         why="the search pipeline agents ride via search_web",
         min_links=5, min_chars=500),
]

DETERMINISM_URL = "https://example.com"   # captured twice; hashes must match


# ---------------------------------------------------------------- checks

def _classify_error(e: Exception) -> str:
    m = str(e).lower()
    if "resolve" in m or "dns" in m or "not known" in m:
        return "dns"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "ssl" in m or "tls" in m or "cert" in m:
        return "tls"
    return "error"


def _check_site(site: dict, bundle: dict, manifest, body: str) -> list:
    """Structural expectations -> list of failure strings (empty = pass)."""
    fails = []
    lines = body.splitlines()
    if "shape" in site and manifest.shape != site["shape"]:
        fails.append(f"shape: wanted {site['shape']}, got {manifest.shape} "
                     f"(conf {manifest.confidence})")
    if "min_chars" in site and len(body) < site["min_chars"]:
        fails.append(f"thin: {len(body)} chars < {site['min_chars']}")
    if "min_links" in site:
        n = body.count("](http")
        if n < site["min_links"]:
            fails.append(f"links: {n} < {site['min_links']}")
    if "min_feed_items" in site:
        n = sum(1 for l in lines if l.startswith("- ") and "](http" in l)
        if n < site["min_feed_items"]:
            fails.append(f"feed items: {n} < {site['min_feed_items']}")
    if "min_fences" in site and body.count("```") // 2 < site["min_fences"]:
        fails.append(f"code fences: {body.count('```') // 2} "
                     f"< {site['min_fences']}")
    if "min_headings" in site:
        n = sum(1 for l in lines if l.startswith("#"))
        if n < site["min_headings"]:
            fails.append(f"headings: {n} < {site['min_headings']}")
    for needle in site.get("contains", []):
        if needle not in body:
            fails.append(f"missing: {needle!r}")
    if "title_re" in site:
        title = bundle["doc"].get("title", "")
        if not re.search(site["title_re"], title):
            fails.append(f"title {title!r} !~ /{site['title_re']}/")
    if site.get("has_feed") and not bundle["doc"].get("feeds"):
        fails.append("no RSS feed discovered")
    if site.get("has_image"):
        if not any(b.get("images") or b.get("kind") == "img"
                   for b in bundle["doc"]["blocks"]):
            fails.append("no images captured")
    return fails


# ---------------------------------------------------------------- phases

def offline_gate() -> bool:
    from mdb.cli import selftest
    print("phase 0 — offline fixture corpus")
    return selftest() == 0


def _network_up() -> bool:
    try:
        socket.getaddrinfo("news.ycombinator.com", 443)
        return True
    except OSError:
        return False


def live_sweep(pick: list) -> bool:
    from mdb.bundle import content_hash
    from mdb.capture import Engine
    from mdb.classify import classify
    from mdb.emit import emit_body

    sites = [s for s in SITES if not pick or s["name"] in pick]
    print(f"\nphase 1 — live sweep ({len(sites)} sites"
          f"{' + determinism' if not pick else ''})")
    failures = 0
    with Engine() as eng:
        for site in sites:
            t0 = time.time()
            try:
                bundle = eng.capture(site["url"])
                manifest = classify(bundle)
                body = emit_body(bundle, manifest)
                fails = _check_site(site, bundle, manifest, body)
            except Exception as e:
                dt = time.time() - t0
                # A DNS black-hole on an env_dns_warn site is machine state
                # (GlobalProtect split-DNS holds quantum.com until reboot),
                # not a tool regression — warn, don't block the commit.
                if site.get("env_dns_warn") and _classify_error(e) == "dns":
                    print(f"  {site['name']:9} WARN [dns/env] "
                          f"{str(e)[:80]} ({dt:.1f}s) — mdb doctor "
                          f"{site['url'].split('/')[2]}")
                    continue
                failures += 1
                print(f"  {site['name']:9} FAIL [{_classify_error(e)}] "
                      f"{str(e)[:90]} ({dt:.1f}s)")
                continue
            dt = time.time() - t0
            slow = "  SLOW" if dt > 12 else ""
            if fails:
                failures += 1
                print(f"  {site['name']:9} FAIL shape={manifest.shape} "
                      f"({dt:.1f}s) — {'; '.join(fails)}")
            else:
                print(f"  {site['name']:9} ok   shape={manifest.shape} "
                      f"conf={manifest.confidence} "
                      f"{len(body) // 1000}k chars ({dt:.1f}s){slow}")

        if not pick:   # determinism rides the same warm engine
            hashes = [content_hash(emit_body(b, classify(b)))
                      for b in (eng.capture(DETERMINISM_URL),
                                eng.capture(DETERMINISM_URL))]
            if hashes[0] == hashes[1]:
                print(f"  determin. ok   {hashes[0]}")
            else:
                failures += 1
                print(f"  determin. FAIL hash drift: {hashes}")

    total = len(sites) + (0 if pick else 1)
    print(f"live sweep: {total - failures}/{total} passing")
    return failures == 0


HOOK = """#!/bin/sh
# mdb checkin gate — installed by: tests/checkin.py --install-hook
# Escapes: MDB_CHECKIN_SKIP_LIVE=1 git commit ... | git commit --no-verify
cd "$(git rev-parse --show-toplevel)" || exit 1
exec .venv/bin/python tests/checkin.py
"""


def install_hook() -> int:
    root = os.popen("git rev-parse --show-toplevel").read().strip()
    path = os.path.join(root, ".git", "hooks", "pre-commit")
    with open(path, "w") as f:
        f.write(HOOK)
    os.chmod(path, 0o755)
    print(f"installed {path}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--install-hook" in args:
        return install_hook()
    offline_only = "--offline-only" in args
    live_only = "--live-only" in args
    pick = [a for a in args if not a.startswith("--")]

    t0 = time.time()
    ok = True
    if not live_only:
        ok = offline_gate() and ok
    if not offline_only:
        if os.environ.get("MDB_CHECKIN_SKIP_LIVE"):
            print("\nphase 1 — SKIPPED (MDB_CHECKIN_SKIP_LIVE)")
        elif not _network_up():
            print("\nphase 1 — SKIPPED: network unavailable; gating on "
                  "fixtures alone. Run the live sweep when back online.")
        else:
            ok = live_sweep(pick) and ok
    print(f"\ncheckin gate: {'PASS' if ok else 'FAIL'} "
          f"({time.time() - t0:.0f}s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
