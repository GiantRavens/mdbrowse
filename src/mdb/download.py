"""Authenticated file downloads: fetch like Safari would, name sensibly.

Shared by the reader's `d` key and the `mdb get` CLI. Session cookies,
Safari UA, and Referer ride along — the same identity the rest of the
tool presents, so hotlink-protected and login-gated files come through.
"""

import mimetypes
import os
import re
import sys
from urllib.parse import unquote, urlparse

from . import cookies as safari_cookies
from .capture import IPHONE_UA

DOWNLOAD_DIR = os.path.expanduser(
    os.environ.get("MDBROWSE_DOWNLOADS", "~/Downloads"))

# mimetypes.guess_extension has unhelpful favorites (.jpe, .htm)
_EXT_OVERRIDES = {"image/jpeg": ".jpg", "text/html": ".html",
                  "image/svg+xml": ".svg", "text/plain": ".txt"}


def _filename(final_url: str, content_disposition: str, content_type: str) -> str:
    if content_disposition:
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", content_disposition)
        if m:
            name = os.path.basename(unquote(m.group(1)).strip())
            if name:
                return name
    name = os.path.basename(unquote(urlparse(final_url).path)).strip()
    if not name:
        name = (urlparse(final_url).hostname or "download").replace(".", "-")
    if not os.path.splitext(name)[1]:
        ct = (content_type or "").split(";")[0].strip().lower()
        ext = _EXT_OVERRIDES.get(ct) or mimetypes.guess_extension(ct or "") or ""
        name += ext
    # keep it filesystem-friendly
    return re.sub(r"[^\w.\-()+ ]+", "-", name)[:120] or "download"


def _dedupe(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{base}-{n}{ext}"):
        n += 1
    return f"{base}-{n}{ext}"


def download(url: str, private: bool = False, referer: str = None,
             dest_dir: str = None):
    """Fetch a URL to disk. Returns (path, size_bytes)."""
    import httpx
    headers = {"User-Agent": IPHONE_UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    cookies = None if private else safari_cookies.for_httpx()
    with httpx.Client(follow_redirects=True, timeout=120.0,
                      headers=headers, cookies=cookies) as c:
        r = c.get(url)
        r.raise_for_status()
        data = r.content
        name = _filename(str(r.url), r.headers.get("content-disposition", ""),
                         r.headers.get("content-type", ""))
    dest_dir = os.path.expanduser(dest_dir) if dest_dir else DOWNLOAD_DIR
    os.makedirs(dest_dir, exist_ok=True)
    path = _dedupe(os.path.join(dest_dir, name))
    with open(path, "wb") as f:
        f.write(data)
    return path, len(data)


def get_cli(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="mdb get",
        description="Download a file through your Safari session "
                    f"(to {DOWNLOAD_DIR}, or --out DIR).")
    ap.add_argument("url")
    ap.add_argument("--out", default=None, help="destination directory")
    ap.add_argument("--private", action="store_true",
                    help="no cookies (anonymous fetch)")
    ap.add_argument("--referer", default=None)
    a = ap.parse_args(argv)
    url = a.url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    try:
        path, size = download(url, private=a.private, referer=a.referer,
                              dest_dir=a.out)
    except Exception as e:
        print(f"mdb get: {e}", file=sys.stderr)
        return 1
    print(f"{path}  ({size / 1024:.0f} KB)")
    return 0
