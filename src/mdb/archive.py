"""Archive store: timestamped markdown documents (front-matter + body)
plus search over them — the archive is a personal web memory, not a
write-only bucket.

Search is a term-AND scan of every file, newest first: honest and
index-free at the archive's current size. Graduation trigger: when a
search visibly lags (thousands of documents), promote to a real FTS
index — the kf/df pattern — rather than tuning the scan."""

import datetime
import os
import re
from urllib.parse import urlparse

from .paths import data_path

ARCHIVE_DIR = data_path("archive", "MDBROWSE_ARCHIVE")

_FM = re.compile(r"(?s)^---\n(.*?)\n---\n")


def _front_matter(text: str):
    """Split a document into (meta dict, body). Tolerant line parser —
    our own emitter wrote these files, so keys are simple scalars."""
    m = _FM.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).split("\n"):
        k, sep, v = line.partition(":")
        if sep:
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end():]


def search_archive(query: str, max_results: int = 10) -> list:
    """Term-AND full-text search over archived pages. Returns hits
    newest-first-then-by-score: {path, title, source, retrieved,
    score, snippet}. Score = term frequency, title hits weighted."""
    terms = [t.lower() for t in query.split() if t]
    if not terms or not os.path.isdir(ARCHIVE_DIR):
        return []
    hits = []
    for fname in sorted(os.listdir(ARCHIVE_DIR), reverse=True):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(ARCHIVE_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        low = text.lower()
        if not all(t in low for t in terms):
            continue
        meta, body = _front_matter(text)
        title = meta.get("title", fname)
        score = sum(low.count(t) for t in terms)
        score += sum(5 for t in terms if t in title.lower())
        i = body.lower().find(terms[0])
        snippet = ""
        if i >= 0:
            start = body.rfind("\n", 0, i) + 1
            end = body.find("\n", i)
            snippet = body[start:end if end > 0 else len(body)][:240]
        hits.append({"path": path, "title": title,
                     "source": meta.get("source", ""),
                     "retrieved": meta.get("retrieved", ""),
                     "score": score, "snippet": snippet})
    hits.sort(key=lambda h: -h["score"])
    return hits[:max_results]


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
