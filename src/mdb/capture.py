"""Capture stage: drive Chromium, wait for content, run the in-page walker.

Output is a *capture bundle* (dict, JSON-serializable): document meta plus a
flat list of leaf blocks with landmark/kind/inline-markdown/links/geometry.
page.content() is never taken — the serialized-HTML re-parsing path is the
architecture this rebuild retires.

Ported intact from legacy mdbrowse.py (they were the good parts): the
content-stability settle heuristic, the stealth shim, tracker blocking,
warm-session reuse, and the www. retry.
"""

import datetime
import sys
import time
from importlib import resources
from urllib.parse import urlparse, urlunparse

from . import EXTRACTOR_VERSION
from . import cookies as safari_cookies

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
_PRIVACY_HEADERS = {"DNT": "1", "Sec-GPC": "1"}

# Keep the projected identity internally consistent: hide the automation flag,
# report Safari's vendor, iPhone-like touch points. Each guard defensive.
_STEALTH_INIT_JS = """
try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch (e) {}
try { Object.defineProperty(navigator, 'vendor', {get: () => 'Apple Computer, Inc.'}); } catch (e) {}
try { Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5}); } catch (e) {}
"""

TRACKER_HOSTS = (
    "google-analytics.com", "googletagmanager.com", "doubleclick.net",
    "googlesyndication.com", "google-adservices", "adservice.google",
    "facebook.com/tr", "connect.facebook.net", "facebook.net",
    "analytics.tiktok", "ads-twitter", "static.ads-twitter",
    "scorecardresearch.com", "quantserve.com", "criteo",
    "amazon-adsystem.com", "adsystem", "adnxs.com", "rubiconproject",
    "pubmatic.com", "openx.net", "taboola.com", "outbrain.com",
    "hotjar.com", "mixpanel.com", "segment.com", "segment.io",
    "amplitude.com", "fullstory.com", "mouseflow.com", "clarity.ms",
    "newrelic.com", "nr-data.net", "sentry.io", "bugsnag",
    "branch.io", "appsflyer", "adjust.com", "bing.com/bat",
    "snowplow", "matomo", "piwik", "chartbeat", "parsely",
    "moatads", "adsrvr.org", "cookielaw.org", "onetrust",
)


def _walker_source() -> str:
    return resources.files("mdb").joinpath("walker.js").read_text(encoding="utf-8")


def _www_variant(url: str):
    p = urlparse(url)
    host = p.hostname or ""
    if not host or host.startswith("www.") or "." not in host:
        return None
    return urlunparse(p._replace(netloc="www." + p.netloc))


def _dns_preflight(host: str, timeout: float = 3.0) -> str:
    """'ok' | 'hang' | 'fail' — a threaded getaddrinfo with a hard cap.

    Chromium sits on the same system resolver, so a black-holed name would
    otherwise burn the full navigation budget in silence. A 'hang' means
    the resolver swallowed the query — the classic cause is a split-DNS
    rule (corporate VPN, e.g. GlobalProtect) claiming the domain for
    nameservers that are only reachable on-tunnel. Direct DNS (dig) still
    answers in that state, which is what makes it look so mysterious.
    """
    import socket
    import threading
    result = {}

    def work():
        try:
            socket.getaddrinfo(host, 443)
            result["v"] = "ok"
        except socket.gaierror:
            result["v"] = "fail"
        except Exception:
            result["v"] = "fail"

    # A daemon thread, NOT a ThreadPoolExecutor: pool threads are non-daemon
    # and a hung getaddrinfo would block interpreter exit for its full ~30s
    # — exactly the silence this preflight exists to eliminate.
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    return result.get("v", "hang")


def _should_block(req_url: str, resource_type: str) -> bool:
    if resource_type in ("media", "font"):
        return True
    return any(h in req_url.lower() for h in TRACKER_HOSTS)


def _settle(page, budget_ms: int, wait_selector: str = None) -> None:
    """Wait for the page to *paint its content*, not merely finish the network.

    1. explicit --wait selector, if given;
    2. else, if the page looks like an unhydrated SPA shell, wait for an
       <article> to attach;
    3. scroll nudge for lazy/IntersectionObserver content;
    4. DOM-text-stability poll — done once innerText stops growing.
    """
    deadline = time.monotonic() + budget_ms / 1000.0
    left_ms = lambda: max(0, int((deadline - time.monotonic()) * 1000))
    text_len = lambda: page.evaluate(
        "document.body ? document.body.innerText.length : 0")

    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, state="attached",
                                   timeout=min(left_ms(), 6000))
        except Exception:
            pass
    else:
        try:
            initial = text_len()
        except Exception:
            initial = 0
        if initial < 800:
            # A scriptless page cannot hydrate — the SPA-shell wait would be
            # 2.5s of provably pointless patience (example.com class).
            try:
                has_scripts = page.evaluate("document.scripts.length > 0")
            except Exception:
                has_scripts = True
            if has_scripts:
                try:
                    page.wait_for_selector("article, [role=article]",
                                           state="attached",
                                           timeout=min(left_ms(), 2500))
                except Exception:
                    pass

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(120)
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    poll_end = time.monotonic() + min(left_ms() / 1000.0, 4.0)
    prev, stable = -1, 0
    while stable < 2 and time.monotonic() < poll_end:
        try:
            cur = text_len()
        except Exception:
            break
        if cur > 0 and cur == prev:
            stable += 1
        else:
            stable, prev = 0, cur
        page.wait_for_timeout(150)


class Engine:
    """A warm browser reused across captures (first page pays the launch)."""

    def __init__(self, private: bool = False, timeout: float = 30.0,
                 block_images: bool = True):
        self._private = private
        self._timeout = timeout
        self._block_images = block_images
        self._pw = self._browser = self._context = None
        self._dns_verdicts = {}     # host -> ok|hang|fail, per session

    def _resolve_target(self, url: str) -> str:
        """Observe before navigating: a 3s resolver preflight instead of a
        silent 30s goto on a black-holed name. On a dead apex, jump straight
        to www. (no first-30s burn); on a resolver hang, fail immediately
        and say WHY."""
        host = urlparse(url).hostname or ""
        if not host or "." not in host:
            return url
        verdict = self._dns_verdicts.get(host)
        if verdict is None:
            verdict = self._dns_verdicts[host] = _dns_preflight(host)
        if verdict == "ok":
            return url
        alt = _www_variant(url)
        if alt:
            alt_host = urlparse(alt).hostname or ""
            alt_verdict = self._dns_verdicts.get(alt_host)
            if alt_verdict is None:
                alt_verdict = self._dns_verdicts[alt_host] = _dns_preflight(alt_host)
            if alt_verdict == "ok":
                return alt
        if verdict == "hang":
            raise RuntimeError(
                f"system resolver black-holes '{host}' (lookup hangs, so the "
                f"browser would wait {int(self._timeout)}s in silence). "
                "Likely a split-DNS rule claiming this domain — e.g. a "
                "corporate VPN (GlobalProtect) that isn't connected. Check: "
                f"scutil --dns | grep -A4 {host}")
        raise RuntimeError(f"'{host}' does not resolve (and no www. variant does)")

    def _ensure(self) -> None:
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        ctx_opts = {
            **self._pw.devices.get("iPhone 13", {}),
            "user_agent": IPHONE_UA,
            "java_script_enabled": True,
            "locale": "en-US",
            "extra_http_headers": _PRIVACY_HEADERS if self._private else {},
        }
        self._context = self._browser.new_context(**ctx_opts)
        self._context.add_init_script(_STEALTH_INIT_JS)
        if not self._private:
            try:
                self._context.add_cookies(safari_cookies.for_playwright())
            except Exception as e:
                print(f"mdb: could not seed Safari cookies: {e}", file=sys.stderr)

        def _route(route, request):
            rt = request.resource_type
            if self._block_images and rt == "image":
                return route.abort()
            if _should_block(request.url, rt):
                return route.abort()
            return route.continue_()

        self._context.route("**/*", _route)

    def capture(self, url: str, wait_selector: str = None) -> dict:
        """Load one URL, settle, run the walker. Returns a capture bundle."""
        self._ensure()
        url = self._resolve_target(url)
        page = self._context.new_page()
        budget_ms = int(self._timeout * 1000)
        t0 = time.monotonic()
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=budget_ms)
            except Exception:
                alt = _www_variant(url)  # backstop; preflight usually caught it
                if not alt:
                    raise
                page.goto(alt, wait_until="domcontentloaded", timeout=budget_ms)
            _settle(page, budget_ms, wait_selector)
            doc = page.evaluate(_walker_source())
            return {
                "meta": {
                    "requested_url": url,
                    "url": doc.get("url") or page.url,
                    "fetched_at": datetime.datetime.now()
                        .astimezone().isoformat(timespec="seconds"),
                    "mode": "private" if self._private else "authenticated",
                    "extractor": EXTRACTOR_VERSION,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                },
                "doc": doc,
            }
        finally:
            page.close()

    def close(self) -> None:
        for obj, meth in ((self._context, "close"), (self._browser, "close"),
                          (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, meth)()
                except Exception:
                    pass
        self._pw = self._browser = self._context = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class EngineWorker:
    """One thread owns all Playwright state; jobs arrive via a queue.

    Playwright's sync API is thread-bound, so callers that live in other
    threads (MCP tool pool, daemon accept loop) must not touch Engine
    objects directly. Holds one warm engine per privacy mode."""

    def __init__(self):
        import queue
        import threading
        self._q = queue.Queue()
        self._engines = {}
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            job = self._q.get()
            if job is None:
                for eng in self._engines.values():
                    eng.close()
                break
            url, private, wait, fut = job
            try:
                eng = self._engines.get(private)
                if eng is None:
                    eng = self._engines[private] = Engine(private=private)
                fut.set_result(eng.capture(url, wait_selector=wait))
            except Exception as e:
                fut.set_exception(e)

    def capture(self, url: str, private: bool = False,
                wait: str = None, timeout: float = 150.0) -> dict:
        from concurrent.futures import Future
        fut = Future()
        self._q.put((url, private, wait, fut))
        return fut.result(timeout=timeout)

    def close(self):
        self._q.put(None)
        self._thread.join(timeout=10)


def capture(url: str, private: bool = False, timeout: float = 30.0,
            wait_selector: str = None) -> dict:
    """One-shot capture. Tries the engine daemon first (warm Chromium,
    sub-second; auto-spawned on first use) and falls back to a local
    engine when the daemon path is unavailable or disabled."""
    from . import daemon
    bundle = daemon.capture_via_daemon(url, private, wait_selector)
    if bundle is not None:
        return bundle
    with Engine(private=private, timeout=timeout) as eng:
        return eng.capture(url, wait_selector=wait_selector)
