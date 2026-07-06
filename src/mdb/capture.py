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
import os
import re
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
# Desktop Safari on Mac — matches the Safari cookie jar we seed, so the
# projected identity stays consistent (see Engine desktop mode).
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
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
    if re.fullmatch(r"[\d.]+", host) or ":" in host:
        return None                     # www.192.168.1.7 is not a thing
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


def _descendant_browsers(root_pid: int) -> list:
    """PIDs of browser processes descended from root_pid (chromium via
    playwright's node driver). The watchdog's kill list: sync Playwright
    objects can't be touched from another thread, but the PROCESS can —
    killing the browser makes a wedged page.evaluate raise immediately."""
    import subprocess
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid=,comm="],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    children, comm = {}, {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            pid, ppid, name = parts
            children.setdefault(ppid, []).append(pid)
            comm[pid] = name
    found, stack = [], [str(root_pid)]
    while stack:
        for c in children.get(stack.pop(), []):
            stack.append(c)
            if "chrom" in comm.get(c, "").lower():
                found.append(int(c))
    return found


def _tcp_preflight(host: str, port: int, timeout: float = 2.0) -> bool:
    """Is this host reachable at all? A host is DEAD only when BOTH the
    requested port and its http/https sibling fail — the
    wallstreetjournal.com signature (every SYN dropped on 443 AND 80).
    An alive host connects in well under a second, so a single probe per
    port suffices; checking BOTH ports absorbs a transient lost SYN on
    one of them without a per-port retry that would drag a truly-dead
    host out to 16s. starringthecomputer.com (connects 0.2s, briefly
    flagged dead by a one-port 3s probe under load) now stays alive via
    its sibling port; wsj-apex still fails in ~6s, not a 30s hang."""
    import socket
    sibling = 80 if port == 443 else 443
    for p in (port, sibling):
        try:
            socket.create_connection((host, p), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


# A bot-verification interstitial (Cloudflare "Just a moment…",
# challenge iframes) — detected by the signatures these services leave:
# their challenge script/host, the running-challenge container, or the
# telltale title over an otherwise-empty body. Used to WAIT for the swap
# in settle and to CLASSIFY a stuck one as a wall.
_IS_CHALLENGE_JS = """
(() => {
  const t = (document.title || '').toLowerCase();
  if (t.includes('just a moment') || t.includes('attention required')
      || t.includes('verifying you are human')) return true;
  if (document.querySelector('#challenge-running, #cf-chl-widget,'
      + ' script[src*="challenges.cloudflare.com"], #challenge-stage,'
      + ' iframe[src*="challenges.cloudflare.com"]')) return true;
  return false;
})()
"""


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

    # Cloudflare / interstitial challenge: a "Just a moment…" page runs
    # JS, verifies, and swaps itself for the real content — often within
    # a few seconds even headless. Wait for that swap before doing
    # anything else, so we don't capture the interstitial. If it never
    # clears (hard bot-block), classify handles it as a wall downstream.
    try:
        if page.evaluate(_IS_CHALLENGE_JS):
            wait_end = time.monotonic() + min(left_ms() / 1000.0, 12.0)
            while time.monotonic() < wait_end:
                page.wait_for_timeout(500)
                if not page.evaluate(_IS_CHALLENGE_JS):
                    break
    except Exception:
        pass

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

    # Scroll nudge. Observe first: a page whose imagery is mostly
    # unmaterialized (many <img> with no rendered area — apple.com/iphone
    # holds 106 of 112 back for IntersectionObservers) needs a stepped
    # sweep so mid-page observers actually fire; a single bottom-jump
    # passes through too fast and lit only 6 of them. Everyone else
    # keeps the cheap jump — the sweep (~1.7s max) is paid only where
    # it buys pixels.
    try:
        lazy = page.evaluate(
            "(() => { const im = [...document.querySelectorAll('img')];"
            " if (im.length < 12) return false;"
            " const unsized = im.filter(i => {"
            "   const r = i.getBoundingClientRect();"
            "   return r.width * r.height <= 2500; }).length;"
            " return unsized / im.length > 0.5; })()")
    except Exception:
        lazy = False
    try:
        if lazy and left_ms() > 2500:
            steps = int(page.evaluate(
                "Math.min(12, Math.ceil(document.body.scrollHeight"
                " / Math.max(1, window.innerHeight)))"))
            for i in range(1, steps + 1):
                page.evaluate(f"window.scrollTo(0, {i} * window.innerHeight)")
                page.wait_for_timeout(140)
        else:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(120)
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    # Reveal collapsed content BEFORE the stability poll. Two safe,
    # bounded patterns — no arbitrary clicking:
    #   1. <details> disclosure (standard HTML) — just set .open.
    #   2. mobile Wikipedia (Minerva skin) lazy-loads section BODIES via
    #      API and only on toggle; under our iPhone UA a reference
    #      article renders ~1150 chars instead of ~7000. Click its
    #      section headings, which is the documented expand affordance.
    # Guarded to Minerva so no other site gets its headings clicked.
    try:
        expanded = page.evaluate(
            "(() => {"
            " let n = 0;"
            " for (const d of document.querySelectorAll('details:not([open])'))"
            "   { d.open = true; n++; }"
            " if (document.body.classList.contains('skin-minerva')"
            "     || document.querySelector('.mw-mf, .collapsible-heading')) {"
            "   for (const h of document.querySelectorAll("
            "       '.mw-heading, .collapsible-heading, .section-heading'))"
            "     { try { h.click(); n++; } catch (e) {} }"
            " }"
            " return n; })()")
        if expanded:
            # Minerva section bodies arrive over several async API loads;
            # wait for innerText to stop growing (up to 6s) so the poll
            # below doesn't snapshot a half-expanded article. This is why
            # the wiki row flapped article/feed at the prose-count edge.
            grow_end = time.monotonic() + min(left_ms() / 1000.0, 6.0)
            gprev = -1
            while time.monotonic() < grow_end:
                cur = text_len()
                if cur == gprev:
                    break
                gprev = cur
                page.wait_for_timeout(300)
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
                 block_images: bool = True, headed: bool = False,
                 desktop: bool = False):
        self._private = private
        self._timeout = timeout
        self._block_images = block_images
        self._headed = headed
        self._desktop = desktop
        self._pw = self._browser = self._context = None
        self._dns_verdicts = {}     # host -> ok|hang|fail, per session
        self._tcp_verdicts = {}     # (host, port) -> bool, per session
        self._resolver_rules = {}   # host -> ip, for --host-resolver-rules
        self._no_http2 = False      # sticky after an ERR_HTTP2_PROTOCOL_ERROR

    def _resolve_target(self, url: str) -> str:
        """Observe before navigating: a 3s resolver preflight instead of a
        silent 30s goto on a black-holed name. On a dead apex, jump straight
        to www. (no first-30s burn); on a resolver hang, fail immediately
        and say WHY. Also applies per-host URL rewrites (reddit →
        old.reddit) so the browser fetches the extractor-friendly host."""
        from .policy import rewrite_url
        url = rewrite_url(url)
        host = urlparse(url).hostname or ""
        if not host or "." not in host:
            return url
        verdict = self._dns_verdicts.get(host)
        if verdict is None:
            verdict = self._dns_verdicts[host] = _dns_preflight(host)
        if verdict == "ok":
            if self._tcp_ok(url, host):
                return url
            # Resolves, but nothing listens (wallstreetjournal.com DROPs
            # every SYN). A www sibling may be the live host; otherwise
            # fail in seconds with the why, not a 30s silent goto.
            alt = _www_variant(url)
            if alt:
                alt_host = urlparse(alt).hostname or ""
                av = self._dns_verdicts.get(alt_host)
                if av is None:
                    av = self._dns_verdicts[alt_host] = _dns_preflight(alt_host)
                if av == "ok" and self._tcp_ok(alt, alt_host):
                    return alt
            raise RuntimeError(
                f"'{host}' resolves but accepts no connections — DNS "
                "answers while every SYN to the service port is dropped, "
                "the signature of a dead-but-resolving host. The live "
                "site may answer on a different domain entirely (try a "
                f"web search for the site name). Diagnose: mdb doctor {host}")
        alt = _www_variant(url)
        if alt:
            alt_host = urlparse(alt).hostname or ""
            alt_verdict = self._dns_verdicts.get(alt_host)
            if alt_verdict is None:
                alt_verdict = self._dns_verdicts[alt_host] = _dns_preflight(alt_host)
            if alt_verdict == "ok":
                return alt
        if verdict == "hang":
            if self._dns_bypass(host):
                return url
            raise RuntimeError(
                f"system resolver black-holes '{host}' (lookup hangs, so the "
                f"browser would wait {int(self._timeout)}s in silence), and "
                "direct DNS has no answer either. Likely a split-DNS rule "
                "claiming this domain — e.g. a corporate VPN (GlobalProtect) "
                f"that isn't connected. Diagnose: mdb doctor {host}")
        raise RuntimeError(f"'{host}' does not resolve (and no www. variant does)")

    def _tcp_ok(self, url: str, host: str) -> bool:
        """Cached connect preflight on the URL's service port. Hosts we
        bypass via resolver rules are exempt — the system resolver would
        hang the very getaddrinfo this check rides on, and Chromium
        connects them by mapped IP anyway."""
        if host in self._resolver_rules:
            return True
        p = urlparse(url)
        port = p.port or (80 if p.scheme == "http" else 443)
        key = (host, port)
        v = self._tcp_verdicts.get(key)
        if v is None:
            v = self._tcp_verdicts[key] = _tcp_preflight(host, port)
        return v

    def _dns_bypass(self, host: str) -> bool:
        """The system resolver black-holed this host, but direct DNS may
        still answer — the split-DNS-with-tunnel-down state mdb doctor
        diagnoses. Chromium accepts explicit host->IP maps
        (--host-resolver-rules), so route around the damaged resolver
        instead of refusing: map the host (and its www/apex sibling,
        which a redirect would otherwise hang on), relaunch the engine
        with the rules, and say so. TLS is unaffected — the hostname
        still rides SNI and certificate checks; only resolution is ours."""
        from .doctor import _dig
        ips = _dig(host)
        if not ips:
            return False
        self._resolver_rules[host] = ips[0]
        self._dns_verdicts[host] = "ok"
        sib = host[4:] if host.startswith("www.") else "www." + host
        if sib not in self._resolver_rules:
            sips = _dig(sib)
            if sips:
                self._resolver_rules[sib] = sips[0]
                self._dns_verdicts[sib] = "ok"
        mapped = ", ".join(f"{h} → {ip}" for h, ip in
                           sorted(self._resolver_rules.items())
                           if h in (host, sib))
        print(f"mdb: system resolver black-holes '{host}'; routing around "
              f"it via direct DNS ({mapped}). The damage itself persists "
              f"machine-wide — see: mdb doctor {host}", file=sys.stderr)
        self._relaunch()
        return True

    def _relaunch(self) -> None:
        """Tear down browser+context (keeping Playwright itself) so the
        next _ensure() launches with the current resolver rules."""
        for attr in ("_context", "_browser"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._ensure()

    def _ensure(self) -> None:
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright
        if self._pw is None:
            self._pw = sync_playwright().start()
        args = []
        if self._resolver_rules:
            rules = ", ".join(f"MAP {h} {ip}" for h, ip
                              in sorted(self._resolver_rules.items()))
            args.append(f"--host-resolver-rules={rules}")
        if self._no_http2:
            args.append("--disable-http2")
        # Headed = a real browser window on a real GPU, wearing NO
        # costume: real Chrome channel when installed, native UA, no
        # device emulation, no stealth shim. Verification walls
        # (DataDome et al.) exist to catch identity contradictions —
        # headed mode's whole premise is having none. Headless keeps
        # the iPhone-Safari presentation (small pages, Safari cookies
        # read naturally) plus the shim that keeps it self-consistent.
        if self._headed:
            try:
                self._browser = self._pw.chromium.launch(
                    headless=False, channel="chrome", args=args)
            except Exception:
                self._browser = self._pw.chromium.launch(
                    headless=False, args=args)
            ctx_opts = {
                "java_script_enabled": True,
                "locale": "en-US",
                "extra_http_headers": _PRIVACY_HEADERS if self._private else {},
            }
            self._context = self._browser.new_context(**ctx_opts)
        elif self._desktop:
            # Desktop mode: a Mac-Safari UA + desktop viewport for sites
            # that serve a thin mobile page to a phone (policy.py's
            # DESKTOP_HOSTS — Wikipedia's Minerva collapse et al.). Same
            # Safari cookies, same stealth self-consistency, just not a
            # phone. The UA stays Safari so the cookie jar matches.
            self._browser = self._pw.chromium.launch(headless=True, args=args)
            ctx_opts = {
                "user_agent": DESKTOP_UA,
                "viewport": {"width": 1280, "height": 1600},
                "java_script_enabled": True,
                "locale": "en-US",
                "extra_http_headers": _PRIVACY_HEADERS if self._private else {},
            }
            self._context = self._browser.new_context(**ctx_opts)
            self._context.add_init_script(_STEALTH_INIT_JS)
        else:
            self._browser = self._pw.chromium.launch(headless=True, args=args)
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

    def capture(self, url: str, wait_selector: str = None,
                screenshot_path: str = None) -> dict:
        """Load one URL, settle, run the walker. Returns a capture bundle.
        screenshot_path additionally saves a full-page PNG — the fidelity
        oracle's evidence (pixels as judge, never as extractor).

        A watchdog rides every capture: page.evaluate has no timeout of
        its own, and a wedged evaluate (concurrent chromium fleets)
        would otherwise hang the CALLER forever — the reader sat on a
        blank page for exactly this. Sync Playwright objects are thread-
        bound, but processes aren't: past the deadline, the watchdog
        kills this process's descendant browsers, the blocked call
        raises, the engine resets, and the caller gets an error it can
        show instead of silence."""
        import threading

        # Reddit .json fast path: browser-free, structured, complete.
        # Runs before the engine even starts; falls through to the HTML
        # path (old.reddit via the rewrite in _resolve_target) when it
        # can't authenticate. Skipped for --headed and explicit waits.
        from .reddit import is_reddit, json_bundle
        if (not self._headed and not wait_selector and not screenshot_path
                and is_reddit(urlparse(url).hostname)):
            rb = json_bundle(url, private=self._private)
            if rb is not None:
                return rb

        self._ensure()
        url = self._resolve_target(url)
        page = self._context.new_page()
        budget_ms = int(self._timeout * 1000)
        wd_budget = self._timeout + 15          # page budget + settle slack
        wd_fired = threading.Event()

        def _wd_fire():
            wd_fired.set()
            for pid in _descendant_browsers(os.getpid()):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass

        wd = threading.Timer(wd_budget, _wd_fire)
        wd.daemon = True
        wd.start()
        t0 = time.monotonic()
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=budget_ms)
            except Exception as e:
                # Chromium's HTTP/2 parser is stricter than curl's; some
                # CDNs (adobe.com's) send frames it rejects with
                # ERR_HTTP2_PROTOCOL_ERROR even though the site is fine
                # over HTTP/1.1. Relaunch this engine with H2 disabled
                # (session-sticky) and retry — the DNS-bypass pattern
                # applied to the protocol layer.
                if "ERR_HTTP2_PROTOCOL_ERROR" in str(e) and not self._no_http2:
                    self._no_http2 = True
                    page.close()
                    self._relaunch()
                    page = self._context.new_page()
                    page.goto(url, wait_until="domcontentloaded",
                              timeout=budget_ms)
                else:
                    alt = _www_variant(url)   # backstop; preflight usually caught it
                    if not alt:
                        raise
                    page.goto(alt, wait_until="domcontentloaded",
                              timeout=budget_ms)
            _settle(page, budget_ms, wait_selector)
            from .policy import kill_selectors
            doc = page.evaluate(_walker_source(),
                                kill_selectors(urlparse(page.url).hostname))
            if screenshot_path:
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                except Exception:
                    page.screenshot(path=screenshot_path)
            return {
                "meta": {
                    "requested_url": url,
                    "url": doc.get("url") or page.url,
                    "fetched_at": datetime.datetime.now()
                        .astimezone().isoformat(timespec="seconds"),
                    "mode": "private" if self._private else "authenticated",
                    "extractor": EXTRACTOR_VERSION,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                    "policy_killed": doc.get("policyKilled", 0),
                },
                "doc": doc,
            }
        except Exception:
            if wd_fired.is_set():
                # The browser is dead by our own hand; reset so the next
                # capture relaunches clean, and say what happened.
                for attr in ("_context", "_browser"):
                    try:
                        obj = getattr(self, attr)
                        if obj is not None:
                            obj.close()
                    except Exception:
                        pass
                    setattr(self, attr, None)
                raise RuntimeError(
                    f"capture watchdog: page wedged past {int(wd_budget)}s; "
                    f"browser killed and engine reset — retry (cause is "
                    f"usually concurrent chromium fleets)")
            raise
        finally:
            wd.cancel()
            try:
                page.close()
            except Exception:
                pass

    def fetch_resource(self, url: str, timeout: float = 20.0):
        """Fetch a raw asset THROUGH the browser — its TLS fingerprint,
        HTTP/2 stack, and cookies. Hostile CDNs (luxury-brand WAFs) tarpit
        non-browser clients like httpx; a navigation to the asset URL is
        indistinguishable from the real thing. Returns (bytes, content_type).

        Navigations have resource_type 'document', so the context's
        image-blocking route does not apply here."""
        self._ensure()
        page = self._context.new_page()
        try:
            resp = page.goto(url, wait_until="commit",
                             timeout=int(timeout * 1000))
            if resp is None:
                raise RuntimeError("no response")
            return resp.body(), (resp.headers or {}).get("content-type", "")
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
        self._spawn()

    def _spawn(self):
        """(Re)create the worker thread with a FRESH queue and engine
        set. The queue rides as a thread argument, never read back off
        self — an abandoned wedged loop must not steal jobs from its
        replacement."""
        import queue
        import threading
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._loop, args=(self._q,),
                                        daemon=True)
        self._thread.start()

    def _loop(self, q):
        engines = {}
        while True:
            job = q.get()
            if job is None:
                for eng in engines.values():
                    eng.close()
                break
            url, private, wait, desktop, fut = job
            try:
                key = (private, desktop)     # one warm engine per identity
                eng = engines.get(key)
                if eng is None:
                    eng = engines[key] = Engine(private=private, desktop=desktop)
                fut.set_result(eng.capture(url, wait_selector=wait))
            except Exception as e:
                fut.set_exception(e)

    def capture(self, url: str, private: bool = False,
                wait: str = None, timeout: float = 90.0,
                desktop: bool = False) -> dict:
        from concurrent.futures import Future
        from concurrent.futures import TimeoutError as _FutTimeout
        fut = Future()
        self._q.put((url, private, wait, desktop, fut))
        try:
            return fut.result(timeout=timeout)
        except _FutTimeout:
            # Watchdog: page.evaluate has no timeout of its own, and a
            # wedged evaluate (concurrent chromium fleets) would other-
            # wise stall this worker forever — every later call timing
            # out against a thread that will never read the queue
            # again. Abandon it, spawn fresh. The stuck chromium may
            # linger until process exit; a leaked process is
            # recoverable, a wedged service is not.
            self._spawn()
            raise RuntimeError(
                f"capture wedged past {int(timeout)}s and the engine "
                f"worker was replaced — retry the fetch (cause is "
                f"usually concurrent chromium fleets)")

    def close(self):
        self._q.put(None)
        self._thread.join(timeout=10)


def wants_desktop(url: str) -> bool:
    from .policy import wants_desktop as _wd
    return _wd(urlparse(url).hostname or "")


def capture(url: str, private: bool = False, timeout: float = 30.0,
            wait_selector: str = None, headed: bool = False,
            desktop: bool = None) -> dict:
    """One-shot capture. Tries the engine daemon first (warm Chromium,
    sub-second; auto-spawned on first use) and falls back to a local
    engine when the daemon path is unavailable or disabled. Headed
    captures never ride the daemon — the window is the point.

    desktop=None auto-selects a desktop UA for hosts that serve thin
    mobile pages (policy.DESKTOP_HOSTS); pass True/False to force."""
    if desktop is None:
        desktop = wants_desktop(url)
    if not headed:
        from . import daemon
        bundle = daemon.capture_via_daemon(url, private, wait_selector, desktop)
        if bundle is not None:
            return bundle
    with Engine(private=private, timeout=timeout, headed=headed,
                desktop=desktop) as eng:
        return eng.capture(url, wait_selector=wait_selector)
