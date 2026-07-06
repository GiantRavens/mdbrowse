"""Reddit fast path: the `.json` endpoint as a browser-free capture.

Reddit serves clean structured JSON for any listing or post when you
append `.json` — faster than rendering the SPA, complete (all posts /
the full comment tree), and free of chrome. We build a capture bundle
from it directly, so classify / emit / the reader consume it exactly
like a rendered page: a subreddit becomes a feed, a post becomes an
article with its comments as a nested list.

Requires the user's cookies (reddit 403s the .json to a cold client).
When they're absent — private mode, or a host with no Safari jar — this
returns None and the caller falls back to old.reddit.com HTML through
the normal pipeline (policy.rewrite_url). old.reddit is near-static
markup that our extractor already handles well, so reddit stays covered
either way; .json is the upgrade when we can authenticate.
"""

import datetime
import re
from urllib.parse import urlparse, urlunparse

from . import EXTRACTOR_VERSION

REDDIT_HOSTS = ("reddit.com", "www.reddit.com", "old.reddit.com",
                "np.reddit.com", "i.reddit.com", "m.reddit.com")


def is_reddit(host: str) -> bool:
    host = (host or "").lower()
    return host == "reddit.com" or host.endswith(".reddit.com")


def _json_url(url: str) -> str:
    p = urlparse(url)
    path = p.path
    if path.endswith("/.json") or path.endswith(".json"):
        return url
    path = (path.rstrip("/") or "") + "/.json"
    # Drop tracking query params; keep none — .json takes its own.
    return urlunparse(p._replace(netloc="www.reddit.com", path=path, query=""))


def _fmt_count(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def _abs(permalink: str) -> str:
    return "https://www.reddit.com" + permalink if permalink.startswith("/") \
        else permalink


def _post_row(d: dict) -> dict:
    """One listing post as a feed row: title (linking to its comments),
    the external domain when it's a link post, then the counts and
    subreddit/author as plain text. Only per-post-UNIQUE links appear —
    the comment permalink and the external URL. The subreddit link is
    deliberately NOT emitted: it is identical on every row of a
    subreddit, and the unit detector's shared-link-target pass (built to
    merge fragments of one card) would glue all posts into a single
    item. Title + comments keep the row link-led → a real feed item."""
    title = (d.get("title") or "").strip()
    permalink = _abs(d.get("permalink") or "")
    ext = d.get("url") or ""
    sub = d.get("subreddit", "")
    author = d.get("author", "")
    is_self = d.get("is_self") or (ext and "reddit.com" in ext)
    comments_l = f"[{_fmt_count(d.get('num_comments'))} comments]({permalink})"
    author_href = f"https://www.reddit.com/user/{author}"
    md = f"[{title}]({permalink})"
    links = [{"text": title, "href": permalink},
             {"text": f"{_fmt_count(d.get('num_comments'))} comments",
              "href": permalink}]
    if not is_self and ext.startswith("http"):
        dom = d.get("domain", "")
        md += f" ([{dom}]({ext}))"
        links.append({"text": dom, "href": ext})
    # Author IS linked (its href varies per post, so consecutive rows
    # don't share a target and the unit detector leaves them separate);
    # subreddit stays plain text (constant across a listing → would
    # merge). Together they keep the row link-led → a real feed item.
    md += (f" — {_fmt_count(d.get('score'))} points · {comments_l} · "
           f"r/{sub} · [u/{author}]({author_href})")
    links.append({"text": f"u/{author}", "href": author_href})
    return {"kind": "row", "landmark": "main", "md": md,
            "links": links, "images": []}


def _comment_blocks(children: list, depth: int, out: list, cap: int) -> None:
    for c in children:
        if len(out) >= cap or c.get("kind") != "t1":
            continue
        d = c.get("data") or {}
        body = (d.get("body") or "").strip()
        if not body:
            continue
        body = re.sub(r"\s+", " ", body)
        author = d.get("author", "")
        score = _fmt_count(d.get("score"))
        out.append({"kind": "li", "depth": min(depth, 6), "landmark": "main",
                    "md": f"**u/{author}** ({score}): {body}",
                    "links": [], "images": []})
        replies = d.get("replies")
        if isinstance(replies, dict):
            kids = (replies.get("data") or {}).get("children") or []
            _comment_blocks(kids, depth + 1, out, cap)


def _bundle(url: str, title: str, blocks: list) -> dict:
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "meta": {"requested_url": url, "url": url, "fetched_at": now,
                 "mode": "authenticated", "extractor": EXTRACTOR_VERSION,
                 "elapsed_ms": 0, "source": "reddit-json"},
        "doc": {"url": url, "title": title, "lang": "en", "feeds": [],
                "description": "", "viewport": [980, 1200], "docHeight": 0,
                "interactive": 0, "anchors": len(blocks), "textLen": 0,
                "iframes": [], "challenge": "", "blocks": blocks},
    }


def json_bundle(url: str, private: bool = False):
    """Capture bundle from reddit's .json, or None to fall back to HTML.
    None when: private (no cookies to send), the fetch fails/403s, or
    the payload isn't the JSON shape we understand."""
    if private:
        return None
    import httpx
    from .capture import DESKTOP_UA
    from . import cookies as safari_cookies
    try:
        ck = safari_cookies.for_httpx()
    except Exception:
        ck = None
    if not ck:
        return None
    try:
        r = httpx.get(_json_url(url), follow_redirects=True, timeout=12,
                      headers={"User-Agent": DESKTOP_UA,
                               "Accept": "application/json"}, cookies=ck)
        if r.status_code != 200 or \
                not r.headers.get("content-type", "").startswith("application/json"):
            return None
        data = r.json()
    except Exception:
        return None

    # Post page: [post-listing, comments-listing]. Listing: one Listing.
    if isinstance(data, list) and len(data) == 2:
        posts = (data[0].get("data") or {}).get("children") or []
        if not posts:
            return None
        p = posts[0].get("data") or {}
        title = (p.get("title") or "reddit post").strip()
        blocks = [{"kind": "heading", "level": 1, "landmark": "main",
                   "md": title, "links": [], "images": []}]
        sub = f"r/{p.get('subreddit','')} · u/{p.get('author','')} · " \
              f"{_fmt_count(p.get('score'))} points · " \
              f"{_fmt_count(p.get('num_comments'))} comments"
        blocks.append({"kind": "p", "landmark": "main", "md": f"_{sub}_",
                       "links": [], "images": []})
        selftext = (p.get("selftext") or "").strip()
        if selftext:
            for para in re.split(r"\n\s*\n", selftext):
                para = re.sub(r"\s+", " ", para).strip()
                if para:
                    blocks.append({"kind": "p", "landmark": "main", "md": para,
                                   "links": [], "images": []})
        elif p.get("url", "").startswith("http") and not p.get("is_self"):
            blocks.append({"kind": "p", "landmark": "main",
                           "md": f"Link: [{p.get('domain','')}]({p['url']})",
                           "links": [{"text": p.get("domain", "link"),
                                      "href": p["url"]}], "images": []})
        comments = (data[1].get("data") or {}).get("children") or []
        cblocks = []
        _comment_blocks(comments, 0, cblocks, cap=200)
        if cblocks:
            blocks.append({"kind": "heading", "level": 2, "landmark": "main",
                           "md": "Comments", "links": [], "images": []})
            blocks += cblocks
        return _bundle(_abs(p.get("permalink") or url), title, blocks)

    # Listing (subreddit / front / user).
    if isinstance(data, dict) and data.get("kind") == "Listing":
        children = (data.get("data") or {}).get("children") or []
        rows = [_post_row(c["data"]) for c in children if c.get("kind") == "t3"]
        if not rows:
            return None
        host = urlparse(url).path.strip("/") or "reddit"
        title = f"reddit — {host}"
        return _bundle(url, title, rows)

    return None
