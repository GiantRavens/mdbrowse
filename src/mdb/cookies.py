"""Safari cookie jar -> Playwright cookies. Browse as yourself by default.

Port of the proven binarycookies parser from legacy mdbrowse.py: the page
table is big-endian, cookie records inside each page are little-endian.
"""

import os
import struct
import sys
import time

_COOKIE_PATHS = (
    "~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
    "~/Library/Cookies/Cookies.binarycookies",
)
_MAC_EPOCH_OFFSET = 978307200  # seconds between 1970-01-01 and 2001-01-01
_cache = None


def _path():
    for p in _COOKIE_PATHS:
        full = os.path.expanduser(p)
        if os.path.isfile(full):
            return full
    return None


def _parse(path: str):
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


def load():
    """All non-expired Safari cookies, parsed once per process. [] if unreadable."""
    global _cache
    if _cache is not None:
        return _cache
    path = _path()
    if not path:
        _cache = []
        return _cache
    try:
        cookies = _parse(path)
    except (PermissionError, OSError):
        print("mdb: can't read Safari cookies (grant Full Disk Access, or use "
              "--private). Continuing without cookies.", file=sys.stderr)
        cookies = []
    now = time.time()
    _cache = [c for c in cookies if not c["expires"] or c["expires"] > now]
    return _cache


def for_playwright(cookies=None):
    """Shape parsed cookies for Playwright's context.add_cookies()."""
    out = []
    for c in (cookies if cookies is not None else load()):
        out.append({
            "name": c["name"], "value": c["value"], "domain": c["domain"],
            "path": c["path"], "secure": c["secure"], "httpOnly": c["httponly"],
            "expires": int(c["expires"]) if c["expires"] else -1,
        })
    return out
