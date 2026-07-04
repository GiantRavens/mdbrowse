"""Archive frontend: write full markdown documents (front-matter + body)
to the timestamped archive directory."""

import datetime
import os
import re
from urllib.parse import urlparse

ARCHIVE_DIR = os.path.expanduser(
    os.environ.get("MDBROWSE_ARCHIVE", "~/mdbrowse-archive"))


def slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen].strip("-") or "page"


def save_archive(doc_md: str, title: str, url: str) -> str:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.datetime.now()
    host = urlparse(url).netloc or "local"
    fname = f"{now.strftime('%Y%m%d-%H%M%S')}-{slugify(host + '-' + title)}.md"
    path = os.path.join(ARCHIVE_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc_md)
    return path
