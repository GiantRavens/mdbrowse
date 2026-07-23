"""Human-directed page exports.

Unlike the MCP archive (a searchable application-data store), an explicit
reader/CLI save is a visible research artifact. It defaults to Safari's
download folder and accepts an exact destination from the user.
"""

from __future__ import annotations

import datetime
import os
from urllib.parse import urlparse

from .archive import slugify
from .paths import downloads_dir


SAVE_DIR = downloads_dir()


def _dedupe(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    number = 1
    while os.path.exists(f"{base}-{number}{ext}"):
        number += 1
    return f"{base}-{number}{ext}"


def suggested_page_path(title: str, url: str, dest_dir: str = None,
                        now: datetime.datetime = None) -> str:
    """Return a meaningful, collision-independent default export path."""
    now = now or datetime.datetime.now()
    host = urlparse(url).netloc or "local"
    name = f"{now:%Y%m%d}-{slugify(host + '-' + title)}.md"
    return os.path.join(os.path.expanduser(dest_dir or SAVE_DIR), name)


def save_page(doc_md: str, title: str, url: str,
              destination: str = None) -> str:
    default = suggested_page_path(title, url)
    path = os.path.expanduser(destination.strip()) if destination else default
    if os.path.isdir(path) or path.endswith(os.sep):
        path = os.path.join(path, os.path.basename(default))
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    path = _dedupe(path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(doc_md)
    return path
