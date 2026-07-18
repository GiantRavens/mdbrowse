"""mdb reader — vim-style TUI frontend over the compiler's output.

Input model (task 4 spec): a single **focus ring** over links, images, and forms in
document order, like browser Tab. Two verbs, total:

    Enter = go   (follow the focused link / card)
    Space = peek (preview/toggle the focused image; page-down otherwise)

The governing rule: every keystroke's effect is predictable from what is
visibly highlighted — no behavior may depend on invisible state such as
what happens to be scrolled into view.

The reader consumes the emitter's markdown, which is *our own deterministic
serialization*, tokenized into styled segments before layout. No display
markers are injected and re-parsed (the legacy sentinel sin); focusables
carry (row, col0, col1) span segments, so the ENTIRE link highlights even
across wrapped lines.
"""

import curses
import os
import sys
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import cookies as safari_cookies
from .archive import save_archive
from .capture import Engine
from .classify import classify
from .emit import emit, emit_body

LINK, IMAGE, CARD, FORM = "link", "image", "card", "form"
_FIELD_W = 28                      # underscore-run width of a form field (fixed → stable layout)
_PREVIEW_PROC = None
_PREVIEW_URL = None

_JXA_IMAGE_SIZE = r'''
ObjC.import("AppKit");
function run(argv) {
  var img = $.NSImage.alloc.initWithContentsOfFile(argv[0]);
  if (!img) return "0 0";
  return Math.round(img.size.width) + " " + Math.round(img.size.height);
}
'''

_JXA_IMAGE_WINDOW = r'''
ObjC.import("AppKit");

ObjC.registerSubclass({
  name: "MdbPreviewWindowDelegate",
  protocols: ["NSWindowDelegate"],
  methods: {
    "windowWillClose:": {
      types: ["void", ["id"]],
      implementation: function(notification) {
        $.NSApp.terminate(null);
      }
    }
  }
});

function run(argv) {
  var path = argv[0];
  var img = $.NSImage.alloc.initWithContentsOfFile(path);
  if (!img) return 2;

  var size = img.size;
  var naturalW = Math.max(1, size.width);
  var naturalH = Math.max(1, size.height);
  var frame = $.NSScreen.mainScreen.visibleFrame;
  var maxW = frame.size.width * 0.90;
  var maxH = frame.size.height * 0.85;
  var scale = Math.min(1.0, maxW / naturalW, maxH / naturalH);
  var w = Math.max(32, Math.round(naturalW * scale));
  var h = Math.max(32, Math.round(naturalH * scale));
  var x = frame.origin.x + Math.round((frame.size.width - w) / 2);
  var y = frame.origin.y + Math.round((frame.size.height - h) / 2);

  var app = $.NSApplication.sharedApplication;
  app.setActivationPolicy($.NSApplicationActivationPolicyRegular);

  var style = $.NSWindowStyleMaskTitled
            | $.NSWindowStyleMaskClosable
            | $.NSWindowStyleMaskMiniaturizable
            | $.NSWindowStyleMaskResizable;
  var win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(
    $.NSMakeRect(x, y, w, h), style, $.NSBackingStoreBuffered, false);
  var view = $.NSImageView.alloc.initWithFrame($.NSMakeRect(0, 0, w, h));
  view.setImage(img);
  view.setImageAlignment($.NSImageAlignCenter);
  view.setImageScaling($.NSImageScaleProportionallyUpOrDown);
  win.setTitle("mdb image preview");
  win.setContentView(view);

  var delegate = $.MdbPreviewWindowDelegate.alloc.init;
  win.setDelegate(delegate);
  // A preview is a peek, not a focus transfer. Keep the terminal key so a
  // second Space reaches mdb and closes this process via preview_image().
  // orderFrontRegardless makes the window visible without making it key.
  win.orderFrontRegardless;
  app.run();
  return 0;
}
'''


def _form_line(f) -> str:
    """The dynamic display for a FORM focusable: label + value/underscores + [ submit ].
    Fixed width (tail of a long value) so the laid-out row never changes size."""
    val = f.value or ""
    shown = (val[-_FIELD_W:] if len(val) > _FIELD_W else val).ljust(_FIELD_W, "_")
    return f"⌗ {f.label}  {shown}  [ {f.submit} ]"


def _form_url(f) -> str:
    from urllib.parse import urlencode
    sep = "&" if "?" in (f.href or "") else "?"
    return (f.href or "") + sep + urlencode({f.param: f.value})


def _pagination_href(url: str, bundle: dict | None, direction: str) -> str:
    """Resolve a captured pager target; synthesize only confirmed numeric prev."""
    pagination = ((bundle or {}).get("doc", {}).get("pagination") or {})
    target = pagination.get(direction)
    if target and target.get("href"):
        return target["href"]
    if direction != "prev" or not pagination.get("param"):
        return ""

    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    u = urlsplit(url)
    pairs = parse_qsl(u.query, keep_blank_values=True)
    param = pagination["param"]
    for i, (key, value) in enumerate(pairs):
        if key != param:
            continue
        try:
            n = int(value)
        except ValueError:
            return ""
        if n <= 1:
            return ""
        pairs[i] = (key, str(n - 1))
        return urlunsplit((u.scheme, u.netloc, u.path,
                           urlencode(pairs), u.fragment))
    return ""

HELP_LINES = (
    "mdb reader — keys",
    "",
    "  Tab / S-Tab      next / previous focusable (links, images, forms)",
    "  Enter / o        go — follow the focused link or card",
    "  Space            peek — preview/toggle focused image, else page down",
    "  y                yank focused URL to clipboard",
    "  u / Y            copy current URL to clipboard",
    "  d                download the focused target",
    "  ( / )            previous / next heading",
    "  { / }            previous / next block",
    "  j k  C-d C-u     scroll line / half page",
    "  C-f C-b  PgDn/Up scroll full page",
    "  gg / G           top / bottom of page",
    "  zt / zz / zb     focused element to top / center / bottom",
    "  /  n  N          search, next match, previous match",
    "  H / L            history back / forward",
    "  r                reload page",
    "  s                save markdown archive",
    "  v                speak page from focused element (v again stops)",
    "  S / a            summarize / ask this page (Claude); H returns",
    "  F                open the page's RSS feed (when advertised)",
    "  f                fill the page's search form and go (GET forms)",
    "  . / ,            next / previous detected page",
    "  O                open in browser (MDBROWSE_BROWSER, default Safari)",
    "  B                add page to Safari Reading List",
    "  :                omnibox — URLs navigate, anything else searches",
    "                   (MDBROWSE_SEARCH_ENGINE or MDBROWSE_SEARCH_URL)",
    "                   (also 'ddg t', 'mojeek t', safari:start, feed:)",
    "  q                quit",
    "",
    "  mouse: wheel scrolls, click follows a link, click 🖼 previews",
    "",
    "  (any key to close)",
)


# ---------------------------------------------------------------------------
# Display width (the click/highlight math is in cells, not characters)
# ---------------------------------------------------------------------------
def _cw(ch: str) -> int:
    if ch == "🖼":
        return 2
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _dispw(s: str) -> int:
    return sum(_cw(c) for c in s)


# ---------------------------------------------------------------------------
# Tokenize: our own markdown -> styled segments + focusables
# ---------------------------------------------------------------------------
@dataclass
class Focusable:
    fid: int
    kind: str           # link | image | card | form
    label: str
    href: str = ""      # navigation target (link, card) / form action (form)
    src: str = ""       # preview target (image, card)
    param: str = ""     # form: the query field name
    submit: str = ""    # form: submit-button label
    value: str = ""     # form: the live edit buffer (typed by the user)


# URL matcher tolerating one level of parentheses (Wikipedia URLs).
# UNROLLED to a linear form — the earlier `(?:[^()\s]+|\(...\))+` had a
# nested quantifier over the same character class, and a run of images
# in one line ([![](url) ![](url) …], apple.com's feed) fed the card
# alternative input with no closing `](href)`, detonating catastrophic
# backtracking that hung the reader forever (capture was fine; _tokenize
# was not). This matches the same language — non-paren runs with single-
# level balanced parens between them — with no ambiguity. Label matchers
# stay escape-aware: the walker emits literal brackets as \[ \], and a
# label pattern that stops at any ']' would shred those links.
_URL = r"[^()\s]*(?:\([^()\s]*\)[^()\s]*)*"
_LBL = r"(?:[^\[\]\\]|\\.)"
_TOKEN_RE = re.compile(
    rf"\[(?P<cpre>{_LBL}*)!\[(?P<calt>{_LBL}*)\]\((?P<csrc>{_URL})\)"
    rf"(?P<cpost>{_LBL}*)\]\((?P<chref>{_URL})\)"
    rf"|!\[(?P<alt>{_LBL}*)\]\((?P<src>{_URL})\)"
    rf"|(?<!!)\[(?P<text>{_LBL}+?)\]\((?P<href>{_URL})\)"
)


def _clean(s: str) -> str:
    """Strip emphasis/code marks for terminal display, then unescape the
    walker's markdown escapes."""
    s = s.replace("**", "").replace("`", "")
    s = re.sub(r"(?<!\\)\*([^*\n]+)(?<!\\)\*", r"\1", s)
    return re.sub(r"\\([\\`*_\[\]])", r"\1", s)


_OPENERS = " ([{'\"“‘/-–—"
_CLOSERS = " ,.;:!?)]}'\"”’/-–—%"


def _tokenize(line: str, focusables: list):
    """One logical line -> [(text, fid|None)], appending new focusables.

    Focusables get breathing room: a space is inserted when a link butts
    directly against preceding text or the following text/link (Wikipedia
    citation clusters, adjacent nav links). Display-only — the markdown
    document is untouched, so hashes and diffs stay stable."""
    segs, pos = [], 0

    def pad_before():
        if segs and segs[-1][0] and segs[-1][0][-1] not in _OPENERS:
            segs.append((" ", None))

    def pad_after(end):
        nxt = line[end:end + 1]
        if nxt and nxt not in _CLOSERS and nxt != "\\":
            segs.append((" ", None))

    for m in _TOKEN_RE.finditer(line):
        if m.start() > pos:
            segs.append((_clean(line[pos:m.start()]), None))
        if m.group("chref"):                       # linked image (card)
            label = " ".join(f"{m.group('cpre')} {m.group('cpost')}".split()) \
                    or m.group("calt").strip() or "card"
            f = Focusable(len(focusables), CARD, _clean(label),
                          href=m.group("chref"), src=m.group("csrc"))
            focusables.append(f)
            pad_before()
            # Two spaces after the icon: emoji glyphs overdraw their cell in
            # some terminals, visually fusing with the first letter.
            segs.append(("🖼  " + f.label, f.fid))
        elif m.group("src") is not None:           # plain image
            alt = (m.group("alt") or "").strip() or "image"
            f = Focusable(len(focusables), IMAGE, _clean(alt),
                          src=m.group("src"))
            focusables.append(f)
            pad_before()
            segs.append(("🖼  " + f.label, f.fid))
        else:                                      # plain link
            f = Focusable(len(focusables), LINK, _clean(m.group("text")),
                          href=m.group("href"))
            focusables.append(f)
            pad_before()
            segs.append((f.label, f.fid))
        pad_after(m.end())
        pos = m.end()
    if pos < len(line):
        segs.append((_clean(line[pos:]), None))
    return [(t, fid) for t, fid in segs if t]


def _explode_images(segs, focusables):
    """Split a line's segments so each image/card lands on its OWN display
    line — inline thumbnails break text flow. A bare list marker before
    the image stays attached (feed bullets keep their dash)."""
    groups, buf = [], []

    def buf_is_marker_only():
        joined = "".join(t for t, _ in buf)
        return bool(re.fullmatch(r"\s*(?:[-*]|\d+\.)?\s*", joined))

    for seg in segs:
        _text, fid = seg
        kind = focusables[fid].kind if fid is not None else None
        if kind in (IMAGE, CARD):
            if buf and buf_is_marker_only():
                buf.append(seg)
                groups.append(buf)
                buf = []
            else:
                if buf:
                    groups.append(buf)
                    buf = []
                groups.append([seg])
        else:
            buf.append(seg)
    if buf:
        groups.append(buf)
    return [g for g in groups
            if any(t.strip() for t, _ in g)]


# ---------------------------------------------------------------------------
# Parse body -> logical lines; layout -> display rows with focus spans
# ---------------------------------------------------------------------------
@dataclass
class LLine:
    segs: list                 # [(text, fid|None)]
    style: str = ""            # '' | 'h' | 'q' | 'code' | 'hr'
    indent: int = 0            # continuation indent for wrapped rows


def _forms_of(bundle) -> list:
    """The deduped form blocks from a bundle, in the SAME order emit renders them
    (by first-seen (param, action)) — so form LINES match form BLOCKS positionally."""
    out, seen = [], set()
    for b in ((bundle or {}).get("doc", {}) or {}).get("blocks", []) or []:
        if b.get("kind") != "form":
            continue
        key = (b.get("param"), b.get("action"))
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def parse_body(body: str, bundle=None):
    llines, focusables, in_code = [], [], False
    form_queue = _forms_of(bundle)
    for raw in body.split("\n"):
        if raw.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            llines.append(LLine([(raw, None)], "code"))
            continue
        s = raw.rstrip()
        if not s.strip():
            llines.append(LLine([]))
            continue
        if s.startswith("⌗ ") and form_queue:          # a rendered form: one FORM focusable
            b = form_queue.pop(0)
            f = Focusable(len(focusables), FORM, (b.get("label") or "Search").strip(),
                          href=b.get("action") or "", param=b.get("param") or "q",
                          submit=(b.get("submit_label") or "Search").strip())
            focusables.append(f)
            llines.append(LLine([(_form_line(f), f.fid)], ""))
            continue
        if s.strip() in ("---", "***"):
            llines.append(LLine([("─" * 36, None)], "hr"))
            continue
        style, indent = "", 0
        if s.lstrip().startswith("#"):
            s = s.lstrip().lstrip("#").strip()
            style = "h"
        elif s.lstrip().startswith(">"):
            s = s.lstrip()[1:].strip()
            style = "q"
        else:
            m = re.match(r"^(\s*)(?:[-*]|\d+\.)\s+", s)
            if m:
                indent = len(m.group(0))
        segs = _tokenize(s, focusables)
        for group in _explode_images(segs, focusables):
            llines.append(LLine(group, style, indent))
    return llines, focusables


def _initial_focus(focusables: list) -> int:
    """Do not arm a form field just because it is first on the page.

    Navigation keys like O/H/y should work immediately after load; users
    intentionally enter a field by tabbing to it.
    """
    for f in focusables:
        if f.kind != FORM:
            return f.fid
    return -1


def _wrap_chars(chars, width, indent):
    """Greedy word-wrap over (char, fid) tuples; continuation rows get
    `indent` leading spaces. Focus attribution survives wrapping — that's
    the whole point."""
    rows, ind = [], [(" ", None)] * indent
    cur, curw = [], 0
    word = []

    def newline():
        nonlocal cur, curw
        rows.append(cur)
        cur, curw = list(ind), indent

    def emit_word():
        nonlocal cur, curw, word
        if not word:
            return
        wordw = sum(_cw(c[0]) for c in word)
        if curw > indent and curw + wordw > width:
            while cur and cur[-1][0] == " " and len(cur) > indent:
                cur.pop()
                curw -= 1
            newline()
        for c in word:
            if curw + _cw(c[0]) > width and curw > indent:
                newline()               # hard-break an over-long token
            cur.append(c)
            curw += _cw(c[0])
        word = []

    for c in chars:
        if c[0] == " ":
            emit_word()
            if curw < width:
                cur.append(c)
                curw += 1
        else:
            word.append(c)
    emit_word()
    rows.append(cur)
    return rows


def layout(llines, width):
    """-> (rows, styles, fpos): rows are span lists [(col, text, fid|None)];
    fpos maps fid -> [(row, col0, col1), ...] covering the FULL extent of
    each focusable across wrapped rows."""
    rows, styles, fpos = [], [], {}
    for ll in llines:
        if not ll.segs:
            rows.append([])
            styles.append("")
            continue
        chars = [(ch, fid) for text, fid in ll.segs for ch in text]
        for rowchars in _wrap_chars(chars, width, ll.indent):
            spans, col = [], 0
            cur_fid, cur_text, cur_col = "SENTINEL", "", 0
            for ch, fid in rowchars:
                if fid != cur_fid:
                    if cur_text:
                        spans.append((cur_col, cur_text, cur_fid))
                    cur_fid, cur_text, cur_col = fid, "", col
                cur_text += ch
                col += _cw(ch)
            if cur_text:
                spans.append((cur_col, cur_text, cur_fid))
            r = len(rows)
            for c0, text, fid in spans:
                if fid is not None and text.strip():
                    fpos.setdefault(fid, []).append((r, c0, c0 + _dispw(text)))
            rows.append(spans)
            styles.append(ll.style)
    return rows, styles, fpos


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
_MIME_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/avif": ".avif", "image/svg+xml": ".svg",
    "image/tiff": ".tiff", "image/bmp": ".bmp", "image/heic": ".heic",
}
_KNOWN_EXTS = set(_MIME_EXT.values()) | {".jpeg", ".tif"}


def _image_ext(url: str, content_type: str, data: bytes) -> str:
    """Pick a Quick Look-safe suffix: Content-Type first, then the URL
    path, then magic bytes. NEVER '.img' — extension-less URLs (NASA CDN)
    used to fall back to it, and macOS treats .img as a DISK image, so a
    headshot previewed as a mountable volume."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _MIME_EXT:
        return _MIME_EXT[ct]
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in _KNOWN_EXTS:
        return ext
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if b"ftypavif" in data[:32]:
        return ".avif"
    if b"ftypheic" in data[:32] or b"ftypheix" in data[:32]:
        return ".heic"
    if data.lstrip()[:5].lower() in (b"<svg", b"<?xml"):
        return ".svg"
    return ".jpg"


def _fetch_image(url: str, private: bool = False, referer: str = None,
                 engine=None):
    """Download an image the way a real browser would (session cookies,
    Safari UA, image Accept, Referer) and validate that what came back IS
    an image. Returns (path|None, note) — the note goes to the status bar,
    so a refused or placeholder image is a reading, not a blank window.

    Fallback chain: httpx (fast, 6s) -> the browser engine itself. Hostile
    CDNs (luxury-brand WAFs) tarpit httpx's TLS fingerprint; a fetch
    through Chromium is indistinguishable from the real browser."""
    import httpx
    from .capture import IPHONE_UA
    headers = {
        "User-Agent": IPHONE_UA,
        "Accept": "image/avif,image/webp,image/png,image/jpeg,"
                  "image/*;q=0.8,*/*;q=0.5",
    }
    if referer:
        headers["Referer"] = referer
    via = ""
    try:
        try:
            cookies = None if private else safari_cookies.for_httpx()
            with httpx.Client(follow_redirects=True, timeout=6.0,
                              headers=headers, cookies=cookies) as c:
                r = c.get(url)
                r.raise_for_status()
                data = r.content
            ct_header = r.headers.get("content-type", "")
        except Exception:
            if engine is None:
                raise
            data, ct_header = engine.fetch_resource(url)
            via = " · via engine"
        ct = (ct_header or "").split(";")[0].strip().lower()
        looks_html = (data.lstrip()[:1] == b"<"
                      and b"<svg" not in data[:256].lower())
        if ct.startswith("text/") or ct == "application/json" or (
                not ct.startswith("image/") and looks_html):
            return None, f"site sent {ct or 'HTML'}, not the image (hotlink protection?)"
        if len(data) < 128:
            return None, f"only {len(data)} bytes — a lazy-load placeholder, not the real asset"
        ext = _image_ext(url, ct, data)
        fd, path = tempfile.mkstemp(suffix=ext, prefix="mdb_img_")
        os.write(fd, data)
        os.close(fd)
        return path, (f"{ct or ext.lstrip('.')} · "
                      f"{max(1, len(data) // 1024)} KB{via}")
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:80]}"


def _close_previous_preview() -> None:
    global _PREVIEW_PROC, _PREVIEW_URL
    proc = _PREVIEW_PROC
    _PREVIEW_PROC = None
    _PREVIEW_URL = None
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=0.4)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _macos_image_size(path: str) -> tuple[int, int] | None:
    try:
        r = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA_IMAGE_SIZE, path],
            capture_output=True, text=True, timeout=2)
        if r.returncode != 0:
            return None
        parts = (r.stdout or "").strip().split()
        if len(parts) < 2:
            return None
        w, h = int(float(parts[-2])), int(float(parts[-1]))
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def _image_viewer(path: str) -> tuple[bool, str]:
    """Open a saved image in the platform's viewer, WITHOUT ever raising if none exists.
    macOS uses a tiny Cocoa image window sized to the image; large images are capped to
    the visible screen. A Linux desktop (DISPLAY/WAYLAND) uses the first available
    viewer; a headless box or SSH-without-forwarding reports the saved path."""
    import shutil
    global _PREVIEW_PROC
    _close_previous_preview()
    if sys.platform == "darwin":
        size = _macos_image_size(path)
        if size and shutil.which("osascript"):
            _PREVIEW_PROC = subprocess.Popen(
                ["osascript", "-l", "JavaScript", "-e", _JXA_IMAGE_WINDOW, path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"preview {size[0]}x{size[1]} → {path}"
        if shutil.which("qlmanage"):
            _PREVIEW_PROC = subprocess.Popen(
                ["qlmanage", "-p", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _raise_quicklook()
            return True, f"Quick Look → {path}"
        _PREVIEW_PROC = subprocess.Popen(
            ["open", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, f"opened → {path}"
    have_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if have_display:
        for viewer in ("xdg-open", "feh", "eog", "eom", "gpicview", "xdg-open"):
            if shutil.which(viewer):
                try:
                    _PREVIEW_PROC = subprocess.Popen(
                        [viewer, path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True, f"{viewer} → {path}"
                except Exception:
                    continue
    # No display (headless / SSH without X): saved, not shown — report the path.
    return True, f"saved → {path} (no display to preview here; open it locally)"


def preview_image(url: str, private: bool = False, referer: str = None,
                  engine=None):
    """Fetch + validate an image, then open it in the platform viewer (or, on a headless
    box / SSH session, report where it was saved). Never raises on a missing viewer."""
    global _PREVIEW_URL
    if _PREVIEW_URL == url and _PREVIEW_PROC is not None and _PREVIEW_PROC.poll() is None:
        _close_previous_preview()
        return True, "preview closed"
    path, note = _fetch_image(url, private=private, referer=referer,
                              engine=engine)
    if not path:
        return False, note
    try:
        ok, vnote = _image_viewer(path)
    except Exception as e:
        return True, f"saved → {path} (viewer error: {type(e).__name__})"
    if ok and _PREVIEW_PROC is not None and _PREVIEW_PROC.poll() is None:
        _PREVIEW_URL = url
    return ok, vnote


def _raise_quicklook() -> None:
    """qlmanage draws behind the focused terminal; nudge it forward.
    Best-effort — if Automation permission is denied, it opens behind."""
    script = (
        'tell application "System Events"\n'
        '  repeat 30 times\n'
        '    if exists (process "qlmanage") then\n'
        '      set frontmost of process "qlmanage" to true\n'
        '      exit repeat\n'
        '    end if\n'
        '    delay 0.05\n'
        '  end repeat\n'
        'end tell'
    )
    try:
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def open_in_browser(url: str) -> str:
    """Open the live URL in the user's browser of choice.

    MDBROWSE_BROWSER names the app ('Google Chrome', 'Firefox', ...);
    default is Safari, whose session mdb already rides. Returns the app
    name used, '' on failure."""
    if not url.startswith(("http://", "https://")):
        return ""
    app = os.environ.get("MDBROWSE_BROWSER", "Safari")
    try:
        r = subprocess.run(["open", "-a", app, url], check=False, timeout=5,
                           capture_output=True)
        if r.returncode != 0:       # unknown app name -> system default
            subprocess.run(["open", url], check=False, timeout=5)
            return "default browser"
        return app
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------
@dataclass
class Page:
    url: str
    bundle: dict
    manifest: object
    body: str
    llines: list = field(default_factory=list)
    focusables: list = field(default_factory=list)


class Reader:
    def __init__(self, start_url: str, private: bool = False, width: int = 0,
                 voice: str = None, announce: bool = False):
        self.start_url = start_url
        self.private = private
        self.width = width          # goyo column override (0 = default 88)
        self.voice = voice
        self.announce = announce    # speak each element as focus lands on it
        self.engine = Engine(private=private)
        # Playwright's sync API is thread-bound: the engine may only be
        # touched from ONE thread for its whole life. A single-worker
        # executor owns it — every capture, image fetch, download, and
        # close runs here, and the curses main thread stays free to
        # animate. (Following a link once ran the load on a fresh thread
        # per nav; the second nav hit 'cannot switch to a different
        # thread' — this serializes them onto the engine's own thread.)
        from concurrent.futures import ThreadPoolExecutor
        self._exec = ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="mdb-engine")
        self.history = []           # back stack
        self.forward = []           # forward stack (L); cleared on new go
        self.page = None
        self.msg = ""
        self._say = None            # active `say` process, if any
        self._assist = None         # last LLM answer, shown as a page

    def _speech_stop(self):
        from . import speech
        speech.stop(self._say)
        self._say = None

    # -- pipeline --
    def load(self, url: str) -> Page:
        if url == "assist:last" and self._assist is not None:
            return self._assist
        if url.startswith("feed:"):
            from . import rss
            title, body = rss.page_markdown(url[len("feed:"):], self.private)
            page = Page(url=url, bundle=None, manifest=None, body=body)
            page.llines, page.focusables = parse_body(body, page.bundle)
            return page
        if url.startswith("safari:"):
            from . import safari
            body = safari.page_markdown(url.split(":", 1)[1] or "start")
            page = Page(url=url, bundle=None, manifest=None, body=body)
        else:
            b = self.engine.capture(url)
            m = classify(b)
            body = emit_body(b, m)
            if m.shape in ("app", "wall"):
                # The classified refusal must not be a dead end: the reader
                # itself has the exits. (Frontend hint only — the emitted
                # document, archives, and hashes stay untouched.)
                body += (
                    "\n\n---\n\n"
                    "**From here you can:**\n\n"
                    "- press `O` — open this page in your browser\n"
                    "- press `:` and type search terms — search the web\n"
                    "- press `H` — go back"
                )
            page = Page(url=b["meta"]["url"], bundle=b, manifest=m, body=body)
        page.llines, page.focusables = parse_body(body, page.bundle)
        return page

    def _load_animated(self, scr, url: str) -> Page:
        """Load in a worker thread while the status bar shows a live
        spinner and elapsed seconds — the capture can take seconds
        (render, settle, section-expand) and a frozen 'loading …' line
        reads as a hang. Returns the Page, or an error_page on failure."""
        import time as _t
        from concurrent.futures import TimeoutError as _FutTimeout
        fut = self._exec.submit(self.load, url)   # runs on the engine thread
        spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        t0, i = _t.monotonic(), 0
        h, w = scr.getmaxyx()
        short = url if len(url) <= w - 24 else url[:w - 25] + "…"
        while True:
            try:
                return fut.result(timeout=0.12)
            except _FutTimeout:
                pass
            except Exception as e:      # noqa: BLE001 — shown to the user
                return self.error_page(url, e)
            el = _t.monotonic() - t0
            note = "" if el < 3 else ("  (slow site — still trying)"
                                      if el < 12 else "  (heavy page — hang on)")
            line = f" {spin[i % len(spin)]} loading {short}  {el:0.0f}s{note}"
            try:
                scr.addstr(h - 1, 0, line[:w - 1].ljust(w - 1), curses.A_REVERSE)
                scr.refresh()
            except curses.error:
                pass
            i += 1

    def error_page(self, url: str, e: Exception) -> Page:
        body = (f"# Couldn't load this page\n\n`{url}`\n\n{e}\n\n---\n\n"
                "**From here you can:**\n\n"
                "- press `:` and type a web search for the site\n"
                "- press `O` — open it in your browser\n"
                "- press `H` — go back")
        page = Page(url=url, bundle=None, manifest=None, body=body)
        page.llines, page.focusables = parse_body(body, page.bundle)
        return page

    # -- curses main --
    def run(self):
        try:
            curses.wrapper(self._run)
        finally:
            os.write(1, b"\x1b[?1000;1006l")   # mouse reporting off
            _close_previous_preview()
            self._speech_stop()
            try:
                self._exec.submit(self.engine.close).result(timeout=10)
            except Exception:
                pass
            self._exec.shutdown(wait=False)

    def _status_load(self, scr, url):
        h, w = scr.getmaxyx()
        try:
            scr.addstr(h - 1, 0, f" loading {url} …"[:w - 1].ljust(w - 1),
                       curses.A_REVERSE)
            scr.refresh()
        except curses.error:
            pass

    def _run(self, scr):
        curses.curs_set(0)
        scr.keypad(True)
        # SGR-1006 mouse, spoken directly (see _read_sgr_mouse for why the
        # curses mouse layer is bypassed). 1000h = button events only —
        # never 1003 motion tracking, which Terminal.app rejects wholesale.
        os.write(1, b"\x1b[?1000;1006h")

        current = self.start_url
        while True:
            try:
                self.page = self._load_animated(scr, current)
                current = self.page.url
                hints = []
                if self.page.bundle:
                    doc = self.page.bundle["doc"]
                    if doc.get("feeds"):
                        hints.append("RSS: F")
                    if any(b.get("kind") == "form"
                           for b in doc.get("blocks", [])):
                        hints.append("search form: f")
                    pagination = doc.get("pagination") or {}
                    if pagination.get("next"):
                        hints.append("next: .")
                    if pagination.get("prev") or pagination.get("param"):
                        hints.append("prev: ,")
                if hints:
                    self.msg = " · ".join(hints)
            except Exception as e:
                self.page = self.error_page(current, e)
            nav = self._view(scr)
            self._speech_stop()      # page is changing; the old page hushes
            if nav is None:
                return
            _close_previous_preview()
            action, target = nav
            if action == "go":
                self.history.append(current)
                self.forward.clear()
                current = target
            elif action == "back":
                self.forward.append(current)
                current = self.history.pop()
            elif action == "forward":
                self.history.append(current)
                current = self.forward.pop()
            # "reload": fall through with same URL

    def _view(self, scr):
        """Show self.page; return None to quit, ('go', url), ('back', None),
        or ('reload', None)."""
        page = self.page
        h, w = scr.getmaxyx()

        def geometry():
            nonlocal h, w, content_w, pad, view_h, rows, styles, fpos
            h, w = scr.getmaxyx()
            content_w = min(w - 4, self.width or 88)
            pad = max(0, (w - content_w) // 2)
            view_h = max(1, h - 1 - TOP_PAD)
            rows, styles, fpos = layout(page.llines, content_w)

        TOP_PAD = 2
        content_w = pad = view_h = 0
        rows, styles, fpos = [], [], {}
        geometry()

        focusables = page.focusables
        focus = _initial_focus(focusables)
        top = 0
        search, matches, match_i = "", [], -1
        pending = None            # chord prefix: 'g' or 'z'

        def clamp(t):
            return max(0, min(t, max(0, len(rows) - view_h)))

        def row_text(r):
            return "".join(t for _, t, _ in rows[r])

        def focus_row(fid):
            seg = fpos.get(fid)
            return seg[0][0] if seg else None

        def center_focus():
            nonlocal top
            r = focus_row(focus)
            if r is not None and not (top <= r < top + view_h):
                top = clamp(r - view_h // 2)

        def move_focus(step):
            nonlocal focus
            if not focusables:
                return
            if focus < 0:
                focus = 0 if step > 0 else len(focusables) - 1
            else:
                focus = (focus + step) % len(focusables)
            center_focus()
            if self.announce:
                from . import speech
                self._speech_stop()
                f = focusables[focus]
                prefix = {IMAGE: "image, ", CARD: "linked image, "}.get(f.kind, "")
                self._say = speech.speak((prefix + f.label)[:200], self.voice)

        def attr_for(f, focused):
            if f.kind == LINK:
                base = curses.A_BOLD
            elif f.kind == CARD:
                base = curses.A_BOLD | curses.A_UNDERLINE
            else:
                base = curses.A_UNDERLINE
            return (base | curses.A_REVERSE) if focused else base

        def show_preview(f):
            # fetch_resource is Playwright-bound; run on the engine thread.
            ok, note = self._exec.submit(
                preview_image, f.src, self.private, page.url,
                self.engine).result()
            self.msg = f"🖼  {note}" if ok else f"preview failed: {note}"

        def go(f):
            if f.kind == FORM:
                return ("go", _form_url(f)) if f.value.strip() else None
            if f.kind in (LINK, CARD) and f.href:
                return ("go", f.href)
            if f.kind == IMAGE and f.src:
                show_preview(f)
            return None

        def peek(f):
            if f and f.kind in (IMAGE, CARD) and f.src:
                show_preview(f)
                return True
            return False

        def copy_url(target):
            try:
                subprocess.run(["pbcopy"], input=target.encode(), check=True)
                self.msg = f"copied: {target[:90]}"
            except Exception as e:
                self.msg = f"copy failed: {e}"

        def do_search(term, start):
            nonlocal search, matches, match_i, top
            search = term.lower()
            matches = [r for r in range(len(rows))
                       if search in row_text(r).lower()]
            if not matches:
                search = ""
                self.msg = f"not found: {term}"
                return
            match_i = next((k for k, r in enumerate(matches) if r >= start), 0)
            top = clamp(matches[match_i] - view_h // 2)
            self.msg = f"/{search}  [{match_i + 1}/{len(matches)}]"

        def repeat_search(fwd=True):
            nonlocal match_i, top
            if not matches:
                self.msg = "no search"
                return
            match_i = (match_i + (1 if fwd else -1)) % len(matches)
            top = clamp(matches[match_i] - view_h // 2)
            self.msg = f"/{search}  [{match_i + 1}/{len(matches)}]"

        def put(row, col, s, attr):
            try:
                scr.addstr(row, col, s, attr)
            except curses.error:
                pass

        while True:
            scr.erase()
            visible_focus = []   # (srow, c0, c1, fid, text) for mouse
            for vr in range(view_h):
                r = top + vr
                if r >= len(rows):
                    break
                srow = vr + TOP_PAD
                style = styles[r]
                is_match = (matches and match_i >= 0 and r == matches[match_i])
                base = {"h": curses.A_BOLD, "q": curses.A_DIM,
                        "code": curses.A_DIM, "hr": curses.A_DIM,
                        "": curses.A_NORMAL}[style]
                for c0, text, fid in rows[r]:
                    if fid is None:
                        attr = base | (curses.A_REVERSE if is_match else 0)
                        put(srow, pad + c0, text, attr)
                    else:
                        f = focusables[fid]
                        disp = _form_line(f) if f.kind == FORM else text
                        put(srow, pad + c0, disp, attr_for(f, fid == focus))
                        visible_focus.append((srow, pad + c0,
                                              pad + c0 + _dispw(disp), fid, disp))
            # status bar
            if self.msg:
                status = (" " + self.msg)[:w - 1].ljust(w - 1)
                self.msg = ""
            else:
                left = f" {page.url}"
                if 0 <= focus < len(focusables):
                    f = focusables[focus]
                    tgt = f.href or f.src
                    right = f"[{focus + 1}/{len(focusables)}] {f.kind} → {tgt}"
                elif focusables:
                    right = f"Tab to focus [{len(focusables)}]"
                else:
                    right = "no focusables"
                room = w - 1 - len(right) - 3
                status = (left[:max(10, room)] + "  " + right)[:w - 1].ljust(w - 1)
            put(h - 1, 0, status, curses.A_REVERSE)
            scr.refresh()

            c = scr.getch()

            if c == curses.KEY_RESIZE:
                geometry()
                top = clamp(top)
                scr.clear()
                continue

            # --- form-field editing: a focused FORM captures typing (Lynx-style) ---
            # Enter submits, Backspace deletes, printable chars type into the field;
            # Tab/arrows/ESC fall through so you can still navigate off the field.
            if 0 <= focus < len(focusables) and focusables[focus].kind == FORM:
                foc = focusables[focus]
                if c in (10, 13, curses.KEY_ENTER):
                    nav = go(foc)
                    if nav:
                        return nav
                    self.msg = "type a query first"
                    continue
                if c in (curses.KEY_BACKSPACE, 127, 8):
                    foc.value = foc.value[:-1]
                    continue
                if 32 <= c < 127:
                    foc.value += chr(c)
                    continue

            if c == 27:                      # ESC: SGR mouse (or stray escape)
                ev = self._read_sgr_mouse(scr)
                if ev is None:
                    continue
                btn, mx, my, released = ev
                if btn & 64:                 # wheel: 64 up, 65 down (+mods)
                    top = clamp(top + (3 if btn & 1 else -3))
                    continue
                if btn & 32 or released:     # drag/motion or button-up: ignore
                    continue
                if (btn & 3) != 0:           # not the left button
                    continue
                hit = next((span for span in visible_focus
                            if my == span[0] and span[1] <= mx < span[2]), None)
                if hit is not None:
                    _, c0, _, fid, disp = hit
                    focus = fid
                    f = focusables[fid]
                    icon_hit = disp.startswith("🖼") and mx < c0 + _dispw("🖼  ")
                    # Clicking the picture icon previews it; clicking card text
                    # follows the linked article. Enter still follows too.
                    if f.kind == IMAGE or (f.kind == CARD and icon_hit):
                        peek(f)
                    else:
                        nav = go(f)
                        if nav:
                            return nav
                continue

            if c == ord("q"):
                return None
            if c == ord("?"):
                self._help_overlay(scr, h, w)
                scr.clear()          # full repaint after the overlay
                continue

            # --- focus ring ---
            if c == 9:                                   # Tab
                move_focus(1)
                continue
            if c == curses.KEY_BTAB:                     # Shift-Tab
                move_focus(-1)
                continue

            # --- the two verbs ---
            if c in (10, 13, curses.KEY_ENTER, ord("o")):    # Enter = go
                if 0 <= focus < len(focusables):
                    nav = go(focusables[focus])
                    if nav:
                        return nav
                else:
                    self.msg = "nothing focused"
                continue
            if c == ord(" "):                                # Space = peek
                f = focusables[focus] if 0 <= focus < len(focusables) else None
                if not peek(f):
                    top = clamp(top + view_h - 1)            # else page down
                continue

            # --- copy / download on the focused element or page ---
            if c in (ord("y"), ord("u"), ord("Y"), ord("d")):
                f = focusables[focus] if 0 <= focus < len(focusables) else None
                if c in (ord("u"), ord("Y")):
                    target = page.url
                elif f is None:
                    self.msg = "nothing focused"
                    continue
                elif c == ord("d"):
                    target = f.src if f.kind in (IMAGE, CARD) else f.href
                else:
                    target = f.href or f.src
                if c == ord("d"):
                    try:
                        from .download import download
                        self.msg = "downloading…"
                        # download may fall back to engine.fetch_resource
                        # (Playwright-bound); run on the engine thread.
                        path, size = self._exec.submit(
                            download, target, self.private, page.url,
                            engine=self.engine).result()
                        self.msg = f"saved → {path} ({max(1, size // 1024)} KB)"
                    except Exception as e:
                        self.msg = f"download failed: {str(e)[:80]}"
                else:
                    copy_url(target)
                continue

            # --- page navigation ---
            if c in (ord("H"), curses.KEY_BACKSPACE, 127, 8):
                if self.history:
                    return ("back", None)
                self.msg = "no history"
                continue
            if c == ord("L"):
                if self.forward:
                    return ("forward", None)
                self.msg = "no forward history"
                continue
            if c == ord("r"):
                return ("reload", None)
            if c == ord("s"):
                if page.bundle is not None:
                    try:
                        doc = emit(page.bundle, page.manifest)
                        title = page.bundle["doc"].get("title") or page.url
                        self.msg = f"saved → {save_archive(doc, title, page.url)}"
                    except Exception as e:
                        self.msg = f"save failed: {e}"
                continue
            if c == ord("O"):
                app = open_in_browser(page.url)
                self.msg = (f"opened in {app}" if app
                            else "couldn't open a browser")
                continue
            if c == ord("f"):                # fill the page's GET form
                forms = [b for b in (page.bundle["doc"].get("blocks", [])
                                     if page.bundle else [])
                         if b.get("kind") == "form"]
                if not forms:
                    self.msg = "no fillable form on this page"
                    continue
                # prefer the search-shaped one
                best = next((b for b in forms
                             if b.get("param") in ("q", "s", "search", "query")),
                            forms[0])
                q = self._prompt(scr, h, w, f"{best.get('label') or 'search'}: ")
                if not q.strip():
                    continue
                from urllib.parse import urlencode
                params = dict(best.get("hidden") or {})
                params[best["param"]] = q.strip()
                sep = "&" if "?" in best["action"] else "?"
                return ("go", best["action"] + sep + urlencode(params))

            if c == ord("F"):                # open the page's advertised feed
                feeds = (page.bundle["doc"].get("feeds")
                         if page.bundle else None) or []
                if feeds:
                    return ("go", "feed:" + feeds[0]["href"])
                self.msg = "no feed advertised on this page"
                continue

            if c in (ord("."), ord(",")):    # detected page chain
                direction = "next" if c == ord(".") else "prev"
                href = _pagination_href(page.url, page.bundle, direction)
                if href:
                    return ("go", href)
                self.msg = f"no {direction} page detected"
                continue

            if c in (ord("S"), ord("a")):    # LLM: summarize / ask this page
                from . import assist
                if not assist.available():
                    self.msg = "claude CLI not found on PATH"
                    continue
                if not page.body.strip():
                    self.msg = "nothing to send"
                    continue
                question = None
                if c == ord("a"):
                    question = self._prompt(scr, h, w, "ask: ").strip()
                    if not question:
                        continue
                verb = "summarizing" if question is None else "asking"
                self._status_load(scr, f"{verb} via claude -p …")
                try:
                    if question is None:
                        answer = assist.summarize(page.body, page.url)
                        title = "Summary"
                    else:
                        answer = assist.ask(page.body, question, page.url)
                        title = f"Q: {question}"
                except Exception as e:
                    self.msg = f"assist failed: {str(e)[:120]}"
                    continue
                src = (page.bundle["doc"].get("title")
                       if page.bundle else page.url) or page.url
                body = f"# {title}\n\n_{src}_\n\n{answer}"
                ap = Page(url="assist:last", bundle=None, manifest=None,
                          body=body)
                ap.llines, ap.focusables = parse_body(body, ap.bundle)
                self._assist = ap
                return ("go", "assist:last")

            if c == ord("v"):                # speak page from focused element
                from . import speech
                if self._say and self._say.poll() is None:
                    self._speech_stop()
                    self.msg = "speech stopped"
                    continue
                start = 0
                if 0 <= focus < len(focusables):
                    for i, ll in enumerate(page.llines):
                        if any(fid == focus for _, fid in ll.segs):
                            start = i
                            break
                text = speech.from_llines(page.llines, start)
                if text.strip():
                    self._say = speech.speak(text, self.voice)
                    self.msg = "speaking… (v stops)"
                else:
                    self.msg = "nothing to speak"
                continue
            if c == ord("B"):                # add to Safari Reading List
                from . import safari
                title = (page.bundle["doc"].get("title")
                         if page.bundle else None)
                if page.url.startswith(("http://", "https://")):
                    ok = safari.add_reading_list(page.url, title)
                    self.msg = ("added to Safari Reading List" if ok
                                else "couldn't add (check Automation "
                                     "permission: Terminal → Safari)")
                else:
                    self.msg = "not a web page"
                continue

            # --- search ---
            if c == ord("/"):
                q = self._prompt(scr, h, w, "/")
                if q:
                    do_search(q, top + 1)
                continue
            if c == ord("n"):
                repeat_search(True)
                continue
            if c == ord("N"):
                repeat_search(False)
                continue
            if c == ord(":"):
                u = self._prompt(scr, h, w, ":")
                if u.strip():
                    from .search import omnibox
                    return ("go", omnibox(u))
                continue

            # --- block and heading motions ---
            if c == ord("}"):                 # next block (skip to after blank)
                r = top + 1
                while r < len(rows) and rows[r]:
                    r += 1
                while r < len(rows) and not rows[r]:
                    r += 1
                top = clamp(r)
                continue
            if c == ord("{"):                 # previous block start
                r = top - 1
                while r > 0 and not rows[r]:
                    r -= 1
                while r > 0 and rows[r - 1]:
                    r -= 1
                top = clamp(r)
                continue
            if c == ord(")"):                 # next heading
                nxt = next((r for r, s in enumerate(styles)
                            if s == "h" and r > top), None)
                if nxt is not None:
                    top = clamp(nxt)
                else:
                    self.msg = "no next heading"
                continue
            if c == ord("("):                 # previous heading
                prev = [r for r, s in enumerate(styles) if s == "h" and r < top]
                if prev:
                    top = clamp(prev[-1])
                else:
                    self.msg = "no previous heading"
                continue
            if pending == "z":                # z-chord: zt / zz / zb
                pending = None
                r = focus_row(focus)
                if r is not None:
                    if c == ord("t"):
                        top = clamp(r)
                    elif c == ord("z"):
                        top = clamp(r - view_h // 2)
                    elif c == ord("b"):
                        top = clamp(r - view_h + 1)
                continue
            if c == ord("z"):
                pending = "z"
                continue

            # --- scrolling ---
            if c in (ord("j"), curses.KEY_DOWN):
                top = clamp(top + 1)
            elif c in (ord("k"), curses.KEY_UP):
                top = clamp(top - 1)
            elif c in (curses.KEY_NPAGE, 6):             # PgDn / C-f
                top = clamp(top + view_h - 1)
            elif c in (curses.KEY_PPAGE, 2):             # PgUp / C-b
                top = clamp(top - (view_h - 1))
            elif c == 4:                                 # C-d
                top = clamp(top + view_h // 2)
            elif c == 21:                                # C-u
                top = clamp(top - view_h // 2)
            elif c in (curses.KEY_HOME,):
                top = 0
            elif c in (curses.KEY_END,):
                top = clamp(len(rows))
            elif c == ord("G"):
                top = clamp(len(rows))
            elif c == ord("g"):
                if pending == "g":
                    top = 0
                    pending = None
                else:
                    pending = "g"
                    continue
            pending = None

    @staticmethod
    def _read_sgr_mouse(scr):
        """Parse an SGR-1006 mouse report after a lone ESC: ESC [ < b;x;y M|m.
        Returns (button, col, row, is_release) zero-based, or None.

        We speak the mouse protocol ourselves because this Python links
        Apple's ncurses 6.0 (mouse ABI v1): BUTTON5_PRESSED is 0x0 — wheel-
        DOWN literally does not exist as a curses event — and the legacy
        X10 encoding it requests breaks click coordinates past column 223.
        SGR-1006 gives wheel both ways, full-width coordinates, and events
        we can synthesize in tests."""
        seq_ok = False
        scr.nodelay(True)
        try:
            if scr.getch() != ord("["):
                return None
            if scr.getch() != ord("<"):
                return None
            buf = ""
            for _ in range(24):
                ch = scr.getch()
                if ch == -1:
                    return None
                c = chr(ch)
                if c in "Mm":
                    try:
                        b, x, y = (int(v) for v in buf.split(";"))
                    except ValueError:
                        return None
                    return (b, x - 1, y - 1, c == "m")
                buf += c
            return None
        finally:
            scr.nodelay(False)

    @staticmethod
    def _help_overlay(scr, h, w):
        """Full help as a centered overlay, wrapped to <= 80 columns —
        the one-line status cram ran off narrow terminals. Any key closes."""
        width = min(80, max(40, w - 4))
        lines = [l[:width] for l in HELP_LINES][:max(3, h - 2)]
        left = max(0, (w - width) // 2)
        first = max(0, (h - 1 - len(lines)) // 2)
        scr.erase()
        for i, line in enumerate(lines):
            attr = curses.A_BOLD if i == 0 else curses.A_NORMAL
            if line.strip() == "(any key to close)":
                attr = curses.A_DIM
            try:
                scr.addstr(first + i, left, line, attr)
            except curses.error:
                pass
        scr.refresh()
        scr.getch()

    @staticmethod
    def _prompt(scr, h, w, prefix):
        curses.echo()
        curses.curs_set(1)
        try:
            scr.addstr(h - 1, 0, " " * (w - 1))
            scr.addstr(h - 1, 0, prefix)
            scr.refresh()
            s = scr.getstr(h - 1, len(prefix), w - 2)
        except curses.error:
            s = b""
        finally:
            curses.noecho()
            curses.curs_set(0)
        return s.decode("utf-8", "replace") if s else ""


def browse(url: str, private: bool = False, width: int = 0,
           voice: str = None, announce: bool = False) -> None:
    Reader(url, private=private, width=width,
           voice=voice, announce=announce).run()
