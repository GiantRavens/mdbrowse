#!/usr/bin/env python3
"""
mdbrowse — a private markdown web browser for your terminal.

Fetches a web page, strips out the cruft (ads, trackers, nav chrome),
converts what's left to clean Markdown, and renders it in the terminal.
Also previews local .md files (in the terminal, or as styled HTML in a browser).

- Pretends to be an iPhone (mobile pages are smaller & simpler).
- Sends no cookies and stores none. Each page load is a fresh, anonymous visit.
- Blocks known tracker/ad hosts.
- Static fetch by default (fast). Use --js for JavaScript-heavy / SPA pages
  (renders with a real headless browser engine, still cookie-free).
- --browse gives you w3m-style numbered link following, but usable.

Usage:
    mdbrowse                     # open your Safari homepage
    mdbrowse <url>               # render a web page
    mdbrowse notes.md            # preview a local markdown file
    mdbrowse notes.md --html     # ...as styled HTML in your browser
    mdbrowse --start             # Safari start page: home + bookmarks + reading list
    mdbrowse --bookmarks         # browse your Safari bookmarks
    mdbrowse --reading-list      # browse your Safari reading list
    mdbrowse <url> --js          # render JS-heavy pages (needs Playwright)
    mdbrowse <url> --raw         # print the markdown source instead
    mdbrowse <url> --browse      # interactive: follow numbered links
    mdbrowse <url> --full        # don't strip to "article", convert whole page

Examples:
    mdbrowse
    mdbrowse https://en.wikipedia.org/wiki/Markdown
    mdbrowse README.md --html
    mdbrowse example.com --browse
"""

import argparse
import html as ihtml
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import webbrowser
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Identity: look like a mobile Safari user, carry no state.
# ---------------------------------------------------------------------------
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
_BASE_HEADERS = {
    "User-Agent": IPHONE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# Privacy signals — sent only in --private mode. In default (authenticated)
# mode we look like an ordinary logged-in Safari, which is the point.
_PRIVACY_HEADERS = {
    "DNT": "1",
    "Sec-GPC": "1",  # Global Privacy Control: "do not sell/share"
}


def build_headers(private: bool) -> dict:
    h = dict(_BASE_HEADERS)
    if private:
        h.update(_PRIVACY_HEADERS)
    return h

# Substrings that, if present in a request URL, get blocked in --js mode.
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


def err(msg: str) -> None:
    print(f"mdbrowse: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Safari cookies — be *yourself* by default (OSINT / logged-in pages).
# `--private` opts out: no cookies, plus DNT/Sec-GPC, the old anonymous mode.
# ---------------------------------------------------------------------------
import struct
import time

# Cookies live in the sandboxed container on modern macOS; the pre-Catalina
# location is kept as a fallback.
_COOKIE_PATHS = (
    "~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
    "~/Library/Cookies/Cookies.binarycookies",
)
_MAC_EPOCH_OFFSET = 978307200  # seconds between 1970-01-01 and 2001-01-01
_cookie_cache = None           # parsed once per process


def _safari_cookie_path():
    for p in _COOKIE_PATHS:
        full = os.path.expanduser(p)
        if os.path.isfile(full):
            return full
    return None


def _parse_binarycookies(path: str):
    """Parse Safari's Cookies.binarycookies. Hybrid-endian: the page table is
    big-endian, cookie records inside each page are little-endian."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"cook":
        return []
    n_pages = struct.unpack(">I", data[4:8])[0]
    page_sizes = struct.unpack(">" + "I" * n_pages, data[8:8 + 4 * n_pages])
    pos = 8 + 4 * n_pages
    out = []
    for size in page_sizes:
        page = data[pos:pos + size]
        pos += size
        try:
            n_cookies = struct.unpack("<I", page[4:8])[0]
            offsets = struct.unpack("<" + "I" * n_cookies, page[8:8 + 4 * n_cookies])
        except struct.error:
            continue
        for off in offsets:
            try:
                c = page[off:]
                csize = struct.unpack("<I", c[0:4])[0]
                c = c[:csize]
                flags = struct.unpack("<I", c[8:12])[0]
                uo, no, po, vo = struct.unpack("<IIII", c[16:32])
                expiry = struct.unpack("<d", c[40:48])[0] + _MAC_EPOCH_OFFSET

                def _s(o):
                    end = c.find(b"\x00", o)
                    return c[o:(end if end != -1 else len(c))].decode("utf-8", "replace")

                dom = _s(uo)
                if not dom:
                    continue
                out.append({
                    "domain": dom, "name": _s(no), "path": _s(po) or "/",
                    "value": _s(vo), "secure": bool(flags & 1),
                    "httponly": bool(flags & 4), "expires": expiry,
                })
            except (struct.error, IndexError):
                continue
    return out


def load_safari_cookies():
    """All non-expired Safari cookies, parsed once. [] if unreadable."""
    global _cookie_cache
    if _cookie_cache is not None:
        return _cookie_cache
    path = _safari_cookie_path()
    if not path:
        _cookie_cache = []
        return _cookie_cache
    try:
        cookies = _parse_binarycookies(path)
    except (PermissionError, OSError):
        err("can't read Safari cookies (grant the terminal Full Disk Access, "
            "or use --private). Continuing without cookies.")
        cookies = []
    now = time.time()
    _cookie_cache = [c for c in cookies if not c["expires"] or c["expires"] > now]
    return _cookie_cache


def httpx_cookie_jar(cookies):
    """Build an httpx.Cookies jar with proper domain/path scoping, so the right
    cookies are sent per host even across redirects."""
    import httpx
    jar = httpx.Cookies()
    for c in cookies:
        try:
            jar.jar.set_cookie(_to_cookielib(c))
        except Exception:
            pass
    return jar


def _to_cookielib(c):
    """Convert a parsed cookie dict to a http.cookiejar.Cookie."""
    from http.cookiejar import Cookie
    dom = c["domain"]
    domain_specified = dom.startswith(".")
    return Cookie(
        version=0, name=c["name"], value=c["value"],
        port=None, port_specified=False,
        domain=dom, domain_specified=domain_specified,
        domain_initial_dot=domain_specified,
        path=c["path"], path_specified=True,
        secure=c["secure"], expires=int(c["expires"]) if c["expires"] else None,
        discard=False, comment=None, comment_url=None,
        rest={"HttpOnly": ""} if c["httponly"] else {},
    )


def playwright_cookies(cookies):
    """Shape parsed cookies for Playwright's context.add_cookies()."""
    out = []
    for c in cookies:
        out.append({
            "name": c["name"], "value": c["value"], "domain": c["domain"],
            "path": c["path"], "secure": c["secure"], "httpOnly": c["httponly"],
            "expires": int(c["expires"]) if c["expires"] else -1,
        })
    return out


def normalize_url(url: str) -> str:
    if url.startswith("safari:"):
        return url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_static(url: str, timeout: float = 20.0, private: bool = False) -> str:
    """Plain HTTP GET with a mobile identity. Sends Safari cookies unless private."""
    import httpx

    cookies = None if private else httpx_cookie_jar(load_safari_cookies())
    with httpx.Client(
        headers=build_headers(private),
        follow_redirects=True,
        timeout=timeout,
        cookies=cookies,
    ) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def fetch_js(url: str, timeout: float = 30.0, private: bool = False) -> str:
    """Render with a real (headless) browser engine, blocking trackers.

    Default: seed the context with your Safari cookies (logged-in browsing).
    --private: a fresh, isolated context => no cookies/storage, anonymous.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        err("--js needs Playwright. Install it:")
        err("    pip install playwright && playwright install chromium")
        sys.exit(2)

    def should_block(req_url: str, resource_type: str) -> bool:
        if resource_type in ("image", "media", "font"):
            return True  # we only want text -> faster, lighter
        low = req_url.lower()
        return any(h in low for h in TRACKER_HOSTS)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            device = p.devices.get("iPhone 13", {})
            context = browser.new_context(
                **device,
                user_agent=IPHONE_UA,
                java_script_enabled=True,
                locale="en-US",
                extra_http_headers=_PRIVACY_HEADERS if private else {},
            )
            if not private:
                try:
                    context.add_cookies(playwright_cookies(load_safari_cookies()))
                except Exception as e:
                    err(f"could not seed Safari cookies into the browser: {e}")
            context.route(
                "**/*",
                lambda route, request: (
                    route.abort()
                    if should_block(request.url, request.resource_type)
                    else route.continue_()
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # some pages never go idle; we have enough
            html = page.content()
            return html
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# HTML -> Markdown
# ---------------------------------------------------------------------------
def _clean_md(md: str) -> str:
    md = re.sub(r"(?<=\S)[ \t]{2,}", " ", md)  # collapse runs of spaces
    md = re.sub(r"[ \t]+\n", "\n", md)        # trailing whitespace
    md = re.sub(r"\n{3,}", "\n\n", md)        # collapse blank runs
    return md.strip()


def _strip_css(s: str) -> str:
    """Remove leaked inline CSS (e.g. '.css-1ab2{display:flex}', @media {...}).

    Linear, bounded patterns only — no nested quantifiers (which backtrack
    catastrophically on large pages).
    """
    # a selector run + a declaration block, removed only if it looks like CSS
    s = re.sub(
        r"[^\n{}]{0,200}\{[^{}]{0,4000}\}",
        lambda m: "" if ":" in m.group(0) and (";" in m.group(0)
                                               or "}" in m.group(0)) else m.group(0),
        s,
    )
    s = re.sub(r"[{}]", "", s)                              # stray braces
    return s


def _strip_noise(html: str) -> str:
    """Drop <head>, scripts, styles, and other non-content before conversion."""
    html = re.sub(r"(?is)<head\b.*?</head>", "", html)
    html = re.sub(r"(?is)<(script|style|noscript|template|svg)\b.*?</\1>", "", html)
    return html


def _linearize_tables(html: str) -> str:
    """Most sites (Hacker News, old forums) lay out content in nested tables.
    Markdown converters turn that into a mangled grid. Unwrap layout tables so
    each row becomes its own line instead."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "head", "noscript", "svg",
                   "form", "input", "button"]):
        t.decompose()
    for tr in soup.find_all("tr"):
        tr.insert_after(soup.new_string("\n"))   # break between rows
    for a in soup.find_all("a"):                 # keep adjacent links apart
        a.insert_before(" ")
        a.insert_after(" ")
    for tag in soup.find_all(["table", "tbody", "thead", "tfoot", "tr", "td", "th"]):
        tag.unwrap()                              # drop the grid, keep contents
    return str(soup)


def _absolutize(md: str, base_url: str) -> str:
    if not base_url or base_url.startswith(("file://", "safari:")):
        return md
    return re.sub(
        r"\]\((\S+?)\)",
        lambda m: "](" + urljoin(base_url, m.group(1).strip("<>")) + ")",
        md,
    )


def _visible_len(line: str) -> int:
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)   # link -> its text
    t = re.sub(r"[#>*`|_~-]", "", t)
    return len(t.strip())


_FOOTER_WORDS = re.compile(
    r"\b(guidelines|faq|privacy|terms|legal|contact|copyright|©|rss|"
    r"about us|careers|cookie|sitemap|subscribe|advertise|imprint)\b", re.I)


def _reorder_for_reading(md: str) -> str:
    """Put the main body first, then the leading menu, then the trailing footer.

    The body is delimited by the page's list items / headings. Whatever sits
    *before* the first one is the top menu; whatever sits *after* the last one
    (a story's own subtext aside) is the footer. We move the menu below the body
    so you read content first, then menu, then footer.
    """
    lines = md.split("\n")
    idx = [k for k, l in enumerate(lines)
           if re.match(r"^\s*\d+\.", l) or l.strip().startswith("#")]
    if not idx:
        return md  # no clear content spine -> leave as-is

    first, last = idx[0], idx[-1]
    end = last + 1
    while end < len(lines) and not lines[end].strip():
        end += 1
    # keep one trailing content line with the body (e.g. a story's subtext),
    # unless it already looks like footer link-farm text.
    if (end < len(lines) and _visible_len(lines[end]) > 45
            and not _FOOTER_WORDS.search(lines[end])):
        end += 1

    menu = [l for l in lines[:first] if l.strip()]
    body = "\n".join(lines[first:end]).strip()
    footer = [l for l in lines[end:] if l.strip()]
    if not menu and not footer:
        return md

    out = [body]
    if menu:
        out += ["", "---", "", "## ⋯ menu", "", "\n".join(menu)]
    if footer:
        out += ["", "---", "", "## ⋯ footer", "", "\n".join(footer)]
    return "\n".join(out)


def _full_markdown(html: str, base_url: str = "", reorder: bool = True) -> str:
    """Convert the whole document to markdown, keeping all links."""
    html = _strip_noise(html)
    html = _linearize_tables(html)
    try:
        from markdownify import markdownify as mdify
        md = mdify(html, heading_style="ATX", strip=["script", "style", "img"])
    except ImportError:
        md = re.sub(r"(?s)<[^>]+>", "", html)
    md = _clean_md(_absolutize(_strip_css(md), base_url))
    return _reorder_for_reading(md) if reorder else md


def to_markdown(html: str, url: str, full: bool = False, for_browse: bool = False) -> str:
    """HTML -> Markdown.

    Reading mode: trafilatura gives clean article prose (and keeps inline links
    on real article pages). For link-heavy index/listing pages (where readability
    extraction throws the links away), or when prose is too thin, fall back to a
    whole-page conversion so navigation still works.
    """
    if full:
        return _full_markdown(html, url, reorder=False)

    import trafilatura

    md = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_images=False,
        include_tables=True,
        favor_recall=True,
    )
    md = (md or "").strip()
    traf_links = len(LINK_RE.findall(md))
    good_prose = len(md) >= 200
    # An index/listing page: lots of anchors in the HTML, but the article
    # extractor found almost no inline links (it threw the navigation away).
    html_anchors = len(re.findall(r"<a[\s>]", html))
    index_like = html_anchors >= 30 and traf_links <= 5

    if good_prose and not index_like and (traf_links >= 5 or not for_browse):
        return _clean_md(md)

    # Index page or thin extraction -> linearized whole-page (links included).
    full_md = _full_markdown(html, url)
    return full_md if full_md.strip() else _clean_md(md)


# ---------------------------------------------------------------------------
# Link handling for browse mode
# ---------------------------------------------------------------------------
LINK_RE = re.compile(r"\[([^\]]+)\]\((\S+?)\)")


LINK_START = "\x01"   # invisible markers delimiting an actual link's extent
LINK_END = "\x02"


def extract_and_number_links(md: str, base_url: str, mark: bool = False):
    """Replace [text](url) with 'text [N]' and return (new_md, [urls]).

    With mark=True, wrap each link in invisible LINK_START/LINK_END sentinels so
    the renderer can bold/select exactly the link text (used by the vim reader).
    """
    links = []

    def repl(m):
        text, href = m.group(1), m.group(2)
        href = href.split(" ")[0].strip("<>")
        abs_url = urljoin(base_url, href)
        if not abs_url.startswith(("http://", "https://")):
            return text  # mailto:, javascript:, anchors -> just text
        links.append(abs_url)
        piece = f"{text} [{len(links)}]"
        return f"{LINK_START}{piece}{LINK_END}" if mark else piece

    return LINK_RE.sub(repl, md), links


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render(md: str, url: str, width: int, use_pager: bool, links=None) -> None:
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.rule import Rule
    except ImportError:
        # No rich -> just dump it.
        print(md)
        return

    console = Console(width=width if width else None)
    host = urlparse(url).netloc
    body = Markdown(md, hyperlinks=False)

    def _emit(c):
        c.print(Rule(f"[bold cyan]{host}[/]  [dim]{url}[/]"))
        c.print(body)
        if links:
            c.print(Rule("[dim]links[/]"))
            for i, u in enumerate(links, 1):
                c.print(f"[cyan]{i:>3}[/] [dim]{u}[/]")

    if use_pager and console.is_terminal:
        with console.pager(styles=True):
            _emit(console)
    else:
        _emit(console)


# ---------------------------------------------------------------------------
# Safari: piggyback on the user's homepage, bookmarks, and reading list.
# ---------------------------------------------------------------------------
SAFARI_BOOKMARKS = os.path.expanduser("~/Library/Safari/Bookmarks.plist")
_SKIP_FOLDER_TITLES = {"BookmarksBar", "BookmarksMenu", "com.apple.ReadingList"}


def _safari_default(key: str):
    try:
        r = subprocess.run(
            ["defaults", "read", "com.apple.Safari", key],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _walk_bookmarks(node, folder, out, reading):
    t = node.get("WebBookmarkType")
    if t == "WebBookmarkTypeLeaf":
        url = node.get("URLString", "")
        title = (node.get("URIDictionary") or {}).get("title") or url
        (reading if "ReadingList" in node else out).append((folder, title, url))
        return
    # WebBookmarkTypeList (folder) or the proxy root
    title = node.get("Title", "")
    nxt = folder
    if title and title not in _SKIP_FOLDER_TITLES:
        nxt = f"{folder} / {title}" if folder else title
    for child in node.get("Children", []) or []:
        _walk_bookmarks(child, nxt, out, reading)


def read_safari_bookmarks():
    """Return (bookmarks, reading_list) as lists of (folder, title, url)."""
    with open(SAFARI_BOOKMARKS, "rb") as f:
        data = plistlib.load(f)
    out, reading = [], []
    for child in data.get("Children", []) or []:
        _walk_bookmarks(child, "", out, reading)
    return out, reading


def _md_list(items):
    lines = []
    for folder, title, url in items:
        if not url:
            continue
        label = f"{folder} / {title}" if folder else title
        lines.append(f"- [{label}]({url})")
    return lines


def safari_page(pseudo_url: str) -> str:
    """Render a 'safari:...' pseudo-page from local Safari data."""
    kind = pseudo_url.split(":", 1)[1] or "start"
    try:
        bookmarks, reading = read_safari_bookmarks()
    except FileNotFoundError:
        return ("# Safari\n\nNo Safari bookmarks found at "
                f"`{SAFARI_BOOKMARKS}`.")
    except PermissionError:
        return (
            "# Safari — permission needed\n\n"
            "macOS protects Safari's data. Give your terminal **Full Disk "
            "Access**:\n\n"
            "1. System Settings -> Privacy & Security -> **Full Disk Access**\n"
            "2. Enable your terminal app (Terminal, iTerm, etc.)\n"
            "3. Quit and reopen the terminal, then try again."
        )

    if kind == "reading":
        body = _md_list(reading) or ["_(reading list is empty)_"]
        return "# Safari Reading List\n\n" + "\n".join(body)
    if kind == "bookmarks":
        body = _md_list(bookmarks) or ["_(no bookmarks)_"]
        return "# Safari Bookmarks\n\n" + "\n".join(body)

    # start page
    home = _safari_default("HomePage")
    lines = ["# Safari", ""]
    if home:
        lines += ["## Homepage", "", f"- [{home}]({home})", ""]
    if reading:
        lines += ["## Reading List", ""] + _md_list(reading) + [""]
    lines += ["## Bookmarks", ""] + (_md_list(bookmarks) or ["_(none)_"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Local files (.md / .html) and target resolution
# ---------------------------------------------------------------------------
def resolve_target(s: str) -> str:
    """Decide whether a target is a Safari pseudo-url, a local file, or a URL."""
    if s.startswith(("safari:", "file://")):
        return s
    cand = os.path.expanduser(s)
    if os.path.isfile(cand):
        return "file://" + os.path.abspath(cand)
    return normalize_url(s)


def read_local(path: str, full: bool, for_browse: bool) -> str:
    """Read a local file. Markdown/text returns as-is; HTML is converted."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if os.path.splitext(path)[1].lower() in (".html", ".htm"):
        return to_markdown(text, "file://" + path, full=full, for_browse=for_browse)
    return text  # already markdown / plain text


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ max-width: 46rem; margin: 3rem auto; padding: 0 1.25rem;
         font: 17px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         color: #1a1a1a; background: #fff; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e6e6e6; background: #161616; }}
    a {{ color: #6cb6ff; }} code, pre {{ background: #222; }}
    blockquote {{ color: #aaa; border-color: #444; }}
  }}
  h1,h2,h3 {{ line-height: 1.25; }} h1 {{ font-size: 1.9rem; }}
  a {{ color: #0a58ca; }}
  code {{ background: #f2f2f2; padding: .15em .35em; border-radius: 4px;
         font-size: .9em; }}
  pre {{ background: #f2f2f2; padding: 1rem; border-radius: 8px; overflow:auto; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ margin: 1rem 0; padding: .2rem 1rem; color: #555;
               border-left: 4px solid #ddd; }}
  img {{ max-width: 100%; }} table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #ccc; padding: .4rem .6rem; }}
</style></head>
<body>
{body}
</body></html>
"""


def markdown_to_html(md: str, title: str) -> str:
    try:
        import markdown as mdlib
        body = mdlib.markdown(
            md, extensions=["extra", "sane_lists", "toc", "nl2br"]
        )
    except ImportError:
        body = "<pre>" + ihtml.escape(md) + "</pre>"
    return HTML_TEMPLATE.format(title=ihtml.escape(title or "preview"), body=body)


def open_html_preview(md: str, title: str) -> str:
    """Write a styled HTML render to a temp file and open it in the browser."""
    fd, path = tempfile.mkstemp(suffix=".html", prefix="mdbrowse_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(markdown_to_html(md, title))
    webbrowser.open("file://" + path)
    return path


# ---------------------------------------------------------------------------
# Load one page end to end
# ---------------------------------------------------------------------------
def load(url: str, js: bool, full: bool, for_browse: bool = False,
         private: bool = False):
    if url.startswith("safari:"):
        return safari_page(url)
    if url.startswith("file://"):
        return read_local(url[len("file://"):], full, for_browse)
    html = fetch_js(url, private=private) if js else fetch_static(url, private=private)
    return to_markdown(html, url, full=full, for_browse=for_browse)


# ---------------------------------------------------------------------------
# Browse dispatcher: vim-style curses reader when possible, prompt otherwise.
# ---------------------------------------------------------------------------
def browse(url: str, js: bool, full: bool, width: int, simple: bool = False,
           private: bool = False) -> None:
    if not simple and sys.stdout.isatty() and sys.stdin.isatty():
        try:
            import curses  # noqa: F401
            return vim_browse(url, js, full, private)
        except Exception as e:
            err(f"vim mode unavailable ({e}); falling back to simple mode")
    browse_simple(url, js, full, width, private)


# ---------------------------------------------------------------------------
# Simple prompt loop (fallback / --simple / piped input)
# ---------------------------------------------------------------------------
def browse_simple(url: str, js: bool, full: bool, width: int,
                  private: bool = False) -> None:
    history = []
    current = url
    while True:
        try:
            md = load(current, js, full, for_browse=True, private=private)
        except Exception as e:
            err(f"could not load {current}: {e}")
            if not history:
                return
            current = history.pop()
            continue

        numbered_md, links = extract_and_number_links(md, current)
        render(numbered_md, current, width, use_pager=False, links=links)

        print()
        prompt = "→ number to follow · (b)ack · (u)rl · (q)uit: "
        try:
            choice = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if choice in ("q", "quit", ""):
            return
        if choice in ("b", "back"):
            if history:
                current = history.pop()
            else:
                err("no history")
            continue
        if choice in ("u", "url"):
            try:
                new = input("url: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if new:
                history.append(current)
                current = resolve_target(new)
            continue
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(links):
                history.append(current)
                current = links[idx]
            else:
                err(f"no link [{choice}]")
            continue
        # treat anything else as a URL or local path
        history.append(current)
        current = resolve_target(choice)


# ---------------------------------------------------------------------------
# Vim-style curses reader
# ---------------------------------------------------------------------------
def _normalize_paragraphs(md: str) -> str:
    """Join hard-wrapped lines inside a paragraph into one. Separate blocks by a
    blank line, but keep consecutive list items tight (no blank line between)."""
    def is_list(s):
        return bool(re.match(r"^[-*+]\s", s) or re.match(r"^\d+\.", s))

    blocks, buf = [], []  # blocks: (kind, text); kind in {para, block, list}

    def flush():
        if buf:
            blocks.append(("para", " ".join(x.strip() for x in buf)))
            buf.clear()

    for line in md.split("\n"):
        s = line.strip()
        if not s:
            flush()
        elif s.startswith(("#", ">", "---", "|", "```")):
            flush()
            blocks.append(("block", line.rstrip()))
        elif is_list(s):
            flush()
            blocks.append(("list", line.rstrip()))
        else:
            buf.append(line)
    flush()

    out = []
    for i, (kind, text) in enumerate(blocks):
        if not text.strip():
            continue
        if i:
            prev = blocks[i - 1][0]
            out.append("\n" if kind == "list" and prev == "list" else "\n\n")
        out.append(text)
    return "".join(out)


def _layout(md: str, width: int):
    """Turn numbered markdown into display lines + a map of link# -> line#.

    Light markdown cleanup (drop #, *, `, >) for terminal readability while
    keeping the '[N]' link markers that drive navigation.
    """
    import textwrap

    md = _normalize_paragraphs(md)
    lines, link_line, styles = [], {}, []  # styles: 'h'eading, 'q'uote, ''
    for raw in md.split("\n"):
        s = raw.rstrip()
        kind = ""
        if s.lstrip().startswith("#"):
            s = s.lstrip("#").strip()
            kind = "h"
        elif s.lstrip().startswith(">"):
            s = s.lstrip()[1:].strip()
            kind = "q"
        s = re.sub(r"\*\*|__|`", "", s)          # bold/italic/code marks
        if not s.strip():
            lines.append(""); styles.append(""); continue
        indent = "  " if re.match(r"^\s*[-*]\s", raw) else ""
        # keep each link on one line: shield its inner spaces from the wrapper
        protected = re.sub(r"\x01.*?\x02",
                           lambda m: m.group(0).replace(" ", "\x00"), s)
        wrapped = textwrap.wrap(protected, max(20, width - 1),
                                subsequent_indent=indent,
                                break_long_words=False,
                                break_on_hyphens=False) or [protected]
        for w in wrapped:
            lines.append(w.replace("\x00", " ")); styles.append(kind)
    # map each link number to the first line that shows its [N] marker
    for ln, text in enumerate(lines):
        for m in re.findall(r"\[(\d+)\]", text):
            link_line.setdefault(int(m), ln)
    return lines, styles, link_line


def vim_browse(start_url: str, js: bool, full: bool, private: bool = False) -> None:
    import curses

    state = {"current": start_url, "history": [], "quit": False}

    def run(scr):
        curses.curs_set(0)
        scr.keypad(True)
        # No explicit colors: links and headings are bold, the selected link and
        # status bar are reverse-video — the user's terminal theme supplies color.
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except Exception:
            pass

        while not state["quit"]:
            cur = state["current"]
            try:
                md = load(cur, js, full, for_browse=True, private=private)
                numbered, links = extract_and_number_links(md, cur, mark=True)
            except Exception as e:
                md, links = f"# Error\n\nCould not load {cur}:\n\n{e}", []
                numbered = md

            h, w = scr.getmaxyx()
            content_w = min(w - 4, 88)        # goyo-style narrow column
            pad = max(0, (w - content_w) // 2)
            top_pad = 2                       # blank rows above content
            view_h = max(1, h - 1 - top_pad)  # visible content rows
            lines, styles, link_line = _layout(numbered, content_w)
            top = 0
            cur_link = 1 if links else 0
            pending_g = False
            msg = ""
            search = ""          # active search term (lowercased)
            matches = []         # line indices containing the term
            match_i = -1         # index into matches of the current hit

            def clamp_top(t):
                return max(0, min(t, max(0, len(lines) - view_h)))

            def do_search(term, start, forward=True):
                nonlocal search, matches, match_i, top, msg
                search = term.lower()
                matches = [k for k, l in enumerate(lines)
                           if search in l.lower()]
                if not matches:
                    search = ""
                    msg = f"not found: {term}"
                    return
                if forward:
                    nxt = next((k for k, ln in enumerate(matches) if ln >= start),
                               0)  # wrap to first
                else:
                    prev = [k for k, ln in enumerate(matches) if ln <= start]
                    nxt = prev[-1] if prev else len(matches) - 1
                match_i = nxt
                top = clamp_top(matches[match_i] - view_h // 2)

            def repeat_search(forward=True):
                nonlocal match_i, top, msg
                if not matches:
                    msg = "no search"
                    return
                match_i = (match_i + (1 if forward else -1)) % len(matches)
                top = clamp_top(matches[match_i] - view_h // 2)
                msg = f"/{search}  [{match_i + 1}/{len(matches)}]"

            def put(row, col, s, attr):
                try:
                    scr.addstr(row, col, s, attr)
                except curses.error:
                    pass

            def render_spans(srow, text, clickmap):
                """Draw a line: only actual link text is bold (the current link
                is reverse-video). Records clickable regions into clickmap."""
                col = pad
                i, n = 0, len(text)
                while i < n:
                    ch = text[i]
                    if ch == LINK_START:
                        j = text.find(LINK_END, i + 1)
                        if j == -1:
                            j = n
                        inner = text[i + 1:j].replace(LINK_START, "")
                        mnum = re.search(r"\[(\d+)\]", inner)
                        num = int(mnum.group(1)) if mnum else -1
                        attr = (curses.A_REVERSE | curses.A_BOLD
                                if num == cur_link else curses.A_BOLD)
                        put(srow, col, inner, attr)
                        if num > 0:
                            clickmap.append((srow, col, col + len(inner), num))
                        col += len(inner)
                        i = j + 1
                    elif ch == LINK_END:
                        i += 1  # stray
                    else:
                        k = i
                        while k < n and text[k] not in (LINK_START, LINK_END):
                            k += 1
                        put(srow, col, text[i:k], curses.A_NORMAL)
                        col += k - i
                        i = k

            def strip_marks(t):
                return t.replace(LINK_START, "").replace(LINK_END, "")

            while True:
                scr.erase()
                clickmap = []
                for row in range(view_h):
                    i = top + row
                    if i >= len(lines):
                        break
                    srow = row + top_pad           # leave a top margin
                    text = lines[i][:content_w + 2]  # +2 for sentinels
                    is_match = (search and match_i >= 0 and matches
                                and i == matches[match_i])
                    if is_match:
                        put(srow, pad, strip_marks(text), curses.A_REVERSE)
                    elif styles[i] == "h":
                        put(srow, pad, strip_marks(text), curses.A_BOLD)
                    else:
                        render_spans(srow, text, clickmap)
                # status bar
                tgt = links[cur_link - 1] if 0 < cur_link <= len(links) else ""
                left = f" {cur[:w//2]} "
                right = (f"[{cur_link}/{len(links)}] {tgt}" if links
                         else "no links")
                status = (left + right)[:w - 1].ljust(w - 1)
                if msg:
                    status = (" " + msg)[:w - 1].ljust(w - 1)
                    msg = ""
                try:
                    scr.addstr(h - 1, 0, status, curses.A_REVERSE)
                except curses.error:
                    pass
                scr.refresh()

                c = scr.getch()

                # --- mouse: wheel scrolls, click follows a link ---
                if c == curses.KEY_MOUSE:
                    try:
                        _, mx, my, _, bstate = curses.getmouse()
                    except curses.error:
                        continue
                    up = getattr(curses, "BUTTON4_PRESSED", 0)
                    down = getattr(curses, "BUTTON5_PRESSED", 0)
                    if up and (bstate & up):
                        top = clamp_top(top - 3); continue
                    if down and (bstate & down):
                        top = clamp_top(top + 3); continue
                    hit = next((nm for (sr, c0, c1, nm) in clickmap
                                if my == sr and c0 <= mx < c1), None)
                    if hit:
                        cur_link = hit
                        state["history"].append(cur)
                        state["current"] = links[hit - 1]
                        break
                    continue

                # --- quit / navigation between pages ---
                if c in (ord("q"),):
                    state["quit"] = True
                    return
                if c == ord("?"):
                    msg = ("j/k scroll  h/l (or Tab) link  Enter/click open  "
                           "/ search  n/N next  gg/G top/bot  H back  : url  "
                           "r reload  q quit")
                    continue
                if c in (ord("H"), curses.KEY_BACKSPACE, 127, 8, ord("[")):
                    if state["history"]:
                        state["current"] = state["history"].pop()
                    else:
                        msg = "no history"
                        continue
                    break
                if c in (ord("r"),):
                    break  # reload current
                if c in (10, 13, curses.KEY_ENTER, ord("o")):
                    if 0 < cur_link <= len(links):
                        state["history"].append(cur)
                        state["current"] = links[cur_link - 1]
                        break
                    msg = "no link selected"; continue

                # --- link jumping (l / Tab next, h / Shift-Tab prev) ---
                if c in (9, ord("l")) and links:           # next link
                    cur_link = cur_link % len(links) + 1
                    if cur_link in link_line:
                        top = clamp_top(link_line[cur_link] - view_h // 2)
                    continue
                if c in (curses.KEY_BTAB, ord("h")) and links:  # prev link
                    cur_link = (cur_link - 2) % len(links) + 1
                    if cur_link in link_line:
                        top = clamp_top(link_line[cur_link] - view_h // 2)
                    continue

                # --- search repeat (vim n / N) ---
                if c == ord("n"):
                    repeat_search(forward=True)
                    continue
                if c == ord("N"):
                    repeat_search(forward=False)
                    continue

                # --- scrolling ---
                if c in (ord("j"), curses.KEY_DOWN):
                    top = clamp_top(top + 1)
                elif c in (ord("k"), curses.KEY_UP):
                    top = clamp_top(top - 1)
                elif c in (ord(" "), curses.KEY_NPAGE, 6):   # space / PgDn / C-f
                    top = clamp_top(top + view_h - 1)
                elif c in (curses.KEY_PPAGE, 2):             # PgUp / C-b
                    top = clamp_top(top - (view_h - 1))
                elif c == 4:                                 # Ctrl-D
                    top = clamp_top(top + view_h // 2)
                elif c == 21:                                # Ctrl-U
                    top = clamp_top(top - view_h // 2)
                elif c == ord("G"):
                    top = clamp_top(len(lines))
                elif c == ord("g"):
                    if pending_g:
                        top = 0; pending_g = False
                    else:
                        pending_g = True
                        continue
                elif c == ord("/"):
                    q = _prompt(scr, h, w, "/")
                    if q:
                        do_search(q, top + 1, forward=True)
                        if matches:
                            msg = f"/{search}  [{match_i + 1}/{len(matches)}]"
                elif c == ord(":"):
                    u = _prompt(scr, h, w, ":")
                    if u:
                        state["history"].append(cur)
                        state["current"] = resolve_target(u.strip())
                        break
                pending_g = False

    def _prompt(scr, h, w, prefix):
        curses.echo(); curses.curs_set(1)
        try:
            scr.addstr(h - 1, 0, " " * (w - 1))
            scr.addstr(h - 1, 0, prefix)
            scr.refresh()
            s = scr.getstr(h - 1, len(prefix), w - 2)
        except curses.error:
            s = b""
        finally:
            curses.noecho(); curses.curs_set(0)
        return s.decode("utf-8", "replace") if s else ""

    curses.wrapper(run)


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        prog="mdbrowse",
        description="A private markdown web browser for the terminal.",
    )
    ap.add_argument("url", nargs="?",
                    help="page to read (URL), or a local .md/.html file. "
                         "Omit to open your Safari homepage.")
    ap.add_argument("--bookmarks", action="store_true",
                    help="browse your Safari bookmarks")
    ap.add_argument("--reading-list", action="store_true",
                    help="browse your Safari reading list")
    ap.add_argument("--start", action="store_true",
                    help="open the Safari start page (homepage + bookmarks + reading list)")
    ap.add_argument("--private", "--anonymous", dest="private", action="store_true",
                    help="anonymous mode: send NO Safari cookies, add DNT/Sec-GPC "
                         "(default is to browse as your logged-in Safari self)")
    ap.add_argument("--js", action="store_true",
                    help="render JS-heavy pages with a headless browser engine")
    ap.add_argument("--raw", action="store_true",
                    help="print markdown source instead of rendering")
    ap.add_argument("--html", action="store_true",
                    help="render to styled HTML and open it in your browser")
    ap.add_argument("--browse", action="store_true",
                    help="interactive mode: vim-style navigation, follow links")
    ap.add_argument("--simple", action="store_true",
                    help="use the simple prompt instead of vim-style navigation")
    ap.add_argument("--full", action="store_true",
                    help="convert the whole page, don't strip to the article")
    ap.add_argument("--width", type=int, default=0,
                    help="wrap width (default: terminal width)")
    ap.add_argument("--no-pager", action="store_true",
                    help="don't pipe output through a pager")
    args = ap.parse_args()

    # Resolve the target. No URL -> the Safari homepage; flags -> Safari views.
    if args.bookmarks:
        url, force_browse = "safari:bookmarks", True
    elif args.reading_list:
        url, force_browse = "safari:reading", True
    elif args.start:
        url, force_browse = "safari:start", True
    elif not args.url:
        home = _safari_default("HomePage")
        # Homepage is your landing page -> open it browseable so links work.
        url, force_browse = (normalize_url(home), True) if home else ("safari:start", True)
    else:
        url, force_browse = resolve_target(args.url), False

    if args.browse or (force_browse and not args.raw and not args.html):
        browse(url, args.js, args.full, args.width, simple=args.simple,
               private=args.private)
        return

    try:
        md = load(url, args.js, args.full, private=args.private)
    except Exception as e:
        err(f"could not load {url}: {e}")
        sys.exit(1)

    if not md or not md.strip():
        err("nothing readable extracted (try --full, or --js for SPA pages)")
        sys.exit(1)

    if args.html:
        path = open_html_preview(md, title=url)
        print(f"mdbrowse: opened preview in your browser ({path})")
        return

    if args.raw:
        print(md)
        return

    render(md, url, args.width, use_pager=not args.no_pager)


if __name__ == "__main__":
    main()
