"""RSS/Atom feed mode: when a site publishes a feed, it beats any scrape.

Feeds are XML, and the browser engine would only show us its XML tree
viewer — so this path is static: httpx fetch (same Safari identity),
ElementTree parse, markdown emitted directly in feed shape (one loose
bullet per entry: linked title — date — summary).

Discovery happens in the walker (<link rel=alternate> in the head); the
reader offers F when a page advertises one. feed:URL works anywhere a
URL does.
"""

import html as ihtml
import re
import xml.etree.ElementTree as ET

_ATOM = "{http://www.w3.org/2005/Atom}"


def _text(el) -> str:
    if el is None:
        return ""
    s = "".join(el.itertext())
    s = ihtml.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)          # summaries often carry HTML
    return " ".join(s.split())


def _first(el, *paths):
    for p in paths:
        found = el.find(p)
        if found is not None:
            return found
    return None


def parse(xml_text: str):
    """-> (feed_title, [{title, link, date, summary}, ...]) for RSS or Atom."""
    root = ET.fromstring(xml_text.strip())
    items = []

    if root.tag.endswith("rss") or root.tag == "rdf:RDF" or root.find("channel") is not None:
        channel = root.find("channel")
        if channel is None:
            raise ValueError("no <channel> in RSS document")
        feed_title = _text(channel.find("title")) or "RSS feed"
        for it in channel.findall("item"):
            items.append({
                "title": _text(it.find("title")) or "(untitled)",
                "link": (it.findtext("link") or "").strip(),
                "date": (it.findtext("pubDate") or it.findtext(
                    "{http://purl.org/dc/elements/1.1/}date") or "").strip(),
                "summary": _text(_first(it, "description")),
            })
        return feed_title, items

    if root.tag == f"{_ATOM}feed":
        feed_title = _text(root.find(f"{_ATOM}title")) or "Atom feed"
        for e in root.findall(f"{_ATOM}entry"):
            link = ""
            for l in e.findall(f"{_ATOM}link"):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href") or ""
                    break
            items.append({
                "title": _text(e.find(f"{_ATOM}title")) or "(untitled)",
                "link": link.strip(),
                "date": (e.findtext(f"{_ATOM}updated")
                         or e.findtext(f"{_ATOM}published") or "").strip(),
                "summary": _text(_first(e, f"{_ATOM}summary", f"{_ATOM}content")),
            })
        return feed_title, items

    raise ValueError(f"not an RSS or Atom document (root: {root.tag})")


def _tidy_date(d: str) -> str:
    # ISO timestamps read badly aloud and on screen; keep the date part.
    m = re.match(r"(\d{4}-\d{2}-\d{2})", d)
    if m:
        return m.group(1)
    # RFC822 "Fri, 04 Jul 2026 12:00:00 GMT" -> "Fri, 04 Jul 2026"
    m = re.match(r"([A-Za-z]{3},?\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", d)
    return m.group(1) if m else d[:24]


def to_markdown(feed_title: str, items: list, source_url: str) -> str:
    parts = [f"# {feed_title}"]
    for it in items:
        bits = []
        if it["link"]:
            bits.append(f"[{it['title']}]({it['link']})")
        else:
            bits.append(it["title"])
        if it["date"]:
            bits.append(_tidy_date(it["date"]))
        if it["summary"]:
            s = it["summary"]
            bits.append(s[:240] + ("…" if len(s) > 240 else ""))
        parts.append("- " + " — ".join(bits))
    if len(parts) == 1:
        parts.append("_(feed has no entries)_")
    return "\n\n".join(parts)


def page_markdown(url: str, private: bool = False):
    """Fetch + parse a feed URL -> (title, markdown body)."""
    import httpx
    from . import cookies as safari_cookies
    from .capture import IPHONE_UA
    cookies = None if private else safari_cookies.for_httpx()
    with httpx.Client(follow_redirects=True, timeout=20.0,
                      headers={"User-Agent": IPHONE_UA,
                               "Accept": "application/rss+xml, "
                                         "application/atom+xml, "
                                         "application/xml;q=0.9, */*;q=0.5"},
                      cookies=cookies) as c:
        r = c.get(url)
        r.raise_for_status()
        text = r.text
    title, items = parse(text)
    return title, to_markdown(title, items, url)
