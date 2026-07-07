"""X (Twitter) fast path: the syndication endpoint as a browser-free capture.

X status pages render as a lazily-hydrated SPA where engagement counts are
conveyed by SVG icons (which the walker strips) and the DOM differs per load
— so the generic path yields bare "17K / 131K / 307K" with no labels and no
determinism. X's own public embed API, `cdn.syndication.twimg.com`, serves the
same tweet as clean, labeled, deterministic JSON with no login — the exact
analogue of reddit's `.json` fast path. We build a capture bundle from it so
classify / emit / the reader consume a status page like any rendered article.

Scope: single status pages only (`/<user>/status/<id>`). Profiles, search,
home, and other X surfaces return None and fall through to the walker (which
renders them acceptably, and whose nav harvest gives them a usable menu).
Deleted/protected tweets return an HTML tombstone (not JSON) → None → walker.

Full design: docs/x-adapter.md.
"""

import datetime
import re
from urllib.parse import urlparse

from . import EXTRACTOR_VERSION

# The token query param is required by the endpoint but its value is not
# validated (any short string returns the same payload — verified across
# ancient and modern ids); a fixed sentinel keeps the request deterministic.
_SYND = "https://cdn.syndication.twimg.com/tweet-result?id={id}&token=a"
_X_HOSTS = ("x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com")
_STATUS_RE = re.compile(r"/(?:[^/]+/status(?:es)?|i/web/status)/(\d+)")


def is_x_status(url: str) -> str | None:
    """The numeric tweet id for an X status URL, else None (non-status X
    surfaces and non-X hosts both fall through to the walker)."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if not (host in _X_HOSTS or host.endswith(".x.com")
            or host.endswith(".twitter.com")):
        return None
    m = _STATUS_RE.search(p.path)
    return m.group(1) if m else None


def _date(iso: str) -> str:
    """'2026-07-06T21:01:20.000Z' -> 'Jul 6, 2026'."""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return f"{dt:%b} {dt.day}, {dt.year}"
    except (ValueError, TypeError):
        return ""


def _esc(s: str) -> str:
    """Escape the markdown metacharacters that would corrupt a link or
    emphasis; tweet prose is otherwise passed through verbatim."""
    return re.sub(r"([\\`*_\[\]])", r"\\\1", s)


def _linkify(text: str, entities: dict) -> str:
    """Tweet text -> markdown: expand t.co short links to their destination,
    then link @mentions and #hashtags. Escapes first so a stray * or _ in
    the prose can't leak emphasis, and mention/hashtag insertion runs on the
    escaped string (the inserted [..](..) syntax is the only markup)."""
    out = _esc(text or "")
    for u in (entities or {}).get("urls") or []:
        short = _esc(u.get("url") or "")
        disp = _esc(u.get("display_url") or u.get("expanded_url") or "")
        dest = u.get("expanded_url") or u.get("url") or ""
        if short and dest:
            out = out.replace(short, f"[{disp}]({dest})")
    # A trailing bare t.co (the media permalink Twitter appends) adds noise
    # once the photo is rendered inline — drop a lone one at the very end.
    out = re.sub(r"\s*https://t\.co/\w+\s*$", "", out)
    out = re.sub(r"@(\w{1,15})\b",
                 lambda m: f"[@{m.group(1)}](https://x.com/{m.group(1)})", out)
    out = re.sub(r"(?<!\w)#(\w+)",
                 lambda m: f"[#{m.group(1)}](https://x.com/hashtag/{m.group(1)})",
                 out)
    return out.strip()


def _counts_line(d: dict) -> str:
    """The engagement bar as ONE labeled line — the whole point of the
    adapter. Only the metrics the payload actually carries (replies via
    conversation_count, likes via favorite_count) appear; a missing metric
    is omitted, never faked as 0 (retweet/quote/bookmark aren't in the
    syndication payload)."""
    parts = []
    reps = d.get("conversation_count")
    likes = d.get("favorite_count")
    if isinstance(reps, int):
        parts.append(f"Replies {reps:,}")
    if isinstance(likes, int):
        parts.append(f"Likes {likes:,}")
    return " · ".join(parts)


def _photos(d: dict) -> list:
    """Image URLs from the tweet, preferring the richer mediaDetails
    (covers video posters) and falling back to the photos array."""
    urls = []
    for m in d.get("mediaDetails") or []:
        u = m.get("media_url_https") or m.get("media_url")
        if u:
            urls.append(u)
    if not urls:
        for ph in d.get("photos") or []:
            u = ph.get("url")
            if u:
                urls.append(u)
    return urls


def _blocks(d: dict) -> list:
    user = d.get("user") or {}
    name = (user.get("name") or "").strip()
    handle = (user.get("screen_name") or "").strip()
    head = f"{_esc(name)} (@{handle})" if name else f"@{handle}"
    blocks = [{"kind": "heading", "level": 1, "landmark": "main",
               "md": head, "links": [], "images": []}]

    meta_bits = [b for b in (_date(d.get("created_at") or ""), "X") if b]
    if meta_bits:
        blocks.append({"kind": "p", "landmark": "main",
                       "md": f"_{' · '.join(meta_bits)}_",
                       "links": [], "images": []})

    body = _linkify(d.get("text") or "", d.get("entities") or {})
    if body:
        blocks.append({"kind": "p", "landmark": "main", "md": body,
                       "links": [], "images": []})

    for src in _photos(d):
        blocks.append({"kind": "img", "landmark": "main", "md": "",
                       "src": src, "alt": "", "links": [], "images": [src]})

    counts = _counts_line(d)
    if counts:
        blocks.append({"kind": "p", "landmark": "main", "md": f"_{counts}_",
                       "links": [], "images": []})

    q = d.get("quoted_tweet")
    if isinstance(q, dict):
        qu = q.get("user") or {}
        qh = (qu.get("screen_name") or "").strip()
        qtext = _linkify(q.get("text") or "", q.get("entities") or {})
        qmd = f"**@{qh}**: {qtext}" if qh else qtext
        if qmd.strip():
            blocks.append({"kind": "quote", "landmark": "main", "md": qmd,
                           "links": [], "images": []})
    return blocks


def _bundle(url: str, d: dict) -> dict:
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    user = d.get("user") or {}
    handle = user.get("screen_name") or "x"
    text = re.sub(r"\s+", " ", (d.get("text") or "")).strip()
    title = f"{user.get('name') or handle} on X: “{text[:80]}”" if text \
        else f"@{handle} on X"
    blocks = _blocks(d)
    return {
        "meta": {"requested_url": url, "url": url, "fetched_at": now,
                 "mode": "authenticated", "extractor": EXTRACTOR_VERSION,
                 "elapsed_ms": 0, "source": "x-syndication"},
        "doc": {"url": url, "title": title, "lang": d.get("lang") or "en",
                "feeds": [], "description": text[:200], "viewport": [980, 1200],
                "docHeight": 0, "interactive": 0, "anchors": len(blocks),
                "textLen": len(text), "iframes": [], "challenge": "",
                "blocks": blocks},
    }


def x_bundle(url: str, tweet_id: str, private: bool = False):
    """Capture bundle from X's syndication JSON, or None to fall back to the
    walker. None when the fetch fails, the tweet is gone (an HTML tombstone,
    not JSON), or the payload isn't the Tweet shape we understand. The API is
    public and cookieless, so this works in --private mode too (it sends no
    identity), which is strictly better than the SPA for a private user."""
    import httpx
    from .capture import DESKTOP_UA
    try:
        r = httpx.get(_SYND.format(id=tweet_id), follow_redirects=True,
                      timeout=12, headers={"User-Agent": DESKTOP_UA,
                                           "Accept": "application/json"})
        if r.status_code != 200 or not r.headers.get(
                "content-type", "").startswith("application/json"):
            return None
        d = r.json()
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("__typename") != "Tweet" \
            or not d.get("text") and not d.get("mediaDetails"):
        return None
    return _bundle(url, d)
