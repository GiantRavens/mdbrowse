"""Repeated-unit detector: turn runs of feed/grid fragments into items.

Content items on index pages arrive as runs of structurally near-identical
fragments — HN's (title row, subtext row) pairs, CNN's (kicker, headline)
card fragments. This module groups fragments into units using two
vocabulary-free signals, then renders one line per unit:

  1. **Shared link target** — fragments of one card point at the same story
     (CNN kicker + headline + deck). Applied first, in document order.
  2. **Signature periodicity** — within a run, block signatures
     (kind, link count) form classes; the class whose links carry the
     longest text is the *starter* (titles), and units of any other class
     attach to the preceding starter (HN subtext rows). Guarded: needs >= 2
     classes, >= 3 starters, real title-length links, and at most one
     attachment per class per unit (so a trailing footer row starts its own
     unit instead of gluing onto the last story).
"""

from statistics import median

from .classify import is_link_led, visible_len

ITEMISH_KINDS = ("p", "li", "row", "img")
MIN_RUN = 3          # fewer itemish blocks than this: not repetition, no merging
MIN_STARTERS = 3     # a starter class must repeat to be believed
MIN_TITLE_LEN = 20   # median link length that separates titles from metadata


def _hrefs(b: dict) -> set:
    return {l["href"] for l in (b.get("links") or [])}


def _maxlink(b: dict) -> int:
    return max((len(l["text"]) for l in (b.get("links") or [])), default=0)


def _cls(b: dict):
    """Structural signature: kind + bucketed link count (5+ links reads the
    same as 4 — a link-farm row is a link-farm row)."""
    return (b.get("kind"), min(len(b.get("links") or []), 4))


def is_boundary(b: dict) -> bool:
    """A short, linkless paragraph inside a feed is a section label
    ('Taylor Swift', 'STREAMING NOW'), not content: it bounds runs and
    renders as a pseudo-heading."""
    return (b.get("kind") == "p" and not b.get("links")
            and 0 < visible_len(b.get("md", "")) < 60)


def is_prose(b: dict) -> bool:
    return (b.get("kind") == "p" and visible_len(b.get("md", "")) >= 120
            and not is_link_led(b))


def _standalone_image(b: dict) -> bool:
    """A bare image block carrying a real picture — a hero / showcase
    shot, not a card thumbnail. Card thumbnails ride INSIDE p/li/row
    blocks as inline markdown; a kind=='img' block is a picture standing
    on its own. On a feed these are content (apple.com's product heroes
    vanished when the unit detector swallowed them as 'thumbnails')."""
    return b.get("kind") == "img" and bool(b.get("src"))


def segment(blocks: list):
    """Split a block stream into ('run', [...]) itemish runs and
    ('block', b) passthroughs (headings, prose, boundaries, code,
    standalone images...)."""
    run = []
    for b in blocks:
        if (b.get("kind") in ITEMISH_KINDS and not is_boundary(b)
                and not is_prose(b) and not _standalone_image(b)):
            run.append(b)
        else:
            if run:
                yield ("run", run)
                run = []
            yield ("block", b)
    if run:
        yield ("run", run)


def detect_units(run: list) -> list:
    """Group a run's blocks into units (lists of blocks)."""
    # Pass 1: shared link target joins consecutive fragments of one card.
    units = []
    for b in run:
        if units and _hrefs(b) & set().union(*(_hrefs(x) for x in units[-1])):
            units[-1].append(b)
        else:
            units.append([b])

    # Pass 2: periodicity. Classify each unit by its first block's signature;
    # the class with the longest link text, repeated enough, is the starter.
    counts = {}
    for u in units:
        counts.setdefault(_cls(u[0]), []).append(_maxlink(u[0]))
    if len(counts) < 2:
        return units
    eligible = {c: median(v) for c, v in counts.items()
                if len(v) >= MIN_STARTERS}
    if not eligible:
        return units
    starter = max(eligible, key=lambda c: eligible[c])
    if eligible[starter] < MIN_TITLE_LEN:
        return units

    def starterish(b):
        # Starter-ness is a property of the block, not just its class: an
        # item whose signature deviates (HN's site-link-less "Ask HN" rows)
        # still reads as a title when it carries a title-length link.
        return _cls(b) == starter or _maxlink(b) >= MIN_TITLE_LEN

    # An attachment class must itself RECUR — that's what makes it part of
    # the repeating unit. One-off fragments (a "More" pagination link, a
    # trailing footer bar) are not periodic and stand alone.
    attachable = {c for c, v in counts.items()
                  if c != starter and len(v) >= MIN_STARTERS}

    merged, attached = [], []
    for u in units:
        first = u[0]
        if (merged and _cls(first) in attachable and not starterish(first)
                and starterish(merged[-1][0])
                and _cls(first) not in attached[-1]):
            merged[-1].extend(u)
            attached[-1].add(_cls(first))
        else:
            merged.append(list(u))
            attached.append(set())
    return merged


def unit_markdown(unit: list):
    """One line per unit: the title fragment (longest link) leads; other
    fragments follow in document order, with links that repeat the title's
    target reduced to their text (no URL echo). Bare thumbnails are dropped —
    a feed line is a navigation surface. None if nothing text-y survives."""
    texts = [b for b in unit if b.get("kind") != "img" and b.get("md")]
    if not texts:
        return None
    # The title leads the line. Longest link wins only when it's actually
    # title-length; otherwise document order stands (a short title like
    # "Holes" must not lose the lead to a longer username in its metadata).
    linked = [b for b in texts if b.get("links")]
    title = max(linked, key=_maxlink) if linked else texts[0]
    if linked and _maxlink(title) < MIN_TITLE_LEN:
        title = linked[0]
    t_hrefs = _hrefs(title)
    parts = [title["md"]]
    for b in texts:
        if b is title:
            continue
        md = b["md"]
        for l in b.get("links") or []:
            if l["href"] in t_hrefs:
                md = md.replace(f"[{l['text']}]({l['href']})", l["text"])
        md = md.strip()
        if md:
            parts.append(md)
    return "- " + " — ".join(parts)
